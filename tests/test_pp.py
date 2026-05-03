"""Tests for PP module: BOM, Cost Rollup, Compliance Snapshot."""
import pytest
from decimal import Decimal

from app.modules.mdm import schemas as mdm_schemas, service as mdm_service
from app.modules.pp import schemas as pp_schemas
from app.modules.pp.service import (
    BomExplosionService, ComplianceSnapshotService,
    CostRollupService, ProductionVersionService,
    RecipeService, RoutingService, WorkCenterService,
)


# ==================================================================
# Fixture: minimal PP setup (1 product, 2 raw materials, 1 recipe + routing)
# ==================================================================
@pytest.fixture
def pp_setup(db_session, admin_user):
    cid = admin_user.client_id
    email = admin_user.email
    mdm_svc = mdm_service.MaterialService(db_session)

    # 3 materials
    finished = mdm_svc.create(mdm_schemas.MaterialCreate(
        material_code="MAT-FIN", description="Finished Good",
        material_type="FERT", base_unit="L",
        standard_price=Decimal("0"), country_of_origin="JP",
        auto_classify=False,
    ), cid, email)
    raw_a = mdm_svc.create(mdm_schemas.MaterialCreate(
        material_code="MAT-RAW-A", description="Raw A",
        material_type="ROH", base_unit="KG",
        standard_price=Decimal("100"), country_of_origin="JP",
        auto_classify=False,
    ), cid, email)
    raw_b = mdm_svc.create(mdm_schemas.MaterialCreate(
        material_code="MAT-RAW-B", description="Raw B",
        material_type="ROH", base_unit="KG",
        standard_price=Decimal("200"), country_of_origin="CN",
        auto_classify=False,
    ), cid, email)
    db_session.commit()

    # WorkCenter
    wc = WorkCenterService(db_session).create(pp_schemas.WorkCenterCreate(
        work_center_code="WC-T1", description="Test WC",
        plant_code="P1", labor_rate_per_hour=Decimal("3000"),
        machine_rate_per_hour=Decimal("9000"),
        overhead_rate_percent=Decimal("10"),
    ), cid, email)
    db_session.commit()

    # Recipe (10L of FIN from 5KG of A and 3KG of B)
    recipe = RecipeService(db_session).create(pp_schemas.RecipeCreate(
        material_code="MAT-FIN", plant_code="P1",
        base_quantity=Decimal("10"), base_unit="L",
        yield_percent=Decimal("100"),
        is_default=True,
        items=[
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-RAW-A",
                quantity=Decimal("5"), unit="KG",
            ),
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-RAW-B",
                quantity=Decimal("3"), unit="KG",
            ),
        ],
    ), cid, email)
    db_session.commit()

    # Routing (single op, 60 min machine, 30 min labor)
    routing = RoutingService(db_session).create(pp_schemas.RoutingCreate(
        material_code="MAT-FIN", plant_code="P1",
        base_quantity=Decimal("10"), base_unit="L",
        operations=[pp_schemas.RoutingOperationCreate(
            description="Mix",
            work_center_code="WC-T1",
            setup_time_minutes=Decimal("0"),
            machine_time_minutes=Decimal("60"),
            labor_time_minutes=Decimal("30"),
        )],
    ), cid, email)
    db_session.commit()

    # Production Version
    pv = ProductionVersionService(db_session).create(
        pp_schemas.ProductionVersionCreate(
            material_code="MAT-FIN", plant_code="P1",
            recipe_id=recipe.id, routing_id=routing.id,
            is_default=True,
        ), cid, email)
    db_session.commit()

    return {"finished": finished, "raw_a": raw_a, "raw_b": raw_b,
            "recipe": recipe, "routing": routing, "pv": pv}


# ==================================================================
# BOM Explosion
# ==================================================================
def test_bom_explosion_simple(db_session, admin_user, pp_setup):
    tree = BomExplosionService(db_session).explode(
        admin_user.client_id, "MAT-FIN", "P1",
    )
    assert tree.material_code == "MAT-FIN"
    assert tree.is_purchased is False
    assert len(tree.children) == 2
    codes = {c.material_code for c in tree.children}
    assert codes == {"MAT-RAW-A", "MAT-RAW-B"}
    # Both raw materials should be leaves (purchased)
    assert all(c.is_purchased for c in tree.children)


def test_bom_explosion_for_purchased_material_returns_leaf(
    db_session, admin_user, pp_setup,
):
    tree = BomExplosionService(db_session).explode(
        admin_user.client_id, "MAT-RAW-A", "P1",
    )
    assert tree.is_purchased is True
    assert tree.children == []


# ==================================================================
# Cost Rollup
# ==================================================================
def test_cost_rollup_basic(db_session, admin_user, pp_setup):
    rec = CostRollupService(db_session).rollup(
        pp_schemas.CostRollupRequest(
            material_code="MAT-FIN", plant_code="P1",
            save_result=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    # Per-1L cost of MAT-FIN:
    # Materials: (5*100 + 3*200) per 10L = 1100 / 10 = 110/L
    # Labor:   (30/60) * 3000 / 10 = 150/L
    # Machine: (60/60) * 9000 / 10 = 900/L
    # Overhead: 10% of (labor+machine) = 105/L
    assert rec.raw_material_cost == Decimal("110.0000")
    assert rec.labor_cost == Decimal("150.0000")
    assert rec.machine_cost == Decimal("900.0000")
    assert rec.overhead_cost == Decimal("105.0000")
    assert rec.total_cost == Decimal("1265.0000")


def test_cost_rollup_purchased_material(db_session, admin_user, pp_setup):
    rec = CostRollupService(db_session).rollup(
        pp_schemas.CostRollupRequest(
            material_code="MAT-RAW-A", plant_code="P1",
            save_result=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    # Pure standard price: 100 / unit, no labor/machine
    assert rec.raw_material_cost == Decimal("100.0000")
    assert rec.labor_cost == Decimal("0")
    assert rec.machine_cost == Decimal("0")


# ==================================================================
# Compliance Snapshot
# ==================================================================
def test_compliance_snapshot_includes_all_components(
    db_session, admin_user, pp_setup,
):
    snap = ComplianceSnapshotService(db_session).build(
        admin_user.client_id, "MAT-FIN", "P1",
    )
    assert snap.material_code == "MAT-FIN"
    assert len(snap.components) == 2
    countries = {c.country_of_origin for c in snap.components}
    assert countries == {"JP", "CN"}


def test_compliance_snapshot_no_judgment_logic_in_erp(
    db_session, admin_user, pp_setup,
):
    """ERP must not pre-compute any compliance judgment.
    The snapshot just exposes raw data."""
    snap = ComplianceSnapshotService(db_session).build(
        admin_user.client_id, "MAT-FIN", "P1",
    )
    # Top-level product has no eccn/hs_code set
    assert snap.product_eccn is None
    assert snap.product_hs_code is None
    # Components also have no judgment fields populated by ERP
    for c in snap.components:
        # judgment defaults to UNKNOWN unless AI_TM is called
        assert c.fefta_judgment == "UNKNOWN"


# ==================================================================
# Yield handling
# ==================================================================
def test_cost_rollup_with_yield(db_session, admin_user, pp_setup):
    """50% yield should double the per-unit cost vs 100% yield."""
    pp_setup["recipe"].yield_percent = Decimal("50")
    db_session.commit()

    rec = CostRollupService(db_session).rollup(
        pp_schemas.CostRollupRequest(
            material_code="MAT-FIN", plant_code="P1",
            save_result=False,
        ),
        admin_user.client_id, admin_user.email,
    )
    # Per-unit cost should be doubled compared to the 100% yield case
    assert rec.raw_material_cost == Decimal("220.0000")
    assert rec.labor_cost == Decimal("300.0000")
    assert rec.machine_cost == Decimal("1800.0000")
