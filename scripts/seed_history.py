#!/usr/bin/env python3
"""Comprehensive historical data seeder — past 12 months (FY2025-07 to FY2026-06).

Generates realistic data for a specialty semiconductor-materials company:
  - Photoresists, CMP slurries, etchants, process gases
  - Domestic + international customers (TW, KR, US, DE, NL, CN, SG)
  - Export-controlled ECCN 3C001 items with trade compliance review
  - Past 12 months: COMPLETED SOs → Deliveries → Export Declarations → Billings
  - Past 12 months: COMPLETED Production Orders → raw material POs/GRs
  - Forward 6 months (2026-07 to 2026-12): Sales Forecasts (PIR)
  - Updated stock balances

Usage:
    python scripts/seed_history.py
"""
import sys, os, random, uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(42)

# ── register all models ────────────────────────────────────────
import app.modules.mdm.models
import app.modules.sd.models
import app.modules.pp.models
import app.modules.pp.execution_models
import app.modules.fi.models
import app.modules.hr.models
import app.modules.mm.models
import app.modules.gts.models
import app.modules.co.models
import app.modules.qm.models

from app.core.database import SessionLocal, create_all_tables
from app.core.numbering import next_number

from app.modules.mdm.models import Material, BusinessPartner
from app.modules.sd.models import (
    SalesOrder, SalesOrderItem, Delivery, DeliveryItem,
    BillingDocument, BillingItem, SalesForecast,
)
from app.modules.mm.models import (
    PurchaseOrder, PurchaseOrderItem, GoodsReceipt, GoodsReceiptItem, StockBalance,
)
from app.modules.pp.execution_models import (
    ProcessOrder, ProcessOrderComponent, Batch,
)
from app.modules.gts.models import ExportDeclaration

CLIENT_ID  = "DEMO"
PLANT_CODE = "JP01"        # main plant
SALES_ORG  = "SO-JP"
USER       = "seed@example.com"
TAX_RATE   = Decimal("0.10")
USD_JPY    = Decimal("150")   # exchange rate for export declaration USD values

# ── Product catalogue ──────────────────────────────────────────
# (material_code, unit, unit_price_jpy, eccn, base_monthly_qty, coo)
PRODUCTS = [
    ("MAT-1000001", "KG",  Decimal("85000"),  "EAR99",  1000,  "JP"),  # ArF photoresist
    ("MAT-1000002", "KG",  Decimal("62000"),  "EAR99",  2000,  "JP"),  # KrF photoresist
    ("MAT-1000003", "KG",  Decimal("240000"), "EAR99",  40,    "JP"),  # EUV photoresist (pilot)
    ("MAT-2000001", "KG",  Decimal("12500"),  "EAR99",  15000, "JP"),  # CMP Slurry W
    ("MAT-2000002", "KG",  Decimal("14800"),  "EAR99",  12000, "JP"),  # CMP Slurry Cu
    ("MAT-3000001", "L",   Decimal("3800"),   "3C001",  8000,  "JP"),  # BOE etchant - controlled
    ("MAT-4000001", "CYL", Decimal("98000"),  "3C001",  80,    "JP"),  # Silane gas - controlled
    ("MAT-4000002", "CYL", Decimal("145000"), "3C001",  30,    "JP"),  # WF6 - controlled
]
PROD_MAP = {p[0]: p for p in PRODUCTS}

# ── Customer → product eligibility mapping ─────────────────────
# key = bp_code, value = list of material_codes they buy
CUST_PRODUCTS = {
    # International customers
    "BP-1000001": ["MAT-1000001", "MAT-1000002", "MAT-2000001", "MAT-4000001"],  # US
    "BP-1000002": ["MAT-1000001", "MAT-1000002", "MAT-2000001", "MAT-2000002"],  # TW (NSC)
    "BP-1000003": ["MAT-1000001", "MAT-2000001", "MAT-2000002", "MAT-3000001"],  # KR
    "BP-2000001": ["MAT-1000002", "MAT-2000001", "MAT-2000002"],                 # TW (Pacific)
    "BP-2000002": ["MAT-3000001", "MAT-4000001"],                                # DE
    "BP-3000001": ["MAT-1000001", "MAT-1000003", "MAT-2000001"],                 # TW Apex Foundry
    "BP-3000002": ["MAT-2000001", "MAT-2000002"],                                # KR Helios
    "BP-3000003": ["MAT-1000001", "MAT-4000001"],                                # US Sunrise
    "BP-3000004": ["MAT-1000002", "MAT-2000001"],                                # US Northern Si
    # Domestic JP
    "CUST-JP-01": ["MAT-1000001", "MAT-1000002", "MAT-2000001", "MAT-3000001", "MAT-4000001", "MAT-4000002"],
    "CUST-JP-02": ["MAT-2000001", "MAT-3000001", "MAT-4000002"],
    "CUST-JP-03": ["MAT-4000001", "MAT-4000002"],
    # Other international
    "CUST-NL-01": ["MAT-1000003", "MAT-1000001"],   # ASML — EUV photoresist
    "CUST-KR-01": ["MAT-1000001", "MAT-2000001", "MAT-2000002"],
    "CUST-TW-01": ["MAT-1000001", "MAT-1000002", "MAT-2000001"],
    "CUST-DE-01": ["MAT-3000001", "MAT-2000001"],
    "CUST-SG-01": ["MAT-1000002", "MAT-2000001"],
    "CUST-CN-01": ["MAT-2000001", "MAT-3000001"],  # China — high risk for 3C001
}
INTL_CUSTOMERS = {k for k, v in CUST_PRODUCTS.items() if not k.startswith("CUST-JP")}

# ── Raw material → product BOM mapping ────────────────────────
# raw_mat: (material_code, qty_per_unit_of_fert, unit)
BOM = {
    "MAT-1000001": [("MAT-9000001", 1.05, "KG"), ("MAT-9000002", 0.02, "L"), ("MAT-9000003", 0.005, "KG")],
    "MAT-1000002": [("MAT-9000001", 1.03, "KG"), ("MAT-9000003", 0.004, "KG")],
    "MAT-2000001": [("MAT-9000001", 0.30, "KG"), ("MAT-9000004", 0.05, "L")],
    "MAT-2000002": [("MAT-9000001", 0.30, "KG"), ("MAT-9000004", 0.04, "L")],
    "MAT-3000001": [("MAT-9000002", 0.40, "L"), ("MAT-9000003", 0.10, "KG")],
    "MAT-4000001": [("MAT-9000001", 0.50, "KG")],
    "MAT-4000002": [("MAT-9000001", 0.80, "KG")],
    "MAT-1000003": [("MAT-9000001", 1.10, "KG"), ("MAT-9000002", 0.03, "L")],
}

# ── Seasonal multipliers (month 7→6 = Jul→Jun) ────────────────
SEASON = {
    7: 0.82, 8: 0.78, 9: 0.88,          # summer slowdown
   10: 1.18, 11: 1.25, 12: 1.20,        # Q4 ramp
    1: 0.72, 2: 0.68, 3: 0.85,          # CNY + inventory correction
    4: 1.00, 5: 1.08, 6: 1.12,          # spring recovery
}

# ── Vendor mapping for raw material POs ──────────────────────
VENDOR_FOR_RAW = {
    "MAT-9000001": ("BP-5000001", "JP"),   # Tokyo Specialty Solvents
    "MAT-9000002": ("BP-5000002", "JP"),   # Osaka Hydrogen Peroxide
    "MAT-9000003": ("BP-5000003", "JP"),   # Kyushu Silica Particles
    "MAT-9000004": ("BP-5000004", "DE"),   # Bavarian Fluorine
}


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def month_range():
    """Yield (year, month) for past 12 months (oldest first)."""
    today = date.today()
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        months.append((y, m))
    return list(reversed(months))


def mid_month(year: int, month: int, offset_days: int = 0) -> date:
    return date(year, month, 15) + timedelta(days=offset_days)


def rand_qty(base: float, variance: float = 0.25) -> Decimal:
    """base ± variance%, rounded to 1 decimal."""
    v = base * (1 + random.uniform(-variance, variance))
    return Decimal(str(round(v, 1)))


def jpy_to_usd(jpy: Decimal) -> Decimal:
    return (jpy / USD_JPY).quantize(Decimal("0.01"))


def aitm_case(prefix: str, seq: int) -> str:
    return f"AI-TM-{prefix}-{seq:06d}"


def aitm_tx() -> str:
    return f"TX-{str(uuid.uuid4())[:8].upper()}"


def license_type_for_eccn(eccn: str, dest_country: str) -> str:
    """Determine export license type based on ECCN and destination."""
    if eccn in ("EAR99",):
        return "NLR"
    if eccn == "3C001":
        if dest_country in ("CN",):
            return "BIS_LICENSE"  # needs review
        if dest_country in ("TW", "KR", "SG", "JP"):
            return "NLR"
        return "NLR"
    return "NLR"


def is_export_controlled(eccn: str, dest_country: str) -> bool:
    return eccn not in ("EAR99",) and dest_country not in ("JP",)


def get_material(db, mat_code: str) -> Material:
    return db.query(Material).filter(
        Material.client_id == CLIENT_ID,
        Material.material_code == mat_code,
    ).first()


# ══════════════════════════════════════════════════════════════════════
# 1. Seed monthly sales orders + deliveries + billing
# ══════════════════════════════════════════════════════════════════════

def seed_month_sales(db, year: int, month: int, month_seq: int) -> dict:
    """Create 6-10 completed SOs for this month across customers.
    Returns dict of material_code → total qty sold (for production planning).
    """
    season_mult = SEASON[month]
    customers = list(CUST_PRODUCTS.keys())
    # Pick 7-10 customers for this month (rotate slightly)
    random.shuffle(customers)
    n_customers = random.randint(7, 10)
    active_customers = customers[:n_customers]

    total_sold: dict[str, Decimal] = {}
    seq_base = month_seq * 100

    for idx, cust_code in enumerate(active_customers):
        bp = db.query(BusinessPartner).filter(
            BusinessPartner.client_id == CLIENT_ID,
            BusinessPartner.bp_code == cust_code,
        ).first()
        if not bp:
            continue

        # Customer orders 1-3 products
        prods = CUST_PRODUCTS.get(cust_code, [])
        n_prods = min(len(prods), random.randint(1, 3))
        ordered_prods = random.sample(prods, n_prods)

        so_date    = mid_month(year, month, random.randint(-8, 5))
        del_date   = so_date + timedelta(days=random.randint(14, 28))
        bill_date  = del_date + timedelta(days=random.randint(3, 10))
        is_intl    = cust_code in INTL_CUSTOMERS

        # Build SO items
        items_data = []
        for mat_code in ordered_prods:
            _, unit, unit_price, eccn, base_qty, _ = PROD_MAP[mat_code]
            qty = rand_qty(base_qty * season_mult / n_customers)
            net = (qty * unit_price).quantize(Decimal("1"))
            items_data.append((mat_code, qty, unit, unit_price, net, eccn))

        if not items_data:
            continue

        total_net = sum(x[4] for x in items_data)

        # ── Sales Order ───────────────────────────────────────────
        ck_status = "APPROVED"
        ck_ref    = aitm_case("SO", seq_base + idx)
        # One historically blocked case (CN + controlled, old)
        if cust_code == "CUST-CN-01" and month in (8, 9) and month_seq < 6:
            ck_status = "BLOCKED"

        so = SalesOrder(
            client_id=CLIENT_ID,
            document_number=next_number(db, CLIENT_ID, "SALES_ORDER"),
            document_date=so_date,
            sales_org_code=SALES_ORG,
            customer_code=cust_code,
            customer_po_number=f"PO-{cust_code[-4:]}-{year}{month:02d}-{idx+1:02d}",
            requested_delivery_date=del_date,
            incoterms="CIF" if is_intl else "DDP",
            payment_terms="NET30" if is_intl else "NET60",
            currency="USD" if is_intl else "JPY",
            total_amount=total_net if not is_intl else total_net / USD_JPY,
            status="COMPLETED",
            export_check_status=ck_status,
            export_check_ref=ck_ref,
            created_by=USER, updated_by=USER,
        )
        db.add(so)
        db.flush()

        # SO Items
        for item_no, (mat_code, qty, unit, unit_price, net, eccn) in enumerate(items_data, start=10):
            db.add(SalesOrderItem(
                sales_order_id=so.id,
                item_no=item_no,
                material_code=mat_code,
                quantity=qty,
                unit=unit,
                unit_price=unit_price if not is_intl else unit_price / USD_JPY,
                net_amount=net if not is_intl else net / USD_JPY,
                plant_code=PLANT_CODE,
                created_by=USER, updated_by=USER,
            ))
            total_sold[mat_code] = total_sold.get(mat_code, Decimal("0")) + qty

        db.flush()

        # ── Delivery ──────────────────────────────────────────────
        aitm_case_no = aitm_case("DEL", seq_base + idx) if is_intl else None
        aitm_appr    = "APPROVED" if ck_status == "APPROVED" else "BLOCKED"

        deliv = Delivery(
            client_id=CLIENT_ID,
            document_number=next_number(db, CLIENT_ID, "DELIVERY"),
            document_date=del_date - timedelta(days=2),
            sales_order_id=so.id,
            plant_code=PLANT_CODE,
            actual_delivery_date=del_date,
            aitm_case_no=aitm_case_no,
            aitm_approval_status=aitm_appr if is_intl else None,
            status="COMPLETED",
            created_by=USER, updated_by=USER,
        )
        db.add(deliv)
        db.flush()

        for item_no, (mat_code, qty, unit, *_) in enumerate(items_data, start=10):
            db.add(DeliveryItem(
                delivery_id=deliv.id,
                item_no=item_no,
                material_code=mat_code,
                quantity=qty,
                unit=unit,
                created_by=USER, updated_by=USER,
            ))

        db.flush()

        # ── Export Declarations (international only) ──────────────
        if is_intl:
            for mat_code, qty, unit, unit_price, net, eccn in items_data:
                dest_country = bp.country
                lic_type = license_type_for_eccn(eccn, dest_country)
                decl_value_usd = jpy_to_usd(net)
                db.add(ExportDeclaration(
                    client_id=CLIENT_ID,
                    delivery_id=deliv.id,
                    sales_order_id=so.id,
                    ai_tm_transaction_id=aitm_tx(),
                    declaration_number=next_number(db, CLIENT_ID, "EXPD"),
                    license_type=lic_type,
                    destination_country=dest_country,
                    material_code=mat_code,
                    hs_code=get_material(db, mat_code).hs_code if get_material(db, mat_code) else None,
                    eccn=eccn,
                    quantity=qty,
                    quantity_unit=unit,
                    declared_value_usd=decl_value_usd,
                    status="CLEARED" if ck_status == "APPROVED" else "FLAGGED",
                ))
            db.flush()

        # ── Billing Document ──────────────────────────────────────
        gross = (total_net * (1 + TAX_RATE)).quantize(Decimal("1")) if not is_intl else total_net / USD_JPY
        bill = BillingDocument(
            client_id=CLIENT_ID,
            document_number=next_number(db, CLIENT_ID, "BILLING"),
            document_date=bill_date,
            sales_order_id=so.id,
            delivery_id=deliv.id,
            customer_code=cust_code,
            currency="USD" if is_intl else "JPY",
            net_amount=total_net if not is_intl else total_net / USD_JPY,
            tax_amount=total_net * TAX_RATE if not is_intl else Decimal("0"),
            gross_amount=gross,
            payment_terms=so.payment_terms,
            aitm_case_no=aitm_case_no,
            status="CLEARED",
            created_by=USER, updated_by=USER,
        )
        db.add(bill)
        db.flush()
        for item_no, (mat_code, qty, unit, unit_price, net, _) in enumerate(items_data, start=10):
            db.add(BillingItem(
                billing_document_id=bill.id,
                item_no=item_no,
                material_code=mat_code,
                quantity=qty,
                unit_price=unit_price if not is_intl else unit_price / USD_JPY,
                net_amount=net if not is_intl else net / USD_JPY,
                created_by=USER, updated_by=USER,
            ))
        db.flush()

    return total_sold


# ══════════════════════════════════════════════════════════════════════
# 2. Seed monthly production orders
# ══════════════════════════════════════════════════════════════════════

def seed_month_production(db, year: int, month: int, demand: dict[str, Decimal]):
    """Create 2-3 completed production orders to fulfill monthly demand."""
    # Production runs start 3-4 weeks before delivery
    prod_date = mid_month(year, month, -15)
    end_date  = mid_month(year, month, -3)

    # Find available production versions
    from app.modules.pp.models import ProductionVersion
    pvs = {pv.material_code: pv.version_code
           for pv in db.query(ProductionVersion).filter(
               ProductionVersion.client_id == CLIENT_ID).all()}

    for mat_code, qty in demand.items():
        if qty <= 0 or mat_code not in BOM:
            continue
        # Split large batches into 1-2 production orders
        batch_count = 2 if qty > 5000 else 1
        per_batch = qty / batch_count

        for b in range(batch_count):
            pv_code = pvs.get(mat_code, "PV-DEFAULT")
            order_no = next_number(db, CLIENT_ID, "PROCESS_ORDER")
            actual_qty = per_batch * Decimal(str(random.uniform(0.97, 1.02)))

            order = ProcessOrder(
                client_id=CLIENT_ID,
                document_number=order_no,
                material_code=mat_code,
                plant_code="1000",
                production_version_code=pv_code,
                target_quantity=per_batch.quantize(Decimal("1")),
                target_unit=PROD_MAP[mat_code][1],
                actual_quantity=actual_qty.quantize(Decimal("0.1")),
                scrapped_quantity=Decimal("0"),
                scheduled_start=datetime.combine(prod_date + timedelta(days=b*7), datetime.min.time()),
                scheduled_end=datetime.combine(end_date + timedelta(days=b*7), datetime.min.time()),
                actual_start=datetime.combine(prod_date + timedelta(days=b*7+1), datetime.min.time()),
                actual_end=datetime.combine(end_date + timedelta(days=b*7-1), datetime.min.time()),
                status="COMPLETED",
                created_by=USER, updated_by=USER,
            )
            db.add(order)
            db.flush()

            # Components
            for raw_code, qty_per_unit, raw_unit in BOM.get(mat_code, []):
                planned = (per_batch * Decimal(str(qty_per_unit))).quantize(Decimal("0.01"))
                issued  = (planned * Decimal(str(random.uniform(0.99, 1.02)))).quantize(Decimal("0.01"))
                db.add(ProcessOrderComponent(
                    process_order_id=order.id,
                    item_no=BOM[mat_code].index((raw_code, qty_per_unit, raw_unit)) * 10 + 10,
                    material_code=raw_code,
                    planned_quantity=planned,
                    issued_quantity=issued,
                    unit=raw_unit,
                    created_by=USER, updated_by=USER,
                ))
            db.flush()


# ══════════════════════════════════════════════════════════════════════
# 3. Seed raw material procurement (PO + GR)
# ══════════════════════════════════════════════════════════════════════

def seed_month_procurement(db, year: int, month: int, demand: dict[str, Decimal]):
    """Create completed POs for raw materials needed for production."""
    po_date = mid_month(year, month, -25)  # ordered 5 weeks before production

    # Aggregate raw material needs
    raw_needs: dict[str, Decimal] = {}
    for mat_code, qty in demand.items():
        for raw_code, qty_per_unit, raw_unit in BOM.get(mat_code, []):
            needed = qty * Decimal(str(qty_per_unit)) * Decimal("1.05")  # 5% safety stock
            raw_needs[raw_code] = raw_needs.get(raw_code, Decimal("0")) + needed

    for raw_code, needed_qty in raw_needs.items():
        if raw_code not in VENDOR_FOR_RAW:
            continue
        vendor_code, vendor_country = VENDOR_FOR_RAW[raw_code]

        mat = db.query(Material).filter(
            Material.client_id == CLIENT_ID,
            Material.material_code == raw_code,
        ).first()
        if not mat or not mat.standard_price:
            unit_price = Decimal("500")
        else:
            unit_price = mat.standard_price

        needed_qty = needed_qty.quantize(Decimal("1"))
        net_amount = (needed_qty * unit_price).quantize(Decimal("1"))

        po = PurchaseOrder(
            client_id=CLIENT_ID,
            document_number=next_number(db, CLIENT_ID, "PURCHASE_ORDER"),
            document_date=po_date,
            vendor_code=vendor_code,
            currency="JPY" if vendor_country == "JP" else "USD",
            total_amount=net_amount,
            status="COMPLETED",
            created_by=USER, updated_by=USER,
        )
        db.add(po)
        db.flush()

        poi = PurchaseOrderItem(
            purchase_order_id=po.id,
            item_no=10,
            material_code=raw_code,
            quantity=needed_qty,
            unit=mat.base_unit if mat else "KG",
            unit_price=unit_price,
            net_amount=net_amount,
            plant_code=PLANT_CODE,
            received_quantity=needed_qty,
            invoiced_quantity=needed_qty,
            created_by=USER, updated_by=USER,
        )
        db.add(poi)
        db.flush()

        # Goods Receipt
        gr_date = po_date + timedelta(days=random.randint(10, 20))
        gr = GoodsReceipt(
            client_id=CLIENT_ID,
            document_number=next_number(db, CLIENT_ID, "GOODS_RECEIPT"),
            document_date=gr_date,
            purchase_order_id=po.id,
            plant_code=PLANT_CODE,
            posting_date=gr_date,
            status="COMPLETED",
            created_by=USER, updated_by=USER,
        )
        db.add(gr)
        db.flush()

        db.add(GoodsReceiptItem(
            goods_receipt_id=gr.id,
            po_item_id=poi.id,
            item_no=10,
            material_code=raw_code,
            quantity=needed_qty,
            unit=mat.base_unit if mat else "KG",
            storage_location="0001",
            created_by=USER, updated_by=USER,
        ))
        db.flush()


# ══════════════════════════════════════════════════════════════════════
# 4. Update stock balances
# ══════════════════════════════════════════════════════════════════════

def update_stock_balances(db, all_production: dict[str, Decimal],
                          all_demand: dict[str, Decimal]):
    """Set stock balances to reflect end-of-period state."""
    # Finished goods: production - sales + safety stock (10%)
    for mat_code, produced in all_production.items():
        sold = all_demand.get(mat_code, Decimal("0"))
        net = (produced - sold) * Decimal("0.05")  # ~5% ending stock
        net = max(net, Decimal("0"))

        existing = db.query(StockBalance).filter(
            StockBalance.client_id == CLIENT_ID,
            StockBalance.material_code == mat_code,
            StockBalance.plant_code == "1000",
        ).first()
        if existing:
            existing.unrestricted_qty = net.quantize(Decimal("0.1"))
            existing.updated_by = USER
        else:
            db.add(StockBalance(
                client_id=CLIENT_ID,
                material_code=mat_code,
                plant_code="1000",
                storage_location="0001",
                unrestricted_qty=net.quantize(Decimal("0.1")),
                reserved_qty=Decimal("0"),
                stock_unit=PROD_MAP.get(mat_code, ("","KG"))[1],
                created_by=USER, updated_by=USER,
            ))

    # Raw materials: maintain ~4 weeks of supply
    raw_monthly: dict[str, Decimal] = {}
    for mat_code, qty in all_production.items():
        for raw_code, qty_per_unit, _ in BOM.get(mat_code, []):
            needed = qty * Decimal(str(qty_per_unit))
            raw_monthly[raw_code] = raw_monthly.get(raw_code, Decimal("0")) + needed
    avg_monthly = {k: v / 12 for k, v in raw_monthly.items()}

    for raw_code, monthly_avg in avg_monthly.items():
        safety = (monthly_avg * Decimal("1.2")).quantize(Decimal("1"))  # 6-week safety stock
        mat = db.query(Material).filter(
            Material.client_id == CLIENT_ID, Material.material_code == raw_code).first()
        existing = db.query(StockBalance).filter(
            StockBalance.client_id == CLIENT_ID,
            StockBalance.material_code == raw_code,
            StockBalance.plant_code == PLANT_CODE,
        ).first()
        if existing:
            existing.unrestricted_qty = safety
            existing.updated_by = USER
        else:
            db.add(StockBalance(
                client_id=CLIENT_ID,
                material_code=raw_code,
                plant_code=PLANT_CODE,
                storage_location="0001",
                unrestricted_qty=safety,
                reserved_qty=Decimal("0"),
                stock_unit=mat.base_unit if mat else "KG",
                created_by=USER, updated_by=USER,
            ))
    db.flush()


# ══════════════════════════════════════════════════════════════════════
# 5. Seed Sales Forecasts (PIR) — forward 6 months
# ══════════════════════════════════════════════════════════════════════

def seed_forecasts(db, historical_avg: dict[str, Decimal]):
    """Seed 6 months of forward forecasts based on historical average × growth."""
    today = date.today()
    growth = Decimal("1.05")  # 5% YoY growth assumption

    forward_months = []
    y, m = today.year, today.month
    for _ in range(6):
        m += 1
        if m > 12:
            m = 1
            y += 1
        forward_months.append((y, m))

    print(f"  Seeding forecasts for: {forward_months}")
    for (f_year, f_month) in forward_months:
        season_mult = Decimal(str(SEASON[f_month]))
        for mat_code, (_, unit, unit_price, *_) in PROD_MAP.items():
            avg = historical_avg.get(mat_code, Decimal("0"))
            forecast_qty = (avg * season_mult * growth).quantize(Decimal("1"))
            forecast_val = (forecast_qty * unit_price).quantize(Decimal("1"))

            existing = db.query(SalesForecast).filter(
                SalesForecast.client_id == CLIENT_ID,
                SalesForecast.material_code == mat_code,
                SalesForecast.year == f_year,
                SalesForecast.month == f_month,
                SalesForecast.version == "BASELINE",
            ).first()
            if not existing:
                db.add(SalesForecast(
                    client_id=CLIENT_ID,
                    material_code=mat_code,
                    plant_code="1000",
                    year=f_year,
                    month=f_month,
                    forecast_quantity=forecast_qty,
                    quantity_unit=unit,
                    forecast_value=forecast_val,
                    currency="JPY",
                    version="BASELINE",
                    notes=f"システム自動生成: 過去実績 × {float(growth)*100:.0f}% 成長率 × 季節係数",
                    created_by=USER, updated_by=USER,
                ))
    db.flush()


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    create_all_tables()
    db = SessionLocal()

    try:
        months = month_range()
        print(f"Seeding {len(months)} months: {months[0]} → {months[-1]}")

        all_demand:     dict[str, Decimal] = {}
        all_production: dict[str, Decimal] = {}
        monthly_demand: dict[tuple, dict]  = {}

        for seq, (year, month) in enumerate(months):
            print(f"\n── {year}-{month:02d} (x{SEASON[month]:.2f}) ──")

            # Sales & delivery chain
            print("  [SD] Sales orders / deliveries / billing...")
            demand = seed_month_sales(db, year, month, seq)
            monthly_demand[(year, month)] = demand

            for k, v in demand.items():
                all_demand[k] = all_demand.get(k, Decimal("0")) + v

            # Production
            print("  [PP] Production orders...")
            seed_month_production(db, year, month, demand)
            for k, v in demand.items():
                all_production[k] = all_production.get(k, Decimal("0")) + v

            # Raw material procurement
            print("  [MM] Procurement (PO + GR)...")
            seed_month_procurement(db, year, month, demand)

            db.commit()
            print(f"  ✓ committed month {year}-{month:02d}")

        # Stock balances
        print("\n── Updating stock balances ──")
        update_stock_balances(db, all_production, all_demand)
        db.commit()

        # Sales forecasts
        print("\n── Seeding sales forecasts (PIR) ──")
        avg_monthly = {k: v / 12 for k, v in all_demand.items()}
        seed_forecasts(db, avg_monthly)
        db.commit()

        # Summary
        print("\n═══════ Seed Complete ═══════")
        from app.modules.sd.models import SalesOrder, Delivery, BillingDocument
        from app.modules.gts.models import ExportDeclaration
        from app.modules.mm.models import PurchaseOrder, StockBalance
        from app.modules.pp.execution_models import ProcessOrder

        print(f"  SalesOrders:       {db.query(SalesOrder).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  Deliveries:        {db.query(Delivery).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  BillingDocuments:  {db.query(BillingDocument).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  ExportDeclarations:{db.query(ExportDeclaration).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  PurchaseOrders:    {db.query(PurchaseOrder).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  ProcessOrders:     {db.query(ProcessOrder).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  StockBalances:     {db.query(StockBalance).filter_by(client_id=CLIENT_ID).count():>6}")
        print(f"  SalesForecasts:    {db.query(SalesForecast).filter_by(client_id=CLIENT_ID).count():>6}")

        print(f"\n  Top materials by annual demand:")
        for mat, qty in sorted(all_demand.items(), key=lambda x: -x[1])[:5]:
            print(f"    {mat}: {float(qty):,.0f} {PROD_MAP.get(mat, ('','unit'))[1]}")

    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
