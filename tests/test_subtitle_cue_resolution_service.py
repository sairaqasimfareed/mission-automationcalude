"""
REQ-0, 2026-09-22: resolve_absolute_subtitle_cues remaps
SubtitleExecutionService's own proven narration-chunking logic onto
REQ-00 Stage 1's real, crossfade-corrected scene_timings - the real
per-scene work this whole post-render burn-in service depends on.
"""

from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_result import SceneRenderTiming
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
from src.services.subtitle_cue_resolution_service import (
    resolve_absolute_subtitle_cues,
)


def _preset(*, directive_path: str, preset_id: str) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path=directive_path,
        requested_preset_id=preset_id,
        resolved_preset_id=preset_id,
        found_exact_match=True,
        used_fallback=False,
    )


def _blueprint(
    scene_number: int, *, subtitles_enabled: bool = True
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset(
            directive_path="genre_preset_id", preset_id="genre.default"
        ),
        camera=ResolvedCameraInstruction(
            preset=_preset(directive_path="camera.preset_id", preset_id="camera.none"),
            intensity=DirectiveIntensity.MEDIUM,
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_preset(
                directive_path="transition_in.preset_id", preset_id="transition.cut"
            ),
            duration_seconds=0.0,
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_preset(
                directive_path="transition_out.preset_id", preset_id="transition.cut"
            ),
            duration_seconds=0.0,
        ),
        music=ResolvedMusicInstruction(
            preset=_preset(directive_path="music.preset_id", preset_id="music.none"),
            enabled=False,
        ),
        subtitles=ResolvedSubtitleInstruction(
            preset=_preset(
                directive_path="subtitles.preset_id", preset_id="subtitle.default"
            ),
            enabled=subtitles_enabled,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
    )


def _item(
    scene_number: int,
    *,
    clip_sequence_index: int = 0,
    start: float,
    duration: float = 8.0,
) -> VideoTimelineItem:
    clip = VideoClip(
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=int(duration),
        prompt="test",
        local_file=f"scene_{scene_number}_{clip_sequence_index}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    return VideoTimelineItem(
        clip=clip,
        scene_number=scene_number,
        clip_sequence_index=clip_sequence_index,
        start_time_seconds=start,
        end_time_seconds=start + duration,
        editing_blueprint=_blueprint(scene_number),
    )


def _voice_blueprint(
    scene_number: int, *, narration_text: str, speech_duration: float
) -> ResolvedVoiceBlueprint:
    return ResolvedVoiceBlueprint(
        scene_number=scene_number,
        status=VoiceBlueprintResolutionStatus.RESOLVED,
        profile=ResolvedVoiceProfileReference(
            requested_profile_id="voice.smoke",
            resolved_profile_id="voice.smoke",
            display_name="Smoke Voice",
            found_exact_match=True,
            used_fallback=False,
        ),
        narration_text=narration_text,
        estimated_speech_duration_seconds=speech_duration,
    )


def test_a_single_unsplit_scenes_cues_land_at_its_real_union_position() -> None:
    video_timeline = VideoTimeline(
        items=[_item(1, start=0.0, duration=8.0)],
    )

    voice_blueprints = [
        _voice_blueprint(
            1, narration_text="A short line of narration.", speech_duration=4.0
        )
    ]

    scene_timings = [
        SceneRenderTiming(
            scene_number=1,
            clip_sequence_index=0,
            start_seconds=2.0,  # real position differs from naive 0.0
            end_seconds=10.0,
        )
    ]

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=voice_blueprints,
        scene_timings=scene_timings,
    )

    assert cues

    # Every cue must land inside the scene's real [2.0, 10.0) window,
    # never at its naive [0.0, 8.0) position.
    for cue in cues:
        assert cue.start_seconds >= 2.0
        assert cue.end_seconds <= 10.0


def test_a_split_scenes_cues_stretch_across_the_full_real_union_span() -> None:
    """
    The real caveat this whole file exists to close: a split scene's
    real position is the union across all its sub-clips, not just
    sub-clip 0's own narrower slice - confirmed here by checking the
    last cue can extend well past sub-clip 0's own naive duration.
    """

    video_timeline = VideoTimeline(
        items=[
            _item(1, clip_sequence_index=0, start=0.0, duration=8.0),
            _item(1, clip_sequence_index=1, start=8.0, duration=8.0),
        ],
    )

    voice_blueprints = [
        _voice_blueprint(
            1,
            narration_text=(
                "This is a much longer piece of narration that would "
                "naturally take more than eight seconds to read aloud "
                "in full, spanning what became two separate sub clips."
            ),
            speech_duration=14.0,
        )
    ]

    # Real union spans both sub-clips: 0.0 to 16.0 (double sub-clip
    # 0's own naive 0-8 range).
    scene_timings = [
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=0, start_seconds=0.0, end_seconds=8.0
        ),
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=1, start_seconds=8.0, end_seconds=16.0
        ),
    ]

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=voice_blueprints,
        scene_timings=scene_timings,
    )

    assert cues

    # At least one cue must land beyond sub-clip 0's own naive 8s
    # duration - proof the union span, not sub-clip 0 alone, was used.
    assert any(cue.end_seconds > 8.0 for cue in cues)

    # Nothing may exceed the real union's own end (16.0).
    for cue in cues:
        assert cue.end_seconds <= 16.0


def test_a_scene_with_subtitles_disabled_produces_no_cues() -> None:
    video_timeline = VideoTimeline(
        items=[
            VideoTimelineItem(
                clip=VideoClip(
                    scene_number=1,
                    source_type=SceneSourceType.AI_GENERATE,
                    duration_seconds=8,
                    prompt="test",
                    local_file="scene_1.mp4",
                    source_status=SceneSourceStatus.READY,
                    status=VideoClipStatus.READY,
                ),
                scene_number=1,
                start_time_seconds=0.0,
                end_time_seconds=8.0,
                editing_blueprint=_blueprint(1, subtitles_enabled=False),
            )
        ]
    )

    voice_blueprints = [
        _voice_blueprint(1, narration_text="Some narration.", speech_duration=4.0)
    ]

    scene_timings = [
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=0, start_seconds=0.0, end_seconds=8.0
        )
    ]

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=voice_blueprints,
        scene_timings=scene_timings,
    )

    assert cues == []


def test_a_scene_with_no_matching_timing_produces_no_cues() -> None:
    video_timeline = VideoTimeline(items=[_item(1, start=0.0, duration=8.0)])

    voice_blueprints = [
        _voice_blueprint(1, narration_text="Some narration.", speech_duration=4.0)
    ]

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=voice_blueprints,
        scene_timings=[],
    )

    assert cues == []


def test_two_scenes_stay_ordered_and_within_their_own_real_windows() -> None:
    video_timeline = VideoTimeline(
        items=[
            _item(1, start=0.0, duration=8.0),
            _item(2, start=8.0, duration=8.0),
        ]
    )

    voice_blueprints = [
        _voice_blueprint(
            1, narration_text="First scene narration.", speech_duration=4.0
        ),
        _voice_blueprint(
            2, narration_text="Second scene narration.", speech_duration=4.0
        ),
    ]

    scene_timings = [
        SceneRenderTiming(
            scene_number=1, clip_sequence_index=0, start_seconds=0.0, end_seconds=7.4
        ),
        SceneRenderTiming(
            scene_number=2, clip_sequence_index=0, start_seconds=7.4, end_seconds=15.4
        ),
    ]

    cues = resolve_absolute_subtitle_cues(
        video_timeline=video_timeline,
        voice_blueprints=voice_blueprints,
        scene_timings=scene_timings,
        transition_duration_seconds=0.6,
    )

    assert cues

    scene_1_cues = [cue for cue in cues if cue.end_seconds <= 7.4]
    scene_2_cues = [cue for cue in cues if cue.start_seconds >= 7.4]

    assert len(scene_1_cues) + len(scene_2_cues) == len(cues)
    assert scene_1_cues
    assert scene_2_cues
