"""Sales & Distribution - SQLAlchemy models.

Document chain:
    SalesOrder -> Delivery -> BillingDocument
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import Date, ForeignKey, Numeric, String, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import DocumentMixin, AuditMixin


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
