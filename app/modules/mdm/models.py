"""Master Data Management - SQLAlchemy models.

Phase 1 entities:
- Company        : 会社 (Company Code)
- Material       : 品目マスタ (HSコード/ECCN/該非判定情報を保持)
- BusinessPartner: 取引先マスタ (S/4HANA-style: Customer/Vendor統合)
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import MasterDataMixin


# ------------------------------------------------------------------
# Company (Company Code)
# ------------------------------------------------------------------
class Company(MasterDataMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint("client_id", "company_code", name="uq_companies_client_code"),
    )

    company_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)         # ISO 3166-1 alpha-2
    currency: Mapped[str] = mapped_column(String(3), nullable=False)        # ISO 4217
    fiscal_year_variant: Mapped[str] = mapped_column(String(2), default="K4")  # K4 = Jan-Dec


# ------------------------------------------------------------------
# Material
# ------------------------------------------------------------------
class Material(MasterDataMixin, Base):
    __tablename__ = "materials"
    __table_args__ = (
        UniqueConstraint("client_id", "material_code", name="uq_materials_client_code"),
    )

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    # Material classification
    material_type: Mapped[str] = mapped_column(String(10), default="FERT")
    # FERT=完成品, HALB=半製品, ROH=原材料, HAWA=商品

    base_unit: Mapped[str] = mapped_column(String(5), default="PC")
    weight_kg: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))

    # Pricing
    standard_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 2))
    currency: Mapped[Optional[str]] = mapped_column(String(3))

    # Trade compliance fields (synced from AI_TradeManagement)
    hs_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    eccn: Mapped[Optional[str]] = mapped_column(String(20))
    fefta_judgment: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    # UNKNOWN / NOT_APPLICABLE / APPLICABLE / PENDING
    country_of_origin: Mapped[Optional[str]] = mapped_column(String(2))
    last_compliance_check_at: Mapped[Optional[str]] = mapped_column(String(30))


# ------------------------------------------------------------------
# Business Partner (Customer / Vendor unified)
# ------------------------------------------------------------------
class BusinessPartner(MasterDataMixin, Base):
    __tablename__ = "business_partners"
    __table_args__ = (
        UniqueConstraint("client_id", "bp_code", name="uq_business_partners_client_code"),
    )

    bp_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    bp_type: Mapped[str] = mapped_column(String(10), default="ORG")  # ORG / PERSON
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)

    # Roles - simple comma-separated string for SQLite friendliness.
    # In production (Postgres), prefer ARRAY or a separate role table.
    roles: Mapped[str] = mapped_column(String(100), default="CUSTOMER")
    # Possible values: CUSTOMER, VENDOR, EMPLOYEE (joined by ',')

    # Common contact info
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    address_line1: Mapped[Optional[str]] = mapped_column(String(255))
    address_line2: Mapped[Optional[str]] = mapped_column(String(255))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    postal_code: Mapped[Optional[str]] = mapped_column(String(20))

    # Customer-specific
    credit_limit: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(20))    # NET30, NET60...
    currency: Mapped[Optional[str]] = mapped_column(String(3))

    # Sanctions / denied party flag (synced from AI_TradeManagement)
    is_denied_party: Mapped[bool] = mapped_column(Boolean, default=False)

    def has_role(self, role: str) -> bool:
        return role in (self.roles or "").split(",")
