from pathlib import Path
import sys

# Allow importing backend.core from the project root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.logging_config import setup_kisanmitra_logging
logger = setup_kisanmitra_logging("kisanmitra.ingestion")
