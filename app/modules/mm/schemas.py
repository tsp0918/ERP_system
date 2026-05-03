"""Materials Management - Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

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
