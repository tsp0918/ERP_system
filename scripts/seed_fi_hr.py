"""Seed FI auto-postings, HR master data, and generate a sample PDF.

Run order: seed.py -> seed_pp.py -> seed_mm.py -> seed_pp_execution.py
            -> seed_fi_hr.py (this script)

What this script does:
  1. Set up the default chart of accounts
  2. Replay the existing Billings/GRs/IRs into FI as auto-postings
  3. Compute and display the trial balance
  4. Seed a small set of HR departments and employees
  5. Generate sample PDFs for each invoice variant
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.fi.service import (
    FIPostingService, GLAccountService, TrialBalanceService,
)
from app.modules.hr import schemas as hr_schemas
from app.modules.hr.service import DepartmentService, EmployeeService
from app.modules.mm.models import GoodsReceipt, InvoiceReceipt
from app.modules.sd.models import BillingDocument
from app.modules.sd.invoice_pdf import InvoicePdfGenerator


CLIENT_ID = "DEMO"
ADMIN_EMAIL = settings.INITIAL_ADMIN_EMAIL


def _ensure_admin(db: Session):
    from app.core.auth_models import User
    return db.query(User).filter(User.email == ADMIN_EMAIL).first()


# ==================================================================
# Step 1: Chart of accounts
# ==================================================================
def _seed_chart_of_accounts(db: Session, admin):
    print("\n[① Chart of Accounts]")
    GLAccountService(db).ensure_defaults(CLIENT_ID, admin.email)
    db.commit()
    print("  ✓ Default accounts ensured")


# ==================================================================
# Step 2: Auto-post existing transactions
# ==================================================================
def _auto_post_billings(db: Session, admin):
    print("\n[② Auto-post billings (SD -> FI)]")
    fi = FIPostingService(db)
    bills = db.query(BillingDocument).filter(
        BillingDocument.client_id == CLIENT_ID).all()
    for bill in bills:
        # Skip if already posted (idempotency)
        from app.modules.fi.models import AccountingDocument
        existing = db.query(AccountingDocument).filter(
            AccountingDocument.client_id == CLIENT_ID,
            AccountingDocument.reference == bill.document_number,
            AccountingDocument.source_module == "SD",
        ).first()
        if existing:
            print(f"  · skip {bill.document_number} (already posted "
                  f"as {existing.document_number})")
            continue
        doc = fi.post_billing(bill, CLIENT_ID, admin.email)
        db.commit()
        print(f"  ✓ Bill {bill.document_number} -> FI doc "
              f"{doc.document_number}  ({len(doc.lines)} lines)")


def _auto_post_grs(db: Session, admin):
    print("\n[③ Auto-post goods receipts (MM -> FI)]")
    fi = FIPostingService(db)
    grs = db.query(GoodsReceipt).filter(
        GoodsReceipt.client_id == CLIENT_ID).all()
    for gr in grs:
        from app.modules.fi.models import AccountingDocument
        existing = db.query(AccountingDocument).filter(
            AccountingDocument.client_id == CLIENT_ID,
            AccountingDocument.reference == gr.document_number,
            AccountingDocument.source_module == "MM",
            AccountingDocument.document_type == "WE",
        ).first()
        if existing:
            print(f"  · skip {gr.document_number} (already posted)")
            continue
        try:
            doc = fi.post_goods_receipt(gr, CLIENT_ID, admin.email)
            db.commit()
            print(f"  ✓ GR {gr.document_number} -> FI doc {doc.document_number}")
        except Exception as exc:
            print(f"  ⚠ GR {gr.document_number}: {exc}")


def _auto_post_irs(db: Session, admin):
    print("\n[④ Auto-post invoice receipts (MM -> FI; matched only)]")
    fi = FIPostingService(db)
    irs = db.query(InvoiceReceipt).filter(
        InvoiceReceipt.client_id == CLIENT_ID).all()
    for ir in irs:
        if ir.match_status != "MATCHED":
            print(f"  · skip {ir.document_number} (status={ir.match_status})")
            continue
        from app.modules.fi.models import AccountingDocument
        existing = db.query(AccountingDocument).filter(
            AccountingDocument.client_id == CLIENT_ID,
            AccountingDocument.reference == ir.document_number,
            AccountingDocument.document_type == "RE",
        ).first()
        if existing:
            print(f"  · skip {ir.document_number} (already posted)")
            continue
        doc = fi.post_invoice_receipt(ir, CLIENT_ID, admin.email)
        db.commit()
        print(f"  ✓ IR {ir.document_number} -> FI doc {doc.document_number}")


# ==================================================================
# Step 3: Trial Balance
# ==================================================================
def _show_trial_balance(db: Session):
    print("\n[⑤ Trial Balance]")
    tb = TrialBalanceService(db).compute(CLIENT_ID)
    print(f"  {'Account':<10} {'Name':<30} {'Type':<10} "
          f"{'Debits':>15} {'Credits':>15} {'Balance':>15}")
    print(f"  {'-'*10} {'-'*30} {'-'*10} {'-'*15} {'-'*15} {'-'*15}")
    for r in tb.rows:
        name = (r.account_name or "")[:28]
        atype = r.account_type or "-"
        print(f"  {r.gl_account:<10} {name:<30} {atype:<10} "
              f"{float(r.debit_total):>15,.2f} "
              f"{float(r.credit_total):>15,.2f} "
              f"{float(r.net_balance):>15,.2f}")
    print(f"  {'-'*10} {'-'*30} {'-'*10} {'-'*15} {'-'*15} {'-'*15}")
    print(f"  {'TOTAL':<10} {'':<30} {'':<10} "
          f"{float(tb.total_debits):>15,.2f} {float(tb.total_credits):>15,.2f}"
          f"  {'BALANCED' if tb.is_balanced else 'IMBALANCED!'}")


# ==================================================================
# Step 4: HR master data
# ==================================================================
def _seed_hr(db: Session, admin):
    print("\n[⑥ HR Master Data]")
    dept_svc = DepartmentService(db)
    emp_svc = EmployeeService(db)

    departments = [
        {"department_code": "SALES-JP", "name": "Sales (Japan)",
         "company_code": "1000", "cost_center_code": "CC-SALES-JP"},
        {"department_code": "PROD-JP", "name": "Production (Japan)",
         "company_code": "1000", "cost_center_code": "CC-PROD-JP"},
        {"department_code": "RND", "name": "R&D (Japan)",
         "company_code": "1000", "cost_center_code": "CC-RND-JP"},
        {"department_code": "PROC-JP", "name": "Procurement (Japan)",
         "company_code": "1000", "cost_center_code": "CC-PROC-JP"},
        {"department_code": "SALES-TW", "name": "Sales (Taiwan)",
         "company_code": "3000", "cost_center_code": "CC-SALES-TW"},
    ]
    for spec in departments:
        try:
            d = dept_svc.create(hr_schemas.DepartmentCreate(**spec),
                               CLIENT_ID, admin.email)
            db.commit()
            print(f"  ✓ Dept {d.department_code:<10}  {d.name}")
        except Exception:
            db.rollback()
            print(f"  · skip {spec['department_code']} (exists)")

    employees = [
        {"first_name": "Hiroshi", "last_name": "Tanaka",
         "email": "h.tanaka@example.com",
         "company_code": "1000", "department_code": "SALES-JP",
         "job_title": "Sales Manager", "hire_date": date(2018, 4, 1),
         "base_salary": "8000000", "salary_currency": "JPY"},
        {"first_name": "Akiko", "last_name": "Suzuki",
         "email": "a.suzuki@example.com",
         "company_code": "1000", "department_code": "PROD-JP",
         "job_title": "Production Director", "hire_date": date(2015, 4, 1),
         "base_salary": "10500000", "salary_currency": "JPY"},
        {"first_name": "Kenji", "last_name": "Yamada",
         "email": "k.yamada@example.com",
         "company_code": "1000", "department_code": "RND",
         "job_title": "Senior Researcher", "hire_date": date(2017, 10, 1),
         "base_salary": "9200000", "salary_currency": "JPY"},
        {"first_name": "Yuki", "last_name": "Watanabe",
         "email": "y.watanabe@example.com",
         "company_code": "1000", "department_code": "PROC-JP",
         "job_title": "Procurement Lead", "hire_date": date(2019, 7, 1),
         "base_salary": "7600000", "salary_currency": "JPY"},
        {"first_name": "Mei-Ling", "last_name": "Chen",
         "email": "ml.chen@example.com",
         "company_code": "3000", "department_code": "SALES-TW",
         "job_title": "Sales Engineer", "hire_date": date(2020, 3, 1),
         "base_salary": "1800000", "salary_currency": "TWD"},
    ]
    from decimal import Decimal as D
    for spec in employees:
        if spec.get("base_salary"):
            spec["base_salary"] = D(spec["base_salary"])
        try:
            e = emp_svc.create(hr_schemas.EmployeeCreate(**spec),
                              CLIENT_ID, admin.email)
            db.commit()
            print(f"  ✓ Emp {e.employee_code}  {e.first_name} {e.last_name:<12} "
                  f"({e.department_code}, {e.job_title})")
        except Exception as exc:
            db.rollback()
            print(f"  · skip {spec['email']}: {exc}")


# ==================================================================
# Step 5: Generate sample PDFs
# ==================================================================
def _generate_sample_pdfs(db: Session):
    print("\n[⑦ Generate sample invoice PDFs]")
    from app.modules.mdm.models import BusinessPartner, Company, Material

    bills = db.query(BillingDocument).filter(
        BillingDocument.client_id == CLIENT_ID,
    ).order_by(BillingDocument.id).all()

    if not bills:
        print("  · no billings to render")
        return

    # Map billing -> variant by customer pattern
    seller = db.query(Company).filter(
        Company.client_id == CLIENT_ID, Company.country == "JP",
    ).first()
    if not seller:
        print("  · no seller (JP) company; skipping PDFs")
        return

    output_dir = Path("/tmp/erp_invoices")
    output_dir.mkdir(parents=True, exist_ok=True)

    for bill in bills:
        customer = db.query(BusinessPartner).filter(
            BusinessPartner.bp_code == bill.customer_code,
            BusinessPartner.client_id == CLIENT_ID,
        ).first()
        if not customer:
            continue

        # Decide variant based on the customer naming convention in seed.py
        if bill.customer_code.startswith("BP-1000"):
            variant = "intercompany"
        elif bill.customer_code.startswith("BP-2000"):
            variant = "distributor"
        else:
            variant = "enduser"

        codes = {it.material_code for it in bill.items}
        descs = {m.material_code: m.description for m in db.query(Material).filter(
            Material.client_id == CLIENT_ID,
            Material.material_code.in_(codes),
        ).all()}

        pdf = InvoicePdfGenerator(variant=variant).render(
            billing=bill, customer=customer, seller_company=seller,
            material_descriptions=descs,
        )
        out = output_dir / f"invoice_{bill.document_number}_{variant}.pdf"
        out.write_bytes(pdf)
        print(f"  ✓ {out.name}  ({len(pdf):,} bytes, variant={variant})")
    print(f"  → PDFs written to {output_dir}")


# ==================================================================
# Main
# ==================================================================
def main():
    print("=" * 78)
    print("  Mini Global ERP - FI / HR / PDF Seed")
    print("=" * 78)

    create_all_tables()
    db = SessionLocal()
    try:
        admin = _ensure_admin(db)
        if not admin:
            raise SystemExit("Run scripts/seed.py first.")

        _seed_chart_of_accounts(db, admin)
        _auto_post_billings(db, admin)
        _auto_post_grs(db, admin)
        _auto_post_irs(db, admin)
        _show_trial_balance(db)
        _seed_hr(db, admin)
        _generate_sample_pdfs(db)

        print("\n" + "=" * 78)
        print("  ✓ FI/HR/PDF seed complete.")
        print("=" * 78)
        print("  Try these endpoints:")
        print("    GET  /fi/accounting-docs")
        print("    GET  /fi/accounting-docs/trial-balance/")
        print("    GET  /hr/employees")
        print("    GET  /sd/billing/{id}/pdf?variant=intercompany")
    finally:
        db.close()


if __name__ == "__main__":
    main()
