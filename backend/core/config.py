from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────
    # Credentials have no defaults. A source file that carries a working
    # password is a password that ends up in every clone, branch and archive of
    # this repository — the history scan for this release found exactly that
    # (backend/core/config.py and a deleted docker-compose.yml). Set DB_PASSWORD
    # in .env; production startup refuses to continue without it.
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "kisanmitra"
    db_user: str = "kisanmitra_user"
    db_password: str = ""
    # Every SQL statement plus its bound parameters goes to stdout when this is
    # on. That used to be implied by APP_ENV=development, which meant a routine
    # dev run printed farmer phone numbers, declarations and any credential that
    # happened to sit in an error string. Opt in explicitly instead.
    db_sql_echo: bool = False
    # Connection pool per worker process. The deployment must satisfy:
    #   (db_pool_size + db_max_overflow) x workers per container x replicas
    #   < postgres max_connections (200 in docker-compose.production.yml)
    db_pool_size: int = 10
    db_max_overflow: int = 20

    # Directory holding the cross-process fcntl lock file. In the production
    # compose stack this is a volume shared by both API replicas, so the lock
    # coordinates across containers, not just across workers of one container.
    # Falls back to the system temp directory when the path is not writable
    # (single-host development).
    lock_dir: str = Field(
        "/var/lib/kisanmitra/locks",
        validation_alias=AliasChoices("KISANMITRA_LOCK_DIR", "LOCK_DIR"),
    )
    # Rotating log file directory. Relative to CWD on a bare-metal install;
    # containers set LOG_DIR to a path the non-root appuser can write
    # (see deploy/docker/backend.Dockerfile). Falls back to the system temp
    # directory when the configured path is not creatable.
    log_dir: str = Field(
        "logs",
        validation_alias=AliasChoices("KISANMITRA_LOG_DIR", "LOG_DIR"),
    )
    # Directory holding the trained model artifacts (price_model.pkl,
    # encoders.pkl, model_metadata.json). They are git-ignored and never baked
    # into images, so servers bind-mount them and point MODEL_DIR there.
    # Empty means the repository default (<repo>/data/models).
    model_dir: str = ""

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
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: str = ""
    data_gov_api_key: str = ""

    # ── App ───────────────────────────────────────────────
    app_env: str = "development"
    app_port: int = 8000
    # JWT signing key. Empty by design: falling back to any value that appears
    # in this repository would let anyone forge an admin token.
    secret_key: str = ""
    cors_origins: str = "*"

    # ── Data freshness SLA ────────────────────────────────
    # AGMARKNET mandi records are published with an irregular lag. A spot price
    # older than this many days is reported as stale instead of being forecast
    # from and labelled as today's price.
    price_max_age_days: int = 3

    # ── AGMARKNET refresh ───────────────────────────────────
    # Scheduled incremental ingest, so the freshness SLA above is actually
    # satisfiable. Disable with REFRESH_ENABLED=false (e.g. tests, where no
    # background task should touch the live database).
    refresh_enabled: bool = True
    refresh_interval_hours: int = 6
    # How far back an incremental fetch reaches. The window deliberately
    # overlaps so late uploads and mandi corrections published after our last
    # run are still picked up; duplicates are absorbed by the upsert's
    # ON CONFLICT DO NOTHING.
    refresh_lookback_days: int = 10
    agmarknet_resource_id: str = "35985678-0d79-46b4-9ed6-6f13308a1d24"
    refresh_state: str = "Karnataka"



import hashlib
import logging
import re
logger = logging.getLogger("kisanmitra.config")

try:
    settings = Settings()
except Exception as e:
    logger.error(f"❌ Critical Configuration Error: Missing or invalid environment variables! Details: {e}")
    raise e

# Values that were committed to this repository and are therefore public.
# Stored as SHA-256 digests so the remediation check itself does not re-publish
# a credential: comparing a digest catches the leaked string without ever
# writing it back into source control.
_KNOWN_COMPROMISED_SHA256 = {
    # data.gov.in API key, hardcoded in scripts/fetch_*.py (commit 288ea0f).
    "data_gov_api_key":     "f7afa0417e2eb706b84bb1e7574acaea42f9515d6ad281fffa07d5d182cf87b8",
    # JWT signing secret, used as the fallback in backend/core/security.py.
    "secret_key":           "570dad43de1af4c925f92c16a68a50936da42b7dd6fdeb24850507a1199aac89",
    # The old source defaults, kept so a copy-paste from an old branch is caught.
    "secret_key_default":   "dbe59d40c4b4e52a8dbb1e953c69562fde3ce7c746f4cef2a1f0354c2ffb8726",
    "db_password":          "379fe318de59d4f908e5751609b667b750e1bfc600791a16277d849327b569e4",
    # The WHATSAPP_VERIFY_TOKEN value shipped as the documented example default.
    # Any deployment still using it is authenticating with a public string, so it
    # is rejected like the others. Stored as a digest for the same reason: writing
    # the literal here would republish the credential the hardening is removing.
    "whatsapp_verify_token": "1843e8787226c70977dc0cafd94d3fd42a603d235958254ee844f9fc5e9bdb80",
}


def is_known_compromised_secret(value: str) -> bool:
    """True when `value` is byte-identical to a credential this repo leaked."""
    if not value:
        return False
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    leaked = {v.lower() for v in _KNOWN_COMPROMISED_SHA256.values()}
    # Match against the whole leak set, not just this field's entry: an API key
    # reused as a signing key is still the leaked API key.
    return digest in leaked


def using_leaked_secret() -> bool:
    """
    True when the configured SECRET_KEY cannot be trusted as an authentication
    secret: absent, or byte-identical to a value this repository published.
    Endpoints that compare caller headers against it must refuse service rather
    than run a comparison that is meaningless.
    """
    return not settings.secret_key or is_known_compromised_secret(settings.secret_key)


# HTTP client libraries put the request URL into their exception strings, and
# several of our providers take their credential as a URL parameter. Any error
# text that reaches a log line, a database column or an API response therefore
# has to pass through redaction first.
_SECRET_PARAM_RE = re.compile(
    r"((?:api[-_]?key|access[-_]?token|secret|password|passwd|token)=)[^&\s\"']+",
    re.IGNORECASE,
)
# Below this length a "secret" is indistinguishable from ordinary content (a
# price, an id, a day of the month) and redacting it would corrupt the message.
_MIN_SECRET_REDACTION_LENGTH = 8


def secret_values() -> tuple[str, ...]:
    """The live credential strings, longest first so overlapping values redact fully."""
    raw = (
        settings.data_gov_api_key,
        settings.secret_key,
        settings.db_password,
        settings.whatsapp_token.get_secret_value(),
        settings.whatsapp_app_secret,
        settings.gemini_api_key.get_secret_value(),
    )
    return tuple(sorted({v for v in raw if v and len(v) >= _MIN_SECRET_REDACTION_LENGTH},
                        key=len, reverse=True))


def redact_secrets(message: str | None) -> str | None:
    """Strip credential parameters and known secret values out of `message`."""
    if not message:
        return message
    clean = _SECRET_PARAM_RE.sub(r"\1[REDACTED]", str(message))
    for secret in secret_values():
        if secret in clean:
            clean = clean.replace(secret, "[REDACTED]")
    return clean


def validate_production_settings(config: Settings) -> None:
    """Fail closed when production is configured with missing or known-unsafe secrets."""
    if config.app_env.lower() != "production":
        if not config.secret_key:
            logger.warning("SECRET_KEY is unset — admin token signing is disabled "
                           "until it is provided by the environment.")
        if not config.db_password:
            logger.warning("DB_PASSWORD is unset — database connections will fail. "
                           "Set it in .env; it is deliberately not hardcoded here.")
        return

    checks = (
        (bool(config.secret_key) and len(config.secret_key) >= 32
         and not is_known_compromised_secret(config.secret_key),
         "SECRET_KEY must be set to a unique random value of at least 32 characters "
         "that is not a previously leaked key."),
        (bool(config.db_password)
         and not is_known_compromised_secret(config.db_password),
         "DB_PASSWORD must be set to a non-default production credential."),
        (bool(config.whatsapp_verify_token)
         and not is_known_compromised_secret(config.whatsapp_verify_token),
         "WHATSAPP_VERIFY_TOKEN must be changed from the example default."),
        (bool(config.whatsapp_app_secret),
         "WHATSAPP_APP_SECRET must be set to enforce webhook signature verification."),
        ("*" not in [origin.strip() for origin in config.cors_origins.split(",")],
         "CORS_ORIGINS must list explicit trusted origins; wildcard is unsafe in production."),
        # A leaked credential is unsafe whether or not the refresh job runs:
        # the value is already burned, and REFRESH_ENABLED can be turned on
        # later without the operator noticing the key was never rotated. This
        # must not be gated on refresh_enabled, which is how a burned key was
        # previously accepted whenever the pipeline happened to be disabled.
        (not (config.data_gov_api_key
              and is_known_compromised_secret(config.data_gov_api_key)),
         "DATA_GOV_API_KEY is set to a previously leaked value; rotate it "
         "even if REFRESH_ENABLED is off."),
        # The refresh pipeline is useless without a key and would only log
        # failures, so a production deploy that enables it and omits the key is
        # a configuration error, not a runtime one.
        ((not config.refresh_enabled) or bool(config.data_gov_api_key),
         "DATA_GOV_API_KEY must be set while REFRESH_ENABLED is on."),
    )
    failures = [message for valid, message in checks if not valid]
    if failures:
        raise RuntimeError("Unsafe production configuration: " + " ".join(failures))


validate_production_settings(settings)

