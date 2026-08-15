"""Application configuration loaded from environment variables."""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "Mini Global ERP"
    APP_VERSION: str = "0.1.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # Database
    DATABASE_URL: str = "sqlite:///./erp.db"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    ALGORITHM: str = "HS256"

    # AI Trade Management — 認証ヘッダー (引き継ぎ書 v2.4)
    AI_TM_ORG_ID: str = "erp-system"
    AI_TM_USER_ID: str = "erp-integration@system"
    AI_TM_TIMEOUT_SECONDS: int = 30
    AI_TM_MOCK_MODE: bool = True
    AI_TM_REVIEW_VALID_DAYS: int = 365

    # AI Trade Management — モジュール別URL
    AI_TM_CLASSIFICATION_URL: str = "http://localhost:8002"   # 品目管理・HS分類
    AI_TM_VALIDATION_URL: str = "http://localhost:8011"       # 取引審査・AI判定
    AI_TM_SCREENING_URL: str = "http://localhost:8005"        # 制裁スクリーニング
    AI_TM_RND_URL: str = "http://localhost:8003"              # R&Dリスク評価
    AI_TM_LICENSE_URL: str = "http://localhost:8012"          # 輸出ライセンス管理
    AI_TM_CORE_URL: str = "http://localhost:8000"             # 共通基盤

    # 後方互換 (旧ゲートウェイ / モック用)
    AI_TM_BASE_URL: str = "http://localhost:5001"
    AI_TM_API_KEY: str = "dev-erp-integration-key"

    # Seed
    INITIAL_ADMIN_EMAIL: str = "admin@example.com"
    INITIAL_ADMIN_PASSWORD: str = "admin1234"

    # ---------------------------------------------------------------
    # CRM inbound auth (CRM → ERP calls)
    # ---------------------------------------------------------------
    CRM_INBOUND_BEARER: str = ""
    CRM_INBOUND_SIGNING_SECRET: str = ""
    CRM_INBOUND_SIGNING_SECRET_PREVIOUS: str = ""   # kept during key rotation

    # AI_TM inbound auth (AI_TM → ERP webhooks)
    AITM_INBOUND_BEARER: str = ""
    AITM_INBOUND_SIGNING_SECRET: str = ""

    # ---------------------------------------------------------------
    # ERP → CRM outbound webhooks
    # ---------------------------------------------------------------
    CRM_WEBHOOK_BASE_URL: str = ""
    CRM_WEBHOOK_BEARER: str = ""
    CRM_WEBHOOK_SIGNING_SECRET: str = ""
    CRM_WEBHOOK_PATH_MATERIAL_UPDATED: str = "/webhooks/erp/material-updated"
    CRM_WEBHOOK_PATH_BP_UPDATED: str = "/webhooks/erp/bp-updated"
    CRM_WEBHOOK_PATH_DELIVERY_POSTED: str = "/webhooks/erp/delivery-posted"
    CRM_WEBHOOK_PATH_BILLING_POSTED: str = "/webhooks/erp/billing-posted"
    CRM_WEBHOOK_PATH_RETURN_POSTED: str = "/webhooks/erp/return-posted"

    # ERP → AI_TM outbound request signing
    AITM_REQUEST_SIGNING_SECRET: str = ""

    # Commerce check (IF-32): stub until real provider is integrated
    COMMERCE_CHECK_STUB_MODE: bool = True

    # Webhook delivery worker settings
    WEBHOOK_MAX_ATTEMPTS: int = 6
    WEBHOOK_CONNECT_TIMEOUT_SEC: int = 5
    WEBHOOK_READ_TIMEOUT_SEC: int = 10
    WEBHOOK_WORKER_INTERVAL_SEC: int = 30

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
