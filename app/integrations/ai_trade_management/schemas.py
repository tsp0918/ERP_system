"""AI_TradeManagement integration - request/response schemas.

引き継ぎ書 v2.4 に準拠したスキーマ定義。
旧スキーマ (HSClassifyRequest 等) はモッククライアント互換のため残す。
"""
from typing import List, Optional
from pydantic import BaseModel


# ==================================================================
# 共通
# ==================================================================
class _Base(BaseModel):
    pass


# ==================================================================
# 品目管理 (ai_classification / POST /api/products)
# ==================================================================
class ProductRegisterRequest(_Base):
    code: str                                  # ERP 品目コード (一意)
    name: str                                  # 品目名
    usage_summary: Optional[str] = None        # 工程/装置/性能/最終使用地の4要素
    item_type: Optional[str] = None            # equipment / component / software / material
    eccn: Optional[str] = None
    hs_code: Optional[str] = None
    ai_classification: Optional[str] = None    # dual_use / munitions / EAR99 / not_applicable
    export_control_status: str = "not_evaluated"


class ProductRegisterResponse(_Base):
    id: int
    code: str
    name: str
    export_control_status: str
    created_at: Optional[str] = None


class ErpSyncResponse(_Base):
    """POST /products/erp-sync のレスポンス形式。"""
    ok: bool
    id: int
    code: str
    created: bool = False


# ==================================================================
# BOM 一括同期 (ai_classification / POST /products/erp-sync)
# ==================================================================
class BomSyncComponent(_Base):
    child_code: str
    child_name: str
    quantity: float
    unit_value_usd: Optional[float] = None
    origin_country: Optional[str] = None
    supplier_name: Optional[str] = None


class BomSyncItem(_Base):
    code: str
    name: str
    eccn: Optional[str] = None
    hs_code: Optional[str] = None
    item_type: Optional[str] = None
    bom: List[BomSyncComponent] = []


# ==================================================================
# 取引審査 (ai_validation / POST /api/transactions)
# Validation module v2.4 actual schema
# ==================================================================
class TransactionItem(_Base):
    """品目明細 (_ItemIn)。"""
    item_name: str = ""
    item_description: str = ""


class TransactionUsageRequirement(_Base):
    """最終用途要件 (_UsageIn)。"""
    source: str = "ERP"
    text: str = ""


class TransactionCreateRequest(_Base):
    """POST /api/transactions リクエスト。"""
    title: str                                 # 取引タイトル (必須)
    counterparty_name: Optional[str] = None    # 取引先名
    destination_country: Optional[str] = None  # 仕向国 ISO 3166-1 alpha-2
    items: List[TransactionItem] = []          # 品目リスト
    usage_requirements: List[TransactionUsageRequirement] = []
    source_module: Optional[str] = "ERP"


class TransactionCreateResponse(_Base):
    """POST /api/transactions レスポンス。"""
    id: int
    case_no: str
    title: Optional[str] = None
    status: str                                # draft / reviewed / ...
    url: Optional[str] = None                  # AI_TM UI リンク
    screening_queued: bool = False


class TransactionScreeningResponse(_Base):
    ok: bool
    screening_result: Optional[dict] = None


class TransactionAiJudgeResponse(_Base):
    status: str = "CLEAR"                      # CLEAR / REVIEW / REQUIRES_PERMIT
    catchall_status: Optional[str] = None
    matrix_matches: List[dict] = []
    catchall_result: Optional[dict] = None


class TransactionDetailResponse(_Base):
    id: int
    case_no: str
    status: str                                        # draft / under_review / reviewed / rejected
    title: Optional[str] = None
    destination_country: Optional[str] = None
    counterparty_name: Optional[str] = None
    # AI judgment result (null until AI analysis runs)
    agent_judgment_status: Optional[str] = None        # CLEAR / REVIEW_NEEDED / BLOCKED / REQUIRES_PERMIT
    # Legacy / alternate field names kept for mock/backward compat
    ai_status: Optional[str] = None
    catchall_status: Optional[str] = None
    final_judgment: Optional[str] = None
    export_license_number: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewer_id: Optional[str] = None
    url: Optional[str] = None


# ==================================================================
# 制裁スクリーニング (screening / POST /api/screening/batch)
# ==================================================================
class ScreeningEntity(_Base):
    name: str
    country: str
    entity_type: str = "company"               # company / individual


class ScreeningBatchRequest(_Base):
    entities: List[ScreeningEntity]
    sources: List[str] = ["OFAC_SDN", "BIS_ENTITY", "METI_FUL", "EU_CONSOLIDATED"]


class ScreeningEntityResult(_Base):
    name: str
    status: str                                # no_match / possible_match / match / CRITICAL
    score: float = 0.0
    matched_list: Optional[str] = None
    matched_entity: Optional[str] = None
    denial_reason: Optional[str] = None
    fifty_pct_rule_triggered: bool = False
    parent_sanctioned_entity: Optional[str] = None
    ownership_pct: Optional[float] = None


class ScreeningBatchResponse(_Base):
    results: List[ScreeningEntityResult]


# ==================================================================
# 旧スキーマ (後方互換 / モッククライアント用)
# ==================================================================
class HSClassifyRequest(_Base):
    description: str
    material_code: Optional[str] = None
    country_of_origin: Optional[str] = None


class HSClassifyResponse(_Base):
    hs_code: str
    confidence: float = 0.0
    rationale: Optional[str] = None


class GaihiJudgeRequest(_Base):
    material_code: str
    description: str
    hs_code: Optional[str] = None
    chemical_composition: Optional[str] = None


class GaihiJudgeResponse(_Base):
    judgment: str
    eccn: Optional[str] = None
    item_number: Optional[str] = None
    rationale: Optional[str] = None
    requires_license: bool = False


class DeniedPartyRequest(_Base):
    name: str
    country: str
    address: Optional[str] = None


class DeniedPartyResponse(_Base):
    is_match: bool
    list_name: Optional[str] = None
    confidence: float = 0.0
    rationale: Optional[str] = None


class ExportCheckItem(_Base):
    material_code: str
    quantity: float
    eccn: Optional[str] = None
    hs_code: Optional[str] = None


class ExportCheckRequest(_Base):
    reference: str
    destination_country: str
    customer_code: str
    customer_name: str
    items: List[ExportCheckItem]


class ExportCheckResponse(_Base):
    decision: str
    check_id: str
    message: Optional[str] = None
    blocking_items: List[str] = []


class BomComponent(_Base):
    level: int
    material_code: str
    description: Optional[str] = None
    quantity: float
    unit: str
    hs_code: Optional[str] = None
    eccn: Optional[str] = None
    country_of_origin: Optional[str] = None
    fefta_judgment: Optional[str] = None


class BomJudgeRequest(_Base):
    material_code: str
    plant_code: str
    production_version_code: Optional[str] = None
    product_hs_code: Optional[str] = None
    product_eccn: Optional[str] = None
    components: List[BomComponent]


class BomJudgeResponse(_Base):
    judgment: str
    aggregate_eccn: Optional[str] = None
    risk_factors: List[str] = []
    controlled_components: List[str] = []
    foreign_origin_share_percent: float = 0.0
    rationale: str = ""


class TransactionReviewRequest(_Base):
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


class TransactionReviewResponse(_Base):
    review_id: str
    erp_transaction_id: str
    judgment: str
    review_level: str
    review_completed: bool
    approved: bool
    linked_existing: bool
    eccn: Optional[str] = None
    message: Optional[str] = None


class ShipmentRescreenRequest(_Base):
    review_id: str
    erp_shipment_id: str


class ShipmentRescreenResponse(_Base):
    review_id: str
    erp_shipment_id: str
    approved: bool
    rescreen_changed: bool
    judgment: str
    message: Optional[str] = None
