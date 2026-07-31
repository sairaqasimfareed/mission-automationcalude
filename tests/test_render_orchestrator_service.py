from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.enums import (
    JobStatus,
    WorkflowStage,
)
from src.models.media_strategy import (
    SceneSourceStatus,
    SceneSourceType,
)
from src.models.render_orchestration_result import (
    RenderOrchestrationResult,
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
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)


def build_job() -> VideoJob:
    """Create the minimum valid orchestration test job."""

    return VideoJob(
        project_name="Mission Test",
        channel_name="Mission Channel",
        niche="automation",
        topic="Render orchestration test",
        status=JobStatus.PENDING,
        current_stage=WorkflowStage.RESEARCH,
    )


def prepare_render_ready_job(
    job: VideoJob,
) -> None:
    """
    Populate the minimum valid upstream state required by VideoJob
    before attaching a render result.
    """

    research = ResearchResult.model_construct(
        status=ResearchStatus.APPROVED,
    )

    script = Script(
        title="Synthetic orchestration script",
        content=(
            "Synthetic narration for render "
            "orchestration testing."
        ),
        prompt_version="test-1.0",
        word_count=6,
        estimated_duration_seconds=30,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title="Synthetic Scene",
        narration=(
            "Synthetic narration for render "
            "orchestration testing."
        ),
        visual_prompt=(
            "Synthetic orchestration visual."
        ),
        estimated_duration_seconds=30,
        manual_file_path=(
            "assets/videos/manual/test_scene.mp4"
        ),
        source_status=SceneSourceStatus.READY,
        status=SceneStatus.READY,
    )

    clip = VideoClip(
        scene_number=1,
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=30,
        prompt=(
            "Synthetic orchestration test scene."
        ),
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/test_scene.mp4"
        ),
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )

    job.research = research
    job.script = script

    job.scenes = [
        scene,
    ]

    job.voice_file = (
        "assets/audio/test_voice.wav"
    )

    job.video_clips = [
        clip,
    ]

    job.video_timeline = VideoTimeline(
        clips=[
            clip,
        ],
    )

    job.video_timeline.calculate_duration()

    job.audio_timeline = AudioTimeline()


class SyntheticStage(
    BasePipelineStage
):
    """Deterministic pipeline stage used by orchestrator tests."""

    def __init__(
        self,
        *,
        stage_name: PipelineStageName,
        status: PipelineStageStatus = (
            PipelineStageStatus.COMPLETED
        ),
        warnings: list[str] | None = None,
        errors: list[str] | None = None,
        raise_error: Exception | None = None,
        attach_render_result: bool = False,
    ) -> None:
        self._stage_name = stage_name
        self._status = status
        self._warnings = (
            warnings or []
        )
        self._errors = (
            errors or []
        )
        self._raise_error = (
            raise_error
        )
        self._attach_render_result = (
            attach_render_result
        )

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return self._stage_name

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        if (
            self._raise_error
            is not None
        ):
            raise self._raise_error

        if self._attach_render_result:
            prepare_render_ready_job(
                context.job
            )

            context.job.render_result = (
                RenderResult(
                    success=True,
                    output_file=(
                        "outputs/"
                        "final_video.mp4"
                    ),
                    render_engine="ffmpeg",
                    render_time_seconds=0.1,
                    duration_seconds=30,
                    status=(
                        RenderStatus.COMPLETED
                    ),
                )
            )

        return StageResult(
            stage=self.stage_name,
            status=self._status,
            duration_seconds=0.01,
            warnings=list(
                self._warnings
            ),
            errors=list(
                self._errors
            ),
        )


class FailedRenderStage(
    BasePipelineStage
):
    """Synthetic render stage returning a failed RenderResult."""

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return (
            PipelineStageName.RENDER
        )

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        prepare_render_ready_job(
            context.job
        )

        context.job.render_result = (
            RenderResult(
                success=False,
                output_file=None,
                render_engine="ffmpeg",
                render_time_seconds=0.1,
                duration_seconds=0,
                status=RenderStatus.FAILED,
                error_message=(
                    "Synthetic render failure."
                ),
            )
        )

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.COMPLETED
            ),
        )


def test_requires_at_least_one_stage() -> None:
    try:
        RenderOrchestratorService(
            stages=[],
        )
    except ValueError as error:
        assert (
            "at least one pipeline stage"
            in str(error)
        )
    else:
        raise AssertionError(
            "Empty stage registration "
            "must fail."
        )


def test_duplicate_stage_rejected() -> None:
    stage_a = SyntheticStage(
        stage_name=(
            PipelineStageName.RENDER
        ),
    )

    stage_b = SyntheticStage(
        stage_name=(
            PipelineStageName.RENDER
        ),
    )

    try:
        RenderOrchestratorService(
            stages=[
                stage_a,
                stage_b,
            ],
        )
    except ValueError as error:
        assert (
            "duplicate pipeline stage"
            in str(error)
        )
    else:
        raise AssertionError(
            "Duplicate stages must fail."
        )


def test_registered_stage_order_is_preserved() -> None:
    stages = [
        SyntheticStage(
            stage_name=(
                PipelineStageName
                .ASSET_SELECTION
            ),
        ),
        SyntheticStage(
            stage_name=(
                PipelineStageName
                .VIDEO_TIMELINE
            ),
        ),
        SyntheticStage(
            stage_name=(
                PipelineStageName.RENDER
            ),
        ),
    ]

    service = RenderOrchestratorService(
        stages=stages,
    )

    assert [
        stage.stage_name
        for stage in service.stages
    ] == [
        PipelineStageName.ASSET_SELECTION,
        PipelineStageName.VIDEO_TIMELINE,
        PipelineStageName.RENDER,
    ]


def test_successful_orchestration() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                attach_render_result=True,
            ),
        ],
    )

    result = service.execute(
        job,
        dry_run=True,
    )

    assert isinstance(
        result,
        RenderOrchestrationResult,
    )

    assert result.success is True

    assert (
        result.status
        == JobStatus.COMPLETED
    )

    assert (
        result.current_stage
        == WorkflowStage.READY_FOR_UPLOAD
    )

    assert (
        job.status
        == JobStatus.COMPLETED
    )

    assert (
        job.current_stage
        == WorkflowStage.READY_FOR_UPLOAD
    )

    assert (
        WorkflowStage.RENDER
        in result.completed_stages
    )

    assert (
        result.metadata[
            "dry_run"
        ]
        is True
    )

    assert (
        result.metadata[
            "pipeline_stage_count"
        ]
        == 1
    )


def test_failed_stage_result() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                status=(
                    PipelineStageStatus.FAILED
                ),
                errors=[
                    (
                        "Synthetic render "
                        "stage failure."
                    ),
                ],
            ),
        ],
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        result.status
        == JobStatus.FAILED
    )

    assert (
        result.failed_stage
        == WorkflowStage.RENDER
    )

    assert (
        "Synthetic render stage failure."
        in result.errors
    )

    assert (
        "Synthetic render stage failure."
        in job.errors
    )


def test_stage_exception_is_normalized() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                raise_error=RuntimeError(
                    "Synthetic exception."
                ),
            ),
        ],
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        result.status
        == JobStatus.FAILED
    )

    assert (
        result.failed_stage
        == WorkflowStage.RENDER
    )

    assert (
        "RuntimeError"
        in result.errors[-1]
    )

    assert (
        "Synthetic exception."
        in result.errors[-1]
    )

    assert (
        result.metadata[
            "exception_type"
        ]
        == "RuntimeError"
    )


def test_stage_warnings_are_aggregated() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                warnings=[
                    "Synthetic warning.",
                    "Synthetic warning.",
                ],
                attach_render_result=True,
            ),
        ],
    )

    result = service.execute(
        job
    )

    assert (
        result.warnings
        == [
            "Synthetic warning.",
        ]
    )

    assert (
        job.warnings
        == [
            "Synthetic warning.",
        ]
    )


def test_missing_render_result_fails() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
            ),
        ],
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        result.failed_stage
        == WorkflowStage.RENDER
    )

    assert (
        "without a render result"
        in result.errors[-1]
    )


def test_failed_render_result_fails() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            FailedRenderStage(),
        ],
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        result.failed_stage
        == WorkflowStage.RENDER
    )

    assert (
        "Synthetic render failure."
        in result.errors
    )


def test_metadata_is_deterministic() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                attach_render_result=True,
            ),
        ],
    )

    result = service.execute(
        job,
        dry_run=True,
    )

    assert (
        result.metadata[
            "pipeline_progress_percent"
        ]
        == 100
    )

    assert (
        result.metadata[
            "pipeline_stage_count"
        ]
        == 1
    )

    assert (
        result.metadata[
            "pipeline_completed_stage_count"
        ]
        == 1
    )


def test_multiple_completed_stage_mapping() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName
                    .ASSET_SELECTION
                ),
            ),
            SyntheticStage(
                stage_name=(
                    PipelineStageName
                    .VIDEO_TIMELINE
                ),
            ),
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                attach_render_result=True,
            ),
        ],
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        result.completed_stages
        == [
            WorkflowStage.ASSET_GENERATION,
            WorkflowStage.EDITING,
            WorkflowStage.RENDER,
        ]
    )

    assert (
        result.metadata[
            "pipeline_stage_count"
        ]
        == 3
    )

    assert (
        result.metadata[
            "pipeline_completed_stage_count"
        ]
        == 3
    )


def test_warning_deduplication_across_stages() -> None:
    job = build_job()

    service = RenderOrchestratorService(
        stages=[
            SyntheticStage(
                stage_name=(
                    PipelineStageName
                    .ASSET_SELECTION
                ),
                warnings=[
                    "Shared warning.",
                ],
            ),
            SyntheticStage(
                stage_name=(
                    PipelineStageName.RENDER
                ),
                warnings=[
                    "Shared warning.",
                ],
                attach_render_result=True,
            ),
        ],
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        result.warnings
        == [
            "Shared warning.",
        ]
    )

    assert (
        job.warnings
        == [
            "Shared warning.",
        ]
    )


def main() -> None:
    print()
    print(
        "Running Render Orchestrator "
        "Service tests..."
    )
    print()

    test_requires_at_least_one_stage()

    test_duplicate_stage_rejected()

    test_registered_stage_order_is_preserved()

    test_successful_orchestration()

    test_failed_stage_result()

    test_stage_exception_is_normalized()

    test_stage_warnings_are_aggregated()

    test_missing_render_result_fails()

    test_failed_render_result_fails()

    test_metadata_is_deterministic()

    test_multiple_completed_stage_mapping()

    test_warning_deduplication_across_stages()

    print()
    print(
        "Render Orchestrator Service tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()