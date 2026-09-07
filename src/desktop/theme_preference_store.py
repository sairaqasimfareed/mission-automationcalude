from __future__ import annotations

import json
from pathlib import Path

from src.desktop.theme import ThemeMode

DEFAULT_THEME_PREFERENCE_PATH = Path("data/desktop_preferences.json")


class ThemePreferenceStore:
    """
    Persists the user's chosen theme preference (System/Light/Dark)
    across restarts.

    A small, standalone JSON file rather than QSettings (which writes
    to the Windows registry / a platform-specific location outside
    this project's own `data/` convention that every other piece of
    local desktop state already follows - `provider_profiles.json`,
    `data/checkpoints/`, `data/projects/`) - keeping every piece of
    this app's local state in one place a user can find, back up, or
    delete together, rather than introducing a second, OS-specific
    storage mechanism for one small preference.
    """

    def __init__(self, *, path: Path | None = None) -> None:
        self._path = path if path is not None else DEFAULT_THEME_PREFERENCE_PATH

    def load(self) -> ThemeMode:
        """
        Return the persisted preference.

        Falls back to `ThemeMode.SYSTEM` (this feature's own sensible
        default) if no preference was ever saved, or if the file is
        missing, unreadable, or corrupt - a bad or absent preferences
        file must never prevent the app from starting.
        """

        try:
            raw = self._path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return ThemeMode(data["theme_mode"])
        except (OSError, ValueError, KeyError):
            return ThemeMode.SYSTEM

    def save(self, mode: ThemeMode) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"theme_mode": mode.value}, indent=2),
            encoding="utf-8",
        )
