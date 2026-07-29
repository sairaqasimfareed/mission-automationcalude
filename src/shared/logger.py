import logging
from pathlib import Path

# Logs folder
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Log file
LOG_FILE = LOG_DIR / "mission.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE, encoding="utf-8"), logging.StreamHandler()],
)

logger = logging.getLogger("MissionAutomation")
