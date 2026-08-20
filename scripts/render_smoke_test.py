from __future__ import annotations

from pathlib import Path

from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_config import (
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegVideoCodec,
)
from src.models.ffmpeg_input import FFmpegInputPlan
from src.models.render_progress import RenderProgress
from src.services.ffmpeg_capability_service import (
    FFmpegCapabilityService,
)
from src.services.ffmpeg_execution_service import (
    FFmpegExecutionService,
)

OUTPUT_FILE = Path("outputs/smoke/ffmpeg_execution_smoke.mp4")


def report_progress(
    progress: RenderProgress,
) -> None:
    """Print normalized render progress."""

    print(
        "Progress:",
        f"{progress.progress_percent:.2f}%",
        "| Status:",
        progress.status.value,
        "| Processed:",
        f"{progress.processed_duration_seconds:.3f}s",
        "| Elapsed:",
        f"{progress.elapsed_seconds:.3f}s",
    )


def main() -> None:
    """Run one real one-second render through the execution service."""

    capability_service = FFmpegCapabilityService()

    resolved_config = capability_service.resolve(
        FFmpegConfig(
            video_codec=(FFmpegVideoCodec.LIBX264),
            hardware_acceleration=(FFmpegHardwareAcceleration.NONE),
        )
    )

    ffmpeg_path = resolved_config.capabilities.ffmpeg_path

    if ffmpeg_path is None:
        raise RuntimeError("FFmpeg executable path " "could not be resolved.")

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()

    input_plan = FFmpegInputPlan(
        bindings=[],
        input_count=0,
        video_input_count=0,
        audio_input_count=0,
        metadata={
            "purpose": ("ffmpeg_execution_smoke_test"),
        },
    )

    filter_complex = "[0:v]null[video_final];" "[1:a]anull[audio_final]"

    command_plan = FFmpegCommandPlan(
        executable=ffmpeg_path,
        input_plan=input_plan,
        filter_complex=filter_complex,
        video_output_label="video_final",
        audio_output_label="audio_final",
        output_file=(OUTPUT_FILE.as_posix()),
        arguments=[
            "-y",
            "-f",
            "lavfi",
            "-i",
            ("color=" "c=blue:" "s=320x240:" "r=30:" "d=1"),
            "-f",
            "lavfi",
            "-i",
            ("anullsrc=" "channel_layout=stereo:" "sample_rate=48000"),
            "-filter_complex",
            filter_complex,
            "-map",
            "[video_final]",
            "-map",
            "[audio_final]",
            "-t",
            "1",
            "-c:v",
            resolved_config.selected_video_codec,
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            resolved_config.selected_audio_codec,
            "-b:a",
            "128k",
            OUTPUT_FILE.as_posix(),
        ],
        metadata={
            "purpose": ("ffmpeg_execution_smoke_test"),
        },
    )

    print()
    print(
        "FFmpeg executable:",
        ffmpeg_path,
    )

    print(
        "Video codec:",
        resolved_config.selected_video_codec,
    )

    print(
        "Audio codec:",
        resolved_config.selected_audio_codec,
    )

    print()
    print("Starting real FFmpeg smoke render...")
    print()

    execution_service = FFmpegExecutionService(
        default_timeout_seconds=30.0,
    )

    result = execution_service.execute(
        command_plan,
        total_duration_seconds=1.0,
        timeout_seconds=30.0,
        progress_callback=report_progress,
    )

    print()
    print(
        "Execution status:",
        result.status.value,
    )

    print(
        "Success:",
        result.success,
    )

    print(
        "Exit code:",
        result.exit_code,
    )

    print(
        "Elapsed:",
        f"{result.elapsed_seconds:.3f}s",
    )

    print(
        "Output:",
        result.output_file,
    )

    print(
        "Output exists:",
        result.output_exists,
    )

    print(
        "Output size:",
        result.output_size_bytes,
    )

    if result.error_message:
        print(
            "Error:",
            result.error_message,
        )

    if result.stderr:
        print()
        print("FFmpeg stderr tail:")

        stderr_lines = result.stderr.splitlines()

        for line in stderr_lines[-10:]:
            print(line)

    assert result.success is True

    assert result.exit_code == 0

    assert result.output_exists is True

    assert result.has_output is True

    assert result.output_file is not None

    assert OUTPUT_FILE.exists()

    assert OUTPUT_FILE.is_file()

    assert OUTPUT_FILE.stat().st_size > 0

    assert result.progress.progress_percent == 100.0

    assert result.progress.is_successful_terminal is True

    print()
    print("FFmpeg Execution Service " "real smoke test completed " "successfully.")


if __name__ == "__main__":
    main()
