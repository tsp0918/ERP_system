"""Master Data Management - Pydantic schemas."""
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.shared.base_schemas import AuditFields, ORMModel


# ==================================================================
# Company
# ==================================================================
class CompanyBase(BaseModel):
    company_code: str = Field(..., max_length=10, examples=["1000"])
    name: str = Field(..., max_length=255)
    country: str = Field(..., min_length=2, max_length=2, examples=["JP"])
    currency: str = Field(..., min_length=3, max_length=3, examples=["JPY"])
    fiscal_year_variant: str = Field("K4", max_length=2)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    currency: Optional[str] = None
    fiscal_year_variant: Optional[str] = None
    is_active: Optional[bool] = None


class CompanyResponse(CompanyBase, AuditFields):
    id: int
    is_active: bool


# ==================================================================
# Material
# ==================================================================
class MaterialBase(BaseModel):
    description: str = Field(..., max_length=255)
    material_type: str = Field("FERT", examples=["FERT", "HALB", "ROH", "HAWA"])
    base_unit: str = Field("PC", max_length=5)
    weight_kg: Optional[Decimal] = None
    standard_price: Optional[Decimal] = None
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    hs_code: Optional[str] = Field(None, max_length=20)
    eccn: Optional[str] = Field(None, max_length=20)
    country_of_origin: Optional[str] = Field(None, min_length=2, max_length=2)


class MaterialCreate(MaterialBase):
    material_code: Optional[str] = Field(None, max_length=20,
        description="If omitted, auto-generated as MAT-XXXXXXX")
    # If true, ERP will call AI_TradeManagement to estimate HS / FEFTA
    auto_classify: bool = Field(True,
        description="Trigger AI_TradeManagement classification on create")


class MaterialUpdate(BaseModel):
    description: Optional[str] = None
    material_type: Optional[str] = None
    base_unit: Optional[str] = None
    weight_kg: Optional[Decimal] = None
    standard_price: Optional[Decimal] = None
    currency: Optional[str] = None
    hs_code: Optional[str] = None
    eccn: Optional[str] = None
    fefta_judgment: Optional[str] = None
    country_of_origin: Optional[str] = None
    is_active: Optional[bool] = None


class MaterialResponse(MaterialBase, AuditFields):
    id: int
    material_code: str
    fefta_judgment: str
    last_compliance_check_at: Optional[str] = None
    is_active: bool


# ==================================================================
# Business Partner
# ==================================================================
class BusinessPartnerBase(BaseModel):
    bp_type: str = Field("ORG", examples=["ORG", "PERSON"])
    name: str = Field(..., max_length=255)
    country: str = Field(..., min_length=2, max_length=2)
    roles: str = Field("CUSTOMER",
        description="Comma-separated. Values: CUSTOMER, VENDOR, EMPLOYEE",
        examples=["CUSTOMER", "VENDOR", "CUSTOMER,VENDOR"])
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    payment_terms: Optional[str] = Field(None, examples=["NET30", "NET60"])
    currency: Optional[str] = Field(None, min_length=3, max_length=3)


class BusinessPartnerCreate(BusinessPartnerBase):
    bp_code: Optional[str] = Field(None,
        description="If omitted, auto-generated as BP-XXXXXXX")
    auto_screen: bool = Field(True,
        description="Trigger denied-party screening via AI_TradeManagement")


class BusinessPartnerUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    roles: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address_line1: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    credit_limit: Optional[Decimal] = None
    payment_terms: Optional[str] = None
    currency: Optional[str] = None
    is_denied_party: Optional[bool] = None
    is_active: Optional[bool] = None


class BusinessPartnerResponse(BusinessPartnerBase, AuditFields):
    id: int
    bp_code: str
    is_denied_party: bool
    screening_status: str = "UNSCREENED"
    denial_list: Optional[str] = None
    denial_reason: Optional[str] = None
    last_screened_at: Optional[str] = None
    fifty_pct_rule_triggered: bool = False
    parent_sanctioned_entity: Optional[str] = None
    ai_tm_screening_ref: Optional[str] = None
    is_active: bool


# ==================================================================
# Material Plant (MRP/Procurement view per plant)
# ==================================================================
class MaterialPlantBase(BaseModel):
    material_code: str = Field(..., max_length=20)
    plant_code: str = Field(..., max_length=10)
    procurement_type: str = Field("F", max_length=2,
        description="E=In-house / F=External / X=Both")
    special_procurement_type: Optional[str] = Field(None, max_length=5)
    mrp_type: str = Field("ND", max_length=5,
        description="ND=None / PD=MRP / VB=Reorder point")
    reorder_point: Optional[Decimal] = None
    safety_stock: Optional[Decimal] = None
    max_stock_level: Optional[Decimal] = None
    lot_size_key: str = Field("EX", max_length=5,
        description="EX=Exact / FX=Fixed / HB=Replenishment")
    fixed_lot_size: Optional[Decimal] = None
    min_lot_size: Optional[Decimal] = None
    max_lot_size: Optional[Decimal] = None
    rounding_value: Optional[Decimal] = None
    planned_delivery_days: int = Field(0, ge=0)
    in_house_production_days: int = Field(0, ge=0)
    goods_receipt_processing_days: int = Field(0, ge=0)
    storage_location: Optional[str] = Field(None, max_length=10)
    stock_unit: str = Field("PC", max_length=5)


class MaterialPlantCreate(MaterialPlantBase):
    pass


class MaterialPlantUpdate(BaseModel):
    procurement_type: Optional[str] = None
    special_procurement_type: Optional[str] = None
    mrp_type: Optional[str] = None
    reorder_point: Optional[Decimal] = None
    safety_stock: Optional[Decimal] = None
    max_stock_level: Optional[Decimal] = None
    lot_size_key: Optional[str] = None
    fixed_lot_size: Optional[Decimal] = None
    min_lot_size: Optional[Decimal] = None
    max_lot_size: Optional[Decimal] = None
    rounding_value: Optional[Decimal] = None
    planned_delivery_days: Optional[int] = None
    in_house_production_days: Optional[int] = None
    goods_receipt_processing_days: Optional[int] = None
    storage_location: Optional[str] = None
    stock_unit: Optional[str] = None
    is_active: Optional[bool] = None


class MaterialPlantResponse(MaterialPlantBase, AuditFields):
    id: int
    is_active: bool
