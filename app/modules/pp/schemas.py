"""Production Planning - Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.shared.base_schemas import AuditFields, ORMModel


# ==================================================================
# Work Center
# ==================================================================
class WorkCenterBase(BaseModel):
    work_center_code: str = Field(..., max_length=20, examples=["WC-MIX-01"])
    description: str = Field(..., max_length=255)
    plant_code: str = Field(..., max_length=10)
    capacity_per_day: Optional[Decimal] = None
    capacity_unit: str = Field("H", max_length=5)
    labor_rate_per_hour: Decimal = Field(Decimal("0"), ge=0)
    machine_rate_per_hour: Decimal = Field(Decimal("0"), ge=0)
    overhead_rate_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    currency: str = Field("JPY", min_length=3, max_length=3)


class WorkCenterCreate(WorkCenterBase):
    pass


class WorkCenterUpdate(BaseModel):
    description: Optional[str] = None
    capacity_per_day: Optional[Decimal] = None
    labor_rate_per_hour: Optional[Decimal] = None
    machine_rate_per_hour: Optional[Decimal] = None
    overhead_rate_percent: Optional[Decimal] = None
    is_active: Optional[bool] = None


class WorkCenterResponse(WorkCenterBase, AuditFields):
    id: int
    is_active: bool


# ==================================================================
# Recipe (BOM)
# ==================================================================
class RecipeItemCreate(BaseModel):
    component_material_code: str
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("PC", max_length=5)
    scrap_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    is_phantom: bool = False
    operation_no: Optional[int] = None


class RecipeItemResponse(ORMModel):
    id: int
    item_no: int
    component_material_code: str
    quantity: Decimal
    unit: str
    scrap_percent: Decimal
    is_phantom: bool
    operation_no: Optional[int]


class RecipeCoProductCreate(BaseModel):
    material_code: str
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("PC", max_length=5)
    cost_share_percent: Decimal = Field(Decimal("0"), ge=0, le=100)


class RecipeCoProductResponse(ORMModel):
    id: int
    material_code: str
    quantity: Decimal
    unit: str
    cost_share_percent: Decimal


class RecipeCreate(BaseModel):
    recipe_code: Optional[str] = Field(None, max_length=20,
        description="If omitted, auto-generated as RCP-XXXXXXX")
    material_code: str
    plant_code: str
    description: Optional[str] = None
    base_quantity: Decimal = Field(Decimal("1"), gt=0)
    base_unit: str = Field("PC", max_length=5)
    yield_percent: Decimal = Field(Decimal("100"), gt=0, le=100)
    valid_from: date = Field(default_factory=date.today)
    valid_to: date = date(2099, 12, 31)
    is_default: bool = False
    items: List[RecipeItemCreate] = Field(..., min_length=1)
    co_products: List[RecipeCoProductCreate] = []


class RecipeUpdate(BaseModel):
    description: Optional[str] = None
    base_quantity: Optional[Decimal] = None
    yield_percent: Optional[Decimal] = None
    valid_to: Optional[date] = None
    status: Optional[str] = None
    is_default: Optional[bool] = None


class RecipeResponse(ORMModel):
    id: int
    recipe_code: str
    material_code: str
    plant_code: str
    description: Optional[str]
    base_quantity: Decimal
    base_unit: str
    yield_percent: Decimal
    valid_from: date
    valid_to: date
    status: str
    version: int
    is_default: bool
    is_active: bool
    items: List[RecipeItemResponse]
    co_products: List[RecipeCoProductResponse]
    created_at: datetime
    updated_at: datetime


# ==================================================================
# Routing
# ==================================================================
class RoutingOperationCreate(BaseModel):
    description: str = Field(..., max_length=255)
    work_center_code: str
    setup_time_minutes: Decimal = Field(Decimal("0"), ge=0)
    machine_time_minutes: Decimal = Field(Decimal("0"), ge=0)
    labor_time_minutes: Decimal = Field(Decimal("0"), ge=0)
    yield_percent: Decimal = Field(Decimal("100"), gt=0, le=100)


class RoutingOperationResponse(ORMModel):
    id: int
    operation_no: int
    description: str
    work_center_code: str
    setup_time_minutes: Decimal
    machine_time_minutes: Decimal
    labor_time_minutes: Decimal
    yield_percent: Decimal


class RoutingCreate(BaseModel):
    routing_code: Optional[str] = None
    material_code: str
    plant_code: str
    description: Optional[str] = None
    base_quantity: Decimal = Field(Decimal("1"), gt=0)
    base_unit: str = Field("PC", max_length=5)
    valid_from: date = Field(default_factory=date.today)
    valid_to: date = date(2099, 12, 31)
    operations: List[RoutingOperationCreate] = Field(..., min_length=1)


class RoutingResponse(ORMModel):
    id: int
    routing_code: str
    material_code: str
    plant_code: str
    description: Optional[str]
    base_quantity: Decimal
    base_unit: str
    valid_from: date
    valid_to: date
    status: str
    is_active: bool
    operations: List[RoutingOperationResponse]
    created_at: datetime


# ==================================================================
# Production Version
# ==================================================================
class ProductionVersionCreate(BaseModel):
    version_code: Optional[str] = None
    material_code: str
    plant_code: str
    recipe_id: int
    routing_id: int
    valid_from: date = Field(default_factory=date.today)
    valid_to: date = date(2099, 12, 31)
    is_default: bool = False


class ProductionVersionResponse(ORMModel):
    id: int
    version_code: str
    material_code: str
    plant_code: str
    recipe_id: int
    routing_id: int
    valid_from: date
    valid_to: date
    is_default: bool
    is_active: bool


# ==================================================================
# BOM Explosion (multi-level)
# ==================================================================
class BomExplosionNode(BaseModel):
    """A single node in the multi-level BOM explosion tree."""
    level: int                                     # 0 = top, 1 = direct components, ...
    material_code: str
    description: Optional[str] = None
    quantity: Decimal                              # required quantity at this level
    unit: str
    is_phantom: bool = False
    is_purchased: bool                             # true: leaf (no recipe found)
    children: List["BomExplosionNode"] = []


BomExplosionNode.model_rebuild()


class BomExplosionResponse(BaseModel):
    material_code: str
    plant_code: str
    base_quantity: Decimal
    base_unit: str
    tree: BomExplosionNode


# ==================================================================
# Cost Component Split (Cost Rollup result)
# ==================================================================
class CostBreakdownItem(BaseModel):
    """One line in the cost breakdown JSON (per-component contribution)."""
    level: int
    material_code: str
    description: Optional[str] = None
    quantity: Decimal
    unit: str
    unit_cost: Decimal
    extended_cost: Decimal
    cost_type: str                                 # MATERIAL / LABOR / MACHINE / OVERHEAD


class CostComponentSplitResponse(ORMModel):
    id: int
    material_code: str
    plant_code: str
    production_version_code: Optional[str]
    raw_material_cost: Decimal
    labor_cost: Decimal
    machine_cost: Decimal
    overhead_cost: Decimal
    external_processing_cost: Decimal
    total_cost: Decimal
    currency: str
    base_unit: str
    valid_from: date
    valid_to: date
    breakdown: Optional[List[CostBreakdownItem]] = None


class CostRollupRequest(BaseModel):
    material_code: str
    plant_code: str
    production_version_code: Optional[str] = Field(
        None, description="If omitted, the default version is used")
    overhead_rate_percent: Optional[Decimal] = Field(
        None, ge=0, le=100,
        description="Override the overhead rate. Otherwise WorkCenter rates apply")
    save_result: bool = Field(True,
        description="Persist as CostComponentSplit record")


class CostComparisonRequest(BaseModel):
    """Compare cost of the same material across multiple plants
    (e.g. transfer pricing analysis)."""
    material_code: str
    plant_codes: List[str] = Field(..., min_length=2, max_length=10)


class CostComparisonRow(BaseModel):
    plant_code: str
    raw_material_cost: Decimal
    labor_cost: Decimal
    machine_cost: Decimal
    overhead_cost: Decimal
    total_cost: Decimal
    currency: str
    base_unit: str


class CostComparisonResponse(BaseModel):
    material_code: str
    rows: List[CostComparisonRow]


# ==================================================================
# BOM Compliance Snapshot (for AI_TradeManagement integration)
# ==================================================================
class BomComplianceComponent(BaseModel):
    """Per-component data sent to external compliance services."""
    level: int
    material_code: str
    description: Optional[str] = None
    quantity: Decimal
    unit: str
    # Trade-relevant attributes (read from Material master)
    hs_code: Optional[str] = None
    eccn: Optional[str] = None
    country_of_origin: Optional[str] = None
    fefta_judgment: Optional[str] = None


class BomComplianceSnapshotResponse(BaseModel):
    """Generic, vendor-neutral snapshot of a BOM's compliance-relevant data.

    This is the *interface* the ERP exposes. Any external service
    (AI_TradeManagement or otherwise) can consume this snapshot and
    perform its own analysis. The ERP does not embed any judgment logic.
    """
    material_code: str
    plant_code: str
    production_version_code: Optional[str] = None
    snapshot_taken_at: datetime
    # Top-level product attributes
    product_hs_code: Optional[str] = None
    product_eccn: Optional[str] = None
    product_fefta_judgment: Optional[str] = None
    # Flattened components across all BOM levels
    components: List[BomComplianceComponent]
