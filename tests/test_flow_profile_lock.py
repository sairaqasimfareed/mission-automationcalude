from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from src.browser.flow_profile_lock import (
    DEFAULT_STALE_LOCK_SECONDS,
    FlowProfileLock,
    FlowProfileLockError,
)


def test_acquire_creates_the_profile_directory_and_a_lock_file(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    lock = FlowProfileLock(profile_dir)

    lock.acquire()

    assert profile_dir.exists()
    assert lock.lock_path.exists()
    assert lock.is_locked()

    lock.release()


def test_release_removes_the_lock_file(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    lock = FlowProfileLock(profile_dir)
    lock.acquire()

    lock.release()

    assert not lock.lock_path.exists()
    assert not lock.is_locked()


def test_release_without_acquire_is_a_safe_no_op(tmp_path: Path) -> None:
    lock = FlowProfileLock(tmp_path / "flow.primary")

    lock.release()  # must not raise


def test_release_is_idempotent(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    lock = FlowProfileLock(profile_dir)
    lock.acquire()

    lock.release()
    lock.release()  # must not raise the second time


def test_acquire_is_idempotent_for_the_same_instance(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    lock = FlowProfileLock(profile_dir)

    lock.acquire()
    lock.acquire()  # must not raise or deadlock against itself

    lock.release()


def test_a_second_lock_on_the_same_profile_is_refused_while_live(
    tmp_path: Path,
) -> None:
    profile_dir = tmp_path / "flow.primary"
    first = FlowProfileLock(profile_dir)
    first.acquire()

    second = FlowProfileLock(profile_dir)

    with pytest.raises(FlowProfileLockError, match="already locked"):
        second.acquire()

    first.release()


def test_a_stale_lock_is_reclaimed(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    profile_dir.mkdir(parents=True)

    stale_lock_path = profile_dir / ".flow_profile.lock"
    stale_lock_path.write_text(
        json.dumps({"owner_pid": 999999, "acquired_at": time.time() - 10_000}),
        encoding="utf-8",
    )

    lock = FlowProfileLock(profile_dir, stale_after_seconds=60)
    lock.acquire()  # must not raise - the existing lock is stale

    assert lock.is_locked()

    lock.release()


def test_is_locked_is_false_when_no_lock_file_exists(tmp_path: Path) -> None:
    lock = FlowProfileLock(tmp_path / "flow.primary")

    assert lock.is_locked() is False


def test_a_corrupt_lock_file_is_treated_as_unlocked(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    profile_dir.mkdir(parents=True)
    (profile_dir / ".flow_profile.lock").write_text("not json", encoding="utf-8")

    lock = FlowProfileLock(profile_dir)

    assert lock.is_locked() is False
    lock.acquire()  # must not raise
    lock.release()


def test_lock_file_records_the_real_process_id(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    lock = FlowProfileLock(profile_dir)
    lock.acquire()

    payload = json.loads(lock.lock_path.read_text(encoding="utf-8"))

    assert payload["owner_pid"] == os.getpid()

    lock.release()


def test_context_manager_acquires_and_releases(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"

    with FlowProfileLock(profile_dir) as lock:
        assert lock.is_locked()

    assert not (profile_dir / ".flow_profile.lock").exists()


def test_default_stale_after_seconds_is_fifteen_minutes() -> None:
    assert DEFAULT_STALE_LOCK_SECONDS == 15 * 60
