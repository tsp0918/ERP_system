"""GTS - Pydantic schemas for Export Declarations and AI_TM link tables."""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.shared.base_schemas import ORMModel


# ==================================================================
# Export Declaration
# ==================================================================
class ExportDeclarationBase(BaseModel):
    delivery_id: Optional[int] = None
    sales_order_id: Optional[int] = None

    ai_tm_transaction_id: Optional[str] = Field(None, max_length=50)
    ai_tm_license_number: Optional[str] = Field(None, max_length=50)

    declaration_number: Optional[str] = Field(None, max_length=50)
    license_type: Optional[str] = Field(None, max_length=20,
        description="individual / general / blanket")
    license_authority: Optional[str] = Field(None, max_length=20,
        description="METI / BIS / DDTC / EU_COMPETENT_AUTH")
    license_issued_date: Optional[date] = None
    license_expiry_date: Optional[date] = None

    destination_country: Optional[str] = Field(None, min_length=2, max_length=2)
    material_code: Optional[str] = Field(None, max_length=20)
    hs_code: Optional[str] = Field(None, max_length=20)
    eccn: Optional[str] = Field(None, max_length=20)
    quantity: Optional[Decimal] = Field(None, ge=0)
    quantity_unit: Optional[str] = Field(None, max_length=5)
    declared_value_usd: Optional[Decimal] = Field(None, ge=0)

    remarks: Optional[str] = None


class ExportDeclarationCreate(ExportDeclarationBase):
    pass


class ExportDeclarationUpdate(BaseModel):
    ai_tm_transaction_id: Optional[str] = None
    ai_tm_license_number: Optional[str] = None
    declaration_number: Optional[str] = None
    license_type: Optional[str] = None
    license_authority: Optional[str] = None
    license_issued_date: Optional[date] = None
    license_expiry_date: Optional[date] = None
    destination_country: Optional[str] = None
    material_code: Optional[str] = None
    hs_code: Optional[str] = None
    eccn: Optional[str] = None
    quantity: Optional[Decimal] = None
    quantity_unit: Optional[str] = None
    declared_value_usd: Optional[Decimal] = None
    status: Optional[str] = Field(None,
        description="DRAFT / SUBMITTED / APPROVED / REJECTED / CANCELLED")
    remarks: Optional[str] = None


class ExportDeclarationResponse(ExportDeclarationBase, ORMModel):
    id: int
    client_id: str
    status: str
    created_at: datetime
    updated_at: datetime
