import logging
import logging.handlers
import tempfile
from pathlib import Path

from backend.core.config import redact_secrets, settings


class RedactingFormatter(logging.Formatter):
    """
    Formatter that scrubs credentials from the fully rendered record.

    Formatting the whole line (message AND traceback) rather than filtering the
    message is deliberate: `requests` failures put the data.gov.in key in the
    exception text, and `logger.exception()` renders that below the message, so
    a message-only filter would still write the key into logs/kisanmitra.log.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def setup_kisanmitra_logging(name: str = "kisanmitra"):
    """
    Configure handlers on the "kisanmitra" PARENT logger and return the logger
    `name` for the caller to use.

    Handlers used to be attached to "kisanmitra.api" specifically, so every
    other module logger (kisanmitra.scheduler, kisanmitra.data_refresh, …) had
    no handler above it and its records were silently dropped — an ingestion
    pipeline can run correctly and still be invisible in the logs. Attaching to
    the parent means all kisanmitra.* children propagate into the same file.
    """
    # Never let an unwritable log directory crash the process: containers run
    # as a non-root user and /app is root-owned, so honour LOG_DIR and fall
    # back to the system temp directory when creation fails.
    log_dir = Path(settings.log_dir)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        log_dir = Path(tempfile.gettempdir())
    log_file = log_dir / "kisanmitra.log"

    parent = logging.getLogger("kisanmitra")
    parent.setLevel(logging.INFO)

    # Prevent duplicate logs if already configured
    if not parent.hasHandlers():
        # 1. Rotating File Handler (10MB max per file, 5 backups)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5
        )
        file_format = RedactingFormatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_format)

        # 2. Console Handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(file_format)

        parent.addHandler(file_handler)
        parent.addHandler(console_handler)

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    return logger
