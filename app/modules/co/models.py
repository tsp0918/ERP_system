"""CO (Controlling) — SQLAlchemy models.

Step 1: Asset Master + Asset Cost Rates  (CAPEX → machine_rate)
Step 2: Cost Centers + Budgets + Employee allocation (LABOR → labor_rate)
Step 3: Actual Cost Postings             (plan vs actual variance)
Step 4: Cost Estimate Items              (CoO-level breakdown for De Minimis)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, MasterDataMixin, TenantMixin


# ══════════════════════════════════════════════════════════════════════
# Step 1 — CAPEX / Asset Management
# ══════════════════════════════════════════════════════════════════════

class AssetMaster(MasterDataMixin, Base):
    """固定資産台帳 — 設備ごとの取得情報・償却条件を管理する。

    work_center_code にリンクすることで machine_rate の根拠を追跡可能にする。
    """
    __tablename__ = "asset_master"
    __table_args__ = (UniqueConstraint("client_id", "asset_code"),)

    asset_code:          Mapped[str]           = mapped_column(String(20), nullable=False)
    description:         Mapped[str]           = mapped_column(String(255), nullable=False)
    asset_class:         Mapped[str]           = mapped_column(String(20), default="MACHINERY",
                                                    comment="MACHINERY / BUILDING / TOOL / IT_EQUIPMENT")
    work_center_code:    Mapped[Optional[str]] = mapped_column(String(20), index=True)
    plant_code:          Mapped[Optional[str]] = mapped_column(String(10))
    acquisition_cost:    Mapped[Decimal]       = mapped_column(Numeric(18, 2), nullable=False)
    residual_value:      Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"))
    useful_life_years:   Mapped[int]           = mapped_column(Integer, nullable=False)
    depreciation_method: Mapped[str]           = mapped_column(String(20), default="straight_line",
                                                    comment="straight_line / declining_balance")
    acquisition_date:    Mapped[date]          = mapped_column(Date, nullable=False)
    currency:            Mapped[str]           = mapped_column(String(3), default="JPY")
    notes:               Mapped[Optional[str]] = mapped_column(Text)

    cost_rates: Mapped[list["AssetCostRate"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )

    @property
    def annual_depreciation(self) -> Decimal:
        """定額法の年間償却費（参考値）。"""
        if self.useful_life_years <= 0:
            return Decimal("0")
        return ((self.acquisition_cost - self.residual_value)
                / self.useful_life_years).quantize(Decimal("1"))


class AssetCostRate(AuditMixin, TenantMixin, Base):
    """設備コスト年次計画 — 会計年度ごとに机上コストを計画し machine_rate を算出する。

    machine_rate = (depreciation_plan + maintenance_plan + utility_plan) / planned_hours
    """
    __tablename__ = "asset_cost_rates"
    __table_args__ = (UniqueConstraint("client_id", "asset_code", "fiscal_year"),)

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_code:          Mapped[str]           = mapped_column(
                             String(20), ForeignKey("asset_master.asset_code"), nullable=False, index=True)
    fiscal_year:         Mapped[int]           = mapped_column(Integer, nullable=False)
    depreciation_plan:   Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                    comment="年間計画償却費")
    maintenance_plan:    Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                    comment="年間保守費計画")
    utility_plan:        Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                    comment="ユーティリティ費計画")
    planned_hours:       Mapped[Decimal]       = mapped_column(Numeric(10, 2), nullable=False,
                                                    comment="年間計画稼働時間")
    machine_rate:        Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2),
                                                    comment="算出済み機械レート (JPY/h)")
    currency:            Mapped[str]           = mapped_column(String(3), default="JPY")

    asset: Mapped["AssetMaster"] = relationship(back_populates="cost_rates")

    def calculate_rate(self) -> Decimal:
        """(depreciation + maintenance + utility) / planned_hours を返す。"""
        if not self.planned_hours or self.planned_hours == 0:
            return Decimal("0")
        total = self.depreciation_plan + self.maintenance_plan + self.utility_plan
        return (total / self.planned_hours).quantize(Decimal("1"))


# ══════════════════════════════════════════════════════════════════════
# Step 2 — Cost Centers / Labor Rate
# ══════════════════════════════════════════════════════════════════════

class CostCenter(MasterDataMixin, Base):
    """コストセンター — 原価責任単位（工場部門・製造ライン等）。

    work_center_code にリンクし、コストセンター予算から labor_rate を算出する。
    """
    __tablename__ = "cost_centers"
    __table_args__ = (UniqueConstraint("client_id", "cost_center_code"),)

    cost_center_code:    Mapped[str]           = mapped_column(String(20), nullable=False)
    name:                Mapped[str]           = mapped_column(String(255), nullable=False)
    cost_center_type:    Mapped[str]           = mapped_column(String(20), default="production",
                                                    comment="production / service / admin / rd")
    plant_code:          Mapped[Optional[str]] = mapped_column(String(10))
    work_center_code:    Mapped[Optional[str]] = mapped_column(String(20), index=True,
                                                    comment="紐付く作業センタ")
    responsible_employee_id: Mapped[Optional[int]] = mapped_column(Integer)
    currency:            Mapped[str]           = mapped_column(String(3), default="JPY")
    notes:               Mapped[Optional[str]] = mapped_column(Text)

    budgets:   Mapped[list["CostCenterBudget"]]   = relationship(back_populates="cost_center",
                                                       cascade="all, delete-orphan")
    employees: Mapped[list["CostCenterEmployee"]] = relationship(back_populates="cost_center",
                                                       cascade="all, delete-orphan")


class CostCenterEmployee(AuditMixin, TenantMixin, Base):
    """コストセンター × 従業員配属（多対多・按分対応）。"""
    __tablename__ = "cost_center_employees"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    cost_center_code:    Mapped[str]           = mapped_column(
                             String(20), ForeignKey("cost_centers.cost_center_code"), nullable=False, index=True)
    employee_id:         Mapped[int]           = mapped_column(Integer, nullable=False, index=True)
    allocation_percent:  Mapped[Decimal]       = mapped_column(Numeric(5, 2), default=Decimal("100"),
                                                    comment="兼務時の按分率 (0-100)")
    valid_from:          Mapped[date]          = mapped_column(Date, nullable=False)
    valid_to:            Mapped[Optional[date]] = mapped_column(Date)

    cost_center: Mapped["CostCenter"] = relationship(back_populates="employees")


class CostCenterBudget(AuditMixin, TenantMixin, Base):
    """コストセンター年次予算 — 人件費・間接費の計画値と計画時間から labor_rate を算出する。

    labor_rate     = labor_budget    / planned_labor_hours
    overhead_rate% = indirect_budget / (labor_budget + machine_total_cost) × 100
    """
    __tablename__ = "cost_center_budgets"
    __table_args__ = (UniqueConstraint("client_id", "cost_center_code", "fiscal_year"),)

    id:                    Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    cost_center_code:      Mapped[str]           = mapped_column(
                               String(20), ForeignKey("cost_centers.cost_center_code"), nullable=False, index=True)
    fiscal_year:           Mapped[int]           = mapped_column(Integer, nullable=False)
    # LABOR
    labor_budget:          Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                      comment="年間人件費予算（給与+社保+福利）")
    planned_labor_hours:   Mapped[Decimal]       = mapped_column(Numeric(10, 2), default=Decimal("1"),
                                                      comment="年間計画生産労働時間")
    labor_rate:            Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2),
                                                      comment="算出済み労務レート")
    # OVERHEAD (indirect costs allocated to this CC)
    indirect_budget:       Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                      comment="間接費予算（施設・保険・IT等）")
    overhead_rate_percent: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 4),
                                                      comment="算出済み OH 率(%)")
    currency:              Mapped[str]           = mapped_column(String(3), default="JPY")

    cost_center: Mapped["CostCenter"] = relationship(back_populates="budgets")

    def calculate_labor_rate(self) -> Decimal:
        if not self.planned_labor_hours or self.planned_labor_hours == 0:
            return Decimal("0")
        return (self.labor_budget / self.planned_labor_hours).quantize(Decimal("1"))

    def calculate_overhead_rate(self, direct_cost_base: Decimal) -> Decimal:
        """間接費 / 直接費合計 × 100 = OH率(%)。"""
        if not direct_cost_base or direct_cost_base == 0:
            return Decimal("0")
        return (self.indirect_budget / direct_cost_base * 100).quantize(Decimal("0.01"))


# ══════════════════════════════════════════════════════════════════════
# Step 3 — Actual Cost Postings (Plan vs Actual Variance)
# ══════════════════════════════════════════════════════════════════════

class ActualCostPosting(AuditMixin, TenantMixin, Base):
    """実際原価転記 — 製造指図完了時に計画原価 vs 実際原価の差異を記録する。

    差異区分:
      PRICE_VARIANCE    : 購入価格差異（原料相場・為替）
      QUANTITY_VARIANCE : 使用量差異（歩留まり・廃棄）
      RATE_VARIANCE     : レート差異（残業・稼働率低下）
      VOLUME_VARIANCE   : 操業度差異（固定費の未吸収）
    """
    __tablename__ = "actual_cost_postings"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    process_order_id:    Mapped[int]           = mapped_column(Integer, nullable=False, index=True,
                                                    comment="process_orders.id")
    process_order_number: Mapped[str]          = mapped_column(String(20), nullable=False)
    cost_element:        Mapped[str]           = mapped_column(String(20), nullable=False,
                                                    comment="MATERIAL / LABOR / MACHINE / OVERHEAD / EXTERNAL")
    planned_quantity:    Mapped[Decimal]       = mapped_column(Numeric(14, 4), default=Decimal("0"))
    actual_quantity:     Mapped[Decimal]       = mapped_column(Numeric(14, 4), default=Decimal("0"))
    quantity_unit:       Mapped[Optional[str]] = mapped_column(String(5))
    planned_cost:        Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"))
    actual_cost:         Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"))
    variance:            Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                    comment="actual - planned (正 = 超過)")
    variance_percent:    Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2))
    variance_category:   Mapped[Optional[str]] = mapped_column(String(30))
    currency:            Mapped[str]           = mapped_column(String(3), default="JPY")
    fiscal_year:         Mapped[Optional[int]] = mapped_column(Integer)
    fiscal_period:       Mapped[Optional[int]] = mapped_column(Integer, comment="1-12")
    posted_at:           Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    notes:               Mapped[Optional[str]] = mapped_column(Text)


# ══════════════════════════════════════════════════════════════════════
# Step 4 — Cost Estimate Items (CoO-level breakdown for De Minimis)
# ══════════════════════════════════════════════════════════════════════

class CostEstimateItem(AuditMixin, TenantMixin, Base):
    """標準原価見積明細 — cost_component_splits の CoO 別内訳。

    原産国(origin_country)ごとにコスト配分を管理することで
    US EAR De Minimis 計算 (25%ルール) を正確に行える。
    """
    __tablename__ = "cost_estimate_items"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 親レコード: cost_component_splits
    cost_split_id:       Mapped[int]           = mapped_column(Integer, nullable=False, index=True,
                                                    comment="cost_component_splits.id")
    material_code:       Mapped[str]           = mapped_column(String(20), nullable=False, index=True)
    plant_code:          Mapped[Optional[str]] = mapped_column(String(10))
    fiscal_year:         Mapped[int]           = mapped_column(Integer, nullable=False)
    # 明細種別
    item_type:           Mapped[str]           = mapped_column(String(20), nullable=False,
                                                    comment="MATERIAL / LABOR / MACHINE / OVERHEAD / EXTERNAL")
    reference_code:      Mapped[Optional[str]] = mapped_column(String(50),
                                                    comment="品目コード or 活動タイプコード")
    description:         Mapped[Optional[str]] = mapped_column(String(255))
    quantity:            Mapped[Decimal]       = mapped_column(Numeric(14, 4), default=Decimal("0"))
    quantity_unit:       Mapped[Optional[str]] = mapped_column(String(5))
    unit_cost:           Mapped[Decimal]       = mapped_column(Numeric(18, 4), default=Decimal("0"))
    total_cost:          Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"))
    currency:            Mapped[str]           = mapped_column(String(3), default="JPY")
    # CoO 情報 (De Minimis 計算の核心)
    origin_country:      Mapped[Optional[str]] = mapped_column(String(2), index=True,
                                                    comment="ISO-3166 原産国コード")
    supplier_code:       Mapped[Optional[str]] = mapped_column(String(50))
    us_content_flag:     Mapped[bool]          = mapped_column(Boolean, default=False,
                                                    comment="米国原産 = True → De Minimis 対象")
    eccn:                Mapped[Optional[str]] = mapped_column(String(20),
                                                    comment="EAR99 以外は要注意")
