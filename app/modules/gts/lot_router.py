"""GTS lot-traceability and De Minimis alert endpoints."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.gts.models import (
    MaterialOriginChangeLog, LotDeMinimusAssessment, DeniedPartyScreeningLog,
)
from app.modules.mdm.models import BusinessPartner
from app.modules.pp.execution_models import Batch, BatchGenealogy

# ──────────────────────────────────────────────────────────────────
# Batch / Lot List
# ──────────────────────────────────────────────────────────────────
batch_router = APIRouter(prefix="/mm/batches", tags=["MM - Batch/Lot Traceability"])


class BatchResponse(BaseModel):
    id: int
    batch_code: str
    material_code: str
    plant_code: str
    quantity: float
    unit: str
    source_type: str
    source_reference: Optional[str]
    country_of_origin: Optional[str]
    vendor_code: Optional[str]
    quality_status: str
    production_date: Optional[str]
    expiry_date: Optional[str]
    finished_batch_code: Optional[str] = None  # for genealogy lookup


@batch_router.get("", response_model=list[BatchResponse])
def list_batches(
    material_code: Optional[str] = Query(None),
    source_type: Optional[str] = Query(None, description="PURCHASED / PRODUCED"),
    country_of_origin: Optional[str] = Query(None),
    quality_status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Batch).filter(Batch.client_id == user.client_id)
    if material_code:
        q = q.filter(Batch.material_code == material_code)
    if source_type:
        q = q.filter(Batch.source_type == source_type)
    if country_of_origin:
        q = q.filter(Batch.country_of_origin == country_of_origin)
    if quality_status:
        q = q.filter(Batch.quality_status == quality_status)
    batches = q.order_by(Batch.production_date.desc()).offset(skip).limit(limit).all()
    return [_batch_to_response(b) for b in batches]


def _batch_to_response(b: Batch) -> dict:
    return {
        "id": b.id,
        "batch_code": b.batch_code,
        "material_code": b.material_code,
        "plant_code": b.plant_code,
        "quantity": float(b.quantity),
        "unit": b.unit,
        "source_type": b.source_type,
        "source_reference": b.source_reference,
        "country_of_origin": b.country_of_origin,
        "vendor_code": b.vendor_code,
        "quality_status": b.quality_status,
        "production_date": str(b.production_date) if b.production_date else None,
        "expiry_date": str(b.expiry_date) if b.expiry_date else None,
    }


class GenealogyNode(BaseModel):
    batch_code: str
    material_code: str
    country_of_origin: Optional[str]
    quantity: float
    unit: str
    source_type: str
    direction: str  # PARENT / CHILD


class GenealogyResponse(BaseModel):
    batch_code: str
    material_code: str
    country_of_origin: Optional[str]
    production_date: Optional[str]
    quality_status: str
    parents: list[GenealogyNode]
    children: list[GenealogyNode]


@batch_router.get("/{batch_code}/genealogy", response_model=GenealogyResponse)
def get_genealogy(
    batch_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Trace one hop up (raw material inputs) and one hop down (finished goods outputs)."""
    batch = db.query(Batch).filter(
        Batch.client_id == user.client_id, Batch.batch_code == batch_code).first()
    if not batch:
        raise NotFoundError("Batch", batch_code)

    # Parents: raw material batches consumed to produce this batch
    parent_links = db.query(BatchGenealogy).filter(
        BatchGenealogy.client_id == user.client_id,
        BatchGenealogy.child_batch_code == batch_code,
    ).all()

    # Children: finished goods batches that consumed this raw batch
    child_links = db.query(BatchGenealogy).filter(
        BatchGenealogy.client_id == user.client_id,
        BatchGenealogy.parent_batch_code == batch_code,
    ).all()

    def enrich_link(link: BatchGenealogy, code: str, direction: str) -> dict:
        b2 = db.query(Batch).filter(
            Batch.client_id == user.client_id, Batch.batch_code == code).first()
        return {
            "batch_code": code,
            "material_code": link.parent_material_code if direction == "PARENT" else link.child_material_code,
            "country_of_origin": b2.country_of_origin if b2 else None,
            "quantity": float(link.consumed_quantity),
            "unit": link.consumed_unit,
            "source_type": b2.source_type if b2 else "UNKNOWN",
            "direction": direction,
        }

    return {
        "batch_code": batch.batch_code,
        "material_code": batch.material_code,
        "country_of_origin": batch.country_of_origin,
        "production_date": str(batch.production_date) if batch.production_date else None,
        "quality_status": batch.quality_status,
        "parents": [enrich_link(lk, lk.parent_batch_code, "PARENT") for lk in parent_links],
        "children": [enrich_link(lk, lk.child_batch_code, "CHILD") for lk in child_links],
    }


# ──────────────────────────────────────────────────────────────────
# Origin Change Log
# ──────────────────────────────────────────────────────────────────
origin_router = APIRouter(
    prefix="/gts/origin-change-log", tags=["GTS - Origin Change & De Minimis"])


class OriginChangeResponse(BaseModel):
    id: int
    material_code: str
    from_country: str
    to_country: str
    effective_date: str
    old_vendor_code: Optional[str]
    new_vendor_code: Optional[str]
    last_old_batch_code: Optional[str]
    first_new_batch_code: Optional[str]
    affected_fg_codes: list[str]
    max_deminimis_impact_pct: Optional[float]
    exceeds_threshold: bool
    threshold_pct: float
    ai_tm_notification_sent: bool
    ai_tm_case_ref: Optional[str]
    review_status: str


@origin_router.get("", response_model=list[OriginChangeResponse])
def list_origin_changes(
    material_code: Optional[str] = Query(None),
    review_status: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(MaterialOriginChangeLog).filter(
        MaterialOriginChangeLog.client_id == user.client_id)
    if material_code:
        q = q.filter(MaterialOriginChangeLog.material_code == material_code)
    if review_status:
        q = q.filter(MaterialOriginChangeLog.review_status == review_status)
    logs = q.order_by(MaterialOriginChangeLog.effective_date.desc()).all()
    return [_ocl_to_response(log) for log in logs]


def _ocl_to_response(log: MaterialOriginChangeLog) -> dict:
    return {
        "id": log.id,
        "material_code": log.material_code,
        "from_country": log.from_country,
        "to_country": log.to_country,
        "effective_date": str(log.effective_date),
        "old_vendor_code": log.old_vendor_code,
        "new_vendor_code": log.new_vendor_code,
        "last_old_batch_code": log.last_old_batch_code,
        "first_new_batch_code": log.first_new_batch_code,
        "affected_fg_codes": json.loads(log.affected_fg_codes_json or "[]"),
        "max_deminimis_impact_pct": float(log.max_deminimis_impact_pct) if log.max_deminimis_impact_pct else None,
        "exceeds_threshold": log.exceeds_threshold,
        "threshold_pct": float(log.threshold_pct),
        "ai_tm_notification_sent": log.ai_tm_notification_sent,
        "ai_tm_case_ref": log.ai_tm_case_ref,
        "review_status": log.review_status,
    }


@origin_router.post("/{log_id}/notify-aitm",
                    summary="Push origin change event to AI_TradeManagement")
def notify_aitm(
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Push the origin change event and BREACH-level De Minimis assessments to AI_TM.

    Returns the AI_TM case reference (or a mock ref if AI_TM is offline).
    """
    log = db.query(MaterialOriginChangeLog).filter(
        MaterialOriginChangeLog.client_id == user.client_id,
        MaterialOriginChangeLog.id == log_id,
    ).first()
    if not log:
        raise NotFoundError("MaterialOriginChangeLog", log_id)

    # Find BREACH-level assessments for FG materials affected by this change
    affected_fg = json.loads(log.affected_fg_codes_json or "[]")
    breach_assessments = db.query(LotDeMinimusAssessment).filter(
        LotDeMinimusAssessment.client_id == user.client_id,
        LotDeMinimusAssessment.fg_material_code.in_(affected_fg),
        LotDeMinimusAssessment.alert_level == "BREACH",
        LotDeMinimusAssessment.ai_tm_notified == False,
    ).all()

    # Build payload for AI_TM
    from app.modules.gts.service import GTSService
    gts = GTSService(db)

    payload = {
        "event_type": "MATERIAL_ORIGIN_CHANGE",
        "material_code": log.material_code,
        "from_country": log.from_country,
        "to_country": log.to_country,
        "effective_date": str(log.effective_date),
        "max_us_content_pct": float(log.max_deminimis_impact_pct or 0),
        "exceeds_deminimis_threshold": log.exceeds_threshold,
        "affected_products": affected_fg,
        "breach_lot_count": len(breach_assessments),
        "breach_lots": [
            {
                "fg_batch_code": a.fg_batch_code,
                "fg_material_code": a.fg_material_code,
                "us_content_pct": float(a.us_content_pct),
            }
            for a in breach_assessments[:10]
        ],
    }

    case_ref = gts.push_origin_change_to_aitm(payload)

    # Mark as notified
    now = datetime.utcnow()
    log.ai_tm_notification_sent = True
    log.ai_tm_notification_at = now
    log.ai_tm_case_ref = case_ref
    log.review_status = "ACTION_REQUIRED" if log.exceeds_threshold else "REVIEWED"

    for a in breach_assessments:
        a.ai_tm_notified = True
        a.ai_tm_notified_at = now
        a.ai_tm_case_ref = case_ref

    db.commit()
    return {
        "status": "notified",
        "ai_tm_case_ref": case_ref,
        "breach_assessments_notified": len(breach_assessments),
        "payload_summary": {
            "material_code": log.material_code,
            "origin_change": f"{log.from_country}→{log.to_country}",
            "max_us_content_pct": float(log.max_deminimis_impact_pct or 0),
        },
    }


# ──────────────────────────────────────────────────────────────────
# De Minimis Assessments
# ──────────────────────────────────────────────────────────────────
deminimis_router = APIRouter(
    prefix="/gts/deminimis", tags=["GTS - Origin Change & De Minimis"])


class DeMinimusResponse(BaseModel):
    id: int
    fg_batch_code: str
    fg_material_code: str
    process_order_number: str
    us_origin_value: float
    total_bom_value: float
    us_content_pct: float
    threshold_pct: float
    alert_level: str
    us_components: list[dict]
    ai_tm_notified: bool
    ai_tm_case_ref: Optional[str]
    assessed_at: str


@deminimis_router.get("", response_model=list[DeMinimusResponse])
def list_deminimis(
    alert_level: Optional[str] = Query(None, description="OK / WARNING / BREACH"),
    fg_material_code: Optional[str] = Query(None),
    ai_tm_notified: Optional[bool] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(LotDeMinimusAssessment).filter(
        LotDeMinimusAssessment.client_id == user.client_id)
    if alert_level:
        q = q.filter(LotDeMinimusAssessment.alert_level == alert_level)
    if fg_material_code:
        q = q.filter(LotDeMinimusAssessment.fg_material_code == fg_material_code)
    if ai_tm_notified is not None:
        q = q.filter(LotDeMinimusAssessment.ai_tm_notified == ai_tm_notified)
    items = q.order_by(LotDeMinimusAssessment.us_content_pct.desc()).offset(skip).limit(limit).all()
    return [_dm_to_response(a) for a in items]


def _dm_to_response(a: LotDeMinimusAssessment) -> dict:
    return {
        "id": a.id,
        "fg_batch_code": a.fg_batch_code,
        "fg_material_code": a.fg_material_code,
        "process_order_number": a.process_order_number,
        "us_origin_value": float(a.us_origin_value),
        "total_bom_value": float(a.total_bom_value),
        "us_content_pct": float(a.us_content_pct),
        "threshold_pct": float(a.threshold_pct),
        "alert_level": a.alert_level,
        "us_components": json.loads(a.us_components_json or "[]"),
        "ai_tm_notified": a.ai_tm_notified,
        "ai_tm_case_ref": a.ai_tm_case_ref,
        "assessed_at": str(a.assessed_at),
    }


class MarkNotifiedBody(BaseModel):
    ai_tm_case_ref: Optional[str] = None


@deminimis_router.patch("/{record_id}/mark-notified")
def mark_deminimis_notified(
    record_id: int,
    body: MarkNotifiedBody,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """AI_TM Pull ポーラーが案件作成後に呼び出し、ai_tm_notified フラグを立てる。"""
    a = db.query(LotDeMinimusAssessment).filter(
        LotDeMinimusAssessment.id == record_id,
        LotDeMinimusAssessment.client_id == user.client_id,
    ).first()
    if not a:
        raise HTTPException(status_code=404, detail="record not found")
    a.ai_tm_notified = True
    a.ai_tm_notified_at = datetime.utcnow()
    if body.ai_tm_case_ref:
        a.ai_tm_case_ref = body.ai_tm_case_ref
    db.commit()
    return {"ok": True, "id": record_id, "ai_tm_case_ref": a.ai_tm_case_ref}


# ──────────────────────────────────────────────────────────────────
# Denied Party Screening
# ──────────────────────────────────────────────────────────────────
screening_router = APIRouter(prefix="/gts/screening", tags=["GTS - Denied Party Screening"])


class ScreeningLogResponse(BaseModel):
    id: int
    bp_code: str
    bp_name: str
    bp_country: str
    match_status: str
    match_score: float
    matched_list: Optional[str]
    matched_entity_name: Optional[str]
    denial_reason: Optional[str]
    fifty_pct_rule_triggered: bool
    parent_sanctioned_entity: Optional[str]
    ownership_pct: Optional[float]
    ai_tm_screening_ref: Optional[str]
    screened_at: str
    screened_by: Optional[str]

    class Config:
        from_attributes = True


class RescreenResult(BaseModel):
    bp_code: str
    bp_name: str
    screening_status: str
    match_status: str
    match_score: float
    matched_list: Optional[str]
    ai_tm_ref: Optional[str]


@screening_router.get("/log", response_model=list[ScreeningLogResponse])
def list_screening_logs(
    match_status: Optional[str] = Query(None, description="Filter: CRITICAL/match/possible_match/no_match"),
    bp_code: Optional[str] = None,
    fifty_pct_only: bool = Query(False, description="Only 50% Rule hits"),
    skip: int = 0,
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """制裁スクリーニング監査ログ一覧。"""
    q = db.query(DeniedPartyScreeningLog).filter(
        DeniedPartyScreeningLog.client_id == user.client_id
    )
    if match_status:
        q = q.filter(DeniedPartyScreeningLog.match_status == match_status)
    if bp_code:
        q = q.filter(DeniedPartyScreeningLog.bp_code == bp_code)
    if fifty_pct_only:
        q = q.filter(DeniedPartyScreeningLog.fifty_pct_rule_triggered == True)
    logs = q.order_by(DeniedPartyScreeningLog.screened_at.desc()).offset(skip).limit(limit).all()
    return [ScreeningLogResponse(
        id=l.id, bp_code=l.bp_code, bp_name=l.bp_name, bp_country=l.bp_country,
        match_status=l.match_status, match_score=float(l.match_score or 0),
        matched_list=l.matched_list, matched_entity_name=l.matched_entity_name,
        denial_reason=l.denial_reason, fifty_pct_rule_triggered=l.fifty_pct_rule_triggered,
        parent_sanctioned_entity=l.parent_sanctioned_entity,
        ownership_pct=float(l.ownership_pct) if l.ownership_pct else None,
        ai_tm_screening_ref=l.ai_tm_screening_ref,
        screened_at=str(l.screened_at), screened_by=l.screened_by,
    ) for l in logs]


@screening_router.post("/rescreen-all", response_model=list[RescreenResult])
def rescreen_all_partners(
    only_unscreened: bool = Query(True, description="True=UNSCREENED のみ / False=全件再スクリーニング"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """全取引先をバルクスクリーニングし AI_TM に結果を通知する。"""
    from app.modules.gts.service import GTSService
    gts = GTSService(db)

    q = db.query(BusinessPartner).filter(BusinessPartner.client_id == user.client_id)
    if only_unscreened:
        q = q.filter(BusinessPartner.screening_status == "UNSCREENED")
    bps = q.all()

    results = []
    for bp in bps:
        gts.screen_business_partner(bp, screened_by=user.email)
        db.flush()
        results.append(RescreenResult(
            bp_code=bp.bp_code,
            bp_name=bp.name,
            screening_status=bp.screening_status,
            match_status=(
                "CRITICAL" if bp.screening_status == "BLOCKED"
                else "match" if bp.screening_status == "FLAGGED"
                else "no_match"
            ),
            match_score=0.0,
            matched_list=bp.denial_list,
            ai_tm_ref=bp.ai_tm_screening_ref,
        ))

    db.commit()
    flagged = sum(1 for r in results if r.screening_status in ("BLOCKED", "FLAGGED"))
    import logging
    logging.getLogger(__name__).info(
        "Bulk screening: %d BPs screened, %d flagged", len(results), flagged
    )
    return results


@screening_router.post("/{bp_code}/rescreen", response_model=RescreenResult)
def rescreen_single(
    bp_code: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """指定取引先を個別再スクリーニング。"""
    from app.modules.gts.service import GTSService
    bp = db.query(BusinessPartner).filter(
        BusinessPartner.client_id == user.client_id,
        BusinessPartner.bp_code == bp_code,
    ).first()
    if not bp:
        raise HTTPException(status_code=404, detail=f"BusinessPartner {bp_code} not found")

    GTSService(db).screen_business_partner(bp, screened_by=user.email)
    db.commit()
    return RescreenResult(
        bp_code=bp.bp_code,
        bp_name=bp.name,
        screening_status=bp.screening_status,
        match_status=(
            "CRITICAL" if bp.screening_status == "BLOCKED"
            else "match" if bp.screening_status == "FLAGGED"
            else "no_match"
        ),
        match_score=0.0,
        matched_list=bp.denial_list,
        ai_tm_ref=bp.ai_tm_screening_ref,
    )


def get_lot_traceability_routers():
    return [batch_router, origin_router, deminimis_router, screening_router]
