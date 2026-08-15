"""CO (Controlling) — Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.shared.base_schemas import AuditFields, ORMModel


# ══════════════════════════════════════════════════════════════════════
# Asset Master
# ══════════════════════════════════════════════════════════════════════

class AssetMasterBase(BaseModel):
    asset_code: str = Field(..., max_length=20, examples=["MCH-001"])
    description: str = Field(..., max_length=255)
    asset_class: str = Field("MACHINERY", examples=["MACHINERY", "BUILDING", "TOOL", "IT_EQUIPMENT"])
    work_center_code: Optional[str] = Field(None, max_length=20)
    plant_code: Optional[str] = Field(None, max_length=10)
    acquisition_cost: Decimal = Field(..., gt=0)
    residual_value: Decimal = Field(Decimal("0"), ge=0)
    useful_life_years: int = Field(..., gt=0)
    depreciation_method: str = Field("straight_line", examples=["straight_line", "declining_balance"])
    acquisition_date: date
    currency: str = Field("JPY", min_length=3, max_length=3)
    notes: Optional[str] = None


class AssetMasterCreate(AssetMasterBase):
    pass


class AssetMasterUpdate(BaseModel):
    description: Optional[str] = None
    work_center_code: Optional[str] = None
    residual_value: Optional[Decimal] = None
    useful_life_years: Optional[int] = None
    depreciation_method: Optional[str] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class AssetMasterResponse(AssetMasterBase, AuditFields):
    id: int
    is_active: bool
    annual_depreciation: Decimal


# ══════════════════════════════════════════════════════════════════════
# Asset Cost Rate
# ══════════════════════════════════════════════════════════════════════

class AssetCostRateBase(BaseModel):
    asset_code: str = Field(..., max_length=20)
    fiscal_year: int = Field(..., ge=2000, le=2099)
    depreciation_plan: Decimal = Field(Decimal("0"), ge=0)
    maintenance_plan: Decimal = Field(Decimal("0"), ge=0)
    utility_plan: Decimal = Field(Decimal("0"), ge=0)
    planned_hours: Decimal = Field(..., gt=0)
    currency: str = Field("JPY", min_length=3, max_length=3)


class AssetCostRateCreate(AssetCostRateBase):
    pass


class AssetCostRateUpdate(BaseModel):
    depreciation_plan: Optional[Decimal] = None
    maintenance_plan: Optional[Decimal] = None
    utility_plan: Optional[Decimal] = None
    planned_hours: Optional[Decimal] = None


class AssetCostRateResponse(AssetCostRateBase, AuditFields):
    id: int
    machine_rate: Optional[Decimal]


# ══════════════════════════════════════════════════════════════════════
# Cost Center
# ══════════════════════════════════════════════════════════════════════

class CostCenterBase(BaseModel):
    cost_center_code: str = Field(..., max_length=20, examples=["CC-MFG-001"])
    name: str = Field(..., max_length=255)
    cost_center_type: str = Field("production", examples=["production", "service", "admin", "rd"])
    plant_code: Optional[str] = Field(None, max_length=10)
    work_center_code: Optional[str] = Field(None, max_length=20)
    responsible_employee_id: Optional[int] = None
    currency: str = Field("JPY", min_length=3, max_length=3)
    notes: Optional[str] = None


class CostCenterCreate(CostCenterBase):
    pass


class CostCenterUpdate(BaseModel):
    name: Optional[str] = None
    work_center_code: Optional[str] = None
    responsible_employee_id: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class CostCenterResponse(CostCenterBase, AuditFields):
    id: int
    is_active: bool


# ══════════════════════════════════════════════════════════════════════
# Cost Center Employee
# ══════════════════════════════════════════════════════════════════════

class CostCenterEmployeeBase(BaseModel):
    cost_center_code: str = Field(..., max_length=20)
    employee_id: int
    allocation_percent: Decimal = Field(Decimal("100"), ge=0, le=100)
    valid_from: date
    valid_to: Optional[date] = None


class CostCenterEmployeeCreate(CostCenterEmployeeBase):
    pass


class CostCenterEmployeeUpdate(BaseModel):
    allocation_percent: Optional[Decimal] = None
    valid_to: Optional[date] = None


class CostCenterEmployeeResponse(CostCenterEmployeeBase, AuditFields):
    id: int


# ══════════════════════════════════════════════════════════════════════
# Cost Center Budget
# ══════════════════════════════════════════════════════════════════════

class CostCenterBudgetBase(BaseModel):
    cost_center_code: str = Field(..., max_length=20)
    fiscal_year: int = Field(..., ge=2000, le=2099)
    labor_budget: Decimal = Field(Decimal("0"), ge=0)
    planned_labor_hours: Decimal = Field(Decimal("1"), gt=0)
    indirect_budget: Decimal = Field(Decimal("0"), ge=0)
    currency: str = Field("JPY", min_length=3, max_length=3)


class CostCenterBudgetCreate(CostCenterBudgetBase):
    pass


class CostCenterBudgetUpdate(BaseModel):
    labor_budget: Optional[Decimal] = None
    planned_labor_hours: Optional[Decimal] = None
    indirect_budget: Optional[Decimal] = None


class CostCenterBudgetResponse(CostCenterBudgetBase, AuditFields):
    id: int
    labor_rate: Optional[Decimal]
    overhead_rate_percent: Optional[Decimal]


# ══════════════════════════════════════════════════════════════════════
# Actual Cost Posting
# ══════════════════════════════════════════════════════════════════════

class ActualCostPostingCreate(BaseModel):
    process_order_id: int
    process_order_number: str = Field(..., max_length=20)
    cost_element: str = Field(..., examples=["MATERIAL", "LABOR", "MACHINE", "OVERHEAD", "EXTERNAL"])
    planned_quantity: Decimal = Field(Decimal("0"), ge=0)
    actual_quantity: Decimal = Field(Decimal("0"), ge=0)
    quantity_unit: Optional[str] = Field(None, max_length=5)
    planned_cost: Decimal = Field(Decimal("0"), ge=0)
    actual_cost: Decimal = Field(Decimal("0"), ge=0)
    variance_category: Optional[str] = Field(None, examples=[
        "PRICE_VARIANCE", "QUANTITY_VARIANCE", "RATE_VARIANCE", "VOLUME_VARIANCE"
    ])
    currency: str = Field("JPY", min_length=3, max_length=3)
    fiscal_year: Optional[int] = None
    fiscal_period: Optional[int] = Field(None, ge=1, le=12)
    notes: Optional[str] = None


class ActualCostPostingResponse(ORMModel):
    id: int
    process_order_id: int
    process_order_number: str
    cost_element: str
    planned_quantity: Decimal
    actual_quantity: Decimal
    quantity_unit: Optional[str]
    planned_cost: Decimal
    actual_cost: Decimal
    variance: Decimal
    variance_percent: Optional[Decimal]
    variance_category: Optional[str]
    currency: str
    fiscal_year: Optional[int]
    fiscal_period: Optional[int]
    posted_at: datetime
    notes: Optional[str]


# ══════════════════════════════════════════════════════════════════════
# Cost Estimate Item
# ══════════════════════════════════════════════════════════════════════

class CostEstimateItemBase(BaseModel):
    cost_split_id: int
    material_code: str = Field(..., max_length=20)
    plant_code: Optional[str] = Field(None, max_length=10)
    fiscal_year: int = Field(..., ge=2000, le=2099)
    item_type: str = Field(..., examples=["MATERIAL", "LABOR", "MACHINE", "OVERHEAD", "EXTERNAL"])
    reference_code: Optional[str] = Field(None, max_length=50)
    description: Optional[str] = Field(None, max_length=255)
    quantity: Decimal = Field(Decimal("0"), ge=0)
    quantity_unit: Optional[str] = Field(None, max_length=5)
    unit_cost: Decimal = Field(Decimal("0"), ge=0)
    total_cost: Decimal = Field(Decimal("0"), ge=0)
    currency: str = Field("JPY", min_length=3, max_length=3)
    origin_country: Optional[str] = Field(None, max_length=2)
    supplier_code: Optional[str] = Field(None, max_length=50)
    us_content_flag: bool = False
    eccn: Optional[str] = Field(None, max_length=20)


class CostEstimateItemCreate(CostEstimateItemBase):
    pass


class CostEstimateItemUpdate(BaseModel):
    quantity: Optional[Decimal] = None
    unit_cost: Optional[Decimal] = None
    total_cost: Optional[Decimal] = None
    origin_country: Optional[str] = None
    supplier_code: Optional[str] = None
    us_content_flag: Optional[bool] = None
    eccn: Optional[str] = None


class CostEstimateItemResponse(CostEstimateItemBase, AuditFields):
    id: int


# ══════════════════════════════════════════════════════════════════════
# Calculation result schemas
# ══════════════════════════════════════════════════════════════════════

class MachineRateResult(BaseModel):
    asset_code: str
    fiscal_year: int
    machine_rate: Decimal
    currency: str


class LaborRateResult(BaseModel):
    cost_center_code: str
    fiscal_year: int
    labor_rate: Decimal
    overhead_rate_percent: Decimal
    currency: str


class WorkCenterRateUpdateResult(BaseModel):
    updated: int
    details: List[dict]


class DeMinimisResult(BaseModel):
    material_code: str
    fiscal_year: int
    total_cost: Decimal
    us_content_cost: Decimal
    us_content_percent: Decimal
    de_minimis_threshold: Decimal = Decimal("25.00")
    is_de_minimis: bool
    currency: str
