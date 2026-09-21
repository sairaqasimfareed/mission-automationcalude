from __future__ import annotations

from src.models.editing_directives import DirectiveTimingMode
from src.models.media_strategy import SceneSourceType
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.pipeline_stage import PipelineStageName
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.sound_effect_stage import SoundEffectPipelineStage
from src.pipeline.stage_context import StageContext
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)
from tests.test_sound_effect_stage import FakeSoundEffectProvider, _blueprint, _cue

_TRANSITION_DURATION_SECONDS = 0.6
_SCENE_DURATION_SECONDS = 8.0


def _three_scene_job(
    *,
    sound_effects_by_scene: dict[int, list],
) -> VideoJob:
    scenes = [
        Scene(
            scene_number=number,
            title=f"Scene {number}",
            narration="Narration.",
            visual_prompt="A visual.",
            estimated_duration_seconds=int(_SCENE_DURATION_SECONDS),
        )
        for number in (1, 2, 3)
    ]

    clips = [
        VideoClip(
            scene_number=number,
            source_type=SceneSourceType.STOCK_FOOTAGE,
            duration_seconds=int(_SCENE_DURATION_SECONDS),
            local_file=f"assets/scene_{number}.mp4",
            status=VideoClipStatus.READY,
        )
        for number in (1, 2, 3)
    ]

    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        research=ResearchResult(
            topic="A topic",
            research_summary="A summary.",
            prompt_version="research_prompt_v1.0.0",
            status=ResearchStatus.APPROVED,
        ),
        script=Script(
            title="A title",
            content="Script content.",
            prompt_version="script_prompt_v1.0.0",
            status=ScriptStatus.APPROVED,
        ),
        scenes=scenes,
        video_clips=clips,
        voice_file="assets/voice.mp3",
    )

    items = [
        VideoTimelineItem(
            clip=clip,
            scene_number=number,
            start_time_seconds=(number - 1) * _SCENE_DURATION_SECONDS,
            end_time_seconds=number * _SCENE_DURATION_SECONDS,
            editing_blueprint=_blueprint(
                scene_number=number,
                sound_effects=sound_effects_by_scene.get(number, []),
            ),
        )
        for number, clip in zip((1, 2, 3), clips, strict=True)
    ]

    job.video_timeline = VideoTimeline(items=items, output_resolution="1920x1080")

    return job


def _context(job: VideoJob) -> StageContext:
    return StageContext(
        job=job,
        pipeline_state=PipelineState(current_stage=PipelineStageName.SOUND_EFFECTS),
    )


def _stage(*, transition_duration_seconds: float) -> SoundEffectPipelineStage:
    return SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
        transition_duration_seconds=transition_duration_seconds,
    )


def test_scene_end_cue_on_a_middle_scene_does_not_bleed_into_the_next_scene() -> None:
    """
    Real-world finding, 2026-09-18: confirmed via direct frame
    inspection on a real render - a "scene end" cue clamped against
    its scene's nominal boundary landed transition_duration_seconds
    into the *next* scene's real screen time once crossfade
    shrinkage was accounted for (the nominal boundary assumes no
    crossfade eats into it). A scene-2 cue (a real transition on both
    sides) must reserve the transition duration at its own end, not
    just play at its nominal boundary.
    """

    job = _three_scene_job(
        sound_effects_by_scene={
            2: [_cue(timing_mode=DirectiveTimingMode.SCENE_END)],
        },
    )

    stage = _stage(transition_duration_seconds=_TRANSITION_DURATION_SECONDS)

    stage.execute(_context(job))

    assert job.audio_timeline is not None

    track = job.audio_timeline.tracks[0]

    # scene 2's nominal item.start_time_seconds (8.0) is also one
    # scene boundary ahead of its real, crossfade-corrected start
    # (7.4 - see _resolve_start_time's own docstring for why this
    # correction exists at all). Its own real "end" then reserves the
    # trailing 0.6s for the crossfade into scene 3: 7.4 + (8.0 - 0.6)
    # = 14.8, not the nominal 16.0.
    assert track.start_time_seconds == 14.8


def test_scene_start_cue_on_a_middle_scene_waits_for_the_incoming_crossfade() -> None:
    """A scene-2 "scene start" cue must not play until the crossfade
    blending it in from scene 1 has actually finished."""

    job = _three_scene_job(
        sound_effects_by_scene={
            2: [_cue(timing_mode=DirectiveTimingMode.SCENE_START)],
        },
    )

    stage = _stage(transition_duration_seconds=_TRANSITION_DURATION_SECONDS)

    stage.execute(_context(job))

    assert job.audio_timeline is not None

    track = job.audio_timeline.tracks[0]

    # scene 2's real, crossfade-corrected start is 7.4 (one boundary
    # before its nominal 8.0) - its own real start then reserves the
    # leading 0.6s for the crossfade in from scene 1: 7.4 + 0.6 = 8.0.
    assert track.start_time_seconds == 8.0


def test_first_scene_end_cue_is_unrestricted_at_its_own_end() -> None:
    """The first scene has a real transition only on its outgoing
    side - "scene start" is not restricted, but "scene end" still is."""

    job = _three_scene_job(
        sound_effects_by_scene={
            1: [_cue(timing_mode=DirectiveTimingMode.SCENE_START)],
        },
    )

    stage = _stage(transition_duration_seconds=_TRANSITION_DURATION_SECONDS)

    stage.execute(_context(job))

    assert job.audio_timeline is not None

    track = job.audio_timeline.tracks[0]

    assert track.start_time_seconds == 0.0


def test_last_scene_end_cue_is_unrestricted_at_its_own_end() -> None:
    """The last scene has no outgoing transition - "scene end" may use
    its full, real nominal boundary."""

    job = _three_scene_job(
        sound_effects_by_scene={
            3: [_cue(timing_mode=DirectiveTimingMode.SCENE_END)],
        },
    )

    stage = _stage(transition_duration_seconds=_TRANSITION_DURATION_SECONDS)

    stage.execute(_context(job))

    assert job.audio_timeline is not None

    track = job.audio_timeline.tracks[0]

    # scene 3's real, crossfade-corrected start is 14.8 (two
    # boundaries before its nominal 16.0) - no outgoing transition to
    # reserve for, so "scene end" uses the full 8.0 local duration:
    # 14.8 + 8.0 = 22.8.
    assert track.start_time_seconds == 22.8


def test_zero_transition_duration_leaves_cue_timing_unchanged() -> None:
    """No genre profile resolved (transition_duration_seconds defaults
    to 0.0) must reproduce the exact prior behavior."""

    job = _three_scene_job(
        sound_effects_by_scene={
            2: [_cue(timing_mode=DirectiveTimingMode.SCENE_END)],
        },
    )

    stage = _stage(transition_duration_seconds=0.0)

    stage.execute(_context(job))

    assert job.audio_timeline is not None

    track = job.audio_timeline.tracks[0]

    assert track.start_time_seconds == 16.0
