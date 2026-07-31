from __future__ import annotations

from copy import deepcopy

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_execution_result import (
    FFmpegExecutionResult,
    FFmpegExecutionStatus,
)
from src.models.ffmpeg_input import FFmpegInputPlan
from src.models.render_progress import RenderProgress


def build_command_plan() -> FFmpegCommandPlan:
    """Build a deterministic command plan for stability checks."""

    return FFmpegCommandPlan(
        executable="ffmpeg",
        input_plan=FFmpegInputPlan(
            bindings=[],
            input_count=0,
            video_input_count=0,
            audio_input_count=0,
        ),
        filter_complex=(
            "[0:v]null[video_final];"
            "[1:a]anull[audio_final]"
        ),
        video_output_label="video_final",
        audio_output_label="audio_final",
        output_file="outputs/final_video.mp4",
        arguments=[
            "-y",
            "-i",
            "video.mp4",
            "-i",
            "audio.wav",
            "-filter_complex",
            (
                "[0:v]null[video_final];"
                "[1:a]anull[audio_final]"
            ),
            "-map",
            "[video_final]",
            "-map",
            "[audio_final]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "outputs/final_video.mp4",
        ],
        metadata={
            "purpose": "stability_test",
            "container": "mp4",
        },
    )


def build_success_result() -> FFmpegExecutionResult:
    """Build a deterministic successful execution result."""

    progress = RenderProgress.completed(
        elapsed_seconds=1.25,
        processed_duration_seconds=5.0,
        total_duration_seconds=5.0,
        frame=150,
        fps=30.0,
        output_size_bytes=4096,
        metadata={
            "progress_state": "end",
        },
    )

    return FFmpegExecutionResult.succeeded(
        command=[
            "ffmpeg",
            "-i",
            "input.mp4",
            "output.mp4",
        ],
        output_file="output.mp4",
        output_size_bytes=4096,
        duration_seconds=5.0,
        elapsed_seconds=1.25,
        stdout="",
        stderr="encoding completed",
        progress=progress,
        metadata={
            "container": "mp4",
        },
    )


def build_failure_result() -> FFmpegExecutionResult:
    """Build a deterministic failed execution result."""

    progress = RenderProgress.failed(
        elapsed_seconds=0.75,
        progress_percent=40.0,
        processed_duration_seconds=2.0,
        total_duration_seconds=5.0,
        message="Synthetic FFmpeg failure.",
        metadata={
            "progress_state": "continue",
        },
    )

    stderr = "\n".join(
        f"diagnostic-line-{index}"
        for index in range(
            1,
            26,
        )
    )

    return FFmpegExecutionResult.failed(
        status=FFmpegExecutionStatus.FAILED,
        command=[
            "ffmpeg",
            "-i",
            "input.mp4",
            "output.mp4",
        ],
        exit_code=1,
        elapsed_seconds=0.75,
        stdout="",
        stderr=stderr,
        error_message="Synthetic FFmpeg failure.",
        progress=progress,
        metadata={
            "failure_stage": "ffmpeg_exit",
            "container": "mp4",
        },
    )


def test_command_property_is_deterministic() -> None:
    """Repeated command construction must return equal argv values."""

    plan = build_command_plan()

    first = plan.command
    second = plan.command
    third = plan.command

    assert first == second
    assert second == third

    assert first is not second

    print(
        "Deterministic command-property test passed."
    )


def test_command_preview_is_deterministic() -> None:
    """Repeated human-readable command previews must be identical."""

    plan = build_command_plan()

    first = plan.command_preview
    second = plan.command_preview
    third = plan.command_preview

    assert first == second
    assert second == third

    assert (
        "ffmpeg"
        in first
    )

    assert (
        "outputs/final_video.mp4"
        in first
    )

    print(
        "Deterministic command-preview test passed."
    )


def test_command_access_does_not_mutate_plan() -> None:
    """Reading derived command properties must not mutate the model."""

    plan = build_command_plan()

    before = deepcopy(
        plan.model_dump()
    )

    _ = plan.command
    _ = plan.command_preview
    _ = plan.command
    _ = plan.command_preview

    after = plan.model_dump()

    assert before == after

    print(
        "Command property non-mutation test passed."
    )


def test_command_serialization_is_stable() -> None:
    """Repeated serialization must produce equal model dictionaries."""

    plan = build_command_plan()

    first = plan.model_dump()
    second = plan.model_dump()

    assert first == second

    first_json = (
        plan.model_dump_json()
    )

    second_json = (
        plan.model_dump_json()
    )

    assert (
        first_json
        == second_json
    )

    restored = (
        FFmpegCommandPlan
        .model_validate_json(
            first_json
        )
    )

    assert restored == plan

    print(
        "Command serialization-stability test passed."
    )


def test_success_result_properties_are_idempotent() -> None:
    """Successful diagnostic properties must remain stable."""

    result = build_success_result()

    first_command_line = (
        result.command_line
    )

    first_summary = (
        result.diagnostic_summary
    )

    first_stderr_tail = (
        result.stderr_tail
    )

    for _ in range(5):
        assert (
            result.command_line
            == first_command_line
        )

        assert (
            result.diagnostic_summary
            == first_summary
        )

        assert (
            result.stderr_tail
            == first_stderr_tail
        )

        assert result.has_output is True
        assert result.has_stdout is False
        assert result.has_stderr is True
        assert result.failure_stage is None
        assert result.is_timeout is False
        assert result.is_cancelled is False

    print(
        "Successful result idempotency test passed."
    )


def test_failure_result_properties_are_idempotent() -> None:
    """Failure diagnostic properties must remain stable."""

    result = build_failure_result()

    first_command_line = (
        result.command_line
    )

    first_summary = (
        result.diagnostic_summary
    )

    first_stderr_tail = (
        result.stderr_tail
    )

    first_failure_stage = (
        result.failure_stage
    )

    for _ in range(5):
        assert (
            result.command_line
            == first_command_line
        )

        assert (
            result.diagnostic_summary
            == first_summary
        )

        assert (
            result.stderr_tail
            == first_stderr_tail
        )

        assert (
            result.failure_stage
            == first_failure_stage
        )

        assert result.has_output is False
        assert result.has_stdout is False
        assert result.has_stderr is True
        assert result.is_timeout is False
        assert result.is_cancelled is False

    assert (
        first_failure_stage
        == "ffmpeg_exit"
    )

    print(
        "Failed result idempotency test passed."
    )


def test_stderr_tail_is_deterministic() -> None:
    """Repeated stderr-tail extraction must return identical content."""

    result = build_failure_result()

    first = (
        result.stderr_tail
    )

    second = (
        result.stderr_tail
    )

    assert first == second

    lines = first.splitlines()

    assert len(lines) == 20

    assert (
        lines[0]
        == "diagnostic-line-6"
    )

    assert (
        lines[-1]
        == "diagnostic-line-25"
    )

    print(
        "Deterministic stderr-tail test passed."
    )


def test_result_serialization_is_stable() -> None:
    """Repeated execution-result serialization must remain identical."""

    result = build_failure_result()

    before = deepcopy(
        result.model_dump()
    )

    first = result.model_dump()
    second = result.model_dump()

    assert first == second

    first_json = (
        result.model_dump_json()
    )

    second_json = (
        result.model_dump_json()
    )

    assert (
        first_json
        == second_json
    )

    after = result.model_dump()

    assert before == after

    restored = (
        FFmpegExecutionResult
        .model_validate_json(
            first_json
        )
    )

    assert restored == result

    print(
        "Execution-result serialization test passed."
    )


def test_metadata_access_does_not_mutate_models() -> None:
    """Diagnostic and command properties must leave metadata untouched."""

    plan = build_command_plan()

    result = build_failure_result()

    original_plan_metadata = (
        deepcopy(
            plan.metadata
        )
    )

    original_result_metadata = (
        deepcopy(
            result.metadata
        )
    )

    for _ in range(5):
        _ = plan.command
        _ = plan.command_preview

        _ = result.command_line
        _ = result.failure_stage
        _ = result.stderr_tail
        _ = result.diagnostic_summary

    assert (
        plan.metadata
        == original_plan_metadata
    )

    assert (
        result.metadata
        == original_result_metadata
    )

    print(
        "Metadata non-mutation test passed."
    )


def test_two_equivalent_command_plans_are_equivalent() -> None:
    """Equivalent inputs must produce equivalent command specifications."""

    first = build_command_plan()
    second = build_command_plan()

    assert (
        first.command
        == second.command
    )

    assert (
        first.command_preview
        == second.command_preview
    )

    assert (
        first.arguments
        == second.arguments
    )

    assert (
        first.output_file
        == second.output_file
    )

    print(
        "Equivalent command-plan stability test passed."
    )


def test_two_equivalent_results_have_equal_diagnostics() -> None:
    """Equivalent results must expose equivalent derived diagnostics."""

    first = build_failure_result()
    second = build_failure_result()

    assert (
        first.command_line
        == second.command_line
    )

    assert (
        first.failure_stage
        == second.failure_stage
    )

    assert (
        first.stderr_tail
        == second.stderr_tail
    )

    assert (
        first.diagnostic_summary
        == second.diagnostic_summary
    )

    print(
        "Equivalent result-diagnostics test passed."
    )


def main() -> None:
    """Run Sprint 18.7C stability regression tests."""

    print()
    print(
        "Running FFmpeg Stability tests..."
    )
    print()

    test_command_property_is_deterministic()

    test_command_preview_is_deterministic()

    test_command_access_does_not_mutate_plan()

    test_command_serialization_is_stable()

    test_success_result_properties_are_idempotent()

    test_failure_result_properties_are_idempotent()

    test_stderr_tail_is_deterministic()

    test_result_serialization_is_stable()

    test_metadata_access_does_not_mutate_models()

    test_two_equivalent_command_plans_are_equivalent()

    test_two_equivalent_results_have_equal_diagnostics()

    print()
    print(
        "FFmpeg Stability test suite "
        "completed successfully."
    )


if __name__ == "__main__":
    main()