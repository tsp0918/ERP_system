"""AI_TM 品目登録スクリプト (引き継ぎ書 v2.4 対応)

エンドポイント:
  POST http://localhost:8002/api/products   — 品目登録 (1件ずつ)
  POST http://localhost:8002/products/erp-sync — BOM一括登録

item_type マッピング:
  FERT → equipment
  ROH  → component
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.mdm.models import Material
from app.modules.pp.models import Recipe
from app.modules.gts.service import GTSService

CLIENT_ID = "DEMO"
PLANT_CODE = "1000"
MATERIAL_CODES = [
    "MAT-DMIC-001",
    "MAT-DMIC-C01",
    "MAT-DMIC-C02",
    "MAT-DMIC-C03",
    "MAT-DMIC-C04",
    "MAT-DMIC-C05",
]
SEP = "=" * 70


def main() -> None:
    create_all_tables()
    db = SessionLocal()
    gts = GTSService(db)

    print(SEP)
    print(f"  AI_TM 品目登録 — DRAM混載マイコン (引き継ぎ書 v2.4)")
    print(f"  classification URL: {settings.AI_TM_CLASSIFICATION_URL}")
    print(f"  mock mode        : {settings.AI_TM_MOCK_MODE}")
    print(SEP)

    # DB から品目取得
    materials: list[Material] = (
        db.query(Material)
        .filter(
            Material.material_code.in_(MATERIAL_CODES),
            Material.client_id == CLIENT_ID,
        )
        .order_by(Material.material_code)
        .all()
    )
    mat_map = {m.material_code: m for m in materials}

    # ==================================================================
    # ① 品目ごとに POST /api/products
    # ==================================================================
    print("\n[① 品目登録 — POST /api/products]")
    registered: dict[str, int] = {}   # code → AI_TM product_id

    for code in MATERIAL_CODES:
        mat = mat_map.get(code)
        if mat is None:
            print(f"  SKIP  {code}  (DB に存在しません)")
            continue

        item_type = GTSService._MATERIAL_TYPE_MAP.get(mat.material_type, "component")
        try:
            result = gts.register_product(mat)
            db.commit()
            registered[code] = result.id
            print(
                f"  ✓ {code:<18}  item_type={item_type:<10}"
                f"  AI_TM_id={result.id:<6}  status={result.export_control_status}"
            )
        except Exception as e:
            db.rollback()
            print(f"  ✗ {code:<18}  ERROR: {e}")

    # ==================================================================
    # ② 全品目を /products/erp-sync で同期 (item_type 付き)
    # ==================================================================
    print("\n[② erp-sync — POST /products/erp-sync (item_type 付き)]")

    from app.integrations.ai_trade_management import schemas as ai_schemas

    for code in MATERIAL_CODES:
        mat = mat_map.get(code)
        if mat is None:
            continue
        item_type = GTSService._MATERIAL_TYPE_MAP.get(mat.material_type, "component")
        sync_item = ai_schemas.BomSyncItem(
            code=mat.material_code,
            name=mat.description,
            hs_code=mat.hs_code,
            eccn=mat.eccn,
            item_type=item_type,
            bom=[],
        )
        try:
            r = gts.ai.erp_sync(sync_item)
            label = "新規" if r.created else "更新"
            print(
                f"  ✓ {code:<18}  item_type={item_type:<10}"
                f"  AI_TM_id={r.id:<6}  ({label})"
            )
        except Exception as e:
            print(f"  ✗ {code:<18}  ERROR: {e}")

    # ==================================================================
    # まとめ
    # ==================================================================
    print(f"\n{SEP}")
    print("  登録結果サマリー")
    print(f"  {'code':<18}  {'material_type':<6}  {'item_type':<10}  {'AI_TM_id'}")
    print(f"  {'-'*18}  {'-'*6}  {'-'*10}  {'-'*8}")
    for code in MATERIAL_CODES:
        mat = mat_map.get(code)
        if mat is None:
            continue
        itype = GTSService._MATERIAL_TYPE_MAP.get(mat.material_type, "component")
        ai_id = registered.get(code, "-")
        print(f"  {code:<18}  {mat.material_type:<6}  {itype:<10}  {ai_id}")
    print(SEP)

    db.close()


if __name__ == "__main__":
    main()
