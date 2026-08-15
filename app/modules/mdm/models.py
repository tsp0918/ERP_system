"""Master Data Management - SQLAlchemy models.

Phase 1 entities:
- Company        : 会社 (Company Code)
- Material       : 品目マスタ (HSコード/ECCN/該非判定情報を保持)
- BusinessPartner: 取引先マスタ (S/4HANA-style: Customer/Vendor統合)
- MaterialPlant  : 品目プラントビュー (調達タイプ・MRPパラメータ)
"""
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, UniqueConstraint
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

    # Sanctions / denied party screening (synced from AI_TradeManagement)
    is_denied_party: Mapped[bool] = mapped_column(Boolean, default=False)
    # UNSCREENED / CLEARED / FLAGGED / BLOCKED
    screening_status: Mapped[str] = mapped_column(String(20), default="UNSCREENED")
    denial_list: Mapped[Optional[str]] = mapped_column(String(100))   # e.g. "BIS_ENTITY,OFAC_SDN"
    denial_reason: Mapped[Optional[str]] = mapped_column(String(500))
    last_screened_at: Mapped[Optional[str]] = mapped_column(String(30))
    # 50% Rule: parent sanctioned entity name
    parent_sanctioned_entity: Mapped[Optional[str]] = mapped_column(String(255))
    fifty_pct_rule_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_tm_screening_ref: Mapped[Optional[str]] = mapped_column(String(100))

    # CRM / Commerce check integration fields (Phase 1)
    aitm_party_id: Mapped[Optional[str]] = mapped_column(String(36))
    crm_account_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    corporate_number: Mapped[Optional[str]] = mapped_column(String(20))
    representative_name: Mapped[Optional[str]] = mapped_column(String(200))
    # Commerce check results — separate from sanctions screening (screening_status / is_denied_party)
    credit_check_status: Mapped[Optional[str]] = mapped_column(String(20))   # OK / NG / PENDING
    antisocial_check_status: Mapped[Optional[str]] = mapped_column(String(20))
    credit_checked_at: Mapped[Optional[str]] = mapped_column(String(30))
    antisocial_checked_at: Mapped[Optional[str]] = mapped_column(String(30))

    def has_role(self, role: str) -> bool:
        return role in (self.roles or "").split(",")


# ------------------------------------------------------------------
# MaterialPlant (品目プラントビュー)
# ------------------------------------------------------------------
class MaterialPlant(MasterDataMixin, Base):
    """品目 × プラントの組み合わせマスタ。SAP の MRP1/MRP2/購買ビュー相当。

    調達タイプ・リードタイム・MRP パラメータ・最小在庫などを管理する。
    Material.material_code + plant_code の複合ユニーク制約。
    """
    __tablename__ = "material_plants"
    __table_args__ = (
        UniqueConstraint("client_id", "material_code", "plant_code",
                         name="uq_material_plants_client_mat_plant"),
    )

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)

    # 調達タイプ (SAP: MRP2 ビュー)
    procurement_type: Mapped[str] = mapped_column(String(2), default="F")
    # E=自社製造 / F=外部調達 / X=両方

    special_procurement_type: Mapped[Optional[str]] = mapped_column(String(5))
    # 30=外注加工, 40=別プラントから移送, 50=サブコントラクト等

    # MRP パラメータ
    mrp_type: Mapped[str] = mapped_column(String(5), default="ND")
    # ND=MRPなし / PD=需要量計画 / VB=再発注点計画

    reorder_point: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    safety_stock: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    max_stock_level: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))

    # ロットサイズ
    lot_size_key: Mapped[str] = mapped_column(String(5), default="EX")
    # EX=正確なロット / FX=固定ロット / HB=補充までの期間
    fixed_lot_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    min_lot_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    max_lot_size: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    rounding_value: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))

    # リードタイム (調達・製造)
    planned_delivery_days: Mapped[int] = mapped_column(Integer, default=0)
    # 外部調達: 発注〜入庫までの日数
    in_house_production_days: Mapped[int] = mapped_column(Integer, default=0)
    # 自社製造: 製造リードタイム日数
    goods_receipt_processing_days: Mapped[int] = mapped_column(Integer, default=0)

    # 在庫管理
    storage_location: Mapped[Optional[str]] = mapped_column(String(10))
    stock_unit: Mapped[str] = mapped_column(String(5), default="PC")
