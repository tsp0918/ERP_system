"""IF-32: Commerce check stub — credit and antisocial checks (E3-1, E3-2).

COMMERCE_CHECK_STUB_MODE=true (default):
  Always returns ok. Response structure is production-equivalent.
  stub_mode=true is always logged.
  counterparty_attributes are populated from real ERP data if the BP exists.

Production integration replaces _stub_ok_result with a real provider call.
"""
import logging
import os
from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, Text, Boolean
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import settings
from app.core.database import Base

logger = logging.getLogger(__name__)

STUB_MODE: bool = getattr(settings, "COMMERCE_CHECK_STUB_MODE", True)


# ==================================================================
# DB model
# ==================================================================
class CommerceCheckLog(Base):
    """Audit log for IF-32 commerce check requests."""

    __tablename__ = "commerce_check_logs"

    check_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    request_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "quote" | "engagement"
    crm_quote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    crm_engagement_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bp_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    crm_account_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    request_payload: Mapped[str] = mapped_column(Text, nullable=False)
    result_payload: Mapped[str] = mapped_column(Text, nullable=False)
    overall_result: Mapped[str] = mapped_column(String(20), nullable=False)  # ok | ng | review
    credit_result: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    antisocial_result: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    stub_mode: Mapped[bool] = mapped_column(Boolean, nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


# ==================================================================
# Stub response builder
# ==================================================================
def _stub_ok_result(bp, request_payload: dict) -> dict:
    """Build a production-equivalent response that always passes."""
    attributes = {}
    if bp:
        attributes = {
            "bp_code": bp.bp_code,
            "name": bp.name,
            "country": bp.country,
            "screening_status": bp.screening_status,
            "is_denied_party": bp.is_denied_party,
        }
    return {
        "check_id": str(uuid4()),
        "overall_result": "ok",
        "stub_mode": True,
        "results": {
            "credit": {
                "result": "ok",
                "score": None,
                "message": "[STUB] Credit check skipped — stub mode",
            },
            "antisocial": {
                "result": "ok",
                "score": None,
                "message": "[STUB] Antisocial check skipped — stub mode",
            },
        },
        "counterparty_attributes": attributes,
        "checked_at": datetime.utcnow().isoformat(),
    }


# ==================================================================
# Main entry point
# ==================================================================
def run_commerce_check(db: Session, client_id: str, payload: dict) -> dict:
    """Run a commerce check and persist the log.

    In stub mode, always returns ok and logs stub_mode=true.
    Updates BP credit_check_status and antisocial_check_status if BP found.
    """
    import json

    # Resolve BP from either bp_code or crm_account_id
    from app.modules.mdm.models import BusinessPartner
    bp = None
    bp_code = payload.get("counterparty", {}).get("bp_code")
    crm_account_id = payload.get("counterparty", {}).get("crm_account_id")
    if bp_code:
        bp = db.query(BusinessPartner).filter(
            BusinessPartner.client_id == client_id,
            BusinessPartner.bp_code == bp_code,
        ).first()
    elif crm_account_id:
        bp = db.query(BusinessPartner).filter(
            BusinessPartner.client_id == client_id,
            BusinessPartner.crm_account_id == crm_account_id,
        ).first()

    if STUB_MODE:
        result = _stub_ok_result(bp, payload)
        logger.warning(
            "[commerce_check] STUB MODE — returning ok for client_id=%s bp_code=%s",
            client_id, bp_code or crm_account_id,
        )
    else:
        raise NotImplementedError("Live commerce check provider not integrated")

    # Persist result to BP
    now = datetime.utcnow()
    if bp:
        bp.credit_check_status = result["results"]["credit"]["result"].upper()
        bp.antisocial_check_status = result["results"]["antisocial"]["result"].upper()
        bp.credit_checked_at = now.isoformat()
        bp.antisocial_checked_at = now.isoformat()

    # Audit log
    log = CommerceCheckLog(
        check_id=result["check_id"],
        client_id=client_id,
        request_type=payload.get("request_type", "quote"),
        crm_quote_id=payload.get("crm_quote_id"),
        crm_engagement_id=payload.get("crm_engagement_id"),
        bp_code=bp.bp_code if bp else bp_code,
        crm_account_id=crm_account_id,
        request_payload=json.dumps(payload, default=str),
        result_payload=json.dumps(result, default=str),
        overall_result=result["overall_result"],
        credit_result=result["results"]["credit"]["result"],
        antisocial_result=result["results"]["antisocial"]["result"],
        stub_mode=STUB_MODE,
        checked_at=now,
    )
    db.add(log)

    return result
