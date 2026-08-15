#!/usr/bin/env python3
"""
scripts/fix_data.py
===================
2つのデータ不整合を修正する。

Fix 1: Export Declarations — declaration_number が NULL の 14件に EXPD番号を採番
Fix 2: Sales Orders (PENDING) — AI_TM に case_no で照会して最新ステータスに更新
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import SessionLocal
from app.core.numbering import next_number

# Import all models upfront so SQLAlchemy can resolve FK relationships
import app.modules.mdm.models      # noqa: F401
import app.modules.sd.models       # noqa: F401
import app.modules.gts.models      # noqa: F401
import app.modules.fi.models       # noqa: F401
import app.modules.hr.models       # noqa: F401
import app.modules.mm.models       # noqa: F401
import app.modules.pp.models       # noqa: F401

CLIENT_ID = "DEMO"


def ok(msg):  print(f"  ✅  {msg}")
def info(msg): print(f"  ℹ   {msg}")
def warn(msg): print(f"  ⚠️   {msg}")
def step(msg): print(f"\n  ▶   {msg}")


# ──────────────────────────────────────────────────────────────
# Fix 1: Export Declaration 番号採番
# ──────────────────────────────────────────────────────────────

def fix_export_declaration_numbers(db) -> None:
    from app.modules.gts.models import ExportDeclaration

    targets = db.query(ExportDeclaration).filter(
        ExportDeclaration.client_id == CLIENT_ID,
        ExportDeclaration.declaration_number == None,
    ).order_by(ExportDeclaration.id).all()

    if not targets:
        info("Fix 1: 対象なし (全件採番済み)")
        return

    info(f"Fix 1: NULL declaration_number が {len(targets)} 件 → EXPD番号を採番します")
    for decl in targets:
        num = next_number(db, CLIENT_ID, "EXPD")
        decl.declaration_number = num
        db.flush()
        ok(f"  ExportDeclaration id={decl.id}  dest={decl.destination_country}  → {num}")

    db.commit()
    ok(f"Fix 1 完了: {len(targets)} 件に EXPD番号を採番しました")


# ──────────────────────────────────────────────────────────────
# Fix 2: PENDING 受注 → AI_TM に照会してステータス更新
# ──────────────────────────────────────────────────────────────

BLOCKED_JUDGMENTS = {"BLOCKED", "REJECTED", "REQUIRES_PERMIT"}
BLOCKED_STATUSES  = {"rejected"}


def fix_pending_sales_orders(db) -> None:
    from app.modules.sd.models import SalesOrder
    from app.shared.base_models import DocStatus
    from app.integrations.ai_trade_management.client import get_client

    pending_sos = db.query(SalesOrder).filter(
        SalesOrder.client_id == CLIENT_ID,
        SalesOrder.export_check_status == "PENDING",
        SalesOrder.export_check_ref != None,
    ).order_by(SalesOrder.document_number).all()

    if not pending_sos:
        info("Fix 2: 対象なし (PENDING の受注なし)")
        return

    info(f"Fix 2: export_check_status=PENDING の受注 {len(pending_sos)} 件を AI_TM に照会します")

    client = get_client()
    passed = blocked = skipped = error_count = 0

    for so in pending_sos:
        case_no = so.export_check_ref
        try:
            tx = client.find_transaction_by_case_no(case_no)
            if tx is None:
                warn(f"  SO {so.document_number}: case_no={case_no} が AI_TM に見つかりません → PENDING 維持")
                skipped += 1
                continue

            tx_status     = (tx.status or "").lower()
            agent_judgment = tx.agent_judgment_status or tx.ai_status or ""

            if tx_status in BLOCKED_STATUSES or agent_judgment in BLOCKED_JUDGMENTS:
                so.export_check_status = "BLOCKED"
                so.export_check_message = f"AI_TM re-check: {agent_judgment or tx_status}"
                so.status = DocStatus.BLOCKED
                blocked += 1
                warn(f"  SO {so.document_number}: → BLOCKED  (judgment={agent_judgment}, status={tx.status})")
            elif agent_judgment or tx_status == "reviewed":
                # 明示的な承認 or AI判定済み → PASSED
                so.export_check_status = "PASSED"
                so.export_check_message = None
                passed += 1
                ok(f"  SO {so.document_number}: → PASSED   (judgment={agent_judgment or 'n/a'}, status={tx.status})")
            else:
                # status=draft / judgment=null → スクリーニングをトリガーして再度取得
                info(f"  SO {so.document_number}: draft状態 → スクリーニングをトリガー (case={case_no}, ai_tm_id={tx.id})")
                try:
                    client.run_screening(tx.id)
                    tx2 = client.get_transaction(tx.id)
                    j2  = tx2.agent_judgment_status or tx2.ai_status or ""
                    s2  = (tx2.status or "").lower()
                    if s2 in BLOCKED_STATUSES or j2 in BLOCKED_JUDGMENTS:
                        so.export_check_status = "BLOCKED"
                        so.export_check_message = f"AI_TM re-check after screening: {j2 or s2}"
                        so.status = DocStatus.BLOCKED
                        blocked += 1
                        warn(f"    → BLOCKED (judgment={j2}, status={tx2.status})")
                    elif j2 or s2 == "reviewed":
                        so.export_check_status = "PASSED"
                        so.export_check_message = None
                        passed += 1
                        ok(f"    → PASSED  (judgment={j2 or 'n/a'}, status={tx2.status})")
                    else:
                        skipped += 1
                        info(f"    → スクリーニング後も draft/null → PENDING 維持")
                except Exception as se:
                    skipped += 1
                    warn(f"    スクリーニングトリガー失敗: {se} → PENDING 維持")

        except Exception as exc:
            error_count += 1
            warn(f"  SO {so.document_number}: 照会エラー ({exc}) → PENDING 維持")

    db.commit()
    print(f"\n  Fix 2 完了: PASSED={passed}  BLOCKED={blocked}  PENDING維持={skipped}  エラー={error_count}")


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  ERP Data Fix Script")
    print("  Client: DEMO")
    print("═" * 60)

    db = SessionLocal()
    try:
        step("Fix 1: Export Declaration 採番")
        fix_export_declaration_numbers(db)

        step("Fix 2: PENDING 受注ステータス更新 (AI_TM 照会)")
        fix_pending_sales_orders(db)
    finally:
        db.close()

    print("\n" + "═" * 60)
    print("  ✅  修正完了")
    print("═" * 60 + "\n")


if __name__ == "__main__":
    main()
