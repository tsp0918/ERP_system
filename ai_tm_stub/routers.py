"""AI_TradeManagement Stub - REST endpoints.

This is a self-contained FastAPI app that mimics the AI_TradeManagement
service's interface. It implements the same simple heuristics as the
ERP's `_MockClient`, but exposes them over HTTP so the ERP can be
tested end-to-end with `AI_TM_MOCK_MODE=false`.

Run separately from the ERP, on a different port:
    uvicorn ai_tm_stub.main:app --reload --port 5001

The ERP's .env should set:
    AI_TM_MOCK_MODE=false
    AI_TM_BASE_URL=http://localhost:5001
"""
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field


# ==================================================================
# Schemas (mirror app.integrations.ai_trade_management.schemas)
# ==================================================================
class HSClassifyRequest(BaseModel):
    description: str
    material_code: Optional[str] = None
    country_of_origin: Optional[str] = None


class HSClassifyResponse(BaseModel):
    hs_code: str
    confidence: float
    rationale: Optional[str] = None


class GaihiJudgeRequest(BaseModel):
    material_code: str
    description: str
    hs_code: Optional[str] = None
    chemical_composition: Optional[str] = None


class GaihiJudgeResponse(BaseModel):
    judgment: str
    eccn: Optional[str] = None
    item_number: Optional[str] = None
    rationale: Optional[str] = None
    requires_license: bool = False


class DeniedPartyRequest(BaseModel):
    name: str
    country: str
    address: Optional[str] = None


class DeniedPartyResponse(BaseModel):
    is_match: bool
    list_name: Optional[str] = None
    confidence: float = 0.0
    rationale: Optional[str] = None


class ExportCheckItem(BaseModel):
    material_code: str
    quantity: float
    eccn: Optional[str] = None
    hs_code: Optional[str] = None


class ExportCheckRequest(BaseModel):
    reference: str
    destination_country: str
    customer_code: str
    customer_name: str
    items: List[ExportCheckItem]


class ExportCheckResponse(BaseModel):
    decision: str
    check_id: str
    message: Optional[str] = None
    blocking_items: List[str] = Field(default_factory=list)


# Schemas specific to BOM-based judgment (ERP -> AI_TM batch judgment)
class BomComponentRequest(BaseModel):
    level: int
    material_code: str
    description: Optional[str] = None
    quantity: float
    unit: str
    hs_code: Optional[str] = None
    eccn: Optional[str] = None
    country_of_origin: Optional[str] = None
    fefta_judgment: Optional[str] = None


class BomJudgeRequest(BaseModel):
    """Request body produced from ERP's GET /pp/compliance/snapshot."""
    material_code: str
    plant_code: str
    production_version_code: Optional[str] = None
    product_hs_code: Optional[str] = None
    product_eccn: Optional[str] = None
    components: List[BomComponentRequest]


class BomJudgeResponse(BaseModel):
    judgment: str                          # APPLICABLE / NOT_APPLICABLE / NEEDS_REVIEW
    aggregate_eccn: Optional[str] = None
    risk_factors: List[str]                # human-readable reasons
    controlled_components: List[str]       # material codes triggering control
    foreign_origin_share_percent: float    # by quantity
    rationale: str


# ==================================================================
# Heuristics (mirror ERP's _MockClient logic)
# ==================================================================
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

CONTROLLED_KEYWORDS = ["PRECURSOR", "GAS", "SILANE", "ETCH"]
RESTRICTED_COUNTRIES = {"IR", "KP", "RU", "BY", "SY"}
SENSITIVE_DESTINATIONS = {"CN"}  # Needs license but not blocked outright


# ==================================================================
# Routers
# ==================================================================
hs_router = APIRouter(prefix="/hs", tags=["HS Classification"])
gaihi_router = APIRouter(prefix="/gaihi", tags=["FEFTA / EAR Judgment"])
screening_router = APIRouter(prefix="/screening", tags=["Party Screening"])
export_router = APIRouter(prefix="/export", tags=["Export Pre-Check"])


@hs_router.post("/classify", response_model=HSClassifyResponse)
def hs_classify(req: HSClassifyRequest):
    """Classify a material into an HS code based on its description."""
    desc_upper = req.description.upper()
    for keyword, hs in HS_HINTS.items():
        if keyword in desc_upper:
            return HSClassifyResponse(
                hs_code=hs, confidence=0.85,
                rationale=f"[STUB] Matched keyword '{keyword}'",
            )
    return HSClassifyResponse(
        hs_code="3824.99", confidence=0.30,
        rationale="[STUB] No keyword match - default chemical preparations",
    )


@gaihi_router.post("/judge", response_model=GaihiJudgeResponse)
def gaihi_judge(req: GaihiJudgeRequest):
    """FEFTA/EAR judgment for a single material."""
    desc_upper = req.description.upper()
    is_controlled = any(kw in desc_upper for kw in CONTROLLED_KEYWORDS)
    if is_controlled:
        return GaihiJudgeResponse(
            judgment="APPLICABLE", eccn="3C001",
            item_number="輸出令別表第1の7項",
            rationale="[STUB] Semiconductor process gas / precursor",
            requires_license=True,
        )
    return GaihiJudgeResponse(
        judgment="NOT_APPLICABLE", eccn="EAR99",
        item_number="該当無し",
        rationale="[STUB] General chemical, not on control list",
        requires_license=False,
    )


@gaihi_router.post("/judge-bom", response_model=BomJudgeResponse)
def gaihi_judge_bom(req: BomJudgeRequest):
    """Judge a material's regulatory status by analyzing its full BOM.

    This endpoint is the heart of the integration story:
    a single material may look 'NOT_APPLICABLE' on its own, but if its
    BOM contains controlled components or foreign-origin substances,
    the finished good may itself fall under regulation.
    """
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

        # ECCN-based control check
        if c.eccn and c.eccn != "EAR99":
            controlled_components.append(c.material_code)
            risk_factors.append(
                f"L{c.level} {c.material_code}: controlled (ECCN {c.eccn})")

        # Description heuristic for controlled keywords
        if c.description:
            desc_upper = c.description.upper()
            if any(kw in desc_upper for kw in CONTROLLED_KEYWORDS):
                if c.material_code not in controlled_components:
                    controlled_components.append(c.material_code)
                    risk_factors.append(
                        f"L{c.level} {c.material_code}: controlled (description match)")

    foreign_share = (foreign_qty / total_qty * 100) if total_qty else 0.0

    if controlled_components:
        judgment = "APPLICABLE"
        aggregate_eccn = "3C001"
        rationale = (
            f"[STUB] Finished good inherits control class from "
            f"{len(controlled_components)} controlled component(s)"
        )
    elif foreign_share >= 25.0:
        judgment = "NEEDS_REVIEW"
        aggregate_eccn = None
        rationale = (
            f"[STUB] {foreign_share:.1f}% of input quantity is foreign-origin - "
            "manual review for substantial-transformation rules recommended"
        )
    else:
        judgment = "NOT_APPLICABLE"
        aggregate_eccn = "EAR99"
        rationale = "[STUB] No controlled components, foreign origin within tolerance"

    return BomJudgeResponse(
        judgment=judgment,
        aggregate_eccn=aggregate_eccn,
        risk_factors=risk_factors,
        controlled_components=controlled_components,
        foreign_origin_share_percent=round(foreign_share, 2),
        rationale=rationale,
    )


@screening_router.post("/denied-party", response_model=DeniedPartyResponse)
def denied_party(req: DeniedPartyRequest):
    if req.country in RESTRICTED_COUNTRIES:
        return DeniedPartyResponse(
            is_match=True,
            list_name="STUB Sanctions List",
            confidence=0.95,
            rationale=f"[STUB] Country {req.country} on restricted list",
        )
    return DeniedPartyResponse(
        is_match=False, confidence=0.0, rationale="[STUB] No match",
    )


@export_router.post("/precheck", response_model=ExportCheckResponse)
def export_precheck(req: ExportCheckRequest):
    if req.destination_country in RESTRICTED_COUNTRIES:
        return ExportCheckResponse(
            decision="BLOCKED",
            check_id=f"STUB-EXP-{req.reference}",
            message=f"Destination {req.destination_country} is restricted",
            blocking_items=[i.material_code for i in req.items],
        )
    controlled = [i.material_code for i in req.items
                  if i.eccn and i.eccn != "EAR99"]
    if controlled:
        decision = ("BLOCKED" if req.destination_country in SENSITIVE_DESTINATIONS
                    else "NEEDS_LICENSE")
        return ExportCheckResponse(
            decision=decision,
            check_id=f"STUB-EXP-{req.reference}",
            message=(f"Export license required for {len(controlled)} item(s)"
                     f" to {req.destination_country}"),
            blocking_items=controlled,
        )
    return ExportCheckResponse(
        decision="PASSED",
        check_id=f"STUB-EXP-{req.reference}",
        message="All items cleared for export",
    )


# ==================================================================
# AI_TM-initiated workflow: pull BOM from ERP, judge, write back
# ==================================================================
batch_workflow_router = APIRouter(prefix="/workflows", tags=["AI_TM Workflows"])


class BomReassessRequest(BaseModel):
    """Trigger AI_TM to pull a BOM from ERP, run judgment, and write back."""
    erp_base_url: str = Field("http://localhost:5000",
        description="ERP base URL")
    erp_token: str = Field(..., description="JWT bearer token to call ERP")
    material_code: str
    plant_code: str


class BomReassessResponse(BaseModel):
    material_code: str
    snapshot_components: int
    judgment: str
    rationale: str
    erp_writeback_status: int
    started_at: datetime
    finished_at: datetime


@batch_workflow_router.post("/reassess-bom", response_model=BomReassessResponse)
def reassess_bom(req: BomReassessRequest):
    """End-to-end demo of the AI_TM-driven flow:

    1. AI_TM pulls the ERP's compliance snapshot (HTTP GET to ERP)
    2. AI_TM applies its judgment logic (calls /gaihi/judge-bom internally)
    3. AI_TM writes the result back to ERP (HTTP POST to webhook)

    This proves the bidirectional integration without requiring the ERP
    to have a separate orchestration layer.
    """
    started = datetime.utcnow()

    headers = {"Authorization": f"Bearer {req.erp_token}"}

    # Step 1: GET the BOM compliance snapshot from ERP
    with httpx.Client(timeout=10.0) as client:
        snap = client.get(
            f"{req.erp_base_url}/pp/compliance/snapshot",
            params={"material_code": req.material_code,
                   "plant_code": req.plant_code},
            headers=headers,
        )
        if snap.status_code != 200:
            raise HTTPException(
                status_code=502,
                detail=f"ERP snapshot fetch failed: {snap.status_code} {snap.text}",
            )
        snapshot = snap.json()

    # Step 2: Run the BOM judgment using our own logic
    judge_req = BomJudgeRequest(
        material_code=snapshot["material_code"],
        plant_code=snapshot["plant_code"],
        production_version_code=snapshot.get("production_version_code"),
        product_hs_code=snapshot.get("product_hs_code"),
        product_eccn=snapshot.get("product_eccn"),
        components=[BomComponentRequest(**c) for c in snapshot["components"]],
    )
    judge_resp = gaihi_judge_bom(judge_req)

    # Step 3: Write the result back to ERP via webhook
    with httpx.Client(timeout=10.0) as client:
        wb = client.post(
            f"{req.erp_base_url}/gts/webhook/judgment-updated",
            json={
                "material_code": req.material_code,
                "new_judgment": judge_resp.judgment,
                "new_eccn": judge_resp.aggregate_eccn,
                "rationale": judge_resp.rationale,
            },
            headers=headers,
        )
        writeback_status = wb.status_code

    return BomReassessResponse(
        material_code=req.material_code,
        snapshot_components=len(snapshot["components"]),
        judgment=judge_resp.judgment,
        rationale=judge_resp.rationale,
        erp_writeback_status=writeback_status,
        started_at=started,
        finished_at=datetime.utcnow(),
    )


def get_all_routers():
    return [hs_router, gaihi_router, screening_router, export_router,
            batch_workflow_router]
