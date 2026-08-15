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


# ==================================================================
# Material Alternatives
# ==================================================================
alt_router = APIRouter(prefix="/pp/material-alternatives",
                       tags=["PP - Material Alternatives"])


@alt_router.get("", response_model=PaginatedResponse[schemas.MaterialAlternativeResponse])
def list_material_alternatives(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    recipe_id: int | None = None,
    original_material_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.shared.base_repository import BaseRepository
    repo = BaseRepository(models.MaterialAlternative, db)
    filters = {"recipe_id": recipe_id, "original_material_code": original_material_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@alt_router.get("/{alt_id}", response_model=schemas.MaterialAlternativeResponse)
def get_material_alternative(
    alt_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.shared.base_repository import BaseRepository
    instance = BaseRepository(models.MaterialAlternative, db).get(alt_id, user.client_id)
    if not instance:
        raise NotFoundError("MaterialAlternative", alt_id)
    return instance


@alt_router.post("", response_model=schemas.MaterialAlternativeResponse,
                 status_code=status.HTTP_201_CREATED)
def create_material_alternative(
    payload: schemas.MaterialAlternativeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    alt = service.MaterialAlternativeService(db).create(payload, user.client_id, user.email)
    db.commit()
    db.refresh(alt)
    return alt


@alt_router.put("/{alt_id}", response_model=schemas.MaterialAlternativeResponse)
def update_material_alternative(
    alt_id: int,
    payload: schemas.MaterialAlternativeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.shared.base_repository import BaseRepository
    repo = BaseRepository(models.MaterialAlternative, db)
    instance = repo.get(alt_id, user.client_id)
    if not instance:
        raise NotFoundError("MaterialAlternative", alt_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(instance, data)
    db.commit()
    db.refresh(instance)
    return instance


# ==================================================================
# Cost Sync (CostComponentSplit → Material.standard_price)
# ==================================================================
from typing import Optional as _Opt2
from pydantic import BaseModel as _BM
from sqlalchemy import text as _text

cost_sync_router = APIRouter(prefix="/pp/cost-rollup", tags=["PP - Cost Rollup"])


class CostSyncResult(_BM):
    updated: int
    skipped: int
    details: list[dict]


@cost_sync_router.post("/sync-standard-cost", response_model=CostSyncResult,
                       summary="Push latest CostComponentSplit.total_cost → Material.standard_price")
def sync_standard_cost(
    plant_code: _Opt2[str] = Query(None, description="Limit to one plant"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """For each material with a CostComponentSplit, update Material.standard_price
    with the most recent valid estimate. Idempotent."""
    sql = _text("""
        SELECT material_code, total_cost, currency
        FROM (
            SELECT material_code, total_cost, currency,
                   ROW_NUMBER() OVER (PARTITION BY material_code ORDER BY valid_from DESC) AS rn
            FROM cost_component_splits
            WHERE client_id = :client_id
              AND (:plant IS NULL OR plant_code = :plant)
        ) ranked
        WHERE rn = 1
    """)
    rows = db.execute(sql, {"client_id": user.client_id, "plant": plant_code}).fetchall()

    from app.modules.mdm.models import Material

    updated, skipped = 0, 0
    details = []
    for r in rows:
        mat = db.query(Material).filter(
            Material.client_id == user.client_id,
            Material.material_code == r.material_code,
        ).first()
        if not mat:
            skipped += 1
            continue
        old = mat.standard_price
        mat.standard_price = r.total_cost
        mat.currency = r.currency
        mat.updated_by = user.email
        updated += 1
        details.append({
            "material_code": r.material_code,
            "old_price": float(old) if old is not None else None,
            "new_price": float(r.total_cost),
            "currency": r.currency,
        })
    db.commit()
    return CostSyncResult(updated=updated, skipped=skipped, details=details)


# ==================================================================
# Production Schedule (cross-view of open process orders)
# ==================================================================
from pydantic import BaseModel as _BM2
from datetime import datetime as _dt
from decimal import Decimal as _Dec

schedule_router = APIRouter(prefix="/pp/schedule", tags=["PP - Production Schedule"])


class ScheduleComponent(_BM2):
    material_code: str
    planned_quantity: _Dec
    issued_quantity: _Dec
    remaining_quantity: _Dec
    unit: str


class ProductionScheduleItem(_BM2):
    order_id: int
    order_number: str
    material_code: str
    plant_code: str
    status: str
    target_quantity: _Dec
    actual_quantity: _Dec
    progress_percent: float
    scheduled_start: _Opt2[_dt]
    scheduled_end: _Opt2[_dt]
    components: list[ScheduleComponent]


@schedule_router.get("", response_model=list[ProductionScheduleItem],
                     summary="Production order schedule with component requirements")
def production_schedule(
    status: _Opt2[str] = Query(None, examples=["OPEN", "RELEASED", "DRAFT"]),
    material_code: _Opt2[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.modules.pp.execution_models import ProcessOrder, ProcessOrderComponent

    q = db.query(ProcessOrder).filter(ProcessOrder.client_id == user.client_id)
    if status:
        q = q.filter(ProcessOrder.status == status)
    else:
        q = q.filter(ProcessOrder.status.in_(["DRAFT", "OPEN", "RELEASED"]))
    if material_code:
        q = q.filter(ProcessOrder.material_code == material_code)
    orders = q.order_by(ProcessOrder.scheduled_start.asc().nullslast()).limit(limit).all()

    result = []
    for o in orders:
        comps = db.query(ProcessOrderComponent).filter(
            ProcessOrderComponent.process_order_id == o.id
        ).all()
        progress = (float(o.actual_quantity) / float(o.target_quantity) * 100
                    if o.target_quantity else 0)
        result.append(ProductionScheduleItem(
            order_id=o.id,
            order_number=o.document_number,
            material_code=o.material_code,
            plant_code=o.plant_code,
            status=o.status,
            target_quantity=o.target_quantity,
            actual_quantity=o.actual_quantity,
            progress_percent=round(progress, 1),
            scheduled_start=o.scheduled_start,
            scheduled_end=o.scheduled_end,
            components=[
                ScheduleComponent(
                    material_code=c.material_code,
                    planned_quantity=c.planned_quantity,
                    issued_quantity=c.issued_quantity,
                    remaining_quantity=c.planned_quantity - c.issued_quantity,
                    unit=c.unit,
                )
                for c in comps
            ],
        ))
    return result


def get_pp_routers() -> list[APIRouter]:
    return [
        work_centers_router, recipes_router, explosion_router,
        routings_router, pv_router, cost_router, compliance_router,
        alt_router, cost_sync_router, schedule_router,
    ]
