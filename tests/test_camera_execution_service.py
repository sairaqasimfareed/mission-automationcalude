from __future__ import annotations

from typing import Any

from src.models.camera_execution import (
    CameraExecutionPlan,
    CameraExecutionStatus,
)
from src.models.editing_directives import (
    DirectiveIntensity,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.services.camera_execution_service import (
    CameraExecutionService,
)


def reference(
    *,
    preset_id: str,
    directive_path: str,
    implementation: dict[str, Any] | None = None,
    used_fallback: bool = False,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=(not used_fallback),
        used_fallback=used_fallback,
        implementation=dict(implementation or {}),
    )


def build_blueprint(
    *,
    scene_number: int,
    camera_preset_id: str,
    camera_implementation: dict[str, Any],
    start_offset_seconds: float = 0.0,
    end_offset_seconds: float | None = None,
    zoom_start: float | None = None,
    zoom_end: float | None = None,
    used_fallback: bool = False,
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=reference(
            preset_id="genre.default",
            directive_path="genre_preset_id",
        ),
        camera=ResolvedCameraInstruction(
            preset=reference(
                preset_id=camera_preset_id,
                directive_path="camera.preset_id",
                implementation=(camera_implementation),
                used_fallback=(used_fallback),
            ),
            intensity=(DirectiveIntensity.MEDIUM),
            start_offset_seconds=(start_offset_seconds),
            end_offset_seconds=(end_offset_seconds),
            zoom_start=zoom_start,
            zoom_end=zoom_end,
        ),
        transition_in=(
            ResolvedTransitionInstruction(
                preset=reference(
                    preset_id="transition.cut",
                    directive_path=("transition_in.preset_id"),
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
            )
        ),
        transition_out=(
            ResolvedTransitionInstruction(
                preset=reference(
                    preset_id="transition.cut",
                    directive_path=("transition_out.preset_id"),
                    implementation={
                        "type": "cut",
                    },
                ),
                duration_seconds=0.0,
            )
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=reference(
                preset_id="music.none",
                directive_path="music.preset_id",
            ),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=reference(
                preset_id="subtitle.default",
                directive_path=("subtitles.preset_id"),
            ),
            enabled=False,
            burn_into_video=False,
        ),
        status=(BlueprintResolutionStatus.RESOLVED),
    )


def build_item(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: int,
    blueprint: ResolvedSceneEditingBlueprint,
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=(SceneSourceType.MANUAL_UPLOAD),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        local_file=("assets/videos/" f"scene_{scene_number:03}.mp4"),
        source_status=(SceneSourceStatus.READY),
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=(start_time_seconds),
        end_time_seconds=(start_time_seconds + duration_seconds),
        editing_blueprint=blueprint,
    )


service = CameraExecutionService()


static_blueprint = build_blueprint(
    scene_number=1,
    camera_preset_id="camera.none",
    camera_implementation={
        "motion": "none",
    },
)

zoom_blueprint = build_blueprint(
    scene_number=2,
    camera_preset_id=("camera.slow_zoom_in"),
    camera_implementation={
        "motion": "zoom",
        "direction": "in",
        "default_start_scale": 1.0,
        "default_end_scale": 1.08,
    },
)

item_1 = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=static_blueprint,
)

item_2 = build_item(
    scene_number=2,
    start_time_seconds=8.0,
    duration_seconds=7,
    blueprint=zoom_blueprint,
)

timeline = VideoTimeline(
    clips=[
        item_1.clip,
        item_2.clip,
    ],
    items=[
        item_1,
        item_2,
    ],
)

plan = service.build_plan(
    timeline,
)

print(
    "Camera executions:",
    plan.execution_count,
)

print(
    "Render ready:",
    plan.is_render_ready,
)

assert isinstance(
    plan,
    CameraExecutionPlan,
)

assert plan.execution_count == 2
assert plan.scene_count == 2
assert plan.static_execution_count == 1
assert plan.motion_execution_count == 1
assert plan.ready_execution_count == 2
assert plan.is_valid is True
assert plan.is_render_ready is True


static_execution = next(
    execution for execution in plan.executions if execution.scene_number == 1
)

assert static_execution.is_static is True
assert static_execution.motion_type == "none"
assert static_execution.start_time_seconds == 0.0
assert static_execution.end_time_seconds == 8.0


zoom_execution = next(
    execution for execution in plan.executions if execution.scene_number == 2
)

assert zoom_execution.is_zoom is True
assert zoom_execution.motion_type == "zoom"
assert zoom_execution.direction == "in"
assert zoom_execution.start_time_seconds == 8.0
assert zoom_execution.end_time_seconds == 15.0
assert zoom_execution.zoom_start == 1.0
assert zoom_execution.zoom_end == 1.08


partial_blueprint = build_blueprint(
    scene_number=1,
    camera_preset_id=("camera.slow_zoom_in"),
    camera_implementation={
        "motion": "zoom",
        "direction": "in",
        "default_start_scale": 1.0,
        "default_end_scale": 1.08,
    },
    start_offset_seconds=2.0,
    end_offset_seconds=6.0,
)

partial_item = build_item(
    scene_number=1,
    start_time_seconds=10.0,
    duration_seconds=8,
    blueprint=partial_blueprint,
)

partial_execution = service.build_execution(
    item=partial_item,
)

assert partial_execution.start_time_seconds == 12.0

assert partial_execution.end_time_seconds == 16.0

assert partial_execution.duration_seconds == 4.0

assert partial_execution.local_start_offset_seconds == 2.0

assert partial_execution.local_end_offset_seconds == 6.0


override_zoom_blueprint = build_blueprint(
    scene_number=1,
    camera_preset_id=("camera.slow_zoom_in"),
    camera_implementation={
        "motion": "zoom",
        "direction": "in",
        "default_start_scale": 1.0,
        "default_end_scale": 1.08,
    },
    zoom_start=1.02,
    zoom_end=1.15,
)

override_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=override_zoom_blueprint,
)

override_execution = service.build_execution(
    item=override_item,
)

assert override_execution.zoom_start == 1.02
assert override_execution.zoom_end == 1.15


motion_only_plan = service.build_plan(
    timeline,
    include_static=False,
)

assert motion_only_plan.execution_count == 1
assert motion_only_plan.static_execution_count == 0
assert motion_only_plan.motion_execution_count == 1
assert motion_only_plan.executions[0].scene_number == 2


fallback_blueprint = build_blueprint(
    scene_number=1,
    camera_preset_id=("camera.slow_zoom_in"),
    camera_implementation={
        "motion": "zoom",
        "direction": "in",
        "default_start_scale": 1.0,
        "default_end_scale": 1.08,
    },
    used_fallback=True,
)

fallback_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=fallback_blueprint,
)

fallback_plan = service.build_plan(
    VideoTimeline(
        clips=[
            fallback_item.clip,
        ],
        items=[
            fallback_item,
        ],
    ),
)

assert fallback_plan.warnings

assert any("fallback preset" in warning.lower() for warning in fallback_plan.warnings)


invalid_timing_blueprint = build_blueprint(
    scene_number=1,
    camera_preset_id="camera.none",
    camera_implementation={
        "motion": "none",
    },
    start_offset_seconds=7.0,
    end_offset_seconds=9.0,
)

invalid_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=invalid_timing_blueprint,
)

try:
    service.build_execution(
        item=invalid_item,
    )
except ValueError:
    print("Out-of-scene camera timing " "successfully blocked.")
else:
    raise AssertionError("Out-of-scene camera timing " "should fail.")


missing_scale_blueprint = build_blueprint(
    scene_number=1,
    camera_preset_id="camera.custom_zoom",
    camera_implementation={
        "motion": "zoom",
        "direction": "in",
    },
)

missing_scale_item = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    blueprint=missing_scale_blueprint,
)

try:
    service.build_execution(
        item=missing_scale_item,
    )
except ValueError:
    print("Missing zoom scale values " "successfully blocked.")
else:
    raise AssertionError("Zoom without scales should fail.")


summary = service.summary(plan)

assert summary["execution_count"] == 2
assert summary["static_execution_count"] == 1
assert summary["motion_execution_count"] == 1
assert summary["is_render_ready"] is True


application_plan = service.build_plan(
    timeline,
)

first_execution = application_plan.executions[0]

applied = service.mark_applied(
    application_plan,
    execution_id=str(first_execution.id),
    renderer="ffmpeg",
    renderer_metadata={
        "mode": "dry-run",
    },
)

assert applied.status == CameraExecutionStatus.APPLIED

assert applied.metadata["renderer"] == "ffmpeg"

assert application_plan.applied_count == 1


service.mark_all_applied(
    application_plan,
    renderer="ffmpeg",
)

assert application_plan.applied_count == application_plan.execution_count


failure_plan = service.build_plan(
    timeline,
)

failed = service.mark_failed(
    failure_plan,
    execution_id=str(failure_plan.executions[0].id),
    error_message=("Simulated camera renderer failure."),
    failure_metadata={
        "renderer": "ffmpeg",
    },
)

assert failed.status == CameraExecutionStatus.FAILED

assert failure_plan.failed_count == 1
assert failure_plan.is_valid is False
assert failure_plan.is_render_ready is False


try:
    service.build_plan(
        timeline,
        track_index=-1,
    )
except ValueError:
    print("Negative camera track index " "successfully blocked.")
else:
    raise AssertionError("Negative camera track index " "should fail.")


serialized = plan.model_dump_json()

restored = CameraExecutionPlan.model_validate_json(serialized)

assert restored == plan


print("Camera Execution Service tests " "completed successfully.")
