#!/usr/bin/env python3
"""Demo data seeder for CO (Controlling) and QM (Quality Management) modules.

Usage:
    python scripts/seed_co_qm.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from decimal import Decimal

import app.modules.mdm.models   # noqa: F401 — register FK targets
import app.modules.sd.models    # noqa: F401
import app.modules.pp.models    # noqa: F401
import app.modules.fi.models    # noqa: F401
import app.modules.hr.models    # noqa: F401
import app.modules.mm.models    # noqa: F401
import app.modules.gts.models   # noqa: F401
import app.modules.co.models    # noqa: F401
import app.modules.qm.models    # noqa: F401

from app.core.database import SessionLocal, create_all_tables
from app.core.numbering import next_number
from app.modules.co import models as co
from app.modules.qm import models as qm

CLIENT_ID = "DEMO"
USER      = "seed@example.com"
FY        = 2025


def seed_co(db):
    print("=== CO: Assets ===")
    assets = [
        co.AssetMaster(
            client_id=CLIENT_ID,
            asset_code="MCH-001",
            description="射出成型機 #1",
            asset_class="MACHINERY",
            work_center_code="WC-MOLD",
            plant_code="P001",
            acquisition_cost=Decimal("12000000"),
            residual_value=Decimal("500000"),
            useful_life_years=10,
            depreciation_method="straight_line",
            acquisition_date=date(2020, 4, 1),
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.AssetMaster(
            client_id=CLIENT_ID,
            asset_code="MCH-002",
            description="CNC 加工機 #1",
            asset_class="MACHINERY",
            work_center_code="WC-CNC",
            plant_code="P001",
            acquisition_cost=Decimal("8000000"),
            residual_value=Decimal("200000"),
            useful_life_years=8,
            depreciation_method="straight_line",
            acquisition_date=date(2021, 10, 1),
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.AssetMaster(
            client_id=CLIENT_ID,
            asset_code="MCH-003",
            description="組立ライン搬送設備",
            asset_class="MACHINERY",
            work_center_code="WC-ASSY",
            plant_code="P001",
            acquisition_cost=Decimal("5000000"),
            residual_value=Decimal("100000"),
            useful_life_years=12,
            depreciation_method="straight_line",
            acquisition_date=date(2019, 7, 1),
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
    ]
    for a in assets:
        db.merge(a)  # upsert by PK — but we use add if not present
    db.flush()

    print("=== CO: Asset Cost Rates ===")
    rates = [
        co.AssetCostRate(
            client_id=CLIENT_ID, asset_code="MCH-001", fiscal_year=FY,
            depreciation_plan=Decimal("1150000"),
            maintenance_plan=Decimal("300000"),
            utility_plan=Decimal("200000"),
            planned_hours=Decimal("2000"),
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.AssetCostRate(
            client_id=CLIENT_ID, asset_code="MCH-002", fiscal_year=FY,
            depreciation_plan=Decimal("975000"),
            maintenance_plan=Decimal("150000"),
            utility_plan=Decimal("100000"),
            planned_hours=Decimal("1800"),
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.AssetCostRate(
            client_id=CLIENT_ID, asset_code="MCH-003", fiscal_year=FY,
            depreciation_plan=Decimal("408333"),
            maintenance_plan=Decimal("80000"),
            utility_plan=Decimal("60000"),
            planned_hours=Decimal("2200"),
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
    ]
    for r in rates:
        r.machine_rate = r.calculate_rate()
        db.add(r)
    db.flush()

    print("=== CO: Cost Centers ===")
    ccs = [
        co.CostCenter(
            client_id=CLIENT_ID, cost_center_code="CC-MOLD", name="成型部門",
            cost_center_type="production", plant_code="P001",
            work_center_code="WC-MOLD", currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.CostCenter(
            client_id=CLIENT_ID, cost_center_code="CC-CNC", name="加工部門",
            cost_center_type="production", plant_code="P001",
            work_center_code="WC-CNC", currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.CostCenter(
            client_id=CLIENT_ID, cost_center_code="CC-ASSY", name="組立部門",
            cost_center_type="production", plant_code="P001",
            work_center_code="WC-ASSY", currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.CostCenter(
            client_id=CLIENT_ID, cost_center_code="CC-ADMIN", name="管理部門",
            cost_center_type="admin", plant_code="P001",
            currency="JPY",
            created_by=USER, updated_by=USER,
        ),
    ]
    for cc in ccs:
        db.add(cc)
    db.flush()

    print("=== CO: Cost Center Budgets ===")
    budgets = [
        co.CostCenterBudget(
            client_id=CLIENT_ID, cost_center_code="CC-MOLD", fiscal_year=FY,
            labor_budget=Decimal("12000000"), planned_labor_hours=Decimal("2000"),
            indirect_budget=Decimal("2400000"), currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.CostCenterBudget(
            client_id=CLIENT_ID, cost_center_code="CC-CNC", fiscal_year=FY,
            labor_budget=Decimal("10800000"), planned_labor_hours=Decimal("1800"),
            indirect_budget=Decimal("1620000"), currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.CostCenterBudget(
            client_id=CLIENT_ID, cost_center_code="CC-ASSY", fiscal_year=FY,
            labor_budget=Decimal("13200000"), planned_labor_hours=Decimal("2200"),
            indirect_budget=Decimal("1980000"), currency="JPY",
            created_by=USER, updated_by=USER,
        ),
        co.CostCenterBudget(
            client_id=CLIENT_ID, cost_center_code="CC-ADMIN", fiscal_year=FY,
            labor_budget=Decimal("24000000"), planned_labor_hours=Decimal("2000"),
            indirect_budget=Decimal("6000000"), currency="JPY",
            created_by=USER, updated_by=USER,
        ),
    ]
    for b in budgets:
        b.labor_rate = b.calculate_labor_rate()
        db.add(b)
    db.flush()

    print("CO seeding complete.")


def seed_qm(db):
    print("=== QM: Material Specs ===")
    # Fetch a material code from existing data (or use a placeholder)
    from app.modules.mdm.models import Material
    materials = db.query(Material).filter(
        Material.client_id == CLIENT_ID
    ).limit(3).all()

    mat_codes = [m.material_code for m in materials]
    if not mat_codes:
        mat_codes = ["MAT-001", "MAT-002", "MAT-003"]
        print("  (No materials found in DB; using placeholder codes)")

    for i, mat_code in enumerate(mat_codes[:2]):
        spec = qm.MaterialSpec(
            client_id=CLIENT_ID,
            material_code=mat_code,
            revision="A",
            description=f"{mat_code} 品質規格 Rev.A",
            is_current=True,
            effective_from=date(FY, 4, 1),
            approved_by="品質管理部長",
            created_by=USER, updated_by=USER,
        )
        db.add(spec)
        db.flush()

        # Add 2-3 characteristics per spec
        chars = [
            qm.SpecCharacteristic(
                client_id=CLIENT_ID, spec_id=spec.id,
                char_code="PURITY", description="純度 (%)",
                measurement_type="NUMERIC", unit="%",
                target_value=Decimal("99.9"),
                lower_limit=Decimal("99.5"),
                upper_limit=Decimal("100.0"),
                is_critical=True,
                created_by=USER, updated_by=USER,
            ),
            qm.SpecCharacteristic(
                client_id=CLIENT_ID, spec_id=spec.id,
                char_code="MOISTURE", description="水分量 (%)",
                measurement_type="NUMERIC", unit="%",
                target_value=Decimal("0.1"),
                lower_limit=Decimal("0"),
                upper_limit=Decimal("0.5"),
                is_critical=False,
                created_by=USER, updated_by=USER,
            ),
            qm.SpecCharacteristic(
                client_id=CLIENT_ID, spec_id=spec.id,
                char_code="APPEARANCE", description="外観検査",
                measurement_type="BOOLEAN",
                acceptable_text="異常なし",
                is_critical=True,
                created_by=USER, updated_by=USER,
            ),
        ]
        for c in chars:
            db.add(c)
    db.flush()

    print("=== QM: Inspection Plans ===")
    for i, mat_code in enumerate(mat_codes[:2]):
        plan = qm.InspectionPlan(
            client_id=CLIENT_ID,
            plan_code=f"IP-{mat_code}-OUT",
            material_code=mat_code,
            plant_code="P001",
            inspection_type="OUTGOING",
            description=f"{mat_code} 出荷前検査計画",
            sample_size=5,
            sample_unit="EA",
            valid_from=date(FY, 4, 1),
            created_by=USER, updated_by=USER,
        )
        db.add(plan)
        db.flush()

        ops = [
            qm.InspectionOperation(
                client_id=CLIENT_ID, plan_id=plan.id,
                operation_no=10, char_code="PURITY",
                description="純度測定", required=True,
                created_by=USER, updated_by=USER,
            ),
            qm.InspectionOperation(
                client_id=CLIENT_ID, plan_id=plan.id,
                operation_no=20, char_code="MOISTURE",
                description="水分測定", required=True,
                created_by=USER, updated_by=USER,
            ),
            qm.InspectionOperation(
                client_id=CLIENT_ID, plan_id=plan.id,
                operation_no=30, char_code="APPEARANCE",
                description="外観確認", required=True,
                created_by=USER, updated_by=USER,
            ),
        ]
        for op in ops:
            db.add(op)
    db.flush()

    print("=== QM: Inspection Lots ===")
    lot_number = next_number(db, CLIENT_ID, "INSP")
    lot = qm.InspectionLot(
        client_id=CLIENT_ID,
        lot_number=lot_number,
        material_code=mat_codes[0],
        plant_code="P001",
        inspection_type="OUTGOING",
        source_type="PROCESS_ORDER",
        source_number="PO-DEMO-001",
        lot_quantity=Decimal("1000"),
        quantity_unit="KG",
        created_date=date.today(),
        inspection_date=date.today(),
        lot_status="IN_INSPECTION",
        created_by=USER, updated_by=USER,
    )
    db.add(lot)
    db.flush()

    print("=== QM: Inspection Results ===")
    results = [
        qm.InspectionResult(
            client_id=CLIENT_ID, lot_id=lot.id,
            char_code="PURITY", description="純度 (%)",
            measurement_type="NUMERIC",
            measured_value=Decimal("99.8"),
            unit="%",
            lower_limit=Decimal("99.5"),
            upper_limit=Decimal("100.0"),
            target_value=Decimal("99.9"),
            judgment="PASS",
            is_critical=True,
            inspected_by=USER,
        ),
        qm.InspectionResult(
            client_id=CLIENT_ID, lot_id=lot.id,
            char_code="MOISTURE", description="水分量 (%)",
            measurement_type="NUMERIC",
            measured_value=Decimal("0.2"),
            unit="%",
            lower_limit=Decimal("0"),
            upper_limit=Decimal("0.5"),
            target_value=Decimal("0.1"),
            judgment="PASS",
            is_critical=False,
            inspected_by=USER,
        ),
        qm.InspectionResult(
            client_id=CLIENT_ID, lot_id=lot.id,
            char_code="APPEARANCE", description="外観検査",
            measurement_type="BOOLEAN",
            measured_bool=True,
            judgment="PASS",
            is_critical=True,
            inspected_by=USER,
        ),
    ]
    for r in results:
        db.add(r)
    db.flush()

    # Update lot judgment
    lot.lot_status = "PASSED"
    lot.overall_judgment = "PASS"
    lot.completed_date = date.today()
    db.flush()

    print("=== QM: Quality Certificate ===")
    cert_number = next_number(db, CLIENT_ID, "COA")
    cert = qm.QualityCertificate(
        client_id=CLIENT_ID,
        cert_number=cert_number,
        lot_id=lot.id,
        material_code=mat_codes[0],
        issue_date=date.today(),
        issued_by="品質管理部",
        all_passed=True,
        remarks="全特性合格。出荷承認済み。",
        created_by=USER,
    )
    db.add(cert)
    db.flush()

    print("=== QM: Quality Notification ===")
    qn_number = next_number(db, CLIENT_ID, "QN")
    qn = qm.QualityNotification(
        client_id=CLIENT_ID,
        notification_number=qn_number,
        notification_type="DEFECT",
        material_code=mat_codes[0] if len(mat_codes) > 1 else mat_codes[0],
        subject="原材料ロット 水分値 上限超過",
        description="入荷検査で水分値 0.6% を記録。上限 0.5% 超過のため是正処置実施。",
        defect_code="MC-001",
        severity="MEDIUM",
        reported_date=date.today(),
        reported_by=USER,
        assigned_to="品質管理部",
        status="OPEN",
        created_by=USER, updated_by=USER,
    )
    db.add(qn)
    db.flush()

    print("QM seeding complete.")


def main():
    create_all_tables()
    db = SessionLocal()
    try:
        seed_co(db)
        seed_qm(db)
        db.commit()
        print("\nAll CO/QM demo data committed successfully.")
    except Exception as e:
        db.rollback()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
