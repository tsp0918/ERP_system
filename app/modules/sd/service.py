"""SD service - business rules for the Order-to-Cash flow."""
import logging
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.numbering import next_number
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.sd import models, schemas
from app.shared.base_models import DocStatus
from app.shared.base_repository import BaseRepository


# ---------------------------------------------------------------------------
# Helper: auto-create END_USER BP from CRM end_user payload
# ---------------------------------------------------------------------------

def _create_end_user_bp(
    db: Session,
    client_id: str,
    end_user: "schemas.EndUserCreate",
    user_email: str,
) -> BusinessPartner:
    """Create a BusinessPartner with roles=END_USER and auto_screen=true.

    Called when CRM sends an end_user object on the IF-25 sales order request.
    The bp_code is derived from the CRM account ID (or a generated slug).
    """
    from app.core.numbering import next_number as _nn
    bp_code_base = (end_user.crm_account_id or "EU").upper().replace("-", "")[:15]
    # Ensure uniqueness by appending a counter suffix
    candidate = bp_code_base
    suffix = 1
    while db.query(BusinessPartner).filter(
        BusinessPartner.client_id == client_id,
        BusinessPartner.bp_code == candidate,
    ).first():
        candidate = f"{bp_code_base}-{suffix}"
        suffix += 1

    bp = BusinessPartner(
        client_id=client_id,
        bp_code=candidate,
        bp_type="ORG",
        name=end_user.name,
        country=end_user.country,
        address_line1=end_user.address,
        roles="END_USER",
        crm_account_id=getattr(end_user, "crm_account_id", None),
        screening_status="PENDING",
        created_by=user_email,
        updated_by=user_email,
    )
    db.add(bp)
    db.flush()
    logger.info(
        "[sd_service] Auto-created END_USER BP bp_code=%s for CRM account=%s",
        bp.bp_code, end_user.crm_account_id,
    )
    return bp


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

        # CRM fields: always set from payload regardless of which export-check branch runs
        so.crm_contract_id = getattr(payload, "crm_contract_id", None)
        so.crm_engagement_id = getattr(payload, "crm_engagement_id", None)
        so.contract_start_date = getattr(payload, "contract_start_date", None)
        so.contract_end_date = getattr(payload, "contract_end_date", None)

        self.db.add(so)
        self.db.flush()

        # Export check routing: 3 branches (引き継ぎ書 §5.2, IF-25)
        if getattr(payload, "aitm_transaction_id", None):
            # Branch A — CRM provides an existing AI_TM transaction: link without new review
            from app.modules.gts.models import AITMTransactionLink
            so.aitm_transaction_id = payload.aitm_transaction_id
            self.db.add(AITMTransactionLink(
                client_id=client_id,
                sales_order_id=so.id,
                review_id=payload.aitm_transaction_id,
                review_status="LINKED",
                review_level="AUTO",
                link_source="crm",
                linked_existing=True,
                last_sync_at=__import__("datetime").datetime.utcnow(),
            ))
            so.export_check_status = "PENDING"
        elif not payload.skip_export_check:
            # Branch B — ERP-originated review (IF-19, existing flow)
            from app.modules.gts.service import GTSService
            try:
                link, _tx = GTSService(self.db).transaction_review(so, customer)
                so.export_check_ref = link.review_id
                if link.review_status == "APPROVED":
                    so.export_check_status = "PASSED"
                elif link.review_status == "REJECTED":
                    so.export_check_status = "BLOCKED"
                    so.export_check_message = "[AI_TM] Transaction rejected"
                else:
                    so.export_check_status = "PENDING"
            except Exception as exc:
                so.export_check_status = "ERROR"
                so.export_check_message = f"Integration error: {exc}"
        else:
            # Branch C — deliberately skipped
            so.export_check_status = "SKIPPED"

        # Auto-create end-user BP if CRM provides one (any branch)
        if getattr(payload, "end_user", None):
            _eu_bp = _create_end_user_bp(self.db, client_id, payload.end_user, user_email)
            so.end_user_bp_code = _eu_bp.bp_code

        # Block on REJECTED or ERROR.
        # PENDING from ERP-originated review also blocks until manual approval.
        # PENDING from CRM-linked transaction (Branch A) does NOT block — the review is in AI_TM.
        crm_linked = bool(getattr(payload, "aitm_transaction_id", None))
        if so.export_check_status in ("BLOCKED", "ERROR") or (
            so.export_check_status == "PENDING"
            and not payload.skip_export_check
            and not crm_linked
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

        # IF-21: consume license on AI_TM when SO has an allocation_id and delivery passes
        if getattr(so, "aitm_allocation_id", None) and delivery.aitm_approval_status not in ("BLOCKED", "REJECTED"):
            self._consume_license(delivery, so)

        # IF-28: notify CRM when delivery is created for a CRM-originated SO
        if getattr(so, "crm_contract_id", None):
            from app.shared.webhook_dispatcher import enqueue_webhook
            enqueue_webhook(self.db, client_id, "delivery.goods_issued", {
                "erp_delivery_id": delivery.id,
                "erp_document_number": delivery.document_number,
                "crm_contract_id": so.crm_contract_id,
                "aitm_approval_status": delivery.aitm_approval_status,
                "status": delivery.status,
            })

        return delivery

    def _consume_license(self, delivery: models.Delivery, so: models.SalesOrder) -> None:
        """IF-21: Call AI_TM to consume the license allocation on GI posting.

        Runs in the same DB transaction as delivery creation — rolled back on exception.
        """
        import json
        from decimal import Decimal as _D
        from app.modules.gts.models import LicenseConsumptionLog
        from app.integrations.ai_trade_management.client import get_client

        allocation_id = so.aitm_allocation_id
        total_qty = sum(
            (item.quantity or _D("0")) for item in delivery.items
        )

        client = get_client()
        try:
            resp = client.consume_license(allocation_id, float(total_qty), delivery.document_number)
            response_status = resp.get("status", "consumed")
            remaining = resp.get("remaining_quantity")
        except Exception as exc:
            logger.warning(
                "consume_license failed for delivery=%s allocation=%s: %s",
                delivery.document_number, allocation_id, exc,
            )
            response_status = "error"
            remaining = None
            resp = {"error": str(exc)}

        log = LicenseConsumptionLog(
            client_id=delivery.client_id,
            delivery_id=delivery.id,
            sales_order_id=so.id,
            allocation_id=allocation_id,
            consumed_quantity=total_qty,
            remaining_quantity=_D(str(remaining)) if remaining is not None else None,
            response_status=response_status,
            raw_response=json.dumps(resp, default=str),
        )
        self.db.add(log)
        logger.info(
            "License consumed: delivery=%s allocation=%s qty=%s status=%s",
            delivery.document_number, allocation_id, total_qty, response_status,
        )

    def _run_shipment_rescreen(self, delivery: models.Delivery, so: models.SalesOrder) -> None:
        """Re-screen at delivery time using the SO's AI_TM case number.

        Flow:
          1. Read case_no from so.export_check_ref (set when SO was export-checked)
          2. Look up the live transaction in AI_TM by case_no
          3. Trigger re-screening (POST /api/transactions/{id}/screening)
          4. Fetch updated transaction detail for final judgment
          5. APPROVED → delivery stays OPEN; BLOCKED/REVIEW → delivery BLOCKED
          6. Persist result in AITMShipmentLink + delivery fields
        """
        from datetime import datetime as _dt
        from app.modules.gts.models import AITMShipmentLink
        from app.integrations.ai_trade_management.client import get_client

        case_no = getattr(so, "aitm_transaction_id", None) or so.export_check_ref
        if not case_no:
            if so.export_check_status == "SKIPPED":
                # Export check was deliberately skipped — permit shipment without rescreen
                delivery.aitm_approval_status = "APPROVED"
                return
            # No export approval on record — block for compliance
            delivery.status = DocStatus.BLOCKED
            delivery.aitm_approval_status = "BLOCKED"
            self._save_shipment_link(delivery, None, False, None,
                                     "No AI_TM approval number on SO")
            return

        client = get_client()
        try:
            # Step 1: find transaction by case_no
            tx = client.find_transaction_by_case_no(case_no)
            if tx is None:
                delivery.status = DocStatus.BLOCKED
                delivery.aitm_case_no = case_no
                delivery.aitm_approval_status = "BLOCKED"
                self._save_shipment_link(
                    delivery, case_no, False, None,
                    f"Transaction {case_no} not found in AI_TM"
                )
                return

            # Step 2: trigger re-screening
            client.run_screening(tx.id)

            # Step 3: fetch updated detail
            tx_detail = client.get_transaction(tx.id)

            # Step 4: evaluate approval
            # Blocked statuses from AI_TM (explicit rejection)
            BLOCKED_STATUSES = {"rejected", "REJECTED"}
            BLOCKED_JUDGMENTS = {"BLOCKED", "REJECTED", "REQUIRES_PERMIT"}
            tx_status = (tx_detail.status or "").lower()
            agent_judgment = tx_detail.agent_judgment_status or tx_detail.ai_status or ""
            approved = (
                tx_status not in BLOCKED_STATUSES
                and agent_judgment not in BLOCKED_JUDGMENTS
            )
            ai_status = agent_judgment or f"screening_ok (status={tx_detail.status})"

            delivery.aitm_case_no = case_no
            delivery.aitm_approval_status = "APPROVED" if approved else "BLOCKED"
            if not approved:
                delivery.status = DocStatus.BLOCKED

            self._save_shipment_link(
                delivery, case_no, approved, ai_status,
                None if approved else f"AI_TM re-screen result: {ai_status}",
            )

        except Exception as exc:
            delivery.status = DocStatus.BLOCKED
            delivery.aitm_case_no = case_no
            delivery.aitm_approval_status = "ERROR"
            self._save_shipment_link(
                delivery, case_no, False, None,
                f"Re-screen error: {str(exc)[:200]}",
            )
            logger.warning("Shipment rescreen failed for DEL=%s: %s",
                           delivery.document_number, exc)

    def _save_shipment_link(
        self, delivery, case_no, shipment_ok: bool,
        ai_status, block_reason
    ) -> None:
        from datetime import datetime as _dt
        from app.modules.gts.models import AITMShipmentLink

        link = AITMShipmentLink(
            client_id=delivery.client_id,
            delivery_id=delivery.id,
            case_no=case_no,
            shipment_ok=shipment_ok,
            rescreen_at=_dt.utcnow(),
            rescreen_result="PASSED" if shipment_ok else "CHANGED",
            ai_status=ai_status,
            block_reason=block_reason,
        )
        self.db.add(link)


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

        # Enforce AI_TM approval gate: delivery must be APPROVED before billing
        if getattr(delivery, "aitm_approval_status", None) == "BLOCKED":
            from app.modules.gts.models import AITMShipmentLink
            link = (
                self.db.query(AITMShipmentLink)
                .filter(AITMShipmentLink.delivery_id == delivery.id)
                .order_by(AITMShipmentLink.id.desc())
                .first()
            )
            reason = link.block_reason if link else "unknown"
            raise BusinessRuleError(
                f"Delivery {delivery.document_number} is blocked by AI_TM re-screening "
                f"(case: {getattr(delivery, 'aitm_case_no', '-')}). "
                f"Reason: {reason}. Resolve compliance issue before billing."
            )

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
            aitm_case_no=getattr(delivery, "aitm_case_no", None),
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

        # IF-29: notify CRM when billing is posted for a CRM-originated SO
        if getattr(so, "crm_contract_id", None):
            from app.shared.webhook_dispatcher import enqueue_webhook
            enqueue_webhook(self.db, client_id, "billing.posted", {
                "erp_billing_id": bill.id,
                "erp_document_number": bill.document_number,
                "crm_contract_id": so.crm_contract_id,
                "net_amount": str(bill.net_amount),
                "gross_amount": str(bill.gross_amount),
                "currency": bill.currency,
            })

        return bill
