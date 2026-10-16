"""An app installed under Program Files cannot create ./logs for a normal Windows user; logging must fall
back to a per-user folder instead of stopping the app from starting (found on a second machine).
"""

from __future__ import annotations

from pathlib import Path

from src.shared.logger import resolve_log_dir


def test_a_writable_folder_next_to_the_app_is_used(tmp_path: Path) -> None:
    assert resolve_log_dir(tmp_path / "logs", tmp_path / "other") == tmp_path / "logs"


def test_an_unwritable_folder_falls_back_to_the_per_user_one(tmp_path: Path) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("a file where the folder should be", encoding="utf-8")

    assert resolve_log_dir(blocked / "logs", tmp_path / "user") == tmp_path / "user"


def test_with_no_writable_folder_it_returns_none_instead_of_raising(
    tmp_path: Path,
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("x", encoding="utf-8")

    assert resolve_log_dir(blocked / "a", blocked / "b") is None
