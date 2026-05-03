"""Production Planning - Execution layer REST endpoints."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.pp import execution_models as exec_models
from app.modules.pp import execution_schemas as exec_schemas
from app.modules.pp import execution_service as exec_service
from app.shared.base_repository import BaseRepository
from app.shared.base_schemas import PaginatedResponse


# ==================================================================
# Process Orders
# ==================================================================
po_router = APIRouter(prefix="/pp/process-orders", tags=["PP - Process Orders"])


@po_router.get("", response_model=PaginatedResponse[exec_schemas.ProcessOrderResponse])
def list_process_orders(
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    material_code: str | None = None,
    plant_code: str | None = None,
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    repo = BaseRepository(exec_models.ProcessOrder, db)
    filters = {"material_code": material_code, "plant_code": plant_code,
               "status": status_}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@po_router.get("/{order_id}", response_model=exec_schemas.ProcessOrderResponse)
def get_process_order(order_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    order = BaseRepository(exec_models.ProcessOrder, db).get(order_id, user.client_id)
    if not order:
        raise NotFoundError("ProcessOrder", order_id)
    return order


@po_router.post("", response_model=exec_schemas.ProcessOrderResponse,
                status_code=status.HTTP_201_CREATED)
def create_process_order(payload: exec_schemas.ProcessOrderCreate,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    """Create a process order. Components and operations are auto-populated
    by exploding the referenced ProductionVersion (or the default one)."""
    order = exec_service.ProcessOrderService(db).create(
        payload, user.client_id, user.email)
    db.commit(); db.refresh(order)
    return order


@po_router.post("/{order_id}/release",
                response_model=exec_schemas.ProcessOrderResponse)
def release_process_order(order_id: int, db: Session = Depends(get_db),
                          user: User = Depends(get_current_user)):
    order = exec_service.ProcessOrderService(db).release(
        order_id, user.client_id, user.email)
    db.commit(); db.refresh(order)
    return order


# ==================================================================
# Goods Issue (consumption)
# ==================================================================
@po_router.post("/goods-issue", response_model=exec_schemas.GoodsIssueResponse)
def post_goods_issue(payload: exec_schemas.GoodsIssueRequest,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Consume raw material batches against a process order.

    For each line, a quantity is deducted from the chosen batch and
    the process order component's issued_quantity is incremented.
    Genealogy is recorded at goods receipt time (when the child batch exists).
    """
    result = exec_service.GoodsIssueService(db).post(
        payload, user.client_id, user.email)
    db.commit()
    return result


# ==================================================================
# Operation Confirmation
# ==================================================================
@po_router.post("/operation-confirm",
                response_model=exec_schemas.ProcessOrderOperationResponse)
def confirm_operation(payload: exec_schemas.OperationConfirmRequest,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    op = exec_service.OperationConfirmService(db).confirm(
        payload, user.client_id, user.email)
    db.commit(); db.refresh(op)
    return op


# ==================================================================
# Production Goods Receipt (output -> creates Batch + Genealogy)
# ==================================================================
@po_router.post("/goods-receipt",
                response_model=exec_schemas.ProductionGoodsReceiptResponse)
def post_production_goods_receipt(
    payload: exec_schemas.ProductionGoodsReceiptRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Receive finished goods from a process order.

    Creates a new produced Batch and writes BatchGenealogy rows for every
    consumed parent batch. Marks the process order COMPLETED.
    """
    result = exec_service.ProductionGoodsReceiptService(db).post(
        payload, user.client_id, user.email)
    db.commit()
    return result


# ==================================================================
# Batches
# ==================================================================
batch_router = APIRouter(prefix="/pp/batches", tags=["PP - Batches"])


@batch_router.get("", response_model=PaginatedResponse[exec_schemas.BatchResponse])
def list_batches(
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    material_code: str | None = None,
    plant_code: str | None = None,
    quality_status: str | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    repo = BaseRepository(exec_models.Batch, db)
    filters = {"material_code": material_code, "plant_code": plant_code,
               "quality_status": quality_status}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@batch_router.get("/{batch_code}", response_model=exec_schemas.BatchResponse)
def get_batch(batch_code: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    b = db.query(exec_models.Batch).filter(
        exec_models.Batch.client_id == user.client_id,
        exec_models.Batch.batch_code == batch_code,
    ).first()
    if not b:
        raise NotFoundError("Batch", batch_code)
    return b


@batch_router.post("", response_model=exec_schemas.BatchResponse,
                   status_code=status.HTTP_201_CREATED)
def create_batch(payload: exec_schemas.BatchCreate,
                 db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    """Create a batch directly. Used for opening balances or one-off receipts.
    Normally batches are created by Goods Receipts."""
    b = exec_service.BatchService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(b)
    return b


@batch_router.get("/{batch_code}/genealogy/backward",
                  response_model=exec_schemas.GenealogyResponse)
def trace_backward(batch_code: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Walk upstream: 'this batch was made from which raw lots?'"""
    return exec_service.GenealogyService(db).trace_backward(
        user.client_id, batch_code)


@batch_router.get("/{batch_code}/genealogy/forward",
                  response_model=exec_schemas.GenealogyResponse)
def trace_forward(batch_code: str, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    """Walk downstream: 'this raw lot ended up in which produced lots?'"""
    return exec_service.GenealogyService(db).trace_forward(
        user.client_id, batch_code)


# ==================================================================
# Aggregate
# ==================================================================
def get_pp_execution_routers() -> list[APIRouter]:
    return [po_router, batch_router]
