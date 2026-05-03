"""Materials Management - SQLAlchemy models.

Phase 2C entities (procure-to-pay flow):
- PurchaseRequisition (PR): 購買依頼 (内部の発注予定)
- PurchaseOrder (PO):       購買発注 (ベンダー宛の正式発注書)
- GoodsReceipt (GR):        入庫実績
- InvoiceReceipt (IR):      仕入請求書受領 (3-way match の起点)

Document chain (SAP MM standard):
    PR  -> PO -> GR -> IR
                  └----┘  → 3-way match → AP posting (Phase 2D)

各文書は DocumentMixin を継承するため、document_number / status /
reference (上流文書への参照) を共通で持つ。
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, DocumentMixin


# ==================================================================
# Purchase Requisition (PR)
# ==================================================================
class PurchaseRequisition(DocumentMixin, Base):
    """購買依頼 (内部のリクエスト)。SAP の EBAN/EBKN 相当。

    起源は3つ:
    - 手動登録 (経費購買、消耗品)
    - PP モジュール由来 (製造指図の所要量)
    - MRP 由来 (将来拡張)
    """
    __tablename__ = "purchase_requisitions"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_purchase_requisitions_client_doc"),
    )

    plant_code: Mapped[Optional[str]] = mapped_column(String(10))
    requested_by: Mapped[Optional[str]] = mapped_column(String(100))
    requested_delivery_date: Mapped[Optional[date]] = mapped_column(Date)

    # 起源を示すソースマーカー (監査・トレーサビリティ用)
    source_type: Mapped[str] = mapped_column(String(20), default="MANUAL")
    # MANUAL / MRP / PROCESS_ORDER / SALES_ORDER
    source_reference: Mapped[Optional[str]] = mapped_column(String(50))

    items: Mapped[List["PurchaseRequisitionItem"]] = relationship(
        "PurchaseRequisitionItem",
        back_populates="purchase_requisition",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PurchaseRequisitionItem(AuditMixin, Base):
    __tablename__ = "purchase_requisition_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_requisition_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_requisitions.id", ondelete="CASCADE"), index=True)
    item_no: Mapped[int] = mapped_column(Integer, nullable=False)

    material_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(5), default="PC")

    # 推奨ベンダ (PRから直接POを生成するときに使う)
    suggested_vendor_code: Mapped[Optional[str]] = mapped_column(String(20))
    estimated_unit_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 4))
    currency: Mapped[Optional[str]] = mapped_column(String(3))

    plant_code: Mapped[Optional[str]] = mapped_column(String(10))
    requested_delivery_date: Mapped[Optional[date]] = mapped_column(Date)

    # PO 化された数量を追跡 (完全/部分/未消化を判別)
    ordered_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"))

    purchase_requisition: Mapped["PurchaseRequisition"] = relationship(
        "PurchaseRequisition", back_populates="items")


# ==================================================================
# Purchase Order (PO)
# ==================================================================
class PurchaseOrder(DocumentMixin, Base):
    """購買発注書。SAP の EKKO/EKPO 相当。"""
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_purchase_orders_client_doc"),
    )

    purchasing_org_code: Mapped[Optional[str]] = mapped_column(String(10))
    plant_code: Mapped[Optional[str]] = mapped_column(String(10))

    vendor_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    requested_delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    incoterms: Mapped[Optional[str]] = mapped_column(String(10))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(20))
    currency: Mapped[str] = mapped_column(String(3), default="JPY")

    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))

    items: Mapped[List["PurchaseOrderItem"]] = relationship(
        "PurchaseOrderItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class PurchaseOrderItem(AuditMixin, Base):
    __tablename__ = "purchase_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True)
    item_no: Mapped[int] = mapped_column(Integer, nullable=False)

    # 上流PR行への参照 (PR から PO を起こした場合のみ)
    pr_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("purchase_requisition_items.id"))

    material_code: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(5), default="PC")
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    plant_code: Mapped[Optional[str]] = mapped_column(String(10))

    # 入庫済み数量 (3-way match と部分受領管理用)
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"))
    # 請求書計上済み数量
    invoiced_quantity: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"))

    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder", back_populates="items")


# ==================================================================
# Goods Receipt (GR)
# ==================================================================
class GoodsReceipt(DocumentMixin, Base):
    """入庫実績。SAP の MKPF/MSEG (movement type 101) 相当。"""
    __tablename__ = "goods_receipts"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_goods_receipts_client_doc"),
    )

    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), index=True, nullable=False)
    plant_code: Mapped[Optional[str]] = mapped_column(String(10))
    posting_date: Mapped[date] = mapped_column(Date, default=date.today)

    # ベンダー側の出荷案内番号 (delivery note number)
    vendor_delivery_note: Mapped[Optional[str]] = mapped_column(String(50))

    items: Mapped[List["GoodsReceiptItem"]] = relationship(
        "GoodsReceiptItem",
        back_populates="goods_receipt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class GoodsReceiptItem(AuditMixin, Base):
    __tablename__ = "goods_receipt_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), index=True)
    po_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id"), nullable=False)
    item_no: Mapped[int] = mapped_column(Integer)

    material_code: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(5))

    # 規制対応 / トレーサビリティ
    batch_code: Mapped[Optional[str]] = mapped_column(String(50))
    storage_location: Mapped[Optional[str]] = mapped_column(String(20))

    goods_receipt: Mapped["GoodsReceipt"] = relationship(
        "GoodsReceipt", back_populates="items")


# ==================================================================
# Invoice Receipt (IR) - 仕入請求書
# ==================================================================
class InvoiceReceipt(DocumentMixin, Base):
    """仕入先からの請求書。SAP の RBKP/RSEG 相当。

    POと突合して3-way match を行うとAP仕訳が自動発生 (Phase 2D)。
    """
    __tablename__ = "invoice_receipts"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_invoice_receipts_client_doc"),
    )

    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), nullable=False, index=True)
    vendor_code: Mapped[str] = mapped_column(String(20), nullable=False)

    # 仕入先側の請求書番号
    vendor_invoice_number: Mapped[str] = mapped_column(String(50))
    posting_date: Mapped[date] = mapped_column(Date, default=date.today)
    invoice_date: Mapped[date] = mapped_column(Date, default=date.today)

    currency: Mapped[str] = mapped_column(String(3), default="JPY")
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))

    # 3-way match の結果
    match_status: Mapped[str] = mapped_column(String(20), default="PENDING")
    # PENDING / MATCHED / PRICE_VARIANCE / QTY_VARIANCE / BLOCKED
    match_message: Mapped[Optional[str]] = mapped_column(String(500))

    items: Mapped[List["InvoiceReceiptItem"]] = relationship(
        "InvoiceReceiptItem",
        back_populates="invoice_receipt",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class InvoiceReceiptItem(AuditMixin, Base):
    __tablename__ = "invoice_receipt_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_receipts.id", ondelete="CASCADE"), index=True)
    po_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id"), nullable=False)
    item_no: Mapped[int] = mapped_column(Integer)

    material_code: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(5))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    invoice_receipt: Mapped["InvoiceReceipt"] = relationship(
        "InvoiceReceipt", back_populates="items")
