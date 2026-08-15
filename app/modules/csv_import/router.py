"""CSV bulk-import endpoints.

POST /import/materials          — materials.csv
POST /import/business-partners  — business_partners.csv
POST /import/sales-orders       — sales_orders.csv  (flat: 1 row = 1 line item)
POST /import/deliveries         — deliveries.csv

Each endpoint returns:
  {
    "total": N,
    "success": M,
    "errors": [{"row": K, "key": "...", "error": "..."}]
  }

Rows are processed independently via SQLite SAVEPOINTs so a bad row
does not roll back previously committed rows.
"""
from __future__ import annotations

import csv
import io
import itertools
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.auth_models import User
from app.core.database import get_db
from app.modules.mdm import schemas as mdm_schemas, service as mdm_service
from app.modules.sd import schemas as sd_schemas, service as sd_service, models as sd_models

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/import", tags=["CSV Import"])


# ──────────────────────────────────────────────────────────────────────
# Response schema
# ──────────────────────────────────────────────────────────────────────

class ImportError(BaseModel):
    row: int
    key: str
    error: str


class ImportResult(BaseModel):
    total: int
    success: int
    errors: list[ImportError]


# ──────────────────────────────────────────────────────────────────────
# Utility helpers
# ──────────────────────────────────────────────────────────────────────

def _parse_csv(content: bytes) -> list[dict[str, str]]:
    text = content.decode("utf-8-sig")  # handle BOM
    reader = csv.DictReader(io.StringIO(text))
    return [row for row in reader]


def _str(row: dict, key: str, default: str | None = None) -> str | None:
    v = row.get(key, "").strip()
    return v if v else default


def _bool(row: dict, key: str, default: bool = False) -> bool:
    v = row.get(key, "").strip().lower()
    if v in ("true", "1", "yes"):
        return True
    if v in ("false", "0", "no", ""):
        return default
    return default


def _decimal(row: dict, key: str, default: Decimal | None = None) -> Decimal | None:
    v = row.get(key, "").strip()
    if not v:
        return default
    try:
        return Decimal(v)
    except InvalidOperation:
        raise ValueError(f"'{key}' is not a valid number: {v!r}")


def _date(row: dict, key: str, default: date | None = None) -> date | None:
    v = row.get(key, "").strip()
    if not v:
        return default
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"'{key}' is not a valid date (use YYYY-MM-DD): {v!r}")


def _required(row: dict, key: str) -> str:
    v = row.get(key, "").strip()
    if not v:
        raise ValueError(f"Required column '{key}' is empty")
    return v


# ──────────────────────────────────────────────────────────────────────
# 1. Materials
# ──────────────────────────────────────────────────────────────────────

@router.post("/materials", response_model=ImportResult)
def import_materials(
    file: UploadFile = File(..., description="CSV file (UTF-8)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-create materials from a CSV file.

    Required columns : description
    Optional columns : material_code, material_type, base_unit, weight_kg,
                       standard_price, currency, hs_code, eccn,
                       country_of_origin, auto_classify
    """
    rows = _parse_csv(file.file.read())
    errors: list[ImportError] = []
    success = 0

    for i, row in enumerate(rows, start=2):  # row 1 = header
        key = _str(row, "material_code") or f"row-{i}"
        try:
            payload = mdm_schemas.MaterialCreate(
                material_code=_str(row, "material_code") or None,
                description=_required(row, "description"),
                material_type=_str(row, "material_type") or "FERT",
                base_unit=_str(row, "base_unit") or "PC",
                weight_kg=_decimal(row, "weight_kg"),
                standard_price=_decimal(row, "standard_price"),
                currency=_str(row, "currency"),
                hs_code=_str(row, "hs_code"),
                eccn=_str(row, "eccn"),
                country_of_origin=_str(row, "country_of_origin"),
                auto_classify=_bool(row, "auto_classify", default=False),
            )
            sp = db.begin_nested()
            mdm_service.MaterialService(db).create(payload, user.client_id, user.email)
            db.flush()
            sp.commit()
            success += 1
        except Exception as exc:
            try:
                sp.rollback()
            except Exception:
                pass
            errors.append(ImportError(row=i, key=key, error=str(exc)))

    db.commit()
    return ImportResult(total=len(rows), success=success, errors=errors)


# ──────────────────────────────────────────────────────────────────────
# 2. Business Partners
# ──────────────────────────────────────────────────────────────────────

@router.post("/business-partners", response_model=ImportResult)
def import_business_partners(
    file: UploadFile = File(..., description="CSV file (UTF-8)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-create business partners from a CSV file.

    Required columns : name, country, roles
    Optional columns : bp_code, bp_type, email, phone, address_line1,
                       address_line2, city, postal_code, credit_limit,
                       payment_terms, currency, auto_screen
    """
    rows = _parse_csv(file.file.read())
    errors: list[ImportError] = []
    success = 0

    for i, row in enumerate(rows, start=2):
        key = _str(row, "bp_code") or _str(row, "name") or f"row-{i}"
        try:
            payload = mdm_schemas.BusinessPartnerCreate(
                bp_code=_str(row, "bp_code") or None,
                bp_type=_str(row, "bp_type") or "ORG",
                name=_required(row, "name"),
                country=_required(row, "country"),
                roles=_str(row, "roles") or "CUSTOMER",
                email=_str(row, "email"),
                phone=_str(row, "phone"),
                address_line1=_str(row, "address_line1"),
                address_line2=_str(row, "address_line2"),
                city=_str(row, "city"),
                postal_code=_str(row, "postal_code"),
                credit_limit=_decimal(row, "credit_limit"),
                payment_terms=_str(row, "payment_terms"),
                currency=_str(row, "currency"),
                auto_screen=_bool(row, "auto_screen", default=False),
            )
            sp = db.begin_nested()
            mdm_service.BusinessPartnerService(db).create(payload, user.client_id, user.email)
            db.flush()
            sp.commit()
            success += 1
        except Exception as exc:
            try:
                sp.rollback()
            except Exception:
                pass
            errors.append(ImportError(row=i, key=key, error=str(exc)))

    db.commit()
    return ImportResult(total=len(rows), success=success, errors=errors)


# ──────────────────────────────────────────────────────────────────────
# 3. Sales Orders  (flat format — group by customer_po_number)
# ──────────────────────────────────────────────────────────────────────

@router.post("/sales-orders", response_model=ImportResult)
def import_sales_orders(
    file: UploadFile = File(..., description="CSV file (UTF-8)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-create sales orders from a flat CSV file.

    One row = one line item.  Rows sharing the same customer_po_number
    are merged into a single Sales Order.

    Required columns : customer_po_number, customer_code, currency,
                       material_code, quantity, unit_price
    Optional columns : document_date (YYYY-MM-DD), requested_delivery_date,
                       incoterms, payment_terms, unit, plant_code,
                       sales_org_code, skip_export_check
    """
    rows = _parse_csv(file.file.read())
    errors: list[ImportError] = []
    success = 0

    # Group rows by customer_po_number (preserve insertion order)
    groups: dict[str, list[tuple[int, dict]]] = {}
    for i, row in enumerate(rows, start=2):
        po = row.get("customer_po_number", "").strip()
        if not po:
            errors.append(ImportError(row=i, key=f"row-{i}",
                                      error="Required column 'customer_po_number' is empty"))
            continue
        groups.setdefault(po, []).append((i, row))

    for po_number, line_rows in groups.items():
        first_row_no, first_row = line_rows[0]
        try:
            # Build items list from all rows in this group
            items: list[sd_schemas.SalesOrderItemCreate] = []
            for row_no, row in line_rows:
                qty = _decimal(row, "quantity")
                if qty is None:
                    raise ValueError(f"Required column 'quantity' is empty (row {row_no})")
                items.append(sd_schemas.SalesOrderItemCreate(
                    material_code=_required(row, "material_code"),
                    description=_str(row, "description"),
                    quantity=qty,
                    unit=_str(row, "unit") or "PC",
                    unit_price=_decimal(row, "unit_price") or Decimal("0"),
                    plant_code=_str(row, "plant_code"),
                ))

            payload = sd_schemas.SalesOrderCreate(
                sales_org_code=_str(first_row, "sales_org_code"),
                customer_code=_required(first_row, "customer_code"),
                customer_po_number=po_number,
                document_date=_date(first_row, "document_date") or date.today(),
                requested_delivery_date=_date(first_row, "requested_delivery_date"),
                incoterms=_str(first_row, "incoterms"),
                payment_terms=_str(first_row, "payment_terms"),
                currency=_required(first_row, "currency"),
                items=items,
                skip_export_check=_bool(first_row, "skip_export_check", default=False),
            )
            sp = db.begin_nested()
            sd_service.SalesOrderService(db).create(payload, user.client_id, user.email)
            db.flush()
            sp.commit()
            success += 1
        except Exception as exc:
            try:
                sp.rollback()
            except Exception:
                pass
            errors.append(ImportError(row=first_row_no, key=po_number, error=str(exc)))

    db.commit()
    return ImportResult(total=len(groups), success=success, errors=errors)


# ──────────────────────────────────────────────────────────────────────
# 4. Deliveries
# ──────────────────────────────────────────────────────────────────────

@router.post("/deliveries", response_model=ImportResult)
def import_deliveries(
    file: UploadFile = File(..., description="CSV file (UTF-8)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Bulk-create delivery orders from a CSV file.

    One row = one delivery (all SO items at full quantity by default).

    Required columns : sales_order_number
    Optional columns : document_date (YYYY-MM-DD), plant_code,
                       actual_delivery_date
    """
    rows = _parse_csv(file.file.read())
    errors: list[ImportError] = []
    success = 0

    for i, row in enumerate(rows, start=2):
        so_num = _str(row, "sales_order_number") or f"row-{i}"
        try:
            so_number = _required(row, "sales_order_number")

            # Resolve SO by document_number
            so = db.query(sd_models.SalesOrder).filter(
                sd_models.SalesOrder.client_id == user.client_id,
                sd_models.SalesOrder.document_number == so_number,
            ).first()
            if not so:
                raise ValueError(f"SalesOrder '{so_number}' not found")

            payload = sd_schemas.DeliveryCreate(
                sales_order_id=so.id,
                document_date=_date(row, "document_date") or date.today(),
                plant_code=_str(row, "plant_code"),
                actual_delivery_date=_date(row, "actual_delivery_date"),
                items=None,  # deliver all SO items at full quantity
            )
            sp = db.begin_nested()
            sd_service.DeliveryService(db).create(payload, user.client_id, user.email)
            db.flush()
            sp.commit()
            success += 1
        except Exception as exc:
            try:
                sp.rollback()
            except Exception:
                pass
            errors.append(ImportError(row=i, key=so_num, error=str(exc)))

    db.commit()
    return ImportResult(total=len(rows), success=success, errors=errors)


def get_import_routers():
    return [router]
