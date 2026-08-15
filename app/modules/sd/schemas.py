"""Sales & Distribution - Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.shared.base_schemas import AuditFields, ORMModel


# ==================================================================
# Sales Order Item
# ==================================================================
class SalesOrderItemCreate(BaseModel):
    material_code: str
    description: Optional[str] = None
    quantity: Decimal = Field(..., gt=0)
    unit: str = Field("PC", max_length=5)
    unit_price: Decimal = Field(..., ge=0)
    plant_code: Optional[str] = None


class SalesOrderItemResponse(ORMModel):
    id: int
    item_no: int
    material_code: str
    description: Optional[str]
    quantity: Decimal
    unit: str
    unit_price: Decimal
    net_amount: Decimal
    plant_code: Optional[str]


# ==================================================================
# Sales Order
# ==================================================================
class EndUserCreate(BaseModel):
    """End-user BP to be created automatically when CRM sends end_user on contract (IF-25)."""
    name: str
    country: str = Field(..., min_length=2, max_length=2)
    address: Optional[str] = None
    crm_account_id: Optional[str] = None


class SalesOrderCreate(BaseModel):
    sales_org_code: Optional[str] = None
    customer_code: str = Field(..., examples=["BP-0000001"])
    customer_po_number: Optional[str] = None
    document_date: date = Field(default_factory=date.today)
    requested_delivery_date: Optional[date] = None
    incoterms: Optional[str] = Field(None, examples=["FOB", "CIF", "EXW", "DDP"])
    payment_terms: Optional[str] = Field(None, examples=["NET30", "NET60"])
    currency: str = Field("USD", min_length=3, max_length=3)
    items: List[SalesOrderItemCreate] = Field(..., min_length=1)

    skip_export_check: bool = Field(False,
        description="If true, do not call AI_TradeManagement export-check on create")

    # CRM integration fields (IF-25)
    crm_contract_id: Optional[str] = None
    crm_engagement_id: Optional[str] = None
    aitm_transaction_id: Optional[str] = Field(None,
        description="Existing AI_TM transaction ID sent by CRM (IF-25). Links to existing review instead of creating new one.")
    end_user: Optional[EndUserCreate] = Field(None,
        description="End-user BP to auto-create with auto_screen=true")
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None


class SalesOrderUpdate(BaseModel):
    customer_po_number: Optional[str] = None
    requested_delivery_date: Optional[date] = None
    incoterms: Optional[str] = None
    payment_terms: Optional[str] = None
    status: Optional[str] = None


class SalesOrderResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    sales_org_code: Optional[str]
    customer_code: str
    customer_po_number: Optional[str]
    requested_delivery_date: Optional[date]
    incoterms: Optional[str]
    payment_terms: Optional[str]
    currency: str
    total_amount: Decimal
    export_check_status: str
    export_check_ref: Optional[str]
    export_check_message: Optional[str]
    # CRM integration fields
    crm_contract_id: Optional[str] = None
    crm_engagement_id: Optional[str] = None
    aitm_transaction_id: Optional[str] = None
    aitm_allocation_id: Optional[str] = None
    end_user_bp_code: Optional[str] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    items: List[SalesOrderItemResponse]
    created_at: datetime
    updated_at: datetime


# ==================================================================
# Delivery
# ==================================================================
class DeliveryItemCreate(BaseModel):
    so_item_id: int
    quantity: Decimal = Field(..., gt=0)


class DeliveryCreate(BaseModel):
    sales_order_id: int
    document_date: date = Field(default_factory=date.today)
    plant_code: Optional[str] = None
    actual_delivery_date: Optional[date] = None
    items: Optional[List[DeliveryItemCreate]] = Field(
        None,
        description="If omitted, all SO items are delivered in full",
    )


class DeliveryItemResponse(ORMModel):
    id: int
    item_no: int
    so_item_id: Optional[int]
    material_code: str
    quantity: Decimal
    unit: str


class DeliveryResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    sales_order_id: int
    plant_code: Optional[str]
    actual_delivery_date: Optional[date]
    aitm_case_no: Optional[str]
    aitm_approval_status: Optional[str]
    items: List[DeliveryItemResponse]
    created_at: datetime


# ==================================================================
# Billing
# ==================================================================
class BillingCreate(BaseModel):
    delivery_id: int
    document_date: date = Field(default_factory=date.today)
    payment_terms: Optional[str] = None
    tax_rate_percent: Decimal = Field(Decimal("0"), ge=0, le=100)


class BillingItemResponse(ORMModel):
    id: int
    item_no: int
    material_code: str
    quantity: Decimal
    unit_price: Decimal
    net_amount: Decimal


class BillingResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    status: str
    customer_code: str
    sales_order_id: Optional[int]
    delivery_id: Optional[int]
    currency: str
    net_amount: Decimal
    tax_amount: Decimal
    gross_amount: Decimal
    payment_terms: Optional[str]
    aitm_case_no: Optional[str]
    items: List[BillingItemResponse]
    created_at: datetime
