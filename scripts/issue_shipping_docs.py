#!/usr/bin/env python3
"""
scripts/issue_shipping_docs.py
================================
CLEAR 取引 2件について出荷書類一式を発行する。

対象受注:
  SO-10300000  CUST-JP-01  20 pc  JPY  (国内)
  SO-10300002  CUST-DE-01  15 pc  USD  (ドイツ向け輸出)

各SOについて以下を実行:
  1. DBマイグレーション (新カラム追加)
  2. 既存 Delivery / Billing / ExportDecl をリセット
  3. Delivery 作成  ← AI_TM case_no で再審査 → APPROVED/BLOCKED 保持
  4. BillingDocument 作成  ← 承認済みDeliveryのみ発行可
  5. ExportDeclaration 作成
  6. PDF 発行:
       - Commercial Invoice    (case_no 付き)
       - Packing List          (case_no 付き)
       - Export Declaration    (case_no 付き)

Output: output/shipping_docs/
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal

CLIENT_ID  = "DEMO"
PLANT      = "P001"
USER       = "shipping@erp.system"
OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "output", "shipping_docs",
)


def ok(msg: str)   -> None: print(f"  ✅  {msg}")
def step(msg: str) -> None: print(f"\n  ▶   {msg}")
def info(msg: str) -> None: print(f"  ℹ   {msg}")
def warn(msg: str) -> None: print(f"  ⚠️   {msg}")
def saved(path: str) -> None: print(f"  📄  Saved: {path}")


# ──────────────────────────────────────────────────────────────────
# DB MIGRATION
# ──────────────────────────────────────────────────────────────────

def _migrate(db) -> None:
    """Add new columns if not yet present (SQLite does not auto-migrate)."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE deliveries ADD COLUMN aitm_case_no VARCHAR(50)",
        "ALTER TABLE deliveries ADD COLUMN aitm_approval_status VARCHAR(20)",
        "ALTER TABLE billing_documents ADD COLUMN aitm_case_no VARCHAR(50)",
        "ALTER TABLE ai_tm_shipment_links ADD COLUMN case_no VARCHAR(50)",
        "ALTER TABLE ai_tm_shipment_links ADD COLUMN ai_status VARCHAR(20)",
    ]
    added = []
    for sql in migrations:
        try:
            db.execute(text(sql))
            db.commit()
            col = sql.split("ADD COLUMN")[1].split()[0]
            added.append(col)
        except Exception:
            pass  # column already exists
    if added:
        print(f"  🔧  Migration: added columns {added}")
    else:
        print("  🔧  Migration: all columns already present")


# ──────────────────────────────────────────────────────────────────
# RESET helper
# ──────────────────────────────────────────────────────────────────

def _reset_so_documents(db, so) -> None:
    """Delete Delivery chain and reset SO status to OPEN for reprocessing."""
    from sqlalchemy import text
    from app.modules.sd.models import Delivery, BillingDocument
    from app.modules.gts.models import ExportDeclaration, AITMShipmentLink

    # Find existing deliveries for this SO
    deliveries = db.query(Delivery).filter(
        Delivery.client_id == CLIENT_ID,
        Delivery.sales_order_id == so.id,
    ).all()

    for d in deliveries:
        # Remove shipment links
        db.query(AITMShipmentLink).filter(
            AITMShipmentLink.delivery_id == d.id
        ).delete()
        # Remove export declarations linked to delivery
        db.query(ExportDeclaration).filter(
            ExportDeclaration.delivery_id == d.id
        ).delete()
        # Remove billing documents
        db.query(BillingDocument).filter(
            BillingDocument.delivery_id == d.id
        ).delete()
        db.delete(d)

    # Remove export declarations linked to SO (but not delivery)
    db.query(ExportDeclaration).filter(
        ExportDeclaration.client_id == CLIENT_ID,
        ExportDeclaration.sales_order_id == so.id,
        ExportDeclaration.delivery_id == None,
    ).delete()

    # Reset SO status to OPEN
    so.status = "OPEN"
    db.commit()
    info("Reset SO → OPEN, removed existing Delivery/Billing/ExportDecl")


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────

def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    db = SessionLocal()
    try:
        step("DB Migration")
        _migrate(db)
        _run(db)
    finally:
        db.close()


def _run(db) -> None:
    from app.modules.sd import models as sd_models, service as sd_service, schemas as sd_schemas
    from app.modules.gts import models as gts_models
    from app.modules.mdm.models import BusinessPartner, Company, Material
    from app.core.numbering import next_number

    # ── Seller company ─────────────────────────────────────────────
    seller = (
        db.query(Company)
        .filter(Company.client_id == CLIENT_ID, Company.country == "JP")
        .first()
        or db.query(Company).filter(Company.client_id == CLIENT_ID).first()
    )
    if not seller:
        print("ERROR: No Company found for DEMO — run the main seeder first.")
        return

    # ── CTRL-HC200 ─────────────────────────────────────────────────
    ctrl = db.query(Material).filter(
        Material.client_id == CLIENT_ID,
        Material.material_code == "CTRL-HC200",
    ).first()

    target_doc_numbers = ["10300000", "10300002"]

    print("\n" + "═" * 62)
    print("  出荷書類発行  (Issue Shipping Documents with AI_TM Approval)")
    print("  Client: DEMO  |  Output:", OUTPUT_DIR)
    print("═" * 62)

    for doc_num in target_doc_numbers:
        so = db.query(sd_models.SalesOrder).filter(
            sd_models.SalesOrder.client_id == CLIENT_ID,
            sd_models.SalesOrder.document_number == doc_num,
        ).first()
        if not so:
            print(f"\nWARN: SO {doc_num} not found — skipping")
            continue

        customer = db.query(BusinessPartner).filter(
            BusinessPartner.client_id == CLIENT_ID,
            BusinessPartner.bp_code == so.customer_code,
        ).first()

        print(f"\n{'━' * 62}")
        print(f"  SO-{so.document_number}"
              f"  | {customer.name if customer else so.customer_code}"
              f"  ({so.customer_code})"
              f"  | {so.currency} {so.total_amount:,.2f}"
              f"  | AI_TM case: {so.export_check_ref or '(none)'}")
        print(f"{'━' * 62}")

        # ── Reset ──────────────────────────────────────────────────
        step("Reset existing docs for clean re-run")
        _reset_so_documents(db, so)

        # ── Step 1: Delivery ────────────────────────────────────────
        step("Step 1 — Create Delivery  [AI_TM re-screen will run automatically]")

        delivery_date = so.requested_delivery_date or (
            date.today() + timedelta(days=3)
        )
        delivery = sd_service.DeliveryService(db).create(
            sd_schemas.DeliveryCreate(
                sales_order_id=so.id,
                document_date=date.today(),
                plant_code=PLANT,
                actual_delivery_date=delivery_date,
                items=[],
            ),
            CLIENT_ID,
            USER,
        )
        db.commit()
        db.refresh(delivery)

        case_no = getattr(delivery, "aitm_case_no", None)
        approval = getattr(delivery, "aitm_approval_status", "PENDING")

        ok(f"Delivery {delivery.document_number}  "
           f"status={delivery.status}  "
           f"aitm_case={case_no}  "
           f"approval={approval}")

        if delivery.status == "BLOCKED":
            warn(f"Delivery is BLOCKED — cannot issue billing. Skipping PDF generation.")
            continue

        # ── Step 2: BillingDocument ─────────────────────────────────
        step("Step 2 — Create Billing Document  [requires APPROVED delivery]")

        bill = sd_service.BillingService(db).create_from_delivery(
            sd_schemas.BillingCreate(
                delivery_id=delivery.id,
                document_date=date.today(),
                tax_rate_percent=Decimal("0"),
                payment_terms=so.payment_terms,
            ),
            CLIENT_ID,
            USER,
        )
        db.commit()
        db.refresh(bill)

        ok(f"Billing {bill.document_number}  "
           f"Net {bill.currency} {bill.net_amount:,.2f}  "
           f"aitm_case={getattr(bill, 'aitm_case_no', '-')}")

        # ── Step 3: Export Declaration ──────────────────────────────
        step("Step 3 — Create Export Declaration")

        decl_num = next_number(db, CLIENT_ID, "EXPD")
        so_item = so.items[0] if so.items else None
        total_usd = float(so.total_amount)
        if so.currency == "JPY":
            total_usd = round(total_usd / 150, 2)

        is_domestic = (customer.country == "JP") if customer else True
        decl = gts_models.ExportDeclaration(
            client_id=CLIENT_ID,
            delivery_id=delivery.id,
            sales_order_id=so.id,
            declaration_number=decl_num,
            ai_tm_transaction_id=case_no,
            destination_country=customer.country if customer else "JP",
            material_code="CTRL-HC200",
            hs_code=ctrl.hs_code if ctrl else "8542.39.00",
            eccn=ctrl.eccn if ctrl else "3A001.b.1",
            quantity=so_item.quantity if so_item else Decimal("0"),
            quantity_unit="PC",
            declared_value_usd=Decimal(str(round(total_usd, 2))),
            license_type="NLR" if is_domestic else "EAR_LICENSE_EXCEPTION_LVS",
            license_authority="METI" if is_domestic else "BIS",
            status="DRAFT",
            remarks=(
                "国内向け / Domestic shipment. No export license required."
                if is_domestic else
                f"輸出 / Export to {customer.country}. "
                f"ECCN {ctrl.eccn if ctrl else '3A001.b.1'} — "
                f"License Exception LVS. AI_TM cleared: case {case_no}."
            ),
        )
        db.add(decl)
        db.commit()
        db.refresh(decl)
        ok(f"ExportDeclaration {decl.declaration_number}  "
           f"license={decl.license_type}  ai_tm_ref={case_no}")

        # ── Step 4: Generate PDFs ───────────────────────────────────
        step("Step 4 — Generate PDFs")

        mat_map = {ctrl.material_code: ctrl} if ctrl else {}
        prefix = f"SO-{so.document_number}"

        _gen_invoice(db, bill, customer, seller, mat_map, prefix)
        _gen_packing_list(delivery, customer, seller, mat_map, so, prefix)
        _gen_export_decl(decl, seller, customer, ctrl, so, delivery, prefix)

    print(f"\n{'═' * 62}")
    print(f"  ✅  書類発行完了")
    print(f"  出力先: {OUTPUT_DIR}")
    print(f"{'═' * 62}\n")


# ──────────────────────────────────────────────────────────────────
# PDF helpers
# ──────────────────────────────────────────────────────────────────

def _gen_invoice(db, bill, customer, seller, mat_map, prefix) -> None:
    from app.modules.sd.invoice_pdf import InvoicePdfGenerator
    variant = "distributor" if (customer and customer.country == "JP") else "enduser"
    pdf = InvoicePdfGenerator(variant=variant).render(
        billing=bill,
        customer=customer,
        seller_company=seller,
        material_descriptions={k: v.description for k, v in mat_map.items()},
    )
    path = os.path.join(OUTPUT_DIR, f"{prefix}_invoice_{bill.document_number}.pdf")
    _write(pdf, path)
    case = getattr(bill, "aitm_case_no", "-")
    saved(f"Commercial Invoice  [{bill.document_number}]  "
          f"AI_TM={case}  → {os.path.basename(path)}")


def _gen_packing_list(delivery, customer, seller, mat_map, so, prefix) -> None:
    from app.modules.sd.packing_list_pdf import PackingListPdfGenerator
    pdf = PackingListPdfGenerator().render(
        delivery=delivery,
        customer=customer,
        seller_company=seller,
        material_map=mat_map,
        so_document_number=so.document_number,
        incoterms=so.incoterms,
    )
    path = os.path.join(OUTPUT_DIR,
                        f"{prefix}_packing_{delivery.document_number}.pdf")
    _write(pdf, path)
    saved(f"Packing List        [{delivery.document_number}]  "
          f"AI_TM={getattr(delivery,'aitm_case_no','-')}  "
          f"→ {os.path.basename(path)}")


def _gen_export_decl(decl, seller, customer, material, so, delivery, prefix) -> None:
    from app.modules.gts.export_decl_pdf import ExportDeclPdfGenerator
    pdf = ExportDeclPdfGenerator().render(
        decl=decl,
        seller_company=seller,
        customer=customer,
        material=material,
        ai_tm_case_no=so.export_check_ref,
        so_document_number=so.document_number,
        delivery_document_number=delivery.document_number,
    )
    path = os.path.join(OUTPUT_DIR,
                        f"{prefix}_export_decl_{decl.declaration_number or decl.id}.pdf")
    _write(pdf, path)
    saved(f"Export Declaration  [{decl.declaration_number}]  "
          f"→ {os.path.basename(path)}")


def _write(data: bytes, path: str) -> None:
    with open(path, "wb") as f:
        f.write(data)


if __name__ == "__main__":
    main()
