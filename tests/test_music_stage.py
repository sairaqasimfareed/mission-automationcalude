from __future__ import annotations

from src.models.editing_directives import DirectiveIntensity
from src.models.media_strategy import SceneSourceType
from src.models.research import ResearchResult, ResearchStatus
from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedCameraInstruction,
    ResolvedMusicInstruction,
    ResolvedPresetReference,
    ResolvedSceneEditingBlueprint,
    ResolvedSubtitleInstruction,
    ResolvedTransitionInstruction,
)
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.music_stage import MusicPipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext
from src.providers.music_provider import MusicProvider
from src.services.music_generation_service import MusicGenerationService


def _preset(
    *,
    resolved_preset_id: str,
    implementation: dict[str, object] | None = None,
) -> ResolvedPresetReference:
    return ResolvedPresetReference(
        directive_path="preset_id",
        requested_preset_id=resolved_preset_id,
        resolved_preset_id=resolved_preset_id,
        found_exact_match=True,
        implementation=implementation or {},
    )


def _blueprint(
    *, scene_number: int, music_enabled: bool
) -> ResolvedSceneEditingBlueprint:
    return ResolvedSceneEditingBlueprint(
        scene_number=scene_number,
        genre_preset=_preset(resolved_preset_id="genre.horror"),
        camera=ResolvedCameraInstruction(
            preset=_preset(resolved_preset_id="camera.none"),
        ),
        transition_in=ResolvedTransitionInstruction(
            preset=_preset(resolved_preset_id="transition.cut"),
        ),
        transition_out=ResolvedTransitionInstruction(
            preset=_preset(resolved_preset_id="transition.cut"),
        ),
        music=ResolvedMusicInstruction(
            preset=_preset(
                resolved_preset_id="music.horror_low_drone",
                implementation={"library_query": "dark low suspense drone"},
            ),
            intensity=DirectiveIntensity.LOW,
            volume_percent=25.0,
            enabled=music_enabled,
        ),
        sound_effects=[],
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
    scene_count: int = 2,
    music_enabled: bool = True,
    include_timeline: bool = True,
) -> VideoJob:
    scenes = [
        Scene(
            scene_number=index,
            title=f"Scene {index}",
            narration="Narration.",
            visual_prompt="A visual.",
            estimated_duration_seconds=8,
        )
        for index in range(1, scene_count + 1)
    ]

    clips = [
        VideoClip(
            scene_number=index,
            source_type=SceneSourceType.STOCK_FOOTAGE,
            duration_seconds=8,
            local_file=f"assets/scene_{index}.mp4",
            status=VideoClipStatus.READY,
        )
        for index in range(1, scene_count + 1)
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
    )

    if not include_timeline:
        return job

    items = [
        VideoTimelineItem(
            clip=clips[index - 1],
            scene_number=index,
            start_time_seconds=float((index - 1) * 8),
            end_time_seconds=float(index * 8),
            editing_blueprint=_blueprint(
                scene_number=index,
                music_enabled=music_enabled,
            ),
        )
        for index in range(1, scene_count + 1)
    ]

    job.video_timeline = VideoTimeline(items=items, output_resolution="1920x1080")

    return job


def _context(job: VideoJob) -> StageContext:
    return StageContext(
        job=job,
        pipeline_state=PipelineState(current_stage=PipelineStageName.BACKGROUND_MUSIC),
    )


class FakeMusicProvider(MusicProvider):
    def __init__(self, *, output_file: str = "dry-run://music/test.mp3") -> None:
        self._output_file = output_file

    @property
    def provider_name(self) -> str:
        return "fake"

    def health_check(self) -> bool:
        return True

    def generate_music(self, *, library_query: str, duration_seconds: float) -> str:
        return self._output_file


def test_execute_skips_without_video_timeline() -> None:
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[FakeMusicProvider()]),
    )
    job = _job_with_timeline(include_timeline=False)

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.warnings
    assert job.audio_timeline is None


def test_execute_skips_silently_when_no_music_configured() -> None:
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[FakeMusicProvider()]),
    )
    job = _job_with_timeline(music_enabled=False)

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert not result.warnings
    assert job.audio_timeline is None


def test_execute_attaches_music_track_for_full_timeline_duration() -> None:
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[FakeMusicProvider()]),
    )
    job = _job_with_timeline(scene_count=3, music_enabled=True)

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) == 1

    track = job.audio_timeline.tracks[0]
    assert track.track_type.value == "background_music"
    assert track.start_time_seconds == 0.0
    assert track.duration_seconds == 24.0


def test_execute_is_non_fatal_when_generation_fails() -> None:
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[]),
    )
    job = _job_with_timeline(music_enabled=True)

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert not result.errors
    assert result.warnings
    assert job.audio_timeline is None
