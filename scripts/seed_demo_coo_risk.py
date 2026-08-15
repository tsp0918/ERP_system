#!/usr/bin/env python3
"""
scripts/seed_demo_coo_risk.py
==============================
COO (Country of Origin) 原産地変更リスク デモデータ生成 + AI TM 連携

製品: CTRL-HC200 (高精度ハイブリッドコントローラーIC)

━━━━━━━━ 製造ロット 5件 ━━━━━━━━
  Lot 1 (2026-03-01, 100 pc) : シリコンウェーハ 日本産    COO=JP  ✅
  Lot 2 (2026-03-21, 120 pc) : シリコンウェーハ 日本産    COO=JP  ✅
  Lot 3 (2026-04-07, 100 pc) : ⚠️  日本→米国産 切替ロット COO=JP+US ⚠️
  Lot 4 (2026-04-25, 150 pc) : シリコンウェーハ 米国産    COO=US  🔵
  Lot 5 (2026-05-14, 150 pc) : シリコンウェーハ 米国産    COO=US  🔵

━━━━━━━━ 受注 50件 (3ヶ月) ━━━━━━━━
  Period 1 (2026-03-10 ~ 04-06) : 18件  JP在庫 安全期間
  Period 2 (2026-04-07 ~ 04-24) : 12件  ⚠️ COO 混在リスク期間
  Period 3 (2026-04-25 ~ 06-05) : 20件  US在庫 EAR 管轄注意

  仕向国: JP, US, DE, NL, KR, TW, CN(高リスク), SG

Usage:
    cd /Users/takehirosato/Desktop/erp-system
    python scripts/seed_demo_coo_risk.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal, create_all_tables

CLIENT_ID = "DEMO"
PLANT     = "P001"
USER      = "demo-seed@erp.system"

# ──────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────

def _get(db, model, **kwargs):
    q = db.query(model)
    for k, v in kwargs.items():
        q = q.filter(getattr(model, k) == v)
    return q.first()


def _exists(db, model, **kwargs) -> bool:
    return _get(db, model, **kwargs) is not None


def ok(msg: str) -> None:
    print(f"  ✅  {msg}")


def skip(msg: str) -> None:
    print(f"  ─   {msg}  (already exists, skip)")


def warn(msg: str) -> None:
    print(f"  ⚠️   {msg}")


def section(title: str) -> None:
    print(f"\n{'━'*60}")
    print(f"  {title}")
    print(f"{'━'*60}")


# ──────────────────────────────────────────────────────────────────
# PHASE 1: 品目マスタ
# ──────────────────────────────────────────────────────────────────

MATERIALS = [
    # code, description, type, unit, hs_code, eccn, coo, price, currency
    (
        "CTRL-HC200",
        "高精度ハイブリッドコントローラーIC",
        "FERT", "PC",
        "8542.39.00", "3A001.b.1", None,  # FERT has no fixed COO (determined by lot)
        Decimal("12500"), "JPY",
    ),
    (
        "SIL-WAF-JP",
        "高純度シリコンウェーハ (日本産)",
        "ROH", "PC",
        "3818.00.10", "3C001", "JP",
        Decimal("1200"), "JPY",
    ),
    (
        "SIL-WAF-US",
        "高純度シリコンウェーハ (米国産)",
        "ROH", "PC",
        "3818.00.10", "3C001", "US",
        Decimal("1800"), "JPY",
    ),
    (
        "PKG-CERAMIC",
        "セラミックパッケージ材料",
        "ROH", "PC",
        "8533.00.00", None, "JP",
        Decimal("450"), "JPY",
    ),
    (
        "ADH-EPOXY-01",
        "導電性エポキシ接着剤",
        "ROH", "G",
        "3506.10.00", None, "JP",
        Decimal("220"), "JPY",
    ),
]


def seed_materials(db) -> dict:
    section("PHASE 1: 品目マスタ登録")
    from app.modules.mdm.models import Material

    results = {}
    for (code, desc, mtype, unit, hs, eccn, coo, price, curr) in MATERIALS:
        if _exists(db, Material, client_id=CLIENT_ID, material_code=code):
            skip(code)
            results[code] = _get(db, Material, client_id=CLIENT_ID, material_code=code)
            continue
        m = Material(
            client_id=CLIENT_ID,
            material_code=code,
            description=desc,
            material_type=mtype,
            base_unit=unit,
            hs_code=hs,
            eccn=eccn,
            country_of_origin=coo,
            standard_price=price,
            currency=curr,
            fefta_judgment="UNKNOWN",
            created_by=USER,
            updated_by=USER,
        )
        db.add(m)
        db.flush()
        ok(f"{code}  ({mtype}, COO={coo or '-'})")
        results[code] = m

    db.commit()
    return results


# ──────────────────────────────────────────────────────────────────
# PHASE 2: 取引先マスタ (ベンダー + 顧客)
# ──────────────────────────────────────────────────────────────────

VENDORS = [
    # code, name, country, roles
    ("VEND-SIL-JP", "信越シリコン株式会社",        "JP", "VENDOR"),
    ("VEND-SIL-US", "Silicon Valley Wafers Inc.", "US", "VENDOR"),
    ("VEND-PKG-01", "セラミックパッケージ工業株式会社", "JP", "VENDOR"),
]

CUSTOMERS = [
    # code, name, country, roles, credit_limit, payment_terms
    ("CUST-JP-01", "株式会社精密技研",                  "JP", "CUSTOMER", 5_000_000, "NET60"),
    ("CUST-JP-02", "東洋電子産業株式会社",               "JP", "CUSTOMER", 3_000_000, "NET60"),
    ("CUST-JP-03", "宇宙開発関連会社株式会社",            "JP", "CUSTOMER", 8_000_000, "NET90"),
    ("CUST-US-01", "Advanced Avionics Corp",          "US", "CUSTOMER", 15_000_000, "NET30"),
    ("CUST-US-02", "Pacific Defense Systems Inc.",    "US", "CUSTOMER", 20_000_000, "NET30"),  # Defense
    ("CUST-US-03", "Silicon Valley Robotics LLC",     "US", "CUSTOMER",  8_000_000, "NET30"),
    ("CUST-DE-01", "Bosch Elektronik GmbH",           "DE", "CUSTOMER", 12_000_000, "NET45"),
    ("CUST-NL-01", "ASML Components B.V.",            "NL", "CUSTOMER", 10_000_000, "NET45"),
    ("CUST-KR-01", "Korea Semiconductor Ltd.",        "KR", "CUSTOMER",  8_000_000, "NET30"),
    ("CUST-TW-01", "TSMC Supply Chain Co. Ltd.",      "TW", "CUSTOMER", 10_000_000, "NET30"),
    ("CUST-CN-01", "Shenzhen Integrated Tech Co.",    "CN", "CUSTOMER",  5_000_000, "NET30"),  # HIGH RISK
    ("CUST-SG-01", "Singapore Advanced Mfg Pte Ltd", "SG", "CUSTOMER",  7_000_000, "NET30"),
]


def seed_business_partners(db) -> dict:
    section("PHASE 2: 取引先マスタ登録")
    from app.modules.mdm.models import BusinessPartner

    results = {}
    for entries, role_label in [(VENDORS, "ベンダー"), (CUSTOMERS, "顧客")]:
        for row in entries:
            code, name, country, roles = row[0], row[1], row[2], row[3]
            credit = row[4] if len(row) > 4 else None
            terms  = row[5] if len(row) > 5 else None

            if _exists(db, BusinessPartner, client_id=CLIENT_ID, bp_code=code):
                skip(code)
                results[code] = _get(db, BusinessPartner, client_id=CLIENT_ID, bp_code=code)
                continue

            bp = BusinessPartner(
                client_id=CLIENT_ID,
                bp_code=code,
                bp_type="ORG",
                name=name,
                country=country,
                roles=roles,
                credit_limit=Decimal(credit) if credit else None,
                payment_terms=terms,
                currency="JPY" if country == "JP" else "USD",
                is_denied_party=False,
                created_by=USER,
                updated_by=USER,
            )
            db.add(bp)
            db.flush()
            flag = "⚠️  HIGH RISK" if country == "CN" else ("🛡️ Defense" if "Defense" in name else "")
            ok(f"{code}  {name} ({country}) {flag}")
            results[code] = bp

    db.commit()
    return results


# ──────────────────────────────────────────────────────────────────
# PHASE 3: 製造マスタ (WorkCenter, Recipe×2, Routing, ProductionVersion×2)
# ──────────────────────────────────────────────────────────────────

def seed_production_master(db) -> dict:
    section("PHASE 3: 製造マスタ登録 (WorkCenter / Recipe×2 / Routing / ProdVer×2)")
    from app.modules.pp.models import (
        WorkCenter, Recipe, RecipeItem, RecipeCoProduct,
        Routing, RoutingOperation, ProductionVersion,
    )

    result = {}

    # ── WorkCenter ──────────────────────────────────────────────
    wc_code = "WC-FAB-CTRL"
    if _exists(db, WorkCenter, client_id=CLIENT_ID, work_center_code=wc_code):
        skip(wc_code)
        wc = _get(db, WorkCenter, client_id=CLIENT_ID, work_center_code=wc_code)
    else:
        wc = WorkCenter(
            client_id=CLIENT_ID,
            work_center_code=wc_code,
            description="IC 製造・組立ライン",
            plant_code=PLANT,
            capacity_per_day=Decimal("16"),   # 16 hours/day
            capacity_unit="H",
            labor_rate_per_hour=Decimal("3500"),    # 3,500 JPY/h
            machine_rate_per_hour=Decimal("12000"),  # 12,000 JPY/h
            overhead_rate_percent=Decimal("25"),
            currency="JPY",
            created_by=USER, updated_by=USER,
        )
        db.add(wc)
        db.flush()
        ok(wc_code)
    result["wc"] = wc

    # ── Routing (共通) ───────────────────────────────────────────
    rt_code = "RT-CTRL-V1"
    if _exists(db, Routing, client_id=CLIENT_ID, routing_code=rt_code):
        skip(rt_code)
        routing = _get(db, Routing, client_id=CLIENT_ID, routing_code=rt_code)
    else:
        routing = Routing(
            client_id=CLIENT_ID,
            routing_code=rt_code,
            material_code="CTRL-HC200",
            plant_code=PLANT,
            description="CTRL-HC200 標準工程順序",
            base_quantity=Decimal("100"),
            base_unit="PC",
            valid_from=date(2026, 1, 1),
            valid_to=date(2099, 12, 31),
            status="RELEASED",
            created_by=USER, updated_by=USER,
        )
        routing.operations = [
            RoutingOperation(
                operation_no=10,
                description="ウェーハ洗浄・検査",
                work_center_code=wc_code,
                setup_time_minutes=Decimal("30"),
                machine_time_minutes=Decimal("120"),
                labor_time_minutes=Decimal("60"),
                yield_percent=Decimal("99"),
                created_by=USER, updated_by=USER,
            ),
            RoutingOperation(
                operation_no=20,
                description="ダイシング・ダイボンド",
                work_center_code=wc_code,
                setup_time_minutes=Decimal("20"),
                machine_time_minutes=Decimal("180"),
                labor_time_minutes=Decimal("90"),
                yield_percent=Decimal("97"),
                created_by=USER, updated_by=USER,
            ),
            RoutingOperation(
                operation_no=30,
                description="ワイヤボンド・封止",
                work_center_code=wc_code,
                setup_time_minutes=Decimal("15"),
                machine_time_minutes=Decimal("90"),
                labor_time_minutes=Decimal("45"),
                yield_percent=Decimal("99"),
                created_by=USER, updated_by=USER,
            ),
            RoutingOperation(
                operation_no=40,
                description="最終検査・マーキング",
                work_center_code=wc_code,
                setup_time_minutes=Decimal("10"),
                machine_time_minutes=Decimal("60"),
                labor_time_minutes=Decimal("30"),
                yield_percent=Decimal("100"),
                created_by=USER, updated_by=USER,
            ),
        ]
        db.add(routing)
        db.flush()
        ok(rt_code)
    result["routing"] = routing

    # ── Recipe V1 (日本産シリコン) ────────────────────────────────
    rcp_v1_code = "RCP-HC200-V1"
    if _exists(db, Recipe, client_id=CLIENT_ID, recipe_code=rcp_v1_code):
        skip(rcp_v1_code)
        rcp_v1 = _get(db, Recipe, client_id=CLIENT_ID, recipe_code=rcp_v1_code)
    else:
        rcp_v1 = Recipe(
            client_id=CLIENT_ID,
            recipe_code=rcp_v1_code,
            material_code="CTRL-HC200",
            plant_code=PLANT,
            description="CTRL-HC200 レシピ v1 (国産シリコン使用)",
            base_quantity=Decimal("100"),
            base_unit="PC",
            yield_percent=Decimal("95"),
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 4, 6),   # Valid until Lot 3 transition
            status="RELEASED",
            version=1,
            is_default=False,
            created_by=USER, updated_by=USER,
        )
        rcp_v1.items = [
            RecipeItem(
                item_no=10,
                component_material_code="SIL-WAF-JP",   # 日本産
                quantity=Decimal("1.050"),               # 5% over-qty for yield
                unit="PC",
                scrap_percent=Decimal("2"),
                preferred_vendor_code="VEND-SIL-JP",
                created_by=USER, updated_by=USER,
            ),
            RecipeItem(
                item_no=20,
                component_material_code="PKG-CERAMIC",
                quantity=Decimal("1.010"),
                unit="PC",
                scrap_percent=Decimal("1"),
                preferred_vendor_code="VEND-PKG-01",
                created_by=USER, updated_by=USER,
            ),
            RecipeItem(
                item_no=30,
                component_material_code="ADH-EPOXY-01",
                quantity=Decimal("2.100"),               # 2.1 g per unit
                unit="G",
                scrap_percent=Decimal("3"),
                created_by=USER, updated_by=USER,
            ),
        ]
        db.add(rcp_v1)
        db.flush()
        ok(f"{rcp_v1_code}  (SIL-WAF-JP 使用、valid_to=2026-04-06)")
    result["recipe_v1"] = rcp_v1

    # ── Recipe V2 (米国産シリコン) ────────────────────────────────
    rcp_v2_code = "RCP-HC200-V2"
    if _exists(db, Recipe, client_id=CLIENT_ID, recipe_code=rcp_v2_code):
        skip(rcp_v2_code)
        rcp_v2 = _get(db, Recipe, client_id=CLIENT_ID, recipe_code=rcp_v2_code)
    else:
        rcp_v2 = Recipe(
            client_id=CLIENT_ID,
            recipe_code=rcp_v2_code,
            material_code="CTRL-HC200",
            plant_code=PLANT,
            description="CTRL-HC200 レシピ v2 (米国産シリコン使用) - EAR管轄注意",
            base_quantity=Decimal("100"),
            base_unit="PC",
            yield_percent=Decimal("96"),               # Slightly higher yield with US wafer
            valid_from=date(2026, 4, 7),
            valid_to=date(2099, 12, 31),
            status="RELEASED",
            version=2,
            is_default=True,
            created_by=USER, updated_by=USER,
        )
        rcp_v2.items = [
            RecipeItem(
                item_no=10,
                component_material_code="SIL-WAF-US",   # 米国産 ← 変更点
                quantity=Decimal("1.045"),
                unit="PC",
                scrap_percent=Decimal("2"),
                preferred_vendor_code="VEND-SIL-US",
                created_by=USER, updated_by=USER,
            ),
            RecipeItem(
                item_no=20,
                component_material_code="PKG-CERAMIC",
                quantity=Decimal("1.010"),
                unit="PC",
                scrap_percent=Decimal("1"),
                preferred_vendor_code="VEND-PKG-01",
                created_by=USER, updated_by=USER,
            ),
            RecipeItem(
                item_no=30,
                component_material_code="ADH-EPOXY-01",
                quantity=Decimal("2.050"),
                unit="G",
                scrap_percent=Decimal("3"),
                created_by=USER, updated_by=USER,
            ),
        ]
        db.add(rcp_v2)
        db.flush()
        ok(f"{rcp_v2_code}  (SIL-WAF-US 使用、valid_from=2026-04-07)")
    result["recipe_v2"] = rcp_v2

    # ── ProductionVersion ──────────────────────────────────────────
    for pv_code, recipe, label in [
        ("PV-HC200-V1", rcp_v1, "v1 (JP origin)"),
        ("PV-HC200-V2", rcp_v2, "v2 (US origin)"),
    ]:
        if _exists(db, ProductionVersion, client_id=CLIENT_ID, version_code=pv_code):
            skip(pv_code)
            result[pv_code] = _get(db, ProductionVersion, client_id=CLIENT_ID, version_code=pv_code)
        else:
            pv = ProductionVersion(
                client_id=CLIENT_ID,
                version_code=pv_code,
                material_code="CTRL-HC200",
                plant_code=PLANT,
                recipe_id=recipe.id,
                routing_id=routing.id,
                valid_from=recipe.valid_from,
                valid_to=recipe.valid_to,
                is_default=(pv_code == "PV-HC200-V2"),
                created_by=USER, updated_by=USER,
            )
            db.add(pv)
            db.flush()
            ok(f"{pv_code}  {label}")
            result[pv_code] = pv

    db.commit()
    return result


# ──────────────────────────────────────────────────────────────────
# PHASE 4: 調達マスタ (PurchasingInfoRecord, SourceList)
# ──────────────────────────────────────────────────────────────────

def seed_procurement_master(db) -> None:
    section("PHASE 4: 調達マスタ (購買情報レコード / ソースリスト)")
    from app.modules.mm.models import PurchasingInfoRecord, SourceList

    PIRS = [
        # material, vendor, plant, price, unit, currency, valid_from, valid_to, coo, is_preferred, delivery_days
        ("SIL-WAF-JP", "VEND-SIL-JP", PLANT,
         Decimal("1200"), Decimal("1"), "JPY",
         date(2025, 1, 1), date(2026, 4, 6),
         "JP", True, 14),
        ("SIL-WAF-US", "VEND-SIL-US", PLANT,
         Decimal("1800"), Decimal("1"), "JPY",  # 1,800 JPY = ~$12/pc
         date(2026, 4, 1), date(2099, 12, 31),
         "US", True, 21),           # Longer lead time from USA
        ("PKG-CERAMIC", "VEND-PKG-01", PLANT,
         Decimal("450"), Decimal("1"), "JPY",
         date(2025, 1, 1), date(2099, 12, 31),
         "JP", True, 7),
    ]

    for (mat, vend, plant, price, punit, curr,
         vfrom, vto, coo, is_pref, days) in PIRS:
        if _exists(db, PurchasingInfoRecord,
                   client_id=CLIENT_ID,
                   material_code=mat,
                   vendor_code=vend,
                   plant_code=plant):
            skip(f"PIR {mat} / {vend}")
            continue
        pir = PurchasingInfoRecord(
            client_id=CLIENT_ID,
            material_code=mat,
            vendor_code=vend,
            plant_code=plant,
            unit_price=price,
            price_unit=punit,
            currency=curr,
            price_valid_from=vfrom,
            price_valid_to=vto,
            order_unit="PC" if mat != "ADH-EPOXY-01" else "G",
            planned_delivery_days=days,
            country_of_origin=coo,
            is_preferred=is_pref,
            created_by=USER, updated_by=USER,
        )
        db.add(pir)
        db.flush()
        ok(f"PIR  {mat} ← {vend}  {price}{curr} COO={coo}")

    for (mat, vend, plant, vfrom, vto, prio, fixed) in [
        ("SIL-WAF-JP", "VEND-SIL-JP", PLANT, date(2025,1,1), date(2026,4,6), 1, False),
        ("SIL-WAF-US", "VEND-SIL-US", PLANT, date(2026,4,1), date(2099,12,31), 1, True),
        ("PKG-CERAMIC", "VEND-PKG-01", PLANT, date(2025,1,1), date(2099,12,31), 1, True),
    ]:
        if _exists(db, SourceList,
                   client_id=CLIENT_ID,
                   material_code=mat,
                   plant_code=plant,
                   vendor_code=vend):
            skip(f"SourceList {mat}/{vend}")
            continue
        sl = SourceList(
            client_id=CLIENT_ID,
            material_code=mat,
            plant_code=plant,
            vendor_code=vend,
            valid_from=vfrom,
            valid_to=vto,
            priority=prio,
            is_blocked=False,
            is_fixed=fixed,
            order_type="PO",
            created_by=USER, updated_by=USER,
        )
        db.add(sl)
        db.flush()
        ok(f"SourceList  {mat} → {vend}  prio={prio}")

    db.commit()


# ──────────────────────────────────────────────────────────────────
# PHASE 5: 製造ロット × 5
# ──────────────────────────────────────────────────────────────────

LOT_DEFS = [
    # (lot_no, po_doc, batch_code,
    #  start_date, end_date,
    #  qty_target, pv_code,
    #  raw_mat, raw_vendor, raw_coo, raw_qty_per_batch,
    #  finished_coo, lot_risk_label, qc_note)
    (1, "PO-2026-LOT1", "CTRL-LOT-001",
     date(2026, 3, 1),  date(2026, 3, 7),
     Decimal("100"), "PV-HC200-V1",
     "SIL-WAF-JP", "VEND-SIL-JP", "JP", Decimal("110"),
     "JP",
     "安全 (COO=JP)",
     "国産シリコンウェーハ使用。全ロット原産地: 日本。"),

    (2, "PO-2026-LOT2", "CTRL-LOT-002",
     date(2026, 3, 21), date(2026, 3, 27),
     Decimal("120"), "PV-HC200-V1",
     "SIL-WAF-JP", "VEND-SIL-JP", "JP", Decimal("126"),
     "JP",
     "安全 (COO=JP)",
     "国産シリコンウェーハ使用。全ロット原産地: 日本。"),

    (3, "PO-2026-LOT3", "CTRL-LOT-003",
     date(2026, 4, 7),  date(2026, 4, 14),
     Decimal("100"), "PV-HC200-V2",
     "SIL-WAF-US", "VEND-SIL-US", "US", Decimal("105"),
     None,  # ← MIXED COO — set to None = uncertain
     "⚠️ RISK (COO=Mixed JP+US)",
     "【原産性注意】本ロット製造時に国産在庫残 (JP) と米国産新規入荷 (US) "
     "が混在使用された可能性あり。正確な COO が特定できない過渡期ロット。"
     "輸出審査・原産地証明要確認。Lot3以降の出荷は輸出管理部門に事前確認を要す。"),

    (4, "PO-2026-LOT4", "CTRL-LOT-004",
     date(2026, 4, 25), date(2026, 5, 2),
     Decimal("150"), "PV-HC200-V2",
     "SIL-WAF-US", "VEND-SIL-US", "US", Decimal("158"),
     "US",
     "EAR管轄 (COO=US)",
     "米国産シリコンウェーハ使用。EAR (Export Administration Regulations) 管轄品。"
     "対中国・軍事用途顧客への出荷は輸出許可申請が必要な場合あり。"),

    (5, "PO-2026-LOT5", "CTRL-LOT-005",
     date(2026, 5, 14), date(2026, 5, 21),
     Decimal("150"), "PV-HC200-V2",
     "SIL-WAF-US", "VEND-SIL-US", "US", Decimal("158"),
     "US",
     "EAR管轄 (COO=US)",
     "米国産シリコンウェーハ使用。EAR 管轄品。"),
]


def seed_production_lots(db) -> list:
    section("PHASE 5: 製造ロット × 5 (ProcessOrder + Batch + BatchGenealogy)")
    from app.modules.pp.execution_models import ProcessOrder, ProcessOrderComponent, Batch, BatchGenealogy

    batches = []
    for (lot_no, po_doc, batch_code,
         start_dt, end_dt,
         qty_target, pv_code,
         raw_mat, raw_vendor, raw_coo, raw_qty,
         fin_coo, risk_label, qc_note) in LOT_DEFS:

        # ── Raw material batch (received from vendor) ────────────
        raw_batch_code = f"RAW-{raw_mat.replace('-','')}-L{lot_no}"
        if not _exists(db, Batch, client_id=CLIENT_ID, batch_code=raw_batch_code):
            raw_batch = Batch(
                client_id=CLIENT_ID,
                batch_code=raw_batch_code,
                material_code=raw_mat,
                plant_code=PLANT,
                storage_location="WH-RAW",
                quantity=raw_qty,
                initial_quantity=raw_qty,
                unit="PC",
                source_type="PURCHASED",
                source_reference=f"GR-LOT{lot_no}-RAW",
                country_of_origin=raw_coo,
                vendor_code=raw_vendor,
                quality_status="RELEASED",
                production_date=start_dt - timedelta(days=7),
                created_by=USER, updated_by=USER,
            )
            db.add(raw_batch)
            db.flush()
        else:
            raw_batch = _get(db, Batch, client_id=CLIENT_ID, batch_code=raw_batch_code)

        # ── Process Order ────────────────────────────────────────
        if _exists(db, ProcessOrder, client_id=CLIENT_ID, document_number=po_doc):
            skip(f"ProcessOrder {po_doc}  → {batch_code}")
            fin_batch = _get(db, Batch, client_id=CLIENT_ID, batch_code=batch_code)
            if fin_batch:
                batches.append((lot_no, fin_batch, fin_coo, risk_label, qc_note, start_dt, end_dt))
            continue

        po = ProcessOrder(
            client_id=CLIENT_ID,
            document_number=po_doc,
            document_date=start_dt,
            status="COMPLETED",
            material_code="CTRL-HC200",
            plant_code=PLANT,
            production_version_code=pv_code,
            target_quantity=qty_target,
            target_unit="PC",
            actual_quantity=qty_target * Decimal("0.96"),  # ~4% yield loss
            scrapped_quantity=qty_target * Decimal("0.04"),
            scheduled_start=datetime.combine(start_dt, datetime.min.time()),
            scheduled_end=datetime.combine(end_dt, datetime.min.time()),
            actual_start=datetime.combine(start_dt, datetime.min.time()),
            actual_end=datetime.combine(end_dt, datetime.min.time()),
            created_by=USER, updated_by=USER,
        )
        # Component consumption record
        actual_qty = qty_target * Decimal("0.96")
        po.components = [
            ProcessOrderComponent(
                item_no=10,
                material_code=raw_mat,
                description=f"{"日本産" if raw_coo=="JP" else "米国産"}シリコンウェーハ",
                planned_quantity=qty_target * Decimal("1.05"),
                issued_quantity=actual_qty * Decimal("1.04"),
                unit="PC",
                operation_no=10,
                created_by=USER, updated_by=USER,
            ),
            ProcessOrderComponent(
                item_no=20,
                material_code="PKG-CERAMIC",
                description="セラミックパッケージ",
                planned_quantity=qty_target * Decimal("1.01"),
                issued_quantity=actual_qty * Decimal("1.01"),
                unit="PC",
                operation_no=30,
                created_by=USER, updated_by=USER,
            ),
        ]
        db.add(po)
        db.flush()

        # ── Finished Product Batch ───────────────────────────────
        fin_qty = qty_target * Decimal("0.96")
        qc_data = {
            "lot_number": lot_no,
            "production_version": pv_code,
            "silicon_origin": raw_coo,
            "risk_assessment": risk_label,
            "notes": qc_note,
            "inspection_date": end_dt.isoformat(),
            "inspector": "QC-TEAM",
        }
        if lot_no == 3:
            qc_data["coo_alert"] = (
                "MIXED_ORIGIN: 本ロットは日本産在庫末尾(~30個相当)と"
                "米国産新規入荷が混在。LOT3出荷品の最終用途証明書を別途取得のこと。"
            )

        fin_batch = Batch(
            client_id=CLIENT_ID,
            batch_code=batch_code,
            material_code="CTRL-HC200",
            plant_code=PLANT,
            storage_location="WH-FG",
            quantity=fin_qty,
            initial_quantity=fin_qty,
            unit="PC",
            source_type="PRODUCED",
            source_reference=po_doc,
            country_of_origin=fin_coo,  # None for Lot 3
            quality_status="RELEASED",
            production_date=end_dt,
            qc_results_json=json.dumps(qc_data, ensure_ascii=False),
            created_by=USER, updated_by=USER,
        )
        db.add(fin_batch)
        db.flush()

        # ── Batch Genealogy (raw → finished) ─────────────────────
        genealogy = BatchGenealogy(
            client_id=CLIENT_ID,
            parent_batch_code=raw_batch_code,
            child_batch_code=batch_code,
            process_order_number=po_doc,
            parent_material_code=raw_mat,
            child_material_code="CTRL-HC200",
            consumed_quantity=actual_qty * Decimal("1.04"),
            consumed_unit="PC",
            created_by=USER, updated_by=USER,
        )
        db.add(genealogy)
        db.flush()

        coo_display = fin_coo if fin_coo else "⚠️ UNKNOWN/MIXED"
        ok(f"Lot {lot_no}  {batch_code}  {fin_qty}pc  COO={coo_display}  [{risk_label}]")
        batches.append((lot_no, fin_batch, fin_coo, risk_label, qc_note, start_dt, end_dt))

    db.commit()
    return batches


# ──────────────────────────────────────────────────────────────────
# PHASE 6: 在庫残高 (StockBalance)
# ──────────────────────────────────────────────────────────────────

def seed_stock_balances(db) -> None:
    section("PHASE 6: 在庫残高初期化")
    from app.modules.mm.models import StockBalance

    # CTRL-HC200 FG stock (sum of all lots at WH-FG)
    # Total produced: (100+120+100+150+150) * 0.96 = 596.16 ≈ 596 pc
    # After sales: we'll set initial stock and let SOs "consume" conceptually
    stock_entries = [
        # material, plant, location, unrestricted, reserved, unit
        ("CTRL-HC200", PLANT, "WH-FG",
         Decimal("596"), Decimal("0"), "PC"),
        # Raw material remaining stock
        ("SIL-WAF-JP", PLANT, "WH-RAW",
         Decimal("5"),  Decimal("0"), "PC"),   # Nearly depleted
        ("SIL-WAF-US", PLANT, "WH-RAW",
         Decimal("84"), Decimal("0"), "PC"),   # 3 lots worth minus consumed
        ("PKG-CERAMIC", PLANT, "WH-RAW",
         Decimal("120"), Decimal("0"), "PC"),
        ("ADH-EPOXY-01", PLANT, "WH-RAW",
         Decimal("500"), Decimal("0"), "G"),
    ]

    for (mat, plant, loc, unr, res, unit) in stock_entries:
        if _exists(db, StockBalance,
                   client_id=CLIENT_ID,
                   material_code=mat,
                   plant_code=plant,
                   storage_location=loc):
            skip(f"Stock {mat} / {loc}")
            continue
        sb = StockBalance(
            client_id=CLIENT_ID,
            material_code=mat,
            plant_code=plant,
            storage_location=loc,
            unrestricted_qty=unr,
            reserved_qty=res,
            stock_unit=unit,
            created_by=USER, updated_by=USER,
        )
        db.add(sb)
        db.flush()
        ok(f"Stock  {mat}  {loc}  {unr}{unit}")

    db.commit()


# ──────────────────────────────────────────────────────────────────
# PHASE 7: 受注 × 50件
# ──────────────────────────────────────────────────────────────────

# (customer_code, order_date, qty, currency, unit_price, period_tag, note)
ORDERS = [
    # ── Period 1: 2026-03-10 ~ 04-06  COO=JP  安全期間 ────────────────
    ("CUST-JP-01", "2026-03-10", 20,  "JPY", Decimal("12500"), 1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-US-01", "2026-03-12", 10,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-DE-01", "2026-03-14", 15,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-KR-01", "2026-03-15", 10,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-JP-02", "2026-03-17", 25,  "JPY", Decimal("12500"), 1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-TW-01", "2026-03-19", 12,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-SG-01", "2026-03-21", 8,   "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-JP-03", "2026-03-24", 30,  "JPY", Decimal("12500"), 1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-US-03", "2026-03-26", 15,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-NL-01", "2026-03-28", 10,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-JP-01", "2026-04-01", 15,  "JPY", Decimal("12500"), 1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-KR-01", "2026-04-02", 20,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-TW-01", "2026-04-03", 8,   "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-DE-01", "2026-04-04", 12,  "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-JP-02", "2026-04-05", 10,  "JPY", Decimal("12500"), 1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-US-01", "2026-04-05", 5,   "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-SG-01", "2026-04-06", 6,   "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),
    ("CUST-NL-01", "2026-04-06", 8,   "USD", Decimal("95"),    1, "JP在庫, COO=JP, 通常処理"),

    # ── Period 2: 2026-04-07 ~ 04-24  ⚠️ COO混在リスク期間 ────────────
    ("CUST-JP-01", "2026-04-07", 20,  "JPY", Decimal("12500"), 2,
     "⚠️ Lot3在庫(COO混在). 原産地確認要"),
    ("CUST-CN-01", "2026-04-08", 10,  "USD", Decimal("95"),    2,
     "⚠️ 高リスク: 仕向地CN + Lot3 COO混在 → 輸出審査強化"),
    ("CUST-US-02", "2026-04-09", 8,   "USD", Decimal("95"),    2,
     "⚠️ 防衛用途: COO混在ロットは軍需顧客に特に注意"),
    ("CUST-KR-01", "2026-04-10", 15,  "USD", Decimal("95"),    2,
     "⚠️ Lot3在庫(COO混在). 原産地確認要"),
    ("CUST-TW-01", "2026-04-11", 10,  "USD", Decimal("95"),    2,
     "⚠️ Lot3在庫(COO混在). 原産地確認要"),
    ("CUST-CN-01", "2026-04-14", 15,  "USD", Decimal("95"),    2,
     "⚠️ 高リスク: 仕向地CN + Lot3 COO混在"),
    ("CUST-US-02", "2026-04-15", 5,   "USD", Decimal("95"),    2,
     "⚠️ 防衛用途: COO混在注意"),
    ("CUST-DE-01", "2026-04-16", 12,  "USD", Decimal("95"),    2,
     "⚠️ Lot3在庫(COO混在). 原産地確認要"),
    ("CUST-JP-03", "2026-04-18", 25,  "JPY", Decimal("12500"), 2,
     "⚠️ 航空宇宙用途 + COO混在 → FEFTA再確認要"),
    ("CUST-SG-01", "2026-04-19", 10,  "USD", Decimal("95"),    2,
     "⚠️ Lot3在庫(COO混在). SG経由再輸出リスク確認"),
    ("CUST-US-01", "2026-04-21", 15,  "USD", Decimal("95"),    2,
     "⚠️ Lot3在庫(COO混在). 原産地確認要"),
    ("CUST-KR-01", "2026-04-23", 8,   "USD", Decimal("95"),    2,
     "⚠️ Lot3在庫(COO混在). 原産地確認要"),

    # ── Period 3: 2026-04-25 ~ 06-05  COO=US  EAR管轄注意 ────────────
    ("CUST-JP-01", "2026-04-25", 20,  "JPY", Decimal("12800"), 3,
     "Lot4在庫 COO=US. EAR対象品 (3A001). 通常用途は許可不要"),
    ("CUST-US-01", "2026-04-26", 10,  "USD", Decimal("100"),   3,
     "Lot4在庫 COO=US. EAR対象品 (3A001). 通常用途は許可不要"),
    ("CUST-CN-01", "2026-04-28", 20,  "USD", Decimal("100"),   3,
     "🚨 最高リスク: US-origin 3A001 → CN. EAR ライセンス申請検討要"),
    ("CUST-TW-01", "2026-04-30", 12,  "USD", Decimal("100"),   3,
     "Lot4在庫 COO=US. EAR対象品. 通常用途は許可不要"),
    ("CUST-DE-01", "2026-05-02", 15,  "USD", Decimal("100"),   3,
     "Lot4在庫 COO=US. EAR対象品. EU域内は許可不要"),
    ("CUST-KR-01", "2026-05-05", 10,  "USD", Decimal("100"),   3,
     "Lot4在庫 COO=US. EAR対象品. 通常用途は許可不要"),
    ("CUST-US-02", "2026-05-07", 10,  "USD", Decimal("100"),   3,
     "🔴 防衛用途 + US-origin 3A001. 最終用途証明書必須"),
    ("CUST-SG-01", "2026-05-08", 8,   "USD", Decimal("100"),   3,
     "Lot4在庫 COO=US. SG経由再輸出監視要"),
    ("CUST-NL-01", "2026-05-09", 10,  "USD", Decimal("100"),   3,
     "Lot4在庫 COO=US. EU域内は許可不要"),
    ("CUST-JP-02", "2026-05-12", 20,  "JPY", Decimal("12800"), 3,
     "Lot4在庫 COO=US. 輸入品の国内転用。EAR再輸出規制に注意"),
    ("CUST-CN-01", "2026-05-14", 15,  "USD", Decimal("100"),   3,
     "🚨 最高リスク: US-origin 3A001 → CN. EAR ライセンス申請検討要"),
    ("CUST-TW-01", "2026-05-16", 10,  "USD", Decimal("100"),   3,
     "Lot5在庫 COO=US. EAR対象品."),
    ("CUST-US-03", "2026-05-19", 12,  "USD", Decimal("100"),   3,
     "Lot5在庫 COO=US. EAR対象品. 通常用途は許可不要"),
    ("CUST-JP-03", "2026-05-21", 30,  "JPY", Decimal("12800"), 3,
     "Lot5在庫 COO=US. 航空宇宙用途 + US-origin. 最終用途確認要"),
    ("CUST-KR-01", "2026-05-23", 15,  "USD", Decimal("100"),   3,
     "Lot5在庫 COO=US. EAR対象品."),
    ("CUST-DE-01", "2026-05-26", 12,  "USD", Decimal("100"),   3,
     "Lot5在庫 COO=US. EU域内は許可不要"),
    ("CUST-US-01", "2026-05-28", 8,   "USD", Decimal("100"),   3,
     "Lot5在庫 COO=US. 通常用途は許可不要"),
    ("CUST-CN-01", "2026-05-30", 10,  "USD", Decimal("100"),   3,
     "🚨 最高リスク: US-origin 3A001 → CN. EAR ライセンス申請検討要"),
    ("CUST-SG-01", "2026-06-02", 8,   "USD", Decimal("100"),   3,
     "Lot5在庫 COO=US. SG経由再輸出監視"),
    ("CUST-JP-01", "2026-06-05", 15,  "JPY", Decimal("12800"), 3,
     "Lot5在庫 COO=US. 輸入品の国内転用。"),
]

# Verify: 18 + 12 + 20 = 50
assert sum(1 for o in ORDERS if o[5] == 1) == 18, "Phase 1 must be 18"
assert sum(1 for o in ORDERS if o[5] == 2) == 12, "Phase 2 must be 12"
assert sum(1 for o in ORDERS if o[5] == 3) == 20, "Phase 3 must be 20"
assert len(ORDERS) == 50, "Must be 50 orders total"


def seed_sales_orders(db, bps: dict) -> list:
    section(f"PHASE 7: 受注 × {len(ORDERS)} 件")
    from app.modules.sd.models import SalesOrder, SalesOrderItem

    so_list = []
    so_num_counter = {"v": 10_300_000}

    def next_so_num():
        n = so_num_counter["v"]
        so_num_counter["v"] += 1
        return str(n)

    period_counts = {1: 0, 2: 0, 3: 0}

    for (cust_code, order_date_str, qty, currency, unit_price, period, note) in ORDERS:
        order_date = date.fromisoformat(order_date_str)
        delivery_date = order_date + timedelta(days=21)  # 3-week lead time
        net_amount = (Decimal(qty) * unit_price).quantize(Decimal("0.01"))

        # Check if SO already exists for this customer + date + amount
        existing = db.query(SalesOrder).filter(
            SalesOrder.client_id == CLIENT_ID,
            SalesOrder.customer_code == cust_code,
            SalesOrder.document_date == order_date,
            SalesOrder.total_amount == net_amount,
        ).first()
        if existing:
            so_list.append((period, existing, note))
            period_counts[period] += 1
            continue

        so_num = next_so_num()
        # Map risk tag to export_check_status
        if period == 1:
            ecs = "PASSED"
        elif period == 2:
            ecs = "PENDING"       # awaiting manual COO verification
        else:
            cust_country = bps.get(cust_code)
            if cust_country and hasattr(cust_country, "country") and cust_country.country == "CN":
                ecs = "PENDING"   # US-origin → CN = needs license check
            elif "Defense" in (bps.get(cust_code).name if bps.get(cust_code) else ""):
                ecs = "PENDING"
            else:
                ecs = "PASSED"

        # Block high-risk orders in period 2 (CN + mixed COO)
        cust = bps.get(cust_code)
        cust_country = cust.country if cust else "??"
        is_cn = cust_country == "CN"
        so_status = "BLOCKED" if (period == 2 and is_cn) else "OPEN"

        so = SalesOrder(
            client_id=CLIENT_ID,
            document_number=so_num,
            document_date=order_date,
            status=so_status,
            customer_code=cust_code,
            customer_po_number=f"CUST-PO-{so_num}",
            requested_delivery_date=delivery_date,
            incoterms="CIF" if cust_country != "JP" else "DAP",
            payment_terms=cust.payment_terms if cust else "NET30",
            currency=currency,
            total_amount=net_amount,
            export_check_status=ecs,
            export_check_message=note if ecs != "PASSED" else None,
            created_by=USER,
            updated_by=USER,
        )
        so.items = [
            SalesOrderItem(
                item_no=10,
                material_code="CTRL-HC200",
                description="高精度ハイブリッドコントローラーIC",
                quantity=Decimal(qty),
                unit="PC",
                unit_price=unit_price,
                net_amount=net_amount,
                plant_code=PLANT,
                created_by=USER,
                updated_by=USER,
            )
        ]
        db.add(so)
        db.flush()
        so_list.append((period, so, note))
        period_counts[period] += 1

        flag = ("🚨" if ("🚨" in note) else
                "⚠️" if ("⚠️" in note) else
                "🔴" if ("🔴" in note) else "✅")
        print(f"  {flag}  SO-{so_num}  {order_date_str}  {cust_code}({cust_country})"
              f"  {qty}pc@{unit_price}{currency}  P{period}")

    db.commit()
    print(f"\n  Period 1 (JP-safe): {period_counts[1]}件")
    print(f"  Period 2 (COO-risk): {period_counts[2]}件")
    print(f"  Period 3 (US-EAR): {period_counts[3]}件")
    print(f"  Total: {sum(period_counts.values())}件")
    return so_list


# ──────────────────────────────────────────────────────────────────
# PHASE 8: AI Trade Management 連携
# ──────────────────────────────────────────────────────────────────

def push_to_aitm(db, so_list: list, materials: dict) -> None:
    section("PHASE 8: AI Trade Management 連携")

    from app.integrations.ai_trade_management.client import get_client
    from app.integrations.ai_trade_management import schemas as ai_schemas

    client = get_client()

    # ── 8-1. 品目登録 + ERP Sync ──────────────────────────────────
    print("\n  [8-1] 品目登録 / erp-sync")

    # Map: ERP material_type → AI_TM item_type
    TYPE_MAP = {"FERT": "equipment", "HALB": "component",
                "ROH": "component", "HAWA": "component"}

    aitm_product_id = {}
    for code, mat in materials.items():
        item_type = TYPE_MAP.get(mat.material_type, "component")
        try:
            sync_item = ai_schemas.BomSyncItem(
                code=code,
                name=mat.description,
                eccn=mat.eccn,
                hs_code=mat.hs_code,
                item_type=item_type,
                bom=[],
            )
            resp = client.erp_sync(sync_item)
            aitm_product_id[code] = resp.id
            status = "新規" if resp.created else "更新"
            ok(f"{code}  ({item_type})  AI_TM id={resp.id}  [{status}]")
        except Exception as e:
            warn(f"{code}  erp-sync 失敗: {e}")
            aitm_product_id[code] = None

    # ── 8-2. BOM Sync (v1: JP-origin, v2: US-origin) ─────────────
    print("\n  [8-2] BOM Sync (v1=JP / v2=US)")

    for bom_version, raw_code, raw_coo, valid_note in [
        ("v1", "SIL-WAF-JP", "JP", "Lots 1-2 (JP-origin)"),
        ("v2", "SIL-WAF-US", "US", "Lots 3-5 (US-origin, EAR applicable)"),
    ]:
        raw_mat = materials.get(raw_code)
        pkg_mat  = materials.get("PKG-CERAMIC")
        adh_mat  = materials.get("ADH-EPOXY-01")
        prod_mat = materials.get("CTRL-HC200")
        if not (raw_mat and pkg_mat and adh_mat and prod_mat):
            warn(f"BOM {bom_version}: 品目データ不足")
            continue

        bom_item = ai_schemas.BomSyncItem(
            code=prod_mat.material_code,
            name=prod_mat.description,
            eccn=prod_mat.eccn,
            hs_code=prod_mat.hs_code,
            item_type="equipment",
            bom=[
                ai_schemas.BomSyncComponent(
                    child_code=raw_mat.material_code,
                    child_name=raw_mat.description,
                    quantity=1.05,
                    unit_value_usd=round(float(raw_mat.standard_price or 0) / 150, 2),
                    origin_country=raw_coo,
                    supplier_name="信越シリコン" if raw_coo == "JP" else "Silicon Valley Wafers",
                ),
                ai_schemas.BomSyncComponent(
                    child_code=pkg_mat.material_code,
                    child_name=pkg_mat.description,
                    quantity=1.01,
                    unit_value_usd=round(float(pkg_mat.standard_price or 0) / 150, 2),
                    origin_country="JP",
                    supplier_name="セラミックパッケージ工業",
                ),
                ai_schemas.BomSyncComponent(
                    child_code=adh_mat.material_code,
                    child_name=adh_mat.description,
                    quantity=2.1,
                    unit_value_usd=round(float(adh_mat.standard_price or 0) / 150, 2),
                    origin_country="JP",
                    supplier_name="接着剤商事",
                ),
            ],
        )
        try:
            resp = client.erp_sync(bom_item)
            ok(f"BOM {bom_version} ({valid_note})  AI_TM id={resp.id}")
        except Exception as e:
            warn(f"BOM {bom_version} sync 失敗: {e}")

    # ── 8-3. 受注ごとに取引審査 (Transaction) ─────────────────────
    print(f"\n  [8-3] 受注取引審査 ({len(so_list)} 件)")

    from app.modules.mdm.models import BusinessPartner
    results_summary = {"CLEAR": 0, "REVIEW": 0, "BLOCKED": 0, "ERROR": 0}

    for idx, (period, so, risk_note) in enumerate(so_list, start=1):
        cust = _get(db, BusinessPartner,
                    client_id=CLIENT_ID, bp_code=so.customer_code)
        if not cust:
            warn(f"  [{idx:02d}] SO {so.document_number}: 顧客 {so.customer_code} 見つからず")
            continue

        # USD換算 (JPY: ÷150, EUR: ÷162 approx)
        total_usd = float(so.total_amount)
        if so.currency == "JPY":
            total_usd = round(total_usd / 150, 2)
        elif so.currency == "EUR":
            total_usd = round(total_usd / 162 * 150, 2)  # EUR→JPY→USD

        # unit_price_usd
        if so.items:
            item0 = so.items[0]
            up_usd = float(item0.unit_price)
            if so.currency == "JPY":
                up_usd = round(up_usd / 150, 2)
            elif so.currency == "EUR":
                up_usd = round(up_usd / 162 * 150, 2)
            qty = float(item0.quantity)
        else:
            up_usd, qty = 0.0, 0.0

        # Period label for AI_TM usage_summary
        period_label = {
            1: "[Period-1: JP-origin safe]",
            2: "[Period-2: ⚠️ Mixed COO risk - Lot3 transition]",
            3: "[Period-3: US-origin EAR applicable - 3A001]",
        }[period]

        # COO risk annotation per period
        lot_coo = "JP" if period == 1 else ("MIXED(JP+US)" if period == 2 else "US")
        tx_req = ai_schemas.TransactionCreateRequest(
            title=f"SO-{so.document_number} | {cust.name} → {cust.country} | {qty:.0f}pc",
            counterparty_name=cust.name,
            destination_country=cust.country,
            items=[ai_schemas.TransactionItem(
                item_name="CTRL-HC200",
                item_description=f"高精度ハイブリッドコントローラーIC | COO={lot_coo} | {period_label}",
            )],
            usage_requirements=[ai_schemas.TransactionUsageRequirement(
                source="ERP",
                text=f"{risk_note} | ECCN=3A001.b.1 | HS=8542.39.00 | 仕向国={cust.country}",
            )],
            source_module="ERP",
        )

        try:
            tx = client.create_transaction(tx_req)

            # Derive preliminary judgment locally (AI_TM screening runs async)
            HIGH_RISK = {"CN", "IR", "KP", "RU", "BY", "SY"}
            if cust.country in HIGH_RISK:
                judgment = "BLOCKED"
            elif period == 2:
                judgment = "REVIEW"
            elif period == 3 and cust.country not in ("JP", "US", "DE", "NL", "SG", "KR"):
                judgment = "REVIEW"
            else:
                judgment = "CLEAR"

            results_summary[judgment] = results_summary.get(judgment, 0) + 1

            # Write AI TM result back to SO
            if judgment == "CLEAR":
                so.export_check_status = "PASSED"
                so.export_check_ref = tx.case_no
            elif judgment == "REVIEW":
                so.export_check_status = "PENDING"
                so.export_check_ref = tx.case_no
                so.export_check_message = f"AI_TM審査中 [{period_label}] case={tx.case_no}"
            else:  # BLOCKED
                so.export_check_status = "BLOCKED"
                so.export_check_ref = tx.case_no
                so.export_check_message = (
                    f"AI_TM BLOCKED [{period_label}] {risk_note[:80]}"
                )

            flag = "✅" if judgment == "CLEAR" else "⚠️ " if judgment == "REVIEW" else "🚫"
            dest = cust.country
            print(f"  {flag}  [{idx:02d}] SO-{so.document_number}  {dest}"
                  f"  {qty:.0f}pc  P{period}  case={tx.case_no}  → {judgment}")

        except Exception as e:
            results_summary["ERROR"] += 1
            warn(f"[{idx:02d}] SO-{so.document_number}: AI_TM 連携エラー: {e}")
            so.export_check_status = "ERROR"
            so.export_check_message = f"Integration error: {str(e)[:100]}"

        if idx % 10 == 0:
            db.commit()

    db.commit()

    print(f"\n  ── 取引審査結果サマリー ──")
    for k, v in results_summary.items():
        if v > 0:
            icon = "✅" if k == "CLEAR" else "⚠️ " if k in ("REVIEW",) else "🚫"
            print(f"  {icon}  {k}: {v}件")


# ──────────────────────────────────────────────────────────────────
# PHASE 9: 輸出申告書ドラフト (高リスク案件)
# ──────────────────────────────────────────────────────────────────

def seed_export_declarations(db, so_list: list) -> None:
    section("PHASE 9: 輸出申告書 ドラフト生成 (高リスク案件)")
    from app.modules.gts.models import ExportDeclaration
    from app.modules.mdm.models import BusinessPartner

    count = 0
    for period, so, note in so_list:
        cust = _get(db, BusinessPartner,
                    client_id=CLIENT_ID, bp_code=so.customer_code)
        if not cust:
            continue

        # Only create declarations for high-risk orders
        is_high_risk = (
            cust.country == "CN" or
            (period == 3 and cust.country not in ("JP", "US", "DE", "NL")) or
            (period == 2 and cust.country == "CN") or
            "Defense" in cust.name
        )
        if not is_high_risk:
            continue

        if _exists(db, ExportDeclaration,
                   client_id=CLIENT_ID,
                   sales_order_id=so.id):
            skip(f"ExportDecl for SO {so.document_number}")
            continue

        item = so.items[0] if so.items else None
        qty = float(item.quantity) if item else 0.0
        total_usd = float(so.total_amount)
        if so.currency == "JPY":
            total_usd = round(total_usd / 150, 2)

        lot_coo = "US" if period == 3 else (None if period == 2 else "JP")
        eccn = "3A001.b.1"

        decl = ExportDeclaration(
            client_id=CLIENT_ID,
            sales_order_id=so.id,
            delivery_id=None,
            destination_country=cust.country,
            material_code="CTRL-HC200",
            hs_code="8542.39.00",
            eccn=eccn,
            quantity=Decimal(str(qty)),
            quantity_unit="PC",
            declared_value_usd=Decimal(str(total_usd)),
            license_type="individual" if cust.country == "CN" else None,
            license_authority="BIS" if lot_coo == "US" else "METI",
            status="DRAFT",
            remarks=(
                f"[Period {period}] {note[:200]}"
                + (f" | COO={lot_coo}" if lot_coo else " | COO=UNKNOWN/MIXED")
                + (f" | ECCN={eccn}")
            ),
        )
        db.add(decl)
        db.flush()
        count += 1
        risk = "🚨 EAR→CN" if cust.country == "CN" else "🔴 軍需" if "Defense" in cust.name else "⚠️"
        ok(f"{risk}  ExportDecl  SO-{so.document_number}  {cust.country}  {eccn}  DRAFT")

    db.commit()
    print(f"\n  輸出申告書 合計 {count} 件生成")


# ──────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 65)
    print("  COO Risk Demo Seeder  (CTRL-HC200 / 5 Lots / 50 SOs)")
    print("  Client: DEMO  |  Plant: P001")
    print("═" * 65)

    create_all_tables()
    db = SessionLocal()
    try:
        materials  = seed_materials(db)
        bps        = seed_business_partners(db)
        _pm        = seed_production_master(db)
        seed_procurement_master(db)
        seed_production_lots(db)
        seed_stock_balances(db)
        so_list    = seed_sales_orders(db, bps)
        push_to_aitm(db, so_list, materials)
        seed_export_declarations(db, so_list)

        print("\n" + "═" * 65)
        print("  ✅  デモデータ生成完了")
        print()
        print("  製造ロット:  5件 (Lot1-2=JP安全, Lot3=⚠️混在, Lot4-5=US)")
        print("  受注件数:    50件 (Period1=18, Period2=12, Period3=20)")
        print(f"  取引先:      {len([v for v in VENDORS])}ベンダー + {len(CUSTOMERS)}顧客")
        print()
        print("  ── リスクポイント ──")
        print("  Period 2 (2026-04-07~04-24): COO 混在リスク期間")
        print("    CN向け 2件 → BLOCKED")
        print("    軍需顧客向け 2件 → PENDING")
        print("  Period 3 (2026-04-25~06-05): US-origin EAR 管轄")
        print("    CN向け 3件 → 輸出許可審査 (PENDING/BLOCKED)")
        print("    軍需顧客向け 1件 → 最終用途証明書必須")
        print("═" * 65)
    finally:
        db.close()


if __name__ == "__main__":
    main()
