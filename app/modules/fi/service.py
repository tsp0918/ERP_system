"""Financial Accounting - business logic.

Provides:
1. CRUD on GL accounts (manual setup of chart of accounts)
2. Manual journal posting (with automatic balance validation)
3. AUTO posting from upstream events:
   - Billing (SD): Dr AR / Cr Revenue
   - Goods Receipt (MM): Dr Inventory / Cr GR-IR clearing
   - Invoice Receipt (MM): Dr GR-IR clearing / Cr AP

The auto-posting layer is decoupled from the source modules: services
in SD/MM call FIPostingService.post_billing(), .post_goods_receipt(),
.post_invoice_receipt() to emit accounting documents. SD/MM modules
remain free of accounting logic.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.numbering import next_number
from app.modules.fi import models, schemas
from app.modules.mm.models import GoodsReceipt, InvoiceReceipt
from app.modules.sd.models import BillingDocument
from app.shared.base_models import DocStatus
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)


# ==================================================================
# Default chart-of-accounts mapping (ERP-internal convention)
# ==================================================================
# Account codes used by the auto-posting engine. Customize via the
# GLAccount master if needed (codes here are just sensible defaults).
DEFAULT_ACCOUNTS = {
    "AR":             ("110000", "Accounts Receivable",        "ASSET",     "BS", "D", True),
    "AP":             ("210000", "Accounts Payable",           "LIABILITY", "BS", "C", True),
    "REVENUE":        ("410000", "Sales Revenue",              "REVENUE",   "PL", "C", False),
    "INVENTORY":      ("130000", "Inventory",                  "ASSET",     "BS", "D", False),
    "GR_IR_CLEARING": ("190000", "GR/IR Clearing",             "ASSET",     "BS", "D", False),
    "TAX_OUTPUT":     ("220000", "Tax Output (Sales VAT)",     "LIABILITY", "BS", "C", False),
    "TAX_INPUT":      ("140000", "Tax Input (Purchase VAT)",   "ASSET",     "BS", "D", False),
    "COGS":           ("510000", "Cost of Goods Sold",         "EXPENSE",   "PL", "D", False),
}


def _seed_fi_ranges() -> None:
    from app.core.numbering import DEFAULT_RANGES
    DEFAULT_RANGES.setdefault(
        "ACCOUNTING", {"prefix": "", "width": 10, "start": 1_000_000_000})


# ==================================================================
# GL Account service
# ==================================================================
class GLAccountService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.GLAccount, db)

    def create(self, payload: schemas.GLAccountCreate, client_id: str,
               user_email: str) -> models.GLAccount:
        existing = self.repo.get_by_field("account_code",
                                          payload.account_code, client_id)
        if existing:
            from app.core.exceptions import DuplicateError
            raise DuplicateError("GLAccount", "account_code", payload.account_code)
        data = payload.model_dump()
        data.update({"client_id": client_id,
                    "created_by": user_email, "updated_by": user_email})
        return self.repo.create(data)

    def ensure_defaults(self, client_id: str, user_email: str) -> None:
        """Create the default chart of accounts if not yet present."""
        for key, (code, name, atype, stmt, balance, is_recon) in DEFAULT_ACCOUNTS.items():
            existing = self.repo.get_by_field("account_code", code, client_id)
            if not existing:
                self.repo.create({
                    "client_id": client_id,
                    "account_code": code, "name": name,
                    "account_type": atype, "statement": stmt,
                    "normal_balance": balance, "is_reconciliation": is_recon,
                    "created_by": user_email, "updated_by": user_email,
                })
        self.db.flush()

    def lookup_by_key(self, client_id: str, key: str) -> str:
        """Translate a logical key (e.g. 'AR') into the configured account code."""
        if key not in DEFAULT_ACCOUNTS:
            raise BusinessRuleError(f"Unknown account key: {key}")
        return DEFAULT_ACCOUNTS[key][0]


# ==================================================================
# Generic posting service - all auto-postings flow through here
# ==================================================================
class FIPostingService:
    """Posts accounting documents in response to upstream business events."""

    def __init__(self, db: Session):
        self.db = db
        _seed_fi_ranges()

    # ---------------------------------------------------------------
    # Manual journal
    # ---------------------------------------------------------------
    def post_manual(self, payload: schemas.ManualJournalCreate,
                    client_id: str, user_email: str) -> models.AccountingDocument:
        return self._create_doc(
            client_id=client_id,
            user_email=user_email,
            document_type=payload.document_type,
            company_code=payload.company_code,
            posting_date=payload.posting_date,
            currency=payload.currency,
            source_module="FI",
            reference=None,
            description=payload.description,
            lines=[(l.gl_account, l.debit_credit, l.amount, l.bp_code,
                   l.cost_center, l.tax_code, l.description)
                   for l in payload.lines],
        )

    # ---------------------------------------------------------------
    # Auto: SD Billing -> AR / Revenue
    # ---------------------------------------------------------------
    def post_billing(self, billing: BillingDocument, client_id: str,
                     user_email: str) -> models.AccountingDocument:
        ar_acct = DEFAULT_ACCOUNTS["AR"][0]
        rev_acct = DEFAULT_ACCOUNTS["REVENUE"][0]
        tax_acct = DEFAULT_ACCOUNTS["TAX_OUTPUT"][0]

        lines = [
            # Dr AR (gross)
            (ar_acct, "D", billing.gross_amount, billing.customer_code,
             None, None, f"AR for billing {billing.document_number}"),
            # Cr Revenue (net)
            (rev_acct, "C", billing.net_amount, None, None, None,
             f"Revenue from {billing.document_number}"),
        ]
        if billing.tax_amount > 0:
            lines.append(
                (tax_acct, "C", billing.tax_amount, None, None, None,
                 f"Output VAT on {billing.document_number}"),
            )

        return self._create_doc(
            client_id=client_id, user_email=user_email,
            document_type="DR",
            company_code=None,
            posting_date=billing.document_date,
            currency=billing.currency,
            source_module="SD",
            reference=billing.document_number,
            description=f"Customer billing {billing.document_number}",
            lines=lines,
        )

    # ---------------------------------------------------------------
    # Auto: MM Goods Receipt -> Inventory / GR-IR
    # ---------------------------------------------------------------
    def post_goods_receipt(self, gr: GoodsReceipt, client_id: str,
                          user_email: str) -> models.AccountingDocument:
        from app.modules.mm.models import PurchaseOrder, PurchaseOrderItem

        po = self.db.query(PurchaseOrder).filter(
            PurchaseOrder.id == gr.purchase_order_id).first()
        if not po:
            raise BusinessRuleError("Source PO missing")

        # Compute amounts: GR has no value of its own, infer from PO unit_price
        po_item_map = {p.id: p for p in po.items}
        total = Decimal("0")
        for gri in gr.items:
            poi = po_item_map.get(gri.po_item_id)
            if poi:
                total += (gri.quantity * poi.unit_price).quantize(Decimal("0.01"))

        if total == 0:
            raise BusinessRuleError(
                f"GR {gr.document_number} has no valuable lines")

        inv_acct = DEFAULT_ACCOUNTS["INVENTORY"][0]
        gri_acct = DEFAULT_ACCOUNTS["GR_IR_CLEARING"][0]

        return self._create_doc(
            client_id=client_id, user_email=user_email,
            document_type="WE",   # SAP convention for GR
            company_code=None,
            posting_date=gr.posting_date,
            currency=po.currency,
            source_module="MM",
            reference=gr.document_number,
            description=f"Goods receipt {gr.document_number}",
            lines=[
                (inv_acct, "D", total, None, None, None,
                 f"Inventory in for {gr.document_number}"),
                (gri_acct, "C", total, po.vendor_code, None, None,
                 f"GR/IR clearing for {gr.document_number}"),
            ],
        )

    # ---------------------------------------------------------------
    # Auto: MM Invoice Receipt -> GR-IR / AP
    # ---------------------------------------------------------------
    def post_invoice_receipt(self, ir: InvoiceReceipt, client_id: str,
                            user_email: str) -> models.AccountingDocument:
        if ir.match_status != "MATCHED":
            raise BusinessRuleError(
                f"IR {ir.document_number} match_status={ir.match_status} - "
                "cannot post until matched"
            )
        gri_acct = DEFAULT_ACCOUNTS["GR_IR_CLEARING"][0]
        ap_acct = DEFAULT_ACCOUNTS["AP"][0]
        tax_acct = DEFAULT_ACCOUNTS["TAX_INPUT"][0]

        lines = [
            (gri_acct, "D", ir.net_amount, ir.vendor_code, None, None,
             f"GR/IR clearing reversal for {ir.document_number}"),
            (ap_acct, "C", ir.gross_amount, ir.vendor_code, None, None,
             f"AP for {ir.document_number}"),
        ]
        if ir.tax_amount > 0:
            lines.append(
                (tax_acct, "D", ir.tax_amount, None, None, None,
                 f"Input VAT for {ir.document_number}"),
            )

        return self._create_doc(
            client_id=client_id, user_email=user_email,
            document_type="RE",
            company_code=None,
            posting_date=ir.posting_date,
            currency=ir.currency,
            source_module="MM",
            reference=ir.document_number,
            description=f"Vendor invoice {ir.document_number}",
            lines=lines,
        )

    # ---------------------------------------------------------------
    # Internal builder
    # ---------------------------------------------------------------
    def _create_doc(self, *, client_id: str, user_email: str,
                    document_type: str, company_code: str | None,
                    posting_date: date, currency: str,
                    source_module: str, reference: str | None,
                    description: str | None,
                    lines: Iterable[tuple]) -> models.AccountingDocument:
        # Validate balance
        debits = sum(amt for _, dc, amt, *_ in lines if dc == "D")
        credits = sum(amt for _, dc, amt, *_ in lines if dc == "C")
        if debits != credits:
            raise BusinessRuleError(
                f"Accounting document does not balance: D={debits} C={credits}"
            )

        doc_number = next_number(self.db, client_id, "ACCOUNTING")
        doc = models.AccountingDocument(
            client_id=client_id,
            document_number=doc_number,
            document_date=posting_date,
            posting_date=posting_date,
            document_type=document_type,
            company_code=company_code,
            currency=currency,
            source_module=source_module,
            reference=reference,
            description=description,
            status=DocStatus.OPEN,
            created_by=user_email,
            updated_by=user_email,
        )
        for idx, (acct, dc, amt, bp, cc, tc, desc) in enumerate(lines, start=1):
            doc.lines.append(models.AccountingLine(
                line_no=idx,
                gl_account=acct, debit_credit=dc, amount=amt,
                currency=currency,
                bp_code=bp, cost_center=cc, tax_code=tc,
                description=desc,
                created_by=user_email, updated_by=user_email,
            ))
        self.db.add(doc)
        self.db.flush()
        logger.info(
            "FI doc %s posted (%s, ref=%s, %s lines)",
            doc.document_number, document_type, reference, len(doc.lines),
        )
        return doc


# ==================================================================
# Trial balance
# ==================================================================
class TrialBalanceService:
    def __init__(self, db: Session):
        self.db = db

    def compute(self, client_id: str, company_code: str | None = None,
                posting_date_from: date | None = None,
                posting_date_to: date | None = None) -> schemas.TrialBalanceResponse:
        q = self.db.query(models.AccountingLine).join(
            models.AccountingDocument,
            models.AccountingLine.accounting_document_id ==
            models.AccountingDocument.id,
        ).filter(
            models.AccountingDocument.client_id == client_id,
            models.AccountingDocument.is_reversed == False,  # noqa: E712
        )
        if company_code:
            q = q.filter(models.AccountingDocument.company_code == company_code)
        if posting_date_from:
            q = q.filter(models.AccountingDocument.posting_date >= posting_date_from)
        if posting_date_to:
            q = q.filter(models.AccountingDocument.posting_date <= posting_date_to)

        lines = q.all()

        # Aggregate per account
        agg: dict[str, dict] = {}
        for l in lines:
            row = agg.setdefault(l.gl_account, {
                "debit_total": Decimal("0"),
                "credit_total": Decimal("0"),
            })
            if l.debit_credit == "D":
                row["debit_total"] += l.amount
            else:
                row["credit_total"] += l.amount

        # Look up account names
        accounts = {a.account_code: a for a in self.db.query(models.GLAccount).filter(
            models.GLAccount.client_id == client_id,
        ).all()}

        rows = []
        total_d = total_c = Decimal("0")
        for code, sums in sorted(agg.items()):
            acct = accounts.get(code)
            net = sums["debit_total"] - sums["credit_total"]
            rows.append(schemas.TrialBalanceRow(
                gl_account=code,
                account_name=acct.name if acct else None,
                account_type=acct.account_type if acct else None,
                debit_total=sums["debit_total"],
                credit_total=sums["credit_total"],
                net_balance=net,
            ))
            total_d += sums["debit_total"]
            total_c += sums["credit_total"]

        return schemas.TrialBalanceResponse(
            company_code=company_code,
            posting_date_from=posting_date_from,
            posting_date_to=posting_date_to,
            rows=rows,
            total_debits=total_d,
            total_credits=total_c,
            is_balanced=(total_d == total_c),
        )
