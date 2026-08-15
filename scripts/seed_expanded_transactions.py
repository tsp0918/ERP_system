"""取引データ拡充シード (受注 + AI_TM取引審査リンク + 輸出申告)

仕向地:
  KR / TW / US / EU (DE/NL/FR) / JP / SEA (SG/TH/MY/PH/VN)
  高リスク: CN (YMTC=BLOCKEDを含む) / AE (Iran経由懸念) / IN / TR / RU

取引審査ステータス分布:
  APPROVED (~55%)  - 通常取引、クリア
  PENDING  (~20%)  - 最近作成、判定待ち
  REJECTED (~10%)  - AI_TM が許可しなかった取引
  BLOCKED  (~15%)  - 制裁/Entity List 顧客への取引 → ハードブロック

  source .venv/bin/activate
  python scripts/seed_expanded_transactions.py
"""
import os, sys, random, uuid
from datetime import date, timedelta, datetime
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["AI_TM_MOCK_MODE"] = "true"

from sqlalchemy.orm import Session

from app.core.database import engine, create_all_tables
from app.core.numbering import next_number
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.sd.models import SalesOrder, SalesOrderItem
from app.modules.gts.models import AITMTransactionLink, ExportDeclaration

CLIENT_ID = "DEMO"
USER = "admin@example.com"
PLANT = "1000"

random.seed(42)


def rdate(start: date, end: date) -> date:
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def rand_po():
    return f"PO-{random.randint(10000,99999)}"


# ══════════════════════════════════════════════════════════════════════
# シナリオ定義
#   customer_code, material_codes, qty_range, review_status,
#   eccn (代表品目), license_type, notes
# ══════════════════════════════════════════════════════════════════════

# (customer_code, material_code, unit_price_jpy, qty, eccn, review_status, ai_judgment, notes)
SCENARIOS = [

    # ── Korea (KR) - Normal ────────────────────────────────────────
    *[{"customer":"BP-SAMADV-KR","mat":"MAT-1000001","unit_price":95000,"qty":50,"eccn":"3B001",
       "status":"APPROVED","judgment":"APPROVED","notes":"KrF→ArF転換向け定期出荷"} for _ in range(6)],
    *[{"customer":"BP-SKSPEC-KR","mat":"MAT-2000001","unit_price":12500,"qty":800,"eccn":"EAR99",
       "status":"APPROVED","judgment":"APPROVED","notes":"W-CMP定期供給"} for _ in range(5)],
    *[{"customer":"BP-HELIOS-KR","mat":"MAT-1000002","unit_price":45000,"qty":100,"eccn":"EAR99",
       "status":"APPROVED","judgment":"APPROVED","notes":"KrF PR 定期出荷"} for _ in range(4)],
    {"customer":"BP-DBHITEK-KR","mat":"MAT-3000001","unit_price":18000,"qty":200,"eccn":"3E001",
     "status":"APPROVED","judgment":"APPROVED","notes":"BOE 7:1 出荷 KR向け"},
    {"customer":"BP-SAMADV-KR","mat":"MAT-F0001","unit_price":2800000,"qty":5,"eccn":"3B001",
     "status":"PENDING","judgment":"PENDING","notes":"EUV PR 新規見積 → AI_TM審査中"},
    {"customer":"BP-SKSPEC-KR","mat":"MAT-4000001","unit_price":380000,"qty":20,"eccn":"3C001",
     "status":"APPROVED","judgment":"APPROVED","notes":"SiH4ガス 韓国向け ライセンス確認済"},
    {"customer":"BP-DONGWON-KR","mat":"MAT-F0002","unit_price":8200,"qty":1200,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"STI CMP スラリー定期"},
    {"customer":"BP-DONGWON-KR","mat":"MAT-F0010","unit_price":16000,"qty":600,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"Cu CMP スラリー KR"},

    # ── Korea (KR) - Equipment ─────────────────────────────────────
    {"customer":"BP-SAMADV-KR","mat":"MAT-E0001","unit_price":45000000,"qty":2,"eccn":"3B001",
     "status":"APPROVED","judgment":"APPROVED","notes":"CDS-500 装置 2台 韓国向け"},
    {"customer":"BP-SKSPEC-KR","mat":"MAT-E0002","unit_price":12000000,"qty":1,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"CBU-200 装置 韓国"},

    # ── Taiwan (TW) - Normal ───────────────────────────────────────
    *[{"customer":"BP-TSMC-PUR-TW","mat":"MAT-1000001","unit_price":95000,"qty":100,"eccn":"3B001",
       "status":"APPROVED","judgment":"APPROVED","notes":"TSMC ArF PR 定期"} for _ in range(7)],
    *[{"customer":"BP-UMC-TW","mat":"MAT-2000002","unit_price":18000,"qty":500,"eccn":"EAR99",
       "status":"APPROVED","judgment":"APPROVED","notes":"Cu CMP TW定期"} for _ in range(4)],
    {"customer":"BP-GWAFER-TW","mat":"MAT-3000002","unit_price":4500,"qty":2000,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SC-1 台湾定期"},
    {"customer":"BP-PWRCHIP-TW","mat":"MAT-F0003","unit_price":180000,"qty":30,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SOC-200 TW出荷"},
    {"customer":"BP-TSMC-PUR-TW","mat":"MAT-F0001","unit_price":2800000,"qty":20,"eccn":"3B001",
     "status":"APPROVED","judgment":"APPROVED","notes":"EUV PR TW → ライセンス取得済"},
    {"customer":"BP-TSMC-PUR-TW","mat":"MAT-E0003","unit_price":850000000,"qty":1,"eccn":"3B001",
     "status":"PENDING","judgment":"PENDING","notes":"CMP ツール 台湾向け → AI_TM審査中 (高額)"},
    {"customer":"BP-MEDIATEK-TW","mat":"MAT-F0007","unit_price":95000,"qty":100,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SOG-300 台湾"},
    {"customer":"BP-GWAFER-TW","mat":"MAT-R0003","unit_price":2200,"qty":500,"eccn":"1C350",
     "status":"APPROVED","judgment":"APPROVED","notes":"HF 49% 台湾向け → 最終用途確認済"},

    # ── US (US) - Normal ───────────────────────────────────────────
    *[{"customer":"BP-NSC-US","mat":"MAT-1000001","unit_price":92000,"qty":80,"eccn":"3B001",
       "status":"APPROVED","judgment":"APPROVED","notes":"NSC US ArF PR"} for _ in range(5)],
    {"customer":"BP-SUNRISE-US","mat":"MAT-2000001","unit_price":11500,"qty":1000,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"W-CMP 米国向け"},
    {"customer":"BP-SUNRISE-US","mat":"MAT-4000001","unit_price":380000,"qty":15,"eccn":"3C001",
     "status":"APPROVED","judgment":"APPROVED","notes":"SiH4 US向け 条件付き承認"},
    {"customer":"BP-NSC-US","mat":"MAT-F0001","unit_price":2700000,"qty":10,"eccn":"3B001",
     "status":"APPROVED","judgment":"APPROVED","notes":"EUV PR US向け ライセンス確認済"},
    {"customer":"BP-NSC-US","mat":"MAT-E0004","unit_price":350000000,"qty":1,"eccn":"3B001",
     "status":"PENDING","judgment":"PENDING","notes":"WCS-200 装置 米国 → AI_TM審査中"},

    # ── Europe (DE/NL/FR) - Normal ─────────────────────────────────
    *[{"customer":"BP-EURASIA-DE","mat":"MAT-1000002","unit_price":44000,"qty":80,"eccn":"EAR99",
       "status":"APPROVED","judgment":"APPROVED","notes":"KrF PR 欧州定期"} for _ in range(3)],
    {"customer":"BP-INFINEON-DE","mat":"MAT-2000001","unit_price":13000,"qty":600,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"W-CMP Infineon"},
    {"customer":"BP-NXP-NL","mat":"MAT-F0002","unit_price":8500,"qty":800,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"STI CMP NXP"},
    {"customer":"BP-STMICRO-FR","mat":"MAT-3000001","unit_price":17500,"qty":300,"eccn":"3E001",
     "status":"APPROVED","judgment":"APPROVED","notes":"BOE STMicro 欧州 ライセンス確認"},
    {"customer":"BP-IMEC-BE","mat":"MAT-F0001","unit_price":2800000,"qty":3,"eccn":"3B001",
     "status":"APPROVED","judgment":"APPROVED","notes":"EUV PR IMEC研究用"},
    {"customer":"BP-BOSCH-DE","mat":"MAT-F0009","unit_price":9500,"qty":400,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SC-2 クリーニング Bosch"},
    {"customer":"BP-EURASIA-DE","mat":"MAT-E0001","unit_price":45000000,"qty":1,"eccn":"3B001",
     "status":"PENDING","judgment":"PENDING","notes":"CDS-500 装置 欧州 審査中"},

    # ── Japan domestic ─────────────────────────────────────────────
    *[{"customer":"BP-KIOXIA-JP","mat":"MAT-1000001","unit_price":90000,"qty":150,"eccn":"3B001",
       "status":"APPROVED","judgment":"APPROVED","notes":"Kioxia ArF PR 国内"} for _ in range(4)],
    {"customer":"BP-RENESAS-JP","mat":"MAT-2000001","unit_price":12000,"qty":700,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"W-CMP Renesas 国内"},
    {"customer":"BP-TOSHIBA-JP","mat":"MAT-F0003","unit_price":175000,"qty":60,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SOC-200 Toshiba 国内"},
    {"customer":"BP-KIOXIA-JP","mat":"MAT-F0001","unit_price":2700000,"qty":8,"eccn":"3B001",
     "status":"APPROVED","judgment":"APPROVED","notes":"EUV PR Kioxia 国内"},
    {"customer":"BP-RENESAS-JP","mat":"MAT-E0002","unit_price":12000000,"qty":2,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"CBU-200 装置 国内 2台"},

    # ── Southeast Asia (SG/TH/MY/PH/VN) ──────────────────────────
    {"customer":"BP-NSC-SG","mat":"MAT-1000002","unit_price":44500,"qty":60,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"KrF PR SG向け"},
    {"customer":"BP-UTAC-SG","mat":"MAT-2000002","unit_price":17500,"qty":300,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"Cu CMP UTAC SG"},
    {"customer":"BP-ISSI-TH","mat":"MAT-3000002","unit_price":4200,"qty":1000,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SC-1 タイ向け"},
    {"customer":"BP-PENANG-MY","mat":"MAT-F0002","unit_price":8000,"qty":500,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"STI CMP マレーシア"},
    {"customer":"BP-NEXPERIA-PH","mat":"MAT-F0008","unit_price":11500,"qty":300,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"PR剥離液 フィリピン"},
    {"customer":"BP-VIET-SEMI-VN","mat":"MAT-F0009","unit_price":9000,"qty":400,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SC-2 ベトナム"},

    # ── China (CN) - Normal (non-restricted items to non-Entity-List customers) ──
    {"customer":"BP-HUAHONG-CN","mat":"MAT-3000002","unit_price":4800,"qty":2000,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"SC-1 Hua Hong 通常品"},
    {"customer":"BP-NEXCHIP-CN","mat":"MAT-2000002","unit_price":18500,"qty":400,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"Cu CMP Nexchip 通常"},
    {"customer":"BP-HUAHONG-CN","mat":"MAT-F0008","unit_price":12000,"qty":300,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED","notes":"PR剥離液 中国向け"},

    # ── China (CN) - Needs review (controlled items) ──────────────
    {"customer":"BP-HUAHONG-CN","mat":"MAT-1000001","unit_price":93000,"qty":30,"eccn":"3B001",
     "status":"REJECTED","judgment":"REJECTED",
     "notes":"ArF PR → 中国向け 3B001 EAR §742.4 ライセンス申請却下"},
    {"customer":"BP-NEXCHIP-CN","mat":"MAT-4000001","unit_price":375000,"qty":10,"eccn":"3C001",
     "status":"REJECTED","judgment":"REJECTED",
     "notes":"SiH4ガス → 中国向け 3C001 ライセンス申請中 → 却下"},
    {"customer":"BP-NSC-TW","mat":"MAT-1000001","unit_price":95000,"qty":50,"eccn":"3B001",
     "status":"APPROVED","judgment":"APPROVED","notes":"NSC TW定期 (既存BP)"},

    # ── BLOCKED: China Entity List customer (YMTC) ────────────────
    {"customer":"BP-YMTC-CN","mat":"MAT-1000001","unit_price":95000,"qty":50,"eccn":"3B001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"ArF PR → YMTC (BIS Entity List) ハードブロック"},
    {"customer":"BP-YMTC-CN","mat":"MAT-F0001","unit_price":2800000,"qty":10,"eccn":"3B001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"EUV PR → YMTC 完全禁止"},
    {"customer":"BP-YMTC-CN","mat":"MAT-4000002","unit_price":1200000,"qty":5,"eccn":"3C001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"WF6 → YMTC BIS Entity List ブロック"},
    {"customer":"BP-YMTC-CN","mat":"MAT-E0003","unit_price":850000000,"qty":1,"eccn":"3B001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"CMP ツール → YMTC 装置輸出禁止"},

    # ── HIGH-RISK: UAE (Galaxy Horizon - Iran re-export懸念) ───────
    {"customer":"BP-GALAXYHZN-AE","mat":"MAT-1000001","unit_price":95000,"qty":20,"eccn":"3B001",
     "status":"REJECTED","judgment":"REJECTED",
     "notes":"ArF PR → Galaxy Horizon AE Iran懸念 EUC取得不可 申請却下"},
    {"customer":"BP-GALAXYHZN-AE","mat":"MAT-R0003","unit_price":2200,"qty":200,"eccn":"1C350",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"HF → AE Iran再輸出懸念 1C350 完全ブロック"},
    {"customer":"BP-GALAXYHZN-AE","mat":"MAT-F0005","unit_price":18000,"qty":100,"eccn":"1C350",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"BOE-50 1C350 AE向け UAE経由 Iran end-user疑い"},

    # ── HIGH-RISK: Russia (Angstrem - CAATSA elevated risk) ───────
    {"customer":"BP-ANGSTREM-RU","mat":"MAT-1000002","unit_price":44000,"qty":20,"eccn":"EAR99",
     "status":"REJECTED","judgment":"REJECTED",
     "notes":"KrF PR → ロシア向け CAATSA懸念 最終用途確認できず申請却下"},
    {"customer":"BP-ANGSTREM-RU","mat":"MAT-4000001","unit_price":375000,"qty":5,"eccn":"3C001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"SiH4 → ロシア 3C001 EAR license required RU ブロック"},

    # ── BLOCKED: North Korea (Pyongyang Tech) ─────────────────────
    {"customer":"BP-PYONGTEK-KP","mat":"MAT-1000001","unit_price":95000,"qty":10,"eccn":"3B001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"ArF PR → 北朝鮮 OFAC SDN 完全禁止"},
    {"customer":"BP-PYONGTEK-KP","mat":"MAT-E0001","unit_price":45000000,"qty":1,"eccn":"3B001",
     "status":"BLOCKED","judgment":"BLOCKED",
     "notes":"CDS-500 装置 → 北朝鮮 完全禁止"},

    # ── HIGH-RISK: India (dual-use concern) ───────────────────────
    {"customer":"BP-INDOTECH-IN","mat":"MAT-4000001","unit_price":370000,"qty":10,"eccn":"3C001",
     "status":"PENDING","judgment":"PENDING",
     "notes":"SiH4 → インド 最終用途申告書確認中 AI_TM審査待ち"},
    {"customer":"BP-INDOTECH-IN","mat":"MAT-R0005","unit_price":180000,"qty":5,"eccn":"1C351",
     "status":"PENDING","judgment":"PENDING",
     "notes":"TMAl前駆体 → インド 1C351 ライセンス審査中"},
    {"customer":"BP-INDOTECH-IN","mat":"MAT-F0005","unit_price":17500,"qty":50,"eccn":"1C350",
     "status":"PENDING","judgment":"PENDING",
     "notes":"BOE 1C350 → インド 最終用途疑義調査中"},

    # ── HIGH-RISK: Turkey (transit risk) ──────────────────────────
    {"customer":"BP-ANATOLTECH-TR","mat":"MAT-1000002","unit_price":44500,"qty":20,"eccn":"EAR99",
     "status":"PENDING","judgment":"PENDING",
     "notes":"KrF PR トルコ → 通過リスク調査中"},
    {"customer":"BP-ANATOLTECH-TR","mat":"MAT-R0003","unit_price":2200,"qty":100,"eccn":"1C350",
     "status":"REJECTED","judgment":"REJECTED",
     "notes":"HF → トルコ 1C350 最終用途不明 申請却下"},

    # ── ChemTech Israel - controlled item ─────────────────────────
    {"customer":"BP-CHEMTECH-IL","mat":"MAT-3000001","unit_price":17500,"qty":200,"eccn":"3E001",
     "status":"APPROVED","judgment":"APPROVED",
     "notes":"BOE イスラエル向け 3E001 US同盟国ライセンス免除"},
    {"customer":"BP-CHEMTECH-IL","mat":"MAT-4000002","unit_price":1200000,"qty":8,"eccn":"3C001",
     "status":"APPROVED","judgment":"APPROVED",
     "notes":"WF6 → イスラエル 3C001 同盟国承認済"},

    # ── Agents / Trading (代理店経由出荷) ─────────────────────────
    {"customer":"AGT-MARUBENI-JP","mat":"MAT-F0002","unit_price":8100,"qty":1000,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED",
     "notes":"丸紅経由 STI CMP 再販向け"},
    {"customer":"AGT-ITOCHU-JP","mat":"MAT-2000001","unit_price":12200,"qty":800,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED",
     "notes":"伊藤忠ケミカル経由 W-CMP"},
    {"customer":"AGT-MITSUBISHI-JP","mat":"MAT-F0009","unit_price":9200,"qty":600,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED",
     "notes":"三菱ケミカルトレーディング SC-2"},
    {"customer":"AGT-CHIMIEPLUS-FR","mat":"MAT-3000002","unit_price":4600,"qty":1500,"eccn":"EAR99",
     "status":"APPROVED","judgment":"APPROVED",
     "notes":"欧州代理店 SC-1 フランス経由"},
]

# 既存BPコードマッピング (seed_history.pyで作成済みのコード)
BP_ALIAS = {
    "BP-NSC-US":       "BP-1000001",
    "BP-NSC-TW":       "BP-1000002",
    "BP-NSC-KR":       "BP-1000003",
    "BP-NSC-SG":       "BP-1000004",
    "BP-PACIFIC-TW":   "BP-2000001",
    "BP-EURASIA-DE":   "BP-2000002",
    "BP-CHEMTECH-IL":  "BP-2000003",
    "BP-APEX-TW":      "BP-3000001",
    "BP-HELIOS-KR":    "BP-3000002",
    "BP-SUNRISE-US":   "BP-3000003",
}


def get_bp_code(alias: str) -> str:
    return BP_ALIAS.get(alias, alias)


# date range: 2025-01-01 to 2026-06-30
DATE_RANGE = (date(2025, 1, 1), date(2026, 6, 30))
RECENT_DATE = date(2026, 3, 1)   # これ以降はPENDING可


def run():
    create_all_tables()
    with Session(engine) as db:
        so_created = 0
        aitm_created = 0
        skipped_bp = 0
        stats = {"APPROVED": 0, "PENDING": 0, "REJECTED": 0, "BLOCKED": 0}

        print(f"\n{'='*65}")
        print("  取引データ拡充シード (SO + AI_TM取引審査リンク + 輸出申告)")
        print(f"{'='*65}\n")

        for i, sc in enumerate(SCENARIOS):
            raw_bp = sc["customer"]
            bp_code = get_bp_code(raw_bp)
            mat_code = sc["mat"]
            review_status = sc["status"]

            bp = db.query(BusinessPartner).filter(
                BusinessPartner.client_id == CLIENT_ID,
                BusinessPartner.bp_code == bp_code,
            ).first()
            if not bp:
                print(f"  [SKIP] BP not found: {bp_code}")
                skipped_bp += 1
                continue

            mat = db.query(Material).filter(
                Material.client_id == CLIENT_ID,
                Material.material_code == mat_code,
            ).first()
            if not mat:
                print(f"  [SKIP] Material not found: {mat_code}")
                continue

            # date assignment
            if review_status == "PENDING":
                order_date = rdate(RECENT_DATE, DATE_RANGE[1])
            elif review_status == "BLOCKED":
                order_date = rdate(date(2025, 6, 1), DATE_RANGE[1])
            else:
                order_date = rdate(*DATE_RANGE)

            req_delivery = order_date + timedelta(days=random.randint(14, 45))
            qty = Decimal(str(sc["qty"]))
            unit_price = Decimal(str(sc["unit_price"]))

            # Currency based on BP country
            cur_map = {"JP":"JPY","KR":"KRW","TW":"USD","US":"USD",
                       "DE":"EUR","NL":"EUR","FR":"EUR","BE":"EUR","GB":"GBP",
                       "CN":"USD","SG":"USD","TH":"USD","MY":"USD","PH":"USD",
                       "VN":"USD","AE":"USD","IN":"USD","TR":"USD","RU":"USD","KP":"USD"}
            currency = cur_map.get(bp.country, "USD")

            # Convert to currency
            fx = {"JPY":1,"USD":0.0067,"EUR":0.0061,"KRW":9.0,"GBP":0.0052}
            unit_price_cur = unit_price * Decimal(str(fx.get(currency, 0.0067)))
            total = qty * unit_price_cur

            # SO doc number
            so_num = next_number(db, CLIENT_ID, "SALES_ORDER")

            # export check status
            ec_status_map = {
                "APPROVED": "PASSED",
                "PENDING": "PENDING",
                "REJECTED": "BLOCKED",
                "BLOCKED": "BLOCKED",
            }
            ec_status = ec_status_map.get(review_status, "PENDING")

            so = SalesOrder(
                client_id=CLIENT_ID,
                document_number=so_num,
                document_date=order_date,
                status="OPEN" if review_status not in ("BLOCKED","REJECTED") else "BLOCKED",
                customer_code=bp_code,
                customer_po_number=rand_po(),
                requested_delivery_date=req_delivery,
                incoterms=random.choice(["CIF","FOB","DAP","EXW"]),
                payment_terms=bp.payment_terms or "NET30",
                currency=currency,
                total_amount=total,
                export_check_status=ec_status,
                export_check_ref=f"AITM-{so_num}",
                export_check_message=sc.get("notes",""),
                created_by=USER,
                updated_by=USER,
            )
            db.add(so)
            db.flush()

            # SO item
            item = SalesOrderItem(
                sales_order_id=so.id,
                item_no=10,
                material_code=mat_code,
                description=mat.description[:255] if mat else mat_code,
                quantity=qty,
                unit=mat.base_unit if mat else "KG",
                unit_price=unit_price_cur,
                net_amount=total,
                plant_code=PLANT,
                created_by=USER,
                updated_by=USER,
            )
            db.add(item)
            db.flush()

            # AI_TM Transaction Link
            review_id = str(uuid.uuid4())
            approved_at = None
            if review_status == "APPROVED":
                approved_at = datetime.combine(order_date + timedelta(days=1), datetime.min.time())

            link = AITMTransactionLink(
                client_id=CLIENT_ID,
                sales_order_id=so.id,
                review_id=review_id,
                review_status=review_status,
                review_level="AUTO" if review_status in ("APPROVED","BLOCKED") else "MANUAL",
                eccn=sc.get("eccn"),
                approved_at=approved_at,
                linked_existing=False,
                created_at=datetime.combine(order_date, datetime.min.time()),
            )
            db.add(link)
            db.flush()

            # Export Declaration (for non-BLOCKED)
            if review_status in ("APPROVED",):
                decl_num = f"DECL-{so_num}"
                license_type_map = {
                    "EAR99": "general",
                    "3B001": "individual",
                    "3C001": "individual",
                    "3E001": "individual",
                    "1C350": "individual",
                    "1C351": "individual",
                }
                ltype = license_type_map.get(sc.get("eccn","EAR99"), "general")
                decl = ExportDeclaration(
                    client_id=CLIENT_ID,
                    delivery_id=None,
                    sales_order_id=so.id,
                    ai_tm_transaction_id=review_id,
                    declaration_number=decl_num,
                    license_type=ltype,
                    license_authority="METI" if currency == "JPY" else "BIS",
                    license_issued_date=order_date + timedelta(days=3),
                    license_expiry_date=order_date + timedelta(days=365),
                    destination_country=bp.country,
                    material_code=mat_code,
                    hs_code=mat.hs_code if mat else None,
                    eccn=sc.get("eccn"),
                    quantity=qty,
                    quantity_unit=mat.base_unit if mat else "KG",
                    declared_value_usd=float(total) * 0.0067,
                    status="APPROVED",
                )
                db.add(decl)

            so_created += 1
            aitm_created += 1
            stats[review_status] = stats.get(review_status, 0) + 1

            icon = {"APPROVED":"✅","PENDING":"⏳","REJECTED":"❌","BLOCKED":"🚫"}.get(review_status,"?")
            print(f"  {icon} {so_num:12} {bp_code:30} {mat_code:15} {review_status:8}  {sc.get('notes','')[:50]}")

        db.commit()

        # Final stats
        total_so = db.query(SalesOrder).filter(SalesOrder.client_id == CLIENT_ID).count()
        total_aitm = db.query(AITMTransactionLink).filter(AITMTransactionLink.client_id == CLIENT_ID).count()
        total_decl = db.query(ExportDeclaration).filter(ExportDeclaration.client_id == CLIENT_ID).count()

        print(f"\n{'='*65}")
        print(f"  新規作成: SO {so_created}件 / AI_TMリンク {aitm_created}件")
        print(f"  判定内訳: " + " / ".join(f"{k}: {v}" for k,v in stats.items()))
        print(f"  累計: SO {total_so}件 / AI_TMリンク {total_aitm}件 / 輸出申告 {total_decl}件")
        print(f"{'='*65}\n")


if __name__ == "__main__":
    run()
