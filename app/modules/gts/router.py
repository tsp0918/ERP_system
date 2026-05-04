"""GTS REST endpoints (manual triggers + webhook receiver)."""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.gts.service import GTSService
from app.modules.mdm.models import Material


router = APIRouter(prefix="/gts", tags=["GTS - Trade Compliance"])


# ------------------------------------------------------------------
# Webhook auth helper (API key — AI_TM does not hold an ERP JWT)
# ------------------------------------------------------------------
def _verify_webhook_key(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {settings.AI_TM_API_KEY}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing webhook API key",
        )


# ------------------------------------------------------------------
# Webhook: AI_TM → ERP judgment update
# ------------------------------------------------------------------
class WebhookJudgmentUpdate(BaseModel):
    material_code: str
    new_judgment: str
    new_eccn: str | None = None
    rationale: str | None = None
    client_id: str = "DEMO"     # AI_TM can specify tenant; defaults to DEMO


@router.post("/webhook/judgment-updated", status_code=status.HTTP_200_OK)
def receive_judgment_update(
    payload: WebhookJudgmentUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(_verify_webhook_key),
):
    """Receive a judgment update from AI_TradeManagement.

    - Updates material ECCN / judgment
    - Auto-unblocks deliveries / SOs when APPROVED
    - Cancels open SOs for the material when REJECTED
    Returns HTTP 200 (fire-and-forget; AI_TM does not retry on 2xx).
    """
    result = GTSService(db).apply_judgment_update(
        client_id=payload.client_id,
        material_code=payload.material_code,
        new_judgment=payload.new_judgment,
        new_eccn=payload.new_eccn,
        rationale=payload.rationale,
    )
    db.commit()
    return result


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
    return [router]
