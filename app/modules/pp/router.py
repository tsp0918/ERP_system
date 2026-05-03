"""Production Planning - REST endpoints."""
import json
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError, BusinessRuleError
from app.modules.pp import models, schemas, service
from app.shared.base_repository import BaseRepository
from app.shared.base_router import create_crud_router
from app.shared.base_schemas import PaginatedResponse


# ==================================================================
# Work Centers - generic CRUD
# ==================================================================
work_centers_router = create_crud_router(
    prefix="/pp/work-centers",
    tags=["PP - Work Centers"],
    model=models.WorkCenter,
    create_schema=schemas.WorkCenterCreate,
    update_schema=schemas.WorkCenterUpdate,
    response_schema=schemas.WorkCenterResponse,
    resource_name="WorkCenter",
)


# ==================================================================
# Recipes
# ==================================================================
recipes_router = APIRouter(prefix="/pp/recipes", tags=["PP - Recipes (BOM)"])


@recipes_router.get("", response_model=PaginatedResponse[schemas.RecipeResponse])
def list_recipes(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    material_code: str | None = None,
    plant_code: str | None = None,
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.Recipe, db)
    filters = {"material_code": material_code, "plant_code": plant_code, "status": status_}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@recipes_router.get("/{recipe_id}", response_model=schemas.RecipeResponse)
def get_recipe(recipe_id: int, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    r = BaseRepository(models.Recipe, db).get(recipe_id, client_id=user.client_id)
    if not r:
        raise NotFoundError("Recipe", recipe_id)
    return r


@recipes_router.post("", response_model=schemas.RecipeResponse,
                     status_code=status.HTTP_201_CREATED)
def create_recipe(payload: schemas.RecipeCreate, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    recipe = service.RecipeService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(recipe)
    return recipe


@recipes_router.post("/{recipe_id}/release", response_model=schemas.RecipeResponse)
def release_recipe(recipe_id: int, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    r = service.RecipeService(db).release(recipe_id, user.client_id, user.email)
    db.commit(); db.refresh(r)
    return r


@recipes_router.get("/{recipe_id}/explosion", response_model=schemas.BomExplosionResponse)
def explode_recipe(recipe_id: int, quantity: Decimal | None = None,
                   db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    r = BaseRepository(models.Recipe, db).get(recipe_id, client_id=user.client_id)
    if not r:
        raise NotFoundError("Recipe", recipe_id)
    tree = service.BomExplosionService(db).explode(
        client_id=user.client_id,
        material_code=r.material_code,
        plant_code=r.plant_code,
        quantity=quantity,
    )
    return schemas.BomExplosionResponse(
        material_code=r.material_code,
        plant_code=r.plant_code,
        base_quantity=quantity if quantity is not None else r.base_quantity,
        base_unit=r.base_unit,
        tree=tree,
    )


# ==================================================================
# BOM Explosion (by material/plant directly, not by recipe id)
# ==================================================================
explosion_router = APIRouter(prefix="/pp/bom-explosion", tags=["PP - BOM Explosion"])


@explosion_router.get("", response_model=schemas.BomExplosionResponse)
def explode(material_code: str, plant_code: str,
            quantity: Decimal | None = None,
            db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    """Explode a multi-level BOM for the given material+plant.

    Quantity defaults to the recipe's base_quantity.
    Returns a tree where leaves are purchased components.
    """
    tree = service.BomExplosionService(db).explode(
        client_id=user.client_id,
        material_code=material_code,
        plant_code=plant_code,
        quantity=quantity,
    )
    base_qty = quantity if quantity is not None else tree.quantity
    return schemas.BomExplosionResponse(
        material_code=material_code,
        plant_code=plant_code,
        base_quantity=base_qty,
        base_unit=tree.unit,
        tree=tree,
    )


# ==================================================================
# Routings
# ==================================================================
routings_router = APIRouter(prefix="/pp/routings", tags=["PP - Routings"])


@routings_router.get("", response_model=PaginatedResponse[schemas.RoutingResponse])
def list_routings(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
                  material_code: str | None = None, plant_code: str | None = None,
                  db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    repo = BaseRepository(models.Routing, db)
    filters = {"material_code": material_code, "plant_code": plant_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@routings_router.get("/{routing_id}", response_model=schemas.RoutingResponse)
def get_routing(routing_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    r = BaseRepository(models.Routing, db).get(routing_id, client_id=user.client_id)
    if not r:
        raise NotFoundError("Routing", routing_id)
    return r


@routings_router.post("", response_model=schemas.RoutingResponse,
                      status_code=status.HTTP_201_CREATED)
def create_routing(payload: schemas.RoutingCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    r = service.RoutingService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(r)
    return r


# ==================================================================
# Production Versions
# ==================================================================
pv_router = APIRouter(prefix="/pp/production-versions",
                      tags=["PP - Production Versions"])


@pv_router.get("", response_model=PaginatedResponse[schemas.ProductionVersionResponse])
def list_pvs(skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
             material_code: str | None = None, plant_code: str | None = None,
             db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    repo = BaseRepository(models.ProductionVersion, db)
    filters = {"material_code": material_code, "plant_code": plant_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@pv_router.post("", response_model=schemas.ProductionVersionResponse,
                status_code=status.HTTP_201_CREATED)
def create_pv(payload: schemas.ProductionVersionCreate, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    pv = service.ProductionVersionService(db).create(payload, user.client_id, user.email)
    db.commit(); db.refresh(pv)
    return pv


# ==================================================================
# Cost Rollup
# ==================================================================
cost_router = APIRouter(prefix="/pp/cost", tags=["PP - Costing"])


@cost_router.post("/rollup", response_model=schemas.CostComponentSplitResponse)
def cost_rollup(payload: schemas.CostRollupRequest, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Run a multi-level standard cost estimate (cost rollup).

    Walks the BOM bottom-up, accumulating raw material / labor / machine /
    overhead costs per cost component. Result is saved as a CostComponentSplit
    record (unless save_result=false).
    """
    record = service.CostRollupService(db).rollup(payload, user.client_id, user.email)
    db.commit(); db.refresh(record)
    return _to_split_response(record)


@cost_router.get("/splits/{material_code}",
                 response_model=schemas.CostComponentSplitResponse)
def get_latest_split(material_code: str, plant_code: str,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Get the most recent cost component split for a material+plant."""
    record = db.query(models.CostComponentSplit).filter(
        models.CostComponentSplit.client_id == user.client_id,
        models.CostComponentSplit.material_code == material_code,
        models.CostComponentSplit.plant_code == plant_code,
    ).order_by(models.CostComponentSplit.id.desc()).first()
    if not record:
        raise NotFoundError("CostComponentSplit", f"{material_code}@{plant_code}")
    return _to_split_response(record)


@cost_router.post("/compare", response_model=schemas.CostComparisonResponse)
def compare_costs_across_plants(
    payload: schemas.CostComparisonRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Compare the cost of producing the same material at different plants.

    Useful for transfer pricing analysis - see the per-component breakdown
    of why one plant is more/less expensive than another.
    """
    rows: list[schemas.CostComparisonRow] = []
    for plant in payload.plant_codes:
        try:
            rec = service.CostRollupService(db).rollup(
                schemas.CostRollupRequest(
                    material_code=payload.material_code,
                    plant_code=plant,
                    save_result=False,
                ),
                user.client_id, user.email,
            )
            rows.append(schemas.CostComparisonRow(
                plant_code=plant,
                raw_material_cost=rec.raw_material_cost,
                labor_cost=rec.labor_cost,
                machine_cost=rec.machine_cost,
                overhead_cost=rec.overhead_cost,
                total_cost=rec.total_cost,
                currency=rec.currency,
                base_unit=rec.base_unit,
            ))
        except (NotFoundError, BusinessRuleError) as exc:
            # Plant has no production setup - report zeros
            rows.append(schemas.CostComparisonRow(
                plant_code=plant,
                raw_material_cost=Decimal("0"),
                labor_cost=Decimal("0"),
                machine_cost=Decimal("0"),
                overhead_cost=Decimal("0"),
                total_cost=Decimal("0"),
                currency="N/A",
                base_unit="N/A",
            ))
    return schemas.CostComparisonResponse(material_code=payload.material_code, rows=rows)


# ==================================================================
# Compliance Snapshot - generic data interface for external services
# ==================================================================
compliance_router = APIRouter(prefix="/pp/compliance",
                              tags=["PP - Compliance Data Export"])


@compliance_router.get("/snapshot", response_model=schemas.BomComplianceSnapshotResponse)
def get_compliance_snapshot(material_code: str, plant_code: str,
                            db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    """Generic snapshot of a BOM's trade-compliance attributes.

    The ERP exposes this as a vendor-neutral data interface.
    External services (such as AI_TradeManagement) consume this snapshot
    and apply their own classification / judgment rules.

    The ERP does NOT make compliance judgments - it only delivers
    structured data with HS codes, ECCN, country of origin, etc.
    """
    return service.ComplianceSnapshotService(db).build(
        user.client_id, material_code, plant_code,
    )


# ==================================================================
# Helpers
# ==================================================================
def _to_split_response(record: models.CostComponentSplit
                       ) -> schemas.CostComponentSplitResponse:
    breakdown = None
    if record.breakdown_json:
        try:
            raw = json.loads(record.breakdown_json)
            breakdown = [schemas.CostBreakdownItem(**item) for item in raw]
        except Exception:
            breakdown = None
    return schemas.CostComponentSplitResponse(
        id=record.id,
        material_code=record.material_code,
        plant_code=record.plant_code,
        production_version_code=record.production_version_code,
        raw_material_cost=record.raw_material_cost,
        labor_cost=record.labor_cost,
        machine_cost=record.machine_cost,
        overhead_cost=record.overhead_cost,
        external_processing_cost=record.external_processing_cost,
        total_cost=record.total_cost,
        currency=record.currency,
        base_unit=record.base_unit,
        valid_from=record.valid_from,
        valid_to=record.valid_to,
        breakdown=breakdown,
    )


def get_pp_routers() -> list[APIRouter]:
    return [
        work_centers_router, recipes_router, explosion_router,
        routings_router, pv_router, cost_router, compliance_router,
    ]
