from __future__ import annotations

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


class SuccessfulRenderService(
    RenderService
):
    """Deterministic successful render service."""

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:
        return RenderResult(
            success=True,
            output_file=(
                "outputs/test_render.mp4"
            ),
            render_engine="synthetic",
            render_time_seconds=0.25,
            duration_seconds=int(
                timeline.calculate_duration()
            ),
            status=RenderStatus.COMPLETED,
            warnings=[
                "Synthetic render warning.",
            ],
        )


class FailedRenderService(
    RenderService
):
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
            duration_seconds=int(
                timeline.calculate_duration()
            ),
            status=RenderStatus.FAILED,
            warnings=[
                "Synthetic failure warning.",
            ],
            error_message=(
                "Synthetic render failure."
            ),
        )


class RaisingRenderService(
    RenderService
):
    """Render service used to verify exception propagation."""

    def render(
        self,
        timeline: VideoTimeline,
    ) -> RenderResult:
        raise RuntimeError(
            "Synthetic render exception."
        )


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
        content=(
            "Synthetic narration for "
            "render-stage testing."
        ),
        prompt_version="test-1.0",
        word_count=5,
        estimated_duration_seconds=10,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title="Render Scene",
        narration=(
            "Synthetic narration for "
            "render-stage testing."
        ),
        visual_prompt=(
            "Synthetic render-stage visual."
        ),
        estimated_duration_seconds=10,
        manual_file_path=(
            "assets/videos/manual/"
            "render_stage_test.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=SceneStatus.READY,
    )

    clip = VideoClip(
        scene_number=1,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=10,
        prompt=(
            "Synthetic render-stage clip."
        ),
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            "render_stage_test.mp4"
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
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
        job.video_timeline = (
            VideoTimeline(
                clips=[
                    clip,
                ],
            )
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
            current_stage=(
                PipelineStageName.RENDER
            ),
        ),
        dry_run=True,
    )


def test_stage_name() -> None:
    stage = RenderPipelineStage()

    assert (
        stage.stage_name
        == PipelineStageName.RENDER
    )


def test_successful_render() -> None:
    job = build_job()

    context = build_context(
        job
    )

    stage = RenderPipelineStage(
        render_service=(
            SuccessfulRenderService()
        ),
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert result.successful is True

    assert (
        context.job.render_result
        is not None
    )

    assert (
        context.job.render_result.success
        is True
    )

    assert (
        context.job.render_result.output_file
        == "outputs/test_render.mp4"
    )

    assert result.errors == []

    assert result.warnings == [
        "Synthetic render warning.",
    ]

    assert (
        result.metadata[
            "render_engine"
        ]
        == "synthetic"
    )

    assert (
        result.metadata[
            "output_file"
        ]
        == "outputs/test_render.mp4"
    )


def test_failed_render() -> None:
    job = build_job()

    context = build_context(
        job
    )

    stage = RenderPipelineStage(
        render_service=(
            FailedRenderService()
        ),
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.successful is False

    assert (
        context.job.render_result
        is not None
    )

    assert (
        context.job.render_result.success
        is False
    )

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

    context = build_context(
        job
    )

    stage = RenderPipelineStage(
        render_service=(
            SuccessfulRenderService()
        ),
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert (
        result.errors
        == [
            (
                "Render stage requires "
                "VideoJob.video_timeline."
            ),
        ]
    )

    assert (
        context.job.render_result
        is None
    )


def test_empty_timeline_fails() -> None:
    job = build_job(
        include_timeline=False,
    )

    job.video_timeline = (
        VideoTimeline()
    )

    context = build_context(
        job
    )

    stage = RenderPipelineStage(
        render_service=(
            SuccessfulRenderService()
        ),
    )

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.FAILED
    )

    assert result.errors == [
        (
            "Render stage requires a "
            "non-empty video timeline."
        ),
    ]


def test_render_exception_propagates() -> None:
    job = build_job()

    context = build_context(
        job
    )

    stage = RenderPipelineStage(
        render_service=(
            RaisingRenderService()
        ),
    )

    try:
        stage.execute(
            context
        )
    except RuntimeError as error:
        assert (
            str(error)
            == (
                "Synthetic render "
                "exception."
            )
        )
    else:
        raise AssertionError(
            "Unexpected RenderService "
            "exceptions must propagate."
        )


def test_default_render_service() -> None:
    job = build_job()

    context = build_context(
        job
    )

    stage = RenderPipelineStage()

    result = stage.execute(
        context
    )

    assert (
        result.status
        == PipelineStageStatus.COMPLETED
    )

    assert (
        context.job.render_result
        is not None
    )

    assert (
        context.job.render_result.success
        is True
    )


def main() -> None:
    print()
    print(
        "Running Render Pipeline Stage tests..."
    )
    print()

    test_stage_name()
    test_successful_render()
    test_failed_render()
    test_missing_timeline_fails()
    test_empty_timeline_fails()
    test_render_exception_propagates()
    test_default_render_service()

    print(
        "Render Pipeline Stage tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()