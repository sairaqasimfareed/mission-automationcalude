from __future__ import annotations

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.enums import JobStatus, WorkflowStage
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_result import SceneRenderTiming
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene, SceneStatus
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.pipeline.native_clip_audio_stage import NativeClipAudioPipelineStage
from src.pipeline.pipeline_stage import PipelineStageName, PipelineStageStatus
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.stage_context import StageContext


class _FakeExtractionService:
    def __init__(
        self,
        *,
        tracks: list[AudioTrack] | None = None,
        raise_error: Exception | None = None,
    ) -> None:
        self._tracks = tracks or []
        self._raise_error = raise_error
        self.calls: list[dict[str, object]] = []

    def extract_native_clip_audio_tracks(
        self,
        *,
        video_timeline: VideoTimeline,
        scene_timings: list[SceneRenderTiming],
        output_directory: str,
    ) -> list[AudioTrack]:
        self.calls.append(
            {
                "video_timeline": video_timeline,
                "scene_timings": scene_timings,
                "output_directory": output_directory,
            }
        )

        if self._raise_error is not None:
            raise self._raise_error

        return self._tracks


def _build_job(*, include_native_clip_audio: bool) -> VideoJob:
    job = VideoJob(
        project_name="Native Clip Audio Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Native clip audio wiring",
        status=JobStatus.RUNNING,
        current_stage=WorkflowStage.RENDER,
    )

    # VideoJob's own cross-field validator requires a real voice_file
    # whenever audio_timeline is set - every test in this file may
    # attach one, so this is set unconditionally up front.
    job.voice_file = "assets/audio/test_voice.wav"

    job.audio_inclusion_preferences = AudioInclusionPreferences(
        include_native_clip_audio=include_native_clip_audio,
    )

    return job


def _attach_video_timeline(job: VideoJob) -> None:
    """
    VideoJob's own cross-field validators require video_clips (with a
    matching planned scene) whenever video_timeline is set - all
    three are attached together here so every test stays domain-valid.
    """

    timeline = _video_timeline()

    job.research = ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )

    job.script = Script(
        title="Native Clip Audio Test Script",
        content="A scene with real embedded dialogue.",
        prompt_version="test-1.0",
        word_count=6,
        estimated_duration_seconds=4,
        status=ScriptStatus.APPROVED,
    )

    job.scenes = [
        Scene(
            scene_number=1,
            title="Native Clip Scene",
            narration="A scene with real embedded dialogue.",
            visual_prompt="A scene with real embedded dialogue.",
            estimated_duration_seconds=4,
            status=SceneStatus.READY,
        )
    ]

    job.video_clips = list(timeline.clips)
    job.video_timeline = timeline


def _video_timeline() -> VideoTimeline:
    clip = VideoClip(
        scene_number=1,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=4,
        prompt="A scene with real embedded dialogue.",
        provider="Google Flow",
        local_file="assets/videos/scene_001.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    item = VideoTimelineItem(
        clip=clip,
        scene_number=1,
        start_time_seconds=0.0,
        end_time_seconds=4.0,
        track_index=0,
        layer_index=0,
        enabled=True,
    )

    return VideoTimeline(clips=[clip], items=[item])


def _context(job: VideoJob) -> StageContext:
    return StageContext(
        job=job,
        pipeline_state=PipelineState(current_stage=PipelineStageName.AUDIO_TIMELINE),
        dry_run=True,
    )


def _native_track() -> AudioTrack:
    return AudioTrack(
        track_type=AudioTrackType.NATIVE_CLIP,
        source_file="assets/audio/native_clips/scene_001.m4a",
        start_time_seconds=0.0,
        duration_seconds=4.0,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": 1},
    )


def test_toggle_off_skips_extraction_entirely() -> None:
    job = _build_job(include_native_clip_audio=False)
    _attach_video_timeline(job)

    extraction_service = _FakeExtractionService(tracks=[_native_track()])

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached"] is False
    assert extraction_service.calls == []


def test_no_video_timeline_skips_gracefully() -> None:
    job = _build_job(include_native_clip_audio=True)

    extraction_service = _FakeExtractionService(tracks=[_native_track()])

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached"] is False
    assert extraction_service.calls == []


def test_toggle_on_attaches_real_tracks_onto_the_job() -> None:
    job = _build_job(include_native_clip_audio=True)
    _attach_video_timeline(job)

    track = _native_track()

    extraction_service = _FakeExtractionService(tracks=[track])

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached"] is True
    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks == [track]
    assert len(extraction_service.calls) == 1


def test_already_attached_native_clip_audio_is_not_re_extracted() -> None:
    job = _build_job(include_native_clip_audio=True)
    _attach_video_timeline(job)
    job.audio_timeline = AudioTimeline(tracks=[_native_track()])

    extraction_service = _FakeExtractionService(tracks=[_native_track()])

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached"] is False
    assert result.metadata["reason"] == "native_clip_audio_already_attached"
    assert extraction_service.calls == []


def test_no_scene_carries_real_audio_is_a_real_no_op() -> None:
    job = _build_job(include_native_clip_audio=True)
    _attach_video_timeline(job)

    extraction_service = _FakeExtractionService(tracks=[])

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached"] is False
    assert result.metadata["reason"] == "no_scene_carries_real_native_audio"


def test_extraction_failure_degrades_to_a_warning_not_a_failed_stage() -> None:
    job = _build_job(include_native_clip_audio=True)
    _attach_video_timeline(job)

    extraction_service = _FakeExtractionService(
        raise_error=RuntimeError("Simulated ffmpeg failure.")
    )

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached"] is False
    assert "Simulated ffmpeg failure." in result.warnings[0]


def test_existing_non_native_tracks_are_preserved_alongside_new_ones() -> None:
    job = _build_job(include_native_clip_audio=True)
    _attach_video_timeline(job)

    existing_voiceover = AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file="assets/audio/voiceover.wav",
        start_time_seconds=0.0,
        duration_seconds=4.0,
        status=AudioTrackStatus.READY,
    )

    job.audio_timeline = AudioTimeline(tracks=[existing_voiceover])

    track = _native_track()

    extraction_service = _FakeExtractionService(tracks=[track])

    stage = NativeClipAudioPipelineStage(
        extraction_service=extraction_service,  # type: ignore[arg-type]
    )

    stage.execute(_context(job))

    assert job.audio_timeline is not None
    assert job.audio_timeline.tracks == [existing_voiceover, track]
