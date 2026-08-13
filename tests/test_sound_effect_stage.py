from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity, DirectiveTimingMode
from src.models.media_strategy import SceneSourceType
from src.models.research import ResearchResult, ResearchStatus
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSoundEffectInstruction,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.sound_effect_stage import SoundEffectPipelineStage
from src.pipeline.stage_context import StageContext
from src.providers.sound_effect_provider import SoundEffectProvider
from src.services.sound_effect_generation_service import (
    SoundEffectGenerationService,
)


def _preset(*, resolved_preset_id: str) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path="preset_id",
        requested_preset_id=resolved_preset_id,
        resolved_preset_id=resolved_preset_id,
        found_exact_match=True,
        implementation={"library_query": resolved_preset_id},
    )


def _cue(
    *,
    resolved_preset_id: str = "sfx.door_creak",
    timing_mode: DirectiveTimingMode = DirectiveTimingMode.SCENE_START,
    start_offset_seconds: float = 0.0,
    relative_position_percent: float | None = None,
    enabled: bool = True,
) -> ResolvedSoundEffectInstruction:
    return ResolvedSoundEffectInstruction(
        preset=_preset(resolved_preset_id=resolved_preset_id),
        timing_mode=timing_mode,
        start_offset_seconds=start_offset_seconds,
        relative_position_percent=relative_position_percent,
        volume_percent=70.0,
        intensity=DirectiveIntensity.MEDIUM,
        enabled=enabled,
    )


def _blueprint(
    *,
    scene_number: int,
    sound_effects: list[ResolvedSoundEffectInstruction],
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset(resolved_preset_id="genre.horror"),
        camera=ResolvedCameraInstruction(
            preset=_preset(resolved_preset_id="camera.none")
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_preset(resolved_preset_id="transition.cut"),
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_preset(resolved_preset_id="transition.cut"),
        ),
        music=ResolvedMusicInstruction(
            preset=_preset(resolved_preset_id="music.none"),
            enabled=False,
        ),
        sound_effects=sound_effects,
        subtitles=ResolvedSubtitleInstruction(
            preset=_preset(resolved_preset_id="subtitle.default"),
            enabled=False,
            burn_into_video=False,
        ),
        status=BlueprintResolutionStatus.RESOLVED,
        exact_match_count=6,
    )


def _job_with_timeline(
    *,
    scene_duration: float = 8.0,
    sound_effects: list[ResolvedSoundEffectInstruction] | None = None,
    include_timeline: bool = True,
) -> VideoJob:
    scene = Scene(
        scene_number=1,
        title="Scene 1",
        narration="Narration.",
        visual_prompt="A visual.",
        estimated_duration_seconds=int(scene_duration),
    )

    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.STOCK_FOOTAGE,
        duration_seconds=int(scene_duration),
        local_file="assets/scene_1.mp4",
        status=VideoClipStatus.READY,
    )

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
        scenes=[scene],
        video_clips=[clip],
    )

    if not include_timeline:
        return job

    item = VideoTimelineItem(
        clip=clip,
        scene_number=1,
        start_time_seconds=100.0,
        end_time_seconds=100.0 + scene_duration,
        editing_blueprint=_blueprint(
            scene_number=1,
            sound_effects=sound_effects or [],
        ),
    )

    job.video_timeline = VideoTimeline(items=[item], output_resolution="1920x1080")

    return job


def _context(job: VideoJob) -> StageContext:
    return StageContext(
        job=job,
        pipeline_state=PipelineState(current_stage=PipelineStageName.SOUND_EFFECTS),
    )


class FakeSoundEffectProvider(SoundEffectProvider):
    def __init__(
        self,
        *,
        healthy: bool = True,
        fail_queries: set[str] | None = None,
    ) -> None:
        self._healthy = healthy
        self._fail_queries = fail_queries or set()

    @property
    def provider_name(self) -> str:
        return "fake"

    def health_check(self) -> bool:
        return self._healthy

    def generate_sound_effect(self, *, library_query: str) -> str:
        if library_query in self._fail_queries:
            raise RuntimeError("simulated failure")

        return f"dry-run://sfx/{library_query}.mp3"


def test_execute_reports_zero_attached_without_video_timeline() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(include_timeline=False)

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached_count"] == 0


def test_execute_skips_disabled_cues() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(sound_effects=[_cue(enabled=False)])

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached_count"] == 0
    assert job.audio_timeline is None or not job.audio_timeline.tracks


def test_execute_resolves_scene_start_cue_to_scene_start_time() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(
        sound_effects=[_cue(timing_mode=DirectiveTimingMode.SCENE_START)],
    )

    stage.execute(_context(job))

    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks[0].start_time_seconds == 100.0


def test_execute_resolves_scene_middle_cue_to_scene_midpoint() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(
        scene_duration=8.0,
        sound_effects=[_cue(timing_mode=DirectiveTimingMode.SCENE_MIDDLE)],
    )

    stage.execute(_context(job))

    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks[0].start_time_seconds == 104.0


def test_execute_resolves_scene_end_cue_to_scene_end_time() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(
        scene_duration=8.0,
        sound_effects=[_cue(timing_mode=DirectiveTimingMode.SCENE_END)],
    )

    stage.execute(_context(job))

    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks[0].start_time_seconds == 108.0


def test_execute_resolves_absolute_offset_cue() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(
        sound_effects=[
            _cue(
                timing_mode=DirectiveTimingMode.ABSOLUTE_SECONDS,
                start_offset_seconds=3.0,
            )
        ],
    )

    stage.execute(_context(job))

    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks[0].start_time_seconds == 103.0


def test_execute_resolves_relative_position_cue() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(
        scene_duration=8.0,
        sound_effects=[_cue(relative_position_percent=25.0)],
    )

    stage.execute(_context(job))

    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks[0].start_time_seconds == 102.0


def test_execute_attaches_multiple_enabled_cues_per_scene() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[FakeSoundEffectProvider()]
        ),
    )
    job = _job_with_timeline(
        sound_effects=[
            _cue(resolved_preset_id="sfx.door_creak"),
            _cue(resolved_preset_id="sfx.heartbeat_low"),
        ],
    )

    result = stage.execute(_context(job))

    assert result.metadata["attached_count"] == 2
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) == 2
    assert all(
        track.track_type.value == "sound_effect" for track in job.audio_timeline.tracks
    )


def test_execute_is_non_fatal_when_one_cue_fails() -> None:
    stage = SoundEffectPipelineStage(
        generation_service=SoundEffectGenerationService(
            providers=[
                FakeSoundEffectProvider(fail_queries={"sfx.door_creak"}),
            ]
        ),
    )
    job = _job_with_timeline(
        sound_effects=[
            _cue(resolved_preset_id="sfx.door_creak"),
            _cue(resolved_preset_id="sfx.heartbeat_low"),
        ],
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert not result.errors
    assert result.warnings
    assert result.metadata["attached_count"] == 1
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) == 1
