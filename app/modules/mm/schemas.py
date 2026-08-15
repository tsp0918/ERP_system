"""Materials Management - Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from app.shared.base_schemas import AuditFields

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMModel


# ==================================================================
# Purchase Requisition
# ==================================================================
class PurchaseRequisitionItemCreate(BaseModel):
    material_code: str
    description: Optional[str] = None
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("PC", max_length=5)
    suggested_vendor_code: Optional[str] = None
    estimated_unit_price: Optional[Decimal] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    plant_code: Optional[str] = None
    requested_delivery_date: Optional[date] = None


class PurchaseRequisitionItemResponse(ORMModel):
    id: int
    item_no: int
    material_code: str
    description: Optional[str]
    quantity: Decimal
    unit: str
    suggested_vendor_code: Optional[str]
    estimated_unit_price: Optional[Decimal]
    currency: Optional[str]
    plant_code: Optional[str]
    requested_delivery_date: Optional[date]
    ordered_quantity: Decimal


class PurchaseRequisitionCreate(BaseModel):
    plant_code: Optional[str] = None
    requested_by: Optional[str] = None
    document_date: date = Field(default_factory=date.today)
    requested_delivery_date: Optional[date] = None
    source_type: str = Field("MANUAL",
        description="MANUAL / MRP / PROCESS_ORDER / SALES_ORDER")
    source_reference: Optional[str] = None
    items: List[PurchaseRequisitionItemCreate] = Field(..., min_length=1)


class PurchaseRequisitionResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    plant_code: Optional[str]
    requested_by: Optional[str]
    requested_delivery_date: Optional[date]
    source_type: str
    source_reference: Optional[str]
    items: List[PurchaseRequisitionItemResponse]
    created_at: datetime


# ==================================================================
# Purchase Order
# ==================================================================
class PurchaseOrderItemCreate(BaseModel):
    material_code: str
    description: Optional[str] = None
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("PC", max_length=5)
    unit_price: Decimal = Field(..., ge=0)
    plant_code: Optional[str] = None
    pr_item_id: Optional[int] = None


class PurchaseOrderItemResponse(ORMModel):
    id: int
    item_no: int
    pr_item_id: Optional[int]
    material_code: str
    description: Optional[str]
    quantity: Decimal
    unit: str
    unit_price: Decimal
    net_amount: Decimal
    plant_code: Optional[str]
    received_quantity: Decimal
    invoiced_quantity: Decimal


class PurchaseOrderCreate(BaseModel):
    purchasing_org_code: Optional[str] = None
    plant_code: Optional[str] = None
    vendor_code: str
    document_date: date = Field(default_factory=date.today)
    requested_delivery_date: Optional[date] = None
    incoterms: Optional[str] = Field(None, examples=["FOB", "CIF", "EXW", "DDP"])
    payment_terms: Optional[str] = None
    currency: str = Field("JPY", min_length=3, max_length=3)
    items: List[PurchaseOrderItemCreate] = Field(..., min_length=1)


class PurchaseOrderResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    purchasing_org_code: Optional[str]
    plant_code: Optional[str]
    vendor_code: str
    requested_delivery_date: Optional[date]
    incoterms: Optional[str]
    payment_terms: Optional[str]
    currency: str
    total_amount: Decimal
    items: List[PurchaseOrderItemResponse]
    created_at: datetime


class PurchaseOrderFromPRRequest(BaseModel):
    """PR から PO を一括生成するためのリクエスト。

    省略時はPR内の `suggested_vendor_code` でグルーピングし、
    ベンダーごとに別の PO を生成する。"""
    purchase_requisition_id: int
    vendor_code: Optional[str] = Field(None,
        description="If omitted, group by suggested_vendor_code in PR items")
    purchasing_org_code: Optional[str] = None
    payment_terms: Optional[str] = None
    incoterms: Optional[str] = None


# ==================================================================
# Goods Receipt
# ==================================================================
class GoodsReceiptItemCreate(BaseModel):
    po_item_id: int
    quantity: Decimal = Field(..., gt=0)
    batch_code: Optional[str] = None
    storage_location: Optional[str] = None


class GoodsReceiptItemResponse(ORMModel):
    id: int
    item_no: int
    po_item_id: int
    material_code: str
    quantity: Decimal
    unit: str
    batch_code: Optional[str]
    storage_location: Optional[str]


class GoodsReceiptCreate(BaseModel):
    purchase_order_id: int
    plant_code: Optional[str] = None
    posting_date: date = Field(default_factory=date.today)
    vendor_delivery_note: Optional[str] = None
    items: Optional[List[GoodsReceiptItemCreate]] = Field(
        None,
        description="If omitted, full open quantity of each PO item is received",
    )


class GoodsReceiptResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    purchase_order_id: int
    plant_code: Optional[str]
    posting_date: date
    vendor_delivery_note: Optional[str]
    items: List[GoodsReceiptItemResponse]
    created_at: datetime


# ==================================================================
# Invoice Receipt
# ==================================================================
class InvoiceReceiptItemCreate(BaseModel):
    po_item_id: int
    quantity: Decimal = Field(..., gt=0)
    unit_price: Decimal = Field(..., ge=0)


class InvoiceReceiptItemResponse(ORMModel):
    id: int
    item_no: int
    po_item_id: int
    material_code: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    net_amount: Decimal


class InvoiceReceiptCreate(BaseModel):
    purchase_order_id: int
    vendor_invoice_number: str
    document_date: date = Field(default_factory=date.today)
    invoice_date: date = Field(default_factory=date.today)
    posting_date: date = Field(default_factory=date.today)
    tax_rate_percent: Decimal = Field(Decimal("0"), ge=0, le=100)
    items: List[InvoiceReceiptItemCreate] = Field(..., min_length=1)


class InvoiceReceiptResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    purchase_order_id: int
    vendor_code: str
    vendor_invoice_number: str
    invoice_date: date
    posting_date: date
    currency: str
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    match_status: str
    match_message: Optional[str]
    items: List[InvoiceReceiptItemResponse]
    created_at: datetime


# ==================================================================
# Purchasing Info Record (EINA/EINP equivalent)
# ==================================================================
class PurchasingInfoRecordBase(BaseModel):
    material_code: str = Field(..., max_length=20)
    vendor_code: str = Field(..., max_length=20)
    plant_code: Optional[str] = Field(None, max_length=10,
        description="NULL = applies to all plants")
    unit_price: Decimal = Field(..., ge=0)
    price_unit: Decimal = Field(Decimal("1"), gt=0,
        description="Price per this quantity (e.g. 100 for price per 100 units)")
    currency: str = Field("JPY", min_length=3, max_length=3)
    price_valid_from: date = Field(default_factory=date.today)
    price_valid_to: date = date(2099, 12, 31)
    min_order_quantity: Optional[Decimal] = Field(None, ge=0)
    max_order_quantity: Optional[Decimal] = Field(None, ge=0)
    order_unit: str = Field("PC", max_length=5)
    planned_delivery_days: int = Field(0, ge=0)
    incoterms: Optional[str] = Field(None, max_length=10,
        examples=["FOB", "CIF", "EXW", "DDP"])
    payment_terms: Optional[str] = Field(None, max_length=20)
    country_of_origin: Optional[str] = Field(None, min_length=2, max_length=2)
    vendor_material_code: Optional[str] = Field(None, max_length=50)
    vendor_material_name: Optional[str] = Field(None, max_length=255)
    is_preferred: bool = False
    vendor_eccn: Optional[str] = Field(None, max_length=20)


class PurchasingInfoRecordCreate(PurchasingInfoRecordBase):
    pass


class PurchasingInfoRecordUpdate(BaseModel):
    unit_price: Optional[Decimal] = None
    price_unit: Optional[Decimal] = None
    currency: Optional[str] = None
    price_valid_from: Optional[date] = None
    price_valid_to: Optional[date] = None
    min_order_quantity: Optional[Decimal] = None
    max_order_quantity: Optional[Decimal] = None
    planned_delivery_days: Optional[int] = None
    incoterms: Optional[str] = None
    payment_terms: Optional[str] = None
    country_of_origin: Optional[str] = None
    vendor_material_code: Optional[str] = None
    vendor_material_name: Optional[str] = None
    is_preferred: Optional[bool] = None
    vendor_eccn: Optional[str] = None
    is_active: Optional[bool] = None


class PurchasingInfoRecordResponse(PurchasingInfoRecordBase, AuditFields):
    id: int
    is_active: bool


# ==================================================================
# Source List (EORD equivalent)
# ==================================================================
class SourceListBase(BaseModel):
    material_code: str = Field(..., max_length=20)
    plant_code: str = Field(..., max_length=10)
    vendor_code: str = Field(..., max_length=20)
    valid_from: date = Field(default_factory=date.today)
    valid_to: date = date(2099, 12, 31)
    priority: int = Field(1, ge=1)
    quota_percentage: Optional[Decimal] = Field(None, ge=0, le=100,
        description="Quota-based sourcing share (0-100%)")
    is_blocked: bool = False
    is_fixed: bool = Field(False,
        description="Fixed source: MRP always uses this vendor")
    order_type: str = Field("PO", max_length=10,
        description="PO=Purchase Order / OA=Outline Agreement")
    pir_id: Optional[int] = Field(None,
        description="FK to PurchasingInfoRecord")


class SourceListCreate(SourceListBase):
    pass


class SourceListUpdate(BaseModel):
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    priority: Optional[int] = None
    quota_percentage: Optional[Decimal] = None
    is_blocked: Optional[bool] = None
    is_fixed: Optional[bool] = None
    order_type: Optional[str] = None
    pir_id: Optional[int] = None
    is_active: Optional[bool] = None


class SourceListResponse(SourceListBase, AuditFields):
    id: int
    is_active: bool


# ==================================================================
# Stock Balance (MARD equivalent)
# ==================================================================
class StockBalanceBase(BaseModel):
    material_code: str = Field(..., max_length=20)
    plant_code: str = Field(..., max_length=10)
    storage_location: str = Field("0001", max_length=10)
    unrestricted_qty: Decimal = Field(Decimal("0"), ge=0)
    quality_inspection_qty: Decimal = Field(Decimal("0"), ge=0)
    blocked_qty: Decimal = Field(Decimal("0"), ge=0)
    in_transit_qty: Decimal = Field(Decimal("0"), ge=0)
    reserved_qty: Decimal = Field(Decimal("0"), ge=0)
    stock_unit: str = Field("PC", max_length=5)


class StockBalanceCreate(StockBalanceBase):
    pass


class StockBalanceUpdate(BaseModel):
    unrestricted_qty: Optional[Decimal] = None
    quality_inspection_qty: Optional[Decimal] = None
    blocked_qty: Optional[Decimal] = None
    in_transit_qty: Optional[Decimal] = None
    reserved_qty: Optional[Decimal] = None
    stock_unit: Optional[str] = None
    is_active: Optional[bool] = None


class StockBalanceResponse(StockBalanceBase, AuditFields):
    id: int
    available_qty: Decimal
    is_active: bool


# ==================================================================
# Reservation (RESB equivalent)
# ==================================================================
class ReservationBase(BaseModel):
    material_code: str = Field(..., max_length=20)
    plant_code: str = Field(..., max_length=10)
    storage_location: Optional[str] = Field(None, max_length=10)
    reservation_type: str = Field("MANUAL", max_length=10,
        description="SD=Sales / PP=Production / MANUAL")
    source_document_type: Optional[str] = Field(None, max_length=20)
    source_document_id: Optional[int] = None
    source_document_item: Optional[int] = None
    required_qty: Decimal = Field(..., gt=0)
    confirmed_qty: Optional[Decimal] = Field(None, ge=0)
    requirement_date: Optional[date] = None


class ReservationCreate(ReservationBase):
    pass


class ReservationUpdate(BaseModel):
    confirmed_qty: Optional[Decimal] = None
    requirement_date: Optional[date] = None
    status: Optional[str] = Field(None,
        description="OPEN / PARTIALLY_WITHDRAWN / FULLY_WITHDRAWN / CANCELLED")
    is_active: Optional[bool] = None


class ReservationResponse(ReservationBase, AuditFields):
    id: int
    reservation_number: str
    withdrawn_qty: Decimal
    status: str
    is_active: bool
