from __future__ import annotations

import subprocess
import sys

import pytest
from playwright.sync_api import Error as PlaywrightError

from src.browser.chromium_bootstrap import (
    INTERNAL_PLAYWRIGHT_INSTALL_FLAG,
    _default_browsers_path,
    ensure_chromium_and_retry,
    install_chromium,
    is_missing_browser_error,
    run_playwright_install_entrypoint,
)

# Installer packaging: Chromium is not bundled with the app - the
# first time Google Flow browser automation is actually used on a
# freshly-installed machine, Playwright itself can raise this exact
# real error (documented, not guessed) rather than a genuine launch
# failure. These tests exercise the retry/install logic without ever
# running a real, multi-hundred-megabyte download - real evidence
# for a genuinely missing Chromium binary can only come from an
# actual clean-machine install, disclosed as untested here.
_REAL_MISSING_BROWSER_MESSAGE = (
    "BrowserType.launch: Executable doesn't exist at "
    "C:\\Users\\test\\AppData\\Local\\ms-playwright\\chromium-1234\\chrome-win64\\chrome.exe\n"
    "Looks like Playwright Test or Playwright was just installed or updated.\n"
    "Please run the following command to download new browsers:\n\n"
    "    playwright install\n"
)


def test_is_missing_browser_error_recognizes_the_real_playwright_message() -> None:
    assert (
        is_missing_browser_error(PlaywrightError(_REAL_MISSING_BROWSER_MESSAGE)) is True
    )


def test_is_missing_browser_error_does_not_misfire_on_an_unrelated_failure() -> None:
    assert (
        is_missing_browser_error(PlaywrightError("net::ERR_CONNECTION_RESET")) is False
    )


def test_ensure_chromium_and_retry_returns_directly_when_the_first_call_succeeds() -> (
    None
):
    calls: list[str] = []

    def _launch() -> str:
        calls.append("launch")
        return "browser"

    result = ensure_chromium_and_retry(_launch)

    assert result == "browser"
    assert calls == ["launch"]


def test_ensure_chromium_and_retry_installs_once_and_retries_on_a_missing_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    install_calls: list[str] = []

    def _launch() -> str:
        calls.append("launch")

        if len(calls) == 1:
            raise PlaywrightError(_REAL_MISSING_BROWSER_MESSAGE)

        return "browser"

    monkeypatch.setattr(
        "src.browser.chromium_bootstrap.install_chromium",
        lambda: install_calls.append("install"),
    )

    result = ensure_chromium_and_retry(_launch)

    assert result == "browser"
    assert calls == ["launch", "launch"]
    assert install_calls == ["install"]


def test_ensure_chromium_and_retry_never_installs_for_an_unrelated_failure() -> None:
    def _launch() -> str:
        raise PlaywrightError("net::ERR_CONNECTION_RESET")

    with pytest.raises(PlaywrightError, match="ERR_CONNECTION_RESET"):
        ensure_chromium_and_retry(_launch)


def test_ensure_chromium_and_retry_propagates_a_second_consecutive_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one retry is a real recovery attempt, not an infinite loop -
    if the freshly-installed browser STILL fails to launch, that's a
    genuine, different problem that must still surface."""

    calls: list[str] = []

    def _launch() -> str:
        calls.append("launch")
        raise PlaywrightError(_REAL_MISSING_BROWSER_MESSAGE)

    monkeypatch.setattr("src.browser.chromium_bootstrap.install_chromium", lambda: None)

    with pytest.raises(PlaywrightError, match="Executable doesn't exist"):
        ensure_chromium_and_retry(_launch)

    assert calls == ["launch", "launch"]


def test_install_chromium_uses_dash_m_playwright_when_not_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal (non-packaged) development run must invoke the real
    playwright CLI via "-m", exactly matching the documented, official
    "playwright install chromium" command."""

    monkeypatch.delattr("sys.frozen", raising=False)

    captured_command: list[str] = []

    class _FakeCompletedProcess:
        returncode = 0
        stderr = ""

    def _fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_command.extend(command)
        return _FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    install_chromium()

    assert captured_command == [
        sys.executable,
        "-m",
        "playwright",
        "install",
        "chromium",
    ]


def test_install_chromium_re_invokes_itself_when_frozen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frozen build's own sys.executable is the packaged .exe, not a
    real python.exe - it cannot take a plain "-m playwright" argument.
    It must re-invoke itself with the internal flag instead, which
    app.py's own entry point recognizes."""

    monkeypatch.setattr("sys.frozen", True, raising=False)

    captured_command: list[str] = []

    class _FakeCompletedProcess:
        returncode = 0
        stderr = ""

    def _fake_run(command: list[str], **kwargs: object) -> _FakeCompletedProcess:
        captured_command.extend(command)
        return _FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", _fake_run)

    install_chromium()

    assert captured_command == [
        sys.executable,
        INTERNAL_PLAYWRIGHT_INSTALL_FLAG,
        "chromium",
    ]


def test_install_chromium_raises_with_real_stderr_on_a_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr("sys.frozen", raising=False)

    class _FakeCompletedProcess:
        returncode = 1
        stderr = "no internet connection"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeCompletedProcess())

    with pytest.raises(RuntimeError, match="no internet connection"):
        install_chromium()


def test_run_playwright_install_entrypoint_sets_argv_and_calls_the_real_playwright_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verifies the exact real entry point (playwright.__main__.main,
    the same one the "playwright" CLI script itself uses) is called
    with the right argv - without actually running a real
    installation."""

    import playwright.__main__ as playwright_cli

    captured_argv: list[str] = []

    def _fake_main() -> None:
        captured_argv.extend(sys.argv)
        raise SystemExit(0)

    monkeypatch.setattr(playwright_cli, "main", _fake_main)

    original_argv = list(sys.argv)
    exit_code = run_playwright_install_entrypoint()

    assert exit_code == 0
    assert captured_argv == ["playwright", "install", "chromium"]
    # sys.argv must be restored, not left mutated for the rest of the
    # process (this only matters for a genuinely short-lived install
    # invocation, but the contract should hold regardless).
    assert sys.argv == original_argv


# --- PLAYWRIGHT_BROWSERS_PATH: the real, second bug found via the
# same live repro as the hang-then-error above. Playwright's own
# bundled/frozen driver does not use the standard, well-known
# %LOCALAPPDATA%\ms-playwright cache - it falls back to a "local"
# path relative to its own driver/package directory once PyInstaller
# has flattened that directory in a way that no longer looks like a
# normal npm install. Confirmed directly: a real, already-working
# Chromium install sat untouched at the real, standard location the
# whole time the app kept looking in the wrong, empty one. ---


def test_default_browsers_path_uses_the_real_localappdata_convention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")

    assert _default_browsers_path() == r"C:\Users\test\AppData\Local\ms-playwright"


def test_default_browsers_path_is_none_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\test\AppData\Local")

    assert _default_browsers_path() is None


def test_default_browsers_path_is_none_when_localappdata_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)

    assert _default_browsers_path() is None
