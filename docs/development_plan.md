# ERP 連携実装 開発計画書

**作成日:** 2026-08-15  
**対象ドキュメント:** ERP_連携引き継ぎ書.md  
**合計工数:** 92 人日（Phase 0〜5）

---

## 1. 設計レビュー結果

### 1.1 確認済み設計判断

| # | 論点 | 判断 |
|---|------|------|
| 1 | `aitm_allocation_id` (IF-23 Webhook 受信) | AI_TM チームが並行開発。ERP 側はそのまま実装する |
| 2 | エンドユーザー BP の `auto_screen` | `true` で固定（CRM から `end_user` フィールドで受信した時点で自動スクリーニング） |
| 3 | フェーズ着手順序 | **Phase 0 を明確に最初に着手する**（他フェーズはすべて Phase 0 に依存） |

### 1.2 現状コードとの差分（Gap Analysis）

#### 1.2.1 データモデルのギャップ

**`SalesOrder`（app/modules/sd/models.py）**

| 必要カラム | 現状 | 対処 |
|-----------|------|------|
| `crm_contract_id` | なし | ALTER TABLE / モデル追加 |
| `crm_engagement_id` | なし | 同上 |
| `aitm_transaction_id` | なし | 同上（CRM 紐付け時に直接格納） |
| `aitm_allocation_id` | なし | 同上（IF-23 Webhook で受信） |
| `end_user_bp_code` | なし | 同上 |
| `contract_start_date` | なし | 同上 |
| `contract_end_date` | なし | 同上 |
| `export_review_valid_until` | なし | 同上 |

**`BusinessPartner`（app/modules/mdm/models.py）**

| 必要カラム | 現状 | 対処 |
|-----------|------|------|
| `aitm_party_id` | なし | ALTER TABLE / モデル追加 |
| `crm_account_id` | なし | 同上 |
| `corporate_number` | なし | 同上 |
| `representative_name` | なし | 同上 |
| `credit_check_status` | なし | 同上（sanctions 系とは別管理） |
| `antisocial_check_status` | なし | 同上 |
| `credit_checked_at` | なし | 同上 |
| `antisocial_checked_at` | なし | 同上 |

> **注意:** `screening_status / is_denied_party / denial_list` は AI_TM/sanctions 管理。上記新規カラムは CRM commerce check 管理。混在させない。

**`AITMTransactionLink`（app/modules/gts/models.py）**

| 必要カラム | 現状 | 対処 |
|-----------|------|------|
| `link_source` (`'erp'` / `'crm'`) | なし | カラム追加 |

**`DocStatus`（app/shared/base_models.py）**

| 必要定数 | 現状 | 対処 |
|---------|------|------|
| `SUSPENDED = "SUSPENDED"` | なし | 定数追加、`ALL` セット更新 |

#### 1.2.2 新規テーブルのギャップ

| テーブル | 用途 | フェーズ |
|---------|------|---------|
| `tenant_mapping` | `client_id` ↔ `crm_tenant_id` 変換 | Phase 0 |
| `webhook_delivery` | ERP→CRM 配信キュー（retry / DLQ） | Phase 0 |
| `inbound_request_log` | 受信リクエストの冪等性チェック用 | Phase 0 |
| `commerce_check_logs` | IF-32 商務チェック結果ログ | Phase 3 |
| `return_documents` / `return_document_items` | IF-22/IF-31 返品処理 | Phase 4 |

#### 1.2.3 認証レイヤーのギャップ

現行 `/gts/webhook/judgment-updated` の認証:

```python
# app/modules/gts/router.py（現状）
def _verify_webhook_key(authorization: str = Header(default="")) -> None:
    expected = f"Bearer {settings.AI_TM_API_KEY}"
    if authorization != expected:
        raise HTTPException(status_code=401, ...)
```

**必要な認証（引き継ぎ書 §7 準拠）:**
- HMAC-SHA256: `X-Signature: sha256={hex}` （`"{timestamp}.{raw_body}"` で署名）
- タイムスタンプ: `X-Timestamp` ±300s 検証
- Bearer トークン: 二重認証
- リプレイ防止: `X-Request-Id` を `inbound_request_log` に記録（TTL 10 分）
- キーローテーション: `_PREVIOUS` サフィックスの旧キーも一定期間許容

#### 1.2.4 ビジネスロジックのギャップ

**`SalesOrderService.create` (app/modules/sd/service.py:95)**

```python
# 現状
if not payload.skip_export_check:
    ...GTSService.transaction_review(so, customer)...

# 必要（IF-25 ブランチ）
if payload.aitm_transaction_id:
    # CRM 連携ケース: 既存 AI_TM トランザクションにリンク
    db.add(AITMTransactionLink(
        sales_order_id=so.id,
        aitm_transaction_id=payload.aitm_transaction_id,
        link_source="crm",
        review_status="LINKED"))
    so.aitm_transaction_id = payload.aitm_transaction_id
    so.export_check_status = "PENDING"
elif not payload.skip_export_check:
    GTSService.transaction_review(so, customer)  # IF-19（既存）
else:
    so.export_check_status = "SKIPPED"
```

**`_run_shipment_rescreen` (app/modules/sd/service.py:212)**

CRM リンク受注（`so.aitm_transaction_id` 直接保持）に対して `so.export_check_ref` を `case_no` として使う現ロジックが不整合。修正が必要。

---

## 2. 実装フェーズ計画

### Phase 0 — 共通認証・配信基盤（17 人日）★ **最初に着手**

すべての後続フェーズがこのフェーズに依存する。

#### E0-1: `tenant_mapping` テーブル（1 人日）

**作成ファイル:** `app/modules/mdm/models.py`（末尾に追記）

```python
class TenantMapping(Base):
    __tablename__ = "tenant_mapping"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    crm_tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

**初期データ:** `client_id="DEMO"` → `crm_tenant_id="CRM_DEMO"`

#### E0-2: 受信認証ライブラリ（3 人日）

**新規ファイル:** `app/shared/integration_auth.py`

実装要件:
- `verify_inbound(request, source, x_signature, x_timestamp, x_request_id, x_tenant_id)` 非同期関数
- `source` = `"aitm"` | `"crm"` でシークレット切り替え
- HMAC: `hmac.new(secret, f"{ts}.".encode() + raw_body, sha256).hexdigest()`
- タイムスタンプ: `abs(time.time() - int(x_timestamp)) > 300` → 401
- Bearer 二重確認
- `inbound_request_log` への `x_request_id` 記録（冪等性）

#### E0-3: キーローテーションサポート（1 人日）

**修正ファイル:** `app/shared/integration_auth.py`

- `CRM_INBOUND_SIGNING_SECRET_PREVIOUS` 環境変数が存在する場合、旧キーでも検証を通す
- 新キー検証失敗 → 旧キーで再試行 → 両方失敗で 401

#### E0-4: `/gts/webhook/judgment-updated` 認証強化（1 人日）

**修正ファイル:** `app/modules/gts/router.py`

- 既存 `_verify_webhook_key` を `verify_inbound(..., source="aitm")` に置き換え
- 後続の `aitm_allocation_id` 格納ロジック（IF-23）のプレースホルダーも追加

#### E0-5: `webhook_delivery` テーブル + モデル（3 人日）

**修正ファイル:** `app/core/database.py`（または新規マイグレーション）  
**新規ファイル:** `app/modules/shared/webhook_models.py`

```python
class WebhookDelivery(Base):
    __tablename__ = "webhook_delivery"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    client_id: Mapped[str] = mapped_column(String(20), nullable=False)
    target_system: Mapped[str] = mapped_column(String(20), nullable=False)  # "crm"
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON 文字列（シリアライズ済み）
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # pending|delivered|failed|dlq
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_status_code: Mapped[Optional[int]] = mapped_column(Integer)
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
```

**新規ファイル:** `app/shared/webhook_dispatcher.py`

`enqueue_webhook(db, client_id, event_type, payload_dict)` 関数:
- `event_id = str(uuid4())`
- `occurred_at = datetime.utcnow()`
- `status = "pending"`, `next_attempt_at = now`
- `payload = json.dumps(payload_dict)` （再シリアライズしない。配信時はこの文字列をそのまま送信）

#### E0-6: リトライワーカー（3 人日）

**新規ファイル:** `scripts/process_webhook_queue.py`

実装仕様:
- 30 秒間隔ポーリング（`WEBHOOK_WORKER_INTERVAL_SEC=30`）
- `status="pending" AND next_attempt_at <= now()` を最大 50 件取得
- 配信関数 `deliver(d: WebhookDelivery)`:
  ```python
  body = d.payload.encode()  # stored string をそのまま使う
  ts = str(int(time.time()))
  sig = hmac.new(secret("CRM_WEBHOOK_SIGNING_SECRET"), f"{ts}.".encode() + body, sha256).hexdigest()
  headers = {
      "Authorization": f"Bearer {settings.CRM_WEBHOOK_BEARER}",
      "X-Signature": f"sha256={sig}",
      "X-Timestamp": ts,
      "X-Request-Id": d.event_id,
      "X-Tenant-Id": crm_tenant_id(d.client_id),
      "Content-Type": "application/json",
  }
  ```
- 成功（2xx）: `status="delivered"`, `delivered_at=now`
- 失敗: `attempt_count += 1`
  - `attempt_count < WEBHOOK_MAX_ATTEMPTS(6)`: 指数バックオフ + jitter で `next_attempt_at` 更新
  - `attempt_count >= 6`: `status="dlq"`
- バックオフ計算: `base * 2^attempt + random(0, base)` （base=30s）

#### E0-7: DLQ 管理エンドポイント（3 人日）

**修正ファイル:** `app/main.py`（ルーター登録）  
**新規ファイル:** `app/modules/shared/webhook_router.py`

エンドポイント:
- `GET /admin/webhook-delivery?status=dlq` — DLQ 一覧
- `POST /admin/webhook-delivery/{event_id}/retry` — 手動リトライ（`status="pending"`, `next_attempt_at=now`）
- `DELETE /admin/webhook-delivery/{event_id}` — DLQ 破棄

#### E0-8: `inbound_request_log` テーブル（2 人日）

**新規モデル:** `app/shared/webhook_models.py`（E0-5 と同ファイル）

```python
class InboundRequestLog(Base):
    __tablename__ = "inbound_request_log"
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # "aitm" | "crm"
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)  # +10分
```

冪等性ロジック:
- `verify_inbound` 内で `request_id` を `inbound_request_log` に存在確認
- 存在すれば 409（重複リクエスト）
- なければ挿入（TTL 10 分後の `expires_at` を設定）

**Phase 0 完了条件:**
- [ ] `/gts/webhook/judgment-updated` が HMAC 検証を通過する（IT-01 相当）
- [ ] `webhook_delivery` テーブルにレコードが登録・配信される
- [ ] DLQ エンドポイントが動作する
- [ ] 既存 68 件のテストがすべてグリーン

---

### Phase 1 — CRM 契約受信（22 人日）

#### E1-1: `DocStatus.SUSPENDED` 追加（0.5 人日）

**修正ファイル:** `app/shared/base_models.py`

```python
class DocStatus:
    ...
    SUSPENDED = "SUSPENDED"
    ALL = {DRAFT, OPEN, RELEASED, BLOCKED, COMPLETED, CANCELLED, SUSPENDED}
```

#### E1-2: `SalesOrder` カラム追加（1 人日）

**修正ファイル:** `app/modules/sd/models.py`

追加カラム（すべて nullable）:
```python
crm_contract_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
crm_engagement_id: Mapped[Optional[str]] = mapped_column(String(100))
aitm_transaction_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
aitm_allocation_id: Mapped[Optional[str]] = mapped_column(String(36))
end_user_bp_code: Mapped[Optional[str]] = mapped_column(String(50))
contract_start_date: Mapped[Optional[date]] = mapped_column(Date)
contract_end_date: Mapped[Optional[date]] = mapped_column(Date)
export_review_valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime)
```

#### E1-3: `AITMTransactionLink.link_source` カラム追加（0.5 人日）

**修正ファイル:** `app/modules/gts/models.py`

```python
link_source: Mapped[str] = mapped_column(String(10), default="erp", nullable=False)
# "erp": ERP 起点レビュー, "crm": CRM が既存 AI_TM トランザクションを持ち込んだリンク
```

#### E1-4: `BusinessPartner` カラム追加（1 人日）

**修正ファイル:** `app/modules/mdm/models.py`

追加カラム:
```python
aitm_party_id: Mapped[Optional[str]] = mapped_column(String(36))
crm_account_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
corporate_number: Mapped[Optional[str]] = mapped_column(String(20))
representative_name: Mapped[Optional[str]] = mapped_column(String(200))
credit_check_status: Mapped[Optional[str]] = mapped_column(String(20))  # OK/NG/PENDING
antisocial_check_status: Mapped[Optional[str]] = mapped_column(String(20))
credit_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
antisocial_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
```

#### E1-5: `SalesOrderCreate` スキーマ拡張（1 人日）

**修正ファイル:** `app/modules/sd/schemas.py`

```python
class SalesOrderCreate(BaseModel):
    ...
    crm_contract_id: Optional[str] = None
    crm_engagement_id: Optional[str] = None
    aitm_transaction_id: Optional[str] = None  # IF-25 コア
    end_user: Optional[EndUserCreate] = None   # エンドユーザー BP 自動生成用
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None

class EndUserCreate(BaseModel):
    name: str
    country: str
    address: Optional[str] = None
    crm_account_id: Optional[str] = None
```

#### E1-6: IF-25 ブランチ実装（5 人日）

**修正ファイル:** `app/modules/sd/service.py`

`SalesOrderService.create` のエクスポートチェックセクションを 3 ブランチに分岐:

```python
if payload.aitm_transaction_id:
    # Case CRM: 既存 AI_TM トランザクションへのリンク
    so.aitm_transaction_id = payload.aitm_transaction_id
    so.crm_contract_id = payload.crm_contract_id
    so.crm_engagement_id = payload.crm_engagement_id
    self.db.add(AITMTransactionLink(
        client_id=client_id,
        sales_order_id=so.id,
        aitm_transaction_id=payload.aitm_transaction_id,
        link_source="crm",
        review_status="LINKED",
        linked_existing=True,
    ))
    so.export_check_status = "PENDING"
    # エンドユーザー BP 自動生成
    if payload.end_user:
        _create_end_user_bp(self.db, client_id, payload.end_user, so, user_email)
elif not payload.skip_export_check:
    # Case ERP: 通常フロー（IF-19 既存）
    _link, result = GTSService(self.db).transaction_review(so, customer)
    ...
else:
    so.export_check_status = "SKIPPED"
```

エンドユーザー BP 生成 `_create_end_user_bp`:
- `roles=["END_USER"]`、`auto_screen=True`
- `screening_status="PENDING"` でスクリーニングキューへ
- `so.end_user_bp_code = bp.bp_code`

#### E1-7: `_run_shipment_rescreen` 修正（1 人日）

**修正ファイル:** `app/modules/sd/service.py:212`

```python
# 修正前
case_no = so.export_check_ref

# 修正後
case_no = so.aitm_transaction_id or so.export_check_ref
```

#### E1-8: `POST /crm/sales-orders` エンドポイント（3 人日）

**新規ファイル:** `app/modules/sd/crm_router.py`

- HMAC 認証: `verify_inbound(..., source="crm")`
- ペイロード変換 → `SalesOrderCreate`
- レスポンスに `erp_sales_order_id`, `erp_document_number`, `export_check_status`
- 正常完了後: `enqueue_webhook(db, client_id, "sales_order.created", {...})` (IF-26 契機)

#### E1-9: `POST /crm/continuous-monitoring-hold` エンドポイント（IF-24）（3 人日）

**新規ファイル:** `app/modules/sd/crm_router.py`（E1-8 と同ファイル）

- `so.status = DocStatus.SUSPENDED`
- 理由: `suspension_reason` フィールドを追記（メモ欄相当）
- 対象受注が `OPEN` または `RELEASED` の場合のみ受付
- 完了後: `enqueue_webhook(db, client_id, "sales_order.suspended", {...})`

#### E1-10: IF-23 Webhook 受信（`aitm_allocation_id` 格納）（3 人日）

**修正ファイル:** `app/modules/gts/router.py`（E0-4 のプレースホルダーを実装）

```python
# judgment-updated webhook の拡張
if payload.allocation_id:
    so = _get_so_by_aitm_transaction(db, payload.transaction_id)
    if so:
        so.aitm_allocation_id = payload.allocation_id
```

**Phase 1 完了条件:**
- [ ] `POST /crm/sales-orders` が HMAC 検証を通過する（IT-04 相当）
- [ ] `aitm_transaction_id` あり → `link_source="crm"` で `AITMTransactionLink` 作成
- [ ] `aitm_transaction_id` なし → 既存フロー継続
- [ ] エンドユーザー BP が `auto_screen=true` で生成される（IT-05）
- [ ] `SUSPENDED` ステータスが設定・解除できる（IT-06）
- [ ] 既存 68 件のテストがすべてグリーン

---

### Phase 2 — ERP→CRM プッシュ（14 人日）

#### E2-1: マスタデータ更新 Webhook（IF-26、IF-27）（4 人日）

**修正ファイル:** `app/modules/mdm/service.py`

`MaterialService.update` / `BusinessPartnerService.update` 末尾に追記:
```python
enqueue_webhook(db, client_id, "material.updated", material_to_dict(mat))
enqueue_webhook(db, client_id, "bp.updated", bp_to_dict(bp))
```

#### E2-2: 出荷 Webhook（IF-28）（3 人日）

**修正ファイル:** `app/modules/sd/service.py`

`DeliveryService.post_goods_issue` 末尾に追記:
```python
if delivery.sales_order and delivery.sales_order.crm_contract_id:
    enqueue_webhook(db, client_id, "delivery.goods_issued", delivery_to_dict(delivery))
```

#### E2-3: 請求 Webhook（IF-29）（3 人日）

**修正ファイル:** `app/modules/sd/service.py`（請求確定ロジック）

```python
if billing.crm_contract_id:
    enqueue_webhook(db, client_id, "billing.posted", billing_to_dict(billing))
```

#### E2-4: 返品 Webhook（IF-30）（4 人日）

Phase 4（E4-1）と並行して実装。返品ドキュメント作成後に送信。

**Phase 2 完了条件:**
- [ ] マスタ更新が CRM Webhook を発火する（IT-07/IT-08）
- [ ] 出荷確定・請求確定が CRM Webhook を発火する（IT-09/IT-10）
- [ ] 全 Webhook がリトライキューで処理される（IT-11）

---

### Phase 3 — コマーシャルチェック IF-32（11 人日）

#### E3-1: `commerce_check_logs` テーブル（1 人日）

**新規モデル:** `app/modules/gts/commerce_check.py`

#### E3-2: IF-32 スタブ実装（5 人日）

**新規ファイル:** `app/modules/gts/commerce_check.py`

```python
STUB_MODE = os.getenv("COMMERCE_CHECK_STUB_MODE", "true").lower() == "true"

def run_commerce_check(db, payload):
    bp = _resolve_bp(db, payload.counterparty)
    if STUB_MODE:
        result = _stub_ok_result(bp)  # 常に ok
        # counterparty_attributes は実データから生成
    log = CommerceCheckLog(..., stub_mode=STUB_MODE)
    db.add(log)
    if bp:
        bp.credit_check_status = result["results"]["credit"]["result"].upper()
        bp.antisocial_check_status = result["results"]["antisocial"]["result"].upper()
        bp.credit_checked_at = datetime.utcnow()
        bp.antisocial_checked_at = datetime.utcnow()
    return result
```

`stub_mode=true` を必ずログに記録。

#### E3-3: `POST /crm/commerce-check` エンドポイント（5 人日）

**修正ファイル:** `app/modules/gts/router.py`

- HMAC 認証: `verify_inbound(..., source="crm")`
- `run_commerce_check` 呼び出し
- レスポンス形式は引き継ぎ書 §5.3 の production-equivalent 構造

**Phase 3 完了条件:**
- [ ] `POST /crm/commerce-check` が HMAC 認証を通過する（IT-12）
- [ ] スタブ応答が `stub_mode=true` でログに記録される
- [ ] BP の `credit_check_status` / `antisocial_check_status` が更新される

---

### Phase 4 — ライセンス消費・返品（20 人日）

#### E4-1: 返品ドキュメントモデル（3 人日）

**修正ファイル:** `app/modules/sd/models.py`

```python
class ReturnDocument(Base):
    __tablename__ = "return_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20), nullable=False)
    document_number: Mapped[str] = mapped_column(String(20), nullable=False)
    crm_return_request_id: Mapped[Optional[str]] = mapped_column(String(100))
    original_delivery_id: Mapped[Optional[int]] = mapped_column(ForeignKey("deliveries.id"))
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    return_reason: Mapped[Optional[str]] = mapped_column(String(200))
    ...
```

#### E4-2: `POST /crm/returns` エンドポイント（IF-31）（5 人日）

**新規ファイル:** `app/modules/sd/return_service.py`

- HMAC 認証
- `ReturnDocument` + `ReturnDocumentItem` 作成
- 在庫戻し（`StockMovement` 追記）
- 完了後: IF-30 Webhook 発火（E2-4）

#### E4-3: IF-21 ライセンス消費（`aitm_allocation_id` 使用）（8 人日）

**修正ファイル:** `app/modules/sd/service.py`（GoodsIssue ロジック）

```python
# GoodsIssue 確定と同一 DB トランザクション内で
if so.aitm_allocation_id:
    aitm_client.consume_license(
        allocation_id=so.aitm_allocation_id,
        quantity=total_shipped_qty,
    )
    db.add(LicenseConsumptionLog(
        client_id=client_id,
        delivery_id=delivery.id,
        aitm_allocation_id=so.aitm_allocation_id,
        quantity=total_shipped_qty,
    ))
```

失敗時はロールバック（DB トランザクションを巻き戻す）。

#### E4-4: `LicenseConsumptionLog` テーブル（2 人日）

**修正ファイル:** `app/modules/gts/models.py`

```python
class LicenseConsumptionLog(Base):
    __tablename__ = "license_consumption_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(20))
    delivery_id: Mapped[int] = mapped_column(ForeignKey("deliveries.id"))
    aitm_allocation_id: Mapped[str] = mapped_column(String(36))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    consumed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String(20))  # OK / ERROR
```

#### E4-5: `GET /gts/license-consumptions` エンドポイント（2 人日）

消費済みライセンス一覧。運用確認用。

**Phase 4 完了条件:**
- [ ] 返品処理が在庫を戻す（IT-13）
- [ ] GoodsIssue と同一トランザクションでライセンス消費が記録される（IT-14）
- [ ] ライセンス消費 API 失敗時に GoodsIssue がロールバックされる（RT-06 相当）

---

### Phase 5 — カットオーバー準備（8 人日）

#### E5-1: 環境変数ドキュメント整備（1 人日）

**修正ファイル:** `.env.example`

Phase 0〜4 で追加した全環境変数を列挙:
```bash
# CRM 受信認証
CRM_INBOUND_BEARER=
CRM_INBOUND_SIGNING_SECRET=
CRM_INBOUND_SIGNING_SECRET_PREVIOUS=  # キーローテーション用

# AI_TM 受信認証（既存 AI_TM_API_KEY を拡張）
AITM_INBOUND_BEARER=
AITM_INBOUND_SIGNING_SECRET=

# CRM Webhook 送信
CRM_WEBHOOK_BASE_URL=
CRM_WEBHOOK_BEARER=
CRM_WEBHOOK_SIGNING_SECRET=
CRM_WEBHOOK_PATH_MATERIAL_UPDATED=/webhooks/erp/material-updated
CRM_WEBHOOK_PATH_BP_UPDATED=/webhooks/erp/bp-updated
CRM_WEBHOOK_PATH_DELIVERY_POSTED=/webhooks/erp/delivery-posted
CRM_WEBHOOK_PATH_BILLING_POSTED=/webhooks/erp/billing-posted
CRM_WEBHOOK_PATH_RETURN_POSTED=/webhooks/erp/return-posted

# AI_TM 送信署名
AITM_REQUEST_SIGNING_SECRET=

# コマーシャルチェック
COMMERCE_CHECK_STUB_MODE=true

# Webhook ワーカー
WEBHOOK_MAX_ATTEMPTS=6
WEBHOOK_CONNECT_TIMEOUT_SEC=5
WEBHOOK_READ_TIMEOUT_SEC=10
WEBHOOK_WORKER_INTERVAL_SEC=30
```

#### E5-2: 統合テストシナリオ実装（5 人日）

引き継ぎ書 §9 の IT-01〜IT-16 を `tests/test_crm_integration.py` として実装。

**優先シナリオ:**

| シナリオ ID | 内容 | 対象フェーズ |
|------------|------|------------|
| IT-01 | AI_TM Webhook を HMAC で検証 | Phase 0 |
| IT-02 | タイムスタンプ期限切れで 401 | Phase 0 |
| IT-03 | リプレイ攻撃で 409 | Phase 0 |
| IT-04 | CRM 契約受信 → SO 作成 | Phase 1 |
| IT-05 | エンドユーザー BP 自動生成 + スクリーニング | Phase 1 |
| IT-06 | SUSPENDED / 解除 | Phase 1 |
| IT-07 | マスタ更新 → Webhook キュー | Phase 2 |
| IT-08 | Webhook リトライ（3xx/5xx シミュレーション） | Phase 2 |
| IT-09 | GoodsIssue → Webhook + ライセンス消費 | Phase 4 |
| IT-10 | ライセンス消費失敗 → GoodsIssue ロールバック | Phase 4 |
| IT-11 | コマーシャルチェック → stub_mode ログ確認 | Phase 3 |
| IT-12〜16 | RT-01〜RT-08 リグレッション確認 | 全フェーズ |

#### E5-3: リグレッションガード（2 人日）

既存 68 件のテスト（`tests/` ディレクトリ）を CI チェックに組み込む。

**必須グリーン条件（RT-01〜RT-08）:**

| テスト | 確認内容 |
|--------|---------|
| RT-01 | 既存 SO 作成フロー（`aitm_transaction_id` なし）が壊れない |
| RT-02 | `skip_export_check=true` フローが壊れない |
| RT-03 | 否認当事者チェックが機能する |
| RT-04 | GoodsIssue → 在庫減算が正しい |
| RT-05 | 請求確定 → 売掛債権計上が正しい |
| RT-06 | 外部 API 失敗時のロールバック |
| RT-07 | マルチテナント分離（client_id 混在しない） |
| RT-08 | JWT 認証エラーが 401 を返す |

---

## 3. ファイル変更一覧

### 変更対象（既存ファイル）

| ファイル | 変更内容 |
|---------|---------|
| `app/shared/base_models.py` | `DocStatus.SUSPENDED` 追加 |
| `app/modules/sd/models.py` | `SalesOrder` に 8 カラム追加、`ReturnDocument` 追加 |
| `app/modules/sd/schemas.py` | `SalesOrderCreate` 拡張（CRM フィールド） |
| `app/modules/sd/service.py` | IF-25 ブランチ、`_run_shipment_rescreen` 修正、GoodsIssue ライセンス消費 |
| `app/modules/mdm/models.py` | `BusinessPartner` に 8 カラム追加、`TenantMapping` 追加 |
| `app/modules/mdm/service.py` | Webhook enqueue（IF-26/27） |
| `app/modules/gts/models.py` | `AITMTransactionLink.link_source` 追加、`LicenseConsumptionLog` 追加 |
| `app/modules/gts/router.py` | `/judgment-updated` HMAC 強化、`/crm/commerce-check` 追加 |
| `app/core/config.py` | 新規環境変数 15 件追加 |
| `app/main.py` | 新規ルーター登録 |
| `.env.example` | 新規環境変数ドキュメント |

### 新規作成ファイル

| ファイル | 内容 |
|---------|------|
| `app/shared/integration_auth.py` | HMAC 受信認証ライブラリ |
| `app/shared/webhook_dispatcher.py` | `enqueue_webhook` 関数 |
| `app/shared/webhook_models.py` | `WebhookDelivery`, `InboundRequestLog` モデル |
| `app/modules/sd/crm_router.py` | `POST /crm/sales-orders`, `POST /crm/continuous-monitoring-hold` |
| `app/modules/sd/return_service.py` | 返品処理サービス |
| `app/modules/gts/commerce_check.py` | IF-32 スタブ + `CommerceCheckLog` |
| `app/modules/shared/webhook_router.py` | DLQ 管理 Admin エンドポイント |
| `scripts/process_webhook_queue.py` | リトライワーカー（定期実行スクリプト） |
| `tests/test_crm_integration.py` | IT-01〜IT-16 統合テスト |

---

## 4. 工数サマリー

| フェーズ | 内容 | 工数 | 依存 |
|---------|------|------|------|
| **Phase 0** | 共通認証・配信基盤 | **17 人日** | なし（最初に着手） |
| Phase 1 | CRM 契約受信 | 22 人日 | Phase 0 完了後 |
| Phase 2 | ERP→CRM プッシュ | 14 人日 | Phase 0、Phase 1 の一部 |
| Phase 3 | コマーシャルチェック | 11 人日 | Phase 0 完了後 |
| Phase 4 | ライセンス消費・返品 | 20 人日 | Phase 1、IF-23 実装後 |
| Phase 5 | カットオーバー準備 | 8 人日 | Phase 1〜4 完了後 |
| **合計** | | **92 人日** | |

---

## 5. 実装開始チェックリスト

Phase 0 着手前に確認:

- [ ] `CRM_INBOUND_SIGNING_SECRET` を CRM チームと合意・交換済み
- [ ] `AITM_INBOUND_SIGNING_SECRET` を AI_TM チームと合意・交換済み
- [ ] CRM Webhook エンドポイント URL が確定している
- [ ] `crm_tenant_id` の値が確定している（`tenant_mapping` 初期データ用）
- [ ] AI_TM 側の `aitm_allocation_id` フィールド追加スケジュールを確認済み
