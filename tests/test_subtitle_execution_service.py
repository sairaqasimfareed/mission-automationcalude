from __future__ import annotations

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
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.subtitle_execution import (
    SubtitleExecutionPlan,
    SubtitleExecutionStatus,
    SubtitleTimingSource,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)
from src.models.voice_directives import (
    VoiceDirectiveSource,
)
from src.services.subtitle_execution_service import (
    SubtitleExecutionService,
)


def reference(
    *,
    preset_id: str,
    directive_path: str,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
        implementation={},
    )


def build_blueprint(
    *,
    scene_number: int,
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
            ),
        ),
        transition_in=(
            ResolvedTransitionInstruction(
                preset=reference(
                    preset_id="transition.cut",
                    directive_path=(
                        "transition_in.preset_id"
                    ),
                ),
                duration_seconds=0.0,
            )
        ),
        transition_out=(
            ResolvedTransitionInstruction(
                preset=reference(
                    preset_id="transition.cut",
                    directive_path=(
                        "transition_out.preset_id"
                    ),
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
                preset_id="subtitle.cinematic",
                directive_path=(
                    "subtitles.preset_id"
                ),
            ),
            enabled=True,
            burn_into_video=True,
            maximum_words_per_line=7,
        ),
        status=(
            BlueprintResolutionStatus.RESOLVED
        ),
    )


def build_item(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: int,
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=duration_seconds,
        prompt=f"Scene {scene_number}",
        local_file=(
            "assets/videos/"
            f"scene_{scene_number:03}.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=(
            start_time_seconds
        ),
        end_time_seconds=(
            start_time_seconds
            + duration_seconds
        ),
        editing_blueprint=(
            build_blueprint(
                scene_number=scene_number
            )
        ),
    )


def build_voice_blueprint(
    *,
    scene_number: int,
    narration: str,
    speech_duration: float,
) -> ResolvedVoiceBlueprint:
    return ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=(
            VoiceBlueprintResolutionStatus
            .RESOLVED
        ),
        profile=ResolvedVoiceProfileReference(
            requested_profile_id=(
                "voice.neutral_narrator"
            ),
            resolved_profile_id=(
                "voice.neutral_narrator"
            ),
            display_name=(
                "Neutral Narrator"
            ),
            found_exact_match=True,
        ),
        narration_text=narration,
        estimated_speech_duration_seconds=(
            speech_duration
        ),
        narration_word_count=len(
            narration.split()
        ),
        narration_character_count=len(
            narration
        ),
        source=(
            VoiceDirectiveSource.SYSTEM_DEFAULT
        ),
    )


service = SubtitleExecutionService()

item_1 = build_item(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=8,
)

item_2 = build_item(
    scene_number=2,
    start_time_seconds=8.0,
    duration_seconds=8,
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

voice_1 = build_voice_blueprint(
    scene_number=1,
    narration=(
        "The old bunker door slowly opened "
        "and nobody inside dared to move."
    ),
    speech_duration=8.0,
)

voice_2 = build_voice_blueprint(
    scene_number=2,
    narration=(
        "Then a distant explosion echoed "
        "through the underground corridor."
    ),
    speech_duration=7.5,
)

plan = service.build_plan(
    timeline,
    voice_blueprints=[
        voice_1,
        voice_2,
    ],
)

print(
    "Subtitle segments:",
    plan.segment_count,
)

print(
    "Render ready:",
    plan.is_render_ready,
)

assert isinstance(
    plan,
    SubtitleExecutionPlan,
)

assert plan.segment_count > 0
assert plan.scene_count == 2
assert plan.is_valid is True
assert plan.is_render_ready is True
assert (
    plan.ready_execution_count
    == plan.segment_count
)

assert (
    plan.estimated_segment_count
    == plan.segment_count
)

assert plan.precise_segment_count == 0

for execution in plan.executions:
    assert (
        execution.timing_source
        == SubtitleTimingSource.ESTIMATED
    )

    assert execution.word_count <= 7

    assert (
        execution.end_time_seconds
        > execution.start_time_seconds
    )


scene_1_segments = [
    execution
    for execution in plan.executions
    if execution.scene_number == 1
]

assert scene_1_segments

assert (
    scene_1_segments[0]
    .start_time_seconds
    == 0.0
)

assert (
    scene_1_segments[-1]
    .end_time_seconds
    <= 8.0
)


scene_2_segments = [
    execution
    for execution in plan.executions
    if execution.scene_number == 2
]

assert scene_2_segments

assert (
    scene_2_segments[0]
    .start_time_seconds
    >= 8.0
)

assert (
    scene_2_segments[-1]
    .end_time_seconds
    <= 16.0
)


summary = service.summary(
    plan
)

assert (
    summary["segment_count"]
    == plan.segment_count
)

assert (
    summary["is_render_ready"]
    is True
)


application_plan = service.build_plan(
    timeline,
    voice_blueprints=[
        voice_1,
        voice_2,
    ],
)

first_execution = (
    application_plan.executions[0]
)

applied = service.mark_applied(
    application_plan,
    execution_id=str(
        first_execution.id
    ),
    renderer="ffmpeg",
)

assert (
    applied.status
    == SubtitleExecutionStatus.APPLIED
)

assert (
    applied.metadata["renderer"]
    == "ffmpeg"
)


failure_plan = service.build_plan(
    timeline,
    voice_blueprints=[
        voice_1,
        voice_2,
    ],
)

failed = service.mark_failed(
    failure_plan,
    execution_id=str(
        failure_plan.executions[0].id
    ),
    error_message=(
        "Simulated subtitle failure."
    ),
)

assert (
    failed.status
    == SubtitleExecutionStatus.FAILED
)

assert failure_plan.is_valid is False
assert failure_plan.is_render_ready is False


try:
    service.build_plan(
        timeline,
        voice_blueprints=[
            voice_1,
        ],
    )
except ValueError:
    print(
        "Missing voice blueprint "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Missing voice blueprint should fail."
    )


serialized = (
    plan.model_dump_json()
)

restored = (
    SubtitleExecutionPlan
    .model_validate_json(
        serialized
    )
)

assert restored == plan


print(
    "Subtitle Execution Service tests "
    "completed successfully."
)