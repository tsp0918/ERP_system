"""Shared SQLAlchemy mixins for cross-cutting concerns.

These mixins define the contract every business entity follows:
- TenantMixin: multi-tenancy
- AuditMixin: who/when changed
- DocumentMixin: business documents (orders, deliveries, invoices...)
"""
from datetime import datetime, date
from typing import Optional

from sqlalchemy import DateTime, String, Date, Integer
from sqlalchemy.orm import Mapped, mapped_column, declared_attr


# ------------------------------------------------------------------
# Status constants for documents (string-based to keep SQLite-friendly)
# ------------------------------------------------------------------
class DocStatus:
    """Standard document lifecycle states."""
    DRAFT     = "DRAFT"
    OPEN      = "OPEN"
    RELEASED  = "RELEASED"
    BLOCKED   = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    ALL = {DRAFT, OPEN, RELEASED, BLOCKED, COMPLETED, CANCELLED}


# ------------------------------------------------------------------
# Mixins
# ------------------------------------------------------------------
class TenantMixin:
    """Adds client_id for multi-tenant isolation."""

    @declared_attr
    def client_id(cls) -> Mapped[str]:
        return mapped_column(String(20), index=True, nullable=False, default="DEMO")


class AuditMixin:
    """Adds created/updated timestamps and user references."""

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    @declared_attr
    def created_by(cls) -> Mapped[Optional[str]]:
        return mapped_column(String(100), nullable=True)

    @declared_attr
    def updated_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime,
            default=datetime.utcnow,
            onupdate=datetime.utcnow,
            nullable=False,
        )

    @declared_attr
    def updated_by(cls) -> Mapped[Optional[str]]:
        return mapped_column(String(100), nullable=True)


class DocumentMixin(TenantMixin, AuditMixin):
    """Base shape for any business document.

    All transactional documents (Sales Order, Delivery, Billing, Purchase Order,
    Accounting Doc, ...) share this header structure.
    """

    @declared_attr
    def id(cls) -> Mapped[int]:
        return mapped_column(Integer, primary_key=True, autoincrement=True)

    @declared_attr
    def document_number(cls) -> Mapped[str]:
        # Note: per-tenant uniqueness is enforced by each concrete table via
        # __table_args__ = (UniqueConstraint("client_id", "document_number"), ...)
        return mapped_column(String(20), index=True, nullable=False)

    @declared_attr
    def document_date(cls) -> Mapped[date]:
        return mapped_column(Date, default=date.today, nullable=False)

    @declared_attr
    def status(cls) -> Mapped[str]:
        return mapped_column(String(20), default=DocStatus.OPEN, index=True, nullable=False)

    @declared_attr
    def reference(cls) -> Mapped[Optional[str]]:
        """Pointer to a related document (e.g. SO -> Delivery -> Billing)."""
        return mapped_column(String(50), nullable=True, index=True)


class MasterDataMixin(TenantMixin, AuditMixin):
    """Base shape for master data (Material, BusinessPartner, ...)."""

    @declared_attr
    def id(cls) -> Mapped[int]:
        return mapped_column(Integer, primary_key=True, autoincrement=True)

    @declared_attr
    def is_active(cls) -> Mapped[bool]:
        from sqlalchemy import Boolean
        return mapped_column(Boolean, default=True, nullable=False)
