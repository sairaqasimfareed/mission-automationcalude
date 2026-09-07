from __future__ import annotations

import re
from pathlib import Path

# Matches this codebase's own convention for local storage roots
# (DEFAULT_MANUAL_UPLOAD_STORAGE_ROOT/DEFAULT_STOCK_STORAGE_ROOT in
# scene_asset_and_timeline_infrastructure_factory.py) - a plain
# relative directory under the app's own working data root, not a new
# OS-level user-data-directory convention.
DEFAULT_FLOW_PROFILES_ROOT = Path("data/google_flow_profiles")

# Deliberately conservative: letters, digits, dot, underscore, hyphen
# only. A profile_id becomes a literal directory name on disk - this
# is what stands between "arbitrary provider profile_id string" and a
# path-traversal or otherwise unsafe filesystem write.
_SAFE_PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


class UnsafeProfileIdError(ValueError):
    """Raised when a profile_id is not safe to use as a directory name."""


def profile_directory(
    profile_id: str,
    *,
    root: Path = DEFAULT_FLOW_PROFILES_ROOT,
) -> Path:
    """
    Return the persistent Chromium user-data directory for one Google
    Flow account profile.

    Does not create the directory - Playwright's own
    launch_persistent_context creates it on first use. Raises rather
    than silently sanitizing an unsafe profile_id, since silently
    rewriting it would make a profile's on-disk location unpredictable
    from its own id.
    """

    cleaned = profile_id.strip()

    if not cleaned:
        raise UnsafeProfileIdError("profile_id cannot be empty.")

    if cleaned in {".", ".."}:
        raise UnsafeProfileIdError(f"profile_id cannot be '{cleaned}'.")

    if not _SAFE_PROFILE_ID_PATTERN.match(cleaned):
        raise UnsafeProfileIdError(
            f"profile_id '{profile_id}' contains characters that are not "
            "safe to use as a directory name (only letters, digits, '.', "
            "'_', and '-' are allowed)."
        )

    return root / cleaned
