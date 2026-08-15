"""Webhook delivery worker — polls the queue and delivers pending events to CRM (E0-6).

Run as a long-running process alongside the ERP server:
    python scripts/process_webhook_queue.py

Behaviour:
- Polls webhook_delivery every WEBHOOK_WORKER_INTERVAL_SEC seconds (default 30)
- Delivers pending/failed records whose next_attempt_at <= now (up to 50 per batch)
- On success (2xx): status → "delivered"
- On failure:       attempt_count += 1, next_attempt_at = exponential backoff + jitter
- After WEBHOOK_MAX_ATTEMPTS (default 6): status → "dlq" (dead-letter queue)
- DLQ records can be retried via POST /admin/webhook-delivery/{id}/retry
"""
import hashlib
import hmac
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from app.core.config import settings
from app.core.database import SessionLocal
from app.shared.webhook_models import TenantMapping, WebhookDelivery

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] webhook-worker: %(message)s",
)
logger = logging.getLogger("webhook-worker")

MAX_ATTEMPTS = settings.WEBHOOK_MAX_ATTEMPTS
CONNECT_TIMEOUT = float(settings.WEBHOOK_CONNECT_TIMEOUT_SEC)
READ_TIMEOUT = float(settings.WEBHOOK_READ_TIMEOUT_SEC)
INTERVAL = settings.WEBHOOK_WORKER_INTERVAL_SEC
BACKOFF_BASE = 30  # seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _crm_tenant_id(db, client_id: str) -> str:
    mapping = db.query(TenantMapping).filter(TenantMapping.client_id == client_id).first()
    return mapping.crm_tenant_id if mapping else f"CRM_{client_id}"


def _compute_sig(secret: bytes, timestamp: str, body: bytes) -> str:
    msg = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret, msg, hashlib.sha256).hexdigest()


def _next_attempt_at(attempt_count: int) -> datetime:
    """Exponential backoff with jitter: base * 2^n + uniform(0, base)."""
    delay = BACKOFF_BASE * (2 ** attempt_count) + random.uniform(0, BACKOFF_BASE)
    max_delay = 3600  # cap at 1 hour
    return datetime.utcnow() + timedelta(seconds=min(delay, max_delay))


_PATH_MAP = {
    "material.updated":      lambda: settings.CRM_WEBHOOK_PATH_MATERIAL_UPDATED,
    "bp.updated":            lambda: settings.CRM_WEBHOOK_PATH_BP_UPDATED,
    "delivery.goods_issued": lambda: settings.CRM_WEBHOOK_PATH_DELIVERY_POSTED,
    "billing.posted":        lambda: settings.CRM_WEBHOOK_PATH_BILLING_POSTED,
    "return.posted":         lambda: settings.CRM_WEBHOOK_PATH_RETURN_POSTED,
}


def _event_path(event_type: str) -> str:
    factory = _PATH_MAP.get(event_type)
    if factory:
        return factory()
    # Fallback: derive path from event_type (e.g. "sales_order.created" → "/webhooks/erp/sales-order-created")
    return "/webhooks/erp/" + event_type.replace(".", "-").replace("_", "-")


# ---------------------------------------------------------------------------
# Delivery logic
# ---------------------------------------------------------------------------

def _deliver(d: WebhookDelivery, db) -> None:
    """Attempt a single delivery. Mutates d; caller commits."""
    base_url = settings.CRM_WEBHOOK_BASE_URL
    if not base_url:
        logger.warning("CRM_WEBHOOK_BASE_URL not configured — event_id=%s moved to failed", d.event_id)
        d.attempt_count += 1
        d.last_error = "CRM_WEBHOOK_BASE_URL not configured"
        d.status = "dlq" if d.attempt_count >= MAX_ATTEMPTS else "failed"
        if d.status == "failed":
            d.next_attempt_at = _next_attempt_at(d.attempt_count)
        return

    body = d.payload.encode("utf-8")
    ts = str(int(time.time()))
    signing_secret = (settings.CRM_WEBHOOK_SIGNING_SECRET or "").encode()
    sig = _compute_sig(signing_secret, ts, body) if signing_secret else "sha256=unsigned"
    bearer = settings.CRM_WEBHOOK_BEARER or ""
    tenant_id = _crm_tenant_id(db, d.client_id)
    url = base_url.rstrip("/") + _event_path(d.event_type)

    headers = {
        "Authorization": f"Bearer {bearer}",
        "X-Signature": sig,
        "X-Timestamp": ts,
        "X-Request-Id": d.event_id,
        "X-Tenant-Id": tenant_id,
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(
            timeout=httpx.Timeout(connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=10.0, pool=5.0)
        ) as client:
            resp = client.post(url, content=body, headers=headers)
        d.last_status_code = resp.status_code
        if 200 <= resp.status_code < 300:
            d.status = "delivered"
            d.delivered_at = datetime.utcnow()
            logger.info("Delivered event_id=%s → %s HTTP %d", d.event_id, url, resp.status_code)
            return
        err = f"HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as exc:
        d.last_status_code = None
        err = str(exc)[:500]

    # Failure path
    d.attempt_count += 1
    d.last_error = err
    logger.warning(
        "Delivery failed event_id=%s attempt=%d error=%s", d.event_id, d.attempt_count, err
    )
    if d.attempt_count >= MAX_ATTEMPTS:
        d.status = "dlq"
        logger.error("DLQ event_id=%s after %d attempts", d.event_id, d.attempt_count)
    else:
        d.status = "failed"
        d.next_attempt_at = _next_attempt_at(d.attempt_count)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def _run_batch(db) -> int:
    now = datetime.utcnow()
    pending = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.status.in_(["pending", "failed"]),
            WebhookDelivery.next_attempt_at <= now,
        )
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(50)
        .all()
    )
    for d in pending:
        _deliver(d, db)
    if pending:
        db.commit()
    return len(pending)


def main() -> None:
    logger.info(
        "Webhook delivery worker started — interval=%ds max_attempts=%d", INTERVAL, MAX_ATTEMPTS
    )
    while True:
        try:
            with SessionLocal() as db:
                count = _run_batch(db)
            if count:
                logger.info("Processed %d delivery record(s)", count)
        except Exception:
            logger.exception("Unexpected error in delivery loop — continuing")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
