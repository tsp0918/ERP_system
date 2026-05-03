"""Production Planning - Execution layer service logic.

Workflow (Manufacture-to-Stock):

  1. ProcessOrderService.create()
       - Take a ProductionVersion (= Recipe + Routing)
       - Scale recipe components by target_quantity / recipe.base_quantity
       - Snapshot planned components and operations
       - Order is created with status=OPEN

  2. ProcessOrderService.release()
       - Status OPEN -> RELEASED
       - (in a fuller impl, this would reserve inventory; we skip reservation
         in Phase 2D and check availability at goods-issue time instead)

  3. GoodsIssueService.post()
       - For each line: deduct quantity from the chosen Batch
       - Increment the component's issued_quantity
       - Genealogy is NOT recorded yet - that happens at goods receipt time
         when we know the produced child batch
       - Goods issues are journaled in a working list on the order until
         the production GR closes them out

  4. OperationService.confirm()
       - Record actual machine/labor minutes for an operation

  5. ProductionGoodsReceiptService.post()
       - Create the produced Batch (or merge into an existing one if user
         provides an existing batch_code)
       - Walk the order's already-issued goods-issue records and write
         BatchGenealogy rows linking every consumed parent batch to the
         new child batch
       - Update process order status to COMPLETED
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.exceptions import BusinessRuleError, NotFoundError
from app.core.numbering import next_number
from app.modules.mdm.models import Material
from app.modules.pp import execution_models as exec_models
from app.modules.pp import execution_schemas as exec_schemas
from app.modules.pp import models as pp_models
from app.modules.pp.service import ProductionVersionService
from app.shared.base_models import DocStatus
from app.shared.base_repository import BaseRepository

logger = logging.getLogger(__name__)


def _seed_execution_ranges() -> None:
    from app.core.numbering import DEFAULT_RANGES
    DEFAULT_RANGES.setdefault(
        "PROCESS_ORDER", {"prefix": "", "width": 10, "start": 6_000_000_000})
    DEFAULT_RANGES.setdefault(
        "BATCH", {"prefix": "LOT-", "width": 10, "start": 1})


# ==================================================================
# Process Order
# ==================================================================
class ProcessOrderService:
    def __init__(self, db: Session):
        self.db = db
        _seed_execution_ranges()

    def create(self, payload: exec_schemas.ProcessOrderCreate,
               client_id: str, user_email: str) -> exec_models.ProcessOrder:
        # Resolve production version
        if payload.production_version_code:
            pv = self.db.query(pp_models.ProductionVersion).filter(
                pp_models.ProductionVersion.client_id == client_id,
                pp_models.ProductionVersion.version_code == payload.production_version_code,
            ).first()
            if not pv:
                raise NotFoundError("ProductionVersion", payload.production_version_code)
        else:
            pv = ProductionVersionService(self.db).get_default(
                client_id, payload.material_code, payload.plant_code)
            if not pv:
                raise BusinessRuleError(
                    f"No default ProductionVersion for "
                    f"{payload.material_code}@{payload.plant_code}")

        if pv.material_code != payload.material_code:
            raise BusinessRuleError(
                f"PV {pv.version_code} produces {pv.material_code}, "
                f"not {payload.material_code}")

        recipe = pv.recipe
        routing = pv.routing
        scale = payload.target_quantity / recipe.base_quantity

        po_number = next_number(self.db, client_id, "PROCESS_ORDER")
        order = exec_models.ProcessOrder(
            client_id=client_id,
            document_number=po_number,
            document_date=payload.document_date,
            status=DocStatus.OPEN,
            material_code=payload.material_code,
            plant_code=payload.plant_code,
            production_version_code=pv.version_code,
            target_quantity=payload.target_quantity,
            target_unit=payload.target_unit or recipe.base_unit,
            scheduled_start=payload.scheduled_start,
            scheduled_end=payload.scheduled_end,
            created_by=user_email,
            updated_by=user_email,
        )

        # Snapshot components from recipe (scaled)
        for idx, item in enumerate(recipe.items, start=1):
            scrap_factor = Decimal("1") + (item.scrap_percent / Decimal("100"))
            order.components.append(exec_models.ProcessOrderComponent(
                item_no=idx * 10,
                material_code=item.component_material_code,
                planned_quantity=(item.quantity * scale * scrap_factor),
                unit=item.unit,
                operation_no=item.operation_no,
                created_by=user_email,
                updated_by=user_email,
            ))

        # Snapshot operations from routing (scaled)
        for op in routing.operations:
            order.operations.append(exec_models.ProcessOrderOperation(
                operation_no=op.operation_no,
                description=op.description,
                work_center_code=op.work_center_code,
                planned_machine_minutes=(op.setup_time_minutes
                                         + op.machine_time_minutes * scale),
                planned_labor_minutes=(op.setup_time_minutes
                                       + op.labor_time_minutes * scale),
                created_by=user_email,
                updated_by=user_email,
            ))

        self.db.add(order)
        self.db.flush()
        return order

    def release(self, order_id: int, client_id: str,
                user_email: str) -> exec_models.ProcessOrder:
        order = BaseRepository(exec_models.ProcessOrder, self.db).get(order_id, client_id)
        if not order:
            raise NotFoundError("ProcessOrder", order_id)
        if order.status not in {DocStatus.OPEN, DocStatus.DRAFT}:
            raise BusinessRuleError(
                f"ProcessOrder is in status {order.status}, cannot release")
        order.status = DocStatus.RELEASED
        order.actual_start = order.actual_start or datetime.utcnow()
        order.updated_by = user_email
        return order


# ==================================================================
# Goods Issue (raw material consumption)
# ==================================================================
class GoodsIssueService:
    """Consume raw material batches against a process order.

    We intentionally do NOT write BatchGenealogy here. Genealogy needs
    a child batch, which only exists after the production goods receipt.
    Until then, the issue events are tracked via:
    - Decremented batch.quantity (inventory side-effect)
    - Incremented component.issued_quantity (process order side-effect)

    At goods receipt time, the receipt service rebuilds the parent list
    by scanning consumption-in-flight - see _collect_pending_parents().
    """

    def __init__(self, db: Session):
        self.db = db

    def post(self, payload: exec_schemas.GoodsIssueRequest,
             client_id: str, user_email: str) -> exec_schemas.GoodsIssueResponse:
        order = BaseRepository(exec_models.ProcessOrder, self.db).get(
            payload.process_order_id, client_id)
        if not order:
            raise NotFoundError("ProcessOrder", payload.process_order_id)
        if order.status not in {DocStatus.RELEASED, DocStatus.OPEN}:
            raise BusinessRuleError(
                f"ProcessOrder status {order.status} - goods issue not allowed")

        component_map = {c.id: c for c in order.components}
        results: list[exec_schemas.GoodsIssueLineResult] = []

        for line in payload.lines:
            comp = component_map.get(line.component_id)
            if not comp:
                raise BusinessRuleError(
                    f"Component {line.component_id} not on order "
                    f"{order.document_number}")

            # Validate the batch matches this component's material
            batch = self.db.query(exec_models.Batch).filter(
                exec_models.Batch.client_id == client_id,
                exec_models.Batch.batch_code == line.batch_code,
            ).first()
            if not batch:
                raise NotFoundError("Batch", line.batch_code)
            if batch.material_code != comp.material_code:
                raise BusinessRuleError(
                    f"Batch {batch.batch_code} is material {batch.material_code}, "
                    f"but component expects {comp.material_code}")
            if batch.plant_code != order.plant_code:
                raise BusinessRuleError(
                    f"Batch {batch.batch_code} is at plant {batch.plant_code}, "
                    f"but order is at {order.plant_code}")
            if batch.quality_status != "RELEASED":
                raise BusinessRuleError(
                    f"Batch {batch.batch_code} status {batch.quality_status} "
                    "- not available for consumption")
            if batch.quantity < line.quantity:
                raise BusinessRuleError(
                    f"Batch {batch.batch_code} has {batch.quantity} {batch.unit}, "
                    f"requested {line.quantity}")

            # Deduct from batch
            batch.quantity = batch.quantity - line.quantity
            comp.issued_quantity = comp.issued_quantity + line.quantity

            # Stash a 'pending parent' note on the component using a JSON string.
            # This is replayed at goods-receipt time to write BatchGenealogy rows.
            self._record_pending_parent(comp, line.batch_code, line.quantity)

            results.append(exec_schemas.GoodsIssueLineResult(
                component_id=comp.id,
                batch_code=line.batch_code,
                consumed_quantity=line.quantity,
                remaining_in_batch=batch.quantity,
            ))

        self.db.flush()
        return exec_schemas.GoodsIssueResponse(
            process_order_id=order.id,
            process_order_number=order.document_number,
            posted_at=datetime.utcnow(),
            lines=results,
        )

    @staticmethod
    def _record_pending_parent(comp: exec_models.ProcessOrderComponent,
                               batch_code: str, quantity: Decimal) -> None:
        """Append a (batch_code, quantity) record to the component description
        as a JSON-encoded ledger. Lightweight; avoids a new table.

        Format stored in `description`:
            <original description> ||PENDING_PARENTS||<json_array>
        """
        marker = "||PENDING_PARENTS||"
        original_desc = comp.description or ""
        if marker in original_desc:
            head, _, tail = original_desc.partition(marker)
            try:
                parents = json.loads(tail)
            except Exception:
                parents = []
        else:
            head = original_desc
            parents = []
        parents.append({"batch_code": batch_code, "quantity": str(quantity)})
        comp.description = f"{head}{marker}{json.dumps(parents)}"

    @staticmethod
    def _drain_pending_parents(comp: exec_models.ProcessOrderComponent
                               ) -> List[dict]:
        """Read and clear the pending parents ledger from a component."""
        marker = "||PENDING_PARENTS||"
        desc = comp.description or ""
        if marker not in desc:
            return []
        head, _, tail = desc.partition(marker)
        try:
            parents = json.loads(tail)
        except Exception:
            parents = []
        # Clear the ledger
        comp.description = head
        return parents


# ==================================================================
# Operation Confirmation
# ==================================================================
class OperationConfirmService:
    def __init__(self, db: Session):
        self.db = db

    def confirm(self, payload: exec_schemas.OperationConfirmRequest,
                client_id: str, user_email: str
                ) -> exec_models.ProcessOrderOperation:
        op = self.db.get(exec_models.ProcessOrderOperation, payload.operation_id)
        if not op:
            raise NotFoundError("ProcessOrderOperation", payload.operation_id)

        # Verify tenant via parent order
        parent = self.db.get(exec_models.ProcessOrder, op.process_order_id)
        if not parent or parent.client_id != client_id:
            raise NotFoundError("ProcessOrderOperation", payload.operation_id)

        op.actual_machine_minutes = (op.actual_machine_minutes or Decimal("0")
                                     ) + payload.actual_machine_minutes
        op.actual_labor_minutes = (op.actual_labor_minutes or Decimal("0")
                                   ) + payload.actual_labor_minutes
        op.confirmation_count = op.confirmation_count + 1
        op.is_confirmed = 1
        op.updated_by = user_email
        return op


# ==================================================================
# Production Goods Receipt (output -> creates Batch + Genealogy)
# ==================================================================
class ProductionGoodsReceiptService:
    """Receive finished goods from a process order, creating a Batch
    and writing the genealogy back to all consumed parent batches."""

    def __init__(self, db: Session):
        self.db = db
        _seed_execution_ranges()

    def post(self, payload: exec_schemas.ProductionGoodsReceiptRequest,
             client_id: str, user_email: str
             ) -> exec_schemas.ProductionGoodsReceiptResponse:
        order = BaseRepository(exec_models.ProcessOrder, self.db).get(
            payload.process_order_id, client_id)
        if not order:
            raise NotFoundError("ProcessOrder", payload.process_order_id)
        if order.status not in {DocStatus.RELEASED, DocStatus.OPEN}:
            raise BusinessRuleError(
                f"ProcessOrder status {order.status} - goods receipt not allowed")

        # 1. Determine batch code
        batch_code = payload.batch_code or self._generate_batch_code(client_id)
        existing = self.db.query(exec_models.Batch).filter(
            exec_models.Batch.client_id == client_id,
            exec_models.Batch.batch_code == batch_code,
        ).first()

        # Pull material default origin
        material = self.db.query(Material).filter(
            Material.client_id == client_id,
            Material.material_code == order.material_code,
        ).first()
        country_of_origin = material.country_of_origin if material else None

        if existing:
            # Merge into existing batch (rare for production - usually new lot)
            existing.quantity = existing.quantity + payload.quantity
            existing.initial_quantity = existing.initial_quantity + payload.quantity
            child_batch = existing
        else:
            child_batch = exec_models.Batch(
                client_id=client_id,
                batch_code=batch_code,
                material_code=order.material_code,
                plant_code=order.plant_code,
                storage_location=payload.storage_location,
                quantity=payload.quantity,
                initial_quantity=payload.quantity,
                unit=order.target_unit,
                source_type="PRODUCED",
                source_reference=order.document_number,
                country_of_origin=country_of_origin,
                quality_status="IN_TEST",  # produced lots typically need QC release
                production_date=payload.posting_date,
                created_by=user_email,
                updated_by=user_email,
            )
            self.db.add(child_batch)

        self.db.flush()

        # 2. Drain pending-parents ledgers from every component and write genealogy
        parent_codes: list[str] = []
        for comp in order.components:
            parents = GoodsIssueService._drain_pending_parents(comp)
            for p in parents:
                gen = exec_models.BatchGenealogy(
                    client_id=client_id,
                    parent_batch_code=p["batch_code"],
                    child_batch_code=batch_code,
                    process_order_number=order.document_number,
                    consumed_quantity=Decimal(p["quantity"]),
                    consumed_unit=comp.unit,
                    parent_material_code=comp.material_code,
                    child_material_code=order.material_code,
                    consumed_at=datetime.utcnow(),
                    created_by=user_email,
                    updated_by=user_email,
                )
                self.db.add(gen)
                parent_codes.append(p["batch_code"])

        # 3. Update order header
        order.actual_quantity = order.actual_quantity + payload.quantity
        order.scrapped_quantity = order.scrapped_quantity + payload.scrapped_quantity
        order.actual_end = datetime.utcnow()
        order.status = DocStatus.COMPLETED
        order.updated_by = user_email

        self.db.flush()
        return exec_schemas.ProductionGoodsReceiptResponse(
            process_order_id=order.id,
            process_order_number=order.document_number,
            new_batch_code=batch_code,
            quantity=payload.quantity,
            unit=order.target_unit,
            parent_batches=list(set(parent_codes)),
            posted_at=datetime.utcnow(),
        )

    @staticmethod
    def _generate_batch_code(client_id: str) -> str:
        # Using date + a random-ish suffix would also work; here we use a counter
        from app.core.numbering import next_number
        # next_number takes a session - inject via the calling context instead
        # by keeping creation via a static-like flow; we accept the small coupling
        return f"LOT-{datetime.utcnow():%Y%m%d}-{datetime.utcnow():%H%M%S%f}"[:30]


# ==================================================================
# Batch service - direct creation & query
# ==================================================================
class BatchService:
    """Create batches directly (opening balance / manual receipts) and
    query inventory.

    For purchasing, the recommended flow is:
        MM Goods Receipt -> calls BatchService.create_from_gr() under the hood
    """

    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: exec_schemas.BatchCreate,
               client_id: str, user_email: str) -> exec_models.Batch:
        # Uniqueness within tenant
        dup = self.db.query(exec_models.Batch).filter(
            exec_models.Batch.client_id == client_id,
            exec_models.Batch.batch_code == payload.batch_code,
        ).first()
        if dup:
            raise BusinessRuleError(f"Batch {payload.batch_code} already exists")

        # Pull country_of_origin default from material if not specified
        country = payload.country_of_origin
        if country is None:
            material = self.db.query(Material).filter(
                Material.client_id == client_id,
                Material.material_code == payload.material_code,
            ).first()
            if material:
                country = material.country_of_origin

        batch = exec_models.Batch(
            client_id=client_id,
            batch_code=payload.batch_code,
            material_code=payload.material_code,
            plant_code=payload.plant_code,
            storage_location=payload.storage_location,
            quantity=payload.quantity,
            initial_quantity=payload.quantity,
            unit=payload.unit,
            source_type=payload.source_type,
            source_reference=payload.source_reference,
            country_of_origin=country,
            vendor_code=payload.vendor_code,
            quality_status=payload.quality_status,
            production_date=payload.production_date,
            expiry_date=payload.expiry_date,
            created_by=user_email,
            updated_by=user_email,
        )
        self.db.add(batch)
        self.db.flush()
        return batch


# ==================================================================
# Genealogy traversal (forward / backward)
# ==================================================================
class GenealogyService:
    """Walk batch genealogy in either direction.

    BACKWARD: 'this batch was made from which raw lots?'
              walks parent_batch_code via children
    FORWARD : 'this raw lot ended up in which produced lots?'
              walks child_batch_code via parents
    """

    MAX_DEPTH = 30

    def __init__(self, db: Session):
        self.db = db

    def trace_backward(self, client_id: str,
                       batch_code: str) -> exec_schemas.GenealogyResponse:
        root = self._build_node(client_id, batch_code)
        self._walk_backward(client_id, root, depth=0, visited=set())
        return exec_schemas.GenealogyResponse(
            direction="BACKWARD",
            root_batch_code=batch_code,
            tree=root,
        )

    def trace_forward(self, client_id: str,
                      batch_code: str) -> exec_schemas.GenealogyResponse:
        root = self._build_node(client_id, batch_code)
        self._walk_forward(client_id, root, depth=0, visited=set())
        return exec_schemas.GenealogyResponse(
            direction="FORWARD",
            root_batch_code=batch_code,
            tree=root,
        )

    # ---- helpers ----
    def _build_node(self, client_id: str,
                    batch_code: str) -> exec_schemas.GenealogyNode:
        b = self.db.query(exec_models.Batch).filter(
            exec_models.Batch.client_id == client_id,
            exec_models.Batch.batch_code == batch_code,
        ).first()
        if not b:
            raise NotFoundError("Batch", batch_code)
        return exec_schemas.GenealogyNode(
            batch_code=b.batch_code,
            material_code=b.material_code,
            quantity=b.quantity,
            unit=b.unit,
            country_of_origin=b.country_of_origin,
            vendor_code=b.vendor_code,
            quality_status=b.quality_status,
            source_type=b.source_type,
            source_reference=b.source_reference,
            children=[],
        )

    def _walk_backward(self, client_id: str,
                       node: exec_schemas.GenealogyNode,
                       depth: int, visited: set) -> None:
        """Find all parent batches that fed into node.batch_code."""
        if depth > self.MAX_DEPTH or node.batch_code in visited:
            return
        visited = visited | {node.batch_code}
        rows = self.db.query(exec_models.BatchGenealogy).filter(
            exec_models.BatchGenealogy.client_id == client_id,
            exec_models.BatchGenealogy.child_batch_code == node.batch_code,
        ).all()
        for row in rows:
            parent = self._build_node(client_id, row.parent_batch_code)
            parent.consumed_quantity = row.consumed_quantity
            parent.consumed_in_order = row.process_order_number
            self._walk_backward(client_id, parent, depth + 1, visited)
            node.children.append(parent)

    def _walk_forward(self, client_id: str,
                      node: exec_schemas.GenealogyNode,
                      depth: int, visited: set) -> None:
        """Find all child batches that consumed node.batch_code."""
        if depth > self.MAX_DEPTH or node.batch_code in visited:
            return
        visited = visited | {node.batch_code}
        rows = self.db.query(exec_models.BatchGenealogy).filter(
            exec_models.BatchGenealogy.client_id == client_id,
            exec_models.BatchGenealogy.parent_batch_code == node.batch_code,
        ).all()
        for row in rows:
            child = self._build_node(client_id, row.child_batch_code)
            child.consumed_quantity = row.consumed_quantity
            child.consumed_in_order = row.process_order_number
            self._walk_forward(client_id, child, depth + 1, visited)
            node.children.append(child)
