from __future__ import annotations

from pathlib import Path

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
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)


class SuccessfulVoiceStage(
    BasePipelineStage
):
    """Synthetic voice stage used to verify resume skipping."""

    def __init__(
        self,
    ) -> None:
        self.execution_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.VOICE

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        del context

        self.execution_count += 1

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.COMPLETED
            ),
        )


class FailingRenderStage(
    BasePipelineStage
):
    """Synthetic render stage for the initial failed execution."""

    def __init__(
        self,
    ) -> None:
        self.execution_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.RENDER

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        del context

        self.execution_count += 1

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus.FAILED
            ),
            errors=[
                "Synthetic persisted render failure.",
            ],
        )


class SuccessfulRenderStage(
    BasePipelineStage
):
    """Synthetic render stage used after checkpoint restoration."""

    def __init__(
        self,
    ) -> None:
        self.execution_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return PipelineStageName.RENDER

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        self.execution_count += 1

        prepare_render_ready_job(
            context.job
        )

        context.job.render_result = (
            RenderResult(
                success=True,
                output_file=(
                    "outputs/"
                    "resumed_final_video.mp4"
                ),
                render_engine="synthetic",
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


def build_job() -> VideoJob:
    """Build the central VideoJob shared across the resume cycle."""

    return VideoJob(
        project_name=(
            "Persisted Resume Integration"
        ),
        channel_name="Mission Channel",
        niche="automation",
        topic=(
            "Persisted checkpoint resume"
        ),
        status=JobStatus.PENDING,
        current_stage=WorkflowStage.VOICE,
    )


def build_settings() -> AdvancedSettings:
    """
    Build deterministic checkpoint/resume settings.

    Automatic retry is disabled so the first failed run produces the
    checkpoint immediately rather than consuming stage retries first.
    """

    return AdvancedSettings(
        dry_run=True,
        resume_previous_pipeline=True,
        skip_completed_stages=True,
        save_pipeline_state=True,
        retry_failed_stages=False,
        maximum_stage_retries=0,
        stop_on_stage_failure=True,
    )


def build_storage(
    root: Path,
) -> PipelineCheckpointStorageService:
    """Build isolated checkpoint persistence."""

    return (
        PipelineCheckpointStorageService(
            storage_root=(
                root
                / "checkpoints"
            ),
        )
    )


def prepare_render_ready_job(
    job: VideoJob,
) -> None:
    """
    Populate the valid upstream state required before attaching a
    successful RenderResult.

    This mirrors the already-established valid VideoJob dependency chain.
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
            "Persisted resume integration script"
        ),
        content=(
            "Synthetic narration for persisted "
            "checkpoint resume testing."
        ),
        prompt_version="test-1.0",
        word_count=7,
        estimated_duration_seconds=30,
        status=ScriptStatus.APPROVED,
    )

    scene = Scene(
        scene_number=1,
        title=(
            "Persisted Resume Scene"
        ),
        narration=(
            "Synthetic narration for persisted "
            "checkpoint resume testing."
        ),
        visual_prompt=(
            "Synthetic checkpoint resume visual."
        ),
        estimated_duration_seconds=30,
        manual_file_path=(
            "assets/videos/manual/"
            "checkpoint_resume_scene.mp4"
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
            "Synthetic persisted checkpoint "
            "resume test scene."
        ),
        provider="Manual Upload",
        local_file=(
            "assets/videos/manual/"
            "checkpoint_resume_scene.mp4"
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
        "checkpoint_resume_voice.wav"
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


def test_failed_run_persists_resumable_checkpoint(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    voice_stage = (
        SuccessfulVoiceStage()
    )

    render_stage = (
        FailingRenderStage()
    )

    service = (
        RenderOrchestratorService(
            stages=[
                voice_stage,
                render_stage,
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    result = service.execute(
        job
    )

    assert result.success is False

    assert (
        job.status
        == JobStatus.FAILED
    )

    assert (
        result.failed_stage
        == WorkflowStage.RENDER
    )

    assert (
        voice_stage.execution_count
        == 1
    )

    assert (
        render_stage.execution_count
        == 1
    )

    checkpoints = (
        storage.list_for_job(
            job_id=job.id,
        )
    )

    assert (
        len(checkpoints)
        == 1
    )

    checkpoint = (
        checkpoints[0]
    )

    assert (
        checkpoint.resumable
        is True
    )

    assert (
        checkpoint.failed_stage
        == PipelineStageName.RENDER
    )

    assert (
        checkpoint.completed_stages
        == [
            PipelineStageName.VOICE,
        ]
    )

    assert (
        result.metadata[
            "persisted_checkpoint_id"
        ]
        == str(
            checkpoint.checkpoint_id
        )
    )


def test_new_orchestrator_resumes_latest_checkpoint(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_voice_stage = (
        SuccessfulVoiceStage()
    )

    first_render_stage = (
        FailingRenderStage()
    )

    first_service = (
        RenderOrchestratorService(
            stages=[
                first_voice_stage,
                first_render_stage,
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    first_result = (
        first_service.execute(
            job
        )
    )

    assert (
        first_result.success
        is False
    )

    failed_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert (
        failed_checkpoint
        is not None
    )

    assert (
        failed_checkpoint.failed_stage
        == PipelineStageName.RENDER
    )

    second_voice_stage = (
        SuccessfulVoiceStage()
    )

    second_render_stage = (
        SuccessfulRenderStage()
    )

    # A brand-new orchestrator instance simulates restart of the
    # orchestration runtime. The persisted PipelineCheckpoint is the
    # source of pipeline execution history.
    second_service = (
        RenderOrchestratorService(
            stages=[
                second_voice_stage,
                second_render_stage,
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    second_result = (
        second_service.execute(
            job
        )
    )

    assert (
        second_result.success
        is True
    )

    # VOICE completed before the checkpoint, so it must not execute in
    # the resumed orchestration.
    assert (
        second_voice_stage.execution_count
        == 0
    )

    assert (
        second_render_stage.execution_count
        == 1
    )

    assert (
        job.status
        == JobStatus.COMPLETED
    )

    assert (
        job.current_stage
        == (
            WorkflowStage
            .READY_FOR_UPLOAD
        )
    )

    assert (
        job.render_result
        is not None
    )

    assert (
        job.render_result.success
        is True
    )

    assert (
        second_result.metadata[
            "resumed"
        ]
        is True
    )

    assert (
        second_result.metadata[
            "resume_stage"
        ]
        == PipelineStageName.RENDER.value
    )

    assert (
        second_result.metadata[
            "loaded_checkpoint_id"
        ]
        == str(
            failed_checkpoint
            .checkpoint_id
        )
    )


def test_successful_resume_persists_new_checkpoint(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                FailingRenderStage(),
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    first_result = (
        first_service.execute(
            job
        )
    )

    assert (
        first_result.success
        is False
    )

    failed_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert (
        failed_checkpoint
        is not None
    )

    second_service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                SuccessfulRenderStage(),
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    result = second_service.execute(
        job
    )

    assert (
        result.success
        is True
    )

    checkpoints = (
        storage.list_for_job(
            job_id=job.id,
        )
    )

    assert (
        len(checkpoints)
        == 2
    )

    latest = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert latest is not None

    assert (
        latest.checkpoint_id
        != failed_checkpoint.checkpoint_id
    )

    assert (
        latest.resumable
        is False
    )

    assert (
        latest.failed_stage
        is None
    )

    assert (
        latest.waiting_stage
        is None
    )

    assert (
        latest.completed_stages
        == [
            PipelineStageName.VOICE,
            PipelineStageName.RENDER,
        ]
    )

    assert (
        result.metadata[
            "persisted_checkpoint_id"
        ]
        == str(
            latest.checkpoint_id
        )
    )


def test_resume_checkpoint_preserves_execution_history(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                FailingRenderStage(),
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    first_service.execute(
        job
    )

    first_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert (
        first_checkpoint
        is not None
    )

    first_history_count = len(
        first_checkpoint.stage_results
    )

    second_service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                SuccessfulRenderStage(),
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    result = second_service.execute(
        job
    )

    assert (
        result.success
        is True
    )

    latest = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert latest is not None

    # Current resumed run contributes:
    # - one synthetic VOICE SKIPPED result;
    # - one successful RENDER result.
    assert (
        len(
            latest.stage_results
        )
        == first_history_count + 2
    )

    render_results = [
        stage_result
        for stage_result
        in latest.stage_results
        if (
            stage_result.stage
            == PipelineStageName.RENDER
        )
    ]

    assert [
        stage_result.status
        for stage_result
        in render_results
    ] == [
        PipelineStageStatus.FAILED,
        PipelineStageStatus.COMPLETED,
    ]

    assert (
        PipelineStageName.VOICE
        in latest.completed_stages
    )

    assert (
        PipelineStageName.VOICE
        not in latest.skipped_stages
    )


def test_explicit_checkpoint_id_can_be_resumed(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                FailingRenderStage(),
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    first_service.execute(
        job
    )

    checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert checkpoint is not None

    resumed_voice = (
        SuccessfulVoiceStage()
    )

    resumed_render = (
        SuccessfulRenderStage()
    )

    second_service = (
        RenderOrchestratorService(
            stages=[
                resumed_voice,
                resumed_render,
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    result = second_service.execute(
        job,
        checkpoint_id=(
            checkpoint.checkpoint_id
        ),
    )

    assert result.success is True

    assert (
        resumed_voice.execution_count
        == 0
    )

    assert (
        resumed_render.execution_count
        == 1
    )

    assert (
        result.metadata[
            "loaded_checkpoint_id"
        ]
        == str(
            checkpoint.checkpoint_id
        )
    )


def test_missing_explicit_checkpoint_fails_cleanly(
    tmp_path: Path,
) -> None:
    from uuid import uuid4

    job = build_job()

    storage = build_storage(
        tmp_path
    )

    service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                SuccessfulRenderStage(),
            ],
            advanced_settings=(
                build_settings()
            ),
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    result = service.execute(
        job,
        checkpoint_id=uuid4(),
    )

    assert (
        result.success
        is False
    )

    assert (
        job.status
        == JobStatus.FAILED
    )

    assert (
        "does not exist"
        in result.errors[-1]
    )

    assert (
        result.metadata[
            "checkpoint_phase"
        ]
        == "resume_preparation"
    )


def test_save_pipeline_state_false_does_not_persist(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    settings = AdvancedSettings(
        dry_run=True,
        resume_previous_pipeline=True,
        skip_completed_stages=True,
        save_pipeline_state=False,
        retry_failed_stages=False,
        maximum_stage_retries=0,
        stop_on_stage_failure=True,
    )

    service = (
        RenderOrchestratorService(
            stages=[
                SuccessfulVoiceStage(),
                FailingRenderStage(),
            ],
            advanced_settings=settings,
            checkpoint_storage_service=(
                storage
            ),
        )
    )

    result = service.execute(
        job
    )

    assert (
        result.success
        is False
    )

    assert (
        storage.list_for_job(
            job_id=job.id,
        )
        == []
    )

    assert (
        result.metadata.get(
            "persisted_checkpoint_id"
        )
        is None
    )


def main() -> None:
    print()
    print(
        "Running Render Orchestrator "
        "Checkpoint Resume tests..."
    )
    print()

    print(
        "Run this suite with pytest because "
        "it uses the tmp_path fixture."
    )


if __name__ == "__main__":
    main()