"""Financial Accounting - REST endpoints."""
from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.fi import models, schemas, service
from app.shared.base_repository import BaseRepository
from app.shared.base_router import create_crud_router
from app.shared.base_schemas import PaginatedResponse


# ==================================================================
# GL Accounts - generic CRUD
# ==================================================================
gl_router = create_crud_router(
    prefix="/fi/gl-accounts",
    tags=["FI - GL Accounts"],
    model=models.GLAccount,
    create_schema=schemas.GLAccountCreate,
    update_schema=schemas.GLAccountUpdate,
    response_schema=schemas.GLAccountResponse,
    resource_name="GLAccount",
)


@gl_router.post("/ensure-defaults", status_code=status.HTTP_204_NO_CONTENT)
def ensure_default_accounts(db: Session = Depends(get_db),
                            user: User = Depends(get_current_user)):
    """Create the standard chart of accounts (if missing).

    Called once per client. Idempotent.
    """
    service.GLAccountService(db).ensure_defaults(user.client_id, user.email)
    db.commit()


# ==================================================================
# Accounting Documents
# ==================================================================
doc_router = APIRouter(prefix="/fi/accounting-docs",
                      tags=["FI - Accounting Documents"])


@doc_router.get("",
                response_model=PaginatedResponse[schemas.AccountingDocumentResponse])
def list_docs(
    skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
    document_type: str | None = None,
    source_module: str | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.AccountingDocument, db)
    filters = {"document_type": document_type, "source_module": source_module}
    items = repo.list(client_id=user.client_id, filters=filters,
                      skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@doc_router.get("/{doc_id}", response_model=schemas.AccountingDocumentResponse)
def get_doc(doc_id: int, db: Session = Depends(get_db),
            user: User = Depends(get_current_user)):
    d = BaseRepository(models.AccountingDocument, db).get(doc_id, user.client_id)
    if not d:
        raise NotFoundError("AccountingDocument", doc_id)
    return d


# ==================================================================
# Manual journal
# ==================================================================
@doc_router.post("/manual",
                 response_model=schemas.AccountingDocumentResponse,
                 status_code=status.HTTP_201_CREATED)
def post_manual_journal(payload: schemas.ManualJournalCreate,
                       db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    """Post a manually-entered journal. Must balance (debits == credits)."""
    doc = service.FIPostingService(db).post_manual(
        payload, user.client_id, user.email)
    db.commit(); db.refresh(doc)
    return doc


# ==================================================================
# Trial balance
# ==================================================================
@doc_router.get("/trial-balance/", response_model=schemas.TrialBalanceResponse)
def trial_balance(
    company_code: str | None = None,
    posting_date_from: date | None = None,
    posting_date_to: date | None = None,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """Aggregate debits/credits per account for the period."""
    return service.TrialBalanceService(db).compute(
        user.client_id, company_code, posting_date_from, posting_date_to,
    )


# ==================================================================
# Auto-post hooks (manually trigger from existing Billing/GR/IR)
# ==================================================================
@doc_router.post("/auto-post/billing/{billing_id}",
                 response_model=schemas.AccountingDocumentResponse)
def auto_post_billing(billing_id: int,
                     db: Session = Depends(get_db),
                     user: User = Depends(get_current_user)):
    """Generate the AR/Revenue accounting document for an SD Billing."""
    from app.modules.sd.models import BillingDocument
    bill = BaseRepository(BillingDocument, db).get(billing_id, user.client_id)
    if not bill:
        raise NotFoundError("BillingDocument", billing_id)
    doc = service.FIPostingService(db).post_billing(
        bill, user.client_id, user.email)
    db.commit(); db.refresh(doc)
    return doc


@doc_router.post("/auto-post/goods-receipt/{gr_id}",
                 response_model=schemas.AccountingDocumentResponse)
def auto_post_gr(gr_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Generate the Inventory/GR-IR accounting document for an MM GR."""
    from app.modules.mm.models import GoodsReceipt
    gr = BaseRepository(GoodsReceipt, db).get(gr_id, user.client_id)
    if not gr:
        raise NotFoundError("GoodsReceipt", gr_id)
    doc = service.FIPostingService(db).post_goods_receipt(
        gr, user.client_id, user.email)
    db.commit(); db.refresh(doc)
    return doc


@doc_router.post("/auto-post/invoice-receipt/{ir_id}",
                 response_model=schemas.AccountingDocumentResponse)
def auto_post_ir(ir_id: int, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """Generate the GR-IR/AP accounting document for an MM IR (3-way matched)."""
    from app.modules.mm.models import InvoiceReceipt
    ir = BaseRepository(InvoiceReceipt, db).get(ir_id, user.client_id)
    if not ir:
        raise NotFoundError("InvoiceReceipt", ir_id)
    doc = service.FIPostingService(db).post_invoice_receipt(
        ir, user.client_id, user.email)
    db.commit(); db.refresh(doc)
    return doc


def get_fi_routers() -> list[APIRouter]:
    return [gl_router, doc_router]
