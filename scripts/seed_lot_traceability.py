#!/usr/bin/env python3
"""Seed lot traceability data: material batches, genealogy, origin-change events, De Minimis alerts.

Scenario:
  - MAT-9000001 (PGMEA Solvent): JP-origin through 2025-11, switches to US (Honeywell) from 2026-01
    Impact: ArF/KrF photoresists gain ~4-5% US content (below 25% threshold → WARNING only)

  - MAT-9000004 (CMP Additive/PAG Polymer): JP-origin through 2025-12, switches to US from 2026-02
    Impact: CMP Slurry W gains ~32.8% US content → BREACH
             CMP Slurry Cu gains ~29.9% US content → BREACH

This triggers:
  - MaterialOriginChangeLog entries for each switch
  - LotDeMinimusAssessment for every FG batch produced after origin switch date
  - AI_TM notification flag for BREACH-level assessments

Usage:
    python scripts/seed_lot_traceability.py
"""
import sys, os, json, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
random.seed(99)

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

# Register all models
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
from app.modules.pp.execution_models import ProcessOrder, Batch, BatchGenealogy
from app.modules.gts.models import MaterialOriginChangeLog, LotDeMinimusAssessment
from app.modules.mdm.models import Material
from app.modules.qm.models import InspectionLot, InspectionResult, QualityCertificate

CLIENT_ID = "DEMO"
USER = "seed@example.com"
PLANT_CODE = "1000"

# ── Raw material unit costs (JPY) ─────────────────────────────────
# Used for De Minimis value calculation
RAW_COSTS = {
    "MAT-9000001": {"JP": Decimal("3200"), "US": Decimal("3800"), "unit": "KG"},  # PGMEA
    "MAT-9000002": {"JP": Decimal("800"),  "US": Decimal("950"),  "unit": "L"},   # H2O2
    "MAT-9000003": {"JP": Decimal("15000"),"US": Decimal("17500"),"unit": "KG"},  # Colloidal Silica
    "MAT-9000004": {"JP": Decimal("75000"),"US": Decimal("82000"),"unit": "L"},   # CMP additive/PAG
}

# ── BOM: finished material → list of (raw_code, qty_per_unit_fg, unit) ──
BOM = {
    "MAT-1000001": [("MAT-9000001", Decimal("1.05"), "KG"),
                    ("MAT-9000002", Decimal("0.02"),  "L"),
                    ("MAT-9000003", Decimal("0.005"), "KG")],
    "MAT-1000002": [("MAT-9000001", Decimal("1.03"), "KG"),
                    ("MAT-9000003", Decimal("0.004"), "KG")],
    "MAT-1000003": [("MAT-9000001", Decimal("1.10"), "KG"),
                    ("MAT-9000002", Decimal("0.03"),  "L")],
    "MAT-2000001": [("MAT-9000001", Decimal("0.30"), "KG"),
                    ("MAT-9000004", Decimal("0.05"),  "L")],
    "MAT-2000002": [("MAT-9000001", Decimal("0.30"), "KG"),
                    ("MAT-9000004", Decimal("0.04"),  "L")],
    "MAT-3000001": [("MAT-9000002", Decimal("0.40"), "L"),
                    ("MAT-9000003", Decimal("0.10"),  "KG")],
    "MAT-4000001": [("MAT-9000001", Decimal("0.50"), "KG")],
    "MAT-4000002": [("MAT-9000001", Decimal("0.80"), "KG")],
}

# ── Finished goods unit price (JPY/unit) ─────────────────────────
FG_PRICE = {
    "MAT-1000001": Decimal("85000"),
    "MAT-1000002": Decimal("62000"),
    "MAT-1000003": Decimal("240000"),
    "MAT-2000001": Decimal("12500"),
    "MAT-2000002": Decimal("14800"),
    "MAT-3000001": Decimal("3800"),
    "MAT-4000001": Decimal("98000"),
    "MAT-4000002": Decimal("145000"),
}

# ── Origin switch schedule ────────────────────────────────────────
# After this date, the raw material is sourced from US
ORIGIN_SWITCH = {
    "MAT-9000001": {
        "date": date(2026, 1, 1),
        "from_country": "JP",
        "to_country": "US",
        "old_vendor": "VND-DAICEL-JP",
        "new_vendor": "VND-HONEYWELL-US",
        "old_vendor_name": "Daicel Corporation (Japan)",
        "new_vendor_name": "Honeywell Performance Materials (USA)",
    },
    "MAT-9000004": {
        "date": date(2026, 2, 1),
        "from_country": "JP",
        "to_country": "US",
        "old_vendor": "VND-JSR-JP",
        "new_vendor": "VND-DUPONT-US",
        "old_vendor_name": "JSR Corporation (Japan)",
        "new_vendor_name": "DuPont Electronic Materials (USA)",
    },
}

# ── QM spec limits for photoresist / CMP slurry ──────────────────
QM_SPECS = {
    "MAT-1000001": [("Viscosity", "NUMERIC", "cP", "12.0", "16.0"),
                    ("Particle>0.5um", "NUMERIC", "pcs/mL", None, "5"),
                    ("Water Content", "NUMERIC", "ppm", None, "20")],
    "MAT-1000002": [("Viscosity", "NUMERIC", "cP", "8.0", "12.0"),
                    ("Particle>0.5um", "NUMERIC", "pcs/mL", None, "10")],
    "MAT-2000001": [("pH", "NUMERIC", None, "3.0", "5.0"),
                    ("Slurry Concentration", "NUMERIC", "%wt", "23.0", "25.0"),
                    ("Particle Size D50", "NUMERIC", "nm", "70", "100")],
    "MAT-2000002": [("pH", "NUMERIC", None, "7.0", "9.0"),
                    ("Particle Size D50", "NUMERIC", "nm", "60", "90")],
}

INSP_COUNTER = [0]  # global counter for batch-local inspection IDs


def get_origin(material_code: str, production_date: date) -> str:
    switch = ORIGIN_SWITCH.get(material_code)
    if switch and production_date >= switch["date"]:
        return switch["to_country"]
    return "JP"


def get_vendor(material_code: str, production_date: date) -> str:
    switch = ORIGIN_SWITCH.get(material_code)
    if switch and production_date >= switch["date"]:
        return switch["new_vendor"]
    return switch["old_vendor"] if switch else "VND-JP-GENERIC"


def make_raw_batch_code(material_code: str, origin: str, seq: int) -> str:
    abbr = material_code.replace("MAT-", "").replace("-", "")
    return f"LOT-{abbr}-{origin}-{seq:03d}"


def make_fg_batch_code(material_code: str, po_number: str) -> str:
    abbr = material_code.replace("MAT-", "").replace("-", "")
    return f"FG-{abbr}-{po_number}"


def seed_raw_batches(db) -> dict[str, list[tuple[date, str]]]:
    """Create purchased raw material batches month by month. Returns {mat_code: [(date, batch_code), ...]}."""
    print("\n── Seeding raw material batches ──")
    # Build monthly demand from process orders
    pos = db.query(ProcessOrder).filter(
        ProcessOrder.client_id == CLIENT_ID,
        ProcessOrder.status == "COMPLETED",
    ).order_by(ProcessOrder.scheduled_start).all()

    # Aggregate monthly raw material needs from BOM
    monthly_needs: dict[tuple[int, int], dict[str, Decimal]] = {}
    for po in pos:
        mat = po.material_code
        if mat not in BOM:
            continue
        start = po.scheduled_start
        ym = (start.year, start.month)
        if ym not in monthly_needs:
            monthly_needs[ym] = {}
        qty = po.actual_quantity or po.target_quantity
        for raw_code, qty_per, _ in BOM[mat]:
            monthly_needs[ym][raw_code] = (
                monthly_needs[ym].get(raw_code, Decimal("0")) + qty * qty_per
            )

    lot_map: dict[str, list[tuple[date, str]]] = {}  # raw_code → [(date, batch_code)]
    seq_counters: dict[str, int] = {}

    for ym in sorted(monthly_needs.keys()):
        year, month = ym
        # Delivery mid-month prior
        delivery_date = date(year, month, 15) - timedelta(days=14)
        if delivery_date.month != month:
            delivery_date = date(year, month, 1)

        for raw_code, needed_qty in monthly_needs[ym].items():
            if raw_code not in RAW_COSTS:
                continue
            origin = get_origin(raw_code, delivery_date)
            vendor = get_vendor(raw_code, delivery_date)
            seq_counters[raw_code] = seq_counters.get(raw_code, 0) + 1
            seq = seq_counters[raw_code]
            batch_code = make_raw_batch_code(raw_code, origin, seq)

            # Add 20% safety buffer
            qty_received = (needed_qty * Decimal("1.2")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

            existing = db.query(Batch).filter(
                Batch.client_id == CLIENT_ID,
                Batch.batch_code == batch_code,
            ).first()
            if existing:
                continue

            batch = Batch(
                client_id=CLIENT_ID,
                batch_code=batch_code,
                material_code=raw_code,
                plant_code=PLANT_CODE,
                storage_location="WH01",
                quantity=qty_received,
                initial_quantity=qty_received,
                unit=RAW_COSTS[raw_code]["unit"],
                source_type="PURCHASED",
                source_reference=f"GR-{year}{month:02d}-{raw_code[-4:]}",
                country_of_origin=origin,
                vendor_code=vendor,
                quality_status="RELEASED",
                production_date=delivery_date,
                expiry_date=date(year + 1, month, 1),
                created_by=USER, updated_by=USER,
            )
            db.add(batch)

            if raw_code not in lot_map:
                lot_map[raw_code] = []
            lot_map[raw_code].append((delivery_date, batch_code))

    db.flush()
    print(f"  Created raw material batches for {len(lot_map)} materials")
    for rc, lots in lot_map.items():
        origins = [get_origin(rc, d) for d, _ in lots]
        changes = [f"{origins[i]}→{origins[i+1]}" for i in range(len(origins)-1) if origins[i] != origins[i+1]]
        flag = f"  *** ORIGIN CHANGE: {', '.join(changes)}" if changes else ""
        print(f"    {rc}: {len(lots)} batches{flag}")
    return lot_map


def seed_fg_batches_and_genealogy(db, lot_map: dict[str, list[tuple[date, str]]]) -> list[str]:
    """Create FG batches for each completed ProcessOrder and link via BatchGenealogy."""
    print("\n── Seeding FG batches + genealogy ──")
    pos = db.query(ProcessOrder).filter(
        ProcessOrder.client_id == CLIENT_ID,
        ProcessOrder.status == "COMPLETED",
    ).order_by(ProcessOrder.scheduled_start).all()

    fg_batch_codes: list[str] = []

    for po in pos:
        if po.material_code not in BOM:
            continue
        # Production date = scheduled end
        prod_date = (po.scheduled_end or po.scheduled_start).date()
        qty = po.actual_quantity or po.target_quantity
        fg_code = make_fg_batch_code(po.material_code, po.document_number)

        # FG batch origin = JP (manufactured in Japan, regardless of input origin)
        existing = db.query(Batch).filter(
            Batch.client_id == CLIENT_ID, Batch.batch_code == fg_code).first()
        if not existing:
            fg_batch = Batch(
                client_id=CLIENT_ID,
                batch_code=fg_code,
                material_code=po.material_code,
                plant_code=PLANT_CODE,
                storage_location="FG01",
                quantity=qty,
                initial_quantity=qty,
                unit=po.target_unit,
                source_type="PRODUCED",
                source_reference=po.document_number,
                country_of_origin="JP",  # manufactured in JP
                quality_status="RELEASED",
                production_date=prod_date,
                expiry_date=date(prod_date.year + 1, prod_date.month, prod_date.day),
                created_by=USER, updated_by=USER,
            )
            db.add(fg_batch)

        # Update ProcessOrder.finished_batch_code
        po.finished_batch_code = fg_code

        # BatchGenealogy: find raw batches received before or on production date
        for raw_code, qty_per, _ in BOM[po.material_code]:
            if raw_code not in lot_map:
                continue
            # Pick the most recent raw batch received before production date
            candidates = [(d, bc) for d, bc in lot_map[raw_code] if d <= prod_date]
            if not candidates:
                candidates = lot_map[raw_code][:1]  # fallback to earliest
            _, raw_batch_code = max(candidates, key=lambda x: x[0])

            consumed_qty = (qty * qty_per).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

            existing_gen = db.query(BatchGenealogy).filter(
                BatchGenealogy.client_id == CLIENT_ID,
                BatchGenealogy.parent_batch_code == raw_batch_code,
                BatchGenealogy.child_batch_code == fg_code,
            ).first()
            if not existing_gen:
                db.add(BatchGenealogy(
                    client_id=CLIENT_ID,
                    parent_batch_code=raw_batch_code,
                    child_batch_code=fg_code,
                    process_order_number=po.document_number,
                    consumed_quantity=consumed_qty,
                    consumed_unit=RAW_COSTS[raw_code]["unit"],
                    parent_material_code=raw_code,
                    child_material_code=po.material_code,
                    consumed_at=datetime.combine(prod_date, datetime.min.time()),
                    created_by=USER, updated_by=USER,
                ))

        db.flush()
        fg_batch_codes.append(fg_code)

    print(f"  Created {len(fg_batch_codes)} FG batches with genealogy links")
    return fg_batch_codes


def seed_fg_inspections(db, fg_batch_codes: list[str]):
    """Seed InspectionLots and results for finished goods batches."""
    print("\n── Seeding QM inspection lots for FG batches ──")
    insp_count = 0
    cert_count = 0

    from app.core.numbering import next_number

    for fg_code in fg_batch_codes:
        batch = db.query(Batch).filter(
            Batch.client_id == CLIENT_ID, Batch.batch_code == fg_code).first()
        if not batch or batch.material_code not in QM_SPECS:
            continue

        specs = QM_SPECS[batch.material_code]
        prod_date = batch.production_date

        # Check if inspection lot already exists for this batch (via source_number)
        existing_lot = db.query(InspectionLot).filter(
            InspectionLot.client_id == CLIENT_ID,
            InspectionLot.source_number == fg_code,
        ).first()
        if existing_lot:
            continue

        lot_number = next_number(db, CLIENT_ID, "INSP")
        insp_lot = InspectionLot(
            client_id=CLIENT_ID,
            lot_number=lot_number,
            material_code=batch.material_code,
            plant_code=PLANT_CODE,
            source_type="PRODUCED",
            source_number=fg_code,
            lot_quantity=batch.initial_quantity,
            quantity_unit=batch.unit,
            lot_status="PASSED",
            overall_judgment="PASS",
            created_date=prod_date,
            completed_date=prod_date + timedelta(days=2),
            created_by=USER, updated_by=USER,
        )
        db.add(insp_lot)
        db.flush()

        # Add results for each spec characteristic
        for char_name, char_type, uom, lower, upper in specs:
            if char_type == "NUMERIC":
                low = Decimal(lower) if lower else None
                up = Decimal(upper) if upper else None
                if low and up:
                    measured = low + (up - low) * Decimal("0.4")
                elif up:
                    measured = up * Decimal("0.6")
                else:
                    measured = Decimal("5")
                measured = measured.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                measured = None

            db.add(InspectionResult(
                client_id=CLIENT_ID,
                lot_id=insp_lot.id,
                char_code=char_name[:20],
                description=char_name,
                measurement_type=char_type,
                unit=uom,
                lower_limit=Decimal(lower) if lower else None,
                upper_limit=Decimal(upper) if upper else None,
                measured_value=measured,
                judgment="PASS",
                inspected_by=USER,
                inspected_at=datetime.combine(prod_date + timedelta(days=1), datetime.min.time()),
            ))

        # Issue CoA for this lot
        cert_number = next_number(db, CLIENT_ID, "COA")
        db.add(QualityCertificate(
            client_id=CLIENT_ID,
            cert_number=cert_number,
            lot_id=insp_lot.id,
            material_code=batch.material_code,
            issue_date=prod_date + timedelta(days=2),
            expiry_date=batch.expiry_date,
            issued_by=USER,
            all_passed=True,
        ))

        insp_count += 1
        cert_count += 1

        if insp_count % 20 == 0:
            db.flush()

    db.flush()
    print(f"  Created {insp_count} inspection lots, {cert_count} CoAs")


def calculate_deminimis(fg_material_code: str, fg_batch_code: str, db) -> dict:
    """Calculate De Minimis for a specific FG batch using consumed raw lot origins."""
    # Get genealogy for this FG batch
    genealogy = db.query(BatchGenealogy).filter(
        BatchGenealogy.client_id == CLIENT_ID,
        BatchGenealogy.child_batch_code == fg_batch_code,
    ).all()

    fg_price = FG_PRICE.get(fg_material_code, Decimal("0"))
    fg_batch = db.query(Batch).filter(
        Batch.client_id == CLIENT_ID, Batch.batch_code == fg_batch_code).first()
    if not fg_batch or fg_price == 0:
        return {"us_content_pct": Decimal("0"), "alert_level": "OK", "us_components": []}

    qty = fg_batch.initial_quantity
    total_product_value = qty * fg_price

    us_origin_value = Decimal("0")
    us_components = []
    total_bom_value = Decimal("0")

    for gen in genealogy:
        raw_code = gen.parent_material_code
        if raw_code not in RAW_COSTS:
            continue
        raw_batch = db.query(Batch).filter(
            Batch.client_id == CLIENT_ID, Batch.batch_code == gen.parent_batch_code).first()
        if not raw_batch:
            continue
        origin = raw_batch.country_of_origin
        unit_cost = RAW_COSTS[raw_code].get(origin, RAW_COSTS[raw_code]["JP"])
        component_value = gen.consumed_quantity * unit_cost
        total_bom_value += component_value

        if origin == "US":
            us_origin_value += component_value
            us_pct = float(component_value / total_product_value * 100)
            us_components.append({
                "material_code": raw_code,
                "batch_code": gen.parent_batch_code,
                "country_of_origin": origin,
                "consumed_qty": float(gen.consumed_quantity),
                "unit_cost_jpy": float(unit_cost),
                "value_jpy": float(component_value),
                "pct_of_product": round(us_pct, 2),
            })

    us_content_pct = (us_origin_value / total_product_value * 100).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP) if total_product_value else Decimal("0")

    if us_content_pct >= Decimal("25"):
        alert_level = "BREACH"
    elif us_content_pct >= Decimal("10"):
        alert_level = "WARNING"
    else:
        alert_level = "OK"

    return {
        "us_origin_value": us_origin_value,
        "total_product_value": total_product_value,
        "total_bom_value": total_bom_value,
        "us_content_pct": us_content_pct,
        "alert_level": alert_level,
        "us_components": us_components,
    }


def seed_deminimis_assessments(db, fg_batch_codes: list[str]):
    """Run De Minimis assessment for every FG batch and persist results."""
    print("\n── Running De Minimis assessments ──")
    breach_count = 0
    warning_count = 0
    ok_count = 0

    # Get FG batch → process order mapping
    po_map = {po.finished_batch_code: po.document_number
              for po in db.query(ProcessOrder).filter(
                  ProcessOrder.client_id == CLIENT_ID,
                  ProcessOrder.finished_batch_code.isnot(None)).all()}

    for fg_code in fg_batch_codes:
        batch = db.query(Batch).filter(
            Batch.client_id == CLIENT_ID, Batch.batch_code == fg_code).first()
        if not batch:
            continue

        # Skip if assessment already exists
        existing = db.query(LotDeMinimusAssessment).filter(
            LotDeMinimusAssessment.client_id == CLIENT_ID,
            LotDeMinimusAssessment.fg_batch_code == fg_code,
        ).first()
        if existing:
            continue

        result = calculate_deminimis(batch.material_code, fg_code, db)
        if result["us_content_pct"] == 0 and not result["us_components"]:
            ok_count += 1
            continue  # No US components, skip

        po_number = po_map.get(fg_code, "")
        assessment = LotDeMinimusAssessment(
            client_id=CLIENT_ID,
            fg_batch_code=fg_code,
            fg_material_code=batch.material_code,
            process_order_number=po_number,
            us_origin_value=result["us_origin_value"].quantize(Decimal("0.01")),
            total_bom_value=result["total_bom_value"].quantize(Decimal("0.01")),
            us_content_pct=result["us_content_pct"],
            threshold_pct=Decimal("25.0"),
            alert_level=result["alert_level"],
            us_components_json=json.dumps(result["us_components"]),
            ai_tm_notified=False,
            assessed_at=datetime.utcnow(),
            created_by=USER,
        )
        db.add(assessment)

        if result["alert_level"] == "BREACH":
            breach_count += 1
        elif result["alert_level"] == "WARNING":
            warning_count += 1
        else:
            ok_count += 1

    db.flush()
    print(f"  Assessments: {breach_count} BREACH | {warning_count} WARNING | {ok_count} OK")

    # Show worst cases
    worst = db.query(LotDeMinimusAssessment).filter(
        LotDeMinimusAssessment.client_id == CLIENT_ID,
        LotDeMinimusAssessment.alert_level == "BREACH",
    ).order_by(LotDeMinimusAssessment.us_content_pct.desc()).limit(5).all()
    for a in worst:
        print(f"    BREACH: {a.fg_batch_code} ({a.fg_material_code}) → {a.us_content_pct}% US content")


def seed_origin_change_logs(db, lot_map: dict[str, list[tuple[date, str]]]):
    """Record MaterialOriginChangeLog for each switch event."""
    print("\n── Seeding origin change logs ──")

    for raw_code, switch_info in ORIGIN_SWITCH.items():
        existing = db.query(MaterialOriginChangeLog).filter(
            MaterialOriginChangeLog.client_id == CLIENT_ID,
            MaterialOriginChangeLog.material_code == raw_code,
            MaterialOriginChangeLog.effective_date == switch_info["date"],
        ).first()
        if existing:
            print(f"  Already exists: {raw_code} @ {switch_info['date']}")
            continue

        batches = lot_map.get(raw_code, [])
        switch_date = switch_info["date"]

        jp_batches = [(d, bc) for d, bc in batches if d < switch_date]
        us_batches = [(d, bc) for d, bc in batches if d >= switch_date]
        last_jp = max(jp_batches, key=lambda x: x[0])[1] if jp_batches else None
        first_us = min(us_batches, key=lambda x: x[0])[1] if us_batches else None

        # Find affected FG materials (those using this raw in BOM)
        affected_fg = [fg for fg, bom in BOM.items() if any(r == raw_code for r, _, _ in bom)]

        # Calculate worst-case De Minimis impact for each affected FG
        max_impact = Decimal("0")
        for fg_code in affected_fg:
            if fg_code not in FG_PRICE or raw_code not in RAW_COSTS:
                continue
            # Worst case: all raw input is US-origin
            bom_row = next((row for row in BOM.get(fg_code, []) if row[0] == raw_code), None)
            if not bom_row:
                continue
            qty_per = bom_row[1]
            us_cost = RAW_COSTS[raw_code]["US"]
            fg_price = FG_PRICE[fg_code]
            impact = (qty_per * us_cost / fg_price * 100).quantize(Decimal("0.01"))
            if impact > max_impact:
                max_impact = impact

        exceeds = max_impact >= Decimal("25")

        log = MaterialOriginChangeLog(
            client_id=CLIENT_ID,
            material_code=raw_code,
            from_country=switch_info["from_country"],
            to_country=switch_info["to_country"],
            effective_date=switch_info["date"],
            old_vendor_code=switch_info["old_vendor"],
            new_vendor_code=switch_info["new_vendor"],
            last_old_batch_code=last_jp,
            first_new_batch_code=first_us,
            affected_fg_codes_json=json.dumps(affected_fg),
            max_deminimis_impact_pct=max_impact,
            exceeds_threshold=exceeds,
            threshold_pct=Decimal("25.0"),
            ai_tm_notification_sent=False,
            review_status="PENDING" if exceeds else "REVIEWED",
            created_by=USER,
        )
        db.add(log)
        flag = " *** BREACH THRESHOLD" if exceeds else ""
        print(f"  {raw_code}: {switch_info['from_country']}→{switch_info['to_country']} "
              f"@ {switch_info['date']}  max_impact={max_impact}%{flag}")
        print(f"    Last JP batch: {last_jp} | First US batch: {first_us}")
        print(f"    Affected FG: {affected_fg}")

    db.flush()


def main():
    create_all_tables()
    db = SessionLocal()
    try:
        print("=== Lot Traceability Seeder ===")
        print("Scenario: PGMEA (MAT-9000001) JP→US @ 2026-01")
        print("         CMP Additive (MAT-9000004) JP→US @ 2026-02")

        # 1. Raw material batches with origin tracking
        lot_map = seed_raw_batches(db)
        db.commit()

        # 2. FG batches + genealogy linking
        fg_batch_codes = seed_fg_batches_and_genealogy(db, lot_map)
        db.commit()

        # 3. Origin change event logs
        seed_origin_change_logs(db, lot_map)
        db.commit()

        # 4. De Minimis assessments per FG batch
        seed_deminimis_assessments(db, fg_batch_codes)
        db.commit()

        # 5. QM inspection lots + CoAs for FG batches
        seed_fg_inspections(db, fg_batch_codes)
        db.commit()

        # Summary
        print("\n═══════ Lot Traceability Seeding Complete ═══════")
        raw_count = db.query(Batch).filter(Batch.client_id == CLIENT_ID, Batch.source_type == "PURCHASED").count()
        fg_count = db.query(Batch).filter(Batch.client_id == CLIENT_ID, Batch.source_type == "PRODUCED").count()
        gen_count = db.query(BatchGenealogy).filter(BatchGenealogy.client_id == CLIENT_ID).count()
        breach_count = db.query(LotDeMinimusAssessment).filter(
            LotDeMinimusAssessment.client_id == CLIENT_ID,
            LotDeMinimusAssessment.alert_level == "BREACH").count()
        warn_count = db.query(LotDeMinimusAssessment).filter(
            LotDeMinimusAssessment.client_id == CLIENT_ID,
            LotDeMinimusAssessment.alert_level == "WARNING").count()
        log_count = db.query(MaterialOriginChangeLog).filter(
            MaterialOriginChangeLog.client_id == CLIENT_ID).count()
        insp_count = db.query(InspectionLot).filter(InspectionLot.client_id == CLIENT_ID).count()
        cert_count = db.query(QualityCertificate).filter(QualityCertificate.client_id == CLIENT_ID).count()

        print(f"  Raw material batches:    {raw_count}")
        print(f"  FG batches (produced):   {fg_count}")
        print(f"  Batch genealogy links:   {gen_count}")
        print(f"  Origin change logs:      {log_count}")
        print(f"  De Minimis assessments:  {breach_count} BREACH | {warn_count} WARNING")
        print(f"  Inspection lots:         {insp_count}")
        print(f"  CoAs issued:             {cert_count}")

    except Exception:
        db.rollback()
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
