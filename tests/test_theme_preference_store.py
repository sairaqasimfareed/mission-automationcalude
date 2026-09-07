from __future__ import annotations

from pathlib import Path

import pytest

from src.desktop.theme import ThemeMode
from src.desktop.theme_preference_store import ThemePreferenceStore


def test_load_returns_system_when_no_file_exists(tmp_path: Path) -> None:
    store = ThemePreferenceStore(path=tmp_path / "desktop_preferences.json")

    assert store.load() == ThemeMode.SYSTEM


@pytest.mark.parametrize("mode", list(ThemeMode))
def test_save_then_load_round_trips(tmp_path: Path, mode: ThemeMode) -> None:
    store = ThemePreferenceStore(path=tmp_path / "desktop_preferences.json")

    store.save(mode)

    assert store.load() == mode


def test_save_creates_missing_parent_directories(tmp_path: Path) -> None:
    store = ThemePreferenceStore(path=tmp_path / "nested" / "dir" / "prefs.json")

    store.save(ThemeMode.DARK)

    assert store.load() == ThemeMode.DARK


def test_load_falls_back_to_system_on_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "desktop_preferences.json"
    path.write_text("{not valid json", encoding="utf-8")

    store = ThemePreferenceStore(path=path)

    assert store.load() == ThemeMode.SYSTEM


def test_load_falls_back_to_system_on_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "desktop_preferences.json"
    path.write_text("{}", encoding="utf-8")

    store = ThemePreferenceStore(path=path)

    assert store.load() == ThemeMode.SYSTEM


def test_load_falls_back_to_system_on_unknown_value(tmp_path: Path) -> None:
    path = tmp_path / "desktop_preferences.json"
    path.write_text('{"theme_mode": "neon"}', encoding="utf-8")

    store = ThemePreferenceStore(path=path)

    assert store.load() == ThemeMode.SYSTEM


def test_a_second_save_overwrites_the_first(tmp_path: Path) -> None:
    store = ThemePreferenceStore(path=tmp_path / "desktop_preferences.json")

    store.save(ThemeMode.LIGHT)
    store.save(ThemeMode.DARK)

    assert store.load() == ThemeMode.DARK
