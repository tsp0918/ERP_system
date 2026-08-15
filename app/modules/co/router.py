"""CO (Controlling) — REST endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.modules.co import schemas, service
from app.shared.base_schemas import PaginatedResponse


# ══════════════════════════════════════════════════════════════════════
# Asset Master
# ══════════════════════════════════════════════════════════════════════

asset_router = APIRouter(prefix="/co/assets", tags=["CO - Assets"])


@asset_router.get("", response_model=PaginatedResponse[schemas.AssetMasterResponse])
def list_assets(
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.AssetService(db)
    items = svc.list_assets(user.client_id, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@asset_router.post("", response_model=schemas.AssetMasterResponse,
                   status_code=status.HTTP_201_CREATED)
def create_asset(
    body: schemas.AssetMasterCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.AssetService(db)
    asset = svc.create_asset(user.client_id, body, user.email)
    db.commit()
    db.refresh(asset)
    return asset


@asset_router.get("/{asset_code}", response_model=schemas.AssetMasterResponse)
def get_asset(
    asset_code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.AssetService(db).get_asset(user.client_id, asset_code)


@asset_router.patch("/{asset_code}", response_model=schemas.AssetMasterResponse)
def update_asset(
    asset_code: str, body: schemas.AssetMasterUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.AssetService(db)
    asset = svc.update_asset(user.client_id, asset_code, body, user.email)
    db.commit()
    db.refresh(asset)
    return asset


# ══════════════════════════════════════════════════════════════════════
# Asset Cost Rates
# ══════════════════════════════════════════════════════════════════════

rate_router = APIRouter(prefix="/co/asset-rates", tags=["CO - Asset Cost Rates"])


@rate_router.get("/{asset_code}",
                 response_model=PaginatedResponse[schemas.AssetCostRateResponse])
def list_asset_rates(
    asset_code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.AssetService(db)
    items = svc.list_rates(user.client_id, asset_code)
    return PaginatedResponse(items=items, total=len(items), skip=0, limit=len(items) or 1)


@rate_router.put("", response_model=schemas.AssetCostRateResponse,
                 summary="Create or update an asset cost rate (upsert)")
def upsert_asset_rate(
    body: schemas.AssetCostRateCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.AssetService(db)
    rate = svc.upsert_rate(user.client_id, body, user.email)
    db.commit()
    db.refresh(rate)
    return rate


@rate_router.post("/{asset_code}/{fiscal_year}/calculate",
                  response_model=schemas.MachineRateResult,
                  summary="Recalculate and store machine_rate")
def calculate_machine_rate(
    asset_code: str, fiscal_year: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.AssetService(db)
    result = svc.calculate_machine_rate(user.client_id, asset_code, fiscal_year)
    db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════
# Cost Centers
# ══════════════════════════════════════════════════════════════════════

cc_router = APIRouter(prefix="/co/cost-centers", tags=["CO - Cost Centers"])


@cc_router.get("", response_model=PaginatedResponse[schemas.CostCenterResponse])
def list_cost_centers(
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    items = svc.list_cc(user.client_id, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@cc_router.post("", response_model=schemas.CostCenterResponse,
                status_code=status.HTTP_201_CREATED)
def create_cost_center(
    body: schemas.CostCenterCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    cc = svc.create_cc(user.client_id, body, user.email)
    db.commit()
    db.refresh(cc)
    return cc


@cc_router.get("/{code}", response_model=schemas.CostCenterResponse)
def get_cost_center(
    code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.CostCenterService(db).get_cc(user.client_id, code)


@cc_router.patch("/{code}", response_model=schemas.CostCenterResponse)
def update_cost_center(
    code: str, body: schemas.CostCenterUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    cc = svc.update_cc(user.client_id, code, body, user.email)
    db.commit()
    db.refresh(cc)
    return cc


# Employee allocations sub-resource
@cc_router.get("/{code}/employees",
               response_model=PaginatedResponse[schemas.CostCenterEmployeeResponse])
def list_cc_employees(
    code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    items = svc.list_employees(user.client_id, code)
    return PaginatedResponse(items=items, total=len(items), skip=0, limit=len(items) or 1)


@cc_router.post("/{code}/employees",
                response_model=schemas.CostCenterEmployeeResponse,
                status_code=status.HTTP_201_CREATED)
def add_cc_employee(
    code: str, body: schemas.CostCenterEmployeeCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    emp = svc.add_employee(user.client_id, body, user.email)
    db.commit()
    db.refresh(emp)
    return emp


# ══════════════════════════════════════════════════════════════════════
# Cost Center Budgets
# ══════════════════════════════════════════════════════════════════════

budget_router = APIRouter(prefix="/co/budgets", tags=["CO - Cost Center Budgets"])


@budget_router.get("/{cost_center_code}",
                   response_model=PaginatedResponse[schemas.CostCenterBudgetResponse])
def list_budgets(
    cost_center_code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    items = svc.list_budgets(user.client_id, cost_center_code)
    return PaginatedResponse(items=items, total=len(items), skip=0, limit=len(items) or 1)


@budget_router.put("", response_model=schemas.CostCenterBudgetResponse,
                   summary="Create or update a cost center budget (upsert)")
def upsert_budget(
    body: schemas.CostCenterBudgetCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostCenterService(db)
    budget = svc.upsert_budget(user.client_id, body, user.email)
    db.commit()
    db.refresh(budget)
    return budget


@budget_router.post("/{cost_center_code}/{fiscal_year}/calculate",
                    response_model=schemas.LaborRateResult,
                    summary="Recalculate and store labor_rate / overhead_rate")
def calculate_labor_rate(
    cost_center_code: str, fiscal_year: int,
    direct_cost_base: Optional[float] = Query(
        None, description="Direct cost base for overhead% calculation (defaults to labor_budget)"),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    from decimal import Decimal as D
    svc = service.CostCenterService(db)
    base = D(str(direct_cost_base)) if direct_cost_base else None
    result = svc.calculate_labor_rate(user.client_id, cost_center_code, fiscal_year, base)
    db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════
# Work Center Rate Sync (CO → PP)
# ══════════════════════════════════════════════════════════════════════

sync_router = APIRouter(prefix="/co/sync", tags=["CO - Rate Sync"])


@sync_router.post("/work-center-rates/{fiscal_year}",
                  response_model=schemas.WorkCenterRateUpdateResult,
                  summary="Push CO rates → PP work_centers for given fiscal year")
def sync_work_center_rates(
    fiscal_year: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.WorkCenterRateService(db)
    result = svc.sync_rates(user.client_id, fiscal_year, user.email)
    db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════
# Actual Cost Postings
# ══════════════════════════════════════════════════════════════════════

posting_router = APIRouter(prefix="/co/actual-costs", tags=["CO - Actual Costs"])


@posting_router.get("", response_model=PaginatedResponse[schemas.ActualCostPostingResponse])
def list_postings(
    process_order_id: Optional[int] = None,
    fiscal_year: Optional[int] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.ActualCostService(db)
    items = svc.list_postings(user.client_id, process_order_id, fiscal_year, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@posting_router.post("", response_model=schemas.ActualCostPostingResponse,
                     status_code=status.HTTP_201_CREATED)
def post_actual_cost(
    body: schemas.ActualCostPostingCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.ActualCostService(db)
    posting = svc.post(user.client_id, body, user.email)
    db.commit()
    db.refresh(posting)
    return posting


# ══════════════════════════════════════════════════════════════════════
# Cost Estimate Items / De Minimis
# ══════════════════════════════════════════════════════════════════════

estimate_router = APIRouter(prefix="/co/cost-estimates", tags=["CO - Cost Estimates"])


@estimate_router.get("", response_model=PaginatedResponse[schemas.CostEstimateItemResponse])
def list_items(
    material_code: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostEstimateService(db)
    items = svc.list_items(user.client_id, material_code, fiscal_year, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@estimate_router.post("", response_model=schemas.CostEstimateItemResponse,
                      status_code=status.HTTP_201_CREATED)
def create_item(
    body: schemas.CostEstimateItemCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostEstimateService(db)
    item = svc.create_item(user.client_id, body, user.email)
    db.commit()
    db.refresh(item)
    return item


@estimate_router.patch("/{item_id}", response_model=schemas.CostEstimateItemResponse)
def update_item(
    item_id: int, body: schemas.CostEstimateItemUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.CostEstimateService(db)
    item = svc.update_item(user.client_id, item_id, body, user.email)
    db.commit()
    db.refresh(item)
    return item


@estimate_router.get("/{material_code}/{fiscal_year}/de-minimis",
                     response_model=schemas.DeMinimisResult,
                     summary="Calculate US EAR De Minimis ratio for a material")
def de_minimis(
    material_code: str, fiscal_year: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.CostEstimateService(db).de_minimis(
        user.client_id, material_code, fiscal_year
    )


# ══════════════════════════════════════════════════════════════════════
# Router registry
# ══════════════════════════════════════════════════════════════════════

def get_co_routers():
    return [
        asset_router,
        rate_router,
        cc_router,
        budget_router,
        sync_router,
        posting_router,
        estimate_router,
    ]
