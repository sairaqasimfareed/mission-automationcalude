from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

# Installer packaging decision (see PROJECT_PROGRESS.md's matching
# entry): Playwright's Chromium browser is NOT bundled with the
# installer - it's large (~150-300MB) and bundling it correctly
# inside a PyInstaller build is genuinely fragile. Instead, this app
# auto-installs it transparently the first time Google Flow browser
# automation is actually used (nothing else in this codebase ever
# touches Playwright), via the exact same real "playwright install
# chromium" mechanism the CLI itself uses - never a hand-rolled
# download.

# A frozen (PyInstaller) build's own sys.executable is
# MissionAutomation.exe, not a real python.exe - it does not
# understand a standard interpreter "-m module" flag the way a real
# Python distribution does, so "sys.executable -m playwright install
# chromium" only works in an ordinary (non-frozen) development
# environment. For a frozen build, this app re-invokes ITSELF with
# this internal flag; app.py's own entry point recognizes it and
# dispatches straight to run_playwright_install_entrypoint() before
# ever constructing a QApplication, then exits - never launching the
# real GUI for that invocation.
INTERNAL_PLAYWRIGHT_INSTALL_FLAG = "--internal-playwright-install"

_INSTALL_TIMEOUT_SECONDS = 900.0


def _default_browsers_path() -> str | None:
    """
    Real-world finding: Playwright's own Node driver decides where to
    install/look for browsers using ITS OWN heuristic (not documented
    anywhere this codebase found, only observed directly) - when the
    driver's own package directory doesn't look like a normal npm
    install (exactly the case once PyInstaller has copied it flat into
    `_internal/playwright/driver/package/`), it treats the browsers
    path as "local", i.e. `driver/package/local-browsers/`, instead of
    the standard, well-known `%LOCALAPPDATA%\\ms-playwright` every
    ordinary (non-frozen) Playwright install already uses - including
    this exact machine's own real, already-populated cache. A real
    install into that "local" path then genuinely works (confirmed
    directly), but only after paying for a full, unnecessary
    re-download, and - worse - if that download stalls or fails, the
    app is left looking in a directory that will never contain a
    browser THIS install already has, real evidence via a real
    Check Connection hang-then-error.

    Setting PLAYWRIGHT_BROWSERS_PATH explicitly removes the ambiguity
    entirely - Playwright's own documented, first-class override for
    exactly this. Windows-only (matches this app's own Windows-first
    environment); returns None on any other platform or if
    %LOCALAPPDATA% is somehow unset, letting Playwright fall back to
    its own default rather than pointing at a guessed, wrong path.
    """

    if sys.platform != "win32":
        return None

    local_app_data = os.environ.get("LOCALAPPDATA")

    if not local_app_data:
        return None

    return str(Path(local_app_data) / "ms-playwright")


# Applied at import time, once, for the whole process - every real
# Playwright launch in this codebase goes through FlowBrowserWorker,
# which imports this module before ever calling sync_playwright();
# install_chromium()'s own subprocess inherits the current process
# environment automatically. setdefault() only - an operator or CI
# environment that already set this explicitly is always respected
# as-is, never overridden.
_browsers_path = _default_browsers_path()

if _browsers_path is not None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _browsers_path)


def is_missing_browser_error(exc: Exception) -> bool:
    """
    Whether a Playwright error is the specific, documented "browser
    executable not installed yet" failure - Playwright's own real
    error text (not inferred/guessed) always contains this exact
    substring for that case, distinct from a genuine launch failure
    (a corrupt profile, a real crash, etc.) that must NOT trigger an
    install-and-retry loop.
    """

    return "Executable doesn't exist" in str(exc)


def install_chromium() -> None:
    """
    Run the real, official "playwright install chromium" command as a
    subprocess - never a hand-rolled download of Chromium itself.

    Raises RuntimeError with the real subprocess stderr on failure
    (no internet, disk full, etc.) - the caller decides how to surface
    that to the operator, this function never touches any GUI.
    """

    if getattr(sys, "frozen", False):
        command = [sys.executable, INTERNAL_PLAYWRIGHT_INSTALL_FLAG, "chromium"]
    else:
        command = [sys.executable, "-m", "playwright", "install", "chromium"]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=_INSTALL_TIMEOUT_SECONDS,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "playwright install chromium failed "
            f"(exit code {result.returncode}): {result.stderr.strip()}"
        )


def ensure_chromium_and_retry[T](launch: Callable[[], T]) -> T:
    """
    Call `launch` (a Playwright browser/context launch, e.g.
    `playwright.chromium.launch_persistent_context(...)`); if it fails
    specifically because Chromium isn't installed yet, install it once
    and retry exactly once. Any other failure - or a second,
    consecutive failure after a genuine install attempt - propagates
    unchanged rather than being silently retried forever.
    """

    try:
        return launch()
    except PlaywrightError as exc:
        if not is_missing_browser_error(exc):
            raise

        install_chromium()

        return launch()


def run_playwright_install_entrypoint() -> int:
    """
    Runs "playwright install chromium" in-process, for a frozen
    (PyInstaller) build re-invoked with INTERNAL_PLAYWRIGHT_INSTALL_FLAG
    (see this module's own docstring for why a frozen build needs
    this rather than a plain "-m playwright" subprocess call).

    playwright.__main__.main() is the exact same entry point the real
    "playwright" CLI script uses - it reads sys.argv itself and calls
    sys.exit() when done (a real click-based CLI command), which is
    why this must only ever run in a short-lived, dedicated process
    invocation (app.py's own entry point exits immediately after
    calling this) rather than inside the long-lived main GUI process.
    """

    import playwright.__main__ as playwright_cli

    original_argv = sys.argv
    sys.argv = ["playwright", "install", "chromium"]

    try:
        playwright_cli.main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.argv = original_argv

    return 0
