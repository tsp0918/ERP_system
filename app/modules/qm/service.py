"""QM (Quality Management) — business logic."""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.numbering import next_number
from app.modules.qm import models, schemas
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)

_LOT_PREFIX  = "INSP"
_CERT_PREFIX = "COA"
_QN_PREFIX   = "QN"


# ══════════════════════════════════════════════════════════════════════
# Material Spec Service
# ══════════════════════════════════════════════════════════════════════

class MaterialSpecService:
    def __init__(self, db: Session):
        self.db = db
        self._specs = BaseRepository(models.MaterialSpec, db)

    def list_specs(self, client_id: str, material_code: Optional[str],
                   skip: int, limit: int) -> list:
        filters = {"material_code": material_code} if material_code else {}
        return self._specs.list(client_id=client_id, filters=filters,
                                skip=skip, limit=limit)

    def get_spec(self, client_id: str, spec_id: int) -> models.MaterialSpec:
        spec = (
            self.db.query(models.MaterialSpec)
            .filter(models.MaterialSpec.client_id == client_id,
                    models.MaterialSpec.id == spec_id)
            .first()
        )
        if not spec:
            raise NotFoundError(f"MaterialSpec {spec_id} not found")
        return spec

    def get_current_spec(self, client_id: str, material_code: str) -> models.MaterialSpec:
        spec = (
            self.db.query(models.MaterialSpec)
            .filter(models.MaterialSpec.client_id == client_id,
                    models.MaterialSpec.material_code == material_code,
                    models.MaterialSpec.is_current == True)
            .first()
        )
        if not spec:
            raise NotFoundError(f"No current spec for material '{material_code}'")
        return spec

    def create_spec(self, client_id: str, data: schemas.MaterialSpecCreate,
                    user_email: str) -> models.MaterialSpec:
        # If is_current=True, demote existing current versions
        if data.is_current:
            (
                self.db.query(models.MaterialSpec)
                .filter(models.MaterialSpec.client_id == client_id,
                        models.MaterialSpec.material_code == data.material_code,
                        models.MaterialSpec.is_current == True)
                .update({"is_current": False})
            )

        spec = models.MaterialSpec(
            **{k: v for k, v in data.model_dump(exclude={"characteristics"}).items()},
            client_id=client_id,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(spec)
        self.db.flush()

        for char_data in data.characteristics:
            char = models.SpecCharacteristic(
                **char_data.model_dump(),
                spec_id=spec.id,
                client_id=client_id,
                created_by=user_email,
                updated_by=user_email,
            )
            self.db.add(char)
        self.db.flush()
        return spec

    def update_spec(self, client_id: str, spec_id: int,
                    data: schemas.MaterialSpecUpdate,
                    user_email: str) -> models.MaterialSpec:
        spec = self.get_spec(client_id, spec_id)
        if data.is_current:
            (
                self.db.query(models.MaterialSpec)
                .filter(models.MaterialSpec.client_id == client_id,
                        models.MaterialSpec.material_code == spec.material_code,
                        models.MaterialSpec.id != spec_id,
                        models.MaterialSpec.is_current == True)
                .update({"is_current": False})
            )
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(spec, k, v)
        spec.updated_by = user_email
        self.db.flush()
        return spec


# ══════════════════════════════════════════════════════════════════════
# Inspection Plan Service
# ══════════════════════════════════════════════════════════════════════

class InspectionPlanService:
    def __init__(self, db: Session):
        self.db = db
        self._plans = BaseRepository(models.InspectionPlan, db)

    def list_plans(self, client_id: str, material_code: Optional[str],
                   skip: int, limit: int) -> list:
        filters = {"material_code": material_code} if material_code else {}
        return self._plans.list(client_id=client_id, filters=filters,
                                skip=skip, limit=limit)

    def get_plan(self, client_id: str, plan_code: str) -> models.InspectionPlan:
        plans = self._plans.list(client_id=client_id, filters={"plan_code": plan_code})
        if not plans:
            raise NotFoundError(f"InspectionPlan '{plan_code}' not found")
        return plans[0]

    def create_plan(self, client_id: str, data: schemas.InspectionPlanCreate,
                    user_email: str) -> models.InspectionPlan:
        plan = models.InspectionPlan(
            **{k: v for k, v in data.model_dump(exclude={"operations"}).items()},
            client_id=client_id,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(plan)
        self.db.flush()

        for op_data in data.operations:
            op = models.InspectionOperation(
                **op_data.model_dump(),
                plan_id=plan.id,
                client_id=client_id,
                created_by=user_email,
                updated_by=user_email,
            )
            self.db.add(op)
        self.db.flush()
        return plan

    def update_plan(self, client_id: str, plan_code: str,
                    data: schemas.InspectionPlanUpdate,
                    user_email: str) -> models.InspectionPlan:
        plan = self.get_plan(client_id, plan_code)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(plan, k, v)
        plan.updated_by = user_email
        self.db.flush()
        return plan


# ══════════════════════════════════════════════════════════════════════
# Inspection Lot Service
# ══════════════════════════════════════════════════════════════════════

class InspectionLotService:
    def __init__(self, db: Session):
        self.db = db

    def list_lots(self, client_id: str, material_code: Optional[str],
                  lot_status: Optional[str], skip: int, limit: int) -> list:
        q = (
            self.db.query(models.InspectionLot)
            .filter(models.InspectionLot.client_id == client_id)
        )
        if material_code:
            q = q.filter(models.InspectionLot.material_code == material_code)
        if lot_status:
            q = q.filter(models.InspectionLot.lot_status == lot_status)
        return q.order_by(models.InspectionLot.created_at.desc()).offset(skip).limit(limit).all()

    def get_lot(self, client_id: str, lot_id: int) -> models.InspectionLot:
        lot = (
            self.db.query(models.InspectionLot)
            .filter(models.InspectionLot.client_id == client_id,
                    models.InspectionLot.id == lot_id)
            .first()
        )
        if not lot:
            raise NotFoundError(f"InspectionLot {lot_id} not found")
        return lot

    def create_lot(self, client_id: str, data: schemas.InspectionLotCreate,
                   user_email: str) -> models.InspectionLot:
        lot_number = next_number(self.db, client_id, _LOT_PREFIX)
        lot = models.InspectionLot(
            **data.model_dump(),
            lot_number=lot_number,
            client_id=client_id,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(lot)
        self.db.flush()
        return lot

    def update_lot(self, client_id: str, lot_id: int,
                   data: schemas.InspectionLotUpdate,
                   user_email: str) -> models.InspectionLot:
        lot = self.get_lot(client_id, lot_id)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(lot, k, v)
        lot.updated_by = user_email
        self.db.flush()
        return lot

    def judge_lot(self, client_id: str, lot_id: int,
                  user_email: str) -> schemas.LotJudgmentSummary:
        """Auto-judge lot based on all inspection results."""
        lot = self.get_lot(client_id, lot_id)
        results = (
            self.db.query(models.InspectionResult)
            .filter(models.InspectionResult.client_id == client_id,
                    models.InspectionResult.lot_id == lot_id)
            .all()
        )
        if not results:
            raise BusinessRuleError("No inspection results recorded for this lot")

        total   = len(results)
        passed  = sum(1 for r in results if r.judgment == "PASS")
        failed  = sum(1 for r in results if r.judgment == "FAIL")
        pending = sum(1 for r in results if r.judgment == "PENDING")
        critical_failures = sum(1 for r in results if r.judgment == "FAIL" and r.is_critical)

        if pending > 0:
            overall = "CONDITIONAL"
        elif failed == 0:
            overall = "PASS"
        else:
            overall = "FAIL"

        auto_close = pending == 0
        lot.overall_judgment = overall
        lot.lot_status = "PASSED" if overall == "PASS" else ("FAILED" if overall == "FAIL" else "PARTIAL")
        if auto_close:
            lot.completed_date = date.today()
        lot.updated_by = user_email
        self.db.flush()

        return schemas.LotJudgmentSummary(
            lot_id=lot_id,
            lot_number=lot.lot_number,
            total_characteristics=total,
            passed=passed,
            failed=failed,
            pending=pending,
            critical_failures=critical_failures,
            overall_judgment=overall,
            auto_close=auto_close,
        )


# ══════════════════════════════════════════════════════════════════════
# Inspection Result Service
# ══════════════════════════════════════════════════════════════════════

class InspectionResultService:
    def __init__(self, db: Session):
        self.db = db

    def list_results(self, client_id: str, lot_id: int) -> list:
        return (
            self.db.query(models.InspectionResult)
            .filter(models.InspectionResult.client_id == client_id,
                    models.InspectionResult.lot_id == lot_id)
            .all()
        )

    def record_result(self, client_id: str, data: schemas.InspectionResultCreate,
                      user_email: str) -> models.InspectionResult:
        # Auto-judge numeric results
        judgment = "PENDING"
        if data.measurement_type == "NUMERIC" and data.measured_value is not None:
            ok = True
            if data.lower_limit is not None and data.measured_value < data.lower_limit:
                ok = False
            if data.upper_limit is not None and data.measured_value > data.upper_limit:
                ok = False
            judgment = "PASS" if ok else "FAIL"
        elif data.measurement_type == "BOOLEAN" and data.measured_bool is not None:
            judgment = "PASS" if data.measured_bool else "FAIL"

        result = models.InspectionResult(
            **data.model_dump(),
            judgment=judgment,
            client_id=client_id,
            inspected_by=user_email,
            inspected_at=datetime.utcnow(),
        )
        self.db.add(result)
        self.db.flush()
        return result

    def update_result(self, client_id: str, result_id: int,
                      data: schemas.InspectionResultUpdate,
                      user_email: str) -> models.InspectionResult:
        result = (
            self.db.query(models.InspectionResult)
            .filter(models.InspectionResult.client_id == client_id,
                    models.InspectionResult.id == result_id)
            .first()
        )
        if not result:
            raise NotFoundError(f"InspectionResult {result_id} not found")
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(result, k, v)
        # Re-auto-judge numeric if value changed
        if data.measured_value is not None and result.measurement_type == "NUMERIC":
            ok = True
            if result.lower_limit and result.measured_value < result.lower_limit:
                ok = False
            if result.upper_limit and result.measured_value > result.upper_limit:
                ok = False
            result.judgment = "PASS" if ok else "FAIL"
            result.inspected_by = user_email
            result.inspected_at = datetime.utcnow()
        self.db.flush()
        return result


# ══════════════════════════════════════════════════════════════════════
# Quality Certificate Service
# ══════════════════════════════════════════════════════════════════════

class QualityCertificateService:
    def __init__(self, db: Session):
        self.db = db

    def list_certs(self, client_id: str, material_code: Optional[str],
                   skip: int, limit: int) -> list:
        q = (
            self.db.query(models.QualityCertificate)
            .filter(models.QualityCertificate.client_id == client_id)
        )
        if material_code:
            q = q.filter(models.QualityCertificate.material_code == material_code)
        return q.order_by(models.QualityCertificate.issue_date.desc()).offset(skip).limit(limit).all()

    def issue_cert(self, client_id: str, data: schemas.QualityCertificateCreate,
                   user_email: str) -> models.QualityCertificate:
        # Verify lot exists and passed
        lot = (
            self.db.query(models.InspectionLot)
            .filter(models.InspectionLot.client_id == client_id,
                    models.InspectionLot.id == data.lot_id)
            .first()
        )
        if not lot:
            raise NotFoundError(f"InspectionLot {data.lot_id} not found")
        if lot.lot_status not in ("PASSED", "PARTIAL"):
            raise BusinessRuleError(
                f"Cannot issue certificate for lot in status '{lot.lot_status}'")

        # Check all results passed
        results = (
            self.db.query(models.InspectionResult)
            .filter(models.InspectionResult.client_id == client_id,
                    models.InspectionResult.lot_id == data.lot_id)
            .all()
        )
        all_passed = all(r.judgment == "PASS" for r in results) if results else False

        cert_number = next_number(self.db, client_id, _CERT_PREFIX)
        cert = models.QualityCertificate(
            **data.model_dump(),
            cert_number=cert_number,
            client_id=client_id,
            all_passed=all_passed,
            created_by=user_email,
        )
        self.db.add(cert)
        self.db.flush()
        return cert


# ══════════════════════════════════════════════════════════════════════
# Quality Notification Service
# ══════════════════════════════════════════════════════════════════════

class QualityNotificationService:
    def __init__(self, db: Session):
        self.db = db

    def list_notifications(self, client_id: str, status: Optional[str],
                           severity: Optional[str], skip: int, limit: int) -> list:
        q = (
            self.db.query(models.QualityNotification)
            .filter(models.QualityNotification.client_id == client_id)
        )
        if status:
            q = q.filter(models.QualityNotification.status == status)
        if severity:
            q = q.filter(models.QualityNotification.severity == severity)
        return q.order_by(models.QualityNotification.reported_date.desc()).offset(skip).limit(limit).all()

    def get_notification(self, client_id: str, notification_id: int) -> models.QualityNotification:
        qn = (
            self.db.query(models.QualityNotification)
            .filter(models.QualityNotification.client_id == client_id,
                    models.QualityNotification.id == notification_id)
            .first()
        )
        if not qn:
            raise NotFoundError(f"QualityNotification {notification_id} not found")
        return qn

    def create_notification(self, client_id: str, data: schemas.QualityNotificationCreate,
                            user_email: str) -> models.QualityNotification:
        qn_number = next_number(self.db, client_id, _QN_PREFIX)
        qn = models.QualityNotification(
            **data.model_dump(),
            notification_number=qn_number,
            client_id=client_id,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(qn)
        self.db.flush()
        return qn

    def update_notification(self, client_id: str, notification_id: int,
                            data: schemas.QualityNotificationUpdate,
                            user_email: str) -> models.QualityNotification:
        qn = self.get_notification(client_id, notification_id)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(qn, k, v)
        if data.status == "CLOSED" and not qn.closed_date:
            qn.closed_date = date.today()
        qn.updated_by = user_email
        self.db.flush()
        return qn
