from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.browser.manual_signin_bootstrap import (
    find_real_chrome_executable,
    manual_sign_in_command,
)


def test_find_real_chrome_executable_prefers_path_lookup() -> None:
    with patch(
        "src.browser.manual_signin_bootstrap.shutil.which",
        return_value=r"C:\on\path\chrome.exe",
    ):
        assert find_real_chrome_executable() == r"C:\on\path\chrome.exe"


def test_find_real_chrome_executable_falls_back_to_common_paths() -> None:
    with (
        patch("src.browser.manual_signin_bootstrap.shutil.which", return_value=None),
        patch(
            "src.browser.manual_signin_bootstrap.Path.is_file",
            return_value=True,
        ),
    ):
        found = find_real_chrome_executable()

    assert found is not None
    assert found.endswith("chrome.exe")


def test_find_real_chrome_executable_returns_none_when_not_found() -> None:
    with (
        patch("src.browser.manual_signin_bootstrap.shutil.which", return_value=None),
        patch(
            "src.browser.manual_signin_bootstrap.Path.is_file",
            return_value=False,
        ),
    ):
        assert find_real_chrome_executable() is None


def test_manual_sign_in_command_includes_profile_dir_and_url() -> None:
    command = manual_sign_in_command(
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        Path("data/google_flow_profiles/flow.primary"),
        "https://flow.google.com",
    )

    assert '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"' in command
    assert '--user-data-dir="data\\google_flow_profiles\\flow.primary"' in command
    assert '"https://flow.google.com"' in command


def test_manual_sign_in_command_without_url() -> None:
    command = manual_sign_in_command(
        r"C:\chrome.exe", Path("data/google_flow_profiles/flow.primary")
    )

    assert "--no-first-run" in command
    assert "--no-default-browser-check" in command
