"""Tests for PP Execution: ProcessOrder, Batch, Genealogy."""
import pytest
from decimal import Decimal

from app.modules.pp import execution_schemas as exec_schemas
from app.modules.pp.execution_service import (
    BatchService, GenealogyService, GoodsIssueService,
    ProcessOrderService, ProductionGoodsReceiptService,
)
from tests.test_pp import pp_setup  # reuse the fixture


# ==================================================================
# ProcessOrder lifecycle
# ==================================================================
def test_create_process_order_explodes_recipe(
    db_session, admin_user, pp_setup,
):
    order = ProcessOrderService(db_session).create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-FIN", plant_code="P1",
            target_quantity=Decimal("20"), target_unit="L",
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    db_session.refresh(order)

    # Quantities scaled: target=20L vs base=10L -> factor 2
    # Recipe wants 5KG of A and 3KG of B per 10L
    # Therefore order should plan 10KG A and 6KG B
    assert len(order.components) == 2
    by_mat = {c.material_code: c for c in order.components}
    assert by_mat["MAT-RAW-A"].planned_quantity == Decimal("10.0000")
    assert by_mat["MAT-RAW-B"].planned_quantity == Decimal("6.0000")
    # Operations also scaled
    assert len(order.operations) == 1


def test_release_process_order(db_session, admin_user, pp_setup):
    svc = ProcessOrderService(db_session)
    order = svc.create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-FIN", plant_code="P1",
            target_quantity=Decimal("10"),
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    svc.release(order.id, admin_user.client_id, admin_user.email)
    db_session.commit()
    db_session.refresh(order)
    assert order.status == "RELEASED"
    assert order.actual_start is not None


# ==================================================================
# Batch creation & GoodsIssue
# ==================================================================
@pytest.fixture
def setup_with_batches(db_session, admin_user, pp_setup):
    """pp_setup + opening batches for raw materials."""
    bs = BatchService(db_session)
    batch_a = bs.create(exec_schemas.BatchCreate(
        batch_code="LOT-A-001", material_code="MAT-RAW-A",
        plant_code="P1", quantity=Decimal("100"), unit="KG",
        country_of_origin="JP", quality_status="RELEASED",
    ), admin_user.client_id, admin_user.email)
    batch_b = bs.create(exec_schemas.BatchCreate(
        batch_code="LOT-B-001", material_code="MAT-RAW-B",
        plant_code="P1", quantity=Decimal("100"), unit="KG",
        country_of_origin="CN", quality_status="RELEASED",
    ), admin_user.client_id, admin_user.email)
    db_session.commit()
    return {**pp_setup, "batch_a": batch_a, "batch_b": batch_b}


def test_goods_issue_decrements_batch(db_session, admin_user, setup_with_batches):
    svc = ProcessOrderService(db_session)
    order = svc.create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-FIN", plant_code="P1",
            target_quantity=Decimal("10"),
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    svc.release(order.id, admin_user.client_id, admin_user.email)
    db_session.commit()
    db_session.refresh(order)

    a_comp = next(c for c in order.components if c.material_code == "MAT-RAW-A")
    GoodsIssueService(db_session).post(
        exec_schemas.GoodsIssueRequest(
            process_order_id=order.id,
            lines=[exec_schemas.GoodsIssueLine(
                component_id=a_comp.id,
                batch_code="LOT-A-001",
                quantity=Decimal("5"),
            )],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    db_session.refresh(setup_with_batches["batch_a"])
    assert setup_with_batches["batch_a"].quantity == Decimal("95.0000")


def test_goods_issue_rejects_unreleased_batch(
    db_session, admin_user, setup_with_batches,
):
    """In-test batches default RELEASED, but a BLOCKED batch must be rejected."""
    setup_with_batches["batch_a"].quality_status = "BLOCKED"
    db_session.commit()

    svc = ProcessOrderService(db_session)
    order = svc.create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-FIN", plant_code="P1",
            target_quantity=Decimal("10"),
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    svc.release(order.id, admin_user.client_id, admin_user.email)
    db_session.commit()
    db_session.refresh(order)

    a_comp = next(c for c in order.components if c.material_code == "MAT-RAW-A")
    with pytest.raises(Exception):
        GoodsIssueService(db_session).post(
            exec_schemas.GoodsIssueRequest(
                process_order_id=order.id,
                lines=[exec_schemas.GoodsIssueLine(
                    component_id=a_comp.id,
                    batch_code="LOT-A-001",
                    quantity=Decimal("5"),
                )],
            ),
            admin_user.client_id, admin_user.email,
        )


# ==================================================================
# Full production cycle + Genealogy
# ==================================================================
def test_production_creates_child_batch_with_genealogy(
    db_session, admin_user, setup_with_batches,
):
    svc = ProcessOrderService(db_session)
    order = svc.create(
        exec_schemas.ProcessOrderCreate(
            material_code="MAT-FIN", plant_code="P1",
            target_quantity=Decimal("10"),
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    svc.release(order.id, admin_user.client_id, admin_user.email)
    db_session.commit()
    db_session.refresh(order)

    # Issue both components
    a_comp = next(c for c in order.components if c.material_code == "MAT-RAW-A")
    b_comp = next(c for c in order.components if c.material_code == "MAT-RAW-B")
    GoodsIssueService(db_session).post(
        exec_schemas.GoodsIssueRequest(
            process_order_id=order.id,
            lines=[
                exec_schemas.GoodsIssueLine(
                    component_id=a_comp.id, batch_code="LOT-A-001",
                    quantity=a_comp.planned_quantity,
                ),
                exec_schemas.GoodsIssueLine(
                    component_id=b_comp.id, batch_code="LOT-B-001",
                    quantity=b_comp.planned_quantity,
                ),
            ],
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    # Goods receipt
    result = ProductionGoodsReceiptService(db_session).post(
        exec_schemas.ProductionGoodsReceiptRequest(
            process_order_id=order.id,
            quantity=Decimal("10"),
            batch_code="LOT-FIN-001",
        ),
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    assert result.new_batch_code == "LOT-FIN-001"
    assert set(result.parent_batches) == {"LOT-A-001", "LOT-B-001"}

    # Walk genealogy backward
    backward = GenealogyService(db_session).trace_backward(
        admin_user.client_id, "LOT-FIN-001",
    )
    assert backward.tree.batch_code == "LOT-FIN-001"
    parent_codes = {c.batch_code for c in backward.tree.children}
    assert parent_codes == {"LOT-A-001", "LOT-B-001"}

    # Walk genealogy forward from raw material
    forward = GenealogyService(db_session).trace_forward(
        admin_user.client_id, "LOT-A-001",
    )
    child_codes = {c.batch_code for c in forward.tree.children}
    assert "LOT-FIN-001" in child_codes
