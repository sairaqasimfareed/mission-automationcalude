from __future__ import annotations

import shutil
from pathlib import Path

# GF-13/GF-17, real-world finding (2026-09-07): a human actually
# clicked "Check Connection"/"Open Login" against the real product and
# Google rejected sign-in outright - "Couldn't sign you in - This
# browser or app may not be secure" - from
# accounts.google.com/v3/signin/rejected, even with FlowBrowserWorker
# already using a real, visible (headless=False) window. This is
# Google's own long-standing policy of blocking OAuth/sign-in from
# browsers it detects as embedded or automated (it looks at signals
# Playwright's Chromium always sets when driven via CDP, e.g.
# navigator.webdriver=true and the --enable-automation switch/banner) -
# a well-established, publicly documented Google policy, not a bug in
# this adapter, not a selector problem, and not something a longer
# timeout or a different locator can fix.
#
# The correct, legitimate fix: never drive the actual Google sign-in
# step through Playwright at all. The human instead signs in using
# their own REAL, already-installed, non-automated Chrome, launched
# directly against the exact same on-disk profile directory
# (flow_profile_paths.profile_directory) that FlowBrowserWorker later
# reuses for Check Connection / real generation work. This is a normal,
# fully manual Chrome launch - no CDP, no --enable-automation, nothing
# this module does or could set counts as "automation" from Google's
# point of view - the human types their own password and completes
# any 2-step verification entirely inside that real Chrome window,
# outside this application's process and view, exactly as required by
# this initiative's hard "never type or see a credential" boundary.
#
# What is expected, but NOT yet proven against the real product: that
# the session Google establishes in that real Chrome window is still
# present when Playwright's Chromium later opens the very same
# user-data-dir for Check Connection. This follows from how Chromium-
# family profile directories store cookies/local storage on disk (a
# format shared across Chrome and Chromium builds), but it has not
# been confirmed by an actual human completing this exact bootstrap
# yet - see PROJECT_PROGRESS.md. If Google's automation detection also
# challenges plain navigation (not just the sign-in handshake) once
# Playwright's Chromium opens an already-authenticated profile, that
# would be a new, separate finding requiring further investigation -
# not assumed away here.

_COMMON_WINDOWS_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def find_real_chrome_executable() -> str | None:
    """
    Best-effort discovery of the user's own, already-installed Chrome
    executable - deliberately never Playwright's bundled Chromium,
    which is exactly the browser Google's sign-in flow rejects.

    Returns None (rather than guessing a path that might not exist)
    when nothing is found, so callers can fall back to telling the
    operator to point this at their own Chrome themselves instead of
    silently launching something wrong.
    """

    on_path = shutil.which("chrome") or shutil.which("chrome.exe")

    if on_path is not None:
        return on_path

    for candidate in _COMMON_WINDOWS_CHROME_PATHS:
        if Path(candidate).is_file():
            return candidate

    return None


def manual_sign_in_command(
    chrome_executable: str,
    profile_directory: Path,
    url: str | None = None,
) -> str:
    """
    Build the exact command line for launching a REAL (non-automated)
    Chrome window against one Google Flow account's persistent profile
    directory, for the operator to sign in manually - and, on request,
    to run again themselves if the automatic launch fails.

    --no-first-run/--no-default-browser-check only suppress Chrome's
    own first-run dialogs for a brand-new profile directory; neither
    is an automation flag and neither is anything Google's sign-in
    flow checks for.
    """

    parts = [
        f'"{chrome_executable}"',
        f'--user-data-dir="{profile_directory}"',
        "--no-first-run",
        "--no-default-browser-check",
    ]

    if url:
        parts.append(f'"{url}"')

    return " ".join(parts)
