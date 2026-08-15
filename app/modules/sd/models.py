"""Sales & Distribution - SQLAlchemy models.

Document chain:
    SalesOrder -> Delivery -> BillingDocument
    SalesForecast (PIR) -> drives production planning
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import DocumentMixin, AuditMixin, TenantMixin


# ==================================================================
# Sales Order
# ==================================================================
class SalesOrder(DocumentMixin, Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_sales_orders_client_doc"),
    )

    sales_org_code: Mapped[Optional[str]] = mapped_column(String(10))
    customer_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    customer_po_number: Mapped[Optional[str]] = mapped_column(String(50))

    requested_delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    incoterms: Mapped[Optional[str]] = mapped_column(String(10))    # FOB, CIF, EXW...
    payment_terms: Mapped[Optional[str]] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))

    # Trade compliance result (synced from AI_TradeManagement)
    export_check_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # PENDING / PASSED / BLOCKED / SKIPPED
    export_check_ref: Mapped[Optional[str]] = mapped_column(String(50))
    export_check_message: Mapped[Optional[str]] = mapped_column(String(500))

    # CRM integration fields (Phase 1 — IF-25)
    crm_contract_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    crm_engagement_id: Mapped[Optional[str]] = mapped_column(String(100))
    aitm_transaction_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    aitm_allocation_id: Mapped[Optional[str]] = mapped_column(String(36))   # IF-23
    end_user_bp_code: Mapped[Optional[str]] = mapped_column(String(50))
    contract_start_date: Mapped[Optional[date]] = mapped_column(Date)
    contract_end_date: Mapped[Optional[date]] = mapped_column(Date)
    export_review_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime)

    items: Mapped[List["SalesOrderItem"]] = relationship(
        "SalesOrderItem",
        back_populates="sales_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class SalesOrderItem(AuditMixin, Base):
    __tablename__ = "sales_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"))
    item_no: Mapped[int] = mapped_column(Integer, nullable=False)  # 10, 20, 30...

    material_code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    unit: Mapped[str] = mapped_column(String(5), default="PC")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    plant_code: Mapped[Optional[str]] = mapped_column(String(10))

    sales_order: Mapped["SalesOrder"] = relationship("SalesOrder", back_populates="items")


# ==================================================================
# Delivery
# ==================================================================
class Delivery(DocumentMixin, Base):
    __tablename__ = "deliveries"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_deliveries_client_doc"),
    )

    sales_order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id"), index=True)
    plant_code: Mapped[Optional[str]] = mapped_column(String(10))
    actual_delivery_date: Mapped[Optional[date]] = mapped_column(Date)

    # AI_TradeManagement approval link (populated at delivery creation)
    aitm_case_no: Mapped[Optional[str]] = mapped_column(String(50))
    # PENDING / APPROVED / BLOCKED / ERROR
    aitm_approval_status: Mapped[Optional[str]] = mapped_column(String(20), default="PENDING")

    items: Mapped[List["DeliveryItem"]] = relationship(
        "DeliveryItem",
        back_populates="delivery",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class DeliveryItem(AuditMixin, Base):
    __tablename__ = "delivery_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    so_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sales_order_items.id"))
    item_no: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    unit: Mapped[str] = mapped_column(String(5), default="PC")

    delivery: Mapped["Delivery"] = relationship("Delivery", back_populates="items")


# ==================================================================
# Billing Document
# ==================================================================
class BillingDocument(DocumentMixin, Base):
    __tablename__ = "billing_documents"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_billing_documents_client_doc"),
    )

    sales_order_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sales_orders.id"))
    delivery_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deliveries.id"))
    customer_code: Mapped[str] = mapped_column(String(20), index=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(20))

    # AI_TM approval number (copied from Delivery at billing creation)
    aitm_case_no: Mapped[Optional[str]] = mapped_column(String(50))

    items: Mapped[List["BillingItem"]] = relationship(
        "BillingItem",
        back_populates="billing_document",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BillingItem(AuditMixin, Base):
    __tablename__ = "billing_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    billing_document_id: Mapped[int] = mapped_column(
        ForeignKey("billing_documents.id", ondelete="CASCADE")
    )
    item_no: Mapped[int] = mapped_column(Integer)
    material_code: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 2))
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))

    billing_document: Mapped["BillingDocument"] = relationship(
        "BillingDocument", back_populates="items"
    )


# ==================================================================
# Sales Forecast (PIR — Planned Independent Requirements)
# ==================================================================
class SalesForecast(TenantMixin, Base):
    """月次販売フォーキャスト (SAP の PIR / Planned Independent Requirement 相当)。

    生産計画 (MRP) のインプットとして、月次の販売予測数量・金額を管理する。
    複数バージョン (BASELINE / REVISED_1 / ...) で改訂履歴を保持する。
    """
    __tablename__ = "sales_forecasts"
    __table_args__ = (
        UniqueConstraint("client_id", "material_code", "year", "month", "version",
                         name="uq_sales_forecasts_client_mat_ym_ver"),
    )

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    material_code:     Mapped[str]           = mapped_column(String(20), nullable=False, index=True)
    plant_code:        Mapped[Optional[str]] = mapped_column(String(10))
    customer_code:     Mapped[Optional[str]] = mapped_column(String(20), index=True,
                                                  comment="NULL = 全顧客集計値")
    sales_org_code:    Mapped[Optional[str]] = mapped_column(String(10))
    year:              Mapped[int]           = mapped_column(Integer, nullable=False)
    month:             Mapped[int]           = mapped_column(Integer, nullable=False,
                                                  comment="1-12")
    forecast_quantity: Mapped[Decimal]       = mapped_column(Numeric(15, 3), nullable=False)
    quantity_unit:     Mapped[str]           = mapped_column(String(5), default="KG")
    forecast_value:    Mapped[Decimal]       = mapped_column(Numeric(18, 2), default=Decimal("0"),
                                                  comment="売上予測金額")
    currency:          Mapped[str]           = mapped_column(String(3), default="JPY")
    version:           Mapped[str]           = mapped_column(String(20), default="BASELINE",
                                                  comment="BASELINE / REVISED_1 / REVISED_2 ...")
    notes:             Mapped[Optional[str]] = mapped_column(Text)
    created_at:        Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:        Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow,
                                                  onupdate=datetime.utcnow)
    created_by:        Mapped[Optional[str]] = mapped_column(String(100))
    updated_by:        Mapped[Optional[str]] = mapped_column(String(100))


# ==================================================================
# Return Document  (E4-1 / IF-31)
# ==================================================================
class ReturnDocument(DocumentMixin, Base):
    """Header of a customer return (返品伝票). Created by POST /crm/returns (IF-31)."""

    __tablename__ = "return_documents"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_return_documents_client_doc"),
    )

    sales_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="SET NULL"), index=True, nullable=True
    )
    delivery_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deliveries.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # CRM identifiers
    crm_return_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    crm_contract_id: Mapped[Optional[str]] = mapped_column(String(100))

    return_reason: Mapped[Optional[str]] = mapped_column(String(200))
    return_date: Mapped[Optional[date]] = mapped_column(Date)

    # status: OPEN → COMPLETED
    items: Mapped[List["ReturnDocumentItem"]] = relationship(
        "ReturnDocumentItem", backref="return_doc", cascade="all, delete-orphan"
    )


class ReturnDocumentItem(AuditMixin, Base):
    """Line item of a return document."""

    __tablename__ = "return_document_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    return_doc_id: Mapped[int] = mapped_column(
        ForeignKey("return_documents.id", ondelete="CASCADE"), index=True, nullable=False
    )
    client_id: Mapped[str] = mapped_column(String(20), nullable=False)

    item_no: Mapped[int] = mapped_column(Integer, nullable=False)
    material_code: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(5), default="EA")

    so_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_order_items.id", ondelete="SET NULL"), nullable=True
    )
    delivery_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("delivery_items.id", ondelete="SET NULL"), nullable=True
    )
