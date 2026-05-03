"""SD REST endpoints."""
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.modules.sd import models, schemas, service
from app.shared.base_repository import BaseRepository
from app.shared.base_schemas import PaginatedResponse


# ------------------------------------------------------------------
# Sales Orders
# ------------------------------------------------------------------
so_router = APIRouter(prefix="/sd/sales-orders", tags=["SD - Sales Orders"])


@so_router.get("", response_model=PaginatedResponse[schemas.SalesOrderResponse])
def list_sos(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    customer_code: str | None = None,
    status_: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.SalesOrder, db)
    filters = {"customer_code": customer_code, "status": status_}
    items = repo.list(client_id=user.client_id, filters=filters, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id, filters=filters)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@so_router.get("/{so_id}", response_model=schemas.SalesOrderResponse)
def get_so(
    so_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    so = BaseRepository(models.SalesOrder, db).get(so_id, client_id=user.client_id)
    if not so:
        raise NotFoundError("SalesOrder", so_id)
    return so


@so_router.post("", response_model=schemas.SalesOrderResponse,
                status_code=status.HTTP_201_CREATED)
def create_so(
    payload: schemas.SalesOrderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create Sales Order. Triggers AI_TradeManagement export-check by default.

    If the export check returns BLOCKED, the SO is created with status=BLOCKED
    and cannot be released until resolved.
    """
    so = service.SalesOrderService(db).create(payload, user.client_id, user.email)
    db.commit()
    db.refresh(so)
    return so


@so_router.post("/{so_id}/release", response_model=schemas.SalesOrderResponse)
def release_so(
    so_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    so = service.SalesOrderService(db).release(so_id, user.client_id, user.email)
    db.commit()
    db.refresh(so)
    return so


@so_router.post("/{so_id}/recheck-export", response_model=schemas.SalesOrderResponse)
def recheck_export(
    so_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Re-run the AI_TradeManagement export check (e.g. after material reclassification)."""
    from app.modules.gts.service import GTSService
    from app.modules.mdm.models import BusinessPartner

    so = BaseRepository(models.SalesOrder, db).get(so_id, client_id=user.client_id)
    if not so:
        raise NotFoundError("SalesOrder", so_id)
    customer = db.query(BusinessPartner).filter(
        BusinessPartner.bp_code == so.customer_code,
        BusinessPartner.client_id == user.client_id,
    ).first()
    GTSService(db).check_export(so, customer)
    db.commit()
    db.refresh(so)
    return so


# ------------------------------------------------------------------
# Deliveries
# ------------------------------------------------------------------
delivery_router = APIRouter(prefix="/sd/deliveries", tags=["SD - Deliveries"])


@delivery_router.get("", response_model=PaginatedResponse[schemas.DeliveryResponse])
def list_deliveries(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.Delivery, db)
    items = repo.list(client_id=user.client_id, skip=skip, limit=limit)
    total = repo.count(client_id=user.client_id)
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@delivery_router.get("/{delivery_id}", response_model=schemas.DeliveryResponse)
def get_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    d = BaseRepository(models.Delivery, db).get(delivery_id, client_id=user.client_id)
    if not d:
        raise NotFoundError("Delivery", delivery_id)
    return d


@delivery_router.post("", response_model=schemas.DeliveryResponse,
                      status_code=status.HTTP_201_CREATED)
def create_delivery(
    payload: schemas.DeliveryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    delivery = service.DeliveryService(db).create(payload, user.client_id, user.email)
    db.commit()
    db.refresh(delivery)
    return delivery


# ------------------------------------------------------------------
# Billing
# ------------------------------------------------------------------
billing_router = APIRouter(prefix="/sd/billing", tags=["SD - Billing"])


@billing_router.get("", response_model=PaginatedResponse[schemas.BillingResponse])
def list_billings(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    customer_code: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    repo = BaseRepository(models.BillingDocument, db)
    items = repo.list(
        client_id=user.client_id,
        filters={"customer_code": customer_code},
        skip=skip, limit=limit,
    )
    total = repo.count(client_id=user.client_id, filters={"customer_code": customer_code})
    return PaginatedResponse(items=items, total=total, skip=skip, limit=limit)


@billing_router.get("/{billing_id}", response_model=schemas.BillingResponse)
def get_billing(
    billing_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    b = BaseRepository(models.BillingDocument, db).get(billing_id, client_id=user.client_id)
    if not b:
        raise NotFoundError("BillingDocument", billing_id)
    return b


@billing_router.post("", response_model=schemas.BillingResponse,
                     status_code=status.HTTP_201_CREATED)
def create_billing(
    payload: schemas.BillingCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bill = service.BillingService(db).create_from_delivery(payload, user.client_id, user.email)
    db.commit()
    db.refresh(bill)
    return bill


@billing_router.get("/{billing_id}/pdf",
                    responses={200: {"content": {"application/pdf": {}}}})
def download_billing_pdf(
    billing_id: int,
    variant: str = Query("enduser",
        description="Layout variant: intercompany / distributor / enduser"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Generate and stream a PDF invoice in the chosen layout variant.

    Three variants are available:
    - intercompany : group-internal transfer (e.g. JP HQ -> TW subsidiary)
    - distributor  : authorized reseller
    - enduser      : direct end-user sale (default)
    """
    from fastapi import Response
    from app.modules.mdm.models import BusinessPartner, Company, Material
    from app.modules.sd.invoice_pdf import InvoicePdfGenerator

    bill = BaseRepository(models.BillingDocument, db).get(
        billing_id, client_id=user.client_id)
    if not bill:
        raise NotFoundError("BillingDocument", billing_id)

    customer = db.query(BusinessPartner).filter(
        BusinessPartner.bp_code == bill.customer_code,
        BusinessPartner.client_id == user.client_id,
    ).first()
    if not customer:
        raise NotFoundError("Customer", bill.customer_code)

    # Pick the issuing company - JP HQ if present, otherwise first one
    seller = db.query(Company).filter(
        Company.client_id == user.client_id,
        Company.country == "JP",
    ).first() or db.query(Company).filter(
        Company.client_id == user.client_id,
    ).first()
    if not seller:
        raise NotFoundError("SellerCompany", "any")

    codes = {it.material_code for it in bill.items}
    descs = {m.material_code: m.description for m in db.query(Material).filter(
        Material.client_id == user.client_id,
        Material.material_code.in_(codes),
    ).all()}

    pdf_bytes = InvoicePdfGenerator(variant=variant).render(
        billing=bill, customer=customer, seller_company=seller,
        material_descriptions=descs,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition":
                f'attachment; filename="invoice_{bill.document_number}.pdf"',
        },
    )


def get_sd_routers() -> list[APIRouter]:
    return [so_router, delivery_router, billing_router]
