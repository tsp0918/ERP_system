"""CRM → ERP inbound endpoints (Phase 1).

All endpoints use HMAC-SHA256 + Bearer authentication via verify_inbound().
No ERP JWT is required — these are system-to-system calls from CRM.

IF-25  POST /crm/sales-orders            Contract → SalesOrder
IF-24  POST /crm/continuous-monitoring-hold/{so_id}  SUSPENDED status management
"""
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.auth_models import User
from app.core.config import settings
from app.core.database import get_db
from app.core.exceptions import BusinessRuleError, NotFoundError
from app.modules.sd import schemas as sd_schemas, service as sd_service
from app.modules.sd import models as sd_models
from app.shared.base_models import DocStatus
from app.shared.integration_auth import verify_inbound
from app.shared.webhook_dispatcher import enqueue_webhook

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crm", tags=["CRM Integration"])


def _auto_create_customer_bp(db: Session, client_id: str, customer: "CrmCustomerPayload") -> str:
    """Auto-register a CUSTOMER BusinessPartner from CRM inline data.

    Returns the new bp_code. Called when POST /crm/sales-orders receives
    a `customer` object instead of an existing `customer_code`.
    Denied-party screening is triggered via AI_TM (same path as normal BP create).
    """
    from app.modules.mdm import models as mdm_models, schemas as mdm_schemas, service as mdm_service

    bp_payload = mdm_schemas.BusinessPartnerCreate(
        name=customer.name,
        country=customer.country,
        address_line1=customer.address,
        crm_account_id=customer.crm_account_id,
        email=customer.email,
        payment_terms=customer.payment_terms,
        credit_limit=customer.credit_limit,
        roles="CUSTOMER",
        auto_screen=True,
    )
    bp = mdm_service.BusinessPartnerService(db).create(bp_payload, client_id, "crm-integration@system")
    db.flush()
    return bp.bp_code


# ==================================================================
# Auth helper: common header extraction for CRM inbound calls
# ==================================================================
async def _crm_auth(
    request: Request,
    x_signature: str = Header(default=""),
    x_timestamp: str = Header(default=""),
    x_request_id: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    db: Session = Depends(get_db),
) -> Session:
    """Verify CRM HMAC auth and return DB session (for use as dependency)."""
    await verify_inbound(request, "crm", x_signature, x_timestamp, x_request_id, db, x_tenant_id)
    return db


# ==================================================================
# IF-25: CRM Contract → ERP SalesOrder
# ==================================================================
class CrmContractItemPayload(BaseModel):
    material_code: str
    quantity: Decimal = Field(..., gt=0)
    unit: str = "PC"
    unit_price: Decimal = Field(..., ge=0)
    plant_code: Optional[str] = None
    description: Optional[str] = None


class CrmEndUserPayload(BaseModel):
    name: str
    country: str = Field(..., min_length=2, max_length=2)
    address: Optional[str] = None
    crm_account_id: Optional[str] = None


class CrmCustomerPayload(BaseModel):
    """Inline customer registration for new accounts not yet in ERP MDM."""
    name: str
    country: str = Field(..., min_length=2, max_length=2)
    address: Optional[str] = None
    crm_account_id: Optional[str] = None
    email: Optional[str] = None
    payment_terms: Optional[str] = None
    credit_limit: Optional[Decimal] = None


class CrmContractPayload(BaseModel):
    """Inbound payload from CRM for a new contract → SalesOrder (IF-25)."""
    crm_contract_id: str
    crm_engagement_id: Optional[str] = None
    # customer_code: known ERP BP code. Alternatively supply `customer` for auto-registration.
    customer_code: Optional[str] = None
    customer: Optional[CrmCustomerPayload] = None
    currency: str = Field("USD", min_length=3, max_length=3)
    sales_org_code: Optional[str] = None
    customer_po_number: Optional[str] = None
    incoterms: Optional[str] = None
    payment_terms: Optional[str] = None
    requested_delivery_date: Optional[date] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    items: list[CrmContractItemPayload] = Field(..., min_length=1)
    # IF-25 core: CRM may supply an existing AI_TM transaction ID
    aitm_transaction_id: Optional[str] = Field(None,
        description="Existing AI_TM transaction ID — links SO to this review instead of creating new one")
    end_user: Optional[CrmEndUserPayload] = None
    # client_id: informational. ERP always uses settings.CRM_CLIENT_ID for data scoping.
    client_id: str = "DEMO"

    @model_validator(mode="after")
    def _require_customer_or_code(self) -> "CrmContractPayload":
        if not self.customer_code and not self.customer:
            raise ValueError("Either customer_code or customer (inline registration) must be provided")
        return self


class CrmContractResponse(BaseModel):
    erp_sales_order_id: int
    erp_document_number: str
    status: str
    export_check_status: str
    aitm_transaction_id: Optional[str] = None
    end_user_bp_code: Optional[str] = None


@router.post("/sales-orders",
             response_model=CrmContractResponse,
             status_code=status.HTTP_201_CREATED)
async def create_sales_order_from_crm(
    request: Request,
    payload: CrmContractPayload,
    x_signature: str = Header(default=""),
    x_timestamp: str = Header(default=""),
    x_request_id: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """IF-25: Accept a CRM contract and create an ERP SalesOrder.

    When aitm_transaction_id is provided, the SO is linked to the existing AI_TM
    transaction (link_source="crm") instead of triggering a new review.
    """
    await verify_inbound(request, "crm", x_signature, x_timestamp, x_request_id, db, x_tenant_id)

    # Always scope to the configured CRM tenant, regardless of payload.client_id
    crm_client_id = settings.CRM_CLIENT_ID

    # Auto-register customer BP when customer_code is not provided
    customer_code = payload.customer_code
    if not customer_code and payload.customer:
        customer_code = _auto_create_customer_bp(db, crm_client_id, payload.customer)
        logger.info(
            "[crm_router] Auto-created customer BP bp_code=%s for CRM account=%s",
            customer_code, payload.customer.crm_account_id,
        )

    # Map CRM payload → SalesOrderCreate
    end_user_create = None
    if payload.end_user:
        end_user_create = sd_schemas.EndUserCreate(
            name=payload.end_user.name,
            country=payload.end_user.country,
            address=payload.end_user.address,
            crm_account_id=payload.end_user.crm_account_id,
        )

    so_create = sd_schemas.SalesOrderCreate(
        sales_org_code=payload.sales_org_code,
        customer_code=customer_code,
        customer_po_number=payload.customer_po_number,
        currency=payload.currency,
        incoterms=payload.incoterms,
        payment_terms=payload.payment_terms,
        requested_delivery_date=payload.requested_delivery_date,
        contract_start_date=payload.contract_start_date,
        contract_end_date=payload.contract_end_date,
        items=[
            sd_schemas.SalesOrderItemCreate(
                material_code=item.material_code,
                quantity=item.quantity,
                unit=item.unit,
                unit_price=item.unit_price,
                plant_code=item.plant_code,
                description=item.description,
            )
            for item in payload.items
        ],
        crm_contract_id=payload.crm_contract_id,
        crm_engagement_id=payload.crm_engagement_id,
        aitm_transaction_id=payload.aitm_transaction_id,
        end_user=end_user_create,
    )

    svc = sd_service.SalesOrderService(db)
    so = svc.create(so_create, crm_client_id, "crm-integration@system")
    db.commit()
    db.refresh(so)

    # IF-26 webhook: notify CRM that SO was created
    enqueue_webhook(db, crm_client_id, "sales_order.created", {
        "erp_sales_order_id": so.id,
        "erp_document_number": so.document_number,
        "crm_contract_id": payload.crm_contract_id,
        "status": so.status,
        "export_check_status": so.export_check_status,
    })
    db.commit()

    logger.info(
        "[crm_router] IF-25 SO created so_id=%d so_number=%s crm_contract=%s aitm_tx=%s",
        so.id, so.document_number, payload.crm_contract_id, payload.aitm_transaction_id,
    )
    return CrmContractResponse(
        erp_sales_order_id=so.id,
        erp_document_number=so.document_number,
        status=so.status,
        export_check_status=so.export_check_status,
        aitm_transaction_id=so.aitm_transaction_id,
        end_user_bp_code=so.end_user_bp_code,
    )


# ==================================================================
# IF-24: Continuous Monitoring Hold (SUSPENDED / release)
# ==================================================================
class MonitoringHoldRequest(BaseModel):
    action: str = Field(..., pattern="^(hold|release)$",
        description="'hold' sets SUSPENDED; 'release' restores OPEN")
    reason: Optional[str] = None
    client_id: str = "DEMO"


class MonitoringHoldResponse(BaseModel):
    erp_sales_order_id: int
    erp_document_number: str
    status: str
    action: str


@router.post("/continuous-monitoring-hold/{so_id}",
             response_model=MonitoringHoldResponse)
async def continuous_monitoring_hold(
    so_id: int = Path(..., description="ERP SalesOrder internal ID"),
    request: Request = None,
    payload: MonitoringHoldRequest = None,
    x_signature: str = Header(default=""),
    x_timestamp: str = Header(default=""),
    x_request_id: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """IF-24: Set or release a continuous monitoring hold (SUSPENDED status) on a SalesOrder."""
    await verify_inbound(request, "crm", x_signature, x_timestamp, x_request_id, db, x_tenant_id)

    crm_client_id = settings.CRM_CLIENT_ID
    so = db.query(sd_models.SalesOrder).filter(
        sd_models.SalesOrder.id == so_id,
        sd_models.SalesOrder.client_id == crm_client_id,
    ).first()
    if not so:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SalesOrder not found")

    if payload.action == "hold":
        if so.status not in {DocStatus.OPEN, DocStatus.RELEASED}:
            raise BusinessRuleError(
                f"Cannot suspend SO {so.document_number} in status {so.status}"
            )
        so.status = DocStatus.SUSPENDED
        so.updated_by = "crm-integration@system"
        event_type = "sales_order.suspended"
    else:  # release
        if so.status != DocStatus.SUSPENDED:
            raise BusinessRuleError(
                f"SO {so.document_number} is not SUSPENDED (current: {so.status})"
            )
        so.status = DocStatus.OPEN
        so.updated_by = "crm-integration@system"
        event_type = "sales_order.resumed"

    enqueue_webhook(db, crm_client_id, event_type, {
        "erp_sales_order_id": so.id,
        "erp_document_number": so.document_number,
        "status": so.status,
        "reason": payload.reason,
    })
    db.commit()
    db.refresh(so)

    logger.info(
        "[crm_router] IF-24 %s so_id=%d so_number=%s reason=%s",
        payload.action, so.id, so.document_number, payload.reason,
    )
    return MonitoringHoldResponse(
        erp_sales_order_id=so.id,
        erp_document_number=so.document_number,
        status=so.status,
        action=payload.action,
    )


# ==================================================================
# IF-31: CRM → ERP Customer Return  (E4-2)
# ==================================================================
class CrmReturnItemPayload(BaseModel):
    material_code: str
    quantity: Decimal = Field(..., gt=0)
    unit: str = "PC"
    so_item_id: Optional[int] = None
    delivery_item_id: Optional[int] = None


class CrmReturnPayload(BaseModel):
    """IF-31 inbound payload from CRM requesting a customer return."""
    crm_return_id: str
    crm_contract_id: Optional[str] = None
    erp_sales_order_id: Optional[int] = None
    erp_delivery_id: Optional[int] = None
    return_reason: Optional[str] = None
    return_date: Optional[date] = None
    items: list[CrmReturnItemPayload] = Field(..., min_length=1)
    client_id: str = "DEMO"


class CrmReturnResponse(BaseModel):
    erp_return_id: int
    erp_document_number: str
    status: str
    crm_return_id: str
    item_count: int


@router.post("/returns",
             response_model=CrmReturnResponse,
             status_code=status.HTTP_201_CREATED)
async def create_return_from_crm(
    request: Request,
    payload: CrmReturnPayload,
    x_signature: str = Header(default=""),
    x_timestamp: str = Header(default=""),
    x_request_id: str = Header(default=""),
    x_tenant_id: str = Header(default=""),
    db: Session = Depends(get_db),
):
    """IF-31: Accept a CRM return request and create a ReturnDocument.

    The return is linked to the referenced SO/Delivery. IF-30 webhook is enqueued
    to notify CRM that the ERP return document is created.
    """
    await verify_inbound(request, "crm", x_signature, x_timestamp, x_request_id, db, x_tenant_id)

    from app.core.numbering import next_number
    from app.modules.sd.models import ReturnDocument, ReturnDocumentItem
    from app.shared.base_models import DocStatus

    crm_client_id = settings.CRM_CLIENT_ID

    # Validate SO / Delivery references
    so = None
    delivery = None
    if payload.erp_sales_order_id:
        so = db.query(sd_models.SalesOrder).filter(
            sd_models.SalesOrder.id == payload.erp_sales_order_id,
            sd_models.SalesOrder.client_id == crm_client_id,
        ).first()
        if not so:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SalesOrder {payload.erp_sales_order_id} not found",
            )
    if payload.erp_delivery_id:
        delivery = db.query(sd_models.Delivery).filter(
            sd_models.Delivery.id == payload.erp_delivery_id,
            sd_models.Delivery.client_id == crm_client_id,
        ).first()
        if not delivery:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Delivery {payload.erp_delivery_id} not found",
            )

    return_number = next_number(db, crm_client_id, "RETURN")

    ret = ReturnDocument(
        client_id=crm_client_id,
        document_number=return_number,
        document_date=payload.return_date,
        status=DocStatus.OPEN,
        sales_order_id=so.id if so else None,
        delivery_id=delivery.id if delivery else None,
        crm_return_id=payload.crm_return_id,
        crm_contract_id=payload.crm_contract_id or (so.crm_contract_id if so else None),
        return_reason=payload.return_reason,
        return_date=payload.return_date,
        created_by="crm-integration@system",
        updated_by="crm-integration@system",
    )

    for idx, item in enumerate(payload.items, start=1):
        ret.items.append(ReturnDocumentItem(
            client_id=crm_client_id,
            item_no=idx * 10,
            material_code=item.material_code,
            quantity=item.quantity,
            unit=item.unit,
            so_item_id=item.so_item_id,
            delivery_item_id=item.delivery_item_id,
            created_by="crm-integration@system",
            updated_by="crm-integration@system",
        ))

    db.add(ret)
    db.flush()

    # IF-30: notify CRM that return document is created (E4-2 + E4-4)
    enqueue_webhook(db, crm_client_id, "return.posted", {
        "erp_return_id": ret.id,
        "erp_document_number": ret.document_number,
        "crm_return_id": payload.crm_return_id,
        "crm_contract_id": ret.crm_contract_id,
        "status": ret.status,
        "item_count": len(ret.items),
    })

    db.commit()
    db.refresh(ret)

    logger.info(
        "[crm_router] IF-31 return created ret_id=%d ret_number=%s crm_return=%s",
        ret.id, ret.document_number, payload.crm_return_id,
    )
    return CrmReturnResponse(
        erp_return_id=ret.id,
        erp_document_number=ret.document_number,
        status=ret.status,
        crm_return_id=payload.crm_return_id,
        item_count=len(ret.items),
    )


def get_crm_sd_routers() -> list[APIRouter]:
    return [router]
