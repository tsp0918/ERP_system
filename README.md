# Mini Global ERP

AI_TradeManagement と連携検証するための、最小グローバルERP実装(Phase 1)。
半導体材料メーカーを想定したダミーデータ付き。

---

## クイックスタート

```bash
# 1. 依存インストール
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 環境変数 (デフォルトはSQLite + AI_TMモック)
cp .env.example .env

# 3. ダミーデータ投入 (順序重要)
python scripts/seed.py               # MDM/SD: 法人・品目・取引先・受注4パターン
python scripts/seed_pp.py            # PP: 工作センタ・レシピ・コスト計算
python scripts/seed_mm.py            # MM: 購買依頼・発注・入庫・3-wayマッチ
python scripts/seed_pp_execution.py  # PP実行: 製造指図・ロット・来歴
python scripts/seed_fi_hr.py         # FI/HR/PDF: 自動仕訳・試算表・従業員・PDF生成

# 4. サーバ起動 (5000番ポートで起動)
uvicorn app.main:app --reload --port 8888

# 5. ブラウザで http://localhost:8888/docs を開く
#    Authorize ボタンから admin@example.com / admin1234 でログイン
```

## テスト実行

```bash
# 開発用パッケージをインストール
pip install -r requirements-dev.txt

# 全68テスト実行
pytest

# カバレッジ付き
pytest --cov=app --cov-report=term
```

68テストすべてpass、業務ロジック層 (service) で86-100%、モデル/スキーマ層で100%カバー。

## ローカル開発時のポート割り当て

ERP と AI_TradeManagement を**同じローカルマシン上で同時に動かす**前提で、衝突しない番号を割り当てます。

| サービス | ポート | 起動コマンド |
|---|---|---|
| **ERP (本リポジトリ)** | **8888** | `uvicorn app.main:app --reload --port 8888` |
| **AI_TradeManagement Stub** | **5001** | `uvicorn ai_tm_stub.main:app --reload --port 5001` |
| **AI_TradeManagement (本実装)** | (任意) | tsp0918側で起動済み (8000番台) - 本番向けは `.env` で切替 |

ERP側の `.env` の `AI_TM_BASE_URL=http://localhost:5001` がスタブ前提です。
本実装の AI_TM に切り替える場合は、`.env` の `AI_TM_BASE_URL` を変更するだけで ERP のコードは無変更で動作します。

## AI_TradeManagement Stub について

`ai_tm_stub/` ディレクトリは独立した FastAPI アプリで、AI_TM 本実装が手元で起動できないとき/別ポートで動いているときに、双方向統合の動作確認に使います。

提供エンドポイント:
- `POST /hs/classify` — HSコード分類
- `POST /gaihi/judge` — 単一品目の該非判定
- `POST /gaihi/judge-bom` — **BOM全体を見た総合判定** (Phase 2D で追加)
- `POST /screening/denied-party` — 取引先スクリーニング
- `POST /export/precheck` — 受注時の輸出可否判定
- `POST /workflows/reassess-bom` — **AI_TM主導のBOM再評価ワークフロー** (ERPからGET→判定→Webhookで書き戻し)

## 統合テスト

両サーバを起動した状態で、双方向通信を端から端まで検証:

```bash
# Terminal 1
uvicorn app.main:app --port 8888 --reload

# Terminal 2
uvicorn ai_tm_stub.main:app --port 5001 --reload

# Terminal 3
# .env で AI_TM_MOCK_MODE=false に変更してから
python scripts/integration_test.py
```

VS Code なら `.vscode/launch.json` の `Both: ERP + AI_TM Stub` 複合構成を使えば、
F5 で両サーバが同時に立ち上がります。`launch.json` には:

- ERP / AI_TM Stub の起動
- 4つのシードスクリプト
- 統合テスト
- 上記の複合(ERP + AI_TM Stub 同時起動)

がすべて登録済みです。

---

## システム構成

```
┌─────────────────────────────────────────────────────────────┐
│              Mini Global ERP (FastAPI)                       │
│                                                              │
│  ┌──────┐  ┌──────┐  ┌──────────────┐                      │
│  │ MDM  │  │  SD  │  │     GTS      │ ← AI_TM 唯一の入口    │
│  │      │  │      │  │              │                      │
│  │Comp. │  │ S.O. │  │ classify     │                      │
│  │Mat.  │  │ Del. │  │ screen       │                      │
│  │ BP   │  │ Bill │  │ export check │                      │
│  └──────┘  └──────┘  └──────┬───────┘                      │
│                              │                              │
│  ┌─── shared (基底) ──────────┴─────────┐                  │
│  │ Document/Master Mixin                │                  │
│  │ BaseRepository / CRUD Router Factory │                  │
│  │ Numbering / Auth / Exceptions        │                  │
│  └──────────────────────────────────────┘                  │
│                                                              │
│           SQLite (dev) / PostgreSQL (prod)                   │
└──────────────────────────────────┬───────────────────────────┘
                                   │  HTTP (JSON)
                                   ▼
              ┌────────────────────────────────────┐
              │     AI_TradeManagement Service     │
              │  該非判定 / HS / 特許 / 輸出規制    │
              │  (MOCK_MODEで起動不要)             │
              └────────────────────────────────────┘
```

### モジュール

| Module | 役割 | 主な関心事 |
|---|---|---|
| **MDM** | マスターデータ | Company / Material / BusinessPartner |
| **SD** | 受注→出荷→請求 | SalesOrder / Delivery / BillingDocument / **Invoice PDF** |
| **MM** | 購買→入庫→仕入請求 | PurchaseRequisition / PurchaseOrder / GoodsReceipt / InvoiceReceipt (3-way match) |
| **PP** | 製造管理 (BOM+原価+実行) | Recipe / Routing / WorkCenter / ProductionVersion / CostComponentSplit / ProcessOrder / Batch / BatchGenealogy |
| **FI** | 会計 (自動仕訳+試算表) | GLAccount / AccountingDocument / AccountingLine |
| **HR** | 人事マスタ | Department / Employee / Assignment |
| **GTS** | 貿易コンプラ連携 | AI_TradeManagement への唯一の入口 |
| **shared** | 横断的関心事 | Document基底 / 汎用CRUD / 採番 / 認証 |

### 設計の3つの柱

1. **Document Principle (SAP流)**
   全業務取引を伝票として永続化。`DocumentMixin` が共通ヘッダ
   (document_number / document_date / status / reference) を提供。

2. **汎用CRUDインターフェース**
   `app/shared/base_router.py` の `create_crud_router()` で、
   どんなマスタも `prefix + create/update/response schema + model`
   を渡すだけで標準的な REST が生える。複雑なエンドポイント
   (受注作成→AI_TM呼出など) は service レイヤで個別実装。

3. **連携の局所化**
   AI_TradeManagement との通信は `GTSService` のみが行う。
   業務モジュール (MDM/SD) は GTSService を呼ぶだけ。
   `AI_TM_MOCK_MODE=true` でモック client が返答するため、
   AI_TM 本体を起動せずに ERP 単体で end-to-end テスト可能。

---

## ダミーデータ概要 (半導体材料メーカー)

### 法人 (5社)
- **1000** 日本本社 (Nihon Specialty Chemicals K.K.)
- **2000** 米国法人 / **3000** 台湾法人 / **4000** 韓国法人 / **8888** シンガポール法人

### 品目 (15件)
| 系統 | 例 | 該非判定 (mock) |
|---|---|---|
| フォトレジスト | ArF / KrF / EUV | NOT_APPLICABLE |
| CMPスラリー | Tungsten / Copper | NOT_APPLICABLE |
| エッチャント | BOE / SC-1 | BOE=APPLICABLE |
| プロセスガス・前駆体 | SiH4 / WF6 / HfCl4 | **APPLICABLE (ECCN 3C001)** |
| 原材料 | PGMEA / H2O2 / シリカ / PAGポリマー | NOT_APPLICABLE |

### 取引先 (20件)
| 種別 | 件数 | 主な役割 |
|---|---|---|
| **グループ会社** | 4社 | インターカンパニー / 移転価格 |
| **海外ディーラー** | 3社 (TW/DE/IL) | 二次代理販売 |
| **海外エンドユーザー** | 5社 (TW/KR/US/US/CN) | Tier-1 fab / IDM |
| **化学品サプライヤー** | 6社 (JP/DE/US) | 溶剤・H2O2・ガス・特殊化学品 |
| **包装ベンダ** | 1社 | クリーンルーム容器 |

### 受注4パターン (3つは請求書まで完走、1つは輸出ブロック)
| # | パターン | 顧客 | 結果 |
|---|---|---|---|
| ① | **インターカンパニー (移転価格)** | NSC Taiwan | PASSED → 出荷 → 請求 |
| ② | **海外ディーラー** | Pacific Electronic Chemicals (TW) | PASSED → 出荷 → 請求 |
| ③ | **海外エンドユーザー** | Helios Memory Systems (KR) | PASSED → 出荷 → 請求 |
| ④ | **コンプライアンス (中国向け規制品)** | Yangtze Photonics (CN) | **BLOCKED** by AI_TM |

---

## 主要APIエンドポイント

```
POST   /auth/token                       ログイン
GET    /auth/me                          自分の情報

# マスター
GET    /mdm/companies, /materials, /business-partners      (一覧/取得/作成/更新)
POST   /mdm/materials/{id}/reclassify    手動でAI_TM再判定

# 受注 → 出荷 → 請求
POST   /sd/sales-orders                  作成 (= AI_TM自動チェック)
POST   /sd/sales-orders/{id}/release     リリース
POST   /sd/sales-orders/{id}/recheck-export  輸出再評価
POST   /sd/deliveries                    出荷登録
POST   /sd/billing                       請求書発行

# AI_TM連携
POST   /gts/check-material/{id}          手動で品目再分類
POST   /gts/webhook/judgment-updated     AI_TMからのWebhook受信

# 製造管理 (PP - マスター/原価)
GET    /pp/work-centers                  作業センタ
GET    /pp/recipes                       レシピ (BOM)
POST   /pp/recipes                       レシピ作成
GET    /pp/recipes/{id}/explosion        多階層BOM展開
GET    /pp/bom-explosion?material_code=&plant_code=  品目から直接展開
GET    /pp/routings                      工程順序
GET    /pp/production-versions           Recipe×Routing 組合せ
POST   /pp/cost/rollup                   標準原価計算 (Cost Rollup)
GET    /pp/cost/splits/{material_code}   最新の原価分解取得
POST   /pp/cost/compare                  プラント間コスト比較 (移転価格)
GET    /pp/compliance/snapshot           BOMコンプラスナップショット (汎用)

# 製造管理 (PP - 実行/ロット)
GET    /pp/process-orders                製造指図一覧
POST   /pp/process-orders                製造指図作成 (Recipe自動展開)
POST   /pp/process-orders/{id}/release   指図リリース
POST   /pp/process-orders/goods-issue    投入(原料Lot消費)
POST   /pp/process-orders/operation-confirm  工程実績登録
POST   /pp/process-orders/goods-receipt  完成品入庫 (Batch+Genealogy生成)
GET    /pp/batches                       ロット一覧
POST   /pp/batches                       ロット直接作成 (期首在庫等)
GET    /pp/batches/{code}/genealogy/backward  来歴(完成品→原料)
GET    /pp/batches/{code}/genealogy/forward   来歴(原料→完成品)

# 購買管理 (MM)
GET    /mm/purchase-requisitions         購買依頼一覧
POST   /mm/purchase-requisitions         購買依頼作成
GET    /mm/purchase-orders               発注書一覧
POST   /mm/purchase-orders               発注書直接作成 (PR無し)
POST   /mm/purchase-orders/from-pr       PRから一括PO生成 (ベンダー別グルーピング)
POST   /mm/purchase-orders/{id}/release  発注リリース
GET    /mm/goods-receipts                入庫一覧
POST   /mm/goods-receipts                入庫登録 (部分受領可)
GET    /mm/invoice-receipts              仕入請求書一覧
POST   /mm/invoice-receipts              仕入請求書登録 (3-way match自動実行)

# 会計 (FI)
GET    /fi/gl-accounts                   勘定科目一覧
POST   /fi/gl-accounts/ensure-defaults   標準勘定科目セットアップ
GET    /fi/accounting-docs               仕訳一覧
POST   /fi/accounting-docs/manual        手動仕訳投入 (借方=貸方を強制)
GET    /fi/accounting-docs/trial-balance/  試算表
POST   /fi/accounting-docs/auto-post/billing/{id}        SD請求から自動仕訳
POST   /fi/accounting-docs/auto-post/goods-receipt/{id}  MM入庫から自動仕訳
POST   /fi/accounting-docs/auto-post/invoice-receipt/{id} MM仕入請求から自動仕訳

# 人事 (HR)
GET    /hr/departments                   部門一覧
POST   /hr/departments                   部門作成
GET    /hr/employees                     従業員一覧
POST   /hr/employees                     従業員作成
POST   /hr/employees/{id}/transfer       配属変更 (履歴付き)

# インボイスPDF (SD配下)
GET    /sd/billing/{id}/pdf?variant=intercompany|distributor|enduser
                                          請求書PDFを変種を選んで生成
                                          (グループ間/ディーラー/エンドユーザー)
```

---

## AI_TradeManagement 連携方法

### モック動作 (デフォルト)
`.env` で `AI_TM_MOCK_MODE=true` のまま。
`app/integrations/ai_trade_management/client.py` の `_MockClient` が、
半導体材料の典型的な分類結果を返す:
- フォトレジスト → HS 3707.90 / EAR99
- プロセスガス・前駆体 → HS 28xx / **ECCN 3C001 (規制品)**
- 中国向け = BLOCKED 判定 (規制シミュレーション)

### 実連携モード
```bash
# .env を編集
AI_TM_MOCK_MODE=false
AI_TM_BASE_URL=http://localhost:5001
AI_TM_API_KEY=<your key>
```

AI_TradeManagement 側に必要なエンドポイント:
| Path | Body |
|---|---|
| `POST /hs/classify` | `{description, material_code, country_of_origin}` |
| `POST /gaihi/judge` | `{material_code, description, hs_code, ...}` |
| `POST /screening/denied-party` | `{name, country, address}` |
| `POST /export/precheck` | `{reference, destination_country, customer_*, items[]}` |

スキーマ定義は `app/integrations/ai_trade_management/schemas.py` 参照。

---

## 既知の制約 (Phase 2A〜2D + Phase 3 完了時点)

- **MDM**: 実装済み (Company / Material / BusinessPartner)
- **SD**: 実装済み (受注→出荷→請求 + Invoice PDF 3パターン)
- **MM**: 実装済み (PR/PO/GR/IR + 3-way match)
- **PP (BOM/原価)**: 実装済み (Recipe/Routing/PV/CostRollup)
- **PP (製造実行)**: 実装済み (ProcessOrder/Batch/Genealogy)
- **FI**: 実装済み (自動仕訳 SD→AR/Revenue, MM→GR-IR/AP, 試算表)
- **HR**: 軽量実装済み (Department/Employee + 配属履歴)
- **GTS**: 実装済み (AI_TM 連携、BOM感度判定)

未実装(必要なら今後の拡張):
- **CO (管理会計)**: コストセンタ別集計、収益性分析
- **WM (倉庫)**: ストレージビン、ピッキング
- **APP (買掛金支払)**: 支払予定、銀行送金
- **AR入金**: 顧客入金消込、銀行明細マッチング
- **MRP (所要量計算)**: PR自動発行
- **多通貨換算の高度化**: 為替差損益の自動仕訳

## AI_TradeManagement 連携 - データ受け渡しの設計

ERP は **判定ロジックを一切持たない**。代わりに以下の汎用データインターフェースを提供:

| エンドポイント | 何のデータか |
|---|---|
| `GET /pp/compliance/snapshot` | 多階層BOM展開後の全構成原料の HS/ECCN/原産国/該非状態 |
| `GET /mdm/materials/{id}` | 品目単体の貿易属性 |
| `GET /sd/sales-orders/{id}` | 受注 + 顧客国 + 数量 |

外部システム (AI_TradeManagement 等) はこれらを取得し、自身の判定ロジックを適用。
判定結果は `POST /gts/webhook/judgment-updated` で ERP に書き戻し。

---

## 次のステップ候補

1. **インボイスPDF生成**: `BillingDocument` → 3パターン用テンプレートで PDF 出力
2. **MM**: 仕入先 → PO → 入庫 → 請求受領 → 3-Way match
3. **FI**: 請求/入庫からの自動仕訳、試算表
4. **AI_TradeManagement 実接続**: 現行ERP側はそのまま、相手側のスタブAPIを実装
