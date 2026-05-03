"""GTS service - orchestrates calls to AI_TradeManagement.

This is the only module that talks to the integration client. All other
modules go through GTSService so the integration can be mocked / replaced
without touching business modules.
"""
from datetime import datetime
import logging

from sqlalchemy.orm import Session

from app.integrations.ai_trade_management import client as ai_client
from app.integrations.ai_trade_management import schemas as ai_schemas
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.sd.models import SalesOrder

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
        # 1. HS code (only if not already set)
        if not material.hs_code:
            hs = self.ai.hs_classify(ai_schemas.HSClassifyRequest(
                description=material.description,
                material_code=material.material_code,
                country_of_origin=material.country_of_origin,
            ))
            material.hs_code = hs.hs_code

        # 2. 該非判定 (FEFTA / EAR)
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
    # Export check on Sales Order
    # ------------------------------------------------------------------
    def check_export(self, so: SalesOrder, customer: BusinessPartner) -> SalesOrder:
        # Build item info, including each material's ECCN
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

        # Map AI_TM decision to ERP status
        if result.decision == "PASSED":
            so.export_check_status = "PASSED"
        elif result.decision == "BLOCKED":
            so.export_check_status = "BLOCKED"
        elif result.decision == "NEEDS_LICENSE":
            so.export_check_status = "BLOCKED"  # treat as blocking until license attached
        else:
            so.export_check_status = "PENDING"

        so.export_check_ref = result.check_id
        so.export_check_message = result.message
        return so

    # ------------------------------------------------------------------
    # BOM-based judgment (Phase 2D)
    # ------------------------------------------------------------------
    def judge_bom(self, material_code: str, plant_code: str,
                  client_id: str) -> ai_schemas.BomJudgeResponse:
        """Send a BOM compliance snapshot to AI_TM and return its judgment.

        ERP gathers the snapshot internally (via PP service), AI_TM applies
        its rules. ERP does not encode any judgment logic itself.
        """
        # Local import to avoid circular dependencies
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
