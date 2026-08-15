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
from app.modules.gts.models import AITMTransactionLink, AITMShipmentLink, DeniedPartyScreeningLog
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.sd.models import Delivery, SalesOrder
from app.shared.base_models import DocStatus

logger = logging.getLogger(__name__)


class GTSService:
    def __init__(self, db: Session):
        self.db = db
        self.ai = ai_client.get_client()

    # ------------------------------------------------------------------
    # 品目登録 / 分類 (引き継ぎ書 v2.4: POST /api/products)
    # ------------------------------------------------------------------
    _MATERIAL_TYPE_MAP = {
        "FERT": "equipment",
        "HALB": "component",
        "ROH":  "component",
        "DIEN": "software",
    }

    def register_product(self, material: Material) -> ai_schemas.ProductRegisterResponse:
        """品目を ai_classification に登録/同期する。"""
        item_type = self._MATERIAL_TYPE_MAP.get(material.material_type, "component")
        req = ai_schemas.ProductRegisterRequest(
            code=material.material_code,
            name=material.description,
            usage_summary=material.description,
            item_type=item_type,
            eccn=material.eccn,
            hs_code=material.hs_code,
            export_control_status="not_evaluated",
        )
        result = self.ai.register_product(req)
        material.last_compliance_check_at = datetime.utcnow().isoformat()
        logger.info(
            "ProductRegister %s (item_type=%s) → AI_TM id=%s status=%s",
            material.material_code, item_type, result.id, result.export_control_status,
        )
        return result

    def classify_material(self, material: Material) -> Material:
        """HS分類 + 該非判定を実行して品目を更新する。

        新環境では register_product() で品目登録を推奨。
        旧ゲートウェイ互換エンドポイントを経由して HS/ECCN を取得し
        ERP の品目マスタに反映する。
        """
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
    # 制裁スクリーニング (引き継ぎ書 v2.4: POST /api/screening/batch)
    # ------------------------------------------------------------------
    def screen_business_partner(
        self, bp: BusinessPartner, screened_by: str = "system"
    ) -> BusinessPartner:
        """取引先を制裁リストに対してスクリーニングし、結果をBPとログに反映する。

        照合リスト: OFAC_SDN / BIS_ENTITY / EU_CONSOLIDATED / METI_FUL / OFAC_50PCT
        結果はDeniedPartyScreeningLogに記録し、BusinessPartner.screening_statusを更新する。
        """
        import json
        req = ai_schemas.ScreeningBatchRequest(
            entities=[ai_schemas.ScreeningEntity(
                name=bp.name,
                country=bp.country,
                entity_type="company",
            )],
        )
        try:
            resp = self.ai.screening_batch(req)
        except Exception as exc:
            # AI_TM が未起動 / 接続不可の場合はローカルルールにフォールバック
            logger.warning(
                "AI_TM screening_batch failed (%s), falling back to local rules", exc
            )
            from app.integrations.ai_trade_management.client import _MockClient
            resp = _MockClient().screening_batch(req)
        screened_at = datetime.utcnow().isoformat()

        if not resp.results:
            bp.screening_status = "CLEARED"
            bp.last_screened_at = screened_at
            return bp

        r = resp.results[0]
        is_flagged = r.status in ("match", "CRITICAL")
        is_possible = r.status == "possible_match"

        # BusinessPartner フィールド更新
        bp.is_denied_party = is_flagged
        bp.screening_status = (
            "BLOCKED" if r.status == "CRITICAL"
            else "FLAGGED" if is_flagged
            else "FLAGGED" if is_possible
            else "CLEARED"
        )
        bp.denial_list = r.matched_list
        bp.denial_reason = r.denial_reason
        bp.last_screened_at = screened_at
        bp.fifty_pct_rule_triggered = getattr(r, "fifty_pct_rule_triggered", False)
        bp.parent_sanctioned_entity = getattr(r, "parent_sanctioned_entity", None)

        # AI_TM への Webhook 通知 (FLAGGED / BLOCKED の場合)
        ai_ref = None
        if is_flagged or is_possible:
            try:
                event_payload = {
                    "event_type": "DENIED_PARTY_MATCH",
                    "bp_code": bp.bp_code,
                    "bp_name": bp.name,
                    "country": bp.country,
                    "match_status": r.status,
                    "match_score": r.score,
                    "matched_list": r.matched_list,
                    "matched_entity": r.matched_entity,
                    "denial_reason": r.denial_reason,
                    "fifty_pct_rule": getattr(r, "fifty_pct_rule_triggered", False),
                    "parent_entity": getattr(r, "parent_sanctioned_entity", None),
                    "screened_at": screened_at,
                }
                result = self.ai.post_event(event_payload)
                ai_ref = getattr(result, "case_ref", None)
                bp.ai_tm_screening_ref = ai_ref
                logger.warning(
                    "BP %s FLAGGED: status=%s score=%.2f list=%s → AI_TM ref=%s",
                    bp.bp_code, r.status, r.score, r.matched_list, ai_ref,
                )
            except Exception as exc:
                logger.error("AI_TM event push failed for BP %s: %s", bp.bp_code, exc)

        # 監査ログ記録
        log = DeniedPartyScreeningLog(
            client_id=bp.client_id,
            bp_code=bp.bp_code,
            bp_name=bp.name,
            bp_country=bp.country,
            match_status=r.status,
            match_score=r.score,
            matched_list=r.matched_list,
            matched_entity_name=r.matched_entity,
            denial_reason=r.denial_reason,
            fifty_pct_rule_triggered=getattr(r, "fifty_pct_rule_triggered", False),
            parent_sanctioned_entity=getattr(r, "parent_sanctioned_entity", None),
            ownership_pct=getattr(r, "ownership_pct", None),
            ai_tm_screening_ref=ai_ref,
            raw_response_json=json.dumps(r.model_dump(), default=str),
            screened_at=datetime.utcnow(),
            screened_by=screened_by,
        )
        self.db.add(log)

        return bp

    # ------------------------------------------------------------------
    # 取引審査 (引き継ぎ書 v2.4: ai_validation 多段階フロー)
    # ------------------------------------------------------------------
    def transaction_review(
        self, so: SalesOrder, customer: BusinessPartner
    ) -> tuple[AITMTransactionLink, ai_schemas.TransactionCreateResponse]:
        """受注を AI_TM 取引審査に起票し、スクリーニング・AI判定を実行する。

        フロー:
          1. POST /api/transactions      → 案件作成
          2. POST ./{id}/screening       → 制裁照合
          3. POST ./{id}/ai-judge        → AI 判定
        Returns (link_record, transaction_response).
        """
        # 最もリスクの高い品目を代表品目として選択
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

        # ① 案件作成
        item_list = []
        if best_item and best_material:
            item_list = [ai_schemas.TransactionItem(
                item_name=best_item.material_code,
                item_description=best_material.description,
            )]
        create_req = ai_schemas.TransactionCreateRequest(
            title=so.document_number,           # required field; use SO number as title
            counterparty_name=customer.name,
            destination_country=customer.country,
            items=item_list,
            source_module="ERP",
        )
        tx = self.ai.create_transaction(create_req)

        # ② 制裁照合
        try:
            self.ai.run_screening(tx.id)
        except Exception as e:
            logger.warning("Screening failed for tx_id=%s: %s", tx.id, e)

        # ③ AI 判定
        judge_result = None
        try:
            judge_result = self.ai.run_ai_judge(tx.id)
        except Exception as e:
            logger.warning("AI judge failed for tx_id=%s: %s", tx.id, e)

        # 判定ステータスを ERP 内部形式にマッピング
        ai_status = judge_result.status if judge_result else tx.ai_status or "PENDING"
        judgment_map = {
            "CLEAR": "APPROVED",
            "REVIEW": "NEEDS_REVIEW",
            "REQUIRES_PERMIT": "NEEDS_REVIEW",
            "BLOCKED": "REJECTED",      # restricted destination country
        }
        erp_judgment = judgment_map.get(ai_status, "PENDING")
        approved = ai_status == "CLEAR"

        link = AITMTransactionLink(
            client_id=so.client_id,
            sales_order_id=so.id,
            review_id=str(tx.id),
            review_status=erp_judgment,
            review_level="AUTO",
            eccn=best_material.eccn if best_material else None,
            linked_existing=False,
            last_sync_at=datetime.utcnow(),
        )
        if approved:
            link.approved_at = datetime.utcnow()
            link.expires_at = datetime.utcnow() + timedelta(
                days=settings.AI_TM_REVIEW_VALID_DAYS
            )

        self.db.add(link)

        logger.info(
            "TransactionReview SO=%s ai_status=%s erp_judgment=%s tx_id=%s",
            so.document_number, ai_status, erp_judgment, tx.id,
        )
        return link, tx

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


    # ------------------------------------------------------------------
    # Origin Change → AI_TM notification
    # ------------------------------------------------------------------
    def push_origin_change_to_aitm(self, payload: dict) -> str:
        """Push a material origin change event to AI_TM.

        Returns a case reference string. Falls back to a local reference
        if AI_TM is unreachable.
        """
        import uuid
        try:
            result = self.ai.post_event(payload)
            case_ref = getattr(result, "case_ref", None) or getattr(result, "id", None) or str(uuid.uuid4())
        except Exception as exc:
            logger.warning("AI_TM push_origin_change failed (%s) — using local ref", exc)
            material = payload.get("material_code", "UNK")
            case_ref = f"LOCAL-OCL-{material}-{uuid.uuid4().hex[:8].upper()}"
        logger.info("Origin change for %s pushed to AI_TM → ref=%s", payload.get("material_code"), case_ref)
        return case_ref


# ==================================================================
# Export Declaration Service
# ==================================================================
class ExportDeclarationService:
    """Manages export declaration lifecycle and AI_TM license linkage."""

    def __init__(self, db: Session):
        from app.modules.gts.models import ExportDeclaration
        from app.modules.gts import schemas as gts_schemas
        self._model = ExportDeclaration
        self._schemas = gts_schemas
        self.db = db

    def create(self, payload, client_id: str, user_email: str):
        from app.shared.base_repository import BaseRepository
        repo = BaseRepository(self._model, self.db)
        data = payload.model_dump()
        data.update({
            "client_id": client_id,
            "status": "DRAFT",
            "created_by": user_email if hasattr(self._model, "created_by") else None,
        })
        data = {k: v for k, v in data.items() if v is not None or k in
                ("delivery_id", "sales_order_id", "declaration_number")}
        # ExportDeclaration doesn't use MasterDataMixin, set client_id manually
        instance = self._model(**{**payload.model_dump(), "client_id": client_id,
                                  "status": "DRAFT"})
        self.db.add(instance)
        self.db.flush()
        self.db.refresh(instance)
        return instance

    def submit(self, declaration_id: int, client_id: str,
               user_email: str):
        from app.core.exceptions import NotFoundError, BusinessRuleError
        from sqlalchemy import select
        stmt = select(self._model).where(
            self._model.id == declaration_id,
            self._model.client_id == client_id,
        )
        instance = self.db.execute(stmt).scalar_one_or_none()
        if not instance:
            raise NotFoundError("ExportDeclaration", declaration_id)
        if instance.status != "DRAFT":
            raise BusinessRuleError(
                f"ExportDeclaration {declaration_id} status is {instance.status}, "
                "can only submit DRAFT declarations")
        instance.status = "SUBMITTED"
        self.db.flush()
        return instance
