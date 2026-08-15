#!/usr/bin/env python3
"""Seed open/released production orders to demonstrate the production schedule view.

Usage:
    python scripts/seed_production_plan.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timedelta
from decimal import Decimal

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
from app.modules.pp.execution_models import ProcessOrder, ProcessOrderComponent

CLIENT_ID = "DEMO"
USER      = "seed@example.com"
TODAY     = date.today()


def make_order(db, material_code, plant_code, pv_code, target_qty, status,
               start_delta_days, end_delta_days, components):
    order_number = next_number(db, CLIENT_ID, "PROCESS_ORDER")
    start = datetime.combine(TODAY + timedelta(days=start_delta_days), datetime.min.time())
    end   = datetime.combine(TODAY + timedelta(days=end_delta_days),   datetime.min.time())
    order = ProcessOrder(
        client_id=CLIENT_ID,
        document_number=order_number,
        material_code=material_code,
        plant_code=plant_code,
        production_version_code=pv_code,
        target_quantity=Decimal(str(target_qty)),
        target_unit="PC",
        actual_quantity=Decimal("0"),
        scrapped_quantity=Decimal("0"),
        scheduled_start=start,
        scheduled_end=end,
        status=status,
        created_by=USER, updated_by=USER,
    )
    db.add(order)
    db.flush()

    for idx, (mat_code, planned_qty, unit) in enumerate(components, start=10):
        comp = ProcessOrderComponent(
            process_order_id=order.id,
            item_no=idx * 10,
            material_code=mat_code,
            planned_quantity=Decimal(str(planned_qty)),
            issued_quantity=Decimal("0"),
            unit=unit,
            created_by=USER, updated_by=USER,
        )
        db.add(comp)
    db.flush()
    print(f"  {status:10s} {order_number} → {material_code} x{target_qty}  start={TODAY + timedelta(days=start_delta_days)}")
    return order


def main():
    create_all_tables()
    db = SessionLocal()
    try:
        print("=== Production Plan: seeding open/released process orders ===")

        # Fetch available production version codes
        from app.modules.pp.models import ProductionVersion
        pvs = {pv.material_code: pv.version_code
               for pv in db.query(ProductionVersion).filter(
                   ProductionVersion.client_id == CLIENT_ID).all()}

        def pv(mat): return pvs.get(mat, "PV-DEFAULT")

        # ── CTRL-HC200: stock=596, SO_demand=627 → need ~31 more ──
        make_order(db, "CTRL-HC200", "P001", pv("CTRL-HC200"), 200, "RELEASED",
                   start_delta_days=-2, end_delta_days=3,
                   components=[
                       ("SIL-WAF-JP",  50,  "PC"),
                       ("ADH-EPOXY-01", 20, "KG"),
                   ])

        make_order(db, "CTRL-HC200", "P001", pv("CTRL-HC200"), 150, "OPEN",
                   start_delta_days=4, end_delta_days=10,
                   components=[
                       ("SIL-WAF-US",  40,  "PC"),
                       ("ADH-EPOXY-01", 15, "KG"),
                   ])

        # ── MAT-1000001 (standard product) ──
        make_order(db, "MAT-1000001", "1000", pv("MAT-1000001"), 500, "RELEASED",
                   start_delta_days=0, end_delta_days=7,
                   components=[
                       ("MAT-9000001", 1500, "KG"),
                       ("MAT-9000002",  250, "PC"),
                   ])

        make_order(db, "MAT-1000001", "1000", pv("MAT-1000001"), 300, "OPEN",
                   start_delta_days=8, end_delta_days=15,
                   components=[
                       ("MAT-9000001", 900, "KG"),
                       ("MAT-9000002", 150, "PC"),
                   ])

        # ── MAT-2000001 ──
        make_order(db, "MAT-2000001", "1000", pv("MAT-2000001"), 1000, "DRAFT",
                   start_delta_days=14, end_delta_days=21,
                   components=[
                       ("MAT-9000003", 3000, "KG"),
                       ("MAT-9000004",  200, "PC"),
                   ])

        # ── SIL-WAF-JP: replenishment PO already open; add a production order too ──
        make_order(db, "SIL-WAF-JP", "P001", pv("SIL-WAF-JP"), 100, "OPEN",
                   start_delta_days=5, end_delta_days=12,
                   components=[
                       ("PKG-CERAMIC", 100, "PC"),
                   ])

        db.commit()
        print("\nProduction plan seeding complete.")
    except Exception as e:
        db.rollback()
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
