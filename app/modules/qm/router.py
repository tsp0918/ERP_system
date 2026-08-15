"""QM (Quality Management) — REST endpoints."""
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.modules.qm import schemas, service
from app.shared.base_schemas import PaginatedResponse


# ══════════════════════════════════════════════════════════════════════
# Material Specs
# ══════════════════════════════════════════════════════════════════════

spec_router = APIRouter(prefix="/qm/specs", tags=["QM - Material Specs"])


@spec_router.get("", response_model=PaginatedResponse[schemas.MaterialSpecResponse])
def list_specs(
    material_code: Optional[str] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.MaterialSpecService(db)
    items = svc.list_specs(user.client_id, material_code, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@spec_router.post("", response_model=schemas.MaterialSpecResponse,
                  status_code=status.HTTP_201_CREATED)
def create_spec(
    body: schemas.MaterialSpecCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.MaterialSpecService(db)
    spec = svc.create_spec(user.client_id, body, user.email)
    db.commit()
    db.refresh(spec)
    return spec


@spec_router.get("/{spec_id}", response_model=schemas.MaterialSpecResponse)
def get_spec(
    spec_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.MaterialSpecService(db).get_spec(user.client_id, spec_id)


@spec_router.get("/current/{material_code}", response_model=schemas.MaterialSpecResponse)
def get_current_spec(
    material_code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.MaterialSpecService(db).get_current_spec(user.client_id, material_code)


@spec_router.patch("/{spec_id}", response_model=schemas.MaterialSpecResponse)
def update_spec(
    spec_id: int, body: schemas.MaterialSpecUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.MaterialSpecService(db)
    spec = svc.update_spec(user.client_id, spec_id, body, user.email)
    db.commit()
    db.refresh(spec)
    return spec


# ══════════════════════════════════════════════════════════════════════
# Inspection Plans
# ══════════════════════════════════════════════════════════════════════

plan_router = APIRouter(prefix="/qm/plans", tags=["QM - Inspection Plans"])


@plan_router.get("", response_model=PaginatedResponse[schemas.InspectionPlanResponse])
def list_plans(
    material_code: Optional[str] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionPlanService(db)
    items = svc.list_plans(user.client_id, material_code, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@plan_router.post("", response_model=schemas.InspectionPlanResponse,
                  status_code=status.HTTP_201_CREATED)
def create_plan(
    body: schemas.InspectionPlanCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionPlanService(db)
    plan = svc.create_plan(user.client_id, body, user.email)
    db.commit()
    db.refresh(plan)
    return plan


@plan_router.get("/{plan_code}", response_model=schemas.InspectionPlanResponse)
def get_plan(
    plan_code: str,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.InspectionPlanService(db).get_plan(user.client_id, plan_code)


@plan_router.patch("/{plan_code}", response_model=schemas.InspectionPlanResponse)
def update_plan(
    plan_code: str, body: schemas.InspectionPlanUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionPlanService(db)
    plan = svc.update_plan(user.client_id, plan_code, body, user.email)
    db.commit()
    db.refresh(plan)
    return plan


# ══════════════════════════════════════════════════════════════════════
# Inspection Lots
# ══════════════════════════════════════════════════════════════════════

lot_router = APIRouter(prefix="/qm/lots", tags=["QM - Inspection Lots"])


@lot_router.get("", response_model=PaginatedResponse[schemas.InspectionLotResponse])
def list_lots(
    material_code: Optional[str] = None,
    lot_status: Optional[str] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionLotService(db)
    items = svc.list_lots(user.client_id, material_code, lot_status, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@lot_router.post("", response_model=schemas.InspectionLotResponse,
                 status_code=status.HTTP_201_CREATED)
def create_lot(
    body: schemas.InspectionLotCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionLotService(db)
    lot = svc.create_lot(user.client_id, body, user.email)
    db.commit()
    db.refresh(lot)
    return lot


@lot_router.get("/{lot_id}", response_model=schemas.InspectionLotResponse)
def get_lot(
    lot_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.InspectionLotService(db).get_lot(user.client_id, lot_id)


@lot_router.patch("/{lot_id}", response_model=schemas.InspectionLotResponse)
def update_lot(
    lot_id: int, body: schemas.InspectionLotUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionLotService(db)
    lot = svc.update_lot(user.client_id, lot_id, body, user.email)
    db.commit()
    db.refresh(lot)
    return lot


@lot_router.post("/{lot_id}/judge", response_model=schemas.LotJudgmentSummary,
                 summary="Auto-judge lot based on all recorded inspection results")
def judge_lot(
    lot_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionLotService(db)
    result = svc.judge_lot(user.client_id, lot_id, user.email)
    db.commit()
    return result


# ══════════════════════════════════════════════════════════════════════
# Inspection Results
# ══════════════════════════════════════════════════════════════════════

result_router = APIRouter(prefix="/qm/results", tags=["QM - Inspection Results"])


@result_router.get("/{lot_id}",
                   response_model=PaginatedResponse[schemas.InspectionResultResponse])
def list_results(
    lot_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionResultService(db)
    items = svc.list_results(user.client_id, lot_id)
    return PaginatedResponse(items=items, total=len(items), skip=0, limit=len(items) or 1)


@result_router.post("", response_model=schemas.InspectionResultResponse,
                    status_code=status.HTTP_201_CREATED,
                    summary="Record inspection result (auto-judges NUMERIC/BOOLEAN)")
def record_result(
    body: schemas.InspectionResultCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionResultService(db)
    result = svc.record_result(user.client_id, body, user.email)
    db.commit()
    db.refresh(result)
    return result


@result_router.patch("/{result_id}", response_model=schemas.InspectionResultResponse)
def update_result(
    result_id: int, body: schemas.InspectionResultUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.InspectionResultService(db)
    result = svc.update_result(user.client_id, result_id, body, user.email)
    db.commit()
    db.refresh(result)
    return result


# ══════════════════════════════════════════════════════════════════════
# Quality Certificates (CoA)
# ══════════════════════════════════════════════════════════════════════

cert_router = APIRouter(prefix="/qm/certificates", tags=["QM - Quality Certificates"])


@cert_router.get("", response_model=PaginatedResponse[schemas.QualityCertificateResponse])
def list_certs(
    material_code: Optional[str] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.QualityCertificateService(db)
    items = svc.list_certs(user.client_id, material_code, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@cert_router.post("", response_model=schemas.QualityCertificateResponse,
                  status_code=status.HTTP_201_CREATED,
                  summary="Issue CoA for a passed inspection lot")
def issue_cert(
    body: schemas.QualityCertificateCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.QualityCertificateService(db)
    cert = svc.issue_cert(user.client_id, body, user.email)
    db.commit()
    db.refresh(cert)
    return cert


# ══════════════════════════════════════════════════════════════════════
# Quality Notifications
# ══════════════════════════════════════════════════════════════════════

qn_router = APIRouter(prefix="/qm/notifications", tags=["QM - Quality Notifications"])


@qn_router.get("", response_model=PaginatedResponse[schemas.QualityNotificationResponse])
def list_notifications(
    status: Optional[str] = None,
    severity: Optional[str] = None,
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.QualityNotificationService(db)
    items = svc.list_notifications(user.client_id, status, severity, skip, limit)
    return PaginatedResponse(items=items, total=len(items), skip=skip, limit=limit)


@qn_router.post("", response_model=schemas.QualityNotificationResponse,
                status_code=status.HTTP_201_CREATED)
def create_notification(
    body: schemas.QualityNotificationCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.QualityNotificationService(db)
    qn = svc.create_notification(user.client_id, body, user.email)
    db.commit()
    db.refresh(qn)
    return qn


@qn_router.get("/{notification_id}", response_model=schemas.QualityNotificationResponse)
def get_notification(
    notification_id: int,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    return service.QualityNotificationService(db).get_notification(
        user.client_id, notification_id)


@qn_router.patch("/{notification_id}", response_model=schemas.QualityNotificationResponse,
                 summary="Update status / corrective action")
def update_notification(
    notification_id: int, body: schemas.QualityNotificationUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    svc = service.QualityNotificationService(db)
    qn = svc.update_notification(user.client_id, notification_id, body, user.email)
    db.commit()
    db.refresh(qn)
    return qn


# ══════════════════════════════════════════════════════════════════════
# Router registry
# ══════════════════════════════════════════════════════════════════════

def get_qm_routers():
    return [
        spec_router,
        plan_router,
        lot_router,
        result_router,
        cert_router,
        qn_router,
    ]
