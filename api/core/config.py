from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / "config" / ".env"


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
    db_password: str = "kisan2025secure"

    @property
    def database_url(self) -> str:
        """Async psycopg3 DSN for SQLAlchemy 2.0 async engine."""
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ── External Services ─────────────────────────────────
    openai_api_key: str = ""
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "kisanmitra_verify_2025"
    whatsapp_app_secret: str = ""
    data_gov_api_key: str = ""

    # ── App ───────────────────────────────────────────────
    app_env: str = "development"
    app_port: int = 8000
    secret_key: str = "kisanmitra_secret_2025"


settings = Settings()
