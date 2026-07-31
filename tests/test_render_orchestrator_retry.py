from __future__ import annotations

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.audio_timeline import AudioTimeline
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


class RetryRenderStage(
    BasePipelineStage
):
    """
    Deterministic render stage used for orchestration retry tests.

    The stage explicitly fails for a configured number of executions
    before producing a valid render result.
    """

    def __init__(
        self,
        *,
        failures_before_success: int,
    ) -> None:
        if failures_before_success < 0:
            raise ValueError(
                "Failures before success cannot "
                "be negative."
            )

        self._failures_before_success = (
            failures_before_success
        )

        self.execution_count = 0
        self.before_count = 0
        self.after_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.RENDER

    def before_execute(
        self,
        context: StageContext,
    ) -> None:
        del context

        self.before_count += 1

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        self.execution_count += 1

        if (
            self.execution_count
            <= self._failures_before_success
        ):
            return StageResult(
                stage=self.stage_name,
                status=(
                    PipelineStageStatus.FAILED
                ),
                errors=[
                    (
                        "Synthetic retryable render "
                        f"failure {self.execution_count}."
                    ),
                ],
            )

        prepare_render_ready_job(
            context.job
        )

        context.job.render_result = (
            RenderResult(
                success=True,
                output_file=(
                    "outputs/"
                    "retry_render.mp4"
                ),
                render_engine=(
                    "synthetic"
                ),
                render_time_seconds=0.1,
                duration_seconds=30,
                status=(
                    RenderStatus.COMPLETED
                ),
            )
        )

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.COMPLETED
            ),
        )

    def after_execute(
        self,
        context: StageContext,
        result: StageResult,
    ) -> None:
        del context
        del result

        self.after_count += 1


def build_job() -> VideoJob:
    """Create the minimum valid orchestration retry job."""

    return VideoJob(
        project_name=(
            "Render Retry Integration"
        ),
        channel_name="Mission Channel",
        niche="automation",
        topic=(
            "Render retry orchestration"
        ),
        status=JobStatus.PENDING,
        current_stage=WorkflowStage.RENDER,
    )


def prepare_render_ready_job(
    job: VideoJob,
) -> None:
    """
    Populate the valid upstream state required before attaching a
    RenderResult.

    This intentionally mirrors the already-tested orchestration fixture
    rather than bypassing VideoJob validation.
    """

    research = (
        ResearchResult.model_construct(
            status=(
                ResearchStatus.APPROVED
            ),
        )
    )

    script = Script(
        title=(
            "Synthetic retry orchestration script"
        ),
        content=(
            "Synthetic narration for render "
            "retry orchestration testing."
        ),
        prompt_version="test-1.0",
        word_count=7,
        estimated_duration_seconds=30,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title=(
            "Synthetic Retry Scene"
        ),
        narration=(
            "Synthetic narration for render "
            "retry orchestration testing."
        ),
        visual_prompt=(
            "Synthetic retry orchestration visual."
        ),
        estimated_duration_seconds=30,
        manual_file_path=(
            "assets/videos/manual/"
            "retry_test_scene.mp4"
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
        duration_seconds=30,
        prompt=(
            "Synthetic retry orchestration "
            "test scene."
        ),
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            "retry_test_scene.mp4"
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

    job.voice_file = (
        "assets/audio/"
        "retry_test_voice.wav"
    )

    job.video_clips = [
        clip,
    ]

    job.video_timeline = (
        VideoTimeline(
            clips=[
                clip,
            ],
        )
    )

    job.video_timeline.calculate_duration()

    job.audio_timeline = (
        AudioTimeline()
    )


def build_settings(
    *,
    maximum_retries: int,
    dry_run: bool = True,
) -> AdvancedSettings:
    """Build retry-enabled orchestration settings."""

    return AdvancedSettings(
        dry_run=dry_run,
        retry_failed_stages=True,
        maximum_stage_retries=(
            maximum_retries
        ),
    )


def test_settings_are_exposed() -> None:
    settings = build_settings(
        maximum_retries=2
    )

    service = (
        RenderOrchestratorService(
            stages=[
                RetryRenderStage(
                    failures_before_success=0,
                ),
            ],
            advanced_settings=settings,
        )
    )

    assert (
        service.advanced_settings
        is settings
    )


def test_orchestrator_retries_failed_stage() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=1,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
            advanced_settings=(
                build_settings(
                    maximum_retries=3
                )
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        stage.execution_count
        == 2
    )

    assert (
        stage.before_count
        == 2
    )

    assert (
        stage.after_count
        == 2
    )

    assert (
        job.retry_count
        == 1
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
        job.render_result
        is not None
    )

    assert (
        job.render_result.success
        is True
    )


def test_retry_count_reaches_metadata() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=2,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
            advanced_settings=(
                build_settings(
                    maximum_retries=3
                )
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        stage.execution_count
        == 3
    )

    assert (
        job.retry_count
        == 2
    )

    assert (
        result.metadata[
            "job_retry_count"
        ]
        == 2
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

    assert (
        result.metadata[
            "pipeline_progress_percent"
        ]
        == 100
    )


def test_retry_limit_failure_is_normalized() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=10,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
            advanced_settings=(
                build_settings(
                    maximum_retries=2
                )
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        stage.execution_count
        == 3
    )

    assert (
        stage.before_count
        == 3
    )

    assert (
        stage.after_count
        == 3
    )

    assert (
        job.retry_count
        == 2
    )

    assert (
        job.status
        == JobStatus.FAILED
    )

    assert (
        job.current_stage
        == WorkflowStage.RENDER
    )

    assert (
        result.failed_stage
        == WorkflowStage.RENDER
    )

    assert (
        "Synthetic retryable render failure 3."
        in result.errors
    )

    assert (
        result.metadata[
            "job_retry_count"
        ]
        == 2
    )


def test_no_settings_preserves_old_behavior() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=1,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
        )
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        stage.execution_count
        == 1
    )

    assert (
        stage.before_count
        == 1
    )

    assert (
        stage.after_count
        == 1
    )

    assert (
        job.retry_count
        == 0
    )

    assert (
        job.status
        == JobStatus.FAILED
    )


def test_settings_dry_run_takes_precedence() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=0,
    )

    settings = build_settings(
        maximum_retries=1,
        dry_run=True,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
            advanced_settings=settings,
        )
    )

    result = service.execute(
        job,
        dry_run=False,
    )

    assert result.success is True

    assert (
        result.metadata[
            "dry_run"
        ]
        is True
    )


def test_execute_dry_run_used_without_settings() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=0,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
        )
    )

    result = service.execute(
        job,
        dry_run=True,
    )

    assert result.success is True

    assert (
        result.metadata[
            "dry_run"
        ]
        is True
    )


def test_successful_retry_discards_transient_error() -> None:
    job = build_job()

    stage = RetryRenderStage(
        failures_before_success=1,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                stage,
            ],
            advanced_settings=(
                build_settings(
                    maximum_retries=2
                )
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is True

    assert (
        result.errors
        == []
    )

    assert (
        job.errors
        == []
    )


def main() -> None:
    print()
    print(
        "Running Render Orchestrator "
        "Retry tests..."
    )
    print()

    test_settings_are_exposed()
    test_orchestrator_retries_failed_stage()
    test_retry_count_reaches_metadata()
    test_retry_limit_failure_is_normalized()
    test_no_settings_preserves_old_behavior()
    test_settings_dry_run_takes_precedence()
    test_execute_dry_run_used_without_settings()
    (
        test_successful_retry_discards_transient_error()
    )

    print()
    print(
        "Render Orchestrator Retry tests "
        "completed successfully."
    )


if __name__ == "__main__":
    main()