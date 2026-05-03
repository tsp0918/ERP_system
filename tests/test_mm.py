"""Tests for MM module: PR/PO/GR/IR + 3-way match."""
import pytest
from decimal import Decimal

from app.modules.mdm import schemas as mdm_schemas, service as mdm_service
from app.modules.mm import schemas as mm_schemas, service as mm_service


@pytest.fixture
def vendor_and_material(db_session, admin_user):
    """Create one vendor and one purchasable material."""
    vendor = mdm_service.BusinessPartnerService(db_session).create(
        mdm_schemas.BusinessPartnerCreate(
            bp_code="BP-VEND-T1", name="Test Vendor",
            country="JP", roles="VENDOR",
            payment_terms="NET30", auto_screen=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    material = mdm_service.MaterialService(db_session).create(
        mdm_schemas.MaterialCreate(
            material_code="MAT-PROC-1", description="Procurement Material",
            material_type="ROH", base_unit="KG",
            standard_price=Decimal("500"), auto_classify=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    return {"vendor": vendor, "material": material}


# ==================================================================
# PR -> PO conversion
# ==================================================================
def test_pr_to_po_groups_by_vendor(db_session, admin_user, vendor_and_material):
    pr = mm_service.PurchaseRequisitionService(db_session).create(
        mm_schemas.PurchaseRequisitionCreate(
            plant_code="P1",
            items=[mm_schemas.PurchaseRequisitionItemCreate(
                material_code="MAT-PROC-1",
                quantity=Decimal("100"), unit="KG",
                suggested_vendor_code="BP-VEND-T1",
                estimated_unit_price=Decimal("500"),
                currency="JPY",
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    pos = mm_service.PurchaseOrderService(db_session).create_from_pr(
        mm_schemas.PurchaseOrderFromPRRequest(
            purchase_requisition_id=pr.id,
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert len(pos) == 1
    assert pos[0].vendor_code == "BP-VEND-T1"
    assert pos[0].total_amount == Decimal("50000.00")


# ==================================================================
# 3-way match
# ==================================================================
@pytest.fixture
def open_po(db_session, admin_user, vendor_and_material):
    po = mm_service.PurchaseOrderService(db_session).create(
        mm_schemas.PurchaseOrderCreate(
            plant_code="P1",
            vendor_code="BP-VEND-T1",
            currency="JPY",
            items=[mm_schemas.PurchaseOrderItemCreate(
                material_code="MAT-PROC-1",
                quantity=Decimal("100"),
                unit="KG",
                unit_price=Decimal("500"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    return po


def test_three_way_match_passes_when_quantities_and_price_align(
    db_session, admin_user, open_po,
):
    # Full GR
    mm_service.GoodsReceiptService(db_session).create(
        mm_schemas.GoodsReceiptCreate(purchase_order_id=open_po.id),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    # IR with matching qty and price
    ir = mm_service.InvoiceReceiptService(db_session).create(
        mm_schemas.InvoiceReceiptCreate(
            purchase_order_id=open_po.id,
            vendor_invoice_number="INV-1",
            items=[mm_schemas.InvoiceReceiptItemCreate(
                po_item_id=open_po.items[0].id,
                quantity=Decimal("100"),
                unit_price=Decimal("500"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert ir.match_status == "MATCHED"


def test_three_way_match_blocks_on_price_variance(
    db_session, admin_user, open_po,
):
    mm_service.GoodsReceiptService(db_session).create(
        mm_schemas.GoodsReceiptCreate(purchase_order_id=open_po.id),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    # IR with 10% inflated price (>2% tolerance -> BLOCKED)
    ir = mm_service.InvoiceReceiptService(db_session).create(
        mm_schemas.InvoiceReceiptCreate(
            purchase_order_id=open_po.id,
            vendor_invoice_number="INV-OVER",
            items=[mm_schemas.InvoiceReceiptItemCreate(
                po_item_id=open_po.items[0].id,
                quantity=Decimal("100"),
                unit_price=Decimal("550"),  # 10% over
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert ir.match_status == "BLOCKED"
    assert "variance" in (ir.match_message or "").lower()


def test_three_way_match_blocks_on_excess_qty(
    db_session, admin_user, open_po,
):
    # Partial GR (50)
    mm_service.GoodsReceiptService(db_session).create(
        mm_schemas.GoodsReceiptCreate(
            purchase_order_id=open_po.id,
            items=[mm_schemas.GoodsReceiptItemCreate(
                po_item_id=open_po.items[0].id,
                quantity=Decimal("50"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    # IR billing for the full 100, but only 50 received -> BLOCKED
    ir = mm_service.InvoiceReceiptService(db_session).create(
        mm_schemas.InvoiceReceiptCreate(
            purchase_order_id=open_po.id,
            vendor_invoice_number="INV-OVER-QTY",
            items=[mm_schemas.InvoiceReceiptItemCreate(
                po_item_id=open_po.items[0].id,
                quantity=Decimal("100"),
                unit_price=Decimal("500"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert ir.match_status == "BLOCKED"


def test_partial_receipts_and_invoices(
    db_session, admin_user, open_po,
):
    """Two partial GRs + two partial IRs should all match correctly."""
    gr_svc = mm_service.GoodsReceiptService(db_session)
    ir_svc = mm_service.InvoiceReceiptService(db_session)
    item = open_po.items[0]

    # 1st partial: 60
    gr_svc.create(mm_schemas.GoodsReceiptCreate(
        purchase_order_id=open_po.id,
        items=[mm_schemas.GoodsReceiptItemCreate(
            po_item_id=item.id, quantity=Decimal("60"))],
    ), admin_user.client_id, admin_user.email)
    ir1 = ir_svc.create(mm_schemas.InvoiceReceiptCreate(
        purchase_order_id=open_po.id,
        vendor_invoice_number="INV-P1",
        items=[mm_schemas.InvoiceReceiptItemCreate(
            po_item_id=item.id, quantity=Decimal("60"),
            unit_price=Decimal("500"))],
    ), admin_user.client_id, admin_user.email)
    db_session.commit()
    assert ir1.match_status == "MATCHED"

    # 2nd partial: 40
    gr_svc.create(mm_schemas.GoodsReceiptCreate(
        purchase_order_id=open_po.id,
        items=[mm_schemas.GoodsReceiptItemCreate(
            po_item_id=item.id, quantity=Decimal("40"))],
    ), admin_user.client_id, admin_user.email)
    ir2 = ir_svc.create(mm_schemas.InvoiceReceiptCreate(
        purchase_order_id=open_po.id,
        vendor_invoice_number="INV-P2",
        items=[mm_schemas.InvoiceReceiptItemCreate(
            po_item_id=item.id, quantity=Decimal("40"),
            unit_price=Decimal("500"))],
    ), admin_user.client_id, admin_user.email)
    db_session.commit()
    assert ir2.match_status == "MATCHED"
