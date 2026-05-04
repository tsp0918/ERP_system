"""AI_TradeManagement integration - request/response schemas.

Mirrors the API contract of the AI_TradeManagement service.
"""
from typing import List, Optional
from pydantic import BaseModel


# ------------------------------------------------------------------
# HS code classification
# ------------------------------------------------------------------
class HSClassifyRequest(BaseModel):
    description: str
    material_code: Optional[str] = None
    country_of_origin: Optional[str] = None


class HSClassifyResponse(BaseModel):
    hs_code: str
    confidence: float
    rationale: Optional[str] = None


# ------------------------------------------------------------------
# 該非判定 (FEFTA / EAR)
# ------------------------------------------------------------------
class GaihiJudgeRequest(BaseModel):
    material_code: str
    description: str
    hs_code: Optional[str] = None
    chemical_composition: Optional[str] = None


class GaihiJudgeResponse(BaseModel):
    judgment: str            # APPLICABLE / NOT_APPLICABLE / PENDING
    eccn: Optional[str] = None
    item_number: Optional[str] = None    # 判定項番
    rationale: Optional[str] = None
    requires_license: bool = False


# ------------------------------------------------------------------
# Denied-party / sanctions screening
# ------------------------------------------------------------------
class DeniedPartyRequest(BaseModel):
    name: str
    country: str
    address: Optional[str] = None


class DeniedPartyResponse(BaseModel):
    is_match: bool
    list_name: Optional[str] = None       # SDN / Entity List / 経産省 / etc.
    confidence: float = 0.0
    rationale: Optional[str] = None


# ------------------------------------------------------------------
# Export pre-check (per Sales Order)
# ------------------------------------------------------------------
class ExportCheckItem(BaseModel):
    material_code: str
    quantity: float
    eccn: Optional[str] = None
    hs_code: Optional[str] = None


class ExportCheckRequest(BaseModel):
    reference: str                         # SO number
    destination_country: str
    customer_code: str
    customer_name: str
    items: List[ExportCheckItem]


class ExportCheckResponse(BaseModel):
    decision: str             # PASSED / BLOCKED / NEEDS_LICENSE
    check_id: str             # AI_TM側のID (監査用)
    message: Optional[str] = None
    blocking_items: List[str] = []        # blocked material codes


# ------------------------------------------------------------------
# BOM-based judgment (Phase 2D)
# ------------------------------------------------------------------
class BomComponent(BaseModel):
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
    material_code: str
    plant_code: str
    production_version_code: Optional[str] = None
    product_hs_code: Optional[str] = None
    product_eccn: Optional[str] = None
    components: List[BomComponent]


class BomJudgeResponse(BaseModel):
    judgment: str
    aggregate_eccn: Optional[str] = None
    risk_factors: List[str] = []
    controlled_components: List[str] = []
    foreign_origin_share_percent: float = 0.0
    rationale: str


# ------------------------------------------------------------------
# Transaction review  (POST /transaction/review)
# ------------------------------------------------------------------
class TransactionReviewRequest(BaseModel):
    erp_transaction_id: str
    item_code: str
    item_name: str
    item_description: str
    hs_code: Optional[str] = None
    eccn: Optional[str] = None
    counterparty_name: str
    counterparty_country: str
    counterparty_address: Optional[str] = None
    destination_country: str
    quantity: float
    value_usd: float


class TransactionReviewResponse(BaseModel):
    review_id: str
    erp_transaction_id: str
    judgment: str           # APPROVED / REJECTED / NEEDS_REVIEW / PENDING
    review_level: str       # AUTO / MANUAL
    review_completed: bool
    approved: bool
    linked_existing: bool
    eccn: Optional[str] = None
    message: Optional[str] = None


# ------------------------------------------------------------------
# Shipment re-screening  (POST /shipment/rescreen)
# ------------------------------------------------------------------
class ShipmentRescreenRequest(BaseModel):
    review_id: str
    erp_shipment_id: str


class ShipmentRescreenResponse(BaseModel):
    review_id: str
    erp_shipment_id: str
    approved: bool
    rescreen_changed: bool
    judgment: str
    message: Optional[str] = None
