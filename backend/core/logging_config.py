import logging
import logging.handlers
from pathlib import Path

def setup_kisanmitra_logging(name: str):
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "kisanmitra.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Prevent duplicate logs if already configured
    if logger.hasHandlers():
        return logger

    # 1. Rotating File Handler (10MB max per file, 5 backups)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10*1024*1024, backupCount=5
    )
    file_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    file_handler.setFormatter(file_format)

    # 2. Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(file_format)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger
