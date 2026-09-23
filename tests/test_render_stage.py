from __future__ import annotations

from unittest.mock import MagicMock

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.render_result import (
    RenderResult,
    RenderStatus,
)
from src.models.research import (
    ResearchResult,
    ResearchStatus,
)
from src.models.scene import (
    Scene,
    SceneStatus,
)
from src.models.script import (
    Script,
    ScriptStatus,
)
from src.models.video_clip import (
    VideoClip,
    VideoClipStatus,
)
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.pipeline_state import PipelineState
from src.pipeline.render_stage import (
    RenderPipelineStage,
)
from src.pipeline.stage_context import StageContext
from src.services.render_service import RenderService


class SuccessfulRenderService(RenderService):
    """Deterministic successful render service."""

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:
        return RenderResult(
            success=True,
            output_file=("outputs/test_render.mp4"),
            render_engine="synthetic",
            render_time_seconds=0.25,
            duration_seconds=int(timeline.calculate_duration()),
            status=RenderStatus.COMPLETED,
            warnings=[
                "Synthetic render warning.",
            ],
        )


class FailedRenderService(RenderService):
    """Deterministic failed render service."""

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:
        return RenderResult(
            success=False,
            output_file=None,
            render_engine="synthetic",
            render_time_seconds=0.1,
            duration_seconds=int(timeline.calculate_duration()),
            status=RenderStatus.FAILED,
            warnings=[
                "Synthetic failure warning.",
            ],
            error_message=("Synthetic render failure."),
        )


class RaisingRenderService(RenderService):
    """Render service used to verify exception propagation."""

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:
        raise RuntimeError("Synthetic render exception.")


def build_job(
    *,
    include_timeline: bool = True,
) -> VideoJob:
    """Build a domain-valid job for render-stage tests."""

    job = VideoJob(
        project_name="Render Stage Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Render stage adapter",
        status=JobStatus.RUNNING,
        current_stage=WorkflowStage.RENDER,
    )

    research = ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )

    script = Script(
        title="Render stage script",
        content=("Synthetic narration for " "render-stage testing."),
        prompt_version="test-1.0",
        word_count=5,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title="Render Scene",
        narration=("Synthetic narration for " "render-stage testing."),
        visual_prompt=("Synthetic render-stage visual."),
        estimated_duration_seconds=10,
        manual_file_path=("assets/videos/manual/" "render_stage_test.mp4"),
        source_status=(SceneSourceStatus.READY),
        status=SceneStatus.READY,
    )

    clip = VideoClip(
        scene_number=1,
        source_type=(SceneSourceType.MANUAL_UPLOAD),
        duration_seconds=10,
        prompt=("Synthetic render-stage clip."),
        provider="Manual Upload",
        local_file=("assets/videos/manual/" "render_stage_test.mp4"),
        source_status=(SceneSourceStatus.READY),
        status=VideoClipStatus.READY,
    )

    job.research = research
    job.script = script
    job.scenes = [
        scene,
    ]

    job.video_clips = [
        clip,
    ]

    if include_timeline:
        job.video_timeline = VideoTimeline(
            clips=[
                clip,
            ],
        )

        job.video_timeline.calculate_duration()

    return job


def build_context(
    job: VideoJob,
) -> StageContext:
    """Build pipeline context for one render-stage execution."""

    return StageContext(
        job=job,
        pipeline_state=PipelineState(
            current_stage=(PipelineStageName.RENDER),
        ),
        dry_run=True,
    )


def test_stage_name() -> None:
    stage = RenderPipelineStage()

    assert stage.stage_name == PipelineStageName.RENDER


def test_successful_render() -> None:
    job = build_job()

    context = build_context(job)

    stage = RenderPipelineStage(
        render_service=(SuccessfulRenderService()),
    )

    result = stage.execute(context)

    assert result.status == PipelineStageStatus.COMPLETED

    assert result.successful is True

    assert context.job.render_result is not None

    assert context.job.render_result.success is True

    assert context.job.render_result.output_file == "outputs/test_render.mp4"

    assert result.errors == []

    assert result.warnings == [
        "Synthetic render warning.",
    ]

    assert result.metadata["render_engine"] == "synthetic"

    assert result.metadata["output_file"] == "outputs/test_render.mp4"


def test_failed_render() -> None:
    job = build_job()

    context = build_context(job)

    stage = RenderPipelineStage(
        render_service=(FailedRenderService()),
    )

    result = stage.execute(context)

    assert result.status == PipelineStageStatus.FAILED

    assert result.successful is False

    assert context.job.render_result is not None

    assert context.job.render_result.success is False

    assert result.errors == [
        "Synthetic render failure.",
    ]

    assert result.warnings == [
        "Synthetic failure warning.",
    ]


def test_missing_timeline_fails() -> None:
    job = build_job(
        include_timeline=False,
    )

    context = build_context(job)

    stage = RenderPipelineStage(
        render_service=(SuccessfulRenderService()),
    )

    result = stage.execute(context)

    assert result.status == PipelineStageStatus.FAILED

    assert result.errors == [
        ("Render stage requires " "VideoJob.video_timeline."),
    ]

    assert context.job.render_result is None


def test_empty_timeline_fails() -> None:
    job = build_job(
        include_timeline=False,
    )

    job.video_timeline = VideoTimeline()

    context = build_context(job)

    stage = RenderPipelineStage(
        render_service=(SuccessfulRenderService()),
    )

    result = stage.execute(context)

    assert result.status == PipelineStageStatus.FAILED

    assert result.errors == [
        ("Render stage requires a " "non-empty video timeline."),
    ]


def test_render_exception_propagates() -> None:
    job = build_job()

    context = build_context(job)

    stage = RenderPipelineStage(
        render_service=(RaisingRenderService()),
    )

    try:
        stage.execute(context)
    except RuntimeError as error:
        assert str(error) == ("Synthetic render " "exception.")
    else:
        raise AssertionError("Unexpected RenderService " "exceptions must propagate.")


def test_default_render_service() -> None:
    job = build_job()

    context = build_context(job)

    stage = RenderPipelineStage()

    result = stage.execute(context)

    assert result.status == PipelineStageStatus.COMPLETED

    assert context.job.render_result is not None

    assert context.job.render_result.success is True


def test_progress_callback_reaches_production_render_service() -> None:
    """
    context.services["progress_callback"] must be forwarded to
    ProductionRenderService.render(), and must be None when no
    callback was supplied - never silently dropped either way.
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    fake_production_render_service = MagicMock()
    fake_production_render_service.render.return_value = RenderResult(
        success=True,
        output_file="outputs/test_render.mp4",
        render_engine="ffmpeg",
        render_time_seconds=0.1,
        duration_seconds=10,
        status=RenderStatus.COMPLETED,
    )

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
    )

    def fake_progress_callback(progress: object) -> None:
        return None

    context = build_context(job)
    context.services["progress_callback"] = fake_progress_callback

    stage.execute(context)

    fake_production_render_service.render.assert_called_once()
    call_kwargs = fake_production_render_service.render.call_args.kwargs
    assert call_kwargs["progress_callback"] is fake_progress_callback

    # No progress_callback in services -> forwarded as None, not omitted.
    fake_production_render_service.render.reset_mock()

    no_callback_context = build_context(job)
    stage.execute(no_callback_context)

    no_callback_kwargs = fake_production_render_service.render.call_args.kwargs
    assert no_callback_kwargs["progress_callback"] is None


def _audio_track(track_type: AudioTrackType) -> AudioTrack:
    return AudioTrack(
        track_type=track_type,
        source_file=f"{track_type.value}.wav",
        start_time_seconds=0.0,
        duration_seconds=1.0,
    )


def _all_track_types_timeline() -> AudioTimeline:
    return AudioTimeline(
        tracks=[
            _audio_track(AudioTrackType.NATIVE_CLIP),
            _audio_track(AudioTrackType.VOICEOVER),
            _audio_track(AudioTrackType.BACKGROUND_MUSIC),
            _audio_track(AudioTrackType.SOUND_EFFECT),
        ]
    )


def _fake_production_render_service() -> MagicMock:
    fake = MagicMock()
    fake.render.return_value = RenderResult(
        success=True,
        output_file="outputs/test_render.mp4",
        render_engine="ffmpeg",
        render_time_seconds=0.1,
        duration_seconds=10,
        status=RenderStatus.COMPLETED,
    )

    return fake


def test_default_audio_inclusion_preferences_reproduce_real_behavior() -> None:
    """
    REQ-13: no audio_inclusion_preferences supplied at all must
    reproduce today's exact real behavior - every generated track type
    included, native-clip audio excluded (see
    AudioInclusionPreferences' own docstring).
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = _all_track_types_timeline()

    fake_production_render_service = _fake_production_render_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
    )

    stage.execute(build_context(job))

    call_kwargs = fake_production_render_service.render.call_args.kwargs
    reached_types = {track.track_type for track in call_kwargs["audio_timeline"].tracks}

    assert reached_types == {
        AudioTrackType.VOICEOVER,
        AudioTrackType.BACKGROUND_MUSIC,
        AudioTrackType.SOUND_EFFECT,
    }


def test_explicit_audio_inclusion_preferences_filter_what_reaches_the_real_render() -> (
    None
):
    """
    REQ-13: an explicit AudioInclusionPreferences must genuinely
    change which tracks reach ProductionRenderService.render() - the
    real point of the toggle UI.
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = _all_track_types_timeline()

    fake_production_render_service = _fake_production_render_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        audio_inclusion_preferences=AudioInclusionPreferences(
            include_native_clip_audio=True,
            include_voiceover=False,
            include_music=True,
            include_sound_effects=False,
        ),
    )

    stage.execute(build_context(job))

    call_kwargs = fake_production_render_service.render.call_args.kwargs
    reached_types = {track.track_type for track in call_kwargs["audio_timeline"].tracks}

    assert reached_types == {
        AudioTrackType.NATIVE_CLIP,
        AudioTrackType.BACKGROUND_MUSIC,
    }


def test_all_audio_toggles_off_renders_without_audio_rather_than_failing() -> None:
    """
    REQ-13: every toggle off is not an error - it's a legitimate
    "render without audio" request, already silently supported by
    RenderGraphBuilderService/FilterGraphBuilderService (see REQ-00
    Stage 1's own relaxation of the old unconditional audio-nodes
    requirement).
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = _all_track_types_timeline()

    fake_production_render_service = _fake_production_render_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        audio_inclusion_preferences=AudioInclusionPreferences(
            include_native_clip_audio=False,
            include_voiceover=False,
            include_music=False,
            include_sound_effects=False,
        ),
    )

    result = stage.execute(build_context(job))

    assert result.successful is True

    call_kwargs = fake_production_render_service.render.call_args.kwargs
    assert call_kwargs["audio_timeline"].tracks == []


def test_default_subtitles_enabled_reproduces_real_prior_behavior() -> None:
    """
    Subtitle on/off toggle: no subtitles_enabled supplied at all must
    reproduce every render's real prior behavior - subtitles always
    included (include_subtitles=True).
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    fake_production_render_service = _fake_production_render_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
    )

    stage.execute(build_context(job))

    call_kwargs = fake_production_render_service.render.call_args.kwargs
    assert call_kwargs["include_subtitles"] is True


def test_explicit_subtitles_enabled_false_reaches_the_real_render() -> None:
    """
    Subtitle on/off toggle: an explicit subtitles_enabled=False must
    genuinely reach ProductionRenderService.render() as
    include_subtitles=False - the real point of the toggle.
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    fake_production_render_service = _fake_production_render_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        subtitles_enabled=False,
    )

    stage.execute(build_context(job))

    call_kwargs = fake_production_render_service.render.call_args.kwargs
    assert call_kwargs["include_subtitles"] is False


def _fake_top10_countdown_service() -> MagicMock:
    fake = MagicMock()
    fake.build.return_value = RenderResult(
        success=True,
        output_file="outputs/countdown_final.mp4",
        render_engine="ffmpeg",
        render_time_seconds=0.1,
        duration_seconds=20,
        status=RenderStatus.COMPLETED,
    )

    return fake


def _ranked_job() -> VideoJob:
    """
    REQ-12 (top10 countdown rank cards): a domain-valid job whose only
    scene carries a real Scene.list_rank (as TopTenRankAssignment
    Service would assign) plus a real AudiencePromise -
    SEOContextBuilder (the real, non-mocked call the countdown branch
    makes) requires one.
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()
    job.scenes[0].list_rank = 10

    # SEOContextBuilder (the real, non-mocked call the countdown
    # branch makes) reads research_summary directly -
    # build_job()'s own ResearchResult.model_construct() never sets
    # it (no test before this one needed a real SEOContext).
    job.research = ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
        research_summary="Real research summary for the countdown test.",
    )

    job.audience_promise = AudiencePromise(
        topic=job.topic,
        target_audience="General audience.",
        platform="youtube",
        genre_id="genre.top10",
        target_duration_seconds=10,
        intended_emotion="Excitement.",
        central_curiosity="What's really at the top of this list?",
        primary_question="Which item takes the top spot?",
        viewer_benefit="A ranked, entertaining countdown.",
        expected_payoff="A clear, satisfying number one reveal.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="test-1.0",
    )

    return job


def test_ranked_job_with_countdown_service_configured_uses_countdown_render() -> None:
    """
    REQ-12: a job whose scenes carry a real Scene.list_rank, with a
    real top10_countdown_service configured, must render through
    Top10CountdownService.build() instead of the normal composite
    ProductionRenderService.render() path - the countdown REPLACES the
    render for this job, it does not run alongside it.
    """

    job = _ranked_job()

    fake_production_render_service = _fake_production_render_service()
    fake_top10_countdown_service = _fake_top10_countdown_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        genre_id="genre.top10",
        top10_countdown_service=fake_top10_countdown_service,
    )

    result = stage.execute(build_context(job))

    assert result.successful is True
    fake_top10_countdown_service.build.assert_called_once()
    fake_production_render_service.render.assert_not_called()

    call_kwargs = fake_top10_countdown_service.build.call_args.kwargs
    assert call_kwargs["scenes"] == job.scenes
    assert (
        call_kwargs["output_file"] == fake_production_render_service.DEFAULT_OUTPUT_FILE
    )


def test_ranked_job_without_countdown_service_falls_back_to_normal_render() -> None:
    """
    REQ-12: a genuinely ranked job must still render successfully
    (through the normal composite path) when no top10_countdown_
    service was ever configured for this runtime - a real, disclosed
    fallback, never a hard failure.
    """

    job = _ranked_job()

    fake_production_render_service = _fake_production_render_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        genre_id="genre.top10",
    )

    result = stage.execute(build_context(job))

    assert result.successful is True
    fake_production_render_service.render.assert_called_once()


def test_unranked_job_never_calls_countdown_service_even_when_configured() -> None:
    """
    REQ-12: a normal, unranked job must render through the normal
    composite path even when a real top10_countdown_service IS
    configured for this runtime - the branch is keyed on the job's
    own real Scene.list_rank, never on whether the service exists.
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    fake_production_render_service = _fake_production_render_service()
    fake_top10_countdown_service = _fake_top10_countdown_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        genre_id="genre.documentary",
        top10_countdown_service=fake_top10_countdown_service,
    )

    result = stage.execute(build_context(job))

    assert result.successful is True
    fake_production_render_service.render.assert_called_once()
    fake_top10_countdown_service.build.assert_not_called()


def test_ranked_job_with_countdown_service_but_no_genre_id_raises() -> None:
    """
    REQ-12: a countdown render genuinely needs a real genre id (to
    build a real SEOContext) - a caller that configured the service
    but never forwarded a genre id gets a real exception, matching
    this stage's own documented policy ("unexpected renderer
    exceptions intentionally cross this adapter boundary") rather than
    a silently-swallowed failure.
    """

    job = _ranked_job()

    fake_production_render_service = _fake_production_render_service()
    fake_top10_countdown_service = _fake_top10_countdown_service()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
        top10_countdown_service=fake_top10_countdown_service,
    )

    try:
        stage.execute(build_context(job))
    except RuntimeError as error:
        assert "genre id" in str(error)
    else:
        raise AssertionError("Expected a RuntimeError for the missing genre id.")

    fake_top10_countdown_service.build.assert_not_called()


def test_execute_video_only_writes_video_only_render_result_not_render_result() -> None:
    """
    REQ-00 Stage 1: execute_video_only() must call
    ProductionRenderService.render_video_only() (not .render()) and
    store the result on VideoJob.video_only_render_result - the real,
    final render_result field must stay untouched, since Stage 2/3
    don't exist yet and render_result still means the only thing
    anything today treats as "the finished video".
    """

    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    fake_production_render_service = MagicMock()
    fake_production_render_service.render_video_only.return_value = RenderResult(
        success=True,
        output_file="outputs/test_video_only.mp4",
        render_engine="ffmpeg",
        render_time_seconds=0.1,
        duration_seconds=10,
        status=RenderStatus.COMPLETED,
    )

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
    )

    context = build_context(job)

    result = stage.execute_video_only(context)

    assert result.status == PipelineStageStatus.COMPLETED

    fake_production_render_service.render_video_only.assert_called_once()

    fake_production_render_service.render.assert_not_called()

    assert context.job.video_only_render_result is not None

    assert context.job.video_only_render_result.output_file == (
        "outputs/test_video_only.mp4"
    )

    assert context.job.render_result is None


def test_execute_video_only_without_production_render_service_fails_cleanly() -> None:
    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    stage = RenderPipelineStage()

    context = build_context(job)

    result = stage.execute_video_only(context)

    assert result.status == PipelineStageStatus.FAILED

    assert context.job.video_only_render_result is None


def test_execute_video_only_without_audio_timeline_fails_cleanly() -> None:
    job = build_job()
    job.voice_file = "assets/audio/test_voice.wav"

    fake_production_render_service = MagicMock()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
    )

    context = build_context(job)

    result = stage.execute_video_only(context)

    assert result.status == PipelineStageStatus.FAILED

    fake_production_render_service.render_video_only.assert_not_called()


def test_execute_video_only_without_timeline_fails_cleanly() -> None:
    job = build_job(include_timeline=False)
    job.voice_file = "assets/audio/test_voice.wav"
    job.audio_timeline = AudioTimeline()

    fake_production_render_service = MagicMock()

    stage = RenderPipelineStage(
        production_render_service=fake_production_render_service,
        voice_blueprints=[MagicMock()],
    )

    context = build_context(job)

    result = stage.execute_video_only(context)

    assert result.status == PipelineStageStatus.FAILED

    fake_production_render_service.render_video_only.assert_not_called()


def main() -> None:
    print()
    print("Running Render Pipeline Stage tests...")
    print()

    test_stage_name()
    test_successful_render()
    test_failed_render()
    test_missing_timeline_fails()
    test_empty_timeline_fails()
    test_render_exception_propagates()
    test_default_render_service()
    test_progress_callback_reaches_production_render_service()
    test_execute_video_only_writes_video_only_render_result_not_render_result()
    test_execute_video_only_without_production_render_service_fails_cleanly()
    test_execute_video_only_without_audio_timeline_fails_cleanly()
    test_execute_video_only_without_timeline_fails_cleanly()

    print("Render Pipeline Stage tests " "completed successfully.")


if __name__ == "__main__":
    main()
