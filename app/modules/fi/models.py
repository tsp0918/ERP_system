"""Financial Accounting - SQLAlchemy models.

Phase 3 entities:
- GLAccount         : 総勘定元帳の勘定科目
- AccountingDocument: 仕訳伝票ヘッダ (SAP の BKPF 相当)
- AccountingLine    : 仕訳明細 (借方/貸方) (SAP の BSEG 相当)

Document Principle: every business event (billing, GR, IR, ...) emits
an accounting document. The accounting document is the audit-immutable
record of the financial impact.
"""
from datetime import date
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    Boolean, Date, ForeignKey, Integer, Numeric, String, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.shared.base_models import AuditMixin, DocumentMixin, MasterDataMixin


# ==================================================================
# GL Account (Chart of Accounts)
# ==================================================================
class GLAccount(MasterDataMixin, Base):
    """General-ledger account. SAP の SKA1/SKB1 相当 (簡略版)。"""
    __tablename__ = "gl_accounts"
    __table_args__ = (
        UniqueConstraint("client_id", "account_code",
                        name="uq_gl_accounts_client_code"),
    )

    account_code: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # ASSET / LIABILITY / EQUITY / REVENUE / EXPENSE
    account_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # BS or PL
    statement: Mapped[str] = mapped_column(String(2), nullable=False)
    # Normal balance side: D (debit) or C (credit)
    normal_balance: Mapped[str] = mapped_column(String(1), default="D")
    is_reconciliation: Mapped[bool] = mapped_column(
        Boolean, default=False,
        comment="If True, postings to this account require a sub-ledger key (BP/asset)")


# ==================================================================
# Accounting Document
# ==================================================================
class AccountingDocument(DocumentMixin, Base):
    """Accounting document. SAP の BKPF 相当。"""
    __tablename__ = "accounting_documents"
    __table_args__ = (
        UniqueConstraint("client_id", "document_number",
                        name="uq_accounting_documents_client_doc"),
    )

    company_code: Mapped[Optional[str]] = mapped_column(String(10), index=True)
    posting_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)

    # Document type: SA (general)/DR (customer invoice)/RE (vendor invoice)/...
    document_type: Mapped[str] = mapped_column(String(2), default="SA")

    currency: Mapped[str] = mapped_column(String(3), default="JPY")

    # Source link (e.g. BillingDocument.document_number)
    source_module: Mapped[Optional[str]] = mapped_column(String(10))
    # SD / MM / FI

    description: Mapped[Optional[str]] = mapped_column(String(255))

    is_reversed: Mapped[bool] = mapped_column(Boolean, default=False)
    reversed_by_doc: Mapped[Optional[str]] = mapped_column(String(20))

    lines: Mapped[List["AccountingLine"]] = relationship(
        "AccountingLine", back_populates="accounting_document",
        cascade="all, delete-orphan", lazy="selectin",
    )


class AccountingLine(AuditMixin, Base):
    """Accounting line. SAP の BSEG 相当 (簡略版)."""
    __tablename__ = "accounting_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    accounting_document_id: Mapped[int] = mapped_column(
        ForeignKey("accounting_documents.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)

    gl_account: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    debit_credit: Mapped[str] = mapped_column(String(1), nullable=False)  # D or C
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="JPY")

    # Sub-ledger references (optional, used for reconciliation accounts)
    bp_code: Mapped[Optional[str]] = mapped_column(String(20))   # AR/AP
    cost_center: Mapped[Optional[str]] = mapped_column(String(20))
    tax_code: Mapped[Optional[str]] = mapped_column(String(10))

    description: Mapped[Optional[str]] = mapped_column(String(255))

    accounting_document: Mapped["AccountingDocument"] = relationship(
        "AccountingDocument", back_populates="lines")
