from __future__ import annotations

from typing import Any

from src.models.animation_execution import (
    AnimationExecutionPlan,
    AnimationExecutionStatus,
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
    ResolvedAnimationInstruction,
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
from src.services.animation_execution_service import (
    AnimationExecutionService,
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


def animation(
    *,
    preset_id: str,
    implementation: dict[str, Any],
    start_offset_seconds: float = 0.0,
    duration_seconds: float | None = None,
    enabled: bool = True,
    used_fallback: bool = False,
) -> ResolvedAnimationInstruction:
    return ResolvedAnimationInstruction(
        preset=reference(
            preset_id=preset_id,
            directive_path=("animations.preset_id"),
            implementation=implementation,
            used_fallback=used_fallback,
        ),
        intensity=DirectiveIntensity.MEDIUM,
        start_offset_seconds=(start_offset_seconds),
        duration_seconds=(duration_seconds),
        enabled=enabled,
    )


def blueprint(
    *,
    scene_number: int,
    animations: list[ResolvedAnimationInstruction],
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=reference(
            preset_id="genre.default",
            directive_path="genre_preset_id",
        ),
        camera=ResolvedCameraInstruction(
            preset=reference(
                preset_id="camera.none",
                directive_path="camera.preset_id",
                implementation={
                    "motion": "none",
                },
            ),
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
        animations=animations,
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


def item(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: int,
    animations: list[ResolvedAnimationInstruction],
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
        editing_blueprint=blueprint(
            scene_number=scene_number,
            animations=animations,
        ),
    )


service = AnimationExecutionService()


parallax = animation(
    preset_id="animation.slow_parallax",
    implementation={
        "animation": "parallax",
        "speed": "slow",
    },
)

subtitle_fade = animation(
    preset_id="animation.subtitle_fade",
    implementation={
        "animation": "fade",
        "target": "subtitle",
    },
    start_offset_seconds=2.0,
    duration_seconds=3.0,
)

item_1 = item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    animations=[
        parallax,
    ],
)

item_2 = item(
    scene_number=2,
    start_time_seconds=8.0,
    duration_seconds=7,
    animations=[
        subtitle_fade,
    ],
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
    "Animation executions:",
    plan.execution_count,
)

print(
    "Render ready:",
    plan.is_render_ready,
)

assert isinstance(
    plan,
    AnimationExecutionPlan,
)

assert plan.execution_count == 2
assert plan.active_execution_count == 2
assert plan.ready_execution_count == 2
assert plan.scene_count == 2
assert plan.is_valid is True
assert plan.is_render_ready is True


parallax_execution = next(
    execution for execution in plan.executions if execution.scene_number == 1
)

assert parallax_execution.animation_type == "parallax"

assert parallax_execution.start_time_seconds == 0.0

assert parallax_execution.end_time_seconds == 8.0

assert parallax_execution.duration_seconds == 8.0


fade_execution = next(
    execution for execution in plan.executions if execution.scene_number == 2
)

assert fade_execution.animation_type == "fade"
assert fade_execution.target == "subtitle"

assert fade_execution.start_time_seconds == 10.0

assert fade_execution.end_time_seconds == 13.0

assert fade_execution.duration_seconds == 3.0


disabled = animation(
    preset_id="animation.slow_parallax",
    implementation={
        "animation": "parallax",
    },
    enabled=False,
)

disabled_item = item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    animations=[
        disabled,
    ],
)

disabled_plan = service.build_plan(
    VideoTimeline(
        clips=[
            disabled_item.clip,
        ],
        items=[
            disabled_item,
        ],
    ),
)

assert disabled_plan.execution_count == 0
assert disabled_plan.is_valid is True
assert disabled_plan.is_render_ready is True


fallback = animation(
    preset_id="animation.slow_parallax",
    implementation={
        "animation": "parallax",
    },
    used_fallback=True,
)

fallback_item = item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    animations=[
        fallback,
    ],
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


invalid_animation = animation(
    preset_id="animation.slow_parallax",
    implementation={
        "animation": "parallax",
    },
    start_offset_seconds=7.0,
    duration_seconds=2.0,
)

invalid_item = item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
    animations=[
        invalid_animation,
    ],
)

try:
    service.build_plan(
        VideoTimeline(
            clips=[
                invalid_item.clip,
            ],
            items=[
                invalid_item,
            ],
        ),
    )
except ValueError:
    print("Out-of-scene animation " "successfully blocked.")
else:
    raise AssertionError("Animation beyond scene should fail.")


summary = service.summary(plan)

assert summary["execution_count"] == 2
assert summary["active_execution_count"] == 2
assert summary["is_render_ready"] is True


application_plan = service.build_plan(
    timeline,
)

applied = service.mark_applied(
    application_plan,
    execution_id=str(application_plan.executions[0].id),
    renderer="ffmpeg",
)

assert applied.status == AnimationExecutionStatus.APPLIED

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
    error_message=("Simulated animation failure."),
)

assert failed.status == AnimationExecutionStatus.FAILED

assert failure_plan.failed_count == 1
assert failure_plan.is_valid is False
assert failure_plan.is_render_ready is False


serialized = plan.model_dump_json()

restored = AnimationExecutionPlan.model_validate_json(serialized)

assert restored == plan


print("Animation Execution Service tests " "completed successfully.")
