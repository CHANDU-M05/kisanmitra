from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "kisanmitra"
    db_user: str = "kisanmitra_user"
    db_password: str = "REDACTED_IN_HISTORY"

    @property
    def database_url(self) -> str:
        """Async psycopg3 DSN for SQLAlchemy 2.0 async engine."""
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ── External Services ─────────────────────────────────
    gemini_api_key: SecretStr = SecretStr("")
    whatsapp_token: SecretStr = SecretStr("")
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "REDACTED_IN_HISTORY"
    whatsapp_app_secret: str = ""
    data_gov_api_key: str = ""

    # ── App ───────────────────────────────────────────────
    app_env: str = "development"
    app_port: int = 8000
    secret_key: str = "REDACTED_IN_HISTORY"
    cors_origins: str = "*"



import logging
logger = logging.getLogger("kisanmitra.config")

try:
    settings = Settings()
except Exception as e:
    logger.error(f"❌ Critical Configuration Error: Missing or invalid environment variables! Details: {e}")
    raise e

_INSECURE_DEFAULT_KEY = "REDACTED_IN_HISTORY"
if settings.secret_key == _INSECURE_DEFAULT_KEY and settings.app_env == "production":
    raise RuntimeError(
        "SECRET_KEY is still set to the insecure default value. "
        "Set a strong SECRET_KEY in your .env file before running in production."
    )

if settings.app_env == "production" and not settings.whatsapp_app_secret:
    raise RuntimeError(
        "WHATSAPP_APP_SECRET must be set when running in production environment. "
        "Strictly enforce fail-closed webhook signature verification."
    )

