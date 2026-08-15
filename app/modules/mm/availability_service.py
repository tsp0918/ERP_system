"""Material Availability Service — cross-module MRP-style view.

Aggregates per-material:
  stock      : StockBalance (MM)
  po_supply  : Open PurchaseOrderItems remaining qty (MM)
  prod_supply: Open/Released ProcessOrders target qty (PP execution)
  so_demand  : Open SalesOrderItems qty (SD)
  comp_demand: Open ProcessOrderComponent remaining qty (PP execution)
  cost       : latest CostComponentSplit.total_cost OR Material.standard_price (MDM/PP)

All queries are pure SQL for efficiency; no cross-module ORM relationship traversal.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session


class MaterialAvailabilityItem(BaseModel):
    material_code: str
    description: str
    material_type: str
    base_unit: str

    # Cost
    standard_cost: Optional[Decimal]
    cost_source: str  # "CCS" (CostComponentSplit) | "MDM" (Material.standard_price) | "—"
    cost_currency: Optional[str]

    # Current stock (sum across plants / storage locations)
    stock_qty: Decimal
    reserved_qty: Decimal
    available_qty: Decimal  # stock - reserved

    # Supply pipeline
    open_po_qty: Decimal        # PO ordered but not yet GR'd
    in_production_qty: Decimal  # ProcessOrders OPEN/RELEASED (finished goods supply)

    # Demand
    open_so_qty: Decimal          # Sales order items (open / released SOs)
    component_demand_qty: Decimal # Raw material needed by open production orders

    # Projected
    projected_qty: Decimal  # available + po_supply + prod_supply - so_demand - comp_demand

    class Config:
        from_attributes = True


def get_material_availability(
    db: Session,
    client_id: str,
    material_type: Optional[str] = None,
    material_code: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
) -> list[MaterialAvailabilityItem]:
    """Return per-material MRP-style availability rows."""

    # Build the mega cross-module aggregation query.
    # Each sub-query is a LEFT JOIN so materials with no stock/orders still appear.
    sql = text("""
        WITH
        -- 1. All materials (base)
        base AS (
            SELECT
                m.material_code,
                m.description,
                m.material_type,
                m.base_unit,
                m.standard_price,
                m.currency AS mat_currency
            FROM materials m
            WHERE m.client_id = :client_id
              AND (:mat_type IS NULL OR m.material_type = :mat_type)
              AND (:mat_code IS NULL OR m.material_code = :mat_code)
              AND m.is_active = 1
            ORDER BY m.material_code
            LIMIT :limit OFFSET :skip
        ),

        -- 2. Stock balances (sum across plants)
        stock AS (
            SELECT
                material_code,
                COALESCE(SUM(unrestricted_qty), 0) AS stock_qty,
                COALESCE(SUM(reserved_qty), 0)     AS reserved_qty
            FROM stock_balances
            WHERE client_id = :client_id
            GROUP BY material_code
        ),

        -- 3. Open PO supply (ordered but not GR'd)
        po_supply AS (
            SELECT
                poi.material_code,
                COALESCE(SUM(poi.quantity - poi.received_quantity), 0) AS open_po_qty
            FROM purchase_order_items poi
            JOIN purchase_orders po ON po.id = poi.purchase_order_id
            WHERE po.client_id = :client_id
              AND po.status NOT IN ('COMPLETED', 'CANCELLED')
              AND poi.quantity > poi.received_quantity
            GROUP BY poi.material_code
        ),

        -- 4. Production supply (open/released process orders — finished goods)
        prod_supply AS (
            SELECT
                material_code,
                COALESCE(SUM(target_quantity - actual_quantity), 0) AS in_production_qty
            FROM process_orders
            WHERE client_id = :client_id
              AND status IN ('OPEN', 'RELEASED', 'DRAFT')
              AND target_quantity > actual_quantity
            GROUP BY material_code
        ),

        -- 5. Open SO demand (open sales order items)
        so_demand AS (
            SELECT
                soi.material_code,
                COALESCE(SUM(soi.quantity), 0) AS open_so_qty
            FROM sales_order_items soi
            JOIN sales_orders so ON so.id = soi.sales_order_id
            WHERE so.client_id = :client_id
              AND so.status IN ('OPEN', 'RELEASED', 'BLOCKED')
            GROUP BY soi.material_code
        ),

        -- 6. Component demand (raw materials needed by open production orders)
        comp_demand AS (
            SELECT
                poc.material_code,
                COALESCE(SUM(poc.planned_quantity - poc.issued_quantity), 0) AS component_demand_qty
            FROM process_order_components poc
            JOIN process_orders po2 ON po2.id = poc.process_order_id
            WHERE po2.client_id = :client_id
              AND po2.status IN ('OPEN', 'RELEASED', 'DRAFT')
              AND poc.planned_quantity > poc.issued_quantity
            GROUP BY poc.material_code
        ),

        -- 7. Latest CostComponentSplit cost
        ccs AS (
            SELECT
                material_code,
                total_cost,
                currency
            FROM (
                SELECT
                    material_code,
                    total_cost,
                    currency,
                    ROW_NUMBER() OVER (PARTITION BY client_id, material_code ORDER BY valid_from DESC) AS rn
                FROM cost_component_splits
                WHERE client_id = :client_id
            ) ranked
            WHERE rn = 1
        )

        SELECT
            b.material_code,
            b.description,
            b.material_type,
            b.base_unit,

            -- Cost: prefer CCS, fall back to MDM standard_price
            CASE
                WHEN ccs.total_cost IS NOT NULL THEN ccs.total_cost
                ELSE b.standard_price
            END                     AS standard_cost,
            CASE
                WHEN ccs.total_cost IS NOT NULL THEN 'CCS'
                WHEN b.standard_price IS NOT NULL THEN 'MDM'
                ELSE '—'
            END                     AS cost_source,
            COALESCE(ccs.currency, b.mat_currency) AS cost_currency,

            -- Stock
            COALESCE(s.stock_qty,    0) AS stock_qty,
            COALESCE(s.reserved_qty, 0) AS reserved_qty,
            COALESCE(s.stock_qty, 0) - COALESCE(s.reserved_qty, 0) AS available_qty,

            -- Supply
            COALESCE(p.open_po_qty,       0) AS open_po_qty,
            COALESCE(ps.in_production_qty, 0) AS in_production_qty,

            -- Demand
            COALESCE(d.open_so_qty,           0) AS open_so_qty,
            COALESCE(cd.component_demand_qty, 0) AS component_demand_qty,

            -- Projected = available + po_supply + prod_supply - so_demand - comp_demand
            (COALESCE(s.stock_qty, 0) - COALESCE(s.reserved_qty, 0)
             + COALESCE(p.open_po_qty, 0)
             + COALESCE(ps.in_production_qty, 0)
             - COALESCE(d.open_so_qty, 0)
             - COALESCE(cd.component_demand_qty, 0)
            ) AS projected_qty

        FROM base b
        LEFT JOIN stock      s  ON s.material_code  = b.material_code
        LEFT JOIN po_supply  p  ON p.material_code  = b.material_code
        LEFT JOIN prod_supply ps ON ps.material_code = b.material_code
        LEFT JOIN so_demand  d  ON d.material_code  = b.material_code
        LEFT JOIN comp_demand cd ON cd.material_code = b.material_code
        LEFT JOIN ccs           ON ccs.material_code = b.material_code
        ORDER BY b.material_code
    """)

    rows = db.execute(sql, {
        "client_id": client_id,
        "mat_type": material_type,
        "mat_code": material_code,
        "limit": limit,
        "skip": skip,
    }).fetchall()

    result = []
    for r in rows:
        result.append(MaterialAvailabilityItem(
            material_code=r.material_code,
            description=r.description,
            material_type=r.material_type,
            base_unit=r.base_unit,
            standard_cost=Decimal(str(r.standard_cost)) if r.standard_cost is not None else None,
            cost_source=r.cost_source or "—",
            cost_currency=r.cost_currency,
            stock_qty=Decimal(str(r.stock_qty or 0)),
            reserved_qty=Decimal(str(r.reserved_qty or 0)),
            available_qty=Decimal(str(r.available_qty or 0)),
            open_po_qty=Decimal(str(r.open_po_qty or 0)),
            in_production_qty=Decimal(str(r.in_production_qty or 0)),
            open_so_qty=Decimal(str(r.open_so_qty or 0)),
            component_demand_qty=Decimal(str(r.component_demand_qty or 0)),
            projected_qty=Decimal(str(r.projected_qty or 0)),
        ))
    return result


def count_materials(db: Session, client_id: str,
                    material_type: Optional[str] = None,
                    material_code: Optional[str] = None) -> int:
    sql = text("""
        SELECT COUNT(*) FROM materials
        WHERE client_id = :client_id
          AND is_active = 1
          AND (:mat_type IS NULL OR material_type = :mat_type)
          AND (:mat_code IS NULL OR material_code = :mat_code)
    """)
    return db.execute(sql, {"client_id": client_id,
                            "mat_type": material_type,
                            "mat_code": material_code}).scalar() or 0
