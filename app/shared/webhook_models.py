"""Shared DB models for integration infrastructure.

- TenantMapping      : client_id ↔ crm_tenant_id conversion
- WebhookDelivery    : outbound webhook delivery queue (ERP→CRM)
- InboundRequestLog  : inbound request deduplication (replay protection)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TenantMapping(Base):
    """Maps ERP client_id to CRM tenant identifiers for Webhook X-Tenant-Id headers."""

    __tablename__ = "tenant_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    crm_tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class WebhookDelivery(Base):
    """Outbound webhook delivery queue for ERP → CRM events.

    The worker (scripts/process_webhook_queue.py) polls this table and delivers
    pending records with exponential backoff. Records that exceed MAX_ATTEMPTS
    are moved to DLQ (status='dlq') for manual intervention.
    """

    __tablename__ = "webhook_delivery"
    __table_args__ = (
        Index("ix_webhook_delivery_status_next", "status", "next_attempt_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    client_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    target_system: Mapped[str] = mapped_column(String(20), nullable=False)  # "crm"
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # JSON string serialized once at enqueue time — worker sends it as-is
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | delivered | failed | dlq
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class InboundRequestLog(Base):
    """Records inbound X-Request-Id values to detect and reject replay attacks.

    Entries are valid for 10 minutes (expires_at). The auth layer calls db.merge()
    so expired entries are silently replaced.
    """

    __tablename__ = "inbound_request_log"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # "aitm" | "crm"
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
