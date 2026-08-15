"""Seed: DRAM混載マイコン テストデータ + AI_TradeManagement 連携検証

登録内容:
  ① 最終製品  MAT-DMIC-001  DRAM混載マイコン 32bit ARM Cortex-M4 (4MB LPDRAM)
  ② 部品5点  MAT-DMIC-C01〜C05 (Die×2, 基板, ワイヤ, モールド)
  ③ 作業センタ  WC-CHIP-JP (半導体組立ライン)
  ④ Recipe (BOM) + Routing + Production Version
  ⑤ AI_TM 連携
       - 各品目: HS分類 + 該非判定 (classify_material)
       - 最終製品: BOM全体判定 (judge_bom)
       - 取引審査シミュ: transaction_review (台湾法人向け仮SO)
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, create_all_tables
from app.modules.mdm import schemas as mdm_schemas
from app.modules.mdm.models import BusinessPartner, Material
from app.modules.mdm.service import MaterialService
from app.modules.pp import schemas as pp_schemas
from app.modules.pp.service import (
    ProductionVersionService, RecipeService, RoutingService, WorkCenterService,
)
from app.modules.gts.service import GTSService
from app.integrations.ai_trade_management import schemas as ai_schemas

CLIENT_ID = "DEMO"
ADMIN_EMAIL = settings.INITIAL_ADMIN_EMAIL
PLANT_CODE = "1000"

SEP = "=" * 70


def _get_or_create_material(db: Session, data: dict) -> Material:
    existing = db.query(Material).filter(
        Material.material_code == data["material_code"],
        Material.client_id == CLIENT_ID,
    ).first()
    if existing:
        print(f"  (既存)  {data['material_code']}  {data['description'][:45]}")
        return existing
    svc = MaterialService(db)
    mat = svc.create(
        mdm_schemas.MaterialCreate(**data),
        client_id=CLIENT_ID,
        user_email=ADMIN_EMAIL,
    )
    db.commit()
    db.refresh(mat)
    print(f"  ✓ {mat.material_code}  {mat.description[:45]}")
    return mat


def main() -> None:
    create_all_tables()
    db: Session = SessionLocal()

    print(SEP)
    print("  DRAM混載マイコン テストデータ投入 + AI_TradeManagement 連携")
    print(SEP)

    # ==================================================================
    # ① 品目マスタ登録
    # ==================================================================
    print("\n[① 品目マスタ]")

    MATERIALS = [
        # ---- 最終製品 (FERT) ----
        {
            "material_code": "MAT-DMIC-001",
            "description": "DRAM Embedded MCU 32bit ARM Cortex-M4 120MHz 4MB LPDRAM",
            "material_type": "FERT",
            "base_unit": "PC",
            "standard_price": "8500",
            "currency": "JPY",
            "country_of_origin": "JP",
        },
        # ---- 購買部品 (ROH) ----
        {
            "material_code": "MAT-DMIC-C01",
            "description": "LPDRAM Die 4MB 16nm SDRAM (KR origin, JEDEC LPDDR4)",
            "material_type": "ROH",
            "base_unit": "PC",
            "standard_price": "1200",
            "currency": "JPY",
            "country_of_origin": "KR",   # 外国産 → BOM外国原産比率に影響
        },
        {
            "material_code": "MAT-DMIC-C02",
            "description": "ARM Cortex-M4 MCU Core Die 32bit 120MHz FPU DSP (TW fabless)",
            "material_type": "ROH",
            "base_unit": "PC",
            "standard_price": "1800",
            "currency": "JPY",
            "country_of_origin": "TW",   # 外国産 → BOM外国原産比率に影響
        },
        {
            "material_code": "MAT-DMIC-C03",
            "description": "BGA Package Substrate 7x7mm 0.5mm pitch (FC-BGA, semiconductor)",
            "material_type": "ROH",
            "base_unit": "PC",
            "standard_price": "350",
            "currency": "JPY",
            "country_of_origin": "JP",
        },
        {
            "material_code": "MAT-DMIC-C04",
            "description": "Gold Bonding Wire 25um 99.99% (thermo-compression, IC assembly)",
            "material_type": "ROH",
            "base_unit": "M",
            "standard_price": "180",
            "currency": "JPY",
            "country_of_origin": "JP",
        },
        {
            "material_code": "MAT-DMIC-C05",
            "description": "Epoxy Mold Compound Silica-filled (semiconductor encapsulant)",
            "material_type": "ROH",
            "base_unit": "G",
            "standard_price": "12",
            "currency": "JPY",
            "country_of_origin": "JP",
        },
    ]

    materials = {d["material_code"]: _get_or_create_material(db, d) for d in MATERIALS}

    # ==================================================================
    # ② AI_TM: 各品目の HS 分類 + 該非判定
    # ==================================================================
    print("\n[② AI_TM 品目分類 (HS + 該非判定)]")
    gts = GTSService(db)
    for mat in materials.values():
        gts.classify_material(mat)
        db.commit()
        db.refresh(mat)
        print(
            f"  {mat.material_code:<16}  HS={mat.hs_code or '-':<10}"
            f"  ECCN={mat.eccn or '-':<10}  判定={mat.fefta_judgment}"
        )

    # ==================================================================
    # ③ 作業センタ (半導体組立専用)
    # ==================================================================
    print("\n[③ 作業センタ]")
    wc_svc = WorkCenterService(db)
    WC_DATA = {
        "work_center_code": "WC-CHIP-JP",
        "description": "半導体組立ライン (Die Bond / Wire Bond / Mold / Test)",
        "plant_code": PLANT_CODE,
        "capacity_per_day": "20",
        "capacity_unit": "H",
        "labor_rate_per_hour": "15000",
        "machine_rate_per_hour": "45000",
        "overhead_rate_percent": "20",
        "currency": "JPY",
    }
    try:
        wc = wc_svc.create(
            pp_schemas.WorkCenterCreate(**WC_DATA),
            client_id=CLIENT_ID,
            user_email=ADMIN_EMAIL,
        )
        db.commit()
        print(f"  ✓ {wc.work_center_code}  {wc.description}")
    except Exception:
        db.rollback()
        from app.modules.pp.models import WorkCenter
        wc = db.query(WorkCenter).filter(
            WorkCenter.work_center_code == "WC-CHIP-JP",
            WorkCenter.client_id == CLIENT_ID,
        ).first()
        print(f"  (既存) {wc.work_center_code}  {wc.description}")

    # ==================================================================
    # ④ Recipe (BOM)
    #   最終製品 1PC あたりの構成
    #   KR/TW 産部品の数量合計が JP 産より多い → BOM外国原産 > 25%
    # ==================================================================
    print("\n[④ Recipe / BOM]")
    rcp_svc = RecipeService(db)
    recipe_data = pp_schemas.RecipeCreate(
        recipe_code="RCP-DMIC-001",
        material_code="MAT-DMIC-001",
        plant_code=PLANT_CODE,
        description="DRAM混載マイコン 組立レシピ (1PC/バッチ)",
        base_quantity=Decimal("1"),
        base_unit="PC",
        yield_percent=Decimal("95"),
        items=[
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-DMIC-C01",
                quantity=Decimal("1.05"),   # 5%歩留まりロス分上乗せ
                unit="PC",
            ),
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-DMIC-C02",
                quantity=Decimal("1.05"),
                unit="PC",
            ),
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-DMIC-C03",
                quantity=Decimal("1.00"),
                unit="PC",
            ),
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-DMIC-C04",
                quantity=Decimal("0.025"),  # 25mm → M換算
                unit="M",
            ),
            pp_schemas.RecipeItemCreate(
                component_material_code="MAT-DMIC-C05",
                quantity=Decimal("0.80"),   # g
                unit="G",
            ),
        ],
    )
    try:
        recipe = rcp_svc.create(recipe_data, client_id=CLIENT_ID, user_email=ADMIN_EMAIL)
        db.commit()
        print(f"  ✓ Recipe {recipe.recipe_code}  ({len(recipe.items)} コンポーネント)")
        for it in recipe.items:
            mat = materials.get(it.component_material_code)
            origin = mat.country_of_origin if mat else "?"
            print(f"      {it.component_material_code:<18}  {it.quantity:>6} {it.unit:<3}  origin={origin}")
    except Exception as e:
        db.rollback()
        from app.modules.pp.models import Recipe
        recipe = db.query(Recipe).filter(
            Recipe.recipe_code == "RCP-DMIC-001",
            Recipe.client_id == CLIENT_ID,
        ).first()
        print(f"  (既存) Recipe {recipe.recipe_code}")

    # ==================================================================
    # ⑤ Routing (工程順序)
    # ==================================================================
    print("\n[⑤ Routing]")
    rtg_svc = RoutingService(db)
    routing_data = pp_schemas.RoutingCreate(
        routing_code="RTG-DMIC-001",
        material_code="MAT-DMIC-001",
        plant_code=PLANT_CODE,
        description="DRAM混載マイコン 組立工程",
        operations=[
            pp_schemas.RoutingOperationCreate(
                operation_number=10,
                work_center_code="WC-CHIP-JP",
                description="ダイボンディング (LPDRAM + MCU Die 搭載)",
                labor_time_hours=Decimal("0.02"),
                machine_time_hours=Decimal("0.02"),
            ),
            pp_schemas.RoutingOperationCreate(
                operation_number=20,
                work_center_code="WC-CHIP-JP",
                description="ワイヤボンディング (Au wire 接合)",
                labor_time_hours=Decimal("0.05"),
                machine_time_hours=Decimal("0.05"),
            ),
            pp_schemas.RoutingOperationCreate(
                operation_number=30,
                work_center_code="WC-CHIP-JP",
                description="モールディング (エポキシ封止)",
                labor_time_hours=Decimal("0.03"),
                machine_time_hours=Decimal("0.03"),
            ),
            pp_schemas.RoutingOperationCreate(
                operation_number=40,
                work_center_code="WC-CHIP-JP",
                description="外観検査 / 電気的特性テスト",
                labor_time_hours=Decimal("0.10"),
                machine_time_hours=Decimal("0.08"),
            ),
        ],
    )
    from app.modules.pp.models import Recipe as RecipeModel, Routing as RoutingModel, ProductionVersion as PVModel
    try:
        routing = rtg_svc.create(routing_data, client_id=CLIENT_ID, user_email=ADMIN_EMAIL)
        db.commit()
        print(f"  ✓ Routing {routing.routing_code}  ({len(routing.operations)} 工程)")
        for op in routing.operations:
            print(f"      Op{op.operation_number:02d}  {op.description}")
    except Exception:
        db.rollback()
        routing = db.query(RoutingModel).filter(
            RoutingModel.routing_code == "RTG-DMIC-001",
            RoutingModel.client_id == CLIENT_ID,
        ).first()
        print(f"  (既存) Routing {routing.routing_code}")

    # fetch integer PKs needed for ProductionVersion
    recipe_row = db.query(RecipeModel).filter(
        RecipeModel.recipe_code == "RCP-DMIC-001",
        RecipeModel.client_id == CLIENT_ID,
    ).first()
    routing_row = db.query(RoutingModel).filter(
        RoutingModel.routing_code == "RTG-DMIC-001",
        RoutingModel.client_id == CLIENT_ID,
    ).first()

    # ==================================================================
    # ⑥ Production Version
    # ==================================================================
    print("\n[⑥ Production Version]")
    pv_svc = ProductionVersionService(db)
    pv_data = pp_schemas.ProductionVersionCreate(
        version_code="PV-DMIC-001",
        material_code="MAT-DMIC-001",
        plant_code=PLANT_CODE,
        recipe_id=recipe_row.id,
        routing_id=routing_row.id,
        valid_from=date.today(),
        valid_to=date(2099, 12, 31),
        is_default=True,
    )
    try:
        pv = pv_svc.create(pv_data, client_id=CLIENT_ID, user_email=ADMIN_EMAIL)
        db.commit()
        print(f"  ✓ ProdVer {pv.version_code}  recipe_id={pv.recipe_id}  routing_id={pv.routing_id}")
    except Exception:
        db.rollback()
        pv = db.query(PVModel).filter(
            PVModel.version_code == "PV-DMIC-001",
            PVModel.client_id == CLIENT_ID,
        ).first()
        print(f"  (既存) ProdVer {pv.version_code}")

    # ==================================================================
    # ⑦ AI_TM: BOM全体判定 (judge_bom)
    # ==================================================================
    print("\n[⑦ AI_TM BOM全体判定]")
    gts = GTSService(db)
    bom_result = gts.judge_bom("MAT-DMIC-001", PLANT_CODE, CLIENT_ID)

    print(f"  製品         : MAT-DMIC-001  @Plant {PLANT_CODE}")
    print(f"  BOM判定      : {bom_result.judgment}")
    print(f"  集約ECCN     : {bom_result.aggregate_eccn or '-'}")
    print(f"  外国産比率   : {bom_result.foreign_origin_share_percent:.1f}%")
    print(f"  規制コンポーネント: {bom_result.controlled_components or '(なし)'}")
    if bom_result.risk_factors:
        print("  リスク要因:")
        for rf in bom_result.risk_factors:
            print(f"    - {rf}")
    print(f"  判定根拠     : {bom_result.rationale}")

    # ==================================================================
    # ⑧ AI_TM: 取引審査シミュレーション (台湾法人向け仮受注)
    # ==================================================================
    print("\n[⑧ AI_TM 取引審査シミュレーション (台湾法人向け仮SO)]")
    final_mat = materials["MAT-DMIC-001"]
    tw_bp = db.query(BusinessPartner).filter(
        BusinessPartner.bp_code == "BP-1000002",  # NSC Taiwan
        BusinessPartner.client_id == CLIENT_ID,
    ).first()

    if tw_bp:
        review_req = ai_schemas.TransactionReviewRequest(
            erp_transaction_id="TEST-DMIC-TW-001",
            item_code=final_mat.material_code,
            item_name=final_mat.description,
            item_description=final_mat.description,
            hs_code=final_mat.hs_code,
            eccn=final_mat.eccn,
            counterparty_name=tw_bp.name,
            counterparty_country=tw_bp.country,
            counterparty_address=getattr(tw_bp, "address_line1", None),
            destination_country=tw_bp.country,
            quantity=1000.0,
            value_usd=85000.0,
        )
        review_result = gts.ai.transaction_review(review_req)
        print(f"  取引先       : {tw_bp.name} ({tw_bp.country})")
        print(f"  品目         : {final_mat.material_code}")
        print(f"  数量/金額    : 1,000 PC / USD 85,000")
        print(f"  review_id    : {review_result.review_id}")
        print(f"  審査結果     : {review_result.judgment}")
        print(f"  承認         : {'✓ APPROVED' if review_result.approved else '✗ NOT APPROVED'}")
        print(f"  審査レベル   : {review_result.review_level}")
        print(f"  ECCN(AI_TM) : {review_result.eccn or '-'}")
        print(f"  メッセージ   : {review_result.message}")
    else:
        print("  BP-1000002 (NSC Taiwan) が見つかりません。seed.py を先に実行してください。")

    # ==================================================================
    # まとめ
    # ==================================================================
    print(f"\n{SEP}")
    print("  ✓ DRAM混載マイコン テストデータ投入 + AI_TM 連携完了")
    print(SEP)
    print("\n  確認用エンドポイント:")
    print("    GET  /mdm/materials?material_type=FERT          # 最終製品一覧")
    print("    GET  /pp/recipes?material_code=MAT-DMIC-001     # BOM確認")
    print("    GET  /pp/bom-explosion?material_code=MAT-DMIC-001&plant_code=1000")
    print("    GET  /pp/compliance/snapshot?material_code=MAT-DMIC-001&plant_code=1000")
    print("    POST /gts/judge-bom?material_code=MAT-DMIC-001&plant_code=1000")

    db.close()


if __name__ == "__main__":
    main()
