"""Production Planning - SQLAlchemy models.

Phase 2A entities (master data):
- WorkCenter         : 作業センタ (機械/人員のキャパとレート)
- Recipe (BOM)       : 配合 (Header)  + RecipeItem (Components)
- Routing            : 工程順序 (Header) + RoutingOperation (各工程)
- ProductionVersion  : Recipe + Routing の組み合わせバージョン

Phase 2B entities (costing):
- CostComponentSplit : 計算済み標準原価の分解結果

Note: 製造実行 (ProcessOrder/Batch) は Phase 2C 以降。
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, MasterDataMixin


# ==================================================================
# Work Center
# ==================================================================
class WorkCenter(MasterDataMixin, Base):
    """作業センタ - 機械・人員のキャパとコストレートを定義。

    SAP の CRHD/CRCO 相当。
    Routing の各工程は WorkCenter に紐付き、Cost Rollup でレートが使われる。
    """
    __tablename__ = "work_centers"
    __table_args__ = (
        UniqueConstraint("client_id", "work_center_code",
                        name="uq_work_centers_client_code"),
    )

    work_center_code: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)

    # Capacity
    capacity_per_day: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    capacity_unit: Mapped[str] = mapped_column(String(5), default="H")  # H=hours

    # Cost rates (per hour) - used in Cost Rollup
    labor_rate_per_hour: Mapped[Decimal] = mapped_column(Numeric(15, 4), default=0)
    machine_rate_per_hour: Mapped[Decimal] = mapped_column(Numeric(15, 4), default=0)
    overhead_rate_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="JPY")


# ==================================================================
# Recipe (BOM)
# ==================================================================
class Recipe(MasterDataMixin, Base):
    """製造レシピ / BOM ヘッダ。

    SAP の STKO (BOM Header) 相当。
    1つの製品 (material_code) × プラント (plant_code) に対し
    複数バージョンを保持可能。default フラグで標準レシピを示す。
    """
    __tablename__ = "recipes"
    __table_args__ = (
        UniqueConstraint("client_id", "recipe_code",
                        name="uq_recipes_client_code"),
    )

    recipe_code: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False)
    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)

    description: Mapped[Optional[str]] = mapped_column(String(255))

    # Reference quantity for the recipe (e.g. 100 L per batch)
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), default=Decimal("1"))
    base_unit: Mapped[str] = mapped_column(String(5), default="PC")

    # Process yield - 投入量に対する産出量比 (例: 95.0 = 95%)
    yield_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("100"))

    # Validity & lifecycle
    valid_from: Mapped[date] = mapped_column(Date, default=date.today)
    valid_to: Mapped[date] = mapped_column(Date, default=date(2099, 12, 31))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    # DRAFT / RELEASED / OBSOLETE

    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    items: Mapped[List["RecipeItem"]] = relationship(
        "RecipeItem", back_populates="recipe",
        cascade="all, delete-orphan", lazy="selectin",
    )
    co_products: Mapped[List["RecipeCoProduct"]] = relationship(
        "RecipeCoProduct", back_populates="recipe",
        cascade="all, delete-orphan", lazy="selectin",
    )


class RecipeItem(AuditMixin, Base):
    """投入原料 (BOM Component)。SAP の STPO 相当。"""
    __tablename__ = "recipe_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    item_no: Mapped[int] = mapped_column(Integer, nullable=False)  # 10, 20, 30...

    component_material_code: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(5), default="PC")

    # Process loss factor - 工程廃棄率 (例: 2.0 = 2% scrap)
    scrap_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("0"))

    # ファントム品 (架空中間品。explosion時に展開され在庫管理対象外)
    is_phantom: Mapped[bool] = mapped_column(Boolean, default=False)

    # 投入工程 (Routing operation_no への参照。NULLなら最初の工程)
    operation_no: Mapped[Optional[int]] = mapped_column(Integer)

    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="items")


class RecipeCoProduct(AuditMixin, Base):
    """副産物 / Co-product / By-product (プロセス製造特有)。

    例: 蒸留工程で得られる回収溶媒。
    cost_share_percent でコストの按分比率を指定。
    """
    __tablename__ = "recipe_co_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recipe_id: Mapped[int] = mapped_column(
        ForeignKey("recipes.id", ondelete="CASCADE"), index=True)
    material_code: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(5), default="PC")
    cost_share_percent: Mapped[Decimal] = mapped_column(
        Numeric(7, 4), default=Decimal("0"),
        comment="0=by-product (no cost share), >0=co-product")

    recipe: Mapped["Recipe"] = relationship("Recipe", back_populates="co_products")


# ==================================================================
# Routing (Master Recipe / Process Sequence)
# ==================================================================
class Routing(MasterDataMixin, Base):
    """工程順序ヘッダ。SAP の PLKO 相当。"""
    __tablename__ = "routings"
    __table_args__ = (
        UniqueConstraint("client_id", "routing_code",
                        name="uq_routings_client_code"),
    )

    routing_code: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False)
    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)

    description: Mapped[Optional[str]] = mapped_column(String(255))
    base_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), default=Decimal("1"))
    base_unit: Mapped[str] = mapped_column(String(5), default="PC")

    valid_from: Mapped[date] = mapped_column(Date, default=date.today)
    valid_to: Mapped[date] = mapped_column(Date, default=date(2099, 12, 31))
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")

    operations: Mapped[List["RoutingOperation"]] = relationship(
        "RoutingOperation", back_populates="routing",
        cascade="all, delete-orphan", lazy="selectin",
    )


class RoutingOperation(AuditMixin, Base):
    """工程ステップ。SAP の PLPO 相当。"""
    __tablename__ = "routing_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    routing_id: Mapped[int] = mapped_column(
        ForeignKey("routings.id", ondelete="CASCADE"), index=True)
    operation_no: Mapped[int] = mapped_column(Integer, nullable=False)  # 0010, 0020...
    description: Mapped[str] = mapped_column(String(255), nullable=False)

    # Logical reference (no FK) - resolved per-tenant by code lookup
    work_center_code: Mapped[str] = mapped_column(String(20), nullable=False)

    # Time consumption per base_quantity of the routing
    setup_time_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"),
        comment="Fixed setup time, independent of quantity")
    machine_time_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"),
        comment="Machine time per base_quantity")
    labor_time_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"),
        comment="Labor time per base_quantity")

    # Per-operation yield (cumulative yield = product of all op yields)
    yield_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4), default=Decimal("100"))

    routing: Mapped["Routing"] = relationship("Routing", back_populates="operations")


# ==================================================================
# Production Version (S/4HANA - Recipe + Routing pairing)
# ==================================================================
class ProductionVersion(MasterDataMixin, Base):
    """Production Version - Recipe と Routing の組み合わせ。

    S/4HANA では in-house manufacturing の唯一のソースとして必須。
    Cost Rollup と Process Order はこのオブジェクトを起点にする。
    """
    __tablename__ = "production_versions"
    __table_args__ = (
        UniqueConstraint("client_id", "version_code",
                        name="uq_production_versions_client_code"),
    )

    version_code: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False)
    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)

    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False)
    routing_id: Mapped[int] = mapped_column(ForeignKey("routings.id"), nullable=False)

    valid_from: Mapped[date] = mapped_column(Date, default=date.today)
    valid_to: Mapped[date] = mapped_column(Date, default=date(2099, 12, 31))

    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    recipe: Mapped["Recipe"] = relationship("Recipe", lazy="selectin")
    routing: Mapped["Routing"] = relationship("Routing", lazy="selectin")


# ==================================================================
# Cost Component Split (calculated cost breakdown)
# ==================================================================
class CostComponentSplit(AuditMixin, Base):
    """品目×プラントごとの計算済み標準原価の分解結果。

    SAP の Cost Component Split (CK13N) 相当。
    Cost Rollup を実行するたびにレコードが追加され、
    valid_from / valid_to で履歴管理される。
    """
    __tablename__ = "cost_component_splits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    production_version_code: Mapped[Optional[str]] = mapped_column(String(20))

    # Per-unit (1 unit of base_unit) cost components
    raw_material_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    labor_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    machine_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    overhead_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    external_processing_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)

    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="JPY")
    base_unit: Mapped[str] = mapped_column(String(5), default="PC")

    # When this estimate is valid
    valid_from: Mapped[date] = mapped_column(Date, default=date.today)
    valid_to: Mapped[date] = mapped_column(Date, default=date(2099, 12, 31))

    # Detailed breakdown (BOM explosion) as JSON for drill-down/audit
    breakdown_json: Mapped[Optional[str]] = mapped_column(Text)
