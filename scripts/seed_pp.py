"""Seed Production Planning master data.

Adds:
- 1 raw material that's missing (PAG Monomer) for the multi-level recipe
- 5 Work Centers (JP plant) + 5 Work Centers (TW plant) with different rates
- 3 Recipes (multi-level structure)
- 3 Routings
- Production Versions linking them
- Runs Cost Rollup at the end

After this script: cost comparison API can show the JP vs TW cost gap
that motivates transfer pricing analysis.
"""
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.mdm import schemas as mdm_schemas
from app.modules.mdm.models import Material
from app.modules.mdm.service import MaterialService
from app.modules.pp import schemas as pp_schemas
from app.modules.pp.service import (
    BomExplosionService, ComplianceSnapshotService, CostRollupService,
    ProductionVersionService, RecipeService, RoutingService, WorkCenterService,
)


CLIENT_ID = "DEMO"
ADMIN_EMAIL = settings.INITIAL_ADMIN_EMAIL


# ==================================================================
# 1. Additional raw material - PAG Monomer (a chemical intermediate)
# ==================================================================
ADDITIONAL_MATERIALS = [
    {"material_code": "MAT-9000005",
     "description": "PAG Monomer (Photoacid Generator Precursor)",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "65000", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-9000006",
     "description": "Quencher Additive (Trioctylamine Solution)",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "12000", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-9000007",
     "description": "pH Modifier (Aqueous KOH 5%)",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "1800", "currency": "JPY",
     "country_of_origin": "JP"},
    {"material_code": "MAT-9000008",
     "description": "Pure Water (DI Water Electronic Grade)",
     "material_type": "ROH", "base_unit": "KG",
     "standard_price": "150", "currency": "JPY",
     "country_of_origin": "JP"},
    # Intermediate (HALB) - PAG Polymer Solution. This will have its own recipe.
    {"material_code": "MAT-8000001",
     "description": "PAG Polymer Solution (Intermediate)",
     "material_type": "HALB", "base_unit": "KG",
     "standard_price": "0", "currency": "JPY",  # 計算で出るので0でOK
     "country_of_origin": "JP"},
]


# ==================================================================
# 2. Work Centers - JP plant (1000) + TW plant (3000) with different rates
# ==================================================================
WORK_CENTERS = [
    # ---- JP Plant (Plant 1000) - higher labor cost, higher OH ----
    {"work_center_code": "WC-MIX-JP", "description": "Reactor / Mixing Vessel #1",
     "plant_code": "1000", "capacity_per_day": "16", "capacity_unit": "H",
     "labor_rate_per_hour": "6000", "machine_rate_per_hour": "18000",
     "overhead_rate_percent": "12", "currency": "JPY"},
    {"work_center_code": "WC-DIST-JP", "description": "Distillation Column",
     "plant_code": "1000", "capacity_per_day": "20", "capacity_unit": "H",
     "labor_rate_per_hour": "6000", "machine_rate_per_hour": "25000",
     "overhead_rate_percent": "12", "currency": "JPY"},
    {"work_center_code": "WC-FILT-JP", "description": "Precision Filtration",
     "plant_code": "1000", "capacity_per_day": "16", "capacity_unit": "H",
     "labor_rate_per_hour": "6000", "machine_rate_per_hour": "15000",
     "overhead_rate_percent": "12", "currency": "JPY"},
    {"work_center_code": "WC-PACK-JP", "description": "Cleanroom Filling Line",
     "plant_code": "1000", "capacity_per_day": "16", "capacity_unit": "H",
     "labor_rate_per_hour": "7000", "machine_rate_per_hour": "8000",
     "overhead_rate_percent": "15", "currency": "JPY"},
    {"work_center_code": "WC-QC-JP", "description": "QC Lab (Specs / Particle Count)",
     "plant_code": "1000", "capacity_per_day": "8", "capacity_unit": "H",
     "labor_rate_per_hour": "8000", "machine_rate_per_hour": "5000",
     "overhead_rate_percent": "10", "currency": "JPY"},

    # ---- TW Plant (Plant 3000) - lower labor cost, similar machine ----
    {"work_center_code": "WC-MIX-TW", "description": "Reactor / Mixing Vessel #1 (TW)",
     "plant_code": "3000", "capacity_per_day": "20", "capacity_unit": "H",
     "labor_rate_per_hour": "2000", "machine_rate_per_hour": "16000",
     "overhead_rate_percent": "8", "currency": "JPY"},
    {"work_center_code": "WC-DIST-TW", "description": "Distillation Column (TW)",
     "plant_code": "3000", "capacity_per_day": "20", "capacity_unit": "H",
     "labor_rate_per_hour": "2000", "machine_rate_per_hour": "22000",
     "overhead_rate_percent": "8", "currency": "JPY"},
    {"work_center_code": "WC-FILT-TW", "description": "Precision Filtration (TW)",
     "plant_code": "3000", "capacity_per_day": "20", "capacity_unit": "H",
     "labor_rate_per_hour": "2000", "machine_rate_per_hour": "13000",
     "overhead_rate_percent": "8", "currency": "JPY"},
    {"work_center_code": "WC-PACK-TW", "description": "Cleanroom Filling Line (TW)",
     "plant_code": "3000", "capacity_per_day": "20", "capacity_unit": "H",
     "labor_rate_per_hour": "2500", "machine_rate_per_hour": "7500",
     "overhead_rate_percent": "10", "currency": "JPY"},
    {"work_center_code": "WC-QC-TW", "description": "QC Lab (TW)",
     "plant_code": "3000", "capacity_per_day": "12", "capacity_unit": "H",
     "labor_rate_per_hour": "3500", "machine_rate_per_hour": "5000",
     "overhead_rate_percent": "10", "currency": "JPY"},
]


# ==================================================================
# 3. Recipes & Routings - 3 product families
# ==================================================================
def _build_recipes_for_plant(plant_code: str, wc_suffix: str) -> list:
    """Generate recipe + routing definitions for a given plant."""
    return [
        # ----------------------------------------------------------
        # Recipe A: PAG Polymer Solution (intermediate, HALB)
        # ----------------------------------------------------------
        {
            "label": f"PAG Polymer Solution Recipe @ {plant_code}",
            "recipe": {
                "material_code": "MAT-8000001",
                "plant_code": plant_code,
                "description": "PAG polymer synthesis (intermediate)",
                "base_quantity": Decimal("100"),  # 100 KG output
                "base_unit": "KG",
                "yield_percent": Decimal("96"),
                "is_default": True,
                "items": [
                    {"component_material_code": "MAT-9000005",  # PAG Monomer
                     "quantity": Decimal("12"), "unit": "KG"},
                    {"component_material_code": "MAT-9000001",  # PGMEA Solvent
                     "quantity": Decimal("85"), "unit": "KG", "scrap_percent": Decimal("1")},
                ],
            },
            "routing": {
                "material_code": "MAT-8000001",
                "plant_code": plant_code,
                "description": "PAG polymer synthesis route",
                "base_quantity": Decimal("100"),
                "base_unit": "KG",
                "operations": [
                    {"description": "Polymerization", "work_center_code": f"WC-MIX-{wc_suffix}",
                     "setup_time_minutes": Decimal("60"),
                     "machine_time_minutes": Decimal("240"),
                     "labor_time_minutes": Decimal("120")},
                    {"description": "Filtration", "work_center_code": f"WC-FILT-{wc_suffix}",
                     "setup_time_minutes": Decimal("30"),
                     "machine_time_minutes": Decimal("60"),
                     "labor_time_minutes": Decimal("30")},
                ],
            },
        },
        # ----------------------------------------------------------
        # Recipe B: ArF Photoresist (final product, multi-level via PAG Polymer)
        # ----------------------------------------------------------
        {
            "label": f"ArF Photoresist Recipe @ {plant_code}",
            "recipe": {
                "material_code": "MAT-1000001",
                "plant_code": plant_code,
                "description": "ArF Immersion Photoresist NSP-AR450 production",
                "base_quantity": Decimal("100"),  # 100 L output
                "base_unit": "L",
                "yield_percent": Decimal("92"),
                "is_default": True,
                "items": [
                    {"component_material_code": "MAT-8000001",  # PAG Polymer (intermediate!)
                     "quantity": Decimal("30"), "unit": "KG"},
                    {"component_material_code": "MAT-9000004",  # PAG Resin
                     "quantity": Decimal("2"), "unit": "KG"},
                    {"component_material_code": "MAT-9000006",  # Quencher
                     "quantity": Decimal("0.5"), "unit": "KG"},
                    {"component_material_code": "MAT-9000001",  # PGMEA Solvent (additional)
                     "quantity": Decimal("65"), "unit": "KG"},
                ],
            },
            "routing": {
                "material_code": "MAT-1000001",
                "plant_code": plant_code,
                "description": "ArF photoresist final mixing & QC",
                "base_quantity": Decimal("100"),
                "base_unit": "L",
                "operations": [
                    {"description": "Final Mixing", "work_center_code": f"WC-MIX-{wc_suffix}",
                     "setup_time_minutes": Decimal("45"),
                     "machine_time_minutes": Decimal("180"),
                     "labor_time_minutes": Decimal("90")},
                    {"description": "Sub-micron Filtration",
                     "work_center_code": f"WC-FILT-{wc_suffix}",
                     "setup_time_minutes": Decimal("30"),
                     "machine_time_minutes": Decimal("120"),
                     "labor_time_minutes": Decimal("30")},
                    {"description": "QC Inspection", "work_center_code": f"WC-QC-{wc_suffix}",
                     "setup_time_minutes": Decimal("0"),
                     "machine_time_minutes": Decimal("60"),
                     "labor_time_minutes": Decimal("60")},
                    {"description": "Cleanroom Filling",
                     "work_center_code": f"WC-PACK-{wc_suffix}",
                     "setup_time_minutes": Decimal("30"),
                     "machine_time_minutes": Decimal("90"),
                     "labor_time_minutes": Decimal("90")},
                ],
            },
        },
        # ----------------------------------------------------------
        # Recipe C: CMP Slurry for Tungsten (with co-product: recovered water)
        # ----------------------------------------------------------
        {
            "label": f"CMP Slurry Recipe @ {plant_code}",
            "recipe": {
                "material_code": "MAT-2000001",
                "plant_code": plant_code,
                "description": "CMP Slurry for Tungsten production",
                "base_quantity": Decimal("1000"),  # 1000 L output
                "base_unit": "L",
                "yield_percent": Decimal("97"),
                "is_default": True,
                "items": [
                    {"component_material_code": "MAT-9000003",  # Colloidal Silica
                     "quantity": Decimal("600"), "unit": "KG"},
                    {"component_material_code": "MAT-9000002",  # H2O2
                     "quantity": Decimal("80"), "unit": "KG"},
                    {"component_material_code": "MAT-9000007",  # pH Modifier
                     "quantity": Decimal("5"), "unit": "KG"},
                    {"component_material_code": "MAT-9000008",  # Pure Water
                     "quantity": Decimal("320"), "unit": "KG"},
                ],
                "co_products": [
                    # Recovered process water - 5% by-product, no cost share
                    {"material_code": "MAT-9000008", "quantity": Decimal("50"),
                     "unit": "KG", "cost_share_percent": Decimal("0")},
                ],
            },
            "routing": {
                "material_code": "MAT-2000001",
                "plant_code": plant_code,
                "description": "CMP slurry mixing & filling",
                "base_quantity": Decimal("1000"),
                "base_unit": "L",
                "operations": [
                    {"description": "Blending", "work_center_code": f"WC-MIX-{wc_suffix}",
                     "setup_time_minutes": Decimal("30"),
                     "machine_time_minutes": Decimal("120"),
                     "labor_time_minutes": Decimal("60")},
                    {"description": "Filtration", "work_center_code": f"WC-FILT-{wc_suffix}",
                     "setup_time_minutes": Decimal("20"),
                     "machine_time_minutes": Decimal("90"),
                     "labor_time_minutes": Decimal("30")},
                    {"description": "Filling", "work_center_code": f"WC-PACK-{wc_suffix}",
                     "setup_time_minutes": Decimal("30"),
                     "machine_time_minutes": Decimal("60"),
                     "labor_time_minutes": Decimal("60")},
                ],
            },
        },
    ]


def _ensure_admin(db: Session):
    from app.core.auth_models import User
    return db.query(User).filter(User.email == ADMIN_EMAIL).first()


def _seed_additional_materials(db: Session, admin):
    print("\n[Additional raw materials for BOM]")
    svc = MaterialService(db)
    existing = {m.material_code for m in db.query(Material)
                .filter(Material.client_id == CLIENT_ID).all()}
    for spec in ADDITIONAL_MATERIALS:
        if spec["material_code"] in existing:
            print(f"  · skip {spec['material_code']}")
            continue
        clean = {**spec}
        if "standard_price" in clean:
            clean["standard_price"] = Decimal(str(clean["standard_price"]))
        # auto_classify=False to keep this script focused on PP
        payload = mdm_schemas.MaterialCreate(**clean, auto_classify=False)
        m = svc.create(payload, CLIENT_ID, admin.email)
        db.commit()
        print(f"  ✓ {m.material_code}  {m.description[:50]}")


def _seed_work_centers(db: Session, admin):
    print("\n[Work Centers]")
    svc = WorkCenterService(db)
    from app.modules.pp.models import WorkCenter
    existing = {w.work_center_code for w in db.query(WorkCenter)
                .filter(WorkCenter.client_id == CLIENT_ID).all()}
    for spec in WORK_CENTERS:
        if spec["work_center_code"] in existing:
            print(f"  · skip {spec['work_center_code']}")
            continue
        clean = {**spec}
        for k in ("labor_rate_per_hour", "machine_rate_per_hour",
                  "overhead_rate_percent", "capacity_per_day"):
            if k in clean and clean[k] is not None:
                clean[k] = Decimal(str(clean[k]))
        payload = pp_schemas.WorkCenterCreate(**clean)
        wc = svc.create(payload, CLIENT_ID, admin.email)
        db.commit()
        print(f"  ✓ {wc.work_center_code}  ({wc.plant_code})  "
              f"L={wc.labor_rate_per_hour}/h  M={wc.machine_rate_per_hour}/h  "
              f"OH={wc.overhead_rate_percent}%")


def _seed_recipes_and_routings(db: Session, admin, plant_code: str, wc_suffix: str):
    print(f"\n[Recipes / Routings / Production Versions @ Plant {plant_code}]")
    recipe_svc = RecipeService(db)
    routing_svc = RoutingService(db)
    pv_svc = ProductionVersionService(db)

    for spec in _build_recipes_for_plant(plant_code, wc_suffix):
        print(f"  · {spec['label']}")
        # Build Recipe payload
        recipe_dict = {k: v for k, v in spec["recipe"].items()
                       if k not in ("items", "co_products")}
        recipe_payload = pp_schemas.RecipeCreate(
            **recipe_dict,
            items=[pp_schemas.RecipeItemCreate(**i) for i in spec["recipe"]["items"]],
            co_products=[pp_schemas.RecipeCoProductCreate(**c)
                         for c in spec["recipe"].get("co_products", [])],
        )
        recipe = recipe_svc.create(recipe_payload, CLIENT_ID, admin.email)
        db.commit(); db.refresh(recipe)
        print(f"      ✓ Recipe  {recipe.recipe_code}  ({len(recipe.items)} items)")

        # Routing
        routing_dict = {k: v for k, v in spec["routing"].items() if k != "operations"}
        routing_payload = pp_schemas.RoutingCreate(
            **routing_dict,
            operations=[pp_schemas.RoutingOperationCreate(**o)
                        for o in spec["routing"]["operations"]],
        )
        routing = routing_svc.create(routing_payload, CLIENT_ID, admin.email)
        db.commit(); db.refresh(routing)
        print(f"      ✓ Routing {routing.routing_code}  ({len(routing.operations)} ops)")

        # Production Version (default)
        pv_payload = pp_schemas.ProductionVersionCreate(
            material_code=recipe.material_code,
            plant_code=plant_code,
            recipe_id=recipe.id,
            routing_id=routing.id,
            is_default=True,
        )
        pv = pv_svc.create(pv_payload, CLIENT_ID, admin.email)
        db.commit(); db.refresh(pv)
        print(f"      ✓ ProdVer {pv.version_code}")


def _run_cost_rollup(db: Session, admin):
    """Run cost rollup for the 3 final products at JP plant."""
    print("\n[Cost Rollup - JP Plant]")
    svc = CostRollupService(db)
    targets = [
        ("MAT-1000001", "1000", "ArF Photoresist (multi-level via PAG Polymer)"),
        ("MAT-2000001", "1000", "CMP Slurry for Tungsten"),
        ("MAT-8000001", "1000", "PAG Polymer Solution (intermediate)"),
    ]
    for mat, plant, desc in targets:
        rec = svc.rollup(
            pp_schemas.CostRollupRequest(material_code=mat, plant_code=plant),
            CLIENT_ID, admin.email,
        )
        db.commit()
        print(f"  ✓ {mat} @ {plant}  {desc}")
        print(f"      raw_material  = {rec.raw_material_cost:>12,.2f}")
        print(f"      labor         = {rec.labor_cost:>12,.2f}")
        print(f"      machine       = {rec.machine_cost:>12,.2f}")
        print(f"      overhead      = {rec.overhead_cost:>12,.2f}")
        print(f"      TOTAL/unit    = {rec.total_cost:>12,.2f} {rec.currency}/{rec.base_unit}")


def _show_plant_comparison(db: Session, admin):
    """Show JP vs TW cost comparison for ArF Photoresist."""
    print("\n[Cost Comparison - ArF Photoresist: JP (1000) vs TW (3000)]")
    svc = CostRollupService(db)
    rows = []
    for plant in ["1000", "3000"]:
        rec = svc.rollup(
            pp_schemas.CostRollupRequest(
                material_code="MAT-1000001",
                plant_code=plant,
                save_result=False,
            ),
            CLIENT_ID, admin.email,
        )
        rows.append((plant, rec))

    print(f"  {'Cost Component':<22}{'JP (1000)':>15}{'TW (3000)':>15}{'Δ%':>10}")
    print(f"  {'-'*22}{'-'*15}{'-'*15}{'-'*10}")
    components = [
        ("Raw Material", "raw_material_cost"),
        ("Labor",        "labor_cost"),
        ("Machine",      "machine_cost"),
        ("Overhead",     "overhead_cost"),
        ("TOTAL/L",      "total_cost"),
    ]
    for label, attr in components:
        jp = getattr(rows[0][1], attr)
        tw = getattr(rows[1][1], attr)
        diff = ((tw - jp) / jp * 100) if jp != 0 else Decimal("0")
        print(f"  {label:<22}{jp:>15,.2f}{tw:>15,.2f}{float(diff):>+9.1f}%")


def _show_compliance_snapshot(db: Session):
    """Demonstrate the vendor-neutral compliance snapshot API."""
    print("\n[Compliance Snapshot - generic data interface for AI_TradeManagement]")
    snapshot = ComplianceSnapshotService(db).build(
        CLIENT_ID, "MAT-1000001", "1000",
    )
    print(f"  Product: {snapshot.material_code}  HS={snapshot.product_hs_code}  "
          f"ECCN={snapshot.product_eccn}  Judgment={snapshot.product_fefta_judgment}")
    print(f"  {len(snapshot.components)} components in BOM:")
    for c in snapshot.components:
        indent = "    " * c.level
        print(f"  {indent}L{c.level}  {c.material_code:<15} "
              f"{c.quantity:>8} {c.unit:<3}  HS={c.hs_code or '-':<8} "
              f"ECCN={c.eccn or '-':<8} origin={c.country_of_origin or '-':<3} "
              f"判定={c.fefta_judgment or '-'}")


def main():
    print("=" * 78)
    print("  Mini Global ERP - Phase 2 PP Seed (BOM + Cost Rollup)")
    print("=" * 78)

    create_all_tables()
    db = SessionLocal()
    try:
        admin = _ensure_admin(db)
        if not admin:
            raise SystemExit("Run scripts/seed.py first to create admin user.")

        _seed_additional_materials(db, admin)
        _seed_work_centers(db, admin)
        _seed_recipes_and_routings(db, admin, "1000", "JP")
        _seed_recipes_and_routings(db, admin, "3000", "TW")
        _run_cost_rollup(db, admin)
        _show_plant_comparison(db, admin)
        _show_compliance_snapshot(db)

        print("\n" + "=" * 78)
        print("  ✓ PP seed complete.")
        print("=" * 78)
        print("  Try these endpoints:")
        print("    GET  /pp/recipes")
        print("    GET  /pp/bom-explosion?material_code=MAT-1000001&plant_code=1000")
        print("    POST /pp/cost/rollup       {material_code, plant_code}")
        print("    POST /pp/cost/compare      {material_code, plant_codes:[...]}")
        print("    GET  /pp/compliance/snapshot?material_code=MAT-1000001&plant_code=1000")
    finally:
        db.close()


if __name__ == "__main__":
    main()
