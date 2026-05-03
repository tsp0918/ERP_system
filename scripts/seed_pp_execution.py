"""Seed Production Execution scenarios.

Demonstrates the full manufacture-to-stock flow with batch genealogy.

Scenarios:
  ① Setup raw material batches (incl. one Chinese-origin lot)
  ② Process Order: PAG Polymer Solution (intermediate level)
       - Multiple raw batches consumed
       - Mixed origin (JP + CN) -> intermediate batch becomes mixed
  ③ Process Order: ArF Photoresist (top level, consumes intermediate)
       - Final product lot inherits genealogy back to all raw lots

End state: walking backward from finished ArF lot reveals:
  - Direct parents: PGMEA Solvent (JP), PAG Resin (DE), Quencher (JP),
    PAG Polymer Solution (intermediate)
  - Through PAG Polymer: PAG Monomer (JP), PGMEA Solvent (CN)
  → AI_TradeManagement can detect 'this finished lot contains CN-origin
    PGMEA' even though the top-level material says origin=JP.

Run order: seed.py -> seed_pp.py -> seed_mm.py -> seed_pp_execution.py
"""
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.pp import execution_schemas as exec_schemas
from app.modules.pp.execution_service import (
    BatchService, GenealogyService, GoodsIssueService,
    OperationConfirmService, ProcessOrderService,
    ProductionGoodsReceiptService,
)


CLIENT_ID = "DEMO"
ADMIN_EMAIL = settings.INITIAL_ADMIN_EMAIL


def _ensure_admin(db: Session):
    from app.core.auth_models import User
    return db.query(User).filter(User.email == ADMIN_EMAIL).first()


# ==================================================================
# Scenario 1: Opening raw-material batches
# ==================================================================
def _seed_raw_batches(db: Session, admin):
    print("\n[① Opening raw material batches at JP plant]")
    svc = BatchService(db)
    opening_batches = [
        # PAG Monomer - JP origin
        {"batch_code": "LOT-JP-PAGM-001", "material_code": "MAT-9000005",
         "plant_code": "1000", "quantity": Decimal("50"), "unit": "KG",
         "country_of_origin": "JP", "vendor_code": "BP-5000006",
         "production_date": date.today() - timedelta(days=30),
         "storage_location": "WH-RAW-01"},
        # PGMEA Solvent - JP origin (clean)
        {"batch_code": "LOT-JP-PGMEA-101", "material_code": "MAT-9000001",
         "plant_code": "1000", "quantity": Decimal("500"), "unit": "KG",
         "country_of_origin": "JP", "vendor_code": "BP-5000001",
         "storage_location": "WH-RAW-01"},
        # PGMEA Solvent - CN origin (this is the "trade-relevant" lot)
        {"batch_code": "LOT-CN-PGMEA-202", "material_code": "MAT-9000001",
         "plant_code": "1000", "quantity": Decimal("300"), "unit": "KG",
         "country_of_origin": "CN", "vendor_code": "BP-5000001",
         "storage_location": "WH-RAW-02"},
        # PAG Resin - DE origin
        {"batch_code": "LOT-DE-PAGR-A1", "material_code": "MAT-9000004",
         "plant_code": "1000", "quantity": Decimal("20"), "unit": "KG",
         "country_of_origin": "DE", "vendor_code": "BP-5000004",
         "storage_location": "WH-RAW-01"},
        # Quencher additive - JP
        {"batch_code": "LOT-JP-QNCH-001", "material_code": "MAT-9000006",
         "plant_code": "1000", "quantity": Decimal("10"), "unit": "KG",
         "country_of_origin": "JP", "vendor_code": "BP-5000001",
         "storage_location": "WH-RAW-01"},
    ]
    for spec in opening_batches:
        b = svc.create(exec_schemas.BatchCreate(**spec), CLIENT_ID, admin.email)
        db.commit()
        print(f"  ✓ Batch {b.batch_code:<25}  {b.material_code:<15}  "
              f"qty={b.quantity:>7} {b.unit:<3}  origin={b.country_of_origin}")


# ==================================================================
# Scenario 2: Manufacture intermediate (PAG Polymer Solution)
# ==================================================================
def _scenario_intermediate_production(db: Session, admin) -> str:
    print("\n[② Process Order: PAG Polymer Solution (intermediate)]")
    print("    - Will consume PAG Monomer + a mix of JP/CN PGMEA lots")
    print("    - Target output: 100 KG PAG Polymer Solution")

    # Create the process order
    order = ProcessOrderService(db).create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-8000001",
            plant_code="1000",
            target_quantity=Decimal("100"),
            target_unit="KG",
            scheduled_start=datetime.utcnow(),
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(order)
    print(f"  ✓ ProcessOrder #{order.document_number}  PV={order.production_version_code}")

    # Release
    ProcessOrderService(db).release(order.id, CLIENT_ID, admin.email)
    db.commit(); db.refresh(order)
    print(f"      released  status={order.status}")

    # Identify component IDs
    comp_by_material = {c.material_code: c for c in order.components}
    pag_comp = comp_by_material["MAT-9000005"]
    pgmea_comp = comp_by_material["MAT-9000001"]

    # Goods issue: PAG Monomer (full from JP lot)
    GoodsIssueService(db).post(
        exec_schemas.GoodsIssueRequest(
            process_order_id=order.id,
            lines=[exec_schemas.GoodsIssueLine(
                component_id=pag_comp.id,
                batch_code="LOT-JP-PAGM-001",
                quantity=pag_comp.planned_quantity,
            )],
        ),
        CLIENT_ID, admin.email,
    )
    db.commit()
    print(f"  ✓ Issued {pag_comp.planned_quantity} KG PAG Monomer (LOT-JP-PAGM-001)")

    # Goods issue: PGMEA - split between JP and CN lots
    half = (pgmea_comp.planned_quantity / Decimal("2")).quantize(Decimal("0.001"))
    remainder = pgmea_comp.planned_quantity - half
    GoodsIssueService(db).post(
        exec_schemas.GoodsIssueRequest(
            process_order_id=order.id,
            lines=[
                exec_schemas.GoodsIssueLine(
                    component_id=pgmea_comp.id,
                    batch_code="LOT-JP-PGMEA-101",
                    quantity=half,
                ),
                exec_schemas.GoodsIssueLine(
                    component_id=pgmea_comp.id,
                    batch_code="LOT-CN-PGMEA-202",
                    quantity=remainder,
                ),
            ],
        ),
        CLIENT_ID, admin.email,
    )
    db.commit()
    print(f"  ✓ Issued PGMEA split: {half} KG from JP lot + {remainder} KG from CN lot")

    # Confirm operations (just simulate - take planned values)
    db.refresh(order)
    for op in order.operations:
        OperationConfirmService(db).confirm(
            exec_schemas.OperationConfirmRequest(
                operation_id=op.id,
                actual_machine_minutes=op.planned_machine_minutes,
                actual_labor_minutes=op.planned_labor_minutes,
            ),
            CLIENT_ID, admin.email,
        )
    db.commit()
    print(f"  ✓ Confirmed {len(order.operations)} operations")

    # Goods receipt - finishes the order, creates child batch with genealogy
    intermediate_batch = "LOT-INT-PAGSOL-001"
    result = ProductionGoodsReceiptService(db).post(
        exec_schemas.ProductionGoodsReceiptRequest(
            process_order_id=order.id,
            quantity=Decimal("96"),  # 96 KG output (4% loss = mix of yield+scrap)
            scrapped_quantity=Decimal("0"),
            batch_code=intermediate_batch,
            storage_location="WH-INT-01",
        ),
        CLIENT_ID, admin.email,
    )
    db.commit()
    print(f"  ✓ Goods Receipt: produced batch {result.new_batch_code} "
          f"({result.quantity} KG)")
    print(f"      genealogy parents: {result.parent_batches}")

    return intermediate_batch


# ==================================================================
# Scenario 3: Manufacture finished product (ArF Photoresist)
# ==================================================================
def _scenario_finished_production(db: Session, admin, intermediate_batch: str) -> str:
    print("\n[③ Process Order: ArF Photoresist (finished product)]")
    print(f"    - Will consume the intermediate batch {intermediate_batch}")
    print("    - Plus PGMEA, PAG Resin, Quencher")
    print("    - Target output: 100 L ArF Photoresist")

    # Promote intermediate batch to RELEASED so we can issue it
    intermediate = db.query(__import__("app").modules.pp.execution_models.Batch).filter_by(
        client_id=CLIENT_ID, batch_code=intermediate_batch).first()
    intermediate.quality_status = "RELEASED"
    db.commit()
    print(f"  ✓ Promoted intermediate batch to RELEASED (mock QC pass)")

    order = ProcessOrderService(db).create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-1000001",
            plant_code="1000",
            target_quantity=Decimal("100"),
            target_unit="L",
            scheduled_start=datetime.utcnow(),
        ),
        CLIENT_ID, admin.email,
    )
    db.commit(); db.refresh(order)
    print(f"  ✓ ProcessOrder #{order.document_number}")

    ProcessOrderService(db).release(order.id, CLIENT_ID, admin.email)
    db.commit(); db.refresh(order)

    # Issue components
    comp_by_material = {c.material_code: c for c in order.components}
    issues = [
        # Intermediate batch - this is the genealogy chain link
        ("MAT-8000001", intermediate_batch),
        ("MAT-9000004", "LOT-DE-PAGR-A1"),
        ("MAT-9000006", "LOT-JP-QNCH-001"),
        ("MAT-9000001", "LOT-JP-PGMEA-101"),
    ]
    lines = []
    for mat, batch in issues:
        comp = comp_by_material[mat]
        lines.append(exec_schemas.GoodsIssueLine(
            component_id=comp.id,
            batch_code=batch,
            quantity=comp.planned_quantity,
        ))
    GoodsIssueService(db).post(
        exec_schemas.GoodsIssueRequest(process_order_id=order.id, lines=lines),
        CLIENT_ID, admin.email,
    )
    db.commit()
    print(f"  ✓ Issued {len(lines)} component batches")

    db.refresh(order)
    for op in order.operations:
        OperationConfirmService(db).confirm(
            exec_schemas.OperationConfirmRequest(
                operation_id=op.id,
                actual_machine_minutes=op.planned_machine_minutes,
                actual_labor_minutes=op.planned_labor_minutes,
            ),
            CLIENT_ID, admin.email,
        )
    db.commit()

    finished_batch = "LOT-FIN-ArF-001"
    result = ProductionGoodsReceiptService(db).post(
        exec_schemas.ProductionGoodsReceiptRequest(
            process_order_id=order.id,
            quantity=Decimal("92"),
            batch_code=finished_batch,
            storage_location="WH-FG-01",
        ),
        CLIENT_ID, admin.email,
    )
    db.commit()
    print(f"  ✓ Goods Receipt: produced finished batch {result.new_batch_code} "
          f"({result.quantity} L)")
    print(f"      direct genealogy parents: {result.parent_batches}")

    return finished_batch


# ==================================================================
# Scenario 4: Walk genealogy in both directions
# ==================================================================
def _show_genealogy(db: Session, finished_batch: str):
    print("\n[④ Genealogy traceability]")
    svc = GenealogyService(db)

    print(f"\n  ── BACKWARD trace from finished batch {finished_batch} ──")
    print("     'This finished lot was made from which raw lots?'")
    backward = svc.trace_backward(CLIENT_ID, finished_batch)
    _print_tree(backward.tree, indent=4)

    print(f"\n  ── FORWARD trace from CN-origin raw batch LOT-CN-PGMEA-202 ──")
    print("     'This Chinese PGMEA lot ended up in which finished lots?'")
    forward = svc.trace_forward(CLIENT_ID, "LOT-CN-PGMEA-202")
    _print_tree(forward.tree, indent=4)

    # Highlight the trade-relevant finding
    print("\n  💡 Trade compliance insight:")
    print(f"     Finished lot {finished_batch} contains CN-origin PGMEA via")
    print("     the intermediate, even though MAT-1000001 has origin=JP.")
    print("     This is the kind of structural data AI_TradeManagement needs")
    print("     to detect substantial-transformation / origin-rule issues.")


def _print_tree(node, indent: int = 0, prefix: str = ""):
    pad = " " * indent
    origin = f" origin={node.country_of_origin or '-'}"
    consumed = f"  consumed={node.consumed_quantity}" if node.consumed_quantity else ""
    print(f"{pad}{prefix}{node.batch_code:<24}  {node.material_code:<15} "
          f"qty={node.quantity:>7} {node.unit:<3}{origin}{consumed}")
    for i, child in enumerate(node.children):
        last = (i == len(node.children) - 1)
        _print_tree(child, indent + 4, prefix="└── " if last else "├── ")


# ==================================================================
# Main
# ==================================================================
def main():
    print("=" * 78)
    print("  Mini Global ERP - Phase 2D Execution Seed (ProcessOrder + Batch)")
    print("=" * 78)

    create_all_tables()
    db = SessionLocal()
    try:
        admin = _ensure_admin(db)
        if not admin:
            raise SystemExit("Run scripts/seed.py first.")

        _seed_raw_batches(db, admin)
        intermediate_batch = _scenario_intermediate_production(db, admin)
        finished_batch = _scenario_finished_production(db, admin, intermediate_batch)
        _show_genealogy(db, finished_batch)

        print("\n" + "=" * 78)
        print("  ✓ Execution seed complete.")
        print("=" * 78)
        print("  Try these endpoints:")
        print("    GET  /pp/process-orders")
        print(f"    GET  /pp/batches/{finished_batch}/genealogy/backward")
        print("    GET  /pp/batches/LOT-CN-PGMEA-202/genealogy/forward")
    finally:
        db.close()


if __name__ == "__main__":
    main()
