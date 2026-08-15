"""Admin REST endpoints for webhook delivery queue management (E0-7).

Endpoints:
    GET    /admin/webhook-delivery            list (filterable by status)
    POST   /admin/webhook-delivery/{id}/retry manual re-queue from DLQ
    DELETE /admin/webhook-delivery/{id}       discard DLQ record
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.shared.webhook_models import WebhookDelivery

router = APIRouter(prefix="/admin/webhook-delivery", tags=["Admin - Webhook Queue"])


class WebhookDeliveryOut(BaseModel):
    event_id: str
    client_id: str
    target_system: str
    event_type: str
    status: str
    attempt_count: int
    next_attempt_at: Optional[datetime] = None
    last_status_code: Optional[int] = None
    last_error: Optional[str] = None
    occurred_at: datetime
    delivered_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


@router.get("", response_model=list[WebhookDeliveryOut])
def list_deliveries(
    status_: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List webhook delivery records. Use ?status=dlq to see the dead-letter queue."""
    q = db.query(WebhookDelivery).filter(WebhookDelivery.client_id == user.client_id)
    if status_:
        q = q.filter(WebhookDelivery.status == status_)
    return q.order_by(WebhookDelivery.occurred_at.desc()).limit(limit).all()


@router.post("/{event_id}/retry", response_model=WebhookDeliveryOut)
def retry_delivery(
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Manually re-queue a failed or DLQ delivery for immediate retry."""
    delivery = db.query(WebhookDelivery).filter(
        WebhookDelivery.event_id == event_id,
        WebhookDelivery.client_id == user.client_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    delivery.status = "pending"
    delivery.next_attempt_at = datetime.utcnow()
    db.commit()
    db.refresh(delivery)
    return delivery


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def discard_delivery(
    event_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Permanently discard a DLQ delivery record."""
    delivery = db.query(WebhookDelivery).filter(
        WebhookDelivery.event_id == event_id,
        WebhookDelivery.client_id == user.client_id,
    ).first()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    db.delete(delivery)
    db.commit()


def get_webhook_admin_routers() -> list[APIRouter]:
    return [router]
