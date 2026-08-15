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
# Purchasing Info Records
# ==================================================================
pir_router = APIRouter(prefix="/mm/purchasing-info-records",
                       tags=["MM - Purchasing Info Records"])


@pir_router.get("", response_model=PaginatedResponse[schemas.PurchasingInfoRecordResponse])
def list_pirs(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
              material_code: str | None = None,
              vendor_code: str | None = None,
              db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    repo = BaseRepository(models.PurchasingInfoRecord, db)
    filters = {"material_code": material_code, "vendor_code": vendor_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@pir_router.get("/{pir_id}", response_model=schemas.PurchasingInfoRecordResponse)
def get_pir(pir_id: int, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    pir = BaseRepository(models.PurchasingInfoRecord, db).get(pir_id, user.client_id)
    if not pir:
        raise NotFoundError("PurchasingInfoRecord", pir_id)
    return pir


@pir_router.post("", response_model=schemas.PurchasingInfoRecordResponse,
                 status_code=status.HTTP_201_CREATED)
def create_pir(payload: schemas.PurchasingInfoRecordCreate,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    pir = service.PurchasingInfoRecordService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(pir)
    return pir


@pir_router.put("/{pir_id}", response_model=schemas.PurchasingInfoRecordResponse)
def update_pir(pir_id: int, payload: schemas.PurchasingInfoRecordUpdate,
               db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    repo = BaseRepository(models.PurchasingInfoRecord, db)
    instance = repo.get(pir_id, user.client_id)
    if not instance:
        raise NotFoundError("PurchasingInfoRecord", pir_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(instance, data)
    db.commit(); db.refresh(instance)
    return instance


# ==================================================================
# Source List
# ==================================================================
sl_router = APIRouter(prefix="/mm/source-lists", tags=["MM - Source Lists"])


@sl_router.get("", response_model=PaginatedResponse[schemas.SourceListResponse])
def list_source_lists(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                      material_code: str | None = None,
                      plant_code: str | None = None,
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    repo = BaseRepository(models.SourceList, db)
    filters = {"material_code": material_code, "plant_code": plant_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@sl_router.get("/{sl_id}", response_model=schemas.SourceListResponse)
def get_source_list(sl_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    sl = BaseRepository(models.SourceList, db).get(sl_id, user.client_id)
    if not sl:
        raise NotFoundError("SourceList", sl_id)
    return sl


@sl_router.post("", response_model=schemas.SourceListResponse,
                status_code=status.HTTP_201_CREATED)
def create_source_list(payload: schemas.SourceListCreate,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    sl = service.SourceListService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(sl)
    return sl


@sl_router.put("/{sl_id}", response_model=schemas.SourceListResponse)
def update_source_list(sl_id: int, payload: schemas.SourceListUpdate,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    repo = BaseRepository(models.SourceList, db)
    instance = repo.get(sl_id, user.client_id)
    if not instance:
        raise NotFoundError("SourceList", sl_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(instance, data)
    db.commit(); db.refresh(instance)
    return instance


# ==================================================================
# Stock Balances
# ==================================================================
stock_router = APIRouter(prefix="/mm/stock-balances", tags=["MM - Stock Balances"])


@stock_router.get("", response_model=PaginatedResponse[schemas.StockBalanceResponse])
def list_stock_balances(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                        material_code: str | None = None,
                        plant_code: str | None = None,
                        db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    repo = BaseRepository(models.StockBalance, db)
    filters = {"material_code": material_code, "plant_code": plant_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@stock_router.get("/{stock_id}", response_model=schemas.StockBalanceResponse)
def get_stock_balance(stock_id: int, db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    sb = BaseRepository(models.StockBalance, db).get(stock_id, user.client_id)
    if not sb:
        raise NotFoundError("StockBalance", stock_id)
    return sb


@stock_router.post("", response_model=schemas.StockBalanceResponse,
                   status_code=status.HTTP_201_CREATED)
def create_stock_balance(payload: schemas.StockBalanceCreate,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    sb = service.StockBalanceService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(sb)
    return sb


@stock_router.put("/{stock_id}", response_model=schemas.StockBalanceResponse)
def update_stock_balance(stock_id: int, payload: schemas.StockBalanceUpdate,
                         db: Session = Depends(get_db),
                         user: User = Depends(get_current_user)):
    repo = BaseRepository(models.StockBalance, db)
    instance = repo.get(stock_id, user.client_id)
    if not instance:
        raise NotFoundError("StockBalance", stock_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(instance, data)
    db.commit(); db.refresh(instance)
    return instance


# ==================================================================
# Reservations
# ==================================================================
res_router = APIRouter(prefix="/mm/reservations", tags=["MM - Reservations"])


@res_router.get("", response_model=PaginatedResponse[schemas.ReservationResponse])
def list_reservations(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                      material_code: str | None = None,
                      plant_code: str | None = None,
                      status_: str | None = Query(None, alias="status"),
                      db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    repo = BaseRepository(models.Reservation, db)
    filters = {"material_code": material_code, "plant_code": plant_code, "status": status_}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@res_router.get("/{res_id}", response_model=schemas.ReservationResponse)
def get_reservation(res_id: int, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    r = BaseRepository(models.Reservation, db).get(res_id, user.client_id)
    if not r:
        raise NotFoundError("Reservation", res_id)
    return r


@res_router.post("", response_model=schemas.ReservationResponse,
                 status_code=status.HTTP_201_CREATED)
def create_reservation(payload: schemas.ReservationCreate,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    r = service.ReservationService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(r)
    return r


@res_router.post("/{res_id}/cancel", response_model=schemas.ReservationResponse)
def cancel_reservation(res_id: int, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    r = service.ReservationService(db).cancel(res_id, user.client_id, user.email)
    db.commit(); db.refresh(r)
    return r


# ==================================================================
# Material Availability (MRP-style cross-module view)
# ==================================================================
from typing import Optional as _Opt
from app.modules.mm.availability_service import (
    get_material_availability, count_materials, MaterialAvailabilityItem,
)
from app.shared.base_schemas import PaginatedResponse as _PR

avail_router = APIRouter(prefix="/mm/material-availability",
                         tags=["MM - Material Availability"])


@avail_router.get("", response_model=_PR[MaterialAvailabilityItem],
                  summary="MRP-style per-material stock / supply / demand / cost view")
def material_availability(
    material_type: _Opt[str] = Query(None, examples=["FERT", "ROH", "HALB"]),
    material_code: _Opt[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items = get_material_availability(
        db, user.client_id, material_type, material_code, skip, limit)
    total = count_materials(db, user.client_id, material_type, material_code)
    return _PR(items=items, total=total, skip=skip, limit=limit)


# ==================================================================
# Aggregate
# ==================================================================
def get_mm_routers() -> list[APIRouter]:
    return [pr_router, po_router, gr_router, ir_router,
            pir_router, sl_router, stock_router, res_router, avail_router]
