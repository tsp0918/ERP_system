"""GTS REST endpoints (manual triggers + webhook receiver)."""
from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.gts import models as gts_models
from app.modules.gts import schemas as gts_schemas
from app.modules.gts.service import GTSService, ExportDeclarationService
from app.modules.mdm.models import Material
from app.shared.base_repository import BaseRepository
from app.shared.base_schemas import PaginatedResponse
from app.shared.integration_auth import verify_inbound


router = APIRouter(prefix="/gts", tags=["GTS - Trade Compliance"])


# ------------------------------------------------------------------
# Webhook: AI_TM → ERP judgment update  (E0-4: HMAC-SHA256 auth)
# ------------------------------------------------------------------
class WebhookJudgmentUpdate(BaseModel):
    material_code: str
    new_judgment: str
    new_eccn: str | None = None
    rationale: str | None = None
    client_id: str = "DEMO"     # AI_TM can specify tenant; defaults to DEMO
    # IF-23: allocation ID populated when AI_TM completes license allocation
    allocation_id: str | None = None
    transaction_id: str | None = None


@router.post("/webhook/judgment-updated", status_code=status.HTTP_200_OK)
async def receive_judgment_update(
    request: Request,
    payload: WebhookJudgmentUpdate,
    x_signature: str = Header(default=""),
    x_timestamp: str = Header(default=""),
    x_request_id: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """Receive a judgment update from AI_TradeManagement.

    Auth: HMAC-SHA256 (X-Signature) + Bearer (X-Authorization) + timestamp ±300s.
    - Updates material ECCN / judgment
    - Auto-unblocks deliveries / SOs when APPROVED
    - Cancels open SOs for the material when REJECTED
    - Stores aitm_allocation_id when payload.allocation_id is present (IF-23)
    Returns HTTP 200 (fire-and-forget; AI_TM does not retry on 2xx).
    """
    await verify_inbound(
        request, "aitm", x_signature, x_timestamp, x_request_id, db, x_tenant_id
    )

    result = GTSService(db).apply_judgment_update(
        client_id=payload.client_id,
        material_code=payload.material_code,
        new_judgment=payload.new_judgment,
        new_eccn=payload.new_eccn,
        rationale=payload.rationale,
    )

    # IF-23: store allocation_id on the linked SalesOrder
    if payload.allocation_id and payload.transaction_id:
        _store_allocation_id(db, payload.client_id, payload.transaction_id, payload.allocation_id)

    db.commit()
    return result


def _store_allocation_id(db: Session, client_id: str, transaction_id: str, allocation_id: str) -> None:
    """Persist aitm_allocation_id received via IF-23 onto the matching SalesOrder."""
    from app.modules.sd.models import SalesOrder
    so = db.query(SalesOrder).filter(
        SalesOrder.client_id == client_id,
        SalesOrder.aitm_transaction_id == transaction_id,
    ).first()
    if so:
        so.aitm_allocation_id = allocation_id


# ------------------------------------------------------------------
# Manual: re-classify a material
# ------------------------------------------------------------------
@router.post("/check-material/{material_id}")
def check_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually run HS classification + 該非判定 against AI_TradeManagement."""
    material = db.query(Material).filter(
        Material.id == material_id,
        Material.client_id == user.client_id,
    ).first()
    if not material:
        raise NotFoundError("Material", material_id)
    GTSService(db).classify_material(material)
    db.commit()
    db.refresh(material)
    return {
        "material_code": material.material_code,
        "hs_code": material.hs_code,
        "eccn": material.eccn,
        "fefta_judgment": material.fefta_judgment,
        "last_compliance_check_at": material.last_compliance_check_at,
    }


# ------------------------------------------------------------------
# Manual: BOM judgment
# ------------------------------------------------------------------
@router.post("/judge-bom")
def judge_bom(
    material_code: str,
    plant_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit a multi-level BOM to AI_TradeManagement for judgment."""
    result = GTSService(db).judge_bom(material_code, plant_code, user.client_id)
    return result


def get_gts_routers() -> list[APIRouter]:
    return [router, export_decl_router, crm_gts_router, license_router]


# ==================================================================
# E4-5: License Consumption Log query
# ==================================================================
license_router = APIRouter(prefix="/gts", tags=["GTS - Trade Compliance"])


@license_router.get("/license-consumptions")
def list_license_consumptions(
    delivery_id: int | None = Query(None),
    allocation_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """E4-5: List license consumption records for the authenticated client."""
    from sqlalchemy import select
    from app.modules.gts.models import LicenseConsumptionLog

    q = select(LicenseConsumptionLog).where(
        LicenseConsumptionLog.client_id == user.client_id
    )
    if delivery_id is not None:
        q = q.where(LicenseConsumptionLog.delivery_id == delivery_id)
    if allocation_id is not None:
        q = q.where(LicenseConsumptionLog.allocation_id == allocation_id)

    total = db.execute(
        select(LicenseConsumptionLog).where(LicenseConsumptionLog.client_id == user.client_id)
    ).scalars().all()
    items = db.execute(q.offset(skip).limit(limit)).scalars().all()

    return {
        "items": [
            {
                "id": r.id,
                "delivery_id": r.delivery_id,
                "sales_order_id": r.sales_order_id,
                "allocation_id": r.allocation_id,
                "consumed_quantity": str(r.consumed_quantity),
                "remaining_quantity": str(r.remaining_quantity) if r.remaining_quantity is not None else None,
                "response_status": r.response_status,
                "consumed_at": r.consumed_at.isoformat(),
            }
            for r in items
        ],
        "total": len(total),
        "skip": skip,
        "limit": limit,
    }


# ==================================================================
# IF-32: CRM → ERP Commerce Check (stub)
# ==================================================================
crm_gts_router = APIRouter(prefix="/crm", tags=["CRM Integration"])


class CommerceCheckCounterparty(BaseModel):
    bp_code: str | None = None
    crm_account_id: str | None = None
    name: str | None = None
    country: str | None = None


class CommerceCheckRequest(BaseModel):
    """IF-32 inbound payload from CRM for credit/antisocial check."""
    request_type: str = "quote"              # "quote" | "engagement"
    crm_quote_id: int | None = None
    crm_engagement_id: int | None = None
    counterparty: CommerceCheckCounterparty
    client_id: str = "DEMO"


@crm_gts_router.post("/commerce-check")
async def commerce_check(
    request: Request,
    payload: CommerceCheckRequest,
    x_signature: str = Header(default=""),
    x_timestamp: str = Header(default=""),
    x_request_id: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """IF-32: Commerce check (credit + antisocial) called by CRM at quote/contract stage.

    Stub mode (COMMERCE_CHECK_STUB_MODE=true): always returns ok.
    Response is production-equivalent; counterparty_attributes from real ERP data.
    stub_mode=true is logged for audit.
    """
    await verify_inbound(request, "crm", x_signature, x_timestamp, x_request_id, db, x_tenant_id)

    from app.modules.gts.commerce_check import run_commerce_check
    # Always scope to the configured CRM tenant for consistent BP lookups
    result = run_commerce_check(db, settings.CRM_CLIENT_ID, payload.model_dump())
    db.commit()
    return result


# ==================================================================
# Export Declarations
# ==================================================================
export_decl_router = APIRouter(prefix="/gts/export-declarations",
                               tags=["GTS - Export Declarations"])


@export_decl_router.get("",
                        response_model=PaginatedResponse[gts_schemas.ExportDeclarationResponse])
def list_export_declarations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    status_: str | None = Query(None, alias="status"),
    destination_country: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(gts_models.ExportDeclaration, db)
    filters = {"status": status_, "destination_country": destination_country}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@export_decl_router.get("/{decl_id}",
                        response_model=gts_schemas.ExportDeclarationResponse)
def get_export_declaration(
    decl_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.execute(
        select(gts_models.ExportDeclaration).where(
            gts_models.ExportDeclaration.id == decl_id,
            gts_models.ExportDeclaration.client_id == user.client_id,
        )
    ).scalar_one_or_none()
    if not instance:
        raise NotFoundError("ExportDeclaration", decl_id)
    return instance


@export_decl_router.post("",
                         response_model=gts_schemas.ExportDeclarationResponse,
                         status_code=status.HTTP_201_CREATED)
def create_export_declaration(
    payload: gts_schemas.ExportDeclarationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    decl = ExportDeclarationService(db).create(payload, user.client_id, user.email)
    db.commit()
    db.refresh(decl)
    return decl


@export_decl_router.put("/{decl_id}",
                        response_model=gts_schemas.ExportDeclarationResponse)
def update_export_declaration(
    decl_id: int,
    payload: gts_schemas.ExportDeclarationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    instance = db.execute(
        select(gts_models.ExportDeclaration).where(
            gts_models.ExportDeclaration.id == decl_id,
            gts_models.ExportDeclaration.client_id == user.client_id,
        )
    ).scalar_one_or_none()
    if not instance:
        raise NotFoundError("ExportDeclaration", decl_id)
    data = payload.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(instance, k, v)
    db.commit()
    db.refresh(instance)
    return instance


@export_decl_router.post("/{decl_id}/submit",
                         response_model=gts_schemas.ExportDeclarationResponse)
def submit_export_declaration(
    decl_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Transition a DRAFT export declaration to SUBMITTED."""
    decl = ExportDeclarationService(db).submit(decl_id, user.client_id, user.email)
    db.commit()
    db.refresh(decl)
    return decl
