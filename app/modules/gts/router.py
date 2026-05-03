"""GTS REST endpoints (manual triggers + webhook receiver)."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.gts.service import GTSService
from app.modules.mdm.models import Material


router = APIRouter(prefix="/gts", tags=["GTS - Trade Compliance"])


class WebhookJudgmentUpdate(BaseModel):
    """Payload from AI_TradeManagement when a material judgment is updated externally."""
    material_code: str
    new_judgment: str
    new_eccn: str | None = None
    rationale: str | None = None


@router.post("/webhook/judgment-updated", status_code=status.HTTP_204_NO_CONTENT)
def receive_judgment_update(
    payload: WebhookJudgmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Receive an updated 該非判定 from AI_TradeManagement.

    Updates the material and re-evaluates affected open Sales Orders.
    """
    material = db.query(Material).filter(
        Material.material_code == payload.material_code,
        Material.client_id == user.client_id,
    ).first()
    if not material:
        raise NotFoundError("Material", payload.material_code)

    material.fefta_judgment = payload.new_judgment
    if payload.new_eccn:
        material.eccn = payload.new_eccn
    db.commit()

    # Re-evaluation of related open SOs is left as an extension hook.
    return None


@router.post("/check-material/{material_id}")
def check_material(
    material_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually run classification + 該非判定 against AI_TradeManagement."""
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


@router.post("/judge-bom")
def judge_bom(
    material_code: str,
    plant_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Submit a multi-level BOM to AI_TradeManagement for judgment.

    The ERP builds the compliance snapshot internally (per BOM explosion)
    and forwards it to AI_TM. AI_TM applies its judgment rules and returns
    an aggregate decision. The ERP simply records and displays the result;
    it does not make compliance judgments on its own.
    """
    result = GTSService(db).judge_bom(material_code, plant_code, user.client_id)
    return result


def get_gts_routers() -> list[APIRouter]:
    return [router]
