"""GTS - SQLAlchemy models for AI_TM integration link tables.

ZSD_AI_TM_LINK  → AITMTransactionLink  (SO ↔ AI_TM review)
ZSD_AI_TM_SHIP  → AITMShipmentLink     (Delivery ↔ AI_TM rescreen)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
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
    shipment_ok: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rescreen_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    rescreen_result: Mapped[Optional[str]] = mapped_column(String(10))  # PASSED / CHANGED
    block_reason: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
