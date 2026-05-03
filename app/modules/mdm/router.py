"""MDM REST endpoints.

Companies use the generic CRUD factory.
Materials and BusinessPartners override `create` to integrate with AI_TM.
"""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.mdm import models, schemas, service
from app.shared.base_repository import BaseRepository
from app.shared.base_router import create_crud_router
from app.shared.base_schemas import PaginatedResponse


# ------------------------------------------------------------------
# Companies - pure generic CRUD
# ------------------------------------------------------------------
companies_router = create_crud_router(
    prefix="/mdm/companies",
    tags=["MDM - Companies"],
    model=models.Company,
    create_schema=schemas.CompanyCreate,
    update_schema=schemas.CompanyUpdate,
    response_schema=schemas.CompanyResponse,
    resource_name="Company",
)


# ------------------------------------------------------------------
# Materials - custom create with AI_TM integration
# ------------------------------------------------------------------
materials_router = APIRouter(prefix="/mdm/materials", tags=["MDM - Materials"])


@materials_router.get("", response_model=PaginatedResponse[schemas.MaterialResponse])
def list_materials(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    material_type: str | None = None,
    hs_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.Material, db)
    filters = {"material_type": material_type, "hs_code": hs_code}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@materials_router.get("/{item_id}", response_model=schemas.MaterialResponse)
def get_material(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = BaseRepository(models.Material, db).get(item_id, client_id=user.client_id)
    if not instance:
        raise NotFoundError("Material", item_id)
    return instance


@materials_router.post("", response_model=schemas.MaterialResponse,
                       status_code=status.HTTP_201_CREATED)
def create_material(
    payload: schemas.MaterialCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a material. Triggers AI_TradeManagement classification by default."""
    material = service.MaterialService(db).create(payload, user.client_id, user.email)
    db.commit()
    db.refresh(material)
    return material


@materials_router.put("/{item_id}", response_model=schemas.MaterialResponse)
def update_material(
    item_id: int,
    payload: schemas.MaterialUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.Material, db)
    instance = repo.get(item_id, client_id=user.client_id)
    if not instance:
        raise NotFoundError("Material", item_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(instance, data)
    db.commit()
    db.refresh(instance)
    return instance


@materials_router.post("/{item_id}/reclassify", response_model=schemas.MaterialResponse)
def reclassify_material(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually trigger AI_TradeManagement re-classification."""
    instance = BaseRepository(models.Material, db).get(item_id, client_id=user.client_id)
    if not instance:
        raise NotFoundError("Material", item_id)
    from app.modules.gts.service import GTSService
    GTSService(db).classify_material(instance)
    db.commit()
    db.refresh(instance)
    return instance


# ------------------------------------------------------------------
# Business Partners - custom create with denied-party screening
# ------------------------------------------------------------------
bp_router = APIRouter(prefix="/mdm/business-partners", tags=["MDM - Business Partners"])


@bp_router.get("", response_model=PaginatedResponse[schemas.BusinessPartnerResponse])
def list_bps(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    role: str | None = Query(None, description="Filter by role token (CUSTOMER/VENDOR)"),
    country: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.BusinessPartner, db)
    items = repo.list(
        client_id=user.client_id,
        filters={"country": country},
        skip=skip, limit=limit,
    )
    if role:
        items = [bp for bp in items if bp.has_role(role)]
    total = len(items) if role else repo.count(
        client_id=user.client_id, filters={"country": country}
    )
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@bp_router.get("/{item_id}", response_model=schemas.BusinessPartnerResponse)
def get_bp(
    item_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = BaseRepository(models.BusinessPartner, db).get(item_id, client_id=user.client_id)
    if not instance:
        raise NotFoundError("BusinessPartner", item_id)
    return instance


@bp_router.post("", response_model=schemas.BusinessPartnerResponse,
                status_code=status.HTTP_201_CREATED)
def create_bp(
    payload: schemas.BusinessPartnerCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bp = service.BusinessPartnerService(db).create(payload, user.client_id, user.email)
    db.commit()
    db.refresh(bp)
    return bp


@bp_router.put("/{item_id}", response_model=schemas.BusinessPartnerResponse)
def update_bp(
    item_id: int,
    payload: schemas.BusinessPartnerUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.BusinessPartner, db)
    instance = repo.get(item_id, client_id=user.client_id)
    if not instance:
        raise NotFoundError("BusinessPartner", item_id)
    data = payload.model_dump(exclude_unset=True)
    data["updated_by"] = user.email
    repo.update(instance, data)
    db.commit()
    db.refresh(instance)
    return instance


# Aggregate router for inclusion in main app
def get_mdm_routers() -> list[APIRouter]:
    return [companies_router, materials_router, bp_router]
