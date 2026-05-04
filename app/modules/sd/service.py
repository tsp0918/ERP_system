"""SD service - business rules for the Order-to-Cash flow."""
from decimal import Decimal
from typing import List

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.numbering import next_number
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.sd import models, schemas
from app.shared.base_models import DocStatus
from app.shared.base_repository import BaseRepository


class SalesOrderService:
    """Order creation + GTS export check."""

    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        payload: schemas.SalesOrderCreate,
        client_id: str,
        user_email: str,
    ) -> models.SalesOrder:
        # Validate customer exists and has CUSTOMER role
        customer = self.db.query(BusinessPartner).filter(
            BusinessPartner.bp_code == payload.customer_code,
            BusinessPartner.client_id == client_id,
        ).first()
        if not customer:
            raise NotFoundError("Customer (BusinessPartner)", payload.customer_code)
        if not customer.has_role("CUSTOMER"):
            raise BusinessRuleError(
                f"BP {customer.bp_code} does not have CUSTOMER role"
            )
        if customer.is_denied_party:
            raise BusinessRuleError(
                f"Customer {customer.bp_code} is flagged as denied party"
            )

        # Build header
        so_number = next_number(self.db, client_id, "SALES_ORDER")
        so = models.SalesOrder(
            client_id=client_id,
            document_number=so_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            sales_org_code=payload.sales_org_code,
            customer_code=payload.customer_code,
            customer_po_number=payload.customer_po_number,
            requested_delivery_date=payload.requested_delivery_date,
            incoterms=payload.incoterms,
            payment_terms=payload.payment_terms or customer.payment_terms,
            currency=payload.currency,
            created_by=user_email,
            updated_by=user_email,
            export_check_status="PENDING",
        )

        # Build items, validate materials exist
        total = Decimal("0")
        for idx, item_in in enumerate(payload.items, start=1):
            material = self.db.query(Material).filter(
                Material.material_code == item_in.material_code,
                Material.client_id == client_id,
            ).first()
            if not material:
                raise NotFoundError("Material", item_in.material_code)

            net_amount = (item_in.quantity * item_in.unit_price).quantize(Decimal("0.01"))
            so.items.append(models.SalesOrderItem(
                item_no=idx * 10,
                material_code=item_in.material_code,
                description=item_in.description or material.description,
                quantity=item_in.quantity,
                unit=item_in.unit,
                unit_price=item_in.unit_price,
                net_amount=net_amount,
                plant_code=item_in.plant_code,
                created_by=user_email,
                updated_by=user_email,
            ))
            total += net_amount

        so.total_amount = total
        self.db.add(so)
        self.db.flush()

        # Run transaction review via AI_TradeManagement (unless skipped)
        if not payload.skip_export_check:
            from app.modules.gts.service import GTSService
            try:
                _link, result = GTSService(self.db).transaction_review(so, customer)
                # Keep export_check_status in sync for backward compatibility
                if result.judgment == "APPROVED":
                    so.export_check_status = "PASSED"
                    so.export_check_ref = result.review_id
                elif result.judgment == "REJECTED":
                    so.export_check_status = "BLOCKED"
                    so.export_check_message = result.message
                else:  # NEEDS_REVIEW / PENDING
                    so.export_check_status = "PENDING"
                    so.export_check_message = result.message
            except Exception as exc:
                so.export_check_status = "ERROR"
                so.export_check_message = f"Integration error: {exc}"

        # Block on REJECTED or ERROR; NEEDS_REVIEW also blocks pending manual approval
        if so.export_check_status in ("BLOCKED", "ERROR") or (
            so.export_check_status == "PENDING"
            and not payload.skip_export_check
        ):
            so.status = DocStatus.BLOCKED

        return so

    def release(self, so_id: int, client_id: str, user_email: str) -> models.SalesOrder:
        so = self._get_or_404(so_id, client_id)
        if so.status == DocStatus.BLOCKED:
            raise BusinessRuleError(
                f"SO {so.document_number} is BLOCKED (export check). "
                "Resolve compliance issue or override before release."
            )
        if so.status not in {DocStatus.OPEN, DocStatus.DRAFT}:
            raise BusinessRuleError(f"SO is in status {so.status}, cannot release")
        so.status = DocStatus.RELEASED
        so.updated_by = user_email
        return so

    def _get_or_404(self, so_id: int, client_id: str) -> models.SalesOrder:
        so = BaseRepository(models.SalesOrder, self.db).get(so_id, client_id)
        if not so:
            raise NotFoundError("SalesOrder", so_id)
        return so


class DeliveryService:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        payload: schemas.DeliveryCreate,
        client_id: str,
        user_email: str,
    ) -> models.Delivery:
        so = BaseRepository(models.SalesOrder, self.db).get(payload.sales_order_id, client_id)
        if not so:
            raise NotFoundError("SalesOrder", payload.sales_order_id)
        if so.status not in {DocStatus.OPEN, DocStatus.RELEASED}:
            raise BusinessRuleError(
                f"SO {so.document_number} status {so.status} - delivery not allowed"
            )

        delivery_number = next_number(self.db, client_id, "DELIVERY")
        delivery = models.Delivery(
            client_id=client_id,
            document_number=delivery_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            reference=so.document_number,
            sales_order_id=so.id,
            plant_code=payload.plant_code,
            actual_delivery_date=payload.actual_delivery_date,
            created_by=user_email,
            updated_by=user_email,
        )

        # Default: deliver all SO items in full
        if not payload.items:
            for so_item in so.items:
                delivery.items.append(models.DeliveryItem(
                    so_item_id=so_item.id,
                    item_no=so_item.item_no,
                    material_code=so_item.material_code,
                    quantity=so_item.quantity,
                    unit=so_item.unit,
                    created_by=user_email,
                    updated_by=user_email,
                ))
        else:
            so_item_map = {it.id: it for it in so.items}
            for idx, di in enumerate(payload.items, start=1):
                src = so_item_map.get(di.so_item_id)
                if not src:
                    raise BusinessRuleError(
                        f"SO item id {di.so_item_id} not on SO {so.document_number}"
                    )
                delivery.items.append(models.DeliveryItem(
                    so_item_id=src.id,
                    item_no=src.item_no,
                    material_code=src.material_code,
                    quantity=di.quantity,
                    unit=src.unit,
                    created_by=user_email,
                    updated_by=user_email,
                ))

        self.db.add(delivery)
        self.db.flush()

        # Shipment re-screening via AI_TradeManagement
        self._run_shipment_rescreen(delivery, so)

        return delivery

    def _run_shipment_rescreen(self, delivery: models.Delivery, so: models.SalesOrder) -> None:
        """Call AI_TM shipment/rescreen using the SO's transaction review_id."""
        from app.modules.gts.models import AITMTransactionLink
        from app.modules.gts.service import GTSService

        tx_link = (
            self.db.query(AITMTransactionLink)
            .filter(AITMTransactionLink.sales_order_id == so.id)
            .order_by(AITMTransactionLink.created_at.desc())
            .first()
        )
        if not tx_link or not tx_link.review_id:
            # No transaction review on record (legacy SO) — skip rescreen
            return

        try:
            ship_link = GTSService(self.db).shipment_rescreen(delivery, tx_link.review_id)
            if not ship_link.shipment_ok:
                delivery.status = DocStatus.BLOCKED
        except Exception as exc:
            # Spec: if AI_TM is unreachable, keep delivery blocked
            delivery.status = DocStatus.BLOCKED
            import logging
            logging.getLogger(__name__).warning(
                "Shipment rescreen failed for DEL=%s: %s", delivery.document_number, exc
            )


class BillingService:
    def __init__(self, db: Session):
        self.db = db

    def create_from_delivery(
        self,
        payload: schemas.BillingCreate,
        client_id: str,
        user_email: str,
    ) -> models.BillingDocument:
        delivery = BaseRepository(models.Delivery, self.db).get(payload.delivery_id, client_id)
        if not delivery:
            raise NotFoundError("Delivery", payload.delivery_id)

        so = self.db.get(models.SalesOrder, delivery.sales_order_id)
        if not so:
            raise BusinessRuleError("Source sales order missing")

        billing_number = next_number(self.db, client_id, "BILLING")
        bill = models.BillingDocument(
            client_id=client_id,
            document_number=billing_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            reference=delivery.document_number,
            sales_order_id=so.id,
            delivery_id=delivery.id,
            customer_code=so.customer_code,
            currency=so.currency,
            payment_terms=payload.payment_terms or so.payment_terms,
            created_by=user_email,
            updated_by=user_email,
        )

        # Match each delivery item to its SO item to recover unit price
        so_item_map = {it.id: it for it in so.items}
        net_total = Decimal("0")
        for idx, di in enumerate(delivery.items, start=1):
            src = so_item_map.get(di.so_item_id)
            unit_price = src.unit_price if src else Decimal("0")
            net_amount = (di.quantity * unit_price).quantize(Decimal("0.01"))
            bill.items.append(models.BillingItem(
                item_no=di.item_no,
                material_code=di.material_code,
                quantity=di.quantity,
                unit_price=unit_price,
                net_amount=net_amount,
                created_by=user_email,
                updated_by=user_email,
            ))
            net_total += net_amount

        tax = (net_total * payload.tax_rate_percent / Decimal("100")).quantize(Decimal("0.01"))
        bill.net_amount = net_total
        bill.tax_amount = tax
        bill.gross_amount = net_total + tax

        # Mark upstream documents as completed
        delivery.status = DocStatus.COMPLETED
        so.status = DocStatus.COMPLETED

        self.db.add(bill)
        self.db.flush()
        return bill
