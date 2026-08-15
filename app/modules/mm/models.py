"""Materials Management - SQLAlchemy models.

Phase 2C entities (procure-to-pay flow):
- PurchaseRequisition (PR)  : 購買依頼
- PurchaseOrder (PO)        : 購買発注
- GoodsReceipt (GR)         : 入庫実績
- InvoiceReceipt (IR)       : 仕入請求書受領 (3-way match)

Phase 3 entities (inventory & supplier master):
- PurchasingInfoRecord      : 購買情報レコード (品目×ベンダー価格・条件)
- SourceList                : ソースリスト (調達先優先順位)
- StockBalance              : 在庫残高 (プラント×保管場所)
- Reservation               : 在庫引当 (製造指図・受注からの所要量)

Document chain (SAP MM standard):
    PR  -> PO -> GR -> IR
                  └----┘  → 3-way match → AP posting
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean, Date, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, DocumentMixin, MasterDataMixin


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


# ==================================================================
# Purchasing Info Record (購買情報レコード)
# ==================================================================
class PurchasingInfoRecord(MasterDataMixin, Base):
    """品目 × ベンダーごとの購買条件マスタ。SAP の EINA/EINP 相当。

    マルチサプライヤー対応の基盤。同一品目に対して複数ベンダーの
    価格・リードタイム・最小発注量・原産国を管理する。
    """
    __tablename__ = "purchasing_info_records"
    __table_args__ = (
        UniqueConstraint("client_id", "material_code", "vendor_code", "plant_code",
                         name="uq_pir_client_mat_vendor_plant"),
    )

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    # plant_code=NULL は全プラント共通

    # 価格条件
    unit_price: Mapped[Decimal] = mapped_column(Numeric(15, 4), nullable=False)
    price_unit: Mapped[Decimal] = mapped_column(Numeric(15, 3), default=Decimal("1"))
    # price_unit=100 の場合、unit_price は 100個あたりの価格
    currency: Mapped[str] = mapped_column(String(3), default="JPY")
    price_valid_from: Mapped[Optional[date]] = mapped_column(Date)
    price_valid_to: Mapped[Optional[date]] = mapped_column(Date)

    # 発注条件
    min_order_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    max_order_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    order_unit: Mapped[str] = mapped_column(String(5), default="PC")
    planned_delivery_days: Mapped[int] = mapped_column(Integer, default=0)
    incoterms: Mapped[Optional[str]] = mapped_column(String(10))
    payment_terms: Mapped[Optional[str]] = mapped_column(String(20))

    # 原産国 (ベンダー調達先ごとに異なる場合がある)
    country_of_origin: Mapped[Optional[str]] = mapped_column(String(2))
    # ISO 3166-1 alpha-2

    # ベンダー品番 (相互参照)
    vendor_material_code: Mapped[Optional[str]] = mapped_column(String(50))
    vendor_material_name: Mapped[Optional[str]] = mapped_column(String(255))

    # 優先フラグ (ソースリストが未設定の場合のデフォルト優先サプライヤー)
    is_preferred: Mapped[bool] = mapped_column(Boolean, default=False)

    # 輸出管理 (ベンダー側の管理分類)
    vendor_eccn: Mapped[Optional[str]] = mapped_column(String(20))


# ==================================================================
# Source List (ソースリスト)
# ==================================================================
class SourceList(MasterDataMixin, Base):
    """品目 × プラントに対する調達先優先順位リスト。SAP の EORD 相当。

    MRP 実行時や PR → PO 変換時の自動調達先決定に使用する。
    複数ベンダーへの割当比率 (quota_percentage) も管理可能。
    """
    __tablename__ = "source_lists"
    __table_args__ = (
        UniqueConstraint("client_id", "material_code", "plant_code", "vendor_code",
                         name="uq_source_list_client_mat_plant_vendor"),
    )

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    vendor_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # 有効期間
    valid_from: Mapped[date] = mapped_column(Date, default=date.today)
    valid_to: Mapped[date] = mapped_column(Date, default=date(2099, 12, 31))

    # 優先度 (1=最高優先)
    priority: Mapped[int] = mapped_column(Integer, default=1)

    # 割当比率 (複数ベンダーへのスプリット発注)
    quota_percentage: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 2))
    # NULL=割当なし / 30.00=30%割当

    # ブロックフラグ
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    # True の場合、このベンダーへの自動選択を禁止

    # 固定ソース (MRP が他ベンダーを選択しないように固定)
    is_fixed: Mapped[bool] = mapped_column(Boolean, default=False)

    # 発注タイプ
    order_type: Mapped[str] = mapped_column(String(10), default="PO")
    # PO=通常発注 / CONTRACT=契約 / SA=枠組み合意

    pir_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("purchasing_info_records.id"), nullable=True)


# ==================================================================
# Stock Balance (在庫残高)
# ==================================================================
class StockBalance(MasterDataMixin, Base):
    """品目 × プラント × 保管場所の在庫残高。SAP の MARD/MARA 相当。

    GoodsReceipt (入庫) / DeliveryItem (出庫) / Reservation (引当) の
    トランザクションごとに更新される。
    """
    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("client_id", "material_code", "plant_code", "storage_location",
                         name="uq_stock_balances_client_mat_plant_sloc"),
    )

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), default="0001")

    # 在庫区分別数量
    unrestricted_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="自由使用在庫 (出庫・引当の対象)")
    quality_inspection_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="品質検査中在庫")
    blocked_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="ブロック在庫 (使用禁止)")
    in_transit_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="輸送中在庫 (GR 前の PO 発注済)")
    reserved_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="引当済数量 (Reservation テーブルと連動)")

    stock_unit: Mapped[str] = mapped_column(String(5), default="PC")

    @property
    def available_qty(self) -> Decimal:
        """引当後の実使用可能数量。"""
        return self.unrestricted_qty - self.reserved_qty


# ==================================================================
# Reservation (在庫引当)
# ==================================================================
class Reservation(MasterDataMixin, Base):
    """在庫引当レコード。SAP の RESB/RKPF 相当。

    製造指図・受注・MM 手動引当から在庫を確保する。
    引当後は StockBalance.reserved_qty を増やして二重引当を防ぐ。
    """
    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("client_id", "reservation_number",
                         name="uq_reservations_client_number"),
    )

    reservation_number: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False)

    material_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    plant_code: Mapped[str] = mapped_column(String(10), index=True, nullable=False)
    storage_location: Mapped[str] = mapped_column(String(10), default="0001")

    # 引当元文書 (受注 / 製造指図 / 手動)
    reservation_type: Mapped[str] = mapped_column(String(10), default="MANUAL")
    # SD=受注 / PP=製造指図 / MANUAL=手動
    source_document_type: Mapped[Optional[str]] = mapped_column(String(20))
    source_document_id: Mapped[Optional[int]] = mapped_column(Integer)
    source_document_item: Mapped[Optional[int]] = mapped_column(Integer)

    # 数量
    required_qty: Mapped[Decimal] = mapped_column(Numeric(15, 3), nullable=False)
    confirmed_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="在庫確認済数量 (ATP チェック後)")
    withdrawn_qty: Mapped[Decimal] = mapped_column(
        Numeric(15, 3), default=Decimal("0"),
        comment="出庫済数量")
    stock_unit: Mapped[str] = mapped_column(String(5), default="PC")

    # スケジュール
    requirement_date: Mapped[Optional[date]] = mapped_column(Date)

    # ステータス
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    # OPEN / PARTIALLY_WITHDRAWN / FULLY_WITHDRAWN / CANCELLED
