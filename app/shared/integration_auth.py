"""HMAC-SHA256 inbound authentication for system-to-system calls (E0-2, E0-3).

Supported sources:
- "aitm" : AI_TradeManagement → ERP  (AITM_INBOUND_SIGNING_SECRET / AITM_INBOUND_BEARER)
- "crm"  : CRM → ERP               (CRM_INBOUND_SIGNING_SECRET  / CRM_INBOUND_BEARER)

Verification steps (引き継ぎ書 §7 準拠):
  1. Bearer token match
  2. X-Timestamp within ±300 s of server clock
  3. HMAC-SHA256 of "{timestamp}.{raw_body}" matches X-Signature
     - Falls back to _PREVIOUS secret for CRM during key rotation
  4. X-Request-Id deduplication (10-minute TTL via inbound_request_log)

Dev behaviour when secrets are empty strings:
  - Bearer check: skipped (no bearer configured)
  - HMAC check:   skipped with a warning log (allows local dev without secrets)
"""
import hashlib
import hmac
import logging
import time
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.shared.webhook_models import InboundRequestLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_auth_config(source: str) -> tuple[bytes, str, bytes | None]:
    """Return (signing_secret, bearer_token, previous_signing_secret_or_None)."""
    if source == "aitm":
        secret_raw = getattr(settings, "AITM_INBOUND_SIGNING_SECRET", "") or ""
        bearer = getattr(settings, "AITM_INBOUND_BEARER", "") or ""
        return secret_raw.encode(), bearer, None
    elif source == "crm":
        secret_raw = getattr(settings, "CRM_INBOUND_SIGNING_SECRET", "") or ""
        bearer = getattr(settings, "CRM_INBOUND_BEARER", "") or ""
        prev_raw = getattr(settings, "CRM_INBOUND_SIGNING_SECRET_PREVIOUS", "") or ""
        previous: bytes | None = prev_raw.encode() if prev_raw else None
        return secret_raw.encode(), bearer, previous
    else:
        raise ValueError(f"Unknown integration source: {source!r}")


def _compute_sig(secret: bytes, timestamp: str, body: bytes) -> str:
    """HMAC-SHA256 of '{timestamp}.{raw_body}', formatted as 'sha256={hex}'."""
    msg = timestamp.encode() + b"." + body
    return "sha256=" + hmac.new(secret, msg, hashlib.sha256).hexdigest()


def _sig_matches(secret: bytes, timestamp: str, body: bytes, received: str) -> bool:
    if not secret:
        return False
    expected = _compute_sig(secret, timestamp, body)
    return hmac.compare_digest(expected, received)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def verify_inbound(
    request: Request,
    source: str,
    x_signature: str,
    x_timestamp: str,
    x_request_id: str,
    db: Session,
    x_tenant_id: str | None = None,
) -> None:
    """Verify an inbound system-to-system request.

    Raises:
        HTTPException 401 – auth failure (INVALID_BEARER / TIMESTAMP_EXPIRED / INVALID_SIGNATURE)
        HTTPException 409 – replay attack detected (DUPLICATE_REQUEST)
    """
    secret, bearer, previous_secret = _get_auth_config(source)

    # --- 1. Bearer token -------------------------------------------------
    if bearer:
        auth_header = request.headers.get("Authorization", "")
        if auth_header != f"Bearer {bearer}":
            logger.warning("[integration_auth] Bearer mismatch source=%s", source)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="INVALID_BEARER",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Dev mode: when no signing secret is configured, skip timestamp + HMAC.
    if not secret:
        logger.warning(
            "[integration_auth] SIGNING_SECRET not set for source=%s — full auth skipped (dev mode)",
            source,
        )
        return

    # --- 2. Timestamp ±300 s -------------------------------------------
    try:
        ts_int = int(x_timestamp)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="INVALID_TIMESTAMP",
        )
    drift = abs(time.time() - ts_int)
    if drift > 300:
        logger.warning("[integration_auth] Timestamp expired drift=%.1fs source=%s", drift, source)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="TIMESTAMP_EXPIRED",
        )

    # --- 3. HMAC signature ---------------------------------------------
    body = await request.body()
    matched = _sig_matches(secret, x_timestamp, body, x_signature)

    if not matched and previous_secret:
        # Key rotation: try the previous secret
        matched = _sig_matches(previous_secret, x_timestamp, body, x_signature)
        if matched:
            logger.info("[integration_auth] Accepted via rotated key source=%s", source)

    if not matched:
        if not secret:
            # Dev / test: no secret configured — skip HMAC but warn
            logger.warning(
                "[integration_auth] SIGNING_SECRET not set for source=%s — HMAC check skipped", source
            )
        else:
            logger.warning("[integration_auth] Signature mismatch source=%s", source)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="INVALID_SIGNATURE",
            )

    # --- 4. Replay protection ------------------------------------------
    if x_request_id:
        now = datetime.utcnow()
        existing = db.get(InboundRequestLog, x_request_id)
        if existing and existing.expires_at > now:
            logger.warning(
                "[integration_auth] Duplicate request_id=%s source=%s", x_request_id, source
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="DUPLICATE_REQUEST",
            )
        # Insert or replace (expired entries are overwritten)
        db.merge(InboundRequestLog(
            request_id=x_request_id,
            source=source,
            received_at=now,
            expires_at=now + timedelta(minutes=10),
        ))
