from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from src.services.ffmpeg_execution_service import (
    FFmpegExecutionService,
)


class FakeProcess:
    """
    Deterministic process double for termination hardening tests.

    Only the subprocess methods used by FFmpegExecutionService are
    implemented.
    """

    def __init__(
        self,
        *,
        initial_return_code: int | None = None,
        terminate_wait_times_out: bool = False,
        terminate_raises: bool = False,
        kill_raises: bool = False,
        kill_wait_times_out: bool = False,
    ) -> None:
        self.return_code = (
            initial_return_code
        )

        self.terminate_wait_times_out = (
            terminate_wait_times_out
        )

        self.terminate_raises = (
            terminate_raises
        )

        self.kill_raises = (
            kill_raises
        )

        self.kill_wait_times_out = (
            kill_wait_times_out
        )

        self.terminate_called = False
        self.kill_called = False
        self.wait_call_count = 0

    def poll(self) -> int | None:
        """Return current fake process state."""

        return self.return_code

    def terminate(self) -> None:
        """Simulate graceful termination."""

        self.terminate_called = True

        if self.terminate_raises:
            raise OSError(
                "Synthetic terminate failure."
            )

        if not self.terminate_wait_times_out:
            self.return_code = -15

    def kill(self) -> None:
        """Simulate forced termination."""

        self.kill_called = True

        if self.kill_raises:
            raise OSError(
                "Synthetic kill failure."
            )

        if not self.kill_wait_times_out:
            self.return_code = -9

    def wait(
        self,
        timeout: float | None = None,
    ) -> int:
        """Simulate bounded process waiting."""

        del timeout

        self.wait_call_count += 1

        if (
            self.terminate_called
            and not self.kill_called
            and self.terminate_wait_times_out
        ):
            raise subprocess.TimeoutExpired(
                cmd="fake-ffmpeg",
                timeout=0.1,
            )

        if (
            self.kill_called
            and self.kill_wait_times_out
        ):
            raise subprocess.TimeoutExpired(
                cmd="fake-ffmpeg",
                timeout=0.1,
            )

        if self.return_code is None:
            self.return_code = 0

        return self.return_code


def as_popen(
    process: FakeProcess,
) -> subprocess.Popen[str]:
    """
    Cast a deterministic fake process to the executor contract.

    Runtime behavior is supplied entirely by FakeProcess.
    """

    return cast(
        subprocess.Popen[str],
        process,
    )


def test_prepare_output_directory_creates_parent(
    root: Path,
) -> None:
    """Missing nested output directories must be created."""

    output_file = (
        root
        / "nested"
        / "renders"
        / "final.mp4"
    )

    assert (
        output_file.parent.exists()
        is False
    )

    FFmpegExecutionService._prepare_output_directory(
        output_file
    )

    assert (
        output_file.parent.exists()
        is True
    )

    assert (
        output_file.parent.is_dir()
        is True
    )

    print(
        "Output directory creation test passed."
    )


def test_stale_output_removed_when_overwrite_enabled(
    root: Path,
) -> None:
    """An old render must be removed before overwrite execution."""

    output_file = (
        root
        / "stale.mp4"
    )

    output_file.write_bytes(
        b"old-render"
    )

    assert output_file.exists()

    FFmpegExecutionService._cleanup_stale_output(
        output_path=output_file,
        overwrite_output=True,
    )

    assert (
        output_file.exists()
        is False
    )

    print(
        "Overwrite stale-output cleanup test passed."
    )


def test_existing_output_preserved_when_overwrite_disabled(
    root: Path,
) -> None:
    """Non-overwrite execution must not delete existing media."""

    output_file = (
        root
        / "preserved.mp4"
    )

    original_content = (
        b"existing-render"
    )

    output_file.write_bytes(
        original_content
    )

    FFmpegExecutionService._cleanup_stale_output(
        output_path=output_file,
        overwrite_output=False,
    )

    assert output_file.exists()

    assert (
        output_file.read_bytes()
        == original_content
    )

    print(
        "Non-overwrite output preservation test passed."
    )


def test_cleanup_missing_output_is_idempotent(
    root: Path,
) -> None:
    """Repeated cleanup of a missing output must remain safe."""

    output_file = (
        root
        / "does_not_exist.mp4"
    )

    FFmpegExecutionService._cleanup_stale_output(
        output_path=output_file,
        overwrite_output=True,
    )

    FFmpegExecutionService._cleanup_stale_output(
        output_path=output_file,
        overwrite_output=True,
    )

    assert (
        output_file.exists()
        is False
    )

    print(
        "Idempotent stale-output cleanup test passed."
    )


def test_directory_as_output_rejected(
    root: Path,
) -> None:
    """A directory can never be treated as the final media file."""

    output_directory = (
        root
        / "not_a_video.mp4"
    )

    output_directory.mkdir()

    try:
        FFmpegExecutionService._prepare_output_directory(
            output_directory
        )
    except ValueError as error:
        assert (
            "directory"
            in str(error).lower()
        )
    else:
        raise AssertionError(
            "Directory output path should "
            "have been rejected."
        )

    print(
        "Directory-as-output rejection test passed."
    )


def test_invalid_parent_path_rejected(
    root: Path,
) -> None:
    """An existing file cannot act as an output parent directory."""

    invalid_parent = (
        root
        / "parent_file"
    )

    invalid_parent.write_text(
        "not a directory",
        encoding="utf-8",
    )

    output_file = (
        invalid_parent
        / "final.mp4"
    )

    try:
        FFmpegExecutionService._prepare_output_directory(
            output_file
        )
    except ValueError as error:
        assert (
            "not a directory"
            in str(error).lower()
        )
    else:
        raise AssertionError(
            "Invalid output parent "
            "should have been rejected."
        )

    print(
        "Invalid output-parent test passed."
    )


def test_already_exited_process_requires_no_cleanup() -> None:
    """An already terminated process must not be touched."""

    process = FakeProcess(
        initial_return_code=0,
    )

    service = (
        FFmpegExecutionService()
    )

    service._terminate_process(
        as_popen(
            process
        )
    )

    assert (
        process.terminate_called
        is False
    )

    assert (
        process.kill_called
        is False
    )

    assert (
        process.wait_call_count
        == 0
    )

    print(
        "Already-exited process cleanup test passed."
    )


def test_graceful_termination() -> None:
    """A responsive process should stop without forced kill."""

    process = FakeProcess()

    service = (
        FFmpegExecutionService(
            terminate_grace_seconds=0.1,
        )
    )

    service._terminate_process(
        as_popen(
            process
        )
    )

    assert (
        process.terminate_called
        is True
    )

    assert (
        process.kill_called
        is False
    )

    assert (
        process.poll()
        is not None
    )

    print(
        "Graceful process termination test passed."
    )


def test_terminate_timeout_escalates_to_kill() -> None:
    """An unresponsive process must escalate from terminate to kill."""

    process = FakeProcess(
        terminate_wait_times_out=True,
    )

    service = (
        FFmpegExecutionService(
            terminate_grace_seconds=0.1,
        )
    )

    service._terminate_process(
        as_popen(
            process
        )
    )

    assert (
        process.terminate_called
        is True
    )

    assert (
        process.kill_called
        is True
    )

    assert (
        process.poll()
        is not None
    )

    assert (
        process.wait_call_count
        >= 2
    )

    print(
        "Terminate-to-kill escalation test passed."
    )


def test_terminate_error_escalates_to_kill() -> None:
    """
    An OS error during terminate must escalate to kill
    when the process remains alive.
    """

    process = FakeProcess(
        terminate_raises=True,
        terminate_wait_times_out=True,
    )

    service = (
        FFmpegExecutionService(
            terminate_grace_seconds=0.1,
        )
    )

    service._terminate_process(
        as_popen(
            process
        )
    )

    assert (
        process.terminate_called
        is True
    )

    assert (
        process.kill_called
        is True
    )

    assert (
        process.poll()
        is not None
    )

    print(
        "Terminate-error fallback test passed."
    )


def test_kill_failure_does_not_escape_cleanup() -> None:
    """
    Cleanup failures must be logged instead of masking the original
    render failure or cancellation.
    """

    process = FakeProcess(
        terminate_wait_times_out=True,
        kill_raises=True,
    )

    service = (
        FFmpegExecutionService(
            terminate_grace_seconds=0.1,
        )
    )

    service._terminate_process(
        as_popen(
            process
        )
    )

    assert (
        process.terminate_called
        is True
    )

    assert (
        process.kill_called
        is True
    )

    print(
        "Kill-failure isolation test passed."
    )


def run_output_safety_tests(
    root: Path,
) -> None:
    """Run hardening tests that require temporary filesystem state."""

    test_prepare_output_directory_creates_parent(
        root
    )

    test_stale_output_removed_when_overwrite_enabled(
        root
    )

    test_existing_output_preserved_when_overwrite_disabled(
        root
    )

    test_cleanup_missing_output_is_idempotent(
        root
    )

    test_directory_as_output_rejected(
        root
    )

    test_invalid_parent_path_rejected(
        root
    )


def run_process_cleanup_tests() -> None:
    """Run deterministic process lifecycle hardening tests."""

    test_already_exited_process_requires_no_cleanup()

    test_graceful_termination()

    test_terminate_timeout_escalates_to_kill()

    test_terminate_error_escalates_to_kill()

    test_kill_failure_does_not_escape_cleanup()


def main() -> None:
    """Run Sprint 18.7A hardening regression tests."""

    import tempfile

    print()
    print(
        "Running FFmpeg Execution Hardening tests..."
    )
    print()

    with tempfile.TemporaryDirectory(
        prefix="mission_ffmpeg_hardening_"
    ) as temporary_directory:
        root = Path(
            temporary_directory
        )

        run_output_safety_tests(
            root
        )

    run_process_cleanup_tests()

    print()
    print(
        "FFmpeg Execution Hardening test suite "
        "completed successfully."
    )


if __name__ == "__main__":
    main()