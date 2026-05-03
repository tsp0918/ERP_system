"""Materials Management - REST endpoints."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.mm import models, schemas, service
from app.shared.base_repository import BaseRepository
from app.shared.base_schemas import PaginatedResponse


# ==================================================================
# Purchase Requisitions
# ==================================================================
pr_router = APIRouter(prefix="/mm/purchase-requisitions",
                     tags=["MM - Purchase Requisitions"])


@pr_router.get("", response_model=PaginatedResponse[schemas.PurchaseRequisitionResponse])
def list_prs(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
             status_: str | None = Query(None, alias="status"),
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    repo = BaseRepository(models.PurchaseRequisition, db)
    filters = {"status": status_}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@pr_router.get("/{pr_id}", response_model=schemas.PurchaseRequisitionResponse)
def get_pr(pr_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    pr = BaseRepository(models.PurchaseRequisition, db).get(pr_id, user.client_id)
    if not pr:
        raise NotFoundError("PurchaseRequisition", pr_id)
    return pr


@pr_router.post("", response_model=schemas.PurchaseRequisitionResponse,
                status_code=status.HTTP_201_CREATED)
def create_pr(payload: schemas.PurchaseRequisitionCreate,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    pr = service.PurchaseRequisitionService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(pr)
    return pr


# ==================================================================
# Purchase Orders
# ==================================================================
po_router = APIRouter(prefix="/mm/purchase-orders", tags=["MM - Purchase Orders"])


@po_router.get("", response_model=PaginatedResponse[schemas.PurchaseOrderResponse])
def list_pos(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
             vendor_code: str | None = None,
             status_: str | None = Query(None, alias="status"),
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    repo = BaseRepository(models.PurchaseOrder, db)
    filters = {"vendor_code": vendor_code, "status": status_}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@po_router.get("/{po_id}", response_model=schemas.PurchaseOrderResponse)
def get_po(po_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    po = BaseRepository(models.PurchaseOrder, db).get(po_id, user.client_id)
    if not po:
        raise NotFoundError("PurchaseOrder", po_id)
    return po


@po_router.post("", response_model=schemas.PurchaseOrderResponse,
                status_code=status.HTTP_201_CREATED)
def create_po(payload: schemas.PurchaseOrderCreate,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    po = service.PurchaseOrderService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(po)
    return po


@po_router.post("/from-pr", response_model=list[schemas.PurchaseOrderResponse],
                status_code=status.HTTP_201_CREATED)
def create_po_from_pr(payload: schemas.PurchaseOrderFromPRRequest,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Generate one or more POs from a Purchase Requisition.

    PR items are grouped by suggested_vendor_code (or by the vendor_code
    in the request) and one PO per vendor is issued."""
    pos = service.PurchaseOrderService(db).create_from_pr(
        payload, user.client_id, user.email)
    db.commit()
    for po in pos:
        db.refresh(po)
    return pos


@po_router.post("/{po_id}/release", response_model=schemas.PurchaseOrderResponse)
def release_po(po_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    po = service.PurchaseOrderService(db).release(po_id, user.client_id, user.email)
    db.commit(); db.refresh(po)
    return po


# ==================================================================
# Goods Receipts
# ==================================================================
gr_router = APIRouter(prefix="/mm/goods-receipts", tags=["MM - Goods Receipts"])


@gr_router.get("", response_model=PaginatedResponse[schemas.GoodsReceiptResponse])
def list_grs(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    repo = BaseRepository(models.GoodsReceipt, db)
    items = repo.list(client_id=user.client_id, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@gr_router.get("/{gr_id}", response_model=schemas.GoodsReceiptResponse)
def get_gr(gr_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    gr = BaseRepository(models.GoodsReceipt, db).get(gr_id, user.client_id)
    if not gr:
        raise NotFoundError("GoodsReceipt", gr_id)
    return gr


@gr_router.post("", response_model=schemas.GoodsReceiptResponse,
                status_code=status.HTTP_201_CREATED)
def create_gr(payload: schemas.GoodsReceiptCreate,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    gr = service.GoodsReceiptService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(gr)
    return gr


# ==================================================================
# Invoice Receipts
# ==================================================================
ir_router = APIRouter(prefix="/mm/invoice-receipts", tags=["MM - Invoice Receipts"])


@ir_router.get("", response_model=PaginatedResponse[schemas.InvoiceReceiptResponse])
def list_irs(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
             match_status: str | None = None,
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    repo = BaseRepository(models.InvoiceReceipt, db)
    filters = {"match_status": match_status}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@ir_router.get("/{ir_id}", response_model=schemas.InvoiceReceiptResponse)
def get_ir(ir_id: int, db: Session = Depends(get_db),
           user: User = Depends(get_current_user)):
    ir = BaseRepository(models.InvoiceReceipt, db).get(ir_id, user.client_id)
    if not ir:
        raise NotFoundError("InvoiceReceipt", ir_id)
    return ir


@ir_router.post("", response_model=schemas.InvoiceReceiptResponse,
                status_code=status.HTTP_201_CREATED)
def create_ir(payload: schemas.InvoiceReceiptCreate,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    """Post a vendor invoice. Performs 3-way match against PO and GR."""
    ir = service.InvoiceReceiptService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(ir)
    return ir


# ==================================================================
# Aggregate
# ==================================================================
def get_mm_routers() -> list[APIRouter]:
    return [pr_router, po_router, gr_router, ir_router]
