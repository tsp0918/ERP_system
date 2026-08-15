"""Outbound webhook enqueue helper (E0-5).

Usage:
    from app.shared.webhook_dispatcher import enqueue_webhook
    enqueue_webhook(db, client_id="DEMO", event_type="material.updated", payload_dict={...})

The payload dict is serialized to JSON once here. The delivery worker
(scripts/process_webhook_queue.py) sends that string as-is, so the HMAC
signature computed over the raw bytes is always stable.
"""
import json
import logging
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.shared.webhook_models import TenantMapping, WebhookDelivery

logger = logging.getLogger(__name__)


def get_crm_tenant_id(db: Session, client_id: str) -> str:
    """Resolve CRM tenant ID from tenant_mapping table, fallback to convention."""
    mapping = db.query(TenantMapping).filter(TenantMapping.client_id == client_id).first()
    if mapping:
        return mapping.crm_tenant_id
    return f"CRM_{client_id}"


def enqueue_webhook(
    db: Session,
    client_id: str,
    event_type: str,
    payload_dict: dict,
    target_system: str = "crm",
) -> WebhookDelivery:
    """Add one outbound webhook delivery to the queue.

    The record is added to the session but NOT committed — the caller owns the
    transaction boundary so the webhook is enqueued atomically with the business
    operation that triggered it.
    """
    now = datetime.utcnow()
    delivery = WebhookDelivery(
        event_id=str(uuid4()),
        client_id=client_id,
        target_system=target_system,
        event_type=event_type,
        payload=json.dumps(payload_dict, default=str, ensure_ascii=False),
        status="pending",
        attempt_count=0,
        next_attempt_at=now,
        occurred_at=now,
    )
    db.add(delivery)
    logger.info(
        "[webhook_dispatcher] Enqueued event_type=%s client_id=%s event_id=%s",
        event_type, client_id, delivery.event_id,
    )
    return delivery
