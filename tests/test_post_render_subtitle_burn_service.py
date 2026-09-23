"""
REQ-0, 2026-09-22: PostRenderSubtitleBurnService builds an
FFmpegCommandPlan by hand (mirroring ExportVariantRenderService's and
AudioMuxRenderService's own proven shape) - these tests verify the
real command structure without needing a real ffmpeg execution (that
real, end-to-end proof lives in
test_post_render_subtitle_burn_real_ffmpeg.py).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue
from src.models.ffmpeg_command import FFmpegCommandPlan
from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegResolvedConfig,
)
from src.services.post_render_subtitle_burn_service import (
    PostRenderSubtitleBurnService,
)


class _FakeCapabilityService:
    def resolve(self, config: FFmpegConfig | None = None) -> FFmpegResolvedConfig:
        return FFmpegResolvedConfig(
            config=config or FFmpegConfig(),
            capabilities=FFmpegCapabilities(
                ffmpeg_available=True,
                ffprobe_available=True,
                ffmpeg_path="ffmpeg",
                ffprobe_path="ffprobe",
                encoders={"libx264", "aac"},
            ),
            selected_video_codec="libx264",
            selected_audio_codec="aac",
        )


class _FakeExecutionService:
    def __init__(self) -> None:
        self.calls: list[tuple[FFmpegCommandPlan, float]] = []

    def execute(
        self,
        command_plan: FFmpegCommandPlan,
        *,
        total_duration_seconds: float,
        **_kwargs: object,
    ) -> object:
        self.calls.append((command_plan, total_duration_seconds))

        class _Result:
            success = True
            output_file = command_plan.output_file
            exit_code = 0
            elapsed_seconds = 0.1
            ffmpeg_command: list[str] = []
            error_message = None
            metadata: dict[str, object] = {}

        return _Result()


def _service() -> tuple[PostRenderSubtitleBurnService, _FakeExecutionService]:
    execution = _FakeExecutionService()
    service = PostRenderSubtitleBurnService(
        capability_service=_FakeCapabilityService(),  # type: ignore[arg-type]
        execution_service=execution,  # type: ignore[arg-type]
    )

    return service, execution


def test_one_drawtext_filter_per_cue_chained_in_order(tmp_path: Path) -> None:
    service, execution = _service()

    cues = [
        AbsoluteSubtitleCue(text="First line.", start_seconds=0.0, end_seconds=3.0),
        AbsoluteSubtitleCue(text="Second line.", start_seconds=3.0, end_seconds=6.0),
    ]

    service.burn(
        input_video_file="stage2_output.mp4",
        cues=cues,
        output_file=str(tmp_path) + "/out.mp4",
        video_duration_seconds=6.0,
    )

    assert len(execution.calls) == 1
    command_plan, duration = execution.calls[0]

    assert duration == 6.0
    assert command_plan.filter_complex.count("drawtext") == 2
    assert "[0:v]drawtext=" in command_plan.filter_complex
    assert "[video_final]" in command_plan.filter_complex
    assert "between(t,0,3)" in command_plan.filter_complex
    assert "between(t,3,6)" in command_plan.filter_complex


def test_audio_always_passes_through_unmodified(tmp_path: Path) -> None:
    service, execution = _service()

    service.burn(
        input_video_file="stage2_output.mp4",
        cues=[AbsoluteSubtitleCue(text="Hi.", start_seconds=0.0, end_seconds=2.0)],
        output_file=str(tmp_path) + "/out.mp4",
        video_duration_seconds=2.0,
    )

    command_plan, _duration = execution.calls[0]

    assert "-map" in command_plan.arguments
    assert "0:a" in command_plan.arguments
    assert "-c:a" in command_plan.arguments
    c_a_index = command_plan.arguments.index("-c:a")
    assert command_plan.arguments[c_a_index + 1] == "copy"


def test_rejects_empty_cues() -> None:
    service, _execution = _service()

    with pytest.raises(ValueError, match="at least one cue"):
        service.burn(
            input_video_file="stage2_output.mp4",
            cues=[],
            output_file="out.mp4",
            video_duration_seconds=6.0,
        )


def test_rejects_non_positive_duration() -> None:
    service, _execution = _service()

    with pytest.raises(ValueError, match="positive video duration"):
        service.burn(
            input_video_file="stage2_output.mp4",
            cues=[AbsoluteSubtitleCue(text="Hi.", start_seconds=0.0, end_seconds=2.0)],
            output_file="out.mp4",
            video_duration_seconds=0.0,
        )


def test_rejects_empty_output_file() -> None:
    service, _execution = _service()

    with pytest.raises(ValueError, match="output file cannot be empty"):
        service.burn(
            input_video_file="stage2_output.mp4",
            cues=[AbsoluteSubtitleCue(text="Hi.", start_seconds=0.0, end_seconds=2.0)],
            output_file="   ",
            video_duration_seconds=6.0,
        )
