import logging
import os
from pathlib import Path


def resolve_log_dir(preferred: Path, fallback: Path | None = None) -> Path | None:
    """The folder logs can really be written to: next to the app when that works, else a per-user
    folder (an app installed under Program Files is read-only for a normal Windows user), else None
    - the app then logs to the console only instead of failing to start."""

    if fallback is None:
        local_app_data = os.environ.get("LOCALAPPDATA")
        fallback = (
            Path(local_app_data) / "MissionAutomation" / "logs"
            if local_app_data
            else None
        )

    for candidate in (preferred, fallback):
        if candidate is None:
            continue

        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("", encoding="utf-8")
            probe.unlink()

            return candidate
        except OSError:
            continue

    return None


# Logs folder
LOG_DIR = resolve_log_dir(Path("logs")) or Path("logs")

handlers: list[logging.Handler] = [logging.StreamHandler()]

# Log file
LOG_FILE = LOG_DIR / "mission.log"

try:
    handlers.insert(0, logging.FileHandler(LOG_FILE, encoding="utf-8"))
except OSError:
    # No writable folder anywhere: keep running, console only.
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=handlers,
)

logger = logging.getLogger("MissionAutomation")
