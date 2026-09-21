from __future__ import annotations

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
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    ResolvedVoiceProfileReference,
    VoiceBlueprintResolutionStatus,
)
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.models.voice_directives import VoiceDirectiveSource
from src.services.subtitle_execution_service import SubtitleExecutionService

_TRANSITION_DURATION_SECONDS = 1.0
_SCENE_DURATION_SECONDS = 8


def _reference(*, preset_id: str, directive_path: str) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
        implementation={},
    )


def _blueprint(*, scene_number: int) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_reference(
            preset_id="genre.default", directive_path="genre_preset_id"
        ),
        camera=ResolvedCameraInstruction(
            preset=_reference(preset_id="camera.none", directive_path="camera.id"),
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_reference(
                preset_id="transition.cross_dissolve",
                directive_path="transition_in.id",
            ),
            duration_seconds=_TRANSITION_DURATION_SECONDS,
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_reference(
                preset_id="transition.cross_dissolve",
                directive_path="transition_out.id",
            ),
            duration_seconds=_TRANSITION_DURATION_SECONDS,
        ),
        visual_effects=[],
        animations=[],
        music=ResolvedMusicInstruction(
            preset=_reference(preset_id="music.none", directive_path="music.id"),
            enabled=False,
        ),
        sound_effects=[],
        subtitles=ResolvedSubtitleInstruction(
            preset=_reference(
                preset_id="subtitle.cinematic", directive_path="subtitles.id"
            ),
            enabled=True,
            burn_into_video=True,
            maximum_words_per_line=7,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _item(*, scene_number: int, start_time_seconds: float) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=_SCENE_DURATION_SECONDS,
        local_file=f"assets/videos/scene_{scene_number:03}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        start_time_seconds=start_time_seconds,
        end_time_seconds=start_time_seconds + _SCENE_DURATION_SECONDS,
        editing_blueprint=_blueprint(scene_number=scene_number),
    )


def _voice_blueprint(*, scene_number: int, narration: str) -> ResolvedVoiceBlueprint:
    return ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.neutral_narrator",
            resolved_profile_id="voice.neutral_narrator",
            display_name="Neutral Narrator",
            found_exact_match=True,
        ),
        narration_text=narration,
        # Deliberately the scene's own full nominal duration, so
        # subtitles would naturally want to use the entire scene
        # window absent the transition-boundary reservation this
        # fix adds.
        estimated_speech_duration_seconds=float(_SCENE_DURATION_SECONDS),
        narration_word_count=len(narration.split()),
        narration_character_count=len(narration),
        source=VoiceDirectiveSource.SYSTEM_DEFAULT,
    )


def _three_scene_timeline() -> tuple[VideoTimeline, list[ResolvedVoiceBlueprint]]:
    items = [
        _item(scene_number=1, start_time_seconds=0.0),
        _item(scene_number=2, start_time_seconds=8.0),
        _item(scene_number=3, start_time_seconds=16.0),
    ]

    timeline = VideoTimeline(
        clips=[item.clip for item in items],
        items=items,
    )

    voice_blueprints = [
        _voice_blueprint(
            scene_number=1,
            narration=(
                "The old bunker door slowly opened and nobody inside dared "
                "to move even one single inch."
            ),
        ),
        _voice_blueprint(
            scene_number=2,
            narration=(
                "Then a distant explosion echoed through the underground "
                "corridor and rattled every loose pipe."
            ),
        ),
        _voice_blueprint(
            scene_number=3,
            narration=(
                "Silence returned as the survivors waited for whatever "
                "would happen to them next."
            ),
        ),
    ]

    return timeline, voice_blueprints


def test_middle_scene_reserves_the_transition_duration_on_both_edges() -> None:
    """
    Real-world finding, 2026-09-18: every scene is fully rendered as
    its own complete clip, subtitles burned in, before a real
    crossfade transition blends it with its neighbor - subtitle
    timing that runs right up to a scene's own edges puts two real,
    different subtitle lines into the same composited frame during
    that blend. Confirmed directly on a real render: scene 11's own
    last subtitle ran to its exact scene end, squarely inside the
    crossfade into scene 12, whose own first subtitle starts at its
    own t=0 - both visible together. A middle scene (a real
    transition on both sides) must reserve transition_duration_seconds
    at both its start and its end.
    """

    timeline, voice_blueprints = _three_scene_timeline()

    service = SubtitleExecutionService()

    plan = service.build_plan(
        timeline,
        voice_blueprints=voice_blueprints,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
    )

    scene_2_executions = [
        execution for execution in plan.executions if execution.scene_number == 2
    ]

    assert scene_2_executions

    first = min(scene_2_executions, key=lambda execution: execution.start_time_seconds)

    last = max(scene_2_executions, key=lambda execution: execution.end_time_seconds)

    # scene 2 starts at global t=8.0 - its own local reserved window
    # is [1.0, 7.0], i.e. global [9.0, 15.0].
    assert first.start_time_seconds >= 9.0

    assert last.end_time_seconds <= 15.0


def test_first_scene_only_reserves_its_trailing_edge() -> None:
    """The first scene has no incoming transition - only its end needs
    the reservation, not its start."""

    timeline, voice_blueprints = _three_scene_timeline()

    service = SubtitleExecutionService()

    plan = service.build_plan(
        timeline,
        voice_blueprints=voice_blueprints,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
    )

    scene_1_executions = [
        execution for execution in plan.executions if execution.scene_number == 1
    ]

    assert scene_1_executions

    first = min(scene_1_executions, key=lambda execution: execution.start_time_seconds)

    last = max(scene_1_executions, key=lambda execution: execution.end_time_seconds)

    assert first.start_time_seconds == 0.0

    # scene 1's own reserved window is [0.0, 7.0] (global, since it
    # starts at t=0).
    assert last.end_time_seconds <= 7.0


def test_last_scene_only_reserves_its_leading_edge() -> None:
    """The last scene has no outgoing transition - only its start needs
    the reservation, not its end."""

    timeline, voice_blueprints = _three_scene_timeline()

    service = SubtitleExecutionService()

    plan = service.build_plan(
        timeline,
        voice_blueprints=voice_blueprints,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
    )

    scene_3_executions = [
        execution for execution in plan.executions if execution.scene_number == 3
    ]

    assert scene_3_executions

    first = min(scene_3_executions, key=lambda execution: execution.start_time_seconds)

    last = max(scene_3_executions, key=lambda execution: execution.end_time_seconds)

    # scene 3 starts at global t=16.0 - its own reserved window is
    # [1.0, 8.0], i.e. global [17.0, 24.0].
    assert first.start_time_seconds >= 17.0

    assert last.end_time_seconds <= 24.0


def test_no_two_scenes_subtitle_windows_overlap_during_the_crossfade() -> None:
    """
    The actual bug this fix closes: scene 1's last subtitle and scene
    2's first subtitle must never both be active during the real
    crossfade blend between them (global [7.0, 9.0), the 1.0s
    overlap around the scene 1/scene 2 boundary).
    """

    timeline, voice_blueprints = _three_scene_timeline()

    service = SubtitleExecutionService()

    plan = service.build_plan(
        timeline,
        voice_blueprints=voice_blueprints,
        transition_duration_seconds=_TRANSITION_DURATION_SECONDS,
    )

    crossfade_start, crossfade_end = 7.0, 9.0

    active_during_crossfade = [
        execution
        for execution in plan.executions
        if execution.start_time_seconds < crossfade_end
        and execution.end_time_seconds > crossfade_start
    ]

    assert active_during_crossfade == []


def test_zero_transition_duration_leaves_subtitle_timing_unchanged() -> None:
    """No genre profile resolved (transition_duration_seconds defaults
    to 0.0) must reproduce the exact prior behavior: subtitles may use
    a scene's entire own duration."""

    timeline, voice_blueprints = _three_scene_timeline()

    service = SubtitleExecutionService()

    plan = service.build_plan(timeline, voice_blueprints=voice_blueprints)

    scene_2_executions = [
        execution for execution in plan.executions if execution.scene_number == 2
    ]

    first = min(scene_2_executions, key=lambda execution: execution.start_time_seconds)

    assert first.start_time_seconds == 8.0
