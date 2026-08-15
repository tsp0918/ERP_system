"""HTTP client for AI_TradeManagement.

引き継ぎ書 v2.4 対応。モジュール別URLへの直接アクセスに切り替え。
認証: X-Organization-Id / X-User-Id ヘッダー (Bearer トークン不要)

MOCK_MODE=true の場合は _MockClient が返る (AI_TM 未起動でも動作可)。
"""
import logging
import uuid
from typing import Optional

import httpx

from app.core.config import settings
from app.core.exceptions import IntegrationError
from app.integrations.ai_trade_management import schemas

logger = logging.getLogger(__name__)


# ==================================================================
# Mock client
# ==================================================================
class _MockClient:
    """引き継ぎ書 v2.4 インターフェースのモック実装。"""

    RESTRICTED_COUNTRIES = {"IR", "KP", "SY", "CU"}
    # RU/BY は possible_match 扱い (完全禁止ではなくリスト記載)
    ELEVATED_RISK_COUNTRIES = {"RU", "BY", "VE", "MM"}
    CONTROLLED_KEYWORDS = ["PRECURSOR", "GAS", "SILANE", "ETCH"]

    def __init__(self):
        # tx_id → destination_country mapping for country-aware run_ai_judge
        self._tx_countries: dict[int, str] = {}

    # BIS Entity List (EAR §744.11) - 代表的な掲載企業キーワード
    BIS_ENTITY_LIST: dict[str, dict] = {
        "HUAWEI": {
            "list": "BIS_ENTITY",
            "score": 0.98,
            "reason": "BIS Entity List (EAR §744.11): Advanced semiconductor & telecom equipment. "
                      "No license exception applies.",
            "matched": "Huawei Technologies Co., Ltd.",
            "status": "CRITICAL",
        },
        "ZTE": {
            "list": "BIS_ENTITY",
            "score": 0.97,
            "reason": "BIS Entity List: ZTE Corporation. Violations of US export regulations.",
            "matched": "ZTE Corporation",
            "status": "CRITICAL",
        },
        "SMIC": {
            "list": "BIS_ENTITY",
            "score": 0.96,
            "reason": "BIS Entity List: Semiconductor Manufacturing International Corporation. "
                      "Military end-use concern (EAR §744.21).",
            "matched": "Semiconductor Manufacturing International Corporation",
            "status": "CRITICAL",
        },
        "SEMICONDUCTOR MANUFACTURING INTERNATIONAL": {
            "list": "BIS_ENTITY",
            "score": 0.96,
            "reason": "BIS Entity List: Semiconductor Manufacturing International Corporation (SMIC). "
                      "Military end-use concern (EAR §744.21).",
            "matched": "Semiconductor Manufacturing International Corporation",
            "status": "CRITICAL",
        },
        "YANGTZE MEMORY": {
            "list": "BIS_ENTITY",
            "score": 0.96,
            "reason": "BIS Entity List: Yangtze Memory Technologies Co., Ltd. (YMTC). "
                      "Advanced NAND memory, military-civil fusion concerns (EAR §744.21).",
            "matched": "Yangtze Memory Technologies Co., Ltd.",
            "status": "CRITICAL",
        },
        "YMTC": {
            "list": "BIS_ENTITY",
            "score": 0.96,
            "reason": "BIS Entity List: Yangtze Memory Technologies Co., Ltd. (YMTC). "
                      "Advanced NAND memory, military-civil fusion concerns.",
            "matched": "Yangtze Memory Technologies Co., Ltd.",
            "status": "CRITICAL",
        },
        "HIKVISION": {
            "list": "BIS_ENTITY",
            "score": 0.97,
            "reason": "BIS Entity List: Hangzhou Hikvision Digital Technology. "
                      "Human rights / surveillance concerns.",
            "matched": "Hangzhou Hikvision Digital Technology Co., Ltd.",
            "status": "CRITICAL",
        },
        "DAHUA": {
            "list": "BIS_ENTITY",
            "score": 0.96,
            "reason": "BIS Entity List: Zhejiang Dahua Technology. Surveillance equipment.",
            "matched": "Zhejiang Dahua Technology Co., Ltd.",
            "status": "CRITICAL",
        },
        "CAMBRICON": {
            "list": "BIS_ENTITY",
            "score": 0.94,
            "reason": "BIS Entity List: Cambricon Technologies. AI chip design, military application.",
            "matched": "Cambricon Technologies Co., Ltd.",
            "status": "match",
        },
        "PHYTIUM": {
            "list": "BIS_ENTITY",
            "score": 0.95,
            "reason": "BIS Entity List: Phytium Technology. High-performance processor, "
                      "supercomputer & military use.",
            "matched": "Phytium Information Technology Co., Ltd.",
            "status": "CRITICAL",
        },
    }

    # OFAC SDN List 掲載企業キーワード
    OFAC_SDN_LIST: dict[str, dict] = {
        "ROSTEC": {
            "list": "OFAC_SDN",
            "score": 0.99,
            "reason": "OFAC SDN: State Corporation Rostec. Russian defense conglomerate. "
                      "E.O. 13661.",
            "matched": "State Corporation Rostec",
            "status": "CRITICAL",
        },
        "IRAN AIR": {
            "list": "OFAC_SDN",
            "score": 0.98,
            "reason": "OFAC SDN: Iran Air. Designated under Iran Sanctions (ITSR).",
            "matched": "Iran Air (Hava Peyma Jomhouri Eslami Iran)",
            "status": "CRITICAL",
        },
        "MAHAN AIR": {
            "list": "OFAC_SDN",
            "score": 0.97,
            "reason": "OFAC SDN: Mahan Air. IRGC support, terrorism nexus (E.O. 13224).",
            "matched": "Mahan Airlines",
            "status": "CRITICAL",
        },
        "BANK MELLI": {
            "list": "OFAC_SDN",
            "score": 0.98,
            "reason": "OFAC SDN: Bank Melli Iran. Primary conduit for IRGC financing.",
            "matched": "Bank Melli Iran",
            "status": "CRITICAL",
        },
        "SOVCOMFLOT": {
            "list": "OFAC_SDN",
            "score": 0.97,
            "reason": "OFAC SDN: PJSC Sovcomflot. Russian state shipping company, sanctioned under "
                      "E.O. 14024 (Russia). Vessel chartering prohibited.",
            "matched": "Public Joint-Stock Company Sovcomflot (SCF)",
            "status": "CRITICAL",
        },
        "NATIONAL IRANIAN TANKER": {
            "list": "OFAC_SDN",
            "score": 0.99,
            "reason": "OFAC SDN: National Iranian Tanker Company (NITC). Primary Iranian crude oil shipper.",
            "matched": "National Iranian Tanker Company",
            "status": "CRITICAL",
        },
    }

    # OFAC / BIS 懸念企業 (possible_match - 確定ではないが要調査)
    WATCHLIST: dict[str, dict] = {
        "COSCO SHIPPING": {
            "list": "OFAC_WATCH,BIS_WATCH",
            "score": 0.65,
            "reason": "COSCO SHIPPING: Some COSCO affiliated vessels listed on OFAC SDN (COSCO Shipping "
                      "Tanker Co.). Requires enhanced due diligence. Not all COSCO entities are designated.",
            "matched": "COSCO SHIPPING (certain affiliated tanker subsidiaries)",
            "status": "possible_match",
        },
        "GALAXY HORIZON": {
            "list": "OFAC_WATCH",
            "score": 0.72,
            "reason": "Galaxy Horizon Trading LLC (UAE): Intelligence indicates possible Iran re-export "
                      "channel. UAE-based entity acting as intermediary for Iranian end-users. "
                      "Enhanced due diligence and end-user certificate required.",
            "matched": "Galaxy Horizon Trading LLC",
            "status": "possible_match",
        },
    }

    # OFAC 50% Rule 掲載企業キーワード (親会社がSDN → 子会社も自動適用)
    OFAC_50PCT_LIST: dict[str, dict] = {
        "HUAWEI MARINE": {
            "list": "OFAC_50PCT",
            "score": 0.90,
            "reason": "OFAC 50% Rule: Subsidiary of Huawei Technologies (BIS Entity List). "
                      "50%+ ownership by listed entity.",
            "matched": "Huawei Marine Networks Co., Ltd.",
            "status": "match",
            "parent": "Huawei Technologies Co., Ltd.",
            "ownership_pct": 51.0,
        },
        "HISILICON": {
            "list": "OFAC_50PCT,BIS_ENTITY",
            "score": 0.95,
            "reason": "BIS Entity List + OFAC 50% Rule: HiSilicon Technologies, "
                      "wholly-owned subsidiary of Huawei. Chip design.",
            "matched": "HiSilicon Technologies Co., Ltd.",
            "status": "CRITICAL",
            "parent": "Huawei Technologies Co., Ltd.",
            "ownership_pct": 100.0,
        },
        "TECHNOPROMEXPORT": {
            "list": "OFAC_50PCT,OFAC_SDN",
            "score": 0.92,
            "reason": "OFAC 50% Rule + SDN: JSC Technopromexport. "
                      "50%+ owned by Rostec (SDN). Russian power plant EPC.",
            "matched": "JSC Technopromexport",
            "status": "CRITICAL",
            "parent": "State Corporation Rostec",
            "ownership_pct": 100.0,
        },
    }
    HS_HINTS = {
        "PHOTORESIST": "3707.90", "RESIST": "3707.90",
        "SLURRY": "3824.99", "CMP": "3824.99",
        "SOLVENT": "2901.10", "ETCH": "2811.19", "ETCHANT": "2811.19",
        "GAS": "2804.40", "SILANE": "2853.90", "PRECURSOR": "2931.90",
        "WAFER": "3818.00", "POLISHING": "3824.99",
    }

    # ── 品目登録 ──────────────────────────────────────────────────
    def register_product(
        self, req: schemas.ProductRegisterRequest
    ) -> schemas.ProductRegisterResponse:
        return schemas.ProductRegisterResponse(
            id=abs(hash(req.code)) % 10000,
            code=req.code,
            name=req.name,
            export_control_status="not_evaluated",
            created_at="[MOCK]",
        )

    def erp_sync(self, item: schemas.BomSyncItem) -> schemas.ErpSyncResponse:
        return schemas.ErpSyncResponse(
            ok=True,
            id=abs(hash(item.code)) % 10000,
            code=item.code,
            created=False,
        )

    def bom_sync(
        self, items: list[schemas.BomSyncItem]
    ) -> list[schemas.ErpSyncResponse]:
        return [self.erp_sync(it) for it in items]

    # ── 取引審査 (多段階) ─────────────────────────────────────────
    def create_transaction(
        self, req: schemas.TransactionCreateRequest
    ) -> schemas.TransactionCreateResponse:
        mock_id = abs(hash(req.title or "")) % 10000
        # Store destination country so run_ai_judge can evaluate restricted-country rules
        self._tx_countries[mock_id] = req.destination_country or ""
        return schemas.TransactionCreateResponse(
            id=mock_id,
            case_no=f"TXN-{mock_id:06d}",
            title=req.title,
            status="draft",
            screening_queued=True,
        )

    def run_screening(self, tx_id: int) -> schemas.TransactionScreeningResponse:
        return schemas.TransactionScreeningResponse(
            ok=True,
            screening_result={"status": "no_match", "matched_entities": []},
        )

    def run_ai_judge(self, tx_id: int) -> schemas.TransactionAiJudgeResponse:
        country = self._tx_countries.get(tx_id, "")
        if country in self.RESTRICTED_COUNTRIES:
            # Restricted destinations are unconditionally blocked
            return schemas.TransactionAiJudgeResponse(status="BLOCKED")
        return schemas.TransactionAiJudgeResponse(status="CLEAR")

    def get_transaction(self, tx_id: int) -> schemas.TransactionDetailResponse:
        return schemas.TransactionDetailResponse(
            id=tx_id, case_no="[MOCK]", status="reviewed",
            ai_status="CLEAR", final_judgment="CLEAR",
        )

    def find_transaction_by_case_no(
        self, case_no: str
    ) -> schemas.TransactionDetailResponse | None:
        mock_id = abs(hash(case_no)) % 10000
        return schemas.TransactionDetailResponse(
            id=mock_id,
            case_no=case_no,
            status="reviewed",
            ai_status="CLEAR",
            final_judgment="CLEAR",
        )

    # ── 制裁スクリーニング ────────────────────────────────────────
    def screening_batch(
        self, req: schemas.ScreeningBatchRequest
    ) -> schemas.ScreeningBatchResponse:
        results = []
        for e in req.entities:
            result = self._screen_single_entity(e)
            results.append(result)
        return schemas.ScreeningBatchResponse(results=results)

    def _screen_single_entity(self, e: schemas.ScreeningEntity) -> schemas.ScreeningEntityResult:
        """名前・国コードをもとに制裁リストを照合する (モック)。

        照合優先順位:
          1. OFAC 50% Rule (子会社キーワード)
          2. BIS Entity List キーワード
          3. OFAC SDN キーワード
          4. 制限国 (完全禁止: IR/KP/SY/CU)
          5. 高リスク国 (RU/BY 等) → possible_match
          6. クリア
        """
        name_upper = e.name.upper()

        # 0. Watchlist (possible_match - 要調査)
        for keyword, info in self.WATCHLIST.items():
            if keyword in name_upper:
                return schemas.ScreeningEntityResult(
                    name=e.name,
                    status=info["status"],
                    score=info["score"],
                    matched_list=info["list"],
                    matched_entity=info.get("matched"),
                    denial_reason=info["reason"],
                    fifty_pct_rule_triggered=False,
                )

        # 1. 50% Rule check
        for keyword, info in self.OFAC_50PCT_LIST.items():
            if keyword in name_upper:
                extra = {}
                if "parent" in info:
                    extra["matched_entity"] = info["matched"]
                return schemas.ScreeningEntityResult(
                    name=e.name,
                    status=info["status"],
                    score=info["score"],
                    matched_list=info["list"],
                    matched_entity=info.get("matched"),
                    denial_reason=info["reason"],
                    fifty_pct_rule_triggered=True,
                    parent_sanctioned_entity=info.get("parent"),
                    ownership_pct=info.get("ownership_pct"),
                )

        # 2. BIS Entity List check
        for keyword, info in self.BIS_ENTITY_LIST.items():
            if keyword in name_upper:
                return schemas.ScreeningEntityResult(
                    name=e.name,
                    status=info["status"],
                    score=info["score"],
                    matched_list=info["list"],
                    matched_entity=info.get("matched"),
                    denial_reason=info["reason"],
                    fifty_pct_rule_triggered=False,
                )

        # 3. OFAC SDN check
        for keyword, info in self.OFAC_SDN_LIST.items():
            if keyword in name_upper:
                return schemas.ScreeningEntityResult(
                    name=e.name,
                    status=info["status"],
                    score=info["score"],
                    matched_list=info["list"],
                    matched_entity=info.get("matched"),
                    denial_reason=info["reason"],
                    fifty_pct_rule_triggered=False,
                )

        # 4. Restricted country (embargo)
        if e.country in self.RESTRICTED_COUNTRIES:
            return schemas.ScreeningEntityResult(
                name=e.name,
                status="CRITICAL",
                score=0.95,
                matched_list="OFAC_SDN,BIS_ENTITY",
                denial_reason=f"Country embargo: {e.country} is subject to comprehensive sanctions.",
                fifty_pct_rule_triggered=False,
            )

        # 5. Elevated risk country → possible_match
        if e.country in self.ELEVATED_RISK_COUNTRIES:
            return schemas.ScreeningEntityResult(
                name=e.name,
                status="possible_match",
                score=0.40,
                matched_list="OFAC_CAATSA,EU_CONSOLIDATED",
                denial_reason=f"Elevated risk country ({e.country}): Enhanced due diligence required.",
                fifty_pct_rule_triggered=False,
            )

        return schemas.ScreeningEntityResult(
            name=e.name, status="no_match", score=0.0,
        )

    # ── 旧インターフェース (後方互換) ─────────────────────────────
    def hs_classify(self, req: schemas.HSClassifyRequest) -> schemas.HSClassifyResponse:
        desc_upper = req.description.upper()
        for keyword, hs in self.HS_HINTS.items():
            if keyword in desc_upper:
                return schemas.HSClassifyResponse(
                    hs_code=hs, confidence=0.85,
                    rationale=f"[MOCK] Matched keyword '{keyword}'",
                )
        return schemas.HSClassifyResponse(
            hs_code="3824.99", confidence=0.30,
            rationale="[MOCK] Default",
        )

    def gaihi_judge(self, req: schemas.GaihiJudgeRequest) -> schemas.GaihiJudgeResponse:
        is_controlled = any(kw in req.description.upper() for kw in self.CONTROLLED_KEYWORDS)
        if is_controlled:
            return schemas.GaihiJudgeResponse(
                judgment="APPLICABLE", eccn="3C001",
                item_number="輸出令別表第1の7項",
                rationale="[MOCK] Semiconductor process gas / precursor",
                requires_license=True,
            )
        return schemas.GaihiJudgeResponse(
            judgment="NOT_APPLICABLE", eccn="EAR99",
            item_number="該当無し",
            rationale="[MOCK] General chemical",
            requires_license=False,
        )

    def denied_party_check(self, req: schemas.DeniedPartyRequest) -> schemas.DeniedPartyResponse:
        if req.country in self.RESTRICTED_COUNTRIES:
            return schemas.DeniedPartyResponse(
                is_match=True, list_name="MOCK Sanctions List",
                confidence=0.95, rationale=f"[MOCK] Country {req.country} restricted",
            )
        return schemas.DeniedPartyResponse(is_match=False, confidence=0.0, rationale="[MOCK] No match")

    def post_event(self, payload: dict) -> object:
        """Generic event push — returns mock response with case_ref."""
        import uuid
        class _R:
            case_ref = f"MOCK-EVT-{uuid.uuid4().hex[:8].upper()}"
        return _R()

    def export_check(self, req: schemas.ExportCheckRequest) -> schemas.ExportCheckResponse:
        if req.destination_country in self.RESTRICTED_COUNTRIES:
            return schemas.ExportCheckResponse(
                decision="BLOCKED", check_id=f"MOCK-EXP-{req.reference}",
                message=f"Destination {req.destination_country} is restricted",
                blocking_items=[i.material_code for i in req.items],
            )
        controlled = [i.material_code for i in req.items if i.eccn and i.eccn != "EAR99"]
        if controlled:
            return schemas.ExportCheckResponse(
                decision="NEEDS_LICENSE", check_id=f"MOCK-EXP-{req.reference}",
                message=f"License required for {len(controlled)} item(s)",
                blocking_items=controlled,
            )
        return schemas.ExportCheckResponse(
            decision="PASSED", check_id=f"MOCK-EXP-{req.reference}",
            message="All items cleared",
        )

    def transaction_review(
        self, req: schemas.TransactionReviewRequest
    ) -> schemas.TransactionReviewResponse:
        dest = req.destination_country
        desc_upper = req.item_description.upper()
        if dest in self.RESTRICTED_COUNTRIES:
            judgment, approved, eccn = "REJECTED", False, None
        elif any(kw in desc_upper for kw in self.CONTROLLED_KEYWORDS):
            judgment, approved, eccn = "NEEDS_REVIEW", False, "3C001"
        elif req.eccn and req.eccn not in ("EAR99", None):
            judgment, approved, eccn = "NEEDS_REVIEW", False, req.eccn
        else:
            judgment, approved, eccn = "APPROVED", True, req.eccn or "EAR99"
        return schemas.TransactionReviewResponse(
            review_id=str(uuid.uuid4()),
            erp_transaction_id=req.erp_transaction_id,
            judgment=judgment, review_level="AUTO",
            review_completed=approved, approved=approved,
            linked_existing=False, eccn=eccn,
            message=f"[MOCK] {judgment}",
        )

    def shipment_rescreen(
        self, req: schemas.ShipmentRescreenRequest
    ) -> schemas.ShipmentRescreenResponse:
        return schemas.ShipmentRescreenResponse(
            review_id=req.review_id, erp_shipment_id=req.erp_shipment_id,
            approved=True, rescreen_changed=False,
            judgment="APPROVED", message="[MOCK] Passed",
        )

    def consume_license(self, allocation_id: str, quantity: float, delivery_no: str) -> dict:
        """IF-21: Mock license consumption — always succeeds."""
        logger.info(
            "[mock] consume_license allocation_id=%s qty=%.4f delivery=%s",
            allocation_id, quantity, delivery_no,
        )
        return {
            "allocation_id": allocation_id,
            "consumed_quantity": quantity,
            "remaining_quantity": max(0.0, 1000.0 - quantity),
            "status": "consumed",
        }

    def judge_bom(self, req: schemas.BomJudgeRequest) -> schemas.BomJudgeResponse:
        risk_factors, controlled, foreign_qty, total_qty = [], [], 0.0, 0.0
        for c in req.components:
            total_qty += c.quantity
            if c.country_of_origin and c.country_of_origin != "JP":
                foreign_qty += c.quantity
                risk_factors.append(f"L{c.level} {c.material_code}: foreign origin {c.country_of_origin}")
            if c.eccn and c.eccn != "EAR99":
                controlled.append(c.material_code)
                risk_factors.append(f"L{c.level} {c.material_code}: controlled (ECCN {c.eccn})")
        share = (foreign_qty / total_qty * 100) if total_qty else 0.0
        if controlled:
            return schemas.BomJudgeResponse(
                judgment="APPLICABLE", aggregate_eccn="3C001",
                risk_factors=risk_factors, controlled_components=controlled,
                foreign_origin_share_percent=round(share, 2),
                rationale=f"[MOCK] {len(controlled)} controlled component(s)",
            )
        if share >= 25.0:
            return schemas.BomJudgeResponse(
                judgment="NEEDS_REVIEW", aggregate_eccn=None,
                risk_factors=risk_factors, controlled_components=[],
                foreign_origin_share_percent=round(share, 2),
                rationale=f"[MOCK] Foreign origin {share:.1f}% triggers review",
            )
        return schemas.BomJudgeResponse(
            judgment="NOT_APPLICABLE", aggregate_eccn="EAR99",
            risk_factors=risk_factors, controlled_components=[],
            foreign_origin_share_percent=round(share, 2),
            rationale="[MOCK] No controlled components",
        )


# ==================================================================
# Real HTTP client (引き継ぎ書 v2.4)
# ==================================================================
class _HttpClient:
    """モジュール別URLに直接アクセスするクライアント。"""

    def __init__(self):
        headers = {
            "Content-Type": "application/json",
            "X-Organization-Id": settings.AI_TM_ORG_ID,
            "X-User-Id": settings.AI_TM_USER_ID,
        }
        timeout = settings.AI_TM_TIMEOUT_SECONDS

        self._classification = httpx.Client(
            base_url=settings.AI_TM_CLASSIFICATION_URL, headers=headers, timeout=timeout)
        self._validation = httpx.Client(
            base_url=settings.AI_TM_VALIDATION_URL, headers=headers, timeout=timeout)
        self._screening = httpx.Client(
            base_url=settings.AI_TM_SCREENING_URL, headers=headers, timeout=timeout)

    def _post(self, client: httpx.Client, path: str, body: dict) -> dict:
        try:
            r = client.post(path, json=body)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as exc:
            raise IntegrationError("AI_TradeManagement", f"{exc.response.status_code} {exc.response.text[:200]}")
        except httpx.HTTPError as exc:
            raise IntegrationError("AI_TradeManagement", str(exc))

    def _get(self, client: httpx.Client, path: str) -> dict:
        try:
            r = client.get(path)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            raise IntegrationError("AI_TradeManagement", str(exc))

    # ── 品目登録 (ai_classification) ──────────────────────────────
    def register_product(
        self, req: schemas.ProductRegisterRequest
    ) -> schemas.ProductRegisterResponse:
        try:
            data = self._post(self._classification, "/api/products", req.model_dump(exclude_none=True))
            return schemas.ProductRegisterResponse(**data)
        except IntegrationError as exc:
            # 409: 既存品目 → by-code で ID 取得して返す
            if "409" in str(exc):
                import re
                m = re.search(r"id=(\d+)", str(exc))
                existing_id = int(m.group(1)) if m else 0
                logger.info("Product %s already exists (id=%s), retrieving.", req.code, existing_id)
                try:
                    data = self._get(
                        self._classification, f"/api/products/by-code/{req.code}"
                    )
                    return schemas.ProductRegisterResponse(**data)
                except Exception:
                    return schemas.ProductRegisterResponse(
                        id=existing_id, code=req.code, name=req.name,
                        export_control_status="existing",
                    )
            raise

    def erp_sync(self, item: schemas.BomSyncItem) -> schemas.ErpSyncResponse:
        """1品目を /products/erp-sync で同期する (item_type 付き)。"""
        payload = {
            "code": item.code,
            "name": item.name,
            "hs_code": item.hs_code,
            "eccn": item.eccn,
            "item_type": item.item_type,
        }
        data = self._post(self._classification, "/products/erp-sync",
                          {k: v for k, v in payload.items() if v is not None})
        return schemas.ErpSyncResponse(**data)

    def bom_sync(
        self, items: list[schemas.BomSyncItem]
    ) -> list[schemas.ProductRegisterResponse]:
        return [self.erp_sync(it) for it in items]

    # ── 取引審査 (ai_validation) ──────────────────────────────────
    def create_transaction(
        self, req: schemas.TransactionCreateRequest
    ) -> schemas.TransactionCreateResponse:
        data = self._post(self._validation, "/api/transactions", req.model_dump(exclude_none=True))
        return schemas.TransactionCreateResponse(**data)

    def run_screening(self, tx_id: int) -> schemas.TransactionScreeningResponse:
        """Trigger re-screening.  AI_TM uses a UI-level endpoint; 303 redirect is expected."""
        try:
            r = self._validation.post(
                f"/ui/transactions/{tx_id}/run-screening",
                json={},
                follow_redirects=False,
            )
            # 303 redirect = screening triggered successfully
            triggered = r.status_code in (200, 201, 303)
        except Exception:
            triggered = False
        return schemas.TransactionScreeningResponse(
            ok=triggered,
            screening_result={"triggered": triggered},
        )

    def run_ai_judge(self, tx_id: int) -> schemas.TransactionAiJudgeResponse:
        data = self._post(self._validation, f"/api/transactions/{tx_id}/ai-judge", {})
        return schemas.TransactionAiJudgeResponse(**data)

    def get_transaction(self, tx_id: int) -> schemas.TransactionDetailResponse:
        data = self._get(self._validation, f"/api/transactions/{tx_id}")
        return schemas.TransactionDetailResponse(**data)

    def find_transaction_by_case_no(
        self, case_no: str
    ) -> schemas.TransactionDetailResponse | None:
        """Look up a transaction by case number via the search endpoint."""
        try:
            r = self._validation.get(
                "/api/transactions/search", params={"q": case_no}
            )
            if r.status_code == 200:
                items = r.json()
                if isinstance(items, list) and items:
                    # search returns minimal fields — fetch full detail
                    tx_id = items[0].get("id")
                    if tx_id:
                        detail = self._get(self._validation,
                                           f"/api/transactions/{tx_id}")
                        return schemas.TransactionDetailResponse(**detail)
        except Exception:
            pass
        return None

    # ── 制裁スクリーニング (screening) ────────────────────────────
    def screening_batch(
        self, req: schemas.ScreeningBatchRequest
    ) -> schemas.ScreeningBatchResponse:
        data = self._post(self._screening, "/api/screening/batch", req.model_dump())
        return schemas.ScreeningBatchResponse(**data)

    # ── 旧インターフェース (後方互換 / 旧ゲートウェイ経由) ────────
    def _legacy_post(self, path: str, body: dict) -> dict:
        try:
            r = httpx.post(
                f"{settings.AI_TM_BASE_URL}{path}",
                json=body,
                headers={"Authorization": f"Bearer {settings.AI_TM_API_KEY}"},
                timeout=settings.AI_TM_TIMEOUT_SECONDS,
            )
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            raise IntegrationError("AI_TradeManagement", str(exc))

    def hs_classify(self, req: schemas.HSClassifyRequest) -> schemas.HSClassifyResponse:
        return schemas.HSClassifyResponse(**self._legacy_post("/hs/classify", req.model_dump()))

    def gaihi_judge(self, req: schemas.GaihiJudgeRequest) -> schemas.GaihiJudgeResponse:
        return schemas.GaihiJudgeResponse(**self._legacy_post("/gaihi/judge", req.model_dump()))

    def denied_party_check(self, req: schemas.DeniedPartyRequest) -> schemas.DeniedPartyResponse:
        return schemas.DeniedPartyResponse(**self._legacy_post("/screening/denied-party", req.model_dump()))

    def post_event(self, payload: dict) -> object:
        """Generic event push to AI_TM events endpoint."""
        result = self._legacy_post("/events", payload)
        class _R:
            case_ref = result.get("id") or result.get("case_ref") or "REMOTE-EVT"
        return _R()

    def export_check(self, req: schemas.ExportCheckRequest) -> schemas.ExportCheckResponse:
        return schemas.ExportCheckResponse(**self._legacy_post("/export/precheck", req.model_dump()))

    def judge_bom(self, req: schemas.BomJudgeRequest) -> schemas.BomJudgeResponse:
        return schemas.BomJudgeResponse(**self._legacy_post("/gaihi/judge-bom", req.model_dump()))

    def transaction_review(
        self, req: schemas.TransactionReviewRequest
    ) -> schemas.TransactionReviewResponse:
        return schemas.TransactionReviewResponse(
            **self._legacy_post("/transaction/review", req.model_dump()))

    def shipment_rescreen(
        self, req: schemas.ShipmentRescreenRequest
    ) -> schemas.ShipmentRescreenResponse:
        return schemas.ShipmentRescreenResponse(
            **self._legacy_post("/shipment/rescreen", req.model_dump()))

    def consume_license(self, allocation_id: str, quantity: float, delivery_no: str) -> dict:
        """IF-21: POST /api/licenses/{allocation_id}/consume"""
        return self._legacy_post(
            f"/licenses/{allocation_id}/consume",
            {"quantity": quantity, "delivery_no": delivery_no},
        )


# ==================================================================
# Factory
# ==================================================================
def get_client() -> _MockClient | _HttpClient:
    if settings.AI_TM_MOCK_MODE:
        logger.debug("Using AI_TradeManagement MOCK client")
        return _MockClient()
    logger.debug("Using AI_TradeManagement HTTP client (v2.4)")
    return _HttpClient()
