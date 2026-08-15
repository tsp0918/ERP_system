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


# ==================================================================
# Sales Forecast (PIR)
# ==================================================================
from typing import Optional as _Opt
from pydantic import BaseModel as _BM
from decimal import Decimal as _Dec

forecast_router = APIRouter(prefix="/sd/forecasts", tags=["SD - Sales Forecast"])


class SalesForecastCreate(_BM):
    material_code: str
    plant_code: _Opt[str] = None
    customer_code: _Opt[str] = None
    sales_org_code: _Opt[str] = None
    year: int
    month: int
    forecast_quantity: _Dec
    quantity_unit: str = "KG"
    forecast_value: _Dec = _Dec("0")
    currency: str = "JPY"
    version: str = "BASELINE"
    notes: _Opt[str] = None


class SalesForecastResponse(_BM):
    id: int
    material_code: str
    plant_code: _Opt[str]
    customer_code: _Opt[str]
    year: int
    month: int
    forecast_quantity: _Dec
    quantity_unit: str
    forecast_value: _Dec
    currency: str
    version: str
    notes: _Opt[str]

    class Config:
        from_attributes = True


@forecast_router.get("", response_model=list[SalesForecastResponse])
def list_forecasts(
    material_code: _Opt[str] = Query(None),
    year: _Opt[int] = Query(None),
    version: str = Query("BASELINE"),
    skip: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.modules.sd.models import SalesForecast
    q = db.query(SalesForecast).filter(
        SalesForecast.client_id == user.client_id,
        SalesForecast.version == version,
    )
    if material_code:
        q = q.filter(SalesForecast.material_code == material_code)
    if year:
        q = q.filter(SalesForecast.year == year)
    return q.order_by(SalesForecast.year, SalesForecast.month,
                      SalesForecast.material_code).offset(skip).limit(limit).all()


@forecast_router.put("", response_model=SalesForecastResponse,
                     summary="Upsert a monthly sales forecast")
def upsert_forecast(
    body: SalesForecastCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.modules.sd.models import SalesForecast
    existing = db.query(SalesForecast).filter(
        SalesForecast.client_id == user.client_id,
        SalesForecast.material_code == body.material_code,
        SalesForecast.year == body.year,
        SalesForecast.month == body.month,
        SalesForecast.version == body.version,
    ).first()
    if existing:
        for k, v in body.model_dump().items():
            setattr(existing, k, v)
        existing.updated_by = user.email
    else:
        existing = SalesForecast(**body.model_dump(),
                                 client_id=user.client_id,
                                 created_by=user.email, updated_by=user.email)
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


@forecast_router.get("/summary", summary="Monthly forecast vs actual summary")
def forecast_vs_actual(
    year: int, version: str = "BASELINE",
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    from app.modules.sd.models import SalesForecast, SalesOrderItem, SalesOrder
    from sqlalchemy import func
    forecasts = db.query(SalesForecast).filter(
        SalesForecast.client_id == user.client_id,
        SalesForecast.year == year,
        SalesForecast.version == version,
    ).all()
    # Actual SO completed amounts per material per month
    actuals = db.execute(
        __import__('sqlalchemy').text("""
            SELECT strftime('%m', so.document_date) AS month,
                   soi.material_code,
                   SUM(soi.quantity) AS actual_qty,
                   SUM(soi.net_amount) AS actual_value
            FROM sales_order_items soi
            JOIN sales_orders so ON so.id = soi.sales_order_id
            WHERE so.client_id = :cid
              AND strftime('%Y', so.document_date) = :yr
              AND so.status = 'COMPLETED'
            GROUP BY month, soi.material_code
        """),
        {"cid": user.client_id, "yr": str(year)}
    ).fetchall()
    actual_map = {(int(r.month), r.material_code): {"qty": float(r.actual_qty), "value": float(r.actual_value)}
                  for r in actuals}
    result = []
    for f in forecasts:
        actual = actual_map.get((f.month, f.material_code), {"qty": 0, "value": 0})
        result.append({
            "material_code": f.material_code, "year": f.year, "month": f.month,
            "forecast_qty": float(f.forecast_quantity),
            "actual_qty": actual["qty"],
            "attainment_pct": round(actual["qty"] / float(f.forecast_quantity) * 100, 1) if f.forecast_quantity else None,
            "forecast_value": float(f.forecast_value),
            "actual_value": actual["value"],
        })
    return sorted(result, key=lambda x: (x["month"], x["material_code"]))


def get_sd_routers() -> list[APIRouter]:
    return [so_router, delivery_router, billing_router, forecast_router]
