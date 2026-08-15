"""Seed denied party / sanctioned entity business partners.

登録する取引先:
  - BIS Entity List 掲載: Huawei, ZTE, SMIC, Hikvision, Dahua, Phytium
  - OFAC SDN 掲載: Rostec, Iran Air, Bank Melli Iran
  - OFAC 50% Rule: HiSilicon (Huawei子会社), Technopromexport (Rostec子会社)
  - 通常取引先 (クリア): Tokyo Electron Ltd., ASML Japan, Applied Materials Japan

実行方法:
  source .venv/bin/activate
  python scripts/seed_denied_parties.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# スクリーニングは Mock クライアントで実行 (AI_TM が未起動でも動作)
# 検知ロジックは _MockClient の Entity List / SDN / 50%ルール辞書を使用し、
# FLAGGED/BLOCKED 時は post_event() で AI_TM Webhook 通知を模擬する
os.environ["AI_TM_MOCK_MODE"] = "true"

from sqlalchemy.orm import Session

from app.core.database import engine, create_all_tables
from app.modules.mdm.models import BusinessPartner
from app.modules.mdm.schemas import BusinessPartnerCreate
from app.modules.mdm.service import BusinessPartnerService
from app.modules.gts.models import DeniedPartyScreeningLog
from app.modules.gts.service import GTSService

CLIENT_ID = "DEMO"
USER_EMAIL = "admin@example.com"

# ──────────────────────────────────────────────────────────────────
# 登録対象取引先
# ──────────────────────────────────────────────────────────────────
BUSINESS_PARTNERS = [
    # ── BIS Entity List ──────────────────────────────────────────
    {
        "bp_code": "BP-HUAWEI-CN",
        "name": "Huawei Technologies Co., Ltd.",
        "country": "CN",
        "roles": "CUSTOMER,VENDOR",
        "bp_type": "ORG",
        "address_line1": "Bantian, Longgang District",
        "city": "Shenzhen",
        "email": "procurement@huawei.com",
        "currency": "CNY",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-ZTE-CN",
        "name": "ZTE Corporation",
        "country": "CN",
        "roles": "CUSTOMER",
        "bp_type": "ORG",
        "address_line1": "ZTE Plaza, Keji Road South",
        "city": "Shenzhen",
        "email": "trade@zte.com.cn",
        "currency": "CNY",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-SMIC-CN",
        "name": "Semiconductor Manufacturing International Corporation",
        "country": "CN",
        "roles": "CUSTOMER",
        "bp_type": "ORG",
        "address_line1": "18 Zhangjiang Road",
        "city": "Shanghai",
        "email": "supply@smics.com",
        "currency": "CNY",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-HIKVISION-CN",
        "name": "Hangzhou Hikvision Digital Technology Co., Ltd.",
        "country": "CN",
        "roles": "CUSTOMER",
        "bp_type": "ORG",
        "address_line1": "555 Qianmo Road",
        "city": "Hangzhou",
        "email": "global@hikvision.com",
        "currency": "CNY",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-PHYTIUM-CN",
        "name": "Phytium Information Technology Co., Ltd.",
        "country": "CN",
        "roles": "CUSTOMER",
        "bp_type": "ORG",
        "address_line1": "Software Park, Tianfu New Area",
        "city": "Chengdu",
        "email": "business@phytium.com.cn",
        "currency": "CNY",
        "auto_screen": True,
    },
    # ── OFAC SDN ─────────────────────────────────────────────────
    {
        "bp_code": "BP-ROSTEC-RU",
        "name": "State Corporation Rostec",
        "country": "RU",
        "roles": "VENDOR",
        "bp_type": "ORG",
        "address_line1": "24 Usacheva Street",
        "city": "Moscow",
        "email": "info@rostec.ru",
        "currency": "RUB",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-IRANAIR-IR",
        "name": "Iran Air",
        "country": "IR",
        "roles": "CUSTOMER",
        "bp_type": "ORG",
        "address_line1": "Iran Air Building, Mehrabad Airport",
        "city": "Tehran",
        "email": "cargo@iranair.ir",
        "currency": "IRR",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-BANKMELLI-IR",
        "name": "Bank Melli Iran",
        "country": "IR",
        "roles": "VENDOR",
        "bp_type": "ORG",
        "address_line1": "Ferdowsi Avenue",
        "city": "Tehran",
        "email": "international@bankmelli.com",
        "currency": "IRR",
        "auto_screen": True,
    },
    # ── OFAC 50% Rule ─────────────────────────────────────────────
    {
        "bp_code": "BP-HISILICON-CN",
        "name": "HiSilicon Technologies Co., Ltd.",
        "country": "CN",
        "roles": "CUSTOMER",
        "bp_type": "ORG",
        "address_line1": "Bantian, Longgang District",
        "city": "Shenzhen",
        "email": "sales@hisilicon.com",
        "currency": "CNY",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-TECHNOPROM-RU",
        "name": "JSC Technopromexport",
        "country": "RU",
        "roles": "VENDOR",
        "bp_type": "ORG",
        "address_line1": "Leninsky Prospekt 49",
        "city": "Moscow",
        "email": "contract@tpe.ru",
        "currency": "RUB",
        "auto_screen": True,
    },
    # ── 通常取引先 (クリア) ────────────────────────────────────────
    {
        "bp_code": "BP-TEL-JP",
        "name": "Tokyo Electron Ltd.",
        "country": "JP",
        "roles": "VENDOR",
        "bp_type": "ORG",
        "address_line1": "Akasaka Biz Tower, 5-3-1 Akasaka",
        "city": "Tokyo",
        "email": "procurement@tel.com",
        "currency": "JPY",
        "credit_limit": 500000000,
        "payment_terms": "NET30",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-ASML-JP",
        "name": "ASML Japan Co., Ltd.",
        "country": "JP",
        "roles": "VENDOR",
        "bp_type": "ORG",
        "address_line1": "2-1-1 Otemachi",
        "city": "Tokyo",
        "email": "sales@asml.com",
        "currency": "JPY",
        "credit_limit": 1000000000,
        "payment_terms": "NET60",
        "auto_screen": True,
    },
    {
        "bp_code": "BP-AMAT-JP",
        "name": "Applied Materials Japan Inc.",
        "country": "JP",
        "roles": "VENDOR",
        "bp_type": "ORG",
        "address_line1": "Shinjuku Monolith, 2-3-1 Nishi-Shinjuku",
        "city": "Tokyo",
        "email": "japan@amat.com",
        "currency": "JPY",
        "credit_limit": 300000000,
        "payment_terms": "NET45",
        "auto_screen": True,
    },
]


def run():
    # SQLite migration: add new columns if they don't exist
    from app.core.database import create_all_tables
    import sqlite3

    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "erp.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Get existing columns in business_partners
    cur.execute("PRAGMA table_info(business_partners)")
    existing_cols = {row[1] for row in cur.fetchall()}

    new_cols = {
        "screening_status": "VARCHAR(20) DEFAULT 'UNSCREENED'",
        "denial_list": "VARCHAR(100)",
        "denial_reason": "VARCHAR(500)",
        "last_screened_at": "VARCHAR(30)",
        "parent_sanctioned_entity": "VARCHAR(255)",
        "fifty_pct_rule_triggered": "BOOLEAN DEFAULT 0",
        "ai_tm_screening_ref": "VARCHAR(100)",
    }
    for col, definition in new_cols.items():
        if col not in existing_cols:
            print(f"  ALTER TABLE business_partners ADD COLUMN {col}")
            conn.execute(f"ALTER TABLE business_partners ADD COLUMN {col} {definition}")

    conn.commit()
    conn.close()
    print("  Migration done.")

    # Create new tables (DeniedPartyScreeningLog)
    create_all_tables()

    with Session(engine) as db:
        svc = BusinessPartnerService(db)
        gts = GTSService(db)
        created_count = 0
        skipped_count = 0

        print(f"\n{'='*60}")
        print("  Denied Party Seed — Business Partner 登録 + スクリーニング")
        print(f"{'='*60}\n")

        for bp_data in BUSINESS_PARTNERS:
            bp_code = bp_data["bp_code"]

            # Check if already exists
            existing = db.query(BusinessPartner).filter(
                BusinessPartner.client_id == CLIENT_ID,
                BusinessPartner.bp_code == bp_code,
            ).first()

            if existing:
                print(f"  [SKIP] {bp_code} ({existing.name}) — already exists")
                # Re-screen existing
                gts.screen_business_partner(existing, screened_by=USER_EMAIL)
                db.flush()
                status_icon = "🚫" if existing.screening_status in ("BLOCKED", "FLAGGED") else "✅"
                print(f"         → Re-screened: {status_icon} {existing.screening_status} | {existing.denial_list or '-'}")
                skipped_count += 1
                continue

            auto_screen = bp_data.pop("auto_screen", True)
            payload = BusinessPartnerCreate(
                **{k: v for k, v in bp_data.items() if k != "bp_code"},
                bp_code=bp_code,
                auto_screen=False,  # We'll call manually to control timing
            )

            bp = svc.create(payload, CLIENT_ID, USER_EMAIL)
            db.flush()

            # Manual screening so we can log the result immediately
            gts.screen_business_partner(bp, screened_by=USER_EMAIL)
            db.flush()

            status_icon = "🚫" if bp.screening_status in ("BLOCKED", "FLAGGED") else "✅"
            fifty_tag = " [50%ルール]" if bp.fifty_pct_rule_triggered else ""
            print(
                f"  [NEW]  {bp_code} ({bp.name})\n"
                f"         → {status_icon} {bp.screening_status}{fifty_tag} | "
                f"List: {bp.denial_list or 'none'} | AI_TM: {bp.ai_tm_screening_ref or '-'}"
            )
            created_count += 1

        db.commit()

        # Summary
        logs = db.query(DeniedPartyScreeningLog).filter(
            DeniedPartyScreeningLog.client_id == CLIENT_ID
        ).all()
        critical = sum(1 for l in logs if l.match_status == "CRITICAL")
        flagged = sum(1 for l in logs if l.match_status == "match")
        possible = sum(1 for l in logs if l.match_status == "possible_match")
        fifty_pct = sum(1 for l in logs if l.fifty_pct_rule_triggered)

        print(f"\n{'='*60}")
        print(f"  完了: 新規 {created_count} 件, スキップ {skipped_count} 件")
        print(f"  スクリーニングログ合計: {len(logs)} 件")
        print(f"    🔴 CRITICAL (完全ブロック): {critical} 件")
        print(f"    🟠 match (要調査):          {flagged} 件")
        print(f"    🟡 possible_match:          {possible} 件")
        print(f"    ⚖️  50%ルール適用:           {fifty_pct} 件")
        print(f"{'='*60}\n")


if __name__ == "__main__":
    run()
