"""Production Planning - business logic.

Three core capabilities:
1. CRUD orchestration for Recipe / Routing / ProductionVersion
2. Multi-level BOM explosion
3. Cost rollup with Cost Component Split (SAP-style)
4. Compliance snapshot - generic data export for external services

Compliance JUDGMENT logic is intentionally NOT here. The ERP's role is to
expose a clean, vendor-neutral data interface; external services
(AI_TradeManagement etc.) consume the snapshot and apply their own rules.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, DuplicateError, NotFoundError
from app.core.numbering import next_number
from app.modules.mdm.models import Material
from app.modules.pp import models, schemas
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)


# ==================================================================
# Numbering helpers
# ==================================================================
def _seed_pp_ranges(db: Session, client_id: str) -> None:
    """Ensure PP-specific number ranges exist."""
    from app.core.numbering import NumberRange, DEFAULT_RANGES
    DEFAULT_RANGES.setdefault("RECIPE", {"prefix": "RCP-", "width": 7, "start": 1})
    DEFAULT_RANGES.setdefault("ROUTING", {"prefix": "RTG-", "width": 7, "start": 1})
    DEFAULT_RANGES.setdefault("PRODUCTION_VERSION", {"prefix": "PV-", "width": 7, "start": 1})
    DEFAULT_RANGES.setdefault("WORK_CENTER", {"prefix": "WC-", "width": 5, "start": 1})


# ==================================================================
# WorkCenter
# ==================================================================
class WorkCenterService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = BaseRepository(models.WorkCenter, db)

    def create(self, payload: schemas.WorkCenterCreate, client_id: str, user_email: str):
        existing = self.repo.get_by_field("work_center_code", payload.work_center_code, client_id)
        if existing:
            raise DuplicateError("WorkCenter", "work_center_code", payload.work_center_code)
        data = payload.model_dump()
        data.update({"client_id": client_id, "created_by": user_email, "updated_by": user_email})
        return self.repo.create(data)


# ==================================================================
# Recipe
# ==================================================================
class RecipeService:
    def __init__(self, db: Session):
        self.db = db
        _seed_pp_ranges(db, "DEMO")

    def create(self, payload: schemas.RecipeCreate, client_id: str, user_email: str) -> models.Recipe:
        # Validate produced material exists
        produced = self.db.query(Material).filter(
            Material.material_code == payload.material_code,
            Material.client_id == client_id,
        ).first()
        if not produced:
            raise NotFoundError("Material (produced)", payload.material_code)

        # Validate all components exist
        for item in payload.items:
            comp = self.db.query(Material).filter(
                Material.material_code == item.component_material_code,
                Material.client_id == client_id,
            ).first()
            if not comp:
                raise NotFoundError("Material (component)", item.component_material_code)

        recipe_code = payload.recipe_code or next_number(self.db, client_id, "RECIPE")

        # Uniqueness
        existing = self.db.query(models.Recipe).filter(
            models.Recipe.recipe_code == recipe_code,
            models.Recipe.client_id == client_id,
        ).first()
        if existing:
            raise DuplicateError("Recipe", "recipe_code", recipe_code)

        recipe = models.Recipe(
            client_id=client_id,
            recipe_code=recipe_code,
            material_code=payload.material_code,
            plant_code=payload.plant_code,
            description=payload.description,
            base_quantity=payload.base_quantity,
            base_unit=payload.base_unit,
            yield_percent=payload.yield_percent,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            is_default=payload.is_default,
            status="DRAFT",
            created_by=user_email,
            updated_by=user_email,
        )

        for idx, item_in in enumerate(payload.items, start=1):
            recipe.items.append(models.RecipeItem(
                item_no=idx * 10,
                component_material_code=item_in.component_material_code,
                quantity=item_in.quantity,
                unit=item_in.unit,
                scrap_percent=item_in.scrap_percent,
                is_phantom=item_in.is_phantom,
                operation_no=item_in.operation_no,
                created_by=user_email,
                updated_by=user_email,
            ))

        for cp_in in payload.co_products:
            recipe.co_products.append(models.RecipeCoProduct(
                material_code=cp_in.material_code,
                quantity=cp_in.quantity,
                unit=cp_in.unit,
                cost_share_percent=cp_in.cost_share_percent,
                created_by=user_email,
                updated_by=user_email,
            ))

        # Maintain default uniqueness within (material, plant)
        if recipe.is_default:
            self._unset_other_defaults(client_id, payload.material_code, payload.plant_code)

        self.db.add(recipe)
        self.db.flush()
        return recipe

    def release(self, recipe_id: int, client_id: str, user_email: str) -> models.Recipe:
        recipe = BaseRepository(models.Recipe, self.db).get(recipe_id, client_id)
        if not recipe:
            raise NotFoundError("Recipe", recipe_id)
        if recipe.status != "DRAFT":
            raise BusinessRuleError(f"Recipe is in status {recipe.status}, cannot release")
        recipe.status = "RELEASED"
        recipe.updated_by = user_email
        return recipe

    def _unset_other_defaults(self, client_id: str, material_code: str, plant_code: str):
        others = self.db.query(models.Recipe).filter(
            models.Recipe.client_id == client_id,
            models.Recipe.material_code == material_code,
            models.Recipe.plant_code == plant_code,
            models.Recipe.is_default == True,  # noqa: E712
        ).all()
        for r in others:
            r.is_default = False


# ==================================================================
# Routing
# ==================================================================
class RoutingService:
    def __init__(self, db: Session):
        self.db = db
        _seed_pp_ranges(db, "DEMO")

    def create(self, payload: schemas.RoutingCreate, client_id: str, user_email: str) -> models.Routing:
        # Validate work centers exist
        for op in payload.operations:
            wc = self.db.query(models.WorkCenter).filter(
                models.WorkCenter.work_center_code == op.work_center_code,
                models.WorkCenter.client_id == client_id,
            ).first()
            if not wc:
                raise NotFoundError("WorkCenter", op.work_center_code)

        routing_code = payload.routing_code or next_number(self.db, client_id, "ROUTING")
        existing = self.db.query(models.Routing).filter(
            models.Routing.routing_code == routing_code,
            models.Routing.client_id == client_id,
        ).first()
        if existing:
            raise DuplicateError("Routing", "routing_code", routing_code)

        routing = models.Routing(
            client_id=client_id,
            routing_code=routing_code,
            material_code=payload.material_code,
            plant_code=payload.plant_code,
            description=payload.description,
            base_quantity=payload.base_quantity,
            base_unit=payload.base_unit,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            status="DRAFT",
            created_by=user_email,
            updated_by=user_email,
        )

        for idx, op_in in enumerate(payload.operations, start=1):
            routing.operations.append(models.RoutingOperation(
                operation_no=idx * 10,
                description=op_in.description,
                work_center_code=op_in.work_center_code,
                setup_time_minutes=op_in.setup_time_minutes,
                machine_time_minutes=op_in.machine_time_minutes,
                labor_time_minutes=op_in.labor_time_minutes,
                yield_percent=op_in.yield_percent,
                created_by=user_email,
                updated_by=user_email,
            ))

        self.db.add(routing)
        self.db.flush()
        return routing


# ==================================================================
# Production Version
# ==================================================================
class ProductionVersionService:
    def __init__(self, db: Session):
        self.db = db
        _seed_pp_ranges(db, "DEMO")

    def create(self, payload: schemas.ProductionVersionCreate, client_id: str,
               user_email: str) -> models.ProductionVersion:
        recipe = BaseRepository(models.Recipe, self.db).get(payload.recipe_id, client_id)
        if not recipe:
            raise NotFoundError("Recipe", payload.recipe_id)
        routing = BaseRepository(models.Routing, self.db).get(payload.routing_id, client_id)
        if not routing:
            raise NotFoundError("Routing", payload.routing_id)

        # Sanity: recipe and routing should target the same material+plant
        if recipe.material_code != payload.material_code:
            raise BusinessRuleError("Recipe.material_code mismatch")
        if routing.material_code != payload.material_code:
            raise BusinessRuleError("Routing.material_code mismatch")
        if recipe.plant_code != payload.plant_code or routing.plant_code != payload.plant_code:
            raise BusinessRuleError("Recipe/Routing plant_code mismatch")

        version_code = payload.version_code or next_number(
            self.db, client_id, "PRODUCTION_VERSION")

        if payload.is_default:
            self._unset_other_defaults(client_id, payload.material_code, payload.plant_code)

        pv = models.ProductionVersion(
            client_id=client_id,
            version_code=version_code,
            material_code=payload.material_code,
            plant_code=payload.plant_code,
            recipe_id=payload.recipe_id,
            routing_id=payload.routing_id,
            valid_from=payload.valid_from,
            valid_to=payload.valid_to,
            is_default=payload.is_default,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(pv)
        self.db.flush()
        return pv

    def get_default(self, client_id: str, material_code: str,
                    plant_code: str) -> Optional[models.ProductionVersion]:
        today = date.today()
        return self.db.query(models.ProductionVersion).filter(
            models.ProductionVersion.client_id == client_id,
            models.ProductionVersion.material_code == material_code,
            models.ProductionVersion.plant_code == plant_code,
            models.ProductionVersion.is_default == True,  # noqa: E712
            models.ProductionVersion.valid_from <= today,
            models.ProductionVersion.valid_to >= today,
            models.ProductionVersion.is_active == True,  # noqa: E712
        ).first()

    def _unset_other_defaults(self, client_id: str, material_code: str, plant_code: str):
        others = self.db.query(models.ProductionVersion).filter(
            models.ProductionVersion.client_id == client_id,
            models.ProductionVersion.material_code == material_code,
            models.ProductionVersion.plant_code == plant_code,
            models.ProductionVersion.is_default == True,  # noqa: E712
        ).all()
        for o in others:
            o.is_default = False


# ==================================================================
# BOM Explosion (multi-level)
# ==================================================================
class BomExplosionService:
    """Recursively explode a BOM, including phantom expansion."""

    MAX_DEPTH = 20  # safety net against circular references

    def __init__(self, db: Session):
        self.db = db

    def explode(self, client_id: str, material_code: str, plant_code: str,
                quantity: Optional[Decimal] = None) -> schemas.BomExplosionNode:
        return self._explode_node(
            client_id=client_id,
            material_code=material_code,
            plant_code=plant_code,
            required_qty=quantity,
            level=0,
            visited=set(),
        )

    def _explode_node(self, client_id: str, material_code: str, plant_code: str,
                      required_qty: Optional[Decimal], level: int,
                      visited: set) -> schemas.BomExplosionNode:
        if level > self.MAX_DEPTH:
            raise BusinessRuleError(f"BOM depth exceeds {self.MAX_DEPTH} - possible cycle")
        if material_code in visited:
            raise BusinessRuleError(f"Circular BOM detected: {material_code}")
        visited = visited | {material_code}

        material = self.db.query(Material).filter(
            Material.material_code == material_code,
            Material.client_id == client_id,
        ).first()
        description = material.description if material else None

        # Find a default Production Version (-> Recipe) for this plant
        pv = ProductionVersionService(self.db).get_default(client_id, material_code, plant_code)

        if pv is None:
            # Leaf: purchased material (no recipe in this plant)
            return schemas.BomExplosionNode(
                level=level,
                material_code=material_code,
                description=description,
                quantity=required_qty if required_qty is not None else Decimal("1"),
                unit=material.base_unit if material else "PC",
                is_phantom=False,
                is_purchased=True,
                children=[],
            )

        recipe = pv.recipe
        # Scaling factor: required_qty / recipe.base_quantity
        if required_qty is None:
            required_qty = recipe.base_quantity
        scale = required_qty / recipe.base_quantity if recipe.base_quantity else Decimal("1")

        children = []
        for item in recipe.items:
            scrap_factor = Decimal("1") + (item.scrap_percent / Decimal("100"))
            child_qty = item.quantity * scale * scrap_factor
            child_node = self._explode_node(
                client_id, item.component_material_code, plant_code,
                child_qty, level + 1, visited,
            )
            child_node.is_phantom = item.is_phantom
            children.append(child_node)

        return schemas.BomExplosionNode(
            level=level,
            material_code=material_code,
            description=description,
            quantity=required_qty,
            unit=recipe.base_unit,
            is_phantom=False,
            is_purchased=False,
            children=children,
        )


# ==================================================================
# Cost Rollup (the heart of Phase 2B)
# ==================================================================
class CostRollupService:
    """Multi-level cost rollup producing a Cost Component Split.

    For each material:
    - If it has a default Production Version in the plant -> recurse into recipe
      and add labor/machine/overhead from the routing
    - Else (purchased) -> use Material.standard_price as raw_material_cost

    The result is per-1-unit cost, broken down into 4 components:
    raw_material / labor / machine / overhead.
    """

    DEFAULT_OVERHEAD_PERCENT = Decimal("0")  # only via WorkCenter unless overridden
    QUANT = Decimal("0.0001")

    def __init__(self, db: Session):
        self.db = db

    def rollup(self, request: schemas.CostRollupRequest, client_id: str,
               user_email: str) -> models.CostComponentSplit:
        breakdown: list[dict] = []
        split = self._rollup_recursive(
            client_id=client_id,
            material_code=request.material_code,
            plant_code=request.plant_code,
            level=0,
            visited=set(),
            breakdown=breakdown,
            overhead_override=request.overhead_rate_percent,
        )

        # Look up base_unit from material
        material = self.db.query(Material).filter(
            Material.material_code == request.material_code,
            Material.client_id == client_id,
        ).first()
        base_unit = material.base_unit if material else "PC"
        currency = (material.currency if material and material.currency else "JPY")

        # Determine production_version_code (if any)
        pv = ProductionVersionService(self.db).get_default(
            client_id, request.material_code, request.plant_code)
        pv_code = pv.version_code if pv else None

        record = models.CostComponentSplit(
            client_id=client_id,
            material_code=request.material_code,
            plant_code=request.plant_code,
            production_version_code=pv_code,
            raw_material_cost=split["raw_material"],
            labor_cost=split["labor"],
            machine_cost=split["machine"],
            overhead_cost=split["overhead"],
            external_processing_cost=split["external"],
            total_cost=(split["raw_material"] + split["labor"]
                        + split["machine"] + split["overhead"] + split["external"]),
            currency=currency,
            base_unit=base_unit,
            valid_from=date.today(),
            valid_to=date(2099, 12, 31),
            breakdown_json=json.dumps(breakdown, default=str, ensure_ascii=False),
            created_by=user_email,
            updated_by=user_email,
        )

        if request.save_result:
            self.db.add(record)
            self.db.flush()
        return record

    def _rollup_recursive(self, client_id: str, material_code: str, plant_code: str,
                          level: int, visited: set, breakdown: list,
                          overhead_override: Optional[Decimal]) -> dict:
        """Returns per-unit costs as {raw_material, labor, machine, overhead, external}."""
        if material_code in visited:
            raise BusinessRuleError(f"Circular BOM in cost rollup: {material_code}")
        visited = visited | {material_code}

        material = self.db.query(Material).filter(
            Material.material_code == material_code,
            Material.client_id == client_id,
        ).first()
        if not material:
            raise NotFoundError("Material", material_code)

        pv = ProductionVersionService(self.db).get_default(client_id, material_code, plant_code)

        # ---- Leaf: purchased component ----
        if pv is None:
            unit_cost = material.standard_price or Decimal("0")
            breakdown.append({
                "level": level,
                "material_code": material_code,
                "description": material.description,
                "quantity": "1",
                "unit": material.base_unit,
                "unit_cost": str(unit_cost),
                "extended_cost": str(unit_cost),
                "cost_type": "MATERIAL",
            })
            return {
                "raw_material": unit_cost,
                "labor": Decimal("0"),
                "machine": Decimal("0"),
                "overhead": Decimal("0"),
                "external": Decimal("0"),
            }

        # ---- Manufactured: recurse ----
        recipe = pv.recipe
        routing = pv.routing

        # 1. Sum up component costs (per recipe.base_quantity of output)
        components_raw_material = Decimal("0")
        components_labor = Decimal("0")
        components_machine = Decimal("0")
        components_overhead = Decimal("0")

        for item in recipe.items:
            child = self._rollup_recursive(
                client_id, item.component_material_code, plant_code,
                level + 1, visited, breakdown, overhead_override,
            )
            scrap_factor = Decimal("1") + (item.scrap_percent / Decimal("100"))
            extended_qty = item.quantity * scrap_factor

            components_raw_material += child["raw_material"] * extended_qty
            components_labor += child["labor"] * extended_qty
            components_machine += child["machine"] * extended_qty
            components_overhead += child["overhead"] * extended_qty

            breakdown.append({
                "level": level,
                "material_code": item.component_material_code,
                "description": None,
                "quantity": str(extended_qty),
                "unit": item.unit,
                "unit_cost": str(child["raw_material"]),
                "extended_cost": str(child["raw_material"] * extended_qty),
                "cost_type": "MATERIAL",
            })

        # 2. Add this level's labor / machine costs from routing
        self_labor = Decimal("0")
        self_machine = Decimal("0")
        self_overhead_from_wc = Decimal("0")

        for op in routing.operations:
            wc = self.db.query(models.WorkCenter).filter(
                models.WorkCenter.work_center_code == op.work_center_code,
                models.WorkCenter.client_id == client_id,
            ).first()
            if not wc:
                continue

            # Time consumed for the recipe.base_quantity output
            machine_minutes = op.setup_time_minutes + op.machine_time_minutes
            labor_minutes = op.setup_time_minutes + op.labor_time_minutes

            op_labor_cost = (labor_minutes / Decimal("60")) * wc.labor_rate_per_hour
            op_machine_cost = (machine_minutes / Decimal("60")) * wc.machine_rate_per_hour

            # Per-WorkCenter overhead applies to that WC's labor+machine
            wc_overhead = ((op_labor_cost + op_machine_cost)
                           * wc.overhead_rate_percent / Decimal("100"))

            self_labor += op_labor_cost
            self_machine += op_machine_cost
            self_overhead_from_wc += wc_overhead

            breakdown.append({
                "level": level,
                "material_code": op.work_center_code,
                "description": op.description,
                "quantity": str((labor_minutes + machine_minutes) / 60),
                "unit": "H",
                "unit_cost": str(wc.labor_rate_per_hour + wc.machine_rate_per_hour),
                "extended_cost": str(op_labor_cost + op_machine_cost),
                "cost_type": "ACTIVITY",
            })

        # 3. Optional overhead override (applies to total raw_material+labor+machine)
        self_overhead_override = Decimal("0")
        if overhead_override is not None:
            base = (components_raw_material + components_labor + components_machine
                    + self_labor + self_machine)
            self_overhead_override = base * overhead_override / Decimal("100")

        total_overhead = components_overhead + self_overhead_from_wc + self_overhead_override

        # 4. Yield adjustment: actual_output = base_quantity * yield_percent / 100
        #    so per-unit costs need to be inflated by 1 / yield_percent
        yield_factor = recipe.yield_percent / Decimal("100")
        if yield_factor <= 0:
            yield_factor = Decimal("1")

        per_base_unit_costs = {
            "raw_material": (components_raw_material / yield_factor),
            "labor": ((components_labor + self_labor) / yield_factor),
            "machine": ((components_machine + self_machine) / yield_factor),
            "overhead": (total_overhead / yield_factor),
            "external": Decimal("0"),
        }

        # 5. Convert from "per recipe.base_quantity" to "per 1 unit"
        if recipe.base_quantity and recipe.base_quantity > 0:
            for k in per_base_unit_costs:
                per_base_unit_costs[k] = per_base_unit_costs[k] / recipe.base_quantity

        return per_base_unit_costs


# ==================================================================
# Compliance Snapshot - vendor-neutral data export
# ==================================================================
class ComplianceSnapshotService:
    """Build a flat snapshot of all components in a BOM with their
    trade-relevant attributes (HS code, ECCN, country of origin).

    The ERP performs no judgment. Callers (e.g. AI_TradeManagement)
    receive the snapshot via this generic API and apply their own logic.
    """

    def __init__(self, db: Session):
        self.db = db

    def build(self, client_id: str, material_code: str,
              plant_code: str) -> schemas.BomComplianceSnapshotResponse:
        # Top-level material
        product = self.db.query(Material).filter(
            Material.material_code == material_code,
            Material.client_id == client_id,
        ).first()
        if not product:
            raise NotFoundError("Material", material_code)

        # Explode the BOM and flatten the tree
        tree = BomExplosionService(self.db).explode(
            client_id, material_code, plant_code,
        )
        flat: list[schemas.BomComplianceComponent] = []
        self._flatten(tree, flat, client_id)

        pv = ProductionVersionService(self.db).get_default(
            client_id, material_code, plant_code)

        return schemas.BomComplianceSnapshotResponse(
            material_code=material_code,
            plant_code=plant_code,
            production_version_code=pv.version_code if pv else None,
            snapshot_taken_at=datetime.utcnow(),
            product_hs_code=product.hs_code,
            product_eccn=product.eccn,
            product_fefta_judgment=product.fefta_judgment,
            components=flat,
        )

    def _flatten(self, node: schemas.BomExplosionNode,
                 out: list, client_id: str) -> None:
        # Skip the top-level node itself; only emit components
        if node.level > 0:
            material = self.db.query(Material).filter(
                Material.material_code == node.material_code,
                Material.client_id == client_id,
            ).first()
            out.append(schemas.BomComplianceComponent(
                level=node.level,
                material_code=node.material_code,
                description=node.description,
                quantity=node.quantity,
                unit=node.unit,
                hs_code=material.hs_code if material else None,
                eccn=material.eccn if material else None,
                country_of_origin=material.country_of_origin if material else None,
                fefta_judgment=material.fefta_judgment if material else None,
            ))
        for child in node.children:
            self._flatten(child, out, client_id)
