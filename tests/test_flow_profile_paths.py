from __future__ import annotations

from pathlib import Path

import pytest

from src.browser.flow_profile_paths import UnsafeProfileIdError, profile_directory


def test_profile_directory_joins_root_and_id(tmp_path: Path) -> None:
    directory = profile_directory("flow.primary", root=tmp_path)

    assert directory == tmp_path / "flow.primary"


def test_profile_directory_uses_the_default_root_by_default() -> None:
    directory = profile_directory("flow.primary")

    assert directory.name == "flow.primary"
    assert directory.parent.name == "google_flow_profiles"


@pytest.mark.parametrize("bad_id", ["", "   ", ".", "..", "../escape", "a/b", "a\\b"])
def test_profile_directory_rejects_unsafe_ids(tmp_path: Path, bad_id: str) -> None:
    with pytest.raises(UnsafeProfileIdError):
        profile_directory(bad_id, root=tmp_path)


def test_profile_directory_allows_dots_dashes_and_underscores(tmp_path: Path) -> None:
    directory = profile_directory("flow.primary-account_1", root=tmp_path)

    assert directory.name == "flow.primary-account_1"


def test_profile_directory_strips_surrounding_whitespace(tmp_path: Path) -> None:
    directory = profile_directory("  flow.primary  ", root=tmp_path)

    assert directory.name == "flow.primary"
