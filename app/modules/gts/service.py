"""GTS service - orchestrates calls to AI_TradeManagement.

This is the only module that talks to the integration client. All other
modules go through GTSService so the integration can be mocked / replaced
without touching business modules.
"""
from datetime import datetime, timedelta
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.integrations.ai_trade_management import client as ai_client
from app.integrations.ai_trade_management import schemas as ai_schemas
from app.modules.gts.models import AITMTransactionLink, AITMShipmentLink
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.sd.models import Delivery, SalesOrder
from app.shared.base_models import DocStatus

logger = logging.getLogger(__name__)


class GTSService:
    def __init__(self, db: Session):
        self.db = db
        self.ai = ai_client.get_client()

    # ------------------------------------------------------------------
    # Material classification
    # ------------------------------------------------------------------
    def classify_material(self, material: Material) -> Material:
        """Run HS classification + 該非判定 and update the material."""
        if not material.hs_code:
            hs = self.ai.hs_classify(ai_schemas.HSClassifyRequest(
                description=material.description,
                material_code=material.material_code,
                country_of_origin=material.country_of_origin,
            ))
            material.hs_code = hs.hs_code

        gaihi = self.ai.gaihi_judge(ai_schemas.GaihiJudgeRequest(
            material_code=material.material_code,
            description=material.description,
            hs_code=material.hs_code,
        ))
        material.fefta_judgment = gaihi.judgment
        if gaihi.eccn:
            material.eccn = gaihi.eccn
        material.last_compliance_check_at = datetime.utcnow().isoformat()

        logger.info(
            "Material %s classified: HS=%s ECCN=%s judgment=%s",
            material.material_code, material.hs_code, material.eccn, material.fefta_judgment,
        )
        return material

    # ------------------------------------------------------------------
    # Denied-party screening
    # ------------------------------------------------------------------
    def screen_business_partner(self, bp: BusinessPartner) -> BusinessPartner:
        result = self.ai.denied_party_check(ai_schemas.DeniedPartyRequest(
            name=bp.name,
            country=bp.country,
            address=bp.address_line1,
        ))
        bp.is_denied_party = result.is_match
        if result.is_match:
            logger.warning(
                "BP %s flagged: %s (%s)",
                bp.bp_code, result.list_name, result.rationale,
            )
        return bp

    # ------------------------------------------------------------------
    # Transaction review (replaces export_check as primary compliance gate)
    # ------------------------------------------------------------------
    def transaction_review(
        self, so: SalesOrder, customer: BusinessPartner
    ) -> tuple[AITMTransactionLink, ai_schemas.TransactionReviewResponse]:
        """Submit a SalesOrder to AI_TM for transaction review.

        Uses the most export-controlled item to represent the order.
        Returns (link_record, raw_response).
        """
        # Pick the most critical item (controlled ECCN first, else first item)
        best_item = None
        best_material = None
        for item in so.items:
            mat = self.db.query(Material).filter(
                Material.material_code == item.material_code,
                Material.client_id == so.client_id,
            ).first()
            if mat and mat.eccn and mat.eccn != "EAR99":
                best_item, best_material = item, mat
                break
        if best_item is None and so.items:
            best_item = so.items[0]
            best_material = self.db.query(Material).filter(
                Material.material_code == best_item.material_code,
                Material.client_id == so.client_id,
            ).first()

        req = ai_schemas.TransactionReviewRequest(
            erp_transaction_id=so.document_number,
            item_code=best_item.material_code if best_item else "",
            item_name=(best_material.description if best_material else ""),
            item_description=(best_material.description if best_material else ""),
            hs_code=best_material.hs_code if best_material else None,
            eccn=best_material.eccn if best_material else None,
            counterparty_name=customer.name,
            counterparty_country=customer.country,
            counterparty_address=getattr(customer, "address_line1", None),
            destination_country=customer.country,
            quantity=float(best_item.quantity) if best_item else 0.0,
            value_usd=float(so.total_amount),
        )

        result = self.ai.transaction_review(req)

        link = AITMTransactionLink(
            client_id=so.client_id,
            sales_order_id=so.id,
            review_id=result.review_id,
            review_status=result.judgment,
            review_level=result.review_level,
            eccn=result.eccn,
            linked_existing=result.linked_existing,
            last_sync_at=datetime.utcnow(),
        )
        if result.approved:
            link.approved_at = datetime.utcnow()
            link.expires_at = datetime.utcnow() + timedelta(
                days=settings.AI_TM_REVIEW_VALID_DAYS
            )

        self.db.add(link)

        logger.info(
            "TransactionReview SO=%s judgment=%s review_id=%s",
            so.document_number, result.judgment, result.review_id,
        )
        return link, result

    # ------------------------------------------------------------------
    # Shipment re-screening
    # ------------------------------------------------------------------
    def shipment_rescreen(
        self, delivery: Delivery, review_id: str
    ) -> AITMShipmentLink:
        """Re-screen a delivery against the linked AI_TM review.

        Returns the shipment link record. Caller must check link.shipment_ok.
        """
        req = ai_schemas.ShipmentRescreenRequest(
            review_id=review_id,
            erp_shipment_id=delivery.document_number,
        )
        result = self.ai.shipment_rescreen(req)

        link = AITMShipmentLink(
            client_id=delivery.client_id,
            delivery_id=delivery.id,
            review_id=review_id,
            shipment_ok=result.approved,
            rescreen_at=datetime.utcnow(),
            rescreen_result="CHANGED" if result.rescreen_changed else "PASSED",
            block_reason=result.message if not result.approved else None,
        )
        self.db.add(link)

        logger.info(
            "ShipmentRescreen DEL=%s approved=%s changed=%s",
            delivery.document_number, result.approved, result.rescreen_changed,
        )
        return link

    # ------------------------------------------------------------------
    # Export check (legacy — kept for backward compatibility)
    # ------------------------------------------------------------------
    def check_export(self, so: SalesOrder, customer: BusinessPartner) -> SalesOrder:
        items = []
        for it in so.items:
            material = self.db.query(Material).filter(
                Material.material_code == it.material_code,
                Material.client_id == so.client_id,
            ).first()
            items.append(ai_schemas.ExportCheckItem(
                material_code=it.material_code,
                quantity=float(it.quantity),
                eccn=material.eccn if material else None,
                hs_code=material.hs_code if material else None,
            ))

        result = self.ai.export_check(ai_schemas.ExportCheckRequest(
            reference=so.document_number,
            destination_country=customer.country,
            customer_code=customer.bp_code,
            customer_name=customer.name,
            items=items,
        ))

        if result.decision == "PASSED":
            so.export_check_status = "PASSED"
        elif result.decision in ("BLOCKED", "NEEDS_LICENSE"):
            so.export_check_status = "BLOCKED"
        else:
            so.export_check_status = "PENDING"

        so.export_check_ref = result.check_id
        so.export_check_message = result.message
        return so

    # ------------------------------------------------------------------
    # BOM-based judgment
    # ------------------------------------------------------------------
    def judge_bom(self, material_code: str, plant_code: str,
                  client_id: str) -> ai_schemas.BomJudgeResponse:
        from app.modules.pp.service import ComplianceSnapshotService

        snapshot = ComplianceSnapshotService(self.db).build(
            client_id, material_code, plant_code,
        )

        request = ai_schemas.BomJudgeRequest(
            material_code=snapshot.material_code,
            plant_code=snapshot.plant_code,
            production_version_code=snapshot.production_version_code,
            product_hs_code=snapshot.product_hs_code,
            product_eccn=snapshot.product_eccn,
            components=[
                ai_schemas.BomComponent(
                    level=c.level,
                    material_code=c.material_code,
                    description=c.description,
                    quantity=float(c.quantity),
                    unit=c.unit,
                    hs_code=c.hs_code,
                    eccn=c.eccn,
                    country_of_origin=c.country_of_origin,
                    fefta_judgment=c.fefta_judgment,
                ) for c in snapshot.components
            ],
        )

        result = self.ai.judge_bom(request)
        logger.info(
            "BOM judgment for %s@%s: %s (%d controlled, %.1f%% foreign)",
            material_code, plant_code, result.judgment,
            len(result.controlled_components),
            result.foreign_origin_share_percent,
        )
        return result

    # ------------------------------------------------------------------
    # Webhook: judgment updated by AI_TM
    # ------------------------------------------------------------------
    def apply_judgment_update(
        self,
        client_id: str,
        material_code: str,
        new_judgment: str,
        new_eccn: str | None,
        rationale: str | None,
    ) -> dict:
        """Apply an incoming judgment update from AI_TM.

        - Updates material ECCN / judgment
        - Auto-unblocks deliveries if APPROVED
        - Cancels open SOs / blocks deliveries if REJECTED
        """
        material = self.db.query(Material).filter(
            Material.material_code == material_code,
            Material.client_id == client_id,
        ).first()

        if not material:
            logger.warning("Webhook: material %s not found in client %s", material_code, client_id)
            return {"updated": False, "reason": "material not found"}

        material.fefta_judgment = new_judgment
        if new_eccn:
            material.eccn = new_eccn
        material.last_compliance_check_at = datetime.utcnow().isoformat()

        affected_so_ids: list[int] = []
        affected_del_ids: list[int] = []

        if new_judgment == "APPROVED":
            # Auto-unblock deliveries that were blocked for this material's review
            links = (
                self.db.query(AITMShipmentLink)
                .filter(
                    AITMShipmentLink.client_id == client_id,
                    AITMShipmentLink.shipment_ok == False,  # noqa: E712
                )
                .all()
            )
            for ship_link in links:
                delivery = self.db.get(Delivery, ship_link.delivery_id)
                if delivery and delivery.status == DocStatus.BLOCKED:
                    delivery.status = DocStatus.OPEN
                    ship_link.shipment_ok = True
                    ship_link.rescreen_result = "PASSED"
                    ship_link.block_reason = None
                    affected_del_ids.append(delivery.id)

            # Unblock corresponding SO transaction links
            tx_links = (
                self.db.query(AITMTransactionLink)
                .filter(
                    AITMTransactionLink.client_id == client_id,
                    AITMTransactionLink.review_status == "NEEDS_REVIEW",
                )
                .all()
            )
            for tx_link in tx_links:
                so = self.db.get(SalesOrder, tx_link.sales_order_id)
                if so and so.status == DocStatus.BLOCKED:
                    so.status = DocStatus.OPEN
                    so.export_check_status = "PASSED"
                    tx_link.review_status = "APPROVED"
                    tx_link.approved_at = datetime.utcnow()
                    tx_link.expires_at = datetime.utcnow() + timedelta(
                        days=settings.AI_TM_REVIEW_VALID_DAYS
                    )
                    affected_so_ids.append(so.id)

        elif new_judgment == "REJECTED":
            # Cancel open SOs containing this material
            from app.modules.sd.models import SalesOrderItem
            so_ids_with_material = [
                row[0] for row in
                self.db.query(SalesOrderItem.sales_order_id)
                .filter(
                    SalesOrderItem.material_code == material_code,
                )
                .distinct()
                .all()
            ]
            for so_id in so_ids_with_material:
                so = self.db.get(SalesOrder, so_id)
                if so and so.client_id == client_id and so.status not in (
                    DocStatus.COMPLETED, DocStatus.CANCELLED
                ):
                    so.status = DocStatus.CANCELLED
                    so.export_check_status = "BLOCKED"
                    affected_so_ids.append(so.id)

        logger.info(
            "Webhook applied: material=%s judgment=%s eccn=%s "
            "unblocked_so=%s unblocked_del=%s",
            material_code, new_judgment, new_eccn,
            affected_so_ids, affected_del_ids,
        )
        return {
            "updated": True,
            "material_code": material_code,
            "new_judgment": new_judgment,
            "affected_sales_orders": affected_so_ids,
            "affected_deliveries": affected_del_ids,
        }
