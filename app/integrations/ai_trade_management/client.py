"""HTTP client for AI_TradeManagement.

In MOCK_MODE (default for local dev), returns deterministic fake responses
so the ERP can be tested end-to-end without the real service running.
"""
import logging
from typing import Optional

import httpx

from app.core.config import settings
from app.core.exceptions import IntegrationError
from app.integrations.ai_trade_management import schemas

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Mock implementations
# ------------------------------------------------------------------
class _MockClient:
    """Returns plausible fake results. Useful for local dev / CI."""

    # Heuristic HS code lookup (semiconductor materials oriented)
    HS_HINTS = {
        "PHOTORESIST":   "3707.90",
        "RESIST":        "3707.90",
        "SLURRY":        "3824.99",
        "CMP":           "3824.99",
        "SOLVENT":       "2901.10",
        "ETCH":          "2811.19",
        "ETCHANT":       "2811.19",
        "GAS":           "2804.40",
        "SILANE":        "2853.90",
        "PRECURSOR":     "2931.90",
        "WAFER":         "3818.00",
        "POLISHING":     "3824.99",
    }

    # Materials we treat as export-controlled in the mock
    CONTROLLED_KEYWORDS = ["PRECURSOR", "GAS", "SILANE", "ETCH"]

    # Restricted destinations in the mock
    RESTRICTED_COUNTRIES = {"IR", "KP", "RU", "BY", "SY"}

    def hs_classify(self, req: schemas.HSClassifyRequest) -> schemas.HSClassifyResponse:
        desc_upper = req.description.upper()
        for keyword, hs in self.HS_HINTS.items():
            if keyword in desc_upper:
                return schemas.HSClassifyResponse(
                    hs_code=hs,
                    confidence=0.85,
                    rationale=f"[MOCK] Matched keyword '{keyword}'",
                )
        return schemas.HSClassifyResponse(
            hs_code="3824.99",
            confidence=0.30,
            rationale="[MOCK] No keyword match - default chemical preparations",
        )

    def gaihi_judge(self, req: schemas.GaihiJudgeRequest) -> schemas.GaihiJudgeResponse:
        desc_upper = req.description.upper()
        is_controlled = any(kw in desc_upper for kw in self.CONTROLLED_KEYWORDS)
        if is_controlled:
            return schemas.GaihiJudgeResponse(
                judgment="APPLICABLE",
                eccn="3C001",
                item_number="輸出令別表第1の7項",
                rationale="[MOCK] Semiconductor process gas / precursor",
                requires_license=True,
            )
        return schemas.GaihiJudgeResponse(
            judgment="NOT_APPLICABLE",
            eccn="EAR99",
            item_number="該当無し",
            rationale="[MOCK] General chemical, not on control list",
            requires_license=False,
        )

    def denied_party_check(self, req: schemas.DeniedPartyRequest) -> schemas.DeniedPartyResponse:
        # Mock: flag any party in restricted countries
        if req.country in self.RESTRICTED_COUNTRIES:
            return schemas.DeniedPartyResponse(
                is_match=True,
                list_name="MOCK Sanctions List",
                confidence=0.95,
                rationale=f"[MOCK] Country {req.country} is on restricted list",
            )
        return schemas.DeniedPartyResponse(
            is_match=False,
            confidence=0.0,
            rationale="[MOCK] No match",
        )

    def export_check(self, req: schemas.ExportCheckRequest) -> schemas.ExportCheckResponse:
        if req.destination_country in self.RESTRICTED_COUNTRIES:
            return schemas.ExportCheckResponse(
                decision="BLOCKED",
                check_id=f"MOCK-EXP-{req.reference}",
                message=f"Destination {req.destination_country} is restricted",
                blocking_items=[i.material_code for i in req.items],
            )
        # If any item is export-controlled, require license
        controlled_items = [i.material_code for i in req.items if i.eccn and i.eccn != "EAR99"]
        if controlled_items:
            return schemas.ExportCheckResponse(
                decision="NEEDS_LICENSE",
                check_id=f"MOCK-EXP-{req.reference}",
                message=f"Export license required for {len(controlled_items)} item(s)",
                blocking_items=controlled_items,
            )
        return schemas.ExportCheckResponse(
            decision="PASSED",
            check_id=f"MOCK-EXP-{req.reference}",
            message="All items cleared for export",
        )

    def transaction_review(
        self, req: schemas.TransactionReviewRequest
    ) -> schemas.TransactionReviewResponse:
        """Mock transaction review.

        - Restricted country  → REJECTED
        - Controlled keywords → NEEDS_REVIEW
        - Otherwise           → APPROVED
        """
        import uuid

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
            judgment=judgment,
            review_level="AUTO",
            review_completed=approved,
            approved=approved,
            linked_existing=False,
            eccn=eccn,
            message=f"[MOCK] {judgment}",
        )

    def shipment_rescreen(
        self, req: schemas.ShipmentRescreenRequest
    ) -> schemas.ShipmentRescreenResponse:
        """Mock shipment re-screening — always passes in mock mode."""
        return schemas.ShipmentRescreenResponse(
            review_id=req.review_id,
            erp_shipment_id=req.erp_shipment_id,
            approved=True,
            rescreen_changed=False,
            judgment="APPROVED",
            message="[MOCK] Re-screening passed. Shipment approved.",
        )

    def judge_bom(self, req: schemas.BomJudgeRequest) -> schemas.BomJudgeResponse:
        """Mock BOM judgment - same logic as the stub server."""
        risk_factors: list[str] = []
        controlled_components: list[str] = []
        foreign_qty = 0.0
        total_qty = 0.0
        for c in req.components:
            total_qty += c.quantity
            if c.country_of_origin and c.country_of_origin != "JP":
                foreign_qty += c.quantity
                risk_factors.append(
                    f"L{c.level} {c.material_code}: foreign origin {c.country_of_origin}")
            if c.eccn and c.eccn != "EAR99":
                controlled_components.append(c.material_code)
                risk_factors.append(
                    f"L{c.level} {c.material_code}: controlled (ECCN {c.eccn})")
            if c.description:
                desc_upper = c.description.upper()
                if any(kw in desc_upper for kw in self.CONTROLLED_KEYWORDS):
                    if c.material_code not in controlled_components:
                        controlled_components.append(c.material_code)
                        risk_factors.append(
                            f"L{c.level} {c.material_code}: controlled (description)")

        foreign_share = (foreign_qty / total_qty * 100) if total_qty else 0.0
        if controlled_components:
            return schemas.BomJudgeResponse(
                judgment="APPLICABLE", aggregate_eccn="3C001",
                risk_factors=risk_factors,
                controlled_components=controlled_components,
                foreign_origin_share_percent=round(foreign_share, 2),
                rationale=f"[MOCK] Inherits control from {len(controlled_components)} component(s)",
            )
        if foreign_share >= 25.0:
            return schemas.BomJudgeResponse(
                judgment="NEEDS_REVIEW", aggregate_eccn=None,
                risk_factors=risk_factors,
                controlled_components=[],
                foreign_origin_share_percent=round(foreign_share, 2),
                rationale=f"[MOCK] Foreign origin share {foreign_share:.1f}% triggers review",
            )
        return schemas.BomJudgeResponse(
            judgment="NOT_APPLICABLE", aggregate_eccn="EAR99",
            risk_factors=risk_factors,
            controlled_components=[],
            foreign_origin_share_percent=round(foreign_share, 2),
            rationale="[MOCK] No controlled components, foreign share within tolerance",
        )


# ------------------------------------------------------------------
# Real HTTP client
# ------------------------------------------------------------------
class _HttpClient:
    def __init__(self, base_url: str, api_key: str, timeout: float):
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    def _post(self, path: str, body: dict) -> dict:
        try:
            r = self._client.post(path, json=body)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as exc:
            raise IntegrationError("AI_TradeManagement", str(exc))

    def hs_classify(self, req: schemas.HSClassifyRequest) -> schemas.HSClassifyResponse:
        return schemas.HSClassifyResponse(**self._post("/hs/classify", req.model_dump()))

    def gaihi_judge(self, req: schemas.GaihiJudgeRequest) -> schemas.GaihiJudgeResponse:
        return schemas.GaihiJudgeResponse(**self._post("/gaihi/judge", req.model_dump()))

    def denied_party_check(self, req: schemas.DeniedPartyRequest) -> schemas.DeniedPartyResponse:
        return schemas.DeniedPartyResponse(**self._post("/screening/denied-party", req.model_dump()))

    def export_check(self, req: schemas.ExportCheckRequest) -> schemas.ExportCheckResponse:
        return schemas.ExportCheckResponse(**self._post("/export/precheck", req.model_dump()))

    def judge_bom(self, req: schemas.BomJudgeRequest) -> schemas.BomJudgeResponse:
        return schemas.BomJudgeResponse(**self._post("/gaihi/judge-bom", req.model_dump()))

    def transaction_review(
        self, req: schemas.TransactionReviewRequest
    ) -> schemas.TransactionReviewResponse:
        return schemas.TransactionReviewResponse(
            **self._post("/transaction/review", req.model_dump())
        )

    def shipment_rescreen(
        self, req: schemas.ShipmentRescreenRequest
    ) -> schemas.ShipmentRescreenResponse:
        return schemas.ShipmentRescreenResponse(
            **self._post("/shipment/rescreen", req.model_dump())
        )


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------
def get_client():
    """Return a mock or real client based on settings."""
    if settings.AI_TM_MOCK_MODE:
        logger.debug("Using AI_TradeManagement MOCK client")
        return _MockClient()
    return _HttpClient(
        base_url=settings.AI_TM_BASE_URL,
        api_key=settings.AI_TM_API_KEY,
        timeout=settings.AI_TM_TIMEOUT_SECONDS,
    )
