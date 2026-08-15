"""QM (Quality Management) — Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.shared.base_schemas import AuditFields, ORMModel


# ══════════════════════════════════════════════════════════════════════
# Spec Characteristic (nested)
# ══════════════════════════════════════════════════════════════════════

class SpecCharacteristicBase(BaseModel):
    char_code: str = Field(..., max_length=20, examples=["PURITY"])
    description: str = Field(..., max_length=255)
    measurement_type: str = Field("NUMERIC", examples=["NUMERIC", "BOOLEAN", "TEXT"])
    unit: Optional[str] = Field(None, max_length=20)
    target_value: Optional[Decimal] = None
    lower_limit: Optional[Decimal] = None
    upper_limit: Optional[Decimal] = None
    acceptable_text: Optional[str] = Field(None, max_length=255)
    is_critical: bool = False


class SpecCharacteristicCreate(SpecCharacteristicBase):
    pass


class SpecCharacteristicResponse(SpecCharacteristicBase, AuditFields):
    id: int
    spec_id: int


# ══════════════════════════════════════════════════════════════════════
# Material Spec
# ══════════════════════════════════════════════════════════════════════

class MaterialSpecBase(BaseModel):
    material_code: str = Field(..., max_length=20)
    revision: str = Field("A", max_length=10)
    description: Optional[str] = Field(None, max_length=255)
    is_current: bool = True
    effective_from: date
    effective_to: Optional[date] = None
    approved_by: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class MaterialSpecCreate(MaterialSpecBase):
    characteristics: List[SpecCharacteristicCreate] = []


class MaterialSpecUpdate(BaseModel):
    description: Optional[str] = None
    is_current: Optional[bool] = None
    effective_to: Optional[date] = None
    approved_by: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class MaterialSpecResponse(MaterialSpecBase, AuditFields):
    id: int
    is_active: bool
    approved_at: Optional[datetime]
    characteristics: List[SpecCharacteristicResponse] = []


# ══════════════════════════════════════════════════════════════════════
# Inspection Plan
# ══════════════════════════════════════════════════════════════════════

class InspectionOperationBase(BaseModel):
    operation_no: int = Field(..., ge=10)
    char_code: str = Field(..., max_length=20)
    description: Optional[str] = Field(None, max_length=255)
    work_center_code: Optional[str] = Field(None, max_length=20)
    required: bool = True


class InspectionOperationCreate(InspectionOperationBase):
    pass


class InspectionOperationResponse(InspectionOperationBase, AuditFields):
    id: int
    plan_id: int


class InspectionPlanBase(BaseModel):
    plan_code: str = Field(..., max_length=20)
    material_code: str = Field(..., max_length=20)
    plant_code: Optional[str] = Field(None, max_length=10)
    inspection_type: str = Field("OUTGOING", examples=["INCOMING", "IN_PROCESS", "OUTGOING"])
    description: Optional[str] = Field(None, max_length=255)
    sample_size: Optional[int] = Field(None, gt=0)
    sample_unit: Optional[str] = Field(None, max_length=10)
    valid_from: date
    valid_to: Optional[date] = None


class InspectionPlanCreate(InspectionPlanBase):
    operations: List[InspectionOperationCreate] = []


class InspectionPlanUpdate(BaseModel):
    description: Optional[str] = None
    sample_size: Optional[int] = None
    valid_to: Optional[date] = None
    is_active: Optional[bool] = None


class InspectionPlanResponse(InspectionPlanBase, AuditFields):
    id: int
    is_active: bool
    operations: List[InspectionOperationResponse] = []


# ══════════════════════════════════════════════════════════════════════
# Inspection Lot
# ══════════════════════════════════════════════════════════════════════

class InspectionLotCreate(BaseModel):
    material_code: str = Field(..., max_length=20)
    plant_code: Optional[str] = Field(None, max_length=10)
    inspection_type: str = Field("OUTGOING")
    plan_id: Optional[int] = None
    source_type: Optional[str] = Field(None, examples=["PROCESS_ORDER", "PURCHASE_ORDER", "DELIVERY"])
    source_id: Optional[int] = None
    source_number: Optional[str] = Field(None, max_length=20)
    lot_quantity: Decimal = Field(..., gt=0)
    quantity_unit: Optional[str] = Field(None, max_length=5)
    inspection_date: Optional[date] = None
    inspector_id: Optional[int] = None
    notes: Optional[str] = None


class InspectionLotUpdate(BaseModel):
    lot_status: Optional[str] = Field(None, examples=["OPEN", "IN_INSPECTION", "PASSED", "FAILED", "PARTIAL"])
    overall_judgment: Optional[str] = Field(None, examples=["PASS", "FAIL", "CONDITIONAL"])
    inspection_date: Optional[date] = None
    completed_date: Optional[date] = None
    inspector_id: Optional[int] = None
    notes: Optional[str] = None


class InspectionLotResponse(ORMModel):
    id: int
    lot_number: str
    material_code: str
    plant_code: Optional[str]
    inspection_type: str
    plan_id: Optional[int]
    source_type: Optional[str]
    source_id: Optional[int]
    source_number: Optional[str]
    lot_quantity: Decimal
    quantity_unit: Optional[str]
    created_date: date
    inspection_date: Optional[date]
    completed_date: Optional[date]
    lot_status: str
    overall_judgment: Optional[str]
    inspector_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


# ══════════════════════════════════════════════════════════════════════
# Inspection Result
# ══════════════════════════════════════════════════════════════════════

class InspectionResultCreate(BaseModel):
    lot_id: int
    char_code: str = Field(..., max_length=20)
    description: Optional[str] = Field(None, max_length=255)
    measurement_type: str = Field("NUMERIC")
    measured_value: Optional[Decimal] = None
    measured_bool: Optional[bool] = None
    measured_text: Optional[str] = Field(None, max_length=255)
    unit: Optional[str] = Field(None, max_length=20)
    lower_limit: Optional[Decimal] = None
    upper_limit: Optional[Decimal] = None
    target_value: Optional[Decimal] = None
    is_critical: bool = False
    inspected_by: Optional[str] = Field(None, max_length=100)
    notes: Optional[str] = None


class InspectionResultUpdate(BaseModel):
    measured_value: Optional[Decimal] = None
    measured_bool: Optional[bool] = None
    measured_text: Optional[str] = None
    judgment: Optional[str] = Field(None, examples=["PENDING", "PASS", "FAIL"])
    notes: Optional[str] = None


class InspectionResultResponse(ORMModel):
    id: int
    lot_id: int
    char_code: str
    description: Optional[str]
    measurement_type: str
    measured_value: Optional[Decimal]
    measured_bool: Optional[bool]
    measured_text: Optional[str]
    unit: Optional[str]
    lower_limit: Optional[Decimal]
    upper_limit: Optional[Decimal]
    target_value: Optional[Decimal]
    judgment: str
    is_critical: bool
    inspected_by: Optional[str]
    inspected_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime


# ══════════════════════════════════════════════════════════════════════
# Quality Certificate
# ══════════════════════════════════════════════════════════════════════

class QualityCertificateCreate(BaseModel):
    lot_id: int
    material_code: str = Field(..., max_length=20)
    issue_date: date = Field(default_factory=date.today)
    expiry_date: Optional[date] = None
    issued_by: Optional[str] = Field(None, max_length=100)
    customer_code: Optional[str] = Field(None, max_length=20)
    delivery_id: Optional[int] = None
    remarks: Optional[str] = None


class QualityCertificateResponse(ORMModel):
    id: int
    cert_number: str
    lot_id: int
    material_code: str
    issue_date: date
    expiry_date: Optional[date]
    issued_by: Optional[str]
    customer_code: Optional[str]
    delivery_id: Optional[int]
    all_passed: bool
    remarks: Optional[str]
    created_at: datetime
    created_by: Optional[str]


# ══════════════════════════════════════════════════════════════════════
# Quality Notification
# ══════════════════════════════════════════════════════════════════════

class QualityNotificationCreate(BaseModel):
    notification_type: str = Field("DEFECT", examples=["DEFECT", "DEVIATION", "COMPLAINT", "IMPROVEMENT"])
    material_code: Optional[str] = Field(None, max_length=20)
    lot_id: Optional[int] = None
    process_order_id: Optional[int] = None
    subject: str = Field(..., max_length=255)
    description: Optional[str] = None
    defect_code: Optional[str] = Field(None, max_length=20)
    severity: str = Field("MEDIUM", examples=["LOW", "MEDIUM", "HIGH", "CRITICAL"])
    quantity_affected: Optional[Decimal] = None
    quantity_unit: Optional[str] = Field(None, max_length=5)
    reported_date: date = Field(default_factory=date.today)
    due_date: Optional[date] = None
    reported_by: Optional[str] = Field(None, max_length=100)
    assigned_to: Optional[str] = Field(None, max_length=100)


class QualityNotificationUpdate(BaseModel):
    status: Optional[str] = Field(None, examples=["OPEN", "IN_PROGRESS", "CLOSED"])
    assigned_to: Optional[str] = None
    root_cause: Optional[str] = None
    corrective_action: Optional[str] = None
    closed_date: Optional[date] = None
    severity: Optional[str] = None


class QualityNotificationResponse(ORMModel):
    id: int
    notification_number: str
    notification_type: str
    material_code: Optional[str]
    lot_id: Optional[int]
    process_order_id: Optional[int]
    subject: str
    description: Optional[str]
    defect_code: Optional[str]
    severity: str
    quantity_affected: Optional[Decimal]
    quantity_unit: Optional[str]
    reported_date: date
    due_date: Optional[date]
    closed_date: Optional[date]
    reported_by: Optional[str]
    assigned_to: Optional[str]
    root_cause: Optional[str]
    corrective_action: Optional[str]
    status: str
    created_at: datetime
    updated_at: datetime


# ══════════════════════════════════════════════════════════════════════
# Judgment summary
# ══════════════════════════════════════════════════════════════════════

class LotJudgmentSummary(BaseModel):
    lot_id: int
    lot_number: str
    total_characteristics: int
    passed: int
    failed: int
    pending: int
    critical_failures: int
    overall_judgment: str
    auto_close: bool
