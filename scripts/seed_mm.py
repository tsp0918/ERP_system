"""Seed Materials Management scenarios.

Generates 4 realistic procurement scenarios for the semiconductor materials
business set up in seed.py and seed_pp.py:

  ① PR -> auto PO (PR initiated by production planning, auto-grouped by vendor)
  ② Direct PO (urgent / spot purchase, no PR)
  ③ Partial GR + Partial IR (mid-flight procurement)
  ④ Price variance triggering 3-way match block

Run order: seed.py  ->  seed_pp.py  ->  seed_mm.py
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.mm import schemas as mm_schemas
from app.modules.mm.service import (
    GoodsReceiptService, InvoiceReceiptService,
    PurchaseOrderService, PurchaseRequisitionService,
)


CLIENT_ID = "DEMO"
ADMIN_EMAIL = settings.INITIAL_ADMIN_EMAIL


def _ensure_admin(db: Session):
    from app.core.auth_models import User
    return db.query(User).filter(User.email == ADMIN_EMAIL).first()


# ==================================================================
# Scenario 1: PR with multiple vendors -> auto-grouped POs
# ==================================================================
def _scenario_pr_to_po(db: Session, admin) -> list:
    print("\n[① PR -> auto-grouped PO (multiple vendors in one PR)]")
    today = date.today()

    pr_payload = mm_schemas.PurchaseRequisitionCreate(
        plant_code="1000",
        requested_by="planner@nsc.example.com",
        document_date=today,
        requested_delivery_date=today + timedelta(days=14),
        source_type="PROCESS_ORDER",
        source_reference="PRO-2026-Q2-001",
        items=[
            # PGMEA solvent from Tokyo Specialty Solvents
            mm_schemas.PurchaseRequisitionItemCreate(
                material_code="MAT-9000001",
                description="PGMEA Solvent (Electronic Grade)",
                quantity=Decimal("2000"), unit="KG",
                suggested_vendor_code="BP-5000001",
                estimated_unit_price=Decimal("1800"), currency="JPY",
                plant_code="1000",
            ),
            # H2O2 from Osaka Hydrogen Peroxide
            mm_schemas.PurchaseRequisitionItemCreate(
                material_code="MAT-9000002",
                description="Hydrogen Peroxide H2O2 31%",
                quantity=Decimal("500"), unit="KG",
                suggested_vendor_code="BP-5000002",
                estimated_unit_price=Decimal("650"), currency="JPY",
                plant_code="1000",
            ),
            # Colloidal Silica from Kyushu Silica
            mm_schemas.PurchaseRequisitionItemCreate(
                material_code="MAT-9000003",
                description="Colloidal Silica Particle Slurry Base",
                quantity=Decimal("3000"), unit="KG",
                suggested_vendor_code="BP-5000003",
                estimated_unit_price=Decimal("4200"), currency="JPY",
                plant_code="1000",
            ),
            # Also PGMEA - same vendor as line 1, will be merged into 1 PO
            mm_schemas.PurchaseRequisitionItemCreate(
                material_code="MAT-9000001",
                description="PGMEA Solvent (Electronic Grade) - additional batch",
                quantity=Decimal("500"), unit="KG",
                suggested_vendor_code="BP-5000001",
                estimated_unit_price=Decimal("1800"), currency="JPY",
                plant_code="1000",
            ),
        ],
    )
    pr = PurchaseRequisitionService(db).create(pr_payload, CLIENT_ID, admin.email)
    db.commit(); db.refresh(pr)
    print(f"  ✓ PR#{pr.document_number}  ({len(pr.items)} items, {pr.source_type})")

    # Generate POs - automatically grouped by suggested_vendor_code
    pos = PurchaseOrderService(db).create_from_pr(
        mm_schemas.PurchaseOrderFromPRRequest(
            purchase_requisition_id=pr.id,
            payment_terms="NET60",
            incoterms="DAP",
        ),
        CLIENT_ID, admin.email,
    )
    db.commit()
    for po in pos:
        db.refresh(po)
        print(f"    ✓ PO#{po.document_number}  vendor={po.vendor_code}  "
              f"total={po.total_amount} {po.currency}  ({len(po.items)} items)")

    return pos


# ==================================================================
# Scenario 2: Direct PO (no PR) - urgent / spot purchase
# ==================================================================
def _scenario_direct_po(db: Session, admin):
    print("\n[② Direct PO - urgent spot purchase, no PR]")
    today = date.today()
    po = PurchaseOrderService(db).create(
        mm_schemas.PurchaseOrderCreate(
            purchasing_org_code="1000",
            plant_code="1000",
            vendor_code="BP-5000004",  # Bavarian Fluorine Chemicals
            document_date=today,
            requested_delivery_date=today + timedelta(days=21),
            incoterms="CIF",
            payment_terms="NET60",
            currency="EUR",
            items=[
                mm_schemas.PurchaseOrderItemCreate(
                    material_code="MAT-9000004",
                    description="Photoacid Generator PAG-Resin Polymer (urgent)",
                    quantity=Decimal("100"), unit="KG",
                    unit_price=Decimal("220.50"),
                    plant_code="1000",
                ),
            ],
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(po)
    print(f"  ✓ PO#{po.document_number}  vendor={po.vendor_code}  "
          f"total={po.total_amount} {po.currency}")
    return po


# ==================================================================
# Scenario 3: Partial GR + Partial IR
# ==================================================================
def _scenario_partial_receipt_invoice(db: Session, admin, po):
    print("\n[③ Partial GR + Partial IR (split deliveries)]")

    # First partial GR - half quantity
    first_po_item = po.items[0]
    half_qty = first_po_item.quantity / 2

    gr1 = GoodsReceiptService(db).create(
        mm_schemas.GoodsReceiptCreate(
            purchase_order_id=po.id,
            plant_code=po.plant_code,
            posting_date=date.today(),
            vendor_delivery_note="DN-2026-EU-001",
            items=[mm_schemas.GoodsReceiptItemCreate(
                po_item_id=first_po_item.id,
                quantity=half_qty,
                batch_code="BV-2026-PAG-A1",
                storage_location="WH-RAW-01",
            )],
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(gr1)
    print(f"  ✓ GR#{gr1.document_number}  partial qty={half_qty} {first_po_item.unit}  "
          f"batch={gr1.items[0].batch_code}")

    # Partial IR matching the first GR
    ir1 = InvoiceReceiptService(db).create(
        mm_schemas.InvoiceReceiptCreate(
            purchase_order_id=po.id,
            vendor_invoice_number="BV-INV-2026-1145",
            invoice_date=date.today(),
            posting_date=date.today(),
            tax_rate_percent=Decimal("0"),
            items=[mm_schemas.InvoiceReceiptItemCreate(
                po_item_id=first_po_item.id,
                quantity=half_qty,
                unit_price=first_po_item.unit_price,
            )],
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(ir1)
    print(f"  ✓ IR#{ir1.document_number}  qty={half_qty} @ {first_po_item.unit_price}  "
          f"match={ir1.match_status}")
    if ir1.match_message:
        print(f"      └─ {ir1.match_message}")


# ==================================================================
# Scenario 4: 3-way match BLOCK due to price variance
# ==================================================================
def _scenario_three_way_match_block(db: Session, admin, pos: list):
    print("\n[④ Price variance -> 3-way match BLOCKED]")
    if not pos:
        print("  · No PO available, skipping")
        return

    # Use first PO from scenario 1
    po = pos[0]
    print(f"  Using PO#{po.document_number} (vendor={po.vendor_code})")

    # Full GR first
    gr = GoodsReceiptService(db).create(
        mm_schemas.GoodsReceiptCreate(
            purchase_order_id=po.id,
            plant_code=po.plant_code,
            posting_date=date.today(),
            vendor_delivery_note="DN-TS-2026-008",
            # items=None means full receipt
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(gr)
    print(f"  ✓ GR#{gr.document_number}  full receipt")

    # IR with inflated price (5% higher than PO -> over 2% tolerance -> BLOCKED)
    poi = po.items[0]
    inflated_price = (poi.unit_price * Decimal("1.05")).quantize(Decimal("0.0001"))
    ir = InvoiceReceiptService(db).create(
        mm_schemas.InvoiceReceiptCreate(
            purchase_order_id=po.id,
            vendor_invoice_number="TS-INV-VARIANCE-2026",
            invoice_date=date.today(),
            posting_date=date.today(),
            tax_rate_percent=Decimal("0"),
            items=[mm_schemas.InvoiceReceiptItemCreate(
                po_item_id=poi.id,
                quantity=poi.received_quantity,
                unit_price=inflated_price,
            )],
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(ir)
    print(f"  ⚠ IR#{ir.document_number}  PO price {poi.unit_price} vs "
          f"IR price {inflated_price}  ({((inflated_price - poi.unit_price) / poi.unit_price * 100):.1f}% variance)")
    print(f"      └─ match_status = {ir.match_status}")
    print(f"      └─ {ir.match_message}")


def main():
    print("=" * 78)
    print("  Mini Global ERP - Phase 2C MM Seed (Procure-to-Pay)")
    print("=" * 78)

    create_all_tables()
    db = SessionLocal()
    try:
        admin = _ensure_admin(db)
        if not admin:
            raise SystemExit("Run scripts/seed.py first.")

        pos = _scenario_pr_to_po(db, admin)
        urgent_po = _scenario_direct_po(db, admin)
        _scenario_partial_receipt_invoice(db, admin, urgent_po)
        _scenario_three_way_match_block(db, admin, pos)

        print("\n" + "=" * 78)
        print("  ✓ MM seed complete.")
        print("=" * 78)
        print("  Try these endpoints:")
        print("    GET  /mm/purchase-requisitions")
        print("    GET  /mm/purchase-orders?status=OPEN")
        print("    POST /mm/purchase-orders/from-pr  {purchase_requisition_id}")
        print("    GET  /mm/goods-receipts")
        print("    GET  /mm/invoice-receipts?match_status=BLOCKED")
    finally:
        db.close()


if __name__ == "__main__":
    main()
