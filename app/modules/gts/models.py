"""GTS - SQLAlchemy models for AI_TM integration link tables + export compliance.

ZSD_AI_TM_LINK  → AITMTransactionLink  (SO ↔ AI_TM review)
ZSD_AI_TM_SHIP  → AITMShipmentLink     (Delivery ↔ AI_TM rescreen)
ExportDeclaration               (出荷文書 ↔ 輸出申告・許可証管理)
MaterialOriginChangeLog         (原産国切り替えイベントログ)
LotDeMinimusAssessment          (製造ロット別 De Minimis 評価)
"""
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AITMTransactionLink(Base):
    """Links a SalesOrder to an AI_TM transaction review record (ZSD_AI_TM_LINK)."""

    __tablename__ = "ai_tm_transaction_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True, nullable=False
    )

    review_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    review_level: Mapped[Optional[str]] = mapped_column(String(10))   # AUTO / MANUAL
    eccn: Mapped[Optional[str]] = mapped_column(String(20))
    # "erp": ERP-originated review, "crm": CRM brought an existing AI_TM transaction (IF-25)
    link_source: Mapped[str] = mapped_column(String(10), default="erp", nullable=False)

    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    linked_existing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


class AITMShipmentLink(Base):
    """Links a Delivery to an AI_TM re-screening result (ZSD_AI_TM_SHIP)."""

    __tablename__ = "ai_tm_shipment_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), index=True, nullable=False
    )

    review_id: Mapped[Optional[str]] = mapped_column(String(36))
    case_no: Mapped[Optional[str]] = mapped_column(String(50), index=True)  # AI_TM case number
    shipment_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rescreen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    rescreen_result: Mapped[Optional[str]] = mapped_column(String(10))  # PASSED / CHANGED
    ai_status: Mapped[Optional[str]] = mapped_column(String(20))        # CLEAR/REVIEW/BLOCKED
    block_reason: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )


# ==================================================================
# Export Declaration (輸出申告・許可証管理)
# ==================================================================
class ExportDeclaration(Base):
    """出荷に対する輸出申告レコード。

    AI_TM の export_license (Port 8012) と連携し、
    輸出許可証番号・通関番号・仕向国・金額等を管理する。
    1つの Delivery に対して 1件の申告を紐付ける。
    """

    __tablename__ = "export_declarations"
    __table_args__ = (
        UniqueConstraint("client_id", "declaration_number",
                         name="uq_export_declarations_client_number"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # 出荷文書との紐付け
    delivery_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("deliveries.id", ondelete="SET NULL"), index=True, nullable=True)
    sales_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="SET NULL"), index=True, nullable=True)

    # AI_TM 連携情報
    ai_tm_transaction_id: Mapped[Optional[str]] = mapped_column(String(50))
    ai_tm_license_number: Mapped[Optional[str]] = mapped_column(String(50))

    # 輸出許可証
    declaration_number: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    license_type: Mapped[Optional[str]] = mapped_column(String(20))
    # individual / general / blanket
    license_authority: Mapped[Optional[str]] = mapped_column(String(20))
    # METI / BIS / DDTC / EU_COMPETENT_AUTH
    license_issued_date: Mapped[Optional[date]] = mapped_column(Date)
    license_expiry_date: Mapped[Optional[date]] = mapped_column(Date)

    # 仕向地・品目情報
    destination_country: Mapped[Optional[str]] = mapped_column(String(2))
    material_code: Mapped[Optional[str]] = mapped_column(String(20))
    hs_code: Mapped[Optional[str]] = mapped_column(String(20))
    eccn: Mapped[Optional[str]] = mapped_column(String(20))
    quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3))
    quantity_unit: Mapped[Optional[str]] = mapped_column(String(5))
    declared_value_usd: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 2))

    # ステータス
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    # DRAFT / SUBMITTED / APPROVED / REJECTED / CANCELLED

    remarks: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ==================================================================
# Material Origin Change Log (原産国切り替えイベント)
# ==================================================================
class MaterialOriginChangeLog(Base):
    """原料ロットの原産国が切り替わったことを記録するイベントログ。

    調達先が変更され country_of_origin が変わった場合に作成される。
    De Minimis 再計算をトリガーし、AI_TM への通知を管理する。
    """
    __tablename__ = "material_origin_change_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # 変更対象の原料
    material_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    from_country: Mapped[str] = mapped_column(String(2), nullable=False)
    to_country: Mapped[str] = mapped_column(String(2), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)

    # 調達先
    old_vendor_code: Mapped[Optional[str]] = mapped_column(String(20))
    new_vendor_code: Mapped[Optional[str]] = mapped_column(String(20))

    # ロット証跡
    last_old_batch_code: Mapped[Optional[str]] = mapped_column(String(50))  # 最後の旧原産地ロット
    first_new_batch_code: Mapped[Optional[str]] = mapped_column(String(50))  # 最初の新原産地ロット

    # 影響評価 (JSON list of material_codes)
    affected_fg_codes_json: Mapped[Optional[str]] = mapped_column(Text)
    # 最大 De Minimis 影響率 (完成品の中で最も影響が大きいもの)
    max_deminimis_impact_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 2))
    exceeds_threshold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=Decimal("25.0"))

    # AI_TM 連携
    ai_tm_notification_sent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_tm_notification_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ai_tm_case_ref: Mapped[Optional[str]] = mapped_column(String(50))

    # レビュー
    review_status: Mapped[str] = mapped_column(
        String(20), default="PENDING", nullable=False, index=True)
    # PENDING / REVIEWED / CLEARED / ACTION_REQUIRED
    reviewer_email: Mapped[Optional[str]] = mapped_column(String(100))
    review_notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))


# ==================================================================
# Lot De Minimis Assessment (製造ロット別 De Minimis 評価)
# ==================================================================
class LotDeMinimusAssessment(Base):
    """完成品製造ロットごとの EAR De Minimis 評価結果。

    BOM × 消費原料ロットの原産国 × 単価 を基に US-origin content % を計算する。
    25% 閾値を超えると BREACH アラートが発行され AI_TM に通知される。
    """
    __tablename__ = "lot_deminimus_assessments"
    __table_args__ = (
        UniqueConstraint("client_id", "fg_batch_code",
                         name="uq_lot_deminimus_client_fgbatch"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # 完成品ロット
    fg_batch_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    fg_material_code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    process_order_number: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # De Minimis 計算
    us_origin_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total_bom_value: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    us_content_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    threshold_pct: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=Decimal("25.0"))
    alert_level: Mapped[str] = mapped_column(
        String(10), default="OK", nullable=False, index=True)
    # OK / WARNING(>10%) / BREACH(>25%)

    # 影響を与えた US-origin 原料ロット (JSON list)
    us_components_json: Mapped[Optional[str]] = mapped_column(Text)
    # [{"material_code":"MAT-9000001","batch_code":"LOT-9001-US-001","value":3990,"pct":4.7}, ...]

    # 影響する下流 SO/Delivery (JSON list of IDs)
    affected_so_numbers_json: Mapped[Optional[str]] = mapped_column(Text)

    # AI_TM 連携
    ai_tm_notified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ai_tm_notified_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    ai_tm_case_ref: Mapped[Optional[str]] = mapped_column(String(50))

    assessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))


class DeniedPartyScreeningLog(Base):
    """制裁/輸出禁止先スクリーニング監査証跡。

    Entity List / SDN / EU Consolidated / METI 外為法 リストおよび OFAC 50%ルール
    の照合結果を記録する。AI_TM screening_batch() の呼び出し毎に 1 レコード生成。
    """

    __tablename__ = "denied_party_screening_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    # 照合対象取引先
    bp_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    bp_name: Mapped[str] = mapped_column(String(255), nullable=False)
    bp_country: Mapped[str] = mapped_column(String(2), nullable=False)

    # スクリーニング結果
    # no_match / possible_match / match / CRITICAL
    match_status: Mapped[str] = mapped_column(String(20), nullable=False)
    match_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    # 照合したリスト (OFAC_SDN / BIS_ENTITY / METI_FUL / EU_CONSOLIDATED / OFAC_50PCT)
    matched_list: Mapped[Optional[str]] = mapped_column(String(200))
    matched_entity_name: Mapped[Optional[str]] = mapped_column(String(255))
    denial_reason: Mapped[Optional[str]] = mapped_column(String(500))

    # 50% ルール
    fifty_pct_rule_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    parent_sanctioned_entity: Mapped[Optional[str]] = mapped_column(String(255))
    ownership_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 1))

    # AI_TM 連携
    ai_tm_screening_ref: Mapped[Optional[str]] = mapped_column(String(100))
    # JSON: full raw response from AI_TM screening_batch
    raw_response_json: Mapped[Optional[str]] = mapped_column(Text)

    screened_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    screened_by: Mapped[Optional[str]] = mapped_column(String(100))


class LicenseConsumptionLog(Base):
    """IF-21: Audit log for license consumption calls to AI_TM per delivery (GI posting)."""

    __tablename__ = "license_consumption_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), index=True, nullable=False)

    delivery_id: Mapped[int] = mapped_column(
        ForeignKey("deliveries.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sales_order_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)

    allocation_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    consumed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    remaining_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4))
    response_status: Mapped[str] = mapped_column(String(20), nullable=False)  # consumed | error

    raw_response: Mapped[Optional[str]] = mapped_column(Text)

    consumed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

