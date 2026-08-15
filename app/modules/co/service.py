"""CO (Controlling) — business logic.

Services:
1. AssetService         : CRUD + calculate machine_rate from AssetCostRate
2. CostCenterService    : CRUD + calculate labor_rate / overhead_rate from CostCenterBudget
3. WorkCenterRateService: Push calculated rates back to PP work_centers
4. ActualCostService    : Post actual costs with auto-variance calculation
5. CostEstimateService  : CRUD + De Minimis (US EAR 25%) calculation
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.modules.co import models, schemas
from app.modules.pp.models import WorkCenter
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
# Asset / Machine Rate
# ══════════════════════════════════════════════════════════════════════

class AssetService:
    def __init__(self, db: Session):
        self.db = db
        self._assets = BaseRepository(models.AssetMaster, db)
        self._rates  = BaseRepository(models.AssetCostRate, db)

    # --- AssetMaster CRUD ---

    def get_asset(self, client_id: str, asset_code: str) -> models.AssetMaster:
        items = self._assets.list(client_id=client_id,
                                  filters={"asset_code": asset_code})
        if not items:
            raise NotFoundError(f"AssetMaster '{asset_code}' not found")
        return items[0]

    def list_assets(self, client_id: str, skip: int, limit: int) -> list:
        return self._assets.list(client_id=client_id, skip=skip, limit=limit)

    def create_asset(self, client_id: str, data: schemas.AssetMasterCreate,
                     user_email: str) -> models.AssetMaster:
        asset = models.AssetMaster(**data.model_dump(),
                                   client_id=client_id,
                                   created_by=user_email,
                                   updated_by=user_email)
        self.db.add(asset)
        self.db.flush()
        return asset

    def update_asset(self, client_id: str, asset_code: str,
                     data: schemas.AssetMasterUpdate,
                     user_email: str) -> models.AssetMaster:
        asset = self.get_asset(client_id, asset_code)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(asset, k, v)
        asset.updated_by = user_email
        self.db.flush()
        return asset

    # --- AssetCostRate CRUD + rate calculation ---

    def list_rates(self, client_id: str, asset_code: str) -> list:
        return self._rates.list(client_id=client_id,
                                filters={"asset_code": asset_code})

    def upsert_rate(self, client_id: str, data: schemas.AssetCostRateCreate,
                    user_email: str) -> models.AssetCostRate:
        existing = self._rates.list(
            client_id=client_id,
            filters={"asset_code": data.asset_code, "fiscal_year": data.fiscal_year}
        )
        if existing:
            rate = existing[0]
            for k, v in data.model_dump(exclude={"asset_code", "fiscal_year",
                                                  "currency"}).items():
                setattr(rate, k, v)
        else:
            rate = models.AssetCostRate(**data.model_dump(),
                                        client_id=client_id,
                                        created_by=user_email,
                                        updated_by=user_email)
            self.db.add(rate)
        self.db.flush()
        rate.machine_rate = rate.calculate_rate()
        rate.updated_by = user_email
        self.db.flush()
        logger.info("AssetCostRate %s/%d → machine_rate=%s",
                    rate.asset_code, rate.fiscal_year, rate.machine_rate)
        return rate

    def calculate_machine_rate(self, client_id: str, asset_code: str,
                               fiscal_year: int) -> schemas.MachineRateResult:
        rates = self._rates.list(client_id=client_id,
                                 filters={"asset_code": asset_code,
                                          "fiscal_year": fiscal_year})
        if not rates:
            raise NotFoundError(
                f"AssetCostRate for '{asset_code}' / {fiscal_year} not found")
        rate: models.AssetCostRate = rates[0]
        rate.machine_rate = rate.calculate_rate()
        self.db.flush()
        return schemas.MachineRateResult(
            asset_code=asset_code,
            fiscal_year=fiscal_year,
            machine_rate=rate.machine_rate,
            currency=rate.currency,
        )


# ══════════════════════════════════════════════════════════════════════
# Cost Center / Labor Rate
# ══════════════════════════════════════════════════════════════════════

class CostCenterService:
    def __init__(self, db: Session):
        self.db = db
        self._cc      = BaseRepository(models.CostCenter, db)
        self._budgets = BaseRepository(models.CostCenterBudget, db)
        self._emps    = BaseRepository(models.CostCenterEmployee, db)

    # --- CostCenter CRUD ---

    def get_cc(self, client_id: str, code: str) -> models.CostCenter:
        items = self._cc.list(client_id=client_id,
                              filters={"cost_center_code": code})
        if not items:
            raise NotFoundError(f"CostCenter '{code}' not found")
        return items[0]

    def list_cc(self, client_id: str, skip: int, limit: int) -> list:
        return self._cc.list(client_id=client_id, skip=skip, limit=limit)

    def create_cc(self, client_id: str, data: schemas.CostCenterCreate,
                  user_email: str) -> models.CostCenter:
        cc = models.CostCenter(**data.model_dump(),
                               client_id=client_id,
                               created_by=user_email,
                               updated_by=user_email)
        self.db.add(cc)
        self.db.flush()
        return cc

    def update_cc(self, client_id: str, code: str,
                  data: schemas.CostCenterUpdate,
                  user_email: str) -> models.CostCenter:
        cc = self.get_cc(client_id, code)
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(cc, k, v)
        cc.updated_by = user_email
        self.db.flush()
        return cc

    # --- CostCenterEmployee CRUD ---

    def list_employees(self, client_id: str, cost_center_code: str) -> list:
        return self._emps.list(client_id=client_id,
                               filters={"cost_center_code": cost_center_code})

    def add_employee(self, client_id: str, data: schemas.CostCenterEmployeeCreate,
                     user_email: str) -> models.CostCenterEmployee:
        emp = models.CostCenterEmployee(**data.model_dump(),
                                        client_id=client_id,
                                        created_by=user_email,
                                        updated_by=user_email)
        self.db.add(emp)
        self.db.flush()
        return emp

    # --- CostCenterBudget CRUD + rate calculation ---

    def list_budgets(self, client_id: str, cost_center_code: str) -> list:
        return self._budgets.list(client_id=client_id,
                                  filters={"cost_center_code": cost_center_code})

    def upsert_budget(self, client_id: str, data: schemas.CostCenterBudgetCreate,
                      user_email: str) -> models.CostCenterBudget:
        existing = self._budgets.list(
            client_id=client_id,
            filters={"cost_center_code": data.cost_center_code,
                     "fiscal_year": data.fiscal_year}
        )
        if existing:
            budget = existing[0]
            for k, v in data.model_dump(exclude={"cost_center_code", "fiscal_year",
                                                  "currency"}).items():
                setattr(budget, k, v)
        else:
            budget = models.CostCenterBudget(**data.model_dump(),
                                             client_id=client_id,
                                             created_by=user_email,
                                             updated_by=user_email)
            self.db.add(budget)
        self.db.flush()
        budget.labor_rate = budget.calculate_labor_rate()
        budget.updated_by = user_email
        self.db.flush()
        logger.info("CostCenterBudget %s/%d → labor_rate=%s",
                    budget.cost_center_code, budget.fiscal_year, budget.labor_rate)
        return budget

    def calculate_labor_rate(self, client_id: str, cost_center_code: str,
                             fiscal_year: int,
                             direct_cost_base: Optional[Decimal] = None
                             ) -> schemas.LaborRateResult:
        budgets = self._budgets.list(
            client_id=client_id,
            filters={"cost_center_code": cost_center_code, "fiscal_year": fiscal_year}
        )
        if not budgets:
            raise NotFoundError(
                f"CostCenterBudget for '{cost_center_code}' / {fiscal_year} not found")
        b: models.CostCenterBudget = budgets[0]
        b.labor_rate = b.calculate_labor_rate()
        base = direct_cost_base or b.labor_budget
        b.overhead_rate_percent = b.calculate_overhead_rate(base)
        self.db.flush()
        return schemas.LaborRateResult(
            cost_center_code=cost_center_code,
            fiscal_year=fiscal_year,
            labor_rate=b.labor_rate,
            overhead_rate_percent=b.overhead_rate_percent or Decimal("0"),
            currency=b.currency,
        )


# ══════════════════════════════════════════════════════════════════════
# Work Center Rate Sync (CO → PP)
# ══════════════════════════════════════════════════════════════════════

class WorkCenterRateService:
    """Push labor_rate / machine_rate from CO budgets+assets → PP work_centers."""

    def __init__(self, db: Session):
        self.db = db

    def sync_rates(self, client_id: str, fiscal_year: int,
                   user_email: str) -> schemas.WorkCenterRateUpdateResult:
        details: list[dict] = []

        # Collect labor rates: CostCenterBudget → work_center_code
        budgets = (
            self.db.query(models.CostCenterBudget)
            .filter(models.CostCenterBudget.client_id == client_id,
                    models.CostCenterBudget.fiscal_year == fiscal_year)
            .all()
        )
        cc_map: dict[str, Decimal] = {}
        oh_map: dict[str, Decimal] = {}
        for b in budgets:
            b.labor_rate = b.calculate_labor_rate()
            cc = (
                self.db.query(models.CostCenter)
                .filter(models.CostCenter.client_id == client_id,
                        models.CostCenter.cost_center_code == b.cost_center_code)
                .first()
            )
            if cc and cc.work_center_code:
                cc_map[cc.work_center_code] = b.labor_rate
                oh_map[cc.work_center_code] = b.overhead_rate_percent or Decimal("0")

        # Collect machine rates: AssetCostRate → work_center_code
        asset_rates = (
            self.db.query(models.AssetCostRate)
            .filter(models.AssetCostRate.client_id == client_id,
                    models.AssetCostRate.fiscal_year == fiscal_year)
            .all()
        )
        machine_map: dict[str, Decimal] = {}
        for ar in asset_rates:
            ar.machine_rate = ar.calculate_rate()
            asset = (
                self.db.query(models.AssetMaster)
                .filter(models.AssetMaster.client_id == client_id,
                        models.AssetMaster.asset_code == ar.asset_code)
                .first()
            )
            if asset and asset.work_center_code:
                # Sum rates when multiple assets → same work center
                wc = asset.work_center_code
                machine_map[wc] = machine_map.get(wc, Decimal("0")) + ar.machine_rate

        # Apply to work centers
        all_wc_codes = set(cc_map) | set(machine_map)
        for wc_code in all_wc_codes:
            wc = (
                self.db.query(WorkCenter)
                .filter(WorkCenter.client_id == client_id,
                        WorkCenter.work_center_code == wc_code)
                .first()
            )
            if not wc:
                logger.warning("WorkCenter '%s' not found; skipping rate sync", wc_code)
                continue
            old_labor   = wc.labor_rate_per_hour
            old_machine = wc.machine_rate_per_hour
            if wc_code in cc_map:
                wc.labor_rate_per_hour = cc_map[wc_code]
            if wc_code in machine_map:
                wc.machine_rate_per_hour = machine_map[wc_code]
            if wc_code in oh_map:
                wc.overhead_rate_percent = oh_map[wc_code]
            details.append({
                "work_center_code": wc_code,
                "labor_rate_old": float(old_labor),
                "labor_rate_new": float(wc.labor_rate_per_hour),
                "machine_rate_old": float(old_machine),
                "machine_rate_new": float(wc.machine_rate_per_hour),
            })

        self.db.flush()
        logger.info("WorkCenterRateSync FY%d: %d work centers updated", fiscal_year, len(details))
        return schemas.WorkCenterRateUpdateResult(updated=len(details), details=details)


# ══════════════════════════════════════════════════════════════════════
# Actual Cost Posting
# ══════════════════════════════════════════════════════════════════════

class ActualCostService:
    def __init__(self, db: Session):
        self.db = db

    def list_postings(self, client_id: str, process_order_id: Optional[int],
                      fiscal_year: Optional[int],
                      skip: int, limit: int) -> list:
        q = (
            self.db.query(models.ActualCostPosting)
            .filter(models.ActualCostPosting.client_id == client_id)
        )
        if process_order_id:
            q = q.filter(models.ActualCostPosting.process_order_id == process_order_id)
        if fiscal_year:
            q = q.filter(models.ActualCostPosting.fiscal_year == fiscal_year)
        return q.offset(skip).limit(limit).all()

    def post(self, client_id: str, data: schemas.ActualCostPostingCreate,
             user_email: str) -> models.ActualCostPosting:
        variance = data.actual_cost - data.planned_cost
        variance_pct: Optional[Decimal] = None
        if data.planned_cost and data.planned_cost != 0:
            variance_pct = (variance / data.planned_cost * 100).quantize(Decimal("0.01"))

        posting = models.ActualCostPosting(
            **data.model_dump(),
            client_id=client_id,
            variance=variance,
            variance_percent=variance_pct,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(posting)
        self.db.flush()
        return posting


# ══════════════════════════════════════════════════════════════════════
# Cost Estimate Items / De Minimis
# ══════════════════════════════════════════════════════════════════════

class CostEstimateService:
    def __init__(self, db: Session):
        self.db = db
        self._items = BaseRepository(models.CostEstimateItem, db)

    def list_items(self, client_id: str, material_code: Optional[str],
                   fiscal_year: Optional[int], skip: int, limit: int) -> list:
        filters = {}
        if material_code:
            filters["material_code"] = material_code
        if fiscal_year:
            filters["fiscal_year"] = fiscal_year
        return self._items.list(client_id=client_id, filters=filters,
                                skip=skip, limit=limit)

    def create_item(self, client_id: str, data: schemas.CostEstimateItemCreate,
                    user_email: str) -> models.CostEstimateItem:
        item = models.CostEstimateItem(**data.model_dump(),
                                       client_id=client_id,
                                       created_by=user_email,
                                       updated_by=user_email)
        self.db.add(item)
        self.db.flush()
        return item

    def update_item(self, client_id: str, item_id: int,
                    data: schemas.CostEstimateItemUpdate,
                    user_email: str) -> models.CostEstimateItem:
        item = (
            self.db.query(models.CostEstimateItem)
            .filter(models.CostEstimateItem.client_id == client_id,
                    models.CostEstimateItem.id == item_id)
            .first()
        )
        if not item:
            raise NotFoundError(f"CostEstimateItem {item_id} not found")
        for k, v in data.model_dump(exclude_none=True).items():
            setattr(item, k, v)
        item.updated_by = user_email
        self.db.flush()
        return item

    def de_minimis(self, client_id: str, material_code: str,
                   fiscal_year: int) -> schemas.DeMinimisResult:
        """US EAR De Minimis: if US-origin value / total value ≤ 25%, product
        may qualify for de minimis exclusion from EAR controls."""
        items = self._items.list(
            client_id=client_id,
            filters={"material_code": material_code, "fiscal_year": fiscal_year}
        )
        if not items:
            raise NotFoundError(
                f"No CostEstimateItems for '{material_code}' / {fiscal_year}")

        total = sum(i.total_cost for i in items)
        us_total = sum(i.total_cost for i in items if i.us_content_flag)
        us_pct = (us_total / total * 100).quantize(Decimal("0.01")) if total else Decimal("0")
        currency = items[0].currency

        return schemas.DeMinimisResult(
            material_code=material_code,
            fiscal_year=fiscal_year,
            total_cost=total,
            us_content_cost=us_total,
            us_content_percent=us_pct,
            is_de_minimis=us_pct <= Decimal("25.00"),
            currency=currency,
        )
