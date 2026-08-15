"""QM (Quality Management) — SQLAlchemy models.

Step 1: Material Specs           (accepted values per material / revision)
Step 2: Inspection Plans         (what to test, which characteristics)
Step 3: Inspection Lots          (per-batch inspection header)
Step 4: Inspection Results       (per-characteristic measured values)
Step 5: Quality Certificates     (CoA issued for each lot)
Step 6: Quality Notifications    (defect / deviation reports)
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
# Step 1 — Material Spec (品目仕様)
# ══════════════════════════════════════════════════════════════════════

class MaterialSpec(MasterDataMixin, Base):
    """品目仕様ヘッダ — 製品・原材料ごとの品質規格 (revision管理)。

    revision = "A", "B", ... で改版を追跡。
    is_current=True のものが有効版。
    """
    __tablename__ = "material_specs"
    __table_args__ = (UniqueConstraint("client_id", "material_code", "revision"),)

    material_code: Mapped[str]           = mapped_column(String(20), nullable=False, index=True)
    revision:      Mapped[str]           = mapped_column(String(10), default="A",
                                               comment="仕様改版番号 A/B/01/02 等")
    description:   Mapped[Optional[str]] = mapped_column(String(255))
    is_current:    Mapped[bool]          = mapped_column(Boolean, default=True,
                                               comment="有効版フラグ (1件のみ True)")
    effective_from: Mapped[date]         = mapped_column(Date, nullable=False)
    effective_to:   Mapped[Optional[date]] = mapped_column(Date)
    approved_by:   Mapped[Optional[str]] = mapped_column(String(100))
    approved_at:   Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes:         Mapped[Optional[str]] = mapped_column(Text)

    characteristics: Mapped[list["SpecCharacteristic"]] = relationship(
        back_populates="spec", cascade="all, delete-orphan"
    )


class SpecCharacteristic(AuditMixin, TenantMixin, Base):
    """仕様特性 — 品目仕様に紐づく個々の検査項目と合否判定基準。"""
    __tablename__ = "spec_characteristics"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    spec_id:         Mapped[int]           = mapped_column(
                         Integer, ForeignKey("material_specs.id"), nullable=False, index=True)
    char_code:       Mapped[str]           = mapped_column(String(20), nullable=False,
                                                comment="特性コード (例: PURITY, MOISTURE, WEIGHT)")
    description:     Mapped[str]           = mapped_column(String(255), nullable=False)
    measurement_type: Mapped[str]          = mapped_column(String(20), default="NUMERIC",
                                                comment="NUMERIC / BOOLEAN / TEXT")
    unit:            Mapped[Optional[str]] = mapped_column(String(20))
    target_value:    Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    lower_limit:     Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    upper_limit:     Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    acceptable_text: Mapped[Optional[str]] = mapped_column(String(255),
                                                comment="BOOLEAN/TEXT型の合格値")
    is_critical:     Mapped[bool]          = mapped_column(Boolean, default=False,
                                                comment="CCP (重要管理点) フラグ")

    spec: Mapped["MaterialSpec"] = relationship(back_populates="characteristics")


# ══════════════════════════════════════════════════════════════════════
# Step 2 — Inspection Plan (検査計画)
# ══════════════════════════════════════════════════════════════════════

class InspectionPlan(MasterDataMixin, Base):
    """検査計画ヘッダ — どの品目に対しどのような検査を実施するか。

    inspection_type: INCOMING (受入), IN_PROCESS (工程内), OUTGOING (出荷前)
    """
    __tablename__ = "inspection_plans"
    __table_args__ = (UniqueConstraint("client_id", "plan_code"),)

    plan_code:       Mapped[str]           = mapped_column(String(20), nullable=False, index=True)
    material_code:   Mapped[str]           = mapped_column(String(20), nullable=False, index=True)
    plant_code:      Mapped[Optional[str]] = mapped_column(String(10))
    inspection_type: Mapped[str]           = mapped_column(String(20), default="OUTGOING",
                                                comment="INCOMING / IN_PROCESS / OUTGOING")
    description:     Mapped[Optional[str]] = mapped_column(String(255))
    sample_size:     Mapped[Optional[int]] = mapped_column(Integer,
                                                comment="サンプリング個数 (NULL=全数)")
    sample_unit:     Mapped[Optional[str]] = mapped_column(String(10))
    valid_from:      Mapped[date]          = mapped_column(Date, nullable=False)
    valid_to:        Mapped[Optional[date]] = mapped_column(Date)

    operations: Mapped[list["InspectionOperation"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )


class InspectionOperation(AuditMixin, TenantMixin, Base):
    """検査工程 — 検査計画に含まれる個々の検査ステップと使用する特性コード。"""
    __tablename__ = "inspection_operations"

    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id:        Mapped[int]           = mapped_column(
                        Integer, ForeignKey("inspection_plans.id"), nullable=False, index=True)
    operation_no:   Mapped[int]           = mapped_column(Integer, nullable=False,
                                               comment="工程番号 (10, 20, 30 ...)")
    char_code:      Mapped[str]           = mapped_column(String(20), nullable=False)
    description:    Mapped[Optional[str]] = mapped_column(String(255))
    work_center_code: Mapped[Optional[str]] = mapped_column(String(20))
    required:       Mapped[bool]          = mapped_column(Boolean, default=True)

    plan: Mapped["InspectionPlan"] = relationship(back_populates="operations")


# ══════════════════════════════════════════════════════════════════════
# Step 3 — Inspection Lot (検査ロット)
# ══════════════════════════════════════════════════════════════════════

class InspectionLot(TenantMixin, Base):
    """検査ロット — バッチ or 入荷ごとの検査ヘッダ。

    lot_status: OPEN → IN_INSPECTION → PASSED / FAILED / PARTIAL
    """
    __tablename__ = "inspection_lots"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    lot_number:          Mapped[str]           = mapped_column(String(20), nullable=False, unique=True,
                                                    index=True)
    material_code:       Mapped[str]           = mapped_column(String(20), nullable=False, index=True)
    plant_code:          Mapped[Optional[str]] = mapped_column(String(10))
    inspection_type:     Mapped[str]           = mapped_column(String(20), default="OUTGOING")
    plan_id:             Mapped[Optional[int]] = mapped_column(Integer,
                                                    comment="inspection_plans.id")
    # 参照元 (どこから発生したか)
    source_type:         Mapped[Optional[str]] = mapped_column(String(20),
                                                    comment="PROCESS_ORDER / PURCHASE_ORDER / DELIVERY")
    source_id:           Mapped[Optional[int]] = mapped_column(Integer)
    source_number:       Mapped[Optional[str]] = mapped_column(String(20))
    # 数量
    lot_quantity:        Mapped[Decimal]       = mapped_column(Numeric(14, 4), default=Decimal("0"))
    quantity_unit:       Mapped[Optional[str]] = mapped_column(String(5))
    # 日程
    created_date:        Mapped[date]          = mapped_column(Date, nullable=False,
                                                    default=date.today)
    inspection_date:     Mapped[Optional[date]] = mapped_column(Date)
    completed_date:      Mapped[Optional[date]] = mapped_column(Date)
    # 判定
    lot_status:          Mapped[str]           = mapped_column(String(20), default="OPEN",
                                                    comment="OPEN / IN_INSPECTION / PASSED / FAILED / PARTIAL")
    overall_judgment:    Mapped[Optional[str]] = mapped_column(String(10),
                                                    comment="PASS / FAIL / CONDITIONAL")
    inspector_id:        Mapped[Optional[int]] = mapped_column(Integer)
    notes:               Mapped[Optional[str]] = mapped_column(Text)
    created_by:          Mapped[Optional[str]] = mapped_column(String(100))
    updated_by:          Mapped[Optional[str]] = mapped_column(String(100))
    created_at:          Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:          Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow,
                                                    onupdate=datetime.utcnow)

    results: Mapped[list["InspectionResult"]] = relationship(
        back_populates="lot", cascade="all, delete-orphan"
    )
    certificate: Mapped[Optional["QualityCertificate"]] = relationship(
        back_populates="lot", uselist=False
    )


# ══════════════════════════════════════════════════════════════════════
# Step 4 — Inspection Results (検査結果)
# ══════════════════════════════════════════════════════════════════════

class InspectionResult(TenantMixin, Base):
    """検査結果明細 — 特性ごとの実測値と合否判定。"""
    __tablename__ = "inspection_results"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    lot_id:          Mapped[int]           = mapped_column(
                         Integer, ForeignKey("inspection_lots.id"), nullable=False, index=True)
    char_code:       Mapped[str]           = mapped_column(String(20), nullable=False)
    description:     Mapped[Optional[str]] = mapped_column(String(255))
    measurement_type: Mapped[str]          = mapped_column(String(20), default="NUMERIC")
    # 実測値 (型によりいずれか1つを使用)
    measured_value:  Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    measured_bool:   Mapped[Optional[bool]]    = mapped_column(Boolean)
    measured_text:   Mapped[Optional[str]]     = mapped_column(String(255))
    unit:            Mapped[Optional[str]]     = mapped_column(String(20))
    # 規格値 (検査時点の仕様をコピー)
    lower_limit:     Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    upper_limit:     Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    target_value:    Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6))
    # 判定
    judgment:        Mapped[str]           = mapped_column(String(10), default="PENDING",
                                                comment="PENDING / PASS / FAIL")
    is_critical:     Mapped[bool]          = mapped_column(Boolean, default=False)
    inspected_by:    Mapped[Optional[str]] = mapped_column(String(100))
    inspected_at:    Mapped[Optional[datetime]] = mapped_column(DateTime)
    notes:           Mapped[Optional[str]] = mapped_column(Text)
    created_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow,
                                                onupdate=datetime.utcnow)

    lot: Mapped["InspectionLot"] = relationship(back_populates="results")


# ══════════════════════════════════════════════════════════════════════
# Step 5 — Quality Certificate / CoA (品質証明書)
# ══════════════════════════════════════════════════════════════════════

class QualityCertificate(TenantMixin, Base):
    """品質証明書 (Certificate of Analysis) — 検査ロット合格後に発行。

    GTS 輸出申告や顧客納品に添付するドキュメントの参照情報を管理する。
    """
    __tablename__ = "quality_certificates"

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    cert_number:     Mapped[str]           = mapped_column(String(30), nullable=False, unique=True,
                                                index=True)
    lot_id:          Mapped[int]           = mapped_column(
                         Integer, ForeignKey("inspection_lots.id"), nullable=False, unique=True)
    material_code:   Mapped[str]           = mapped_column(String(20), nullable=False)
    issue_date:      Mapped[date]          = mapped_column(Date, nullable=False, default=date.today)
    expiry_date:     Mapped[Optional[date]] = mapped_column(Date)
    issued_by:       Mapped[Optional[str]] = mapped_column(String(100))
    # 顧客 / 出荷先 (任意)
    customer_code:   Mapped[Optional[str]] = mapped_column(String(20))
    delivery_id:     Mapped[Optional[int]] = mapped_column(Integer,
                                                comment="deliveries.id")
    # 全項目 PASS かどうか
    all_passed:      Mapped[bool]          = mapped_column(Boolean, default=False)
    remarks:         Mapped[Optional[str]] = mapped_column(Text)
    created_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow,
                                                onupdate=datetime.utcnow)
    created_by:      Mapped[Optional[str]] = mapped_column(String(100))

    lot: Mapped["InspectionLot"] = relationship(back_populates="certificate")


# ══════════════════════════════════════════════════════════════════════
# Step 6 — Quality Notifications (品質通知 / 不具合報告)
# ══════════════════════════════════════════════════════════════════════

class QualityNotification(TenantMixin, Base):
    """品質通知 — 不具合・逸脱・クレームを記録し是正処置を管理する。

    notification_type:
      DEFECT      : 製造工程での不良
      DEVIATION   : 仕様逸脱 (許容範囲内の一時的逸脱申請)
      COMPLAINT   : 顧客クレーム
      IMPROVEMENT : 改善提案

    status: OPEN → IN_PROGRESS → CLOSED
    """
    __tablename__ = "quality_notifications"

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_number: Mapped[str]           = mapped_column(String(20), nullable=False,
                                                    unique=True, index=True)
    notification_type:   Mapped[str]           = mapped_column(String(20), default="DEFECT",
                                                    comment="DEFECT / DEVIATION / COMPLAINT / IMPROVEMENT")
    material_code:       Mapped[Optional[str]] = mapped_column(String(20), index=True)
    lot_id:              Mapped[Optional[int]] = mapped_column(Integer,
                                                    comment="inspection_lots.id")
    process_order_id:    Mapped[Optional[int]] = mapped_column(Integer,
                                                    comment="process_orders.id")
    # 不具合内容
    subject:             Mapped[str]           = mapped_column(String(255), nullable=False)
    description:         Mapped[Optional[str]] = mapped_column(Text)
    defect_code:         Mapped[Optional[str]] = mapped_column(String(20))
    severity:            Mapped[str]           = mapped_column(String(10), default="MEDIUM",
                                                    comment="LOW / MEDIUM / HIGH / CRITICAL")
    quantity_affected:   Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 4))
    quantity_unit:       Mapped[Optional[str]] = mapped_column(String(5))
    # 日程
    reported_date:       Mapped[date]          = mapped_column(Date, nullable=False, default=date.today)
    due_date:            Mapped[Optional[date]] = mapped_column(Date)
    closed_date:         Mapped[Optional[date]] = mapped_column(Date)
    # 担当
    reported_by:         Mapped[Optional[str]] = mapped_column(String(100))
    assigned_to:         Mapped[Optional[str]] = mapped_column(String(100))
    # 是正処置
    root_cause:          Mapped[Optional[str]] = mapped_column(Text)
    corrective_action:   Mapped[Optional[str]] = mapped_column(Text)
    status:              Mapped[str]           = mapped_column(String(20), default="OPEN",
                                                    comment="OPEN / IN_PROGRESS / CLOSED")
    created_at:          Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:          Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow,
                                                    onupdate=datetime.utcnow)
    created_by:          Mapped[Optional[str]] = mapped_column(String(100))
    updated_by:          Mapped[Optional[str]] = mapped_column(String(100))
