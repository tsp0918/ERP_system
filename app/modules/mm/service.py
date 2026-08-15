"""Materials Management - business logic.

Procure-to-pay flow:
    PR -> PO -> GR -> IR (with 3-way match)

Key features:
- Auto-grouping of PR items by suggested vendor when issuing POs
- Status transitions enforced (DRAFT/OPEN -> RELEASED -> COMPLETED)
- Partial receipts and partial invoicing supported
- 3-way match: PO quantity & price vs GR quantity vs IR quantity & price
"""
import logging
from collections import defaultdict
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.numbering import next_number
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.mm import models, schemas
from app.shared.base_models import DocStatus
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)


def _seed_mm_ranges() -> None:
    """Register MM-specific number ranges if not yet present."""
    from app.core.numbering import DEFAULT_RANGES
    DEFAULT_RANGES.setdefault(
        "PURCHASE_REQUISITION", {"prefix": "", "width": 10, "start": 1_000_000_000})
    DEFAULT_RANGES.setdefault(
        "GOODS_RECEIPT", {"prefix": "", "width": 10, "start": 5_000_000_000})
    DEFAULT_RANGES.setdefault(
        "INVOICE_RECEIPT", {"prefix": "", "width": 10, "start": 5_100_000_000})
    DEFAULT_RANGES.setdefault(
        "RESERVATION", {"prefix": "RES-", "width": 7, "start": 1})


# ==================================================================
# Purchase Requisition
# ==================================================================
class PurchaseRequisitionService:
    def __init__(self, db: Session):
        self.db = db
        _seed_mm_ranges()

    def create(self, payload: schemas.PurchaseRequisitionCreate,
               client_id: str, user_email: str) -> models.PurchaseRequisition:
        # Validate materials exist
        for it in payload.items:
            m = self.db.query(Material).filter(
                Material.material_code == it.material_code,
                Material.client_id == client_id,
            ).first()
            if not m:
                raise NotFoundError("Material", it.material_code)

        pr_number = next_number(self.db, client_id, "PURCHASE_REQUISITION")
        pr = models.PurchaseRequisition(
            client_id=client_id,
            document_number=pr_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            plant_code=payload.plant_code,
            requested_by=payload.requested_by or user_email,
            requested_delivery_date=payload.requested_delivery_date,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            created_by=user_email,
            updated_by=user_email,
        )
        for idx, it in enumerate(payload.items, start=1):
            pr.items.append(models.PurchaseRequisitionItem(
                item_no=idx * 10,
                material_code=it.material_code,
                description=it.description,
                quantity=it.quantity,
                unit=it.unit,
                suggested_vendor_code=it.suggested_vendor_code,
                estimated_unit_price=it.estimated_unit_price,
                currency=it.currency,
                plant_code=it.plant_code or payload.plant_code,
                requested_delivery_date=(it.requested_delivery_date
                                         or payload.requested_delivery_date),
                created_by=user_email,
                updated_by=user_email,
            ))
        self.db.add(pr)
        self.db.flush()
        return pr


# ==================================================================
# Purchase Order
# ==================================================================
class PurchaseOrderService:
    def __init__(self, db: Session):
        self.db = db
        _seed_mm_ranges()

    # ---- Direct PO creation ----
    def create(self, payload: schemas.PurchaseOrderCreate,
               client_id: str, user_email: str) -> models.PurchaseOrder:
        # Validate vendor
        vendor = self.db.query(BusinessPartner).filter(
            BusinessPartner.bp_code == payload.vendor_code,
            BusinessPartner.client_id == client_id,
        ).first()
        if not vendor:
            raise NotFoundError("Vendor (BusinessPartner)", payload.vendor_code)
        if not vendor.has_role("VENDOR"):
            raise BusinessRuleError(
                f"BP {vendor.bp_code} does not have VENDOR role")

        # Validate materials exist
        for it in payload.items:
            m = self.db.query(Material).filter(
                Material.material_code == it.material_code,
                Material.client_id == client_id,
            ).first()
            if not m:
                raise NotFoundError("Material", it.material_code)

        po_number = next_number(self.db, client_id, "PURCHASE_ORDER")
        po = models.PurchaseOrder(
            client_id=client_id,
            document_number=po_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            purchasing_org_code=payload.purchasing_org_code,
            plant_code=payload.plant_code,
            vendor_code=payload.vendor_code,
            requested_delivery_date=payload.requested_delivery_date,
            incoterms=payload.incoterms,
            payment_terms=payload.payment_terms or vendor.payment_terms,
            currency=payload.currency,
            created_by=user_email,
            updated_by=user_email,
        )

        total = Decimal("0")
        for idx, it in enumerate(payload.items, start=1):
            net_amount = (it.quantity * it.unit_price).quantize(Decimal("0.01"))
            po.items.append(models.PurchaseOrderItem(
                item_no=idx * 10,
                pr_item_id=it.pr_item_id,
                material_code=it.material_code,
                description=it.description,
                quantity=it.quantity,
                unit=it.unit,
                unit_price=it.unit_price,
                net_amount=net_amount,
                plant_code=it.plant_code or payload.plant_code,
                created_by=user_email,
                updated_by=user_email,
            ))
            total += net_amount

            # Reflect on PR if linked
            if it.pr_item_id:
                pr_item = self.db.get(models.PurchaseRequisitionItem, it.pr_item_id)
                if pr_item:
                    pr_item.ordered_quantity = (
                        (pr_item.ordered_quantity or Decimal("0")) + it.quantity)

        po.total_amount = total
        self.db.add(po)
        self.db.flush()
        return po

    # ---- PO from PR (auto-group by vendor) ----
    def create_from_pr(self, payload: schemas.PurchaseOrderFromPRRequest,
                       client_id: str, user_email: str
                       ) -> List[models.PurchaseOrder]:
        pr = BaseRepository(models.PurchaseRequisition, self.db).get(
            payload.purchase_requisition_id, client_id)
        if not pr:
            raise NotFoundError("PurchaseRequisition", payload.purchase_requisition_id)
        if pr.status not in {DocStatus.OPEN, DocStatus.RELEASED}:
            raise BusinessRuleError(
                f"PR {pr.document_number} status {pr.status} - cannot generate POs")

        # Group PR items by effective vendor
        groups: dict[str, List[models.PurchaseRequisitionItem]] = defaultdict(list)
        for pri in pr.items:
            # Skip items already fully ordered
            if pri.ordered_quantity >= pri.quantity:
                continue
            vendor_code = payload.vendor_code or pri.suggested_vendor_code
            if not vendor_code:
                raise BusinessRuleError(
                    f"PR item {pri.item_no} has no vendor (specify in request "
                    f"or set suggested_vendor_code)")
            groups[vendor_code].append(pri)

        if not groups:
            raise BusinessRuleError(
                f"PR {pr.document_number} has no remaining open items")

        created_pos: List[models.PurchaseOrder] = []
        for vendor_code, items in groups.items():
            po_items = []
            for pri in items:
                remaining = pri.quantity - pri.ordered_quantity
                if remaining <= 0:
                    continue
                po_items.append(schemas.PurchaseOrderItemCreate(
                    material_code=pri.material_code,
                    description=pri.description,
                    quantity=remaining,
                    unit=pri.unit,
                    unit_price=(pri.estimated_unit_price or Decimal("0")),
                    plant_code=pri.plant_code,
                    pr_item_id=pri.id,
                ))
            if not po_items:
                continue

            currency = items[0].currency or "JPY"
            po_payload = schemas.PurchaseOrderCreate(
                purchasing_org_code=payload.purchasing_org_code,
                plant_code=pr.plant_code,
                vendor_code=vendor_code,
                requested_delivery_date=pr.requested_delivery_date,
                incoterms=payload.incoterms,
                payment_terms=payload.payment_terms,
                currency=currency,
                items=po_items,
            )
            po = self.create(po_payload, client_id, user_email)
            po.reference = pr.document_number
            created_pos.append(po)

        # Update PR status: COMPLETED if every item fully ordered
        all_done = all(p.ordered_quantity >= p.quantity for p in pr.items)
        if all_done:
            pr.status = DocStatus.COMPLETED

        return created_pos

    def release(self, po_id: int, client_id: str, user_email: str) -> models.PurchaseOrder:
        po = BaseRepository(models.PurchaseOrder, self.db).get(po_id, client_id)
        if not po:
            raise NotFoundError("PurchaseOrder", po_id)
        if po.status not in {DocStatus.OPEN, DocStatus.DRAFT}:
            raise BusinessRuleError(
                f"PO {po.document_number} status {po.status} - cannot release")
        po.status = DocStatus.RELEASED
        po.updated_by = user_email
        return po


# ==================================================================
# Goods Receipt
# ==================================================================
class GoodsReceiptService:
    def __init__(self, db: Session):
        self.db = db
        _seed_mm_ranges()

    def create(self, payload: schemas.GoodsReceiptCreate,
               client_id: str, user_email: str) -> models.GoodsReceipt:
        po = BaseRepository(models.PurchaseOrder, self.db).get(
            payload.purchase_order_id, client_id)
        if not po:
            raise NotFoundError("PurchaseOrder", payload.purchase_order_id)
        if po.status not in {DocStatus.OPEN, DocStatus.RELEASED}:
            raise BusinessRuleError(
                f"PO {po.document_number} status {po.status} - "
                "cannot post goods receipt")

        gr_number = next_number(self.db, client_id, "GOODS_RECEIPT")
        gr = models.GoodsReceipt(
            client_id=client_id,
            document_number=gr_number,
            document_date=payload.posting_date,
            status=DocStatus.OPEN,
            reference=po.document_number,
            purchase_order_id=po.id,
            plant_code=payload.plant_code or po.plant_code,
            posting_date=payload.posting_date,
            vendor_delivery_note=payload.vendor_delivery_note,
            created_by=user_email,
            updated_by=user_email,
        )

        # Default: full receipt of remaining open quantity per PO item
        if not payload.items:
            for poi in po.items:
                remaining = poi.quantity - poi.received_quantity
                if remaining <= 0:
                    continue
                gr.items.append(models.GoodsReceiptItem(
                    po_item_id=poi.id,
                    item_no=poi.item_no,
                    material_code=poi.material_code,
                    quantity=remaining,
                    unit=poi.unit,
                    created_by=user_email,
                    updated_by=user_email,
                ))
                poi.received_quantity = poi.quantity
        else:
            po_item_map = {p.id: p for p in po.items}
            for gri in payload.items:
                poi = po_item_map.get(gri.po_item_id)
                if not poi:
                    raise BusinessRuleError(
                        f"PO item {gri.po_item_id} not on PO {po.document_number}")
                # Over-receipt check
                new_total = poi.received_quantity + gri.quantity
                if new_total > poi.quantity:
                    raise BusinessRuleError(
                        f"Receipt qty {gri.quantity} exceeds open qty for PO item "
                        f"{poi.item_no} (open: {poi.quantity - poi.received_quantity})")
                gr.items.append(models.GoodsReceiptItem(
                    po_item_id=poi.id,
                    item_no=poi.item_no,
                    material_code=poi.material_code,
                    quantity=gri.quantity,
                    unit=poi.unit,
                    batch_code=gri.batch_code,
                    storage_location=gri.storage_location,
                    created_by=user_email,
                    updated_by=user_email,
                ))
                poi.received_quantity = new_total

        # Mark PO completed when all items fully received
        if all(p.received_quantity >= p.quantity for p in po.items):
            po.status = DocStatus.COMPLETED

        self.db.add(gr)
        self.db.flush()
        return gr


# ==================================================================
# Invoice Receipt + 3-Way Match
# ==================================================================
class InvoiceReceiptService:
    """Vendor invoice posting with 3-way match.

    3-Way match validates:
    1. Each invoice line refers to a valid PO line
    2. Invoiced qty does NOT exceed (received_qty - already_invoiced_qty)
    3. Invoice unit price matches PO unit price within tolerance
    """

    PRICE_TOLERANCE_PERCENT = Decimal("2.0")  # 2% tolerance on price match

    def __init__(self, db: Session):
        self.db = db
        _seed_mm_ranges()

    def create(self, payload: schemas.InvoiceReceiptCreate,
               client_id: str, user_email: str) -> models.InvoiceReceipt:
        po = BaseRepository(models.PurchaseOrder, self.db).get(
            payload.purchase_order_id, client_id)
        if not po:
            raise NotFoundError("PurchaseOrder", payload.purchase_order_id)

        ir_number = next_number(self.db, client_id, "INVOICE_RECEIPT")
        ir = models.InvoiceReceipt(
            client_id=client_id,
            document_number=ir_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            reference=po.document_number,
            purchase_order_id=po.id,
            vendor_code=po.vendor_code,
            vendor_invoice_number=payload.vendor_invoice_number,
            posting_date=payload.posting_date,
            invoice_date=payload.invoice_date,
            currency=po.currency,
            created_by=user_email,
            updated_by=user_email,
        )

        po_item_map = {p.id: p for p in po.items}
        match_problems: list[str] = []
        net_total = Decimal("0")

        for idx, ii in enumerate(payload.items, start=1):
            poi = po_item_map.get(ii.po_item_id)
            if not poi:
                raise BusinessRuleError(
                    f"PO item {ii.po_item_id} not on PO {po.document_number}")

            # --- Quantity check: invoiced <= received - already_invoiced ---
            available_to_invoice = poi.received_quantity - poi.invoiced_quantity
            if ii.quantity > available_to_invoice:
                match_problems.append(
                    f"Item {poi.item_no}: invoiced qty {ii.quantity} exceeds "
                    f"available (received {poi.received_quantity}, already invoiced "
                    f"{poi.invoiced_quantity})"
                )

            # --- Price tolerance check ---
            if poi.unit_price > 0:
                deviation = (ii.unit_price - poi.unit_price) / poi.unit_price * 100
                if abs(deviation) > self.PRICE_TOLERANCE_PERCENT:
                    match_problems.append(
                        f"Item {poi.item_no}: price variance "
                        f"{deviation:.2f}% (PO {poi.unit_price} vs IR {ii.unit_price})"
                    )

            net_amount = (ii.quantity * ii.unit_price).quantize(Decimal("0.01"))
            ir.items.append(models.InvoiceReceiptItem(
                po_item_id=poi.id,
                item_no=poi.item_no,
                material_code=poi.material_code,
                quantity=ii.quantity,
                unit=poi.unit,
                unit_price=ii.unit_price,
                net_amount=net_amount,
                created_by=user_email,
                updated_by=user_email,
            ))
            net_total += net_amount
            poi.invoiced_quantity = poi.invoiced_quantity + ii.quantity

        tax = (net_total * payload.tax_rate_percent / Decimal("100")
              ).quantize(Decimal("0.01"))
        ir.net_amount = net_total
        ir.tax_amount = tax
        ir.gross_amount = net_total + tax

        # Set match status
        if match_problems:
            ir.match_status = "BLOCKED"
            ir.match_message = " | ".join(match_problems)
        else:
            ir.match_status = "MATCHED"
            ir.match_message = "3-way match OK"

        self.db.add(ir)
        self.db.flush()
        return ir


# ==================================================================
# Purchasing Info Record
# ==================================================================
class PurchasingInfoRecordService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.PurchasingInfoRecord, db)

    def create(
        self,
        payload: schemas.PurchasingInfoRecordCreate,
        client_id: str,
        user_email: str,
    ) -> models.PurchasingInfoRecord:
        existing = self.db.query(models.PurchasingInfoRecord).filter(
            models.PurchasingInfoRecord.client_id == client_id,
            models.PurchasingInfoRecord.material_code == payload.material_code,
            models.PurchasingInfoRecord.vendor_code == payload.vendor_code,
            models.PurchasingInfoRecord.plant_code == payload.plant_code,
        ).first()
        if existing:
            raise BusinessRuleError(
                f"PurchasingInfoRecord already exists for "
                f"{payload.material_code}/{payload.vendor_code}/"
                f"{payload.plant_code or 'ALL'}"
            )
        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
        })
        return self.repo.create(data)


# ==================================================================
# Source List
# ==================================================================
class SourceListService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.SourceList, db)

    def create(
        self,
        payload: schemas.SourceListCreate,
        client_id: str,
        user_email: str,
    ) -> models.SourceList:
        existing = self.db.query(models.SourceList).filter(
            models.SourceList.client_id == client_id,
            models.SourceList.material_code == payload.material_code,
            models.SourceList.plant_code == payload.plant_code,
            models.SourceList.vendor_code == payload.vendor_code,
        ).first()
        if existing:
            raise BusinessRuleError(
                f"SourceList entry already exists for "
                f"{payload.material_code}/{payload.plant_code}/{payload.vendor_code}"
            )
        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
        })
        return self.repo.create(data)


# ==================================================================
# Stock Balance
# ==================================================================
class StockBalanceService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.StockBalance, db)

    def create(
        self,
        payload: schemas.StockBalanceCreate,
        client_id: str,
        user_email: str,
    ) -> models.StockBalance:
        existing = self.db.query(models.StockBalance).filter(
            models.StockBalance.client_id == client_id,
            models.StockBalance.material_code == payload.material_code,
            models.StockBalance.plant_code == payload.plant_code,
            models.StockBalance.storage_location == payload.storage_location,
        ).first()
        if existing:
            raise BusinessRuleError(
                f"StockBalance record already exists for "
                f"{payload.material_code}/{payload.plant_code}/{payload.storage_location}"
            )
        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "created_by": user_email,
            "updated_by": user_email,
        })
        return self.repo.create(data)

    def adjust(
        self,
        stock_id: int,
        client_id: str,
        delta_unrestricted: Optional[Decimal] = None,
        delta_reserved: Optional[Decimal] = None,
        user_email: str = "system",
    ) -> models.StockBalance:
        stock = self.repo.get(stock_id, client_id)
        if not stock:
            raise NotFoundError("StockBalance", stock_id)
        if delta_unrestricted is not None:
            stock.unrestricted_qty = max(Decimal("0"),
                                         stock.unrestricted_qty + delta_unrestricted)
        if delta_reserved is not None:
            stock.reserved_qty = max(Decimal("0"),
                                     stock.reserved_qty + delta_reserved)
        stock.updated_by = user_email
        self.db.flush()
        return stock


# ==================================================================
# Reservation
# ==================================================================
class ReservationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.Reservation, db)

    def create(
        self,
        payload: schemas.ReservationCreate,
        client_id: str,
        user_email: str,
    ) -> models.Reservation:
        reservation_number = next_number(self.db, client_id, "RESERVATION")
        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "reservation_number": reservation_number,
            "withdrawn_qty": Decimal("0"),
            "status": "OPEN",
            "created_by": user_email,
            "updated_by": user_email,
        })
        return self.repo.create(data)

    def cancel(self, reservation_id: int, client_id: str,
               user_email: str) -> models.Reservation:
        r = self.repo.get(reservation_id, client_id)
        if not r:
            raise NotFoundError("Reservation", reservation_id)
        if r.status in {"FULLY_WITHDRAWN", "CANCELLED"}:
            raise BusinessRuleError(
                f"Reservation {r.reservation_number} is already {r.status}")
        r.status = "CANCELLED"
        r.updated_by = user_email
        self.db.flush()
        return r
