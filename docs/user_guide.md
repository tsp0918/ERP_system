# Mini Global ERP — ユーザーガイド兼 運用設計指針

**対象読者:** ERP・AI Trade Management・CRM の各担当チーム  
**文書バージョン:** 1.0  
**発行日:** 2026-08-14  
**ERP Version:** 0.1.0

---

## 目次

1. [システム全体像](#1-システム全体像)
2. [ERPモジュール詳細](#2-erpモジュール詳細)
   - [MDM — マスタデータ管理](#21-mdm--マスタデータ管理)
   - [SD — 販売管理](#22-sd--販売管理)
   - [MM — 購買・在庫管理](#23-mm--購買在庫管理)
   - [PP — 生産管理](#24-pp--生産管理)
   - [QM — 品質管理](#25-qm--品質管理)
   - [FI — 財務会計](#26-fi--財務会計)
   - [CO — 管理会計](#27-co--管理会計)
   - [HR — 人事管理](#28-hr--人事管理)
   - [GTS — 貿易コンプライアンス](#29-gts--貿易コンプライアンス)
3. [AI Trade Management 連携仕様](#3-ai-trade-management-連携仕様)
4. [CRM 連携設計指針](#4-crm-連携設計指針)
5. [3システム間の業務フロー](#5-3システム間の業務フロー)
6. [業務分担マトリクス](#6-業務分担マトリクス)
7. [運用上の注意事項](#7-運用上の注意事項)
8. [付録](#8-付録)

---

## 1. システム全体像

### 1.1 このERPが担う領域

Mini Global ERP は、**半導体製造材料・装置の輸出取引**に特化した業務管理システムです。取引先の制裁スクリーニングから、受注・製造・出荷・請求・財務仕訳までの一連の業務プロセスを管理します。

```
┌───────────────────────────────────────────────────────────────────┐
│                         運用全体像                                │
│                                                                   │
│  ┌──────────┐    商談・与信    ┌──────────────┐                  │
│  │   CRM    │ ─────────────→  │              │                  │
│  │          │ ←─────────────  │   Mini       │   品目登録       │
│  │ 顧客管理 │   受注情報同期  │   Global     │ ─────────────→  │
│  │ 商談管理 │                 │   ERP        │                  │
│  │ 営業支援 │                 │              │ ←─────────────  │
│  └──────────┘                 │ （本システム） │   判定結果返却   │
│                               │              │                  │
│                               └──────┬───────┘                  │
│                                      │                          │
│                          制裁/輸出/   │                          │
│                          品目分類依頼 │                          │
│                                      ↓                          │
│                         ┌────────────────────┐                 │
│                         │  AI Trade          │                 │
│                         │  Management        │                 │
│                         │                    │                 │
│                         │ ・取引先制裁審査    │                 │
│                         │ ・輸出取引審査      │                 │
│                         │ ・品目HS/ECCN分類  │                 │
│                         │ ・輸出ライセンス    │                 │
│                         └────────────────────┘                 │
└───────────────────────────────────────────────────────────────────┘
```

### 1.2 技術スペック

| 項目 | 内容 |
|---|---|
| フレームワーク | FastAPI (Python) |
| データベース | SQLite（本番移行時: PostgreSQL推奨） |
| 認証方式 | OAuth2 Password Grant + JWT Bearer（有効期限60分） |
| API仕様 | OpenAPI 3.1 / Swagger UI: `http://localhost:8888/docs` |
| テナント管理 | `client_id` カラムによる論理分離（現在: `DEMO`） |
| 稼働URL | `http://localhost:8888` |
| 管理UI | `http://localhost:8888/ui` |
| AI_TM接続モード | 現在 **MOCKモード**（`AI_TM_MOCK_MODE=true`） |

### 1.3 現在のデータ状況

| データ | 件数 | 備考 |
|---|---|---|
| BusinessPartner（取引先） | 111社 | CLEARED:94、BLOCKED:13、FLAGGED:4 |
| Material（品目） | 72品目 | ROH:27、FERT:26、HALB:13、HAWA:6 |
| SalesOrder（受注） | 258件 | 輸出審査リンク99件付き |
| Delivery（出荷） | 110件 | |
| BillingDocument（請求） | 110件 | |
| ExportDeclaration（輸出申告） | 256件 | |
| DeniedPartyScreeningLog | 248件 | 制裁スクリーニング監査ログ |

---

## 2. ERPモジュール詳細

### 2.1 MDM — マスタデータ管理

**役割:** ERP全体の基盤マスタを管理する。他すべてのモジュールが参照する「正のデータ」を保持する。

#### 管理対象

| エンティティ | 説明 | キー |
|---|---|---|
| BusinessPartner | 取引先（顧客・仕入先・従業員を統合） | `bp_code`（BP-XXXXXXX） |
| Material | 品目（原材料・半製品・完成品・商品） | `material_code`（MAT-XXXXXXX） |
| MaterialPlant | 品目×プラントの調達・MRPパラメータ | `material_code` + `plant_code` |
| Company | 会社コードマスタ | `company_code` |

#### BusinessPartner の特徴

- SAP S/4HANA の BP統合モデルに準拠。顧客・仕入先・従業員を**1レコードで管理**
- `roles` フィールドにカンマ区切りで複数ロールを付与可能（例: `CUSTOMER,VENDOR`）
- 登録時に `auto_screen=true`（デフォルト）を指定すると、AI_TM経由で**自動制裁スクリーニング**が実行される
- `is_denied_party=true` の取引先は**受注登録がブロック**される（SD側でチェック）

#### Material の特徴

- `material_type`: `FERT`（完成品）/ `HALB`（半製品）/ `ROH`（原材料）/ `HAWA`（商品）
- 登録時に `auto_classify=true`（デフォルト）で AI_TM による **HSコード分類・ECCN・外為法判定**が自動実行される
- `eccn`・`hs_code`・`fefta_judgment`・`country_of_origin` が輸出コンプライアンスの核心フィールド

#### 主要API

```
GET    /mdm/business-partners          取引先一覧
POST   /mdm/business-partners          取引先登録（auto_screen=true で自動スクリーニング）
PUT    /mdm/business-partners/{id}     取引先更新
GET    /mdm/materials                  品目一覧
POST   /mdm/materials                  品目登録（auto_classify=true でHS/ECCN分類）
POST   /mdm/materials/{id}/reclassify  品目の再分類（AI_TM再呼び出し）
POST   /import/business-partners       CSV一括インポート
POST   /import/materials               CSV一括インポート
```

---

### 2.2 SD — 販売管理

**役割:** 受注から請求までの販売プロセスを管理する。輸出コンプライアンスチェックと密接に連携する。

#### ドキュメントチェーン

```
SalesOrder（受注）
    → [輸出審査] AI_TM 自動チェック
    → Delivery（出荷指示）
        → [出荷前再スクリーニング] AI_TM
    → BillingDocument（請求書）
        → Invoice PDF発行
    → ExportDeclaration（輸出申告）
```

#### SalesOrder の動作

1. `POST /sd/sales-orders` で受注登録
2. 登録直後に制裁スクリーニング済みの取引先かチェック（`is_denied_party=true` は即ブロック）
3. `skip_export_check=false`（デフォルト）の場合、AI_TM の取引審査（`create_transaction` → `run_screening` → `run_ai_judge`）が自動実行される
4. 審査結果が `export_check_status` フィールドに反映される: `PASSED` / `BLOCKED` / `PENDING`
5. 受注リリース（`POST /sd/sales-orders/{id}/release`）で出荷処理へ進める

#### ステータス遷移

```
OPEN → RELEASED → COMPLETED
              ↓
           BLOCKED（輸出審査不可）
              ↓
          CANCELLED
```

#### 主要API

```
POST   /sd/sales-orders                受注登録（輸出審査自動実行）
POST   /sd/sales-orders/{id}/release   受注リリース
POST   /sd/sales-orders/{id}/recheck-export  輸出審査再チェック
POST   /sd/deliveries                  出荷作成
GET    /sd/billing/{id}/pdf            請求書PDFダウンロード
GET    /sd/forecasts/summary?year=YYYY 月次フォーキャスト vs 実績サマリー
```

---

### 2.3 MM — 購買・在庫管理

**役割:** 仕入先からの調達（購買依頼→発注→入庫→請求照合）と在庫管理を担当する。

#### プロセスフロー

```
PurchaseRequisition（購買依頼）
    → PurchaseOrder（発注書）
        → GoodsReceipt（入庫）
            → [FI自動仕訳] 在庫計上
        → InvoiceReceipt（請求書照合）
            → [FI自動仕訳] 買掛金計上
```

#### 在庫管理の特徴

- `StockBalance`: プラント×品目×保管場所での在庫残高管理
- `Batch`: ロット単位の原産国・製造日・数量管理（トレーサビリティ対応）
- `GET /mm/material-availability`: MRP形式での在庫/供給/需要/コストの一覧表示
- `GET /mm/batches/{code}/genealogy`: 上位・下位ロットの系譜トレース

#### 購買情報レコード

- `PurchasingInfoRecord`: 仕入先×品目ごとの単価・リードタイム・最低発注数量を管理
- `SourceList`: 認定仕入先リスト（どの仕入先から調達するか）

#### 主要API

```
POST   /mm/purchase-orders             発注書作成
POST   /mm/purchase-orders/from-pr     購買依頼からの自動発注
POST   /mm/goods-receipts              入庫登録（FI自動仕訳トリガー）
POST   /mm/invoice-receipts            請求書照合（FI自動仕訳トリガー）
GET    /mm/material-availability       在庫可用性（MRPビュー）
GET    /mm/batches/{code}/genealogy    ロット系譜トレース
```

---

### 2.4 PP — 生産管理

**役割:** 製造指図（プロセスオーダー）の管理、BOM（レシピ）・工順・ワークセンターの管理、原価計算を担当する。

#### 管理対象

| エンティティ | 説明 |
|---|---|
| Recipe（レシピ/BOM） | 製品の部品構成（材料・数量） |
| Routing（工順） | 製造工程の順序と標準時間 |
| WorkCenter（ワークセンター） | 生産設備・作業場 |
| ProductionVersion | レシピ+工順の組み合わせ（製造バリアント） |
| ProcessOrder（製造指図） | 実際の製造指示書 |

#### 製造フロー

```
Recipe（レシピ）+ Routing（工順）
    → ProductionVersion（製造バリアント）
        → ProcessOrder（製造指図）作成
            → Release（リリース）
                → GoodsIssue（材料払出）
                → OperationConfirm（作業確認）
                → ProductionGoodsReceipt（製品入庫）
                    → QM検査ロット自動生成
```

#### コスト計算

- `POST /pp/cost/rollup`: BOMを展開して材料費・加工費・間接費を積み上げ計算
- `POST /pp/cost-rollup/sync-standard-cost`: 計算結果を品目マスタの `standard_price` に反映
- `GET /pp/compliance/snapshot?material_code=X&plant_code=Y`: BOM展開 + コンプライアンス情報（ECCN・HSコード・原産国）のスナップショット取得

#### 主要API

```
GET    /pp/recipes/{id}/explosion      BOM展開（多段階）
POST   /pp/process-orders              製造指図作成
GET    /pp/schedule                    製造スケジュール（部品所要量込み）
POST   /pp/cost/rollup                 原価積み上げ計算
GET    /pp/compliance/snapshot         コンプライアンススナップショット（material_code + plant_code 必須）
```

---

### 2.5 QM — 品質管理

**役割:** 製品・原材料の検査管理、検査証明書（CoA）の発行、品質不良の管理を担当する。

#### プロセスフロー

```
製品入庫（PP.GoodsReceipt）
    → InspectionLot（検査ロット）作成
        → InspectionPlan（検査計画）に従い InspectionResult 記録
            → 自動合否判定（judge）
                ├── PASSED → CoA（品質証明書）発行
                └── FAILED → QualityNotification（品質通知）起票
```

#### 主要API

```
POST   /qm/lots/{id}/judge     自動合否判定（検査結果を集計して判定）
POST   /qm/certificates        CoA発行（合格ロットのみ）
POST   /qm/notifications       品質通知（不良起票）
GET    /qm/specs/current/{material_code}  品目の最新検査規格
```

---

### 2.6 FI — 財務会計

**役割:** 入出金の仕訳計上、GLアカウント管理、試算表の作成を担当する。業務トランザクション（入庫・請求）から自動仕訳を生成する。

#### 自動仕訳トリガー

| トリガー | 仕訳内容 |
|---|---|
| GoodsReceipt（入庫） | 在庫 Dr / 買掛金 Cr |
| InvoiceReceipt（請求照合） | 買掛金 Dr / 未払金 Cr |
| BillingDocument（売上請求） | 売掛金 Dr / 売上 Cr |

#### 主要API

```
POST   /fi/accounting-docs/auto-post/billing/{id}        請求から自動仕訳
POST   /fi/accounting-docs/auto-post/goods-receipt/{id}  入庫から自動仕訳
POST   /fi/accounting-docs/manual                        手動仕訳
GET    /fi/accounting-docs/trial-balance/                試算表
```

---

### 2.7 CO — 管理会計

**役割:** コストセンター別の予算管理、設備コストレート計算、製品原価の管理会計的分析を担当する。

#### 主な機能

- `CostCenter`: 部門別の予算・実績管理
- `Asset`（設備）: 機械時間コストレート（machine_rate）の計算と製造工程への反映
- De Minimis 計算: `GET /co/cost-estimates/{material_code}/{fiscal_year}/de-minimis` で米国EAR規制のDe Minimis比率を算出
- COレート → PPワークセンターへの反映: `POST /co/sync/work-center-rates/{fiscal_year}`

---

### 2.8 HR — 人事管理

**役割:** 社員・部門マスタの管理。コストセンターとの紐付けにより CO モジュールの工数配賦計算に活用される。

```
GET    /hr/employees            社員一覧
POST   /hr/employees/{id}/transfer  部門異動
```

---

### 2.9 GTS — 貿易コンプライアンス

**役割:** ERPの全コンプライアンス機能の中核。AI Trade Managementとの**唯一の接点**であり、他のすべてのモジュールはGTSServiceを経由してAI_TMを呼び出す。

#### GTS が管理するデータ

| データ | 説明 |
|---|---|
| AITMTransactionLink | 受注（SalesOrder）↔ AI_TM 取引審査の紐付け |
| AITMShipmentLink | 出荷（Delivery）↔ AI_TM 出荷前再スクリーニングの紐付け |
| ExportDeclaration | 輸出申告書・輸出許可証の管理 |
| MaterialOriginChangeLog | 原材料の原産国切り替えイベントログ |
| LotDeMinimusAssessment | ロット別 De Minimis 評価（米国原産品含有率） |
| DeniedPartyScreeningLog | 制裁スクリーニング全履歴（監査ログ） |

#### Webhook受信

AI_TM → ERP方向の通知を受け取るエンドポイントが実装済み:

```
POST /gts/webhook/judgment-updated
  - 受信内容: material_code / new_judgment / new_eccn / rationale
  - 動作: 品目のECCN/判定を更新、APPROVED時に保留受注を自動解除、REJECTED時に受注キャンセル
  - 認証: Bearer {AI_TM_API_KEY} ヘッダー（ERP JWTとは別）
```

#### 主要API

```
GET    /gts/screening/log                    制裁スクリーニング監査ログ
POST   /gts/screening/{bp_code}/rescreen     単一BP再スクリーニング
POST   /gts/screening/rescreen-all           全BP一括再スクリーニング
GET    /gts/export-declarations              輸出申告一覧
POST   /gts/export-declarations/{id}/submit  輸出申告提出
GET    /gts/deminimis                        De Minimis評価一覧
GET    /gts/origin-change-log                原産国変更ログ
POST   /gts/judge-bom                        BOM全体の輸出規制判定
```

---

## 3. AI Trade Management 連携仕様

### 3.1 接続アーキテクチャ

AI_TM はマイクロサービス構成（モジュール別URL）。ERPは `GTSService` を通じて各モジュールと通信する。

```
ERP（GTSService）
    ├── 品目分類    → AI_TM Classification  (localhost:8002)
    ├── 取引審査    → AI_TM Validation      (localhost:8011)
    ├── 制裁審査    → AI_TM Screening       (localhost:8005)
    ├── R&D評価     → AI_TM R&D Risk        (localhost:8003)
    └── ライセンス  → AI_TM License         (localhost:8012)

AI_TM → ERP（Webhook）
    └── POST /gts/webhook/judgment-updated
```

**現在の動作モード:** `AI_TM_MOCK_MODE=true`（全AI_TM呼び出しをローカルモックで代替）

### 3.2 連携トリガー一覧

| トリガー | ERP側の操作 | 呼び出すAI_TM機能 | 結果の格納先 |
|---|---|---|---|
| 品目登録 | `POST /mdm/materials`（auto_classify=true） | HS分類 (`hs_classify`) + 該非判定 (`gaihi_judge`) + 品目登録 (`register_product`) | `materials.hs_code` / `eccn` / `fefta_judgment` |
| 品目再分類 | `POST /mdm/materials/{id}/reclassify` | 同上 | 同上 |
| 取引先登録 | `POST /mdm/business-partners`（auto_screen=true） | 制裁スクリーニング (`screening_batch`) | `business_partners.screening_status` / `denial_list` |
| 取引先再スクリーニング | `POST /gts/screening/{bp_code}/rescreen` | 同上 | 同上 |
| 受注登録 | `POST /sd/sales-orders`（skip_export_check=false） | 取引審査 (`create_transaction` → `run_screening` → `run_ai_judge`) | `sales_orders.export_check_status` / `export_check_ref` |
| 受注再審査 | `POST /sd/sales-orders/{id}/recheck-export` | 同上 | 同上 |
| 出荷作成 | `POST /sd/deliveries` | 出荷前再スクリーニング (`shipment_rescreen`) | `ai_tm_shipment_links.shipment_ok` / `ai_status` |
| BOM判定 | `POST /gts/judge-bom` | BOM判定 (`judge_bom`) | レスポンスのみ（DBには非保存） |
| 原産国変更通知 | `POST /gts/origin-change-log/{id}/notify-aitm` | イベント通知 (`post_event`) | `material_origin_change_logs.aitm_notified=true` |
| 判定更新受信 | `POST /gts/webhook/judgment-updated`（AI_TM → ERP） | （受信側） | `materials.eccn` / `fefta_judgment`、保留受注の自動解除 |

### 3.3 制裁スクリーニングのロジック（MOCKモード）

現在のMOCKクライアントは以下の優先順位で照合する:

```
照合優先順位:
  1. WATCHLISTキーワード照合（possible_match）
  2. OFAC 50%ルール（親会社がSDNに掲載された子会社）
  3. BIS Entity List キーワード照合（match/CRITICAL）
  4. OFAC SDNリストキーワード照合（CRITICAL）
  5. 禁輸国コード（IR/KP/SY/CU）→ match
  6. 高リスク国コード（RU/BY/VE/MM）→ possible_match
  7. 該当なし → no_match

結果マッピング:
  CRITICAL / match   → screening_status = BLOCKED, is_denied_party = true
  possible_match     → screening_status = FLAGGED
  no_match           → screening_status = CLEARED
```

### 3.4 AI_TM 接続パラメータ（環境変数）

```bash
AI_TM_MOCK_MODE=true            # false にすると実際のAI_TMに接続
AI_TM_CLASSIFICATION_URL=http://localhost:8002
AI_TM_VALIDATION_URL=http://localhost:8011
AI_TM_SCREENING_URL=http://localhost:8005
AI_TM_LICENSE_URL=http://localhost:8012
AI_TM_ORG_ID=erp-system
AI_TM_USER_ID=erp-integration@system
AI_TM_TIMEOUT_SECONDS=30
AI_TM_REVIEW_VALID_DAYS=365     # 輸出審査の有効期間（日数）
AI_TM_API_KEY=dev-erp-integration-key  # Webhook受信時の認証キー
```

---

## 4. CRM 連携設計指針

### 4.1 データの所有権（Source of Truth）

| データ領域 | 正（SoT） | 連携方向 | 備考 |
|---|---|---|---|
| 取引先マスタ（基本情報） | **ERP** | ERP → CRM | CRMは参照のみ（更新はERP経由） |
| 制裁スクリーニング結果 | **ERP/AI_TM** | ERP → CRM | CRMから書き込み不可 |
| 与信限度額 | **ERP** | ERP ↔ CRM | 更新フローは要件定義で決定 |
| 商談情報 | **CRM** | CRM → ERP | 成約後に受注転記 |
| 受注・出荷・請求 | **ERP** | ERP → CRM | CRMは参照のみ |
| 品目カタログ | **ERP** | ERP → CRM | ECCN等の規制情報を含む |
| 営業活動ログ | **CRM** | — | ERP非管理 |

### 4.2 CRM側で実装すべきガードレール

#### 制裁スクリーニング連動

```
商談作成時の制御フロー:
  1. ERP API で取引先の screening_status を取得
  2. BLOCKED → 商談作成を禁止。「制裁対象: {denial_list}」を表示
  3. FLAGGED → 警告表示の上で作成許可。コンプライアンス部門への承認を要求
  4. UNSCREENED → スクリーニング実施を促す警告
  5. CLEARED → 通常フロー
```

#### 品目の輸出規制連動

```
見積品目追加時の制御フロー:
  1. ERP API で品目の eccn / hs_code / country_of_origin を取得
  2. 仕向国（取引先.country）と eccn の組み合わせを評価
  3. 規制対象品目（3B001/3C001/1C350等）+ リスク国 → 輸出ライセンス確認を要求
  4. fefta_judgment = APPLICABLE → 外為法確認を要求
```

#### 与信枠チェック

```
受注転記前の与信チェック:
  1. ERP API で credit_limit を取得
  2. 既存受注残高（OPEN/RELEASED状態のSO合計）を取得
  3. 今回見積金額 + 残高 > credit_limit の場合は承認フローを起動
```

### 4.3 受注転記のAPI呼び出し仕様

```json
POST http://localhost:8888/sd/sales-orders
Authorization: Bearer {token}

{
  "customer_code": "BP-1000001",
  "customer_po_number": "CRM-DEAL-2026-XXX",
  "document_date": "2026-08-14",
  "requested_delivery_date": "2026-09-30",
  "incoterms": "CIF",
  "payment_terms": "NET60",
  "currency": "USD",
  "skip_export_check": false,
  "items": [
    {
      "material_code": "MAT-1000001",
      "quantity": 100,
      "unit": "L",
      "unit_price": 850.00
    }
  ]
}
```

レスポンスの `document_number`（受注番号）をCRM商談に紐付けて管理する。

### 4.4 推奨する同期方式

| 方式 | 適用ケース | メリット | デメリット |
|---|---|---|---|
| REST差分ポーリング | BP・品目マスタの定期同期 | ERP側の改修不要 | リアルタイム性なし（分〜時間単位） |
| Webhook プッシュ | 制裁ステータス変更の即時通知 | リアルタイム | ERP側にWebhookディスパッチャー実装が必要 |
| CSV/バッチ | 大量データの初期投入 | シンプル | リアルタイム性なし |

**差分ポーリングの実装例:**
```
GET /mdm/business-partners?limit=100&offset=0
```
`updated_at` フィールドで前回同期以降の更新分を検出する（現在`updated_after`クエリパラメータは未実装、要追加）。

---

## 5. 3システム間の業務フロー

### 5.1 新規顧客獲得から初回出荷まで

```
CRM                         ERP（本システム）              AI Trade Management
 │                               │                              │
 │── 新規顧客情報入力 ──────────→│                              │
 │                        BP登録 │── screening_batch ──────────→│
 │                               │                    制裁審査実行│
 │                               │←── 審査結果（CLEARED/BLOCKED）│
 │                               │                              │
 │ [BLOCKED の場合: CRMに警告]    │                              │
 │                               │                              │
 │── 商談クローズ ───────────────→│                              │
 │                      受注登録 │── create_transaction ────────→│
 │                               │── run_screening ─────────────→│
 │                               │── run_ai_judge ──────────────→│
 │                               │←── 輸出審査結果（PASSED/BLOCKED）│
 │                               │                              │
 │←── 受注番号フィードバック ────│                              │
 │                               │                              │
 │                       出荷作成│── shipment_rescreen ─────────→│
 │                               │←── 出荷可否結果              │
 │                               │                              │
 │                       請求発行│                              │
 │←── 請求情報参照 ─────────────│                              │
```

### 5.2 品目の新規登録フロー

```
ERP                              AI Trade Management
 │                                      │
 │── POST /mdm/materials ───────────────│
 │   (auto_classify=true)        HS分類 │ hs_classify()
 │                               該非判定│ gaihi_judge()
 │                               品目登録│ register_product()
 │←── hs_code / eccn / fefta_judgment ──│
 │                                      │
 │ materials テーブルに自動更新          │
 │                                      │
 │ （BOM展開が必要な製品の場合）         │
 │── POST /gts/judge-bom ───────────────│
 │                              BOM判定  │ judge_bom()
 │←── 輸出規制リスク評価結果 ───────────│
```

### 5.3 制裁ステータス変更時の通知フロー（設計案）

```
AI Trade Management          ERP                         CRM
 │                            │                           │
 │── POST /gts/webhook/ ──────→│                           │
 │   judgment-updated          │ 品目ECCN/判定更新          │
 │                             │ 保留受注の自動解除/キャンセル│
 │                             │── [Webhook/ポーリング] ──→ │
 │                             │                    ステータス│
 │                             │                    更新通知  │
 │                             │                           │
 │                             │                 BLOCKED検知│
 │                             │                 商談への警告│
```

---

## 6. 業務分担マトリクス

### 6.1 機能別の主管システム

| 業務機能 | 主管 | 参照 | 備考 |
|---|---|---|---|
| 顧客情報管理（基本） | **ERP** | CRM | BPコードで一元管理 |
| 顧客との関係管理・商談 | **CRM** | — | ERP非管理領域 |
| 仕入先管理 | **ERP** | — | BPのロール=VENDORで管理 |
| 品目カタログ管理 | **ERP** | CRM | ECCN・HSコード含む |
| 制裁スクリーニング | **ERP/AI_TM** | CRM（結果参照） | ERP経由でAI_TMに依頼 |
| 輸出規制品目判定（ECCN/HS） | **AI_TM** | ERP（結果格納） | AI_TMが主判定機関 |
| 輸出取引審査 | **AI_TM** | ERP（結果格納） | 受注ごとに審査 |
| 輸出申告・許可証管理 | **ERP** | — | GTS.ExportDeclaration |
| 受注管理 | **ERP** | CRM（参照） | CRM商談から転記 |
| 与信管理 | **ERP** | CRM | 更新ルール要定義 |
| 出荷・配送管理 | **ERP** | — | |
| 請求・回収管理 | **ERP** | CRM（参照） | PDF発行機能あり |
| 製造管理 | **ERP** | — | PP/QM/MM連携 |
| 財務会計 | **ERP** | — | 自動仕訳 |
| 原価管理 | **ERP** | — | CO/PP連携 |
| 人事管理 | **ERP** | — | |
| 営業予実管理 | **ERP**（フォーキャスト）/ **CRM**（パイプライン） | 相互参照 | ERPは出荷実績ベース |

### 6.2 データ更新権限マトリクス

| データ | ERP | AI_TM | CRM |
|---|---|---|---|
| 取引先基本情報（name/country/address） | **Write** | — | Read / 更新申請 |
| 取引先 screening_status | Read（AI_TM結果格納） | **Write** | Read |
| 取引先 credit_limit | **Write** | — | Read / 要件定義次第 |
| 品目 hs_code / eccn | Read（AI_TM結果格納） | **Write** | Read |
| 品目 standard_price | **Write** | — | Read |
| 受注（SalesOrder） | **Write** | — | Read / 転記APIで作成 |
| 受注 export_check_status | Read（AI_TM結果格納） | **Write** | Read |
| 輸出申告 | **Write** | — | — |
| 在庫残高 | **Write** | — | — |

---

## 7. 運用上の注意事項

### 7.1 BLOCKED取引先への対応

`screening_status = BLOCKED` の取引先に対して:

- ERPの受注登録（`POST /sd/sales-orders`）は**自動ブロック**される
- 既存の未出荷受注は手動でのキャンセル処理が必要
- `is_denied_party=true` フラグが立つ
- CRM側でも商談・見積の作成を**アプリケーションレベルでブロック**することを強く推奨
- スクリーニング結果は `GET /gts/screening/log` で全履歴を監査ログとして参照可能

### 7.2 スクリーニングの再実行タイミング

制裁リストは定期的に更新されるため、以下のタイミングで再スクリーニングを実施することを推奨:

- **新規BP登録時**: `auto_screen=true`（デフォルト）で自動実行
- **定期バッチ**: `POST /gts/screening/rescreen-all`（月次推奨）
- **出荷前**: Delivery作成時に AI_TM が自動再スクリーニング
- **制裁リスト更新情報入手時**: 手動で `rescreen-all` を実行

### 7.3 AI_TM MOCKモードから本番切り替え時の注意

`AI_TM_MOCK_MODE=false` に切り替える前に確認すること:

1. 各AI_TMマイクロサービスのURLが正しく設定されているか
2. `AI_TM_API_KEY` がWebhook認証に使用されるため、AI_TM側と一致しているか
3. `AI_TM_ORG_ID` / `AI_TM_USER_ID` がAI_TM側に登録済みか
4. MOCKモードで `CLEARED` だったBPが本番では `BLOCKED` になる可能性があるため、**全BPの再スクリーニングを実施**すること
5. 既存の輸出審査リンク（`AITMTransactionLink`）の review_status は再評価が必要な場合がある

### 7.4 De Minimis管理（米国EAR）

米国原産品を含む製品の輸出において、含有率が閾値（民生品25%、軍事品10%）を超えると米国EARが適用される:

- `GET /co/cost-estimates/{material_code}/{fiscal_year}/de-minimis` でDe Minimis比率を確認
- `GET /gts/deminimis` でロット別評価結果を確認
- 原産国変更が発生した場合は `GET /gts/origin-change-log` で変更履歴を確認し、`POST /gts/origin-change-log/{id}/notify-aitm` でAI_TMへ通知

### 7.5 輸出コンプライアンス品目のECCN管理

主要な制御品目のECCNと該当業種:

| ECCN | 対象品目例 | 主な規制 |
|---|---|---|
| `3B001` | 半導体製造装置・フォトレジスト | EAR 許可証要（CN/RU等） |
| `3C001` | シリコン前駆体・エピタキシャル材料 | EAR 許可証要 |
| `3E001` | 半導体製造技術 | EAR 技術・ソフトウェア |
| `1C350` | 化学前駆体（Schedule 2物質） | 化学兵器条約対象 |
| `1C351` | 特定の化学薬品 | 化学兵器条約Schedule 1物質 |
| `EAR99` | 規制なし品目 | 制裁国・禁止エンドユーザーへの輸出は注意 |

---

## 8. 付録

### 8.1 主要ステータスコード一覧

| フィールド | 値 | 意味 |
|---|---|---|
| `screening_status` | `UNSCREENED` | 未スクリーニング |
| | `CLEARED` | 審査通過 |
| | `FLAGGED` | 要注意（50%ルール・ウォッチリスト） |
| | `BLOCKED` | 取引禁止（BIS Entity List / OFAC SDN） |
| `export_check_status` | `PENDING` | 審査待ち |
| | `PASSED` | 輸出審査通過 |
| | `BLOCKED` | 輸出禁止 |
| | `SKIPPED` | 審査スキップ |
| `SalesOrder.status` | `OPEN` | 受注登録済み |
| | `RELEASED` | リリース済み（出荷可） |
| | `COMPLETED` | 完了 |
| | `BLOCKED` | ブロック |
| | `CANCELLED` | キャンセル |
| `fefta_judgment` | `APPROVED` | 外為法非該当（承認済み） |
| | `APPLICABLE` | 外為法該当（事前審査必要） |
| | `NOT_APPLICABLE` | 外為法対象外 |
| | `UNKNOWN` | 未判定 |
| | `PENDING` | 判定中 |

### 8.2 コード体系

| コード種別 | 形式 | 例 |
|---|---|---|
| 取引先コード | `BP-XXXXXXX` | `BP-1000001` |
| 品目コード | `MAT-XXXXXXX` | `MAT-1000001` |
| 受注番号 | 10桁数字 | `0010000000` |
| 出荷番号 | `DEL-XXXXXXX` | `DEL-0000001` |
| 請求番号 | `BIL-XXXXXXX` | `BIL-0000001` |
| 輸出申告番号 | `EXP-XXXXXXX` | `EXP-0000001` |
| 製造指図番号 | `PO-XXXXXXX` | `PO-0000001` |
| AI_TM参照番号 | `MOCK-EVT-XXXXXXXX`（MOCKモード） | `MOCK-EVT-a1b2c3d4` |

### 8.3 認証・接続情報（開発環境）

| 項目 | 値 |
|---|---|
| Base URL | `http://localhost:8888` |
| 管理者アカウント | `admin@example.com` / `admin1234` |
| テナントID | `DEMO` |
| トークン取得 | `POST /auth/token` (form: username / password / client_id) |
| Webhook認証キー | `dev-erp-integration-key`（`AI_TM_API_KEY`） |

> **本書は ERP v0.1.0 (2026-08-14時点) の仕様に基づきます。**  
> 最新のAPI仕様は常に `http://localhost:8888/docs` または `http://localhost:8888/openapi.json` を参照してください。
