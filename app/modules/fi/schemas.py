"""Financial Accounting - Pydantic schemas."""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator

from app.shared.base_schemas import AuditFields, ORMModel


# ==================================================================
# GL Account
# ==================================================================
class GLAccountBase(BaseModel):
    account_code: str = Field(..., max_length=20, examples=["110000"])
    name: str = Field(..., max_length=255)
    account_type: str = Field(..., examples=["ASSET", "LIABILITY", "EQUITY",
                                             "REVENUE", "EXPENSE"])
    statement: str = Field(..., examples=["BS", "PL"])
    normal_balance: str = Field("D", examples=["D", "C"])
    is_reconciliation: bool = False


class GLAccountCreate(GLAccountBase):
    pass


class GLAccountUpdate(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


class GLAccountResponse(GLAccountBase, AuditFields):
    id: int
    is_active: bool


# ==================================================================
# Accounting Lines & Documents
# ==================================================================
class AccountingLineCreate(BaseModel):
    gl_account: str
    debit_credit: str = Field(..., pattern="^[DC]$",
                             description="D for debit, C for credit")
    amount: Decimal = Field(..., gt=0)
    bp_code: Optional[str] = None
    cost_center: Optional[str] = None
    tax_code: Optional[str] = None
    description: Optional[str] = None


class AccountingLineResponse(ORMModel):
    id: int
    line_no: int
    gl_account: str
    debit_credit: str
    amount: Decimal
    currency: str
    bp_code: Optional[str]
    cost_center: Optional[str]
    tax_code: Optional[str]
    description: Optional[str]


class ManualJournalCreate(BaseModel):
    """Manual journal entry. Must balance: total debits == total credits."""
    company_code: Optional[str] = None
    posting_date: date = Field(default_factory=date.today)
    document_type: str = Field("SA", description="SA=general, DR=AR, RE=AP, ...")
    currency: str = Field("JPY", min_length=3, max_length=3)
    description: Optional[str] = None
    lines: List[AccountingLineCreate] = Field(..., min_length=2)

    @field_validator("lines")
    @classmethod
    def _balanced(cls, v):
        debits = sum(l.amount for l in v if l.debit_credit == "D")
        credits = sum(l.amount for l in v if l.debit_credit == "C")
        if debits != credits:
            raise ValueError(
                f"Journal does not balance: debits={debits}, credits={credits}"
            )
        return v


class AccountingDocumentResponse(ORMModel):
    id: int
    document_number: str
    document_date: date
    posting_date: date
    document_type: str
    company_code: Optional[str]
    currency: str
    source_module: Optional[str]
    reference: Optional[str]
    description: Optional[str]
    is_reversed: bool
    reversed_by_doc: Optional[str]
    lines: List[AccountingLineResponse]
    created_at: datetime


# ==================================================================
# Trial Balance
# ==================================================================
class TrialBalanceRow(BaseModel):
    gl_account: str
    account_name: Optional[str] = None
    account_type: Optional[str] = None
    debit_total: Decimal
    credit_total: Decimal
    net_balance: Decimal


class TrialBalanceResponse(BaseModel):
    company_code: Optional[str] = None
    posting_date_from: Optional[date] = None
    posting_date_to: Optional[date] = None
    rows: List[TrialBalanceRow]
    total_debits: Decimal
    total_credits: Decimal
    is_balanced: bool
