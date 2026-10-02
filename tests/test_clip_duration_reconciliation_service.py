from __future__ import annotations

from pathlib import Path

import pytest

from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.scene import Scene, SceneStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.services.clip_duration_reconciliation_service import (
    ClipDurationReconciliationService,
)
from src.services.frame_extraction_service import FrameExtractionService


def _scene(
    scene_number: int,
    *,
    real_narration_duration_seconds: float | None,
) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration=f"Narration for scene {scene_number}.",
        visual_prompt=f"Visual prompt for scene {scene_number}.",
        estimated_duration_seconds=8,
        status=SceneStatus.READY,
        real_narration_duration_seconds=real_narration_duration_seconds,
    )


def _clip(
    scene_number: int,
    *,
    duration_seconds: int,
    source_type: SceneSourceType = SceneSourceType.STOCK_FOOTAGE,
    local_file: str | None = "clip.mp4",
) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=source_type,
        duration_seconds=duration_seconds,
        local_file=local_file,
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def _real_video_file(tmp_path: Path) -> Path:
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"fake-real-video-bytes")
    return path


def _frame_extraction_service(
    tmp_path: Path,
) -> tuple[FrameExtractionService, list[list[str]]]:
    received_commands: list[list[str]] = []

    def runner(command: list[str]) -> None:
        received_commands.append(command)
        output_path = command[-1]
        input_path = command[command.index("-i") + 1]
        Path(output_path).write_bytes(f"fake-output-for-{input_path}".encode())

    return FrameExtractionService(runner=runner), received_commands


def test_a_clip_within_tolerance_is_left_unchanged(tmp_path: Path) -> None:
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=8.0)
    clip = _clip(1, duration_seconds=8)

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.warnings == []
    assert result.errors == []
    assert commands == []


def test_a_clip_longer_than_narration_is_trimmed(tmp_path: Path) -> None:
    real_file = _real_video_file(tmp_path)
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=7.0)
    clip = _clip(1, duration_seconds=12, local_file=str(real_file))

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert len(commands) == 1
    trimmed = result.clips[0]
    assert trimmed.duration_seconds == 7
    assert trimmed.local_file != clip.local_file
    assert trimmed.local_file is not None
    assert Path(trimmed.local_file).exists()
    assert trimmed.checksum is not None
    assert result.warnings == []
    assert result.errors == []


def test_a_trim_failure_keeps_the_untrimmed_clip(tmp_path: Path) -> None:
    real_file = _real_video_file(tmp_path)

    def failing_runner(command: list[str]) -> None:
        raise RuntimeError("ffmpeg exploded")

    frame_extraction = FrameExtractionService(runner=failing_runner)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=7.0)
    clip = _clip(1, duration_seconds=12, local_file=str(real_file))

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.warnings == []
    assert result.errors == []


def test_a_mild_shortfall_produces_a_warning_not_an_error(tmp_path: Path) -> None:
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=8.0)
    clip = _clip(1, duration_seconds=7)

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.errors == []
    assert len(result.warnings) == 1
    assert "Scene 1" in result.warnings[0]
    assert commands == []


def test_a_severe_shortfall_produces_a_blocking_error(tmp_path: Path) -> None:
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=10.0)
    clip = _clip(1, duration_seconds=3)

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.warnings == []
    assert len(result.errors) == 1
    assert "Scene 1" in result.errors[0]
    assert commands == []


def test_ai_generated_clips_are_never_reconciled(tmp_path: Path) -> None:
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=3.0)
    clip = _clip(1, duration_seconds=10, source_type=SceneSourceType.AI_GENERATE)

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.warnings == []
    assert result.errors == []
    assert commands == []


def test_a_scene_with_no_real_narration_duration_is_skipped(tmp_path: Path) -> None:
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=None)
    clip = _clip(1, duration_seconds=30)

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.warnings == []
    assert result.errors == []
    assert commands == []


def test_a_clip_with_no_matching_scene_is_skipped(tmp_path: Path) -> None:
    frame_extraction, commands = _frame_extraction_service(tmp_path)
    service = ClipDurationReconciliationService(
        frame_extraction_service=frame_extraction
    )

    scene = _scene(1, real_narration_duration_seconds=8.0)
    clip = _clip(2, duration_seconds=30)

    result = service.reconcile(scenes=[scene], clips=[clip])

    assert result.clips == [clip]
    assert result.warnings == []
    assert result.errors == []
    assert commands == []


def test_negative_tolerance_is_rejected() -> None:
    with pytest.raises(ValueError):
        ClipDurationReconciliationService(tolerance_seconds=-1.0)


def test_severe_shortfall_ratio_out_of_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        ClipDurationReconciliationService(severe_shortfall_ratio=0.0)

    with pytest.raises(ValueError):
        ClipDurationReconciliationService(severe_shortfall_ratio=1.5)
