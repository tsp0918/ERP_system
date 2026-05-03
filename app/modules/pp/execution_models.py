"""Production Planning - Execution layer.

Phase 2D: process orders, batches, and lot genealogy.

Key entities:
- ProcessOrder           : 製造指図 (header, ties to ProductionVersion)
- ProcessOrderComponent  : 投入予定/実績原料 (planned vs actual)
- ProcessOrderOperation  : 工程予定/実績 (machine/labor minutes)
- Batch                  : 製造ロット (in/out of inventory; trade-traceable unit)
- BatchGenealogy         : 親ロット → 子ロットの来歴 (consumed by which order)

Inventory side-effects of execution:
- On Goods Issue (consumption):  parent batch.qty -= consumed
- On Goods Receipt (production): new batch (or +qty if existing batch)

Lot genealogy enables forward and backward traceability:
  forward : 'where did batch L1 end up?' -> walk children via BatchGenealogy
  backward: 'what raw lots are inside batch L42?' -> walk parents
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    DateTime, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, DocumentMixin, TenantMixin


# ==================================================================
# Process Order (製造指図)
# ==================================================================
class ProcessOrder(DocumentMixin, Base):
    """Manufacturing order. SAP の AFKO/AUFK 相当。

    Lifecycle (status field):
        DRAFT     - 作成済み、まだ未確定
        OPEN      - 確定 (投入予定が固まっている、リリース可能)
        RELEASED  - リリース済み、現場で実行中
        COMPLETED - 完成 (Goods Receipt 済み)
        CANCELLED - 取消
    """
    __tablename__ = "process_orders"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_process_orders_client_doc"),
    )

    material_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    plant_code: Mapped[str] = mapped_column(String(10), nullable=False, index=True)

    production_version_code: Mapped[str] = mapped_column(String(20), nullable=False)

    # Quantities
    target_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    target_unit: Mapped[str] = mapped_column(String(5), default="PC")
    actual_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"))
    scrapped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"))

    # Schedule
    scheduled_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    scheduled_end: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_start: Mapped[Optional[datetime]] = mapped_column(DateTime)
    actual_end: Mapped[Optional[datetime]] = mapped_column(DateTime)

    components: Mapped[List["ProcessOrderComponent"]] = relationship(
        "ProcessOrderComponent",
        back_populates="process_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    operations: Mapped[List["ProcessOrderOperation"]] = relationship(
        "ProcessOrderOperation",
        back_populates="process_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ProcessOrderComponent(AuditMixin, Base):
    """Process order line - planned/actual material consumption."""
    __tablename__ = "process_order_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    process_order_id: Mapped[int] = mapped_column(
        ForeignKey("process_orders.id", ondelete="CASCADE"), index=True)
    item_no: Mapped[int] = mapped_column(Integer, nullable=False)

    material_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    issued_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(5), default="PC")

    operation_no: Mapped[Optional[int]] = mapped_column(Integer)

    process_order: Mapped["ProcessOrder"] = relationship(
        "ProcessOrder", back_populates="components")


class ProcessOrderOperation(AuditMixin, Base):
    """Process order operation - planned/actual time consumption per step."""
    __tablename__ = "process_order_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    process_order_id: Mapped[int] = mapped_column(
        ForeignKey("process_orders.id", ondelete="CASCADE"), index=True)
    operation_no: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(255))
    work_center_code: Mapped[str] = mapped_column(String(20))

    planned_machine_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"))
    actual_machine_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"))
    planned_labor_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"))
    actual_labor_minutes: Mapped[Decimal] = mapped_column(
        Numeric(15, 4), default=Decimal("0"))

    confirmation_count: Mapped[int] = mapped_column(Integer, default=0)
    is_confirmed: Mapped[bool] = mapped_column(
        Integer, default=0)  # boolean as int for SQLite

    process_order: Mapped["ProcessOrder"] = relationship(
        "ProcessOrder", back_populates="operations")


# ==================================================================
# Batch (製造/購入ロット)
# ==================================================================
class Batch(AuditMixin, TenantMixin, Base):
    """Lot/Batch. SAP の MCH1 相当。

    A batch is a uniquely-identified, finite-quantity instance of a material.
    Created either by:
    - Goods Receipt against a Purchase Order (purchased lot)
    - Goods Receipt against a Process Order (produced lot)

    Batches are the primary unit of trade traceability - they carry
    country of origin, quality status, expiry, and link to upstream lots
    via BatchGenealogy.
    """
    __tablename__ = "batches"
    __table_args__ = (
        UniqueConstraint("client_id", "batch_code", name="uq_batches_client_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    batch_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    material_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    storage_location: Mapped[Optional[str]] = mapped_column(String(20))

    # Quantities (current available; goods issues subtract from this)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(5), default="PC")
    initial_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)

    # Origin
    source_type: Mapped[str] = mapped_column(String(20), default="PURCHASED")
    # PURCHASED / PRODUCED / OPENING_BALANCE / ADJUSTMENT
    source_reference: Mapped[Optional[str]] = mapped_column(
        String(50), index=True)
    # GR document number, Process Order number, etc.

    # Trade-relevant attributes (replicated from Material on creation,
    # but can be overridden per-batch e.g. when origin differs)
    country_of_origin: Mapped[Optional[str]] = mapped_column(String(2))
    vendor_code: Mapped[Optional[str]] = mapped_column(String(20))

    # Quality
    quality_status: Mapped[str] = mapped_column(String(20), default="RELEASED")
    # IN_TEST / RELEASED / BLOCKED / EXPIRED / DESTROYED

    production_date: Mapped[Optional[date]] = mapped_column(Date)
    expiry_date: Mapped[Optional[date]] = mapped_column(Date)

    # Free-form structured QC data
    qc_results_json: Mapped[Optional[str]] = mapped_column(Text)


# ==================================================================
# Batch Genealogy (parent batch -> child batch)
# ==================================================================
class BatchGenealogy(AuditMixin, TenantMixin, Base):
    """Parent-child relationship between batches.

    One row per (parent_batch, child_batch) consumption event.
    For a multi-component recipe, a single child batch will have
    N parent rows (one per consumed input lot).
    """
    __tablename__ = "batch_genealogy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    parent_batch_code: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True)
    child_batch_code: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True)

    process_order_number: Mapped[str] = mapped_column(String(20), nullable=False)
    consumed_quantity: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    consumed_unit: Mapped[str] = mapped_column(String(5), default="PC")

    parent_material_code: Mapped[str] = mapped_column(String(20))
    child_material_code: Mapped[str] = mapped_column(String(20))

    consumed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
