"""Tests for the FI (Financial Accounting) module."""
import pytest
from decimal import Decimal

from app.modules.fi import schemas as fi_schemas
from app.modules.fi.service import (
    FIPostingService, GLAccountService, TrialBalanceService,
)


@pytest.fixture
def chart_of_accounts(db_session, admin_user):
    GLAccountService(db_session).ensure_defaults(
        admin_user.client_id, admin_user.email,
    )
    db_session.commit()


def test_default_chart_idempotent(db_session, admin_user):
    """Calling ensure_defaults twice does not duplicate rows."""
    svc = GLAccountService(db_session)
    svc.ensure_defaults(admin_user.client_id, admin_user.email)
    db_session.commit()
    count1 = db_session.query(svc.repo.model).count()

    svc.ensure_defaults(admin_user.client_id, admin_user.email)
    db_session.commit()
    count2 = db_session.query(svc.repo.model).count()

    assert count1 == count2 == 8  # 8 default accounts


def test_manual_journal_balanced(db_session, admin_user, chart_of_accounts):
    """Balanced manual journal (10000 cash transfer) is posted."""
    payload = fi_schemas.ManualJournalCreate(
        currency="JPY",
        description="Cash transfer test",
        lines=[
            fi_schemas.AccountingLineCreate(
                gl_account="130000", debit_credit="D", amount=Decimal("10000"),
            ),
            fi_schemas.AccountingLineCreate(
                gl_account="110000", debit_credit="C", amount=Decimal("10000"),
            ),
        ],
    )
    doc = FIPostingService(db_session).post_manual(
        payload, admin_user.client_id, admin_user.email,
    )
    db_session.commit()
    assert len(doc.lines) == 2
    assert doc.document_type == "SA"
    debits = sum(l.amount for l in doc.lines if l.debit_credit == "D")
    credits = sum(l.amount for l in doc.lines if l.debit_credit == "C")
    assert debits == credits == Decimal("10000")


def test_manual_journal_unbalanced_rejected(db_session, admin_user,
                                            chart_of_accounts):
    with pytest.raises(Exception):
        fi_schemas.ManualJournalCreate(
            currency="JPY", description="bad",
            lines=[
                fi_schemas.AccountingLineCreate(
                    gl_account="A", debit_credit="D", amount=Decimal("100"),
                ),
                fi_schemas.AccountingLineCreate(
                    gl_account="B", debit_credit="C", amount=Decimal("99"),
                ),
            ],
        )


def test_post_billing_creates_ar_revenue_split(db_session, admin_user,
                                                chart_of_accounts):
    """Post a fake Billing and verify the standard AR/Revenue split."""
    from datetime import date as date_cls
    from app.modules.sd.models import BillingDocument, BillingItem

    bill = BillingDocument(
        client_id=admin_user.client_id,
        document_number="TEST-BILL-1",
        document_date=date_cls.today(),
        status="OPEN",
        customer_code="BP-X",
        currency="JPY",
        net_amount=Decimal("10000"),
        tax_amount=Decimal("1000"),
        gross_amount=Decimal("11000"),
    )
    db_session.add(bill)
    db_session.flush()

    doc = FIPostingService(db_session).post_billing(
        bill, admin_user.client_id, admin_user.email,
    )
    db_session.commit()

    # 3 lines expected: Dr AR (gross), Cr Revenue (net), Cr Tax (tax)
    assert len(doc.lines) == 3
    by_acct = {l.gl_account: l for l in doc.lines}
    assert by_acct["110000"].debit_credit == "D"   # AR
    assert by_acct["110000"].amount == Decimal("11000")
    assert by_acct["410000"].debit_credit == "C"   # Revenue
    assert by_acct["410000"].amount == Decimal("10000")
    assert by_acct["220000"].debit_credit == "C"   # Output VAT
    assert by_acct["220000"].amount == Decimal("1000")


def test_trial_balance_balanced(db_session, admin_user, chart_of_accounts):
    """Two journal entries posted -> trial balance must balance."""
    svc = FIPostingService(db_session)

    # Entry 1: 1000
    svc.post_manual(fi_schemas.ManualJournalCreate(
        currency="JPY", description="A",
        lines=[
            fi_schemas.AccountingLineCreate(
                gl_account="130000", debit_credit="D", amount=Decimal("1000")),
            fi_schemas.AccountingLineCreate(
                gl_account="210000", debit_credit="C", amount=Decimal("1000")),
        ],
    ), admin_user.client_id, admin_user.email)

    # Entry 2: 2500
    svc.post_manual(fi_schemas.ManualJournalCreate(
        currency="JPY", description="B",
        lines=[
            fi_schemas.AccountingLineCreate(
                gl_account="510000", debit_credit="D", amount=Decimal("2500")),
            fi_schemas.AccountingLineCreate(
                gl_account="110000", debit_credit="C", amount=Decimal("2500")),
        ],
    ), admin_user.client_id, admin_user.email)
    db_session.commit()

    tb = TrialBalanceService(db_session).compute(admin_user.client_id)
    assert tb.is_balanced is True
    assert tb.total_debits == Decimal("3500")
    assert tb.total_credits == Decimal("3500")
    assert len(tb.rows) == 4  # 4 distinct accounts touched
