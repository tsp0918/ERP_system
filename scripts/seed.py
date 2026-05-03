"""Seed dummy data for a semiconductor materials manufacturer.

Persona: Japan-headquartered specialty chemicals company supplying photoresists,
CMP slurries, etchants, and process gases to global semiconductor fabs.

Generates:
- 1 client + admin user
- 5 companies (JP HQ + US/TW/KR/SG subsidiaries)
- ~15 materials across product families + raw materials
- ~20 business partners:
    * Group entities (intercompany / transfer pricing)
    * Overseas distributors
    * Overseas end-users (fabs)
    * Chemical suppliers / packaging vendors
- 3 sales orders illustrating the three invoicing patterns:
    * Intercompany (transfer pricing to overseas plant)
    * Distributor sale
    * End-user direct sale
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# Allow running as `python scripts/seed.py` from project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.core.auth import hash_password
from app.core.auth_models import User
from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.gts.service import GTSService
from app.modules.mdm.models import BusinessPartner, Company, Material
from app.modules.mdm import schemas as mdm_schemas
from app.modules.mdm.service import (
    BusinessPartnerService, CompanyService, MaterialService,
)
from app.modules.sd import schemas as sd_schemas
from app.modules.sd.service import (
    BillingService, DeliveryService, SalesOrderService,
)


CLIENT_ID = "DEMO"
ADMIN_EMAIL = settings.INITIAL_ADMIN_EMAIL


# ==================================================================
# Master data definitions
# ==================================================================
COMPANIES = [
    {"company_code": "1000", "name": "Nihon Specialty Chemicals K.K.",
     "country": "JP", "currency": "JPY"},
    {"company_code": "2000", "name": "NSC Electronic Materials USA, Inc.",
     "country": "US", "currency": "USD"},
    {"company_code": "3000", "name": "NSC Taiwan Materials Co., Ltd.",
     "country": "TW", "currency": "TWD"},
    {"company_code": "4000", "name": "NSC Korea Advanced Materials Ltd.",
     "country": "KR", "currency": "KRW"},
    {"company_code": "5000", "name": "NSC Singapore Pte. Ltd.",
     "country": "SG", "currency": "SGD"},
]


# Product families for a semiconductor materials maker
MATERIALS = [
    # Photoresists (ArF/KrF/EUV families)
    {"material_code": "MAT-1000001", "description": "ArF Immersion Photoresist NSP-AR450",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.05", "standard_price": "85000", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-1000002", "description": "KrF Photoresist NSP-KR220",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.02", "standard_price": "62000", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-1000003", "description": "EUV Photoresist NSP-EUV13 (Pilot Lot)",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.08", "standard_price": "240000", "currency": "JPY",
     "country_of_origin": "JP"},

    # CMP slurries
    {"material_code": "MAT-2000001", "description": "CMP Slurry for Tungsten NSC-WSL30",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.20", "standard_price": "12500", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-2000002", "description": "CMP Slurry for Copper NSC-CuS18",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.15", "standard_price": "14800", "currency": "JPY",
     "country_of_origin": "JP"},

    # Etchants & cleans
    {"material_code": "MAT-3000001", "description": "Buffered Oxide Etchant BOE-7:1",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.10", "standard_price": "3800", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-3000002", "description": "SC-1 Cleaning Solution (Standard)",
     "material_type": "FERT", "base_unit": "L",
     "weight_kg": "1.05", "standard_price": "2200", "currency": "JPY",
     "country_of_origin": "JP"},

    # Process gases / precursors (export-controlled in mock)
    {"material_code": "MAT-4000001", "description": "High Purity Silane Gas SiH4 6N",
     "material_type": "FERT", "base_unit": "KG",
     "weight_kg": "1.00", "standard_price": "98000", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-4000002", "description": "Tungsten Hexafluoride Process Gas WF6",
     "material_type": "FERT", "base_unit": "KG",
     "weight_kg": "1.00", "standard_price": "145000", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-4000003", "description": "Hafnium Precursor for ALD HfCl4",
     "material_type": "FERT", "base_unit": "KG",
     "weight_kg": "1.00", "standard_price": "320000", "currency": "JPY",
     "country_of_origin": "JP"},

    # Raw materials (procurement side)
    {"material_code": "MAT-9000001", "description": "PGMEA Solvent (Electronic Grade)",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "1800", "currency": "JPY", "country_of_origin": "JP"},
    {"material_code": "MAT-9000002", "description": "Hydrogen Peroxide H2O2 31%",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "650", "currency": "JPY", "country_of_origin": "JP"},
    {"material_code": "MAT-9000003", "description": "Colloidal Silica Particle Slurry Base",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "4200", "currency": "JPY", "country_of_origin": "JP"},
    {"material_code": "MAT-9000004", "description": "Photoacid Generator PAG-Resin Polymer",
     "material_type": "HALB", "base_unit": "KG",
     "standard_price": "28500", "currency": "JPY", "country_of_origin": "JP"},

    # Packaging
    {"material_code": "MAT-9100001", "description": "HDPE Chemical Drum 200L (Cleanroom Grade)",
     "material_type": "HAWA", "base_unit": "PC",
     "standard_price": "8500", "currency": "JPY", "country_of_origin": "JP"},
]


# ------------------------------------------------------------------
# Business Partners - 4 categories
# ------------------------------------------------------------------
BUSINESS_PARTNERS = [
    # ---- Group / Intercompany (transfer pricing destinations) ----
    {"bp_code": "BP-1000001", "name": "NSC Electronic Materials USA, Inc.",
     "country": "US", "roles": "CUSTOMER",
     "city": "Phoenix, AZ", "address_line1": "1500 Semiconductor Blvd",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "5000000",
     "_note": "Intercompany - transfer pricing"},
    {"bp_code": "BP-1000002", "name": "NSC Taiwan Materials Co., Ltd.",
     "country": "TW", "roles": "CUSTOMER",
     "city": "Hsinchu", "address_line1": "Hsinchu Science Park, Section 3",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "8000000",
     "_note": "Intercompany - transfer pricing"},
    {"bp_code": "BP-1000003", "name": "NSC Korea Advanced Materials Ltd.",
     "country": "KR", "roles": "CUSTOMER",
     "city": "Hwaseong", "address_line1": "Banwol Industrial Complex, Block 7",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "6000000",
     "_note": "Intercompany - transfer pricing"},
    {"bp_code": "BP-1000004", "name": "NSC Singapore Pte. Ltd.",
     "country": "SG", "roles": "CUSTOMER",
     "city": "Jurong", "address_line1": "12 Jurong Industrial Way",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "3000000",
     "_note": "Intercompany - regional hub"},

    # ---- Overseas Distributors ----
    {"bp_code": "BP-2000001", "name": "Pacific Electronic Chemicals Distribution Ltd.",
     "country": "TW", "roles": "CUSTOMER",
     "city": "Taipei", "address_line1": "8F, No.123 Nanjing E. Rd",
     "currency": "USD", "payment_terms": "NET45",
     "credit_limit": "1500000",
     "_note": "Authorized distributor for Taiwan SME fabs"},
    {"bp_code": "BP-2000002", "name": "Eurasia Specialty Materials GmbH",
     "country": "DE", "roles": "CUSTOMER",
     "city": "Dresden", "address_line1": "Industriestrasse 45",
     "currency": "EUR", "payment_terms": "NET60",
     "credit_limit": "2000000",
     "_note": "EU distributor (Dresden / Eindhoven coverage)"},
    {"bp_code": "BP-2000003", "name": "ChemTech Solutions Israel Ltd.",
     "country": "IL", "roles": "CUSTOMER",
     "city": "Kiryat Gat", "address_line1": "5 HaTaasiya St",
     "currency": "USD", "payment_terms": "NET45",
     "credit_limit": "800000",
     "_note": "Israel distributor"},

    # ---- Overseas End-users (fictional fab operators) ----
    {"bp_code": "BP-3000001", "name": "Apex Foundry Corporation",
     "country": "TW", "roles": "CUSTOMER",
     "city": "Tainan", "address_line1": "Southern Taiwan Science Park, Phase 6",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "20000000",
     "_note": "Tier-1 foundry end-user"},
    {"bp_code": "BP-3000002", "name": "Helios Memory Systems Co.",
     "country": "KR", "roles": "CUSTOMER",
     "city": "Icheon", "address_line1": "467 Bagae-ro, Bubal-eup",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "15000000",
     "_note": "Memory IDM end-user"},
    {"bp_code": "BP-3000003", "name": "Sunrise Logic Devices Inc.",
     "country": "US", "roles": "CUSTOMER",
     "city": "Hillsboro, OR", "address_line1": "2501 NW Compass Way",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "12000000",
     "_note": "Logic IDM end-user"},
    {"bp_code": "BP-3000004", "name": "Northern Silicon Technologies",
     "country": "US", "roles": "CUSTOMER",
     "city": "Boise, ID", "address_line1": "8000 S Federal Way",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "9000000",
     "_note": "Memory IDM end-user"},
    {"bp_code": "BP-3000005", "name": "Yangtze Photonics Manufacturing",
     "country": "CN", "roles": "CUSTOMER",
     "city": "Wuxi", "address_line1": "23 Linghu Avenue, Xinwu District",
     "currency": "USD", "payment_terms": "NET30",
     "credit_limit": "5000000",
     "_note": "China end-user (subject to export controls)"},

    # ---- Chemical / Material Suppliers ----
    {"bp_code": "BP-5000001", "name": "Tokyo Specialty Solvents Corp.",
     "country": "JP", "roles": "VENDOR",
     "city": "Kawasaki", "address_line1": "Daishi Industrial District 4-12",
     "currency": "JPY", "payment_terms": "NET60",
     "_note": "PGMEA / electronic-grade solvents"},
    {"bp_code": "BP-5000002", "name": "Osaka Hydrogen Peroxide Industries",
     "country": "JP", "roles": "VENDOR",
     "city": "Osaka", "address_line1": "Sakai Coastal Industrial Zone, Plant 3",
     "currency": "JPY", "payment_terms": "NET60",
     "_note": "H2O2 supplier"},
    {"bp_code": "BP-5000003", "name": "Kyushu Silica Particles Ltd.",
     "country": "JP", "roles": "VENDOR",
     "city": "Kitakyushu", "address_line1": "Wakamatsu Eco-Town 7",
     "currency": "JPY", "payment_terms": "NET45",
     "_note": "Colloidal silica particles for CMP"},
    {"bp_code": "BP-5000004", "name": "Bavarian Fluorine Chemicals AG",
     "country": "DE", "roles": "VENDOR",
     "city": "Munich", "address_line1": "Chemiepark Süd, Building 12",
     "currency": "EUR", "payment_terms": "NET60",
     "_note": "Specialty fluorine compounds"},
    {"bp_code": "BP-5000005", "name": "Gulf Coast Industrial Gases LLC",
     "country": "US", "roles": "VENDOR",
     "city": "Houston, TX", "address_line1": "10500 Bay Area Blvd",
     "currency": "USD", "payment_terms": "NET45",
     "_note": "High-purity gas supplier"},
    {"bp_code": "BP-5000006", "name": "Nagoya Polymer Synthesis K.K.",
     "country": "JP", "roles": "VENDOR",
     "city": "Nagoya", "address_line1": "Tobishima Industrial Park 22",
     "currency": "JPY", "payment_terms": "NET60",
     "_note": "Custom polymer / PAG synthesis"},

    # ---- Packaging & Logistics ----
    {"bp_code": "BP-6000001", "name": "Asia Cleanroom Container Co.",
     "country": "JP", "roles": "VENDOR",
     "city": "Yokohama", "address_line1": "Kanazawa Industrial Block 14",
     "currency": "JPY", "payment_terms": "NET30",
     "_note": "HDPE drums / cleanroom packaging"},
]


# ==================================================================
# Helpers
# ==================================================================
def _ensure_admin(db: Session) -> User:
    admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
    if admin:
        print(f"  ✓ Admin already exists: {ADMIN_EMAIL}")
        return admin
    admin = User(
        email=ADMIN_EMAIL,
        hashed_password=hash_password(settings.INITIAL_ADMIN_PASSWORD),
        full_name="Demo Administrator",
        is_active=True,
        is_superuser=True,
        client_id=CLIENT_ID,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"  ✓ Admin created: {ADMIN_EMAIL} / {settings.INITIAL_ADMIN_PASSWORD}")
    return admin


def _seed_companies(db: Session, admin: User):
    print("\n[Companies]")
    svc = CompanyService(db)
    existing = {c.company_code for c in db.query(Company).filter(
        Company.client_id == CLIENT_ID).all()}
    for spec in COMPANIES:
        if spec["company_code"] in existing:
            print(f"  · skip {spec['company_code']}")
            continue
        svc.create(mdm_schemas.CompanyCreate(**spec), CLIENT_ID, admin.email)
        print(f"  ✓ {spec['company_code']}  {spec['name']}  ({spec['country']}/{spec['currency']})")
    db.commit()


def _seed_materials(db: Session, admin: User):
    print("\n[Materials]")
    svc = MaterialService(db)
    existing = {m.material_code for m in db.query(Material).filter(
        Material.client_id == CLIENT_ID).all()}
    for spec in MATERIALS:
        if spec["material_code"] in existing:
            print(f"  · skip {spec['material_code']}")
            continue
        # Convert string decimals to Decimal
        clean = {**spec}
        for k in ("weight_kg", "standard_price"):
            if k in clean and clean[k] is not None:
                clean[k] = Decimal(str(clean[k]))
        # auto_classify=True triggers GTS
        payload = mdm_schemas.MaterialCreate(**clean, auto_classify=True)
        m = svc.create(payload, CLIENT_ID, admin.email)
        db.commit()
        print(f"  ✓ {m.material_code}  HS={m.hs_code or '-'}  ECCN={m.eccn or '-'}  "
              f"判定={m.fefta_judgment}  {m.description[:50]}")


def _seed_business_partners(db: Session, admin: User):
    print("\n[Business Partners]")
    svc = BusinessPartnerService(db)
    existing = {bp.bp_code for bp in db.query(BusinessPartner).filter(
        BusinessPartner.client_id == CLIENT_ID).all()}
    for spec in BUSINESS_PARTNERS:
        if spec["bp_code"] in existing:
            print(f"  · skip {spec['bp_code']}")
            continue
        clean = {k: v for k, v in spec.items() if not k.startswith("_")}
        if "credit_limit" in clean and clean["credit_limit"] is not None:
            clean["credit_limit"] = Decimal(str(clean["credit_limit"]))
        payload = mdm_schemas.BusinessPartnerCreate(**clean, auto_screen=True)
        bp = svc.create(payload, CLIENT_ID, admin.email)
        db.commit()
        flag = " 🚫 DENIED" if bp.is_denied_party else ""
        note = spec.get("_note", "")
        print(f"  ✓ {bp.bp_code}  {bp.country}  {bp.name[:40]:40s}  [{bp.roles}]{flag}  {note}")


def _seed_sales_orders(db: Session, admin: User):
    """Three SOs illustrating the three invoicing patterns."""
    print("\n[Sales Orders - 3 invoicing patterns]")
    so_svc = SalesOrderService(db)
    today = date.today()

    scenarios = [
        # ---- Pattern 1: Intercompany / Transfer Pricing ----
        {
            "label": "① INTERCOMPANY (transfer to overseas plant - TW subsidiary)",
            "payload": sd_schemas.SalesOrderCreate(
                sales_org_code="1000",
                customer_code="BP-1000002",  # NSC Taiwan
                customer_po_number="ICO-TW-2026-0145",
                document_date=today,
                requested_delivery_date=today + timedelta(days=14),
                incoterms="DAP",        # transfer pricing - delivered at plant
                payment_terms="NET30",
                currency="USD",
                items=[
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-2000001", quantity=Decimal("500"),
                        unit="L", unit_price=Decimal("78"),  # transfer price < market
                    ),
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-9000004", quantity=Decimal("50"),
                        unit="KG", unit_price=Decimal("180"),
                    ),
                ],
            ),
        },
        # ---- Pattern 2: Overseas Distributor (non-controlled items) ----
        {
            "label": "② DISTRIBUTOR sale (Taiwan distributor for SME fabs)",
            "payload": sd_schemas.SalesOrderCreate(
                sales_org_code="1000",
                customer_code="BP-2000001",  # Pacific Electronic Chemicals
                customer_po_number="PCD-2026-3318",
                document_date=today,
                requested_delivery_date=today + timedelta(days=21),
                incoterms="CIF",
                payment_terms="NET45",
                currency="USD",
                items=[
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-1000002", quantity=Decimal("80"),
                        unit="L", unit_price=Decimal("520"),
                    ),
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-3000002", quantity=Decimal("200"),
                        unit="L", unit_price=Decimal("18"),  # SC-1 cleaning (non-controlled)
                    ),
                ],
            ),
        },
        # ---- Pattern 3: Direct End-User (non-controlled items) ----
        {
            "label": "③ END-USER direct (Korean memory IDM)",
            "payload": sd_schemas.SalesOrderCreate(
                sales_org_code="1000",
                customer_code="BP-3000002",  # Helios Memory Systems
                customer_po_number="HMS-PR-2026-7821",
                document_date=today,
                requested_delivery_date=today + timedelta(days=10),
                incoterms="DDP",
                payment_terms="NET30",
                currency="USD",
                items=[
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-1000001", quantity=Decimal("120"),
                        unit="L", unit_price=Decimal("780"),
                    ),
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-2000002", quantity=Decimal("100"),
                        unit="L", unit_price=Decimal("145"),  # CMP slurry (non-controlled)
                    ),
                ],
            ),
        },
        # ---- Pattern 4: Compliance scenario (controlled item to China) ----
        {
            "label": "④ COMPLIANCE TEST (China end-user requesting controlled precursor)",
            "payload": sd_schemas.SalesOrderCreate(
                sales_org_code="1000",
                customer_code="BP-3000005",  # Yangtze Photonics (CN)
                customer_po_number="YPM-2026-0012",
                document_date=today,
                requested_delivery_date=today + timedelta(days=30),
                incoterms="FOB",
                payment_terms="NET30",
                currency="USD",
                items=[
                    sd_schemas.SalesOrderItemCreate(
                        material_code="MAT-4000003",  # HfCl4 (export-controlled)
                        quantity=Decimal("20"),
                        unit="KG", unit_price=Decimal("3500"),
                    ),
                ],
            ),
        },
    ]

    created_sos = []
    for s in scenarios:
        print(f"\n  {s['label']}")
        so = so_svc.create(s["payload"], CLIENT_ID, admin.email)
        db.commit()
        db.refresh(so)
        print(f"    ✓ SO#{so.document_number}  total={so.total_amount} {so.currency}  "
              f"status={so.status}  export={so.export_check_status}")
        if so.export_check_message:
            print(f"      └─ {so.export_check_message}")
        created_sos.append(so)

    return created_sos


def _seed_deliveries_and_billing(db: Session, admin: User, sales_orders):
    """For SOs that passed the export check, create delivery + billing."""
    print("\n[Deliveries & Billing - simulating order-to-cash]")
    delivery_svc = DeliveryService(db)
    billing_svc = BillingService(db)

    for so in sales_orders:
        if so.status == "BLOCKED":
            print(f"  ⚠ SO#{so.document_number} BLOCKED - skipping delivery")
            continue
        # Release first
        so_svc = SalesOrderService(db)
        try:
            so_svc.release(so.id, CLIENT_ID, admin.email)
            db.commit()
        except Exception as e:
            print(f"  ⚠ release failed for {so.document_number}: {e}")
            continue

        delivery = delivery_svc.create(sd_schemas.DeliveryCreate(
            sales_order_id=so.id,
            plant_code="P100",
            actual_delivery_date=date.today(),
        ), CLIENT_ID, admin.email)
        db.commit(); db.refresh(delivery)
        print(f"  ✓ Delivery#{delivery.document_number}  for SO#{so.document_number}")

        bill = billing_svc.create_from_delivery(sd_schemas.BillingCreate(
            delivery_id=delivery.id,
            payment_terms=so.payment_terms,
            tax_rate_percent=Decimal("0"),  # export = no domestic tax
        ), CLIENT_ID, admin.email)
        db.commit(); db.refresh(bill)
        print(f"  ✓ Invoice#{bill.document_number}  net={bill.net_amount} {bill.currency}  "
              f"to {bill.customer_code}")


# ==================================================================
# Main
# ==================================================================
def main():
    print("=" * 70)
    print("  Mini Global ERP - Semiconductor Materials Maker Seed")
    print("=" * 70)
    print(f"  Database: {settings.DATABASE_URL}")
    print(f"  AI_TM mode: {'MOCK' if settings.AI_TM_MOCK_MODE else 'LIVE'}")
    print(f"  Client ID: {CLIENT_ID}")

    create_all_tables()
    db = SessionLocal()
    try:
        admin = _ensure_admin(db)
        _seed_companies(db, admin)
        _seed_materials(db, admin)
        _seed_business_partners(db, admin)
        sales_orders = _seed_sales_orders(db, admin)
        _seed_deliveries_and_billing(db, admin, sales_orders)

        print("\n" + "=" * 70)
        print("  ✓ Seed complete.")
        print("=" * 70)
        print(f"  Login: {ADMIN_EMAIL} / {settings.INITIAL_ADMIN_PASSWORD}")
        print("  Start server: uvicorn app.main:app --reload --port 5000")
        print("  Docs:         http://localhost:5000/docs")
    finally:
        db.close()


if __name__ == "__main__":
    main()
