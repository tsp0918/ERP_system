"""Production Planning - Execution layer schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMModel


# ==================================================================
# Process Order
# ==================================================================
class ProcessOrderComponentResponse(ORMModel):
    id: int
    item_no: int
    material_code: str
    description: Optional[str]
    planned_quantity: Decimal
    issued_quantity: Decimal
    unit: str
    operation_no: Optional[int]


class ProcessOrderOperationResponse(ORMModel):
    id: int
    operation_no: int
    description: str
    work_center_code: str
    planned_machine_minutes: Decimal
    actual_machine_minutes: Decimal
    planned_labor_minutes: Decimal
    actual_labor_minutes: Decimal
    confirmation_count: int


class ProcessOrderCreate(BaseModel):
    """Create a process order from a Production Version.

    Components and operations are auto-populated by exploding the
    referenced ProductionVersion's recipe and routing, scaled to
    target_quantity. The user supplies only the header.
    """
    material_code: str
    plant_code: str
    target_quantity: Decimal = Field(..., gt=0)
    target_unit: Optional[str] = None
    document_date: date = Field(default_factory=date.today)
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    production_version_code: Optional[str] = Field(
        None, description="If omitted, default version for material+plant is used")


class ProcessOrderResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    material_code: str
    plant_code: str
    production_version_code: str
    target_quantity: Decimal
    target_unit: str
    actual_quantity: Decimal
    scrapped_quantity: Decimal
    scheduled_start: Optional[datetime]
    scheduled_end: Optional[datetime]
    actual_start: Optional[datetime]
    actual_end: Optional[datetime]
    components: List[ProcessOrderComponentResponse]
    operations: List[ProcessOrderOperationResponse]
    created_at: datetime


# ==================================================================
# Goods Issue (consumption against a process order)
# ==================================================================
class GoodsIssueLine(BaseModel):
    """One material consumption against a process order."""
    component_id: int = Field(..., description="ProcessOrderComponent.id")
    batch_code: str = Field(..., description="Source batch to consume from")
    quantity: Decimal = Field(..., gt=0)


class GoodsIssueRequest(BaseModel):
    process_order_id: int
    posting_date: date = Field(default_factory=date.today)
    lines: List[GoodsIssueLine] = Field(..., min_length=1)


class GoodsIssueLineResult(BaseModel):
    component_id: int
    batch_code: str
    consumed_quantity: Decimal
    remaining_in_batch: Decimal


class GoodsIssueResponse(BaseModel):
    process_order_id: int
    process_order_number: str
    posted_at: datetime
    lines: List[GoodsIssueLineResult]


# ==================================================================
# Operation Confirmation (actual minutes worked)
# ==================================================================
class OperationConfirmRequest(BaseModel):
    operation_id: int
    actual_machine_minutes: Decimal = Field(..., ge=0)
    actual_labor_minutes: Decimal = Field(..., ge=0)
    posting_date: date = Field(default_factory=date.today)


# ==================================================================
# Goods Receipt for Production (output -> creates Batch)
# ==================================================================
class ProductionGoodsReceiptRequest(BaseModel):
    process_order_id: int
    quantity: Decimal = Field(..., gt=0)
    scrapped_quantity: Decimal = Field(Decimal("0"), ge=0)
    batch_code: Optional[str] = Field(
        None, description="If omitted, auto-generated as LOT-YYYYMMDD-XXX")
    storage_location: Optional[str] = None
    posting_date: date = Field(default_factory=date.today)


class ProductionGoodsReceiptResponse(BaseModel):
    process_order_id: int
    process_order_number: str
    new_batch_code: str
    quantity: Decimal
    unit: str
    parent_batches: List[str]
    posted_at: datetime


# ==================================================================
# Batch
# ==================================================================
class BatchCreate(BaseModel):
    """Create a batch directly. Used for opening balances or manual receipts.
    Goods Receipt against a PO normally creates batches automatically."""
    batch_code: str = Field(..., max_length=50)
    material_code: str
    plant_code: str
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("PC", max_length=5)
    storage_location: Optional[str] = None
    source_type: str = Field("OPENING_BALANCE")
    source_reference: Optional[str] = None
    country_of_origin: Optional[str] = Field(None, min_length=2, max_length=2)
    vendor_code: Optional[str] = None
    quality_status: str = Field("RELEASED")
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None


class BatchResponse(ORMModel):
    id: int
    batch_code: str
    material_code: str
    plant_code: str
    storage_location: Optional[str]
    quantity: Decimal
    unit: str
    initial_quantity: Decimal
    source_type: str
    source_reference: Optional[str]
    country_of_origin: Optional[str]
    vendor_code: Optional[str]
    quality_status: str
    production_date: Optional[date]
    expiry_date: Optional[date]
    created_at: datetime


# ==================================================================
# Genealogy
# ==================================================================
class GenealogyNode(BaseModel):
    """A node in the genealogy tree (used for both forward and backward views)."""
    batch_code: str
    material_code: str
    quantity: Decimal
    unit: str
    country_of_origin: Optional[str] = None
    vendor_code: Optional[str] = None
    quality_status: str
    source_type: str
    source_reference: Optional[str] = None
    consumed_quantity: Optional[Decimal] = None
    consumed_in_order: Optional[str] = None
    children: List["GenealogyNode"] = []


GenealogyNode.model_rebuild()


class GenealogyResponse(BaseModel):
    direction: str                 # "BACKWARD" (raw->this) or "FORWARD" (this->finished)
    root_batch_code: str
    tree: GenealogyNode
