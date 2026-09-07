from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# GF-2/section 10, "Profile ownership": "A persistent browser profile
# must have controlled ownership... safe acquisition, safe release,
# process shutdown cleanup, stale-lock recovery where safe." A
# Chromium user-data directory can only ever be opened by one live
# process at a time - two workers racing to open the same profile
# would corrupt it, not just error out cleanly.

# How long an unreleased lock is trusted to still represent a live
# process. Deliberately age-based rather than a cross-platform PID-
# liveness check (os.kill(pid, 0) does not mean the same thing on
# Windows as on POSIX) - simple, honest, and matches this codebase's
# own preference for the least surprising mechanism that satisfies the
# actual requirement, not the most sophisticated one available.
DEFAULT_STALE_LOCK_SECONDS = 15 * 60


class FlowProfileLockError(RuntimeError):
    """Raised when a profile is already locked by another live owner."""


@dataclass(frozen=True)
class FlowProfileLockInfo:
    owner_pid: int
    acquired_at: float


class FlowProfileLock:
    """
    A simple file-based mutex for one Google Flow account's persistent
    browser profile directory.

    Not a distributed lock, not reentrant, and not safe against a
    genuinely concurrent acquire from two threads in the same process
    at the exact same instant (callers are expected to serialize
    through FlowBrowserWorker's own single-worker-thread boundary for
    that) - this exists specifically to prevent two separate Mission
    Automation *processes* from opening the same Chromium profile at
    once, which Playwright itself does not guard against.
    """

    def __init__(
        self,
        profile_directory: Path,
        *,
        stale_after_seconds: float = DEFAULT_STALE_LOCK_SECONDS,
    ) -> None:
        self.profile_directory = profile_directory
        self.stale_after_seconds = stale_after_seconds
        self._lock_path = profile_directory / ".flow_profile.lock"
        self._held = False

    @property
    def lock_path(self) -> Path:
        return self._lock_path

    def is_locked(self) -> bool:
        """Whether a live (non-stale) lock currently exists."""

        info = self._read_lock()

        if info is None:
            return False

        return not self._is_stale(info)

    def acquire(self) -> None:
        """
        Acquire the lock, reclaiming a stale one if found.

        Raises FlowProfileLockError if a live lock already exists and
        belongs to a different owner than this instance already holds.
        """

        if self._held:
            return

        existing = self._read_lock()

        if existing is not None and not self._is_stale(existing):
            raise FlowProfileLockError(
                f"Google Flow profile at {self.profile_directory} is "
                f"already locked by pid={existing.owner_pid} "
                f"(acquired {time.time() - existing.acquired_at:.0f}s ago)."
            )

        self.profile_directory.mkdir(parents=True, exist_ok=True)
        self._write_lock()
        self._held = True

    def release(self) -> None:
        """
        Release the lock if this instance holds it.

        Safe to call more than once, and safe to call on a lock this
        instance never actually acquired (a no-op) - process shutdown
        cleanup must never raise.
        """

        if not self._held:
            return

        try:
            self._lock_path.unlink(missing_ok=True)
        finally:
            self._held = False

    def __enter__(self) -> FlowProfileLock:
        self.acquire()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.release()

    def _is_stale(self, info: FlowProfileLockInfo) -> bool:
        return (time.time() - info.acquired_at) > self.stale_after_seconds

    def _read_lock(self) -> FlowProfileLockInfo | None:
        if not self._lock_path.exists():
            return None

        try:
            payload = json.loads(self._lock_path.read_text(encoding="utf-8"))

            return FlowProfileLockInfo(
                owner_pid=int(payload["owner_pid"]),
                acquired_at=float(payload["acquired_at"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            # An unreadable/corrupt lock file is treated as no lock at
            # all rather than raising - a corrupt lock must never
            # permanently block a profile from ever being usable
            # again.
            return None

    def _write_lock(self) -> None:
        payload = {
            "owner_pid": os.getpid(),
            "acquired_at": time.time(),
        }
        self._lock_path.write_text(json.dumps(payload), encoding="utf-8")
