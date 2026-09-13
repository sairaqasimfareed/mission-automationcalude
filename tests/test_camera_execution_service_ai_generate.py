from __future__ import annotations

from typing import Any

from src.models.editing_directives import DirectiveIntensity
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline_item import VideoTimelineItem
from src.services.camera_execution_service import CameraExecutionService


def _reference(
    *, preset_id: str, directive_path: str, implementation: dict[str, Any] | None = None
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        implementation=dict(implementation or {}),
    )


def _blueprint(*, scene_number: int) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_reference(
            preset_id="genre.horror", directive_path="genre_preset_id"
        ),
        camera=ResolvedCameraInstruction(
            preset=_reference(
                preset_id="camera.slow_zoom_in",
                directive_path="camera.preset_id",
                implementation={
                    "motion": "zoom",
                    "direction": "in",
                    "default_start_scale": 1.0,
                    "default_end_scale": 1.08,
                },
            ),
            intensity=DirectiveIntensity.MEDIUM,
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_reference(
                preset_id="transition.cut",
                directive_path="transition_in.preset_id",
                implementation={"type": "cut"},
            ),
            duration_seconds=0.0,
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_reference(
                preset_id="transition.cut",
                directive_path="transition_out.preset_id",
                implementation={"type": "cut"},
            ),
            duration_seconds=0.0,
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=_reference(preset_id="music.none", directive_path="music.preset_id"),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=_reference(
                preset_id="subtitle.default", directive_path="subtitles.preset_id"
            ),
            enabled=False,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _item(*, scene_number: int, source_type: SceneSourceType) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=source_type,
        duration_seconds=8,
        local_file=f"assets/videos/scene_{scene_number:03}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=0.0,
        end_time_seconds=8.0,
        editing_blueprint=_blueprint(scene_number=scene_number),
    )


def test_ai_generated_clip_gets_a_static_camera_execution_despite_zoom_preset() -> None:
    service = CameraExecutionService()
    item = _item(scene_number=1, source_type=SceneSourceType.AI_GENERATE)

    execution = service.build_execution(item=item)

    assert execution.is_static is True
    assert execution.preset_id == "camera.none"
    assert execution.motion_type == "none"
    assert any("AI-generated" in warning for warning in execution.warnings)


def test_manual_upload_clip_still_gets_the_genre_zoom_preset() -> None:
    service = CameraExecutionService()
    item = _item(scene_number=1, source_type=SceneSourceType.MANUAL_UPLOAD)

    execution = service.build_execution(item=item)

    assert execution.is_static is False
    assert execution.is_zoom is True
    assert execution.preset_id == "camera.slow_zoom_in"


def test_stock_footage_clip_still_gets_the_genre_zoom_preset() -> None:
    service = CameraExecutionService()
    item = _item(scene_number=1, source_type=SceneSourceType.STOCK_FOOTAGE)

    execution = service.build_execution(item=item)

    assert execution.is_static is False
    assert execution.is_zoom is True


def test_ai_generated_static_execution_spans_the_full_scene() -> None:
    service = CameraExecutionService()
    item = _item(scene_number=1, source_type=SceneSourceType.AI_GENERATE)

    execution = service.build_execution(item=item)

    assert execution.start_time_seconds == 0.0
    assert execution.end_time_seconds == 8.0
    assert execution.duration_seconds == 8.0
    assert execution.local_start_offset_seconds == 0.0
    assert execution.local_end_offset_seconds == 8.0
