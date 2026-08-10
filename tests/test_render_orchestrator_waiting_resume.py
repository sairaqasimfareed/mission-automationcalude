from __future__ import annotations

from pathlib import Path

from src.models.advanced_settings import (
    AdvancedSettings,
)
from src.models.asset_state import (
    AssetUserDecision,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.audio_timeline import (
    AudioTimeline,
)
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
from src.models.video_job import (
    VideoJob,
)
from src.models.video_timeline import (
    VideoTimeline,
)
from src.pipeline.asset_stage import (
    AssetPipelineStage,
)
from src.pipeline.base_stage import (
    BasePipelineStage,
)
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import (
    StageContext,
)
from src.pipeline.stage_result import (
    StageResult,
)
from src.services.asset_decision_service import (
    AssetDecisionService,
)
from src.services.pipeline_checkpoint_storage_service import (
    PipelineCheckpointStorageService,
)
from src.services.render_orchestrator_service import (
    RenderOrchestratorService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


class WaitingAssetWorkflowService(
    SceneAssetWorkflowService
):
    """
    Deterministic workflow facade for waiting/resume integration tests.

    start() supplies the initial waiting state.

    apply_decision() remains the production implementation inherited
    from SceneAssetWorkflowService and delegates to the real
    AssetDecisionService.
    """

    def __init__(
        self,
    ) -> None:
        self.decision_service = (
            AssetDecisionService()
        )

        self.manual_upload_service = None
        self.visual_asset_router = None
        self.maximum_stock_results = 15

        self.start_count = 0

    def start(
        self,
        scene: Scene,
    ) -> SceneAssetState:
        self.start_count += 1

        return SceneAssetState(
            scene_id=str(
                scene.id
            ),
            scene_number=(
                scene.scene_number
            ),
            status=(
                AssetWorkflowStatus
                .WAITING_FOR_MANUAL_UPLOAD
            ),
            selected_source=(
                SceneSourceType
                .MANUAL_UPLOAD
            ),
            manual_upload_requested=True,
        )


class SuccessfulVoiceStage(
    BasePipelineStage
):
    """Completed upstream stage used to verify resume skipping."""

    def __init__(
        self,
    ) -> None:
        self.execution_count = 0

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        return (
            PipelineStageName.VOICE
        )

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


class SuccessfulRenderStage(
    BasePipelineStage
):
    """Render stage reached only after user input resolves waiting."""

    def __init__(
        self,
    ) -> None:
        self.execution_count = 0

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
        self.execution_count += 1

        prepare_render_ready_job(
            context.job
        )

        context.job.render_result = (
            RenderResult(
                success=True,
                output_file=(
                    "outputs/"
                    "waiting_resume_final.mp4"
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


def build_research() -> ResearchResult:
    """
    Build fully validated approved research.

    This fixture must survive normal Pydantic JSON serialization and
    reconstruction because restart-recovery tests recreate VideoJob
    from persisted JSON rather than reusing the in-memory object.
    """

    return ResearchResult(
        topic=(
            "Waiting-for-user checkpoint resume"
        ),
        research_summary=(
            "Synthetic approved research for "
            "waiting-for-user serialized "
            "restart recovery testing."
        ),
        prompt_version="test-1.0",
        status=(
            ResearchStatus.APPROVED
        ),
    )



def build_script() -> Script:
    return Script(
        title=(
            "Waiting Resume Test"
        ),
        content=(
            "Synthetic script content for "
            "waiting-for-user resume testing."
        ),
        prompt_version="test-1.0",
        word_count=8,
        estimated_duration_seconds=30,
        status=ScriptStatus.APPROVED,
    )


def build_scene() -> Scene:
    return Scene(
        scene_number=1,
        title=(
            "Waiting Resume Scene"
        ),
        narration=(
            "Synthetic narration for "
            "waiting resume testing."
        ),
        visual_prompt=(
            "Synthetic waiting resume visual."
        ),
        estimated_duration_seconds=30,
    )


def build_job() -> VideoJob:
    job = VideoJob(
        project_name=(
            "Waiting Resume Integration"
        ),
        channel_name="Mission Channel",
        niche="automation",
        topic=(
            "Waiting-for-user checkpoint resume"
        ),
        status=JobStatus.PENDING,
        current_stage=WorkflowStage.VOICE,
        research=build_research(),
        script=build_script(),
    )

    job.scenes = [
        build_scene(),
    ]

    return job


def build_settings() -> AdvancedSettings:
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
    Populate the remaining valid state required by successful render
    result validation.
    """

    scene = (
        job.scenes[0]
    )

    selected_state = (
        job.scene_asset_states[0]
    )

    selected_candidate = (
        selected_state
        .selected_candidate
    )

    if selected_candidate is None:
        raise AssertionError(
            "Resolved asset state requires "
            "a selected candidate."
        )

    if not selected_candidate.file_path:
        raise AssertionError(
            "Resolved asset candidate requires "
            "a file path."
        )

    scene.manual_file_path = (
        selected_candidate.file_path
    )

    scene.selected_asset_path = (
        selected_candidate.file_path
    )

    scene.source_status = (
        SceneSourceStatus.READY
    )

    scene.status = (
        SceneStatus.READY
    )

    clip = VideoClip(
        scene_number=(
            scene.scene_number
        ),
        source_type=(
            SceneSourceType.MANUAL_UPLOAD
        ),
        duration_seconds=30,
        prompt=(
            "Synthetic waiting-resume "
            "render clip."
        ),
        provider="Manual Upload",
        local_file=(
            selected_candidate.file_path
        ),
        source_status=(
            SceneSourceStatus.READY
        ),
        status=(
            VideoClipStatus.READY
        ),
    )

    job.voice_file = (
        "assets/audio/"
        "waiting_resume_voice.wav"
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


def build_orchestrator(
    *,
    storage: PipelineCheckpointStorageService,
    workflow: WaitingAssetWorkflowService,
    voice_stage: SuccessfulVoiceStage,
    render_stage: SuccessfulRenderStage,
) -> RenderOrchestratorService:
    return RenderOrchestratorService(
        stages=[
            voice_stage,
            AssetPipelineStage(
                asset_workflow_service=(
                    workflow
                ),
            ),
            render_stage,
        ],
        advanced_settings=(
            build_settings()
        ),
        checkpoint_storage_service=(
            storage
        ),
    )


def test_waiting_stage_persists_checkpoint(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    workflow = (
        WaitingAssetWorkflowService()
    )

    voice_stage = (
        SuccessfulVoiceStage()
    )

    render_stage = (
        SuccessfulRenderStage()
    )

    service = build_orchestrator(
        storage=storage,
        workflow=workflow,
        voice_stage=voice_stage,
        render_stage=render_stage,
    )

    result = service.execute(
        job
    )

    assert (
        result.success
        is False
    )

    assert (
        result.failed_stage
        == WorkflowStage.ASSET_GENERATION
    )

    assert (
        voice_stage.execution_count
        == 1
    )

    assert (
        workflow.start_count
        == 1
    )

    assert (
        render_stage.execution_count
        == 0
    )

    assert (
        len(
            job.scene_asset_states
        )
        == 1
    )

    state = (
        job.scene_asset_states[0]
    )

    assert (
        state.status
        == (
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        )
    )

    checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert (
        checkpoint
        is not None
    )

    assert (
        checkpoint.waiting_stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )

    assert (
        checkpoint.failed_stage
        is None
    )

    assert (
        PipelineStageName.VOICE
        in checkpoint.completed_stages
    )

    assert (
        checkpoint.resumable
        is True
    )


def test_resume_applies_manual_upload_decision(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_workflow = (
        WaitingAssetWorkflowService()
    )

    first_voice = (
        SuccessfulVoiceStage()
    )

    first_render = (
        SuccessfulRenderStage()
    )

    first_service = build_orchestrator(
        storage=storage,
        workflow=first_workflow,
        voice_stage=first_voice,
        render_stage=first_render,
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

    waiting_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert (
        waiting_checkpoint
        is not None
    )

    upload_file = (
        tmp_path
        / "manual_scene_1.mp4"
    )

    upload_file.write_bytes(
        b"synthetic-manual-video"
    )

    second_workflow = (
        WaitingAssetWorkflowService()
    )

    second_voice = (
        SuccessfulVoiceStage()
    )

    second_render = (
        SuccessfulRenderStage()
    )

    second_service = build_orchestrator(
        storage=storage,
        workflow=second_workflow,
        voice_stage=second_voice,
        render_stage=second_render,
    )

    second_result = (
        second_service.execute(
            job,
            user_input={
                "asset_decisions": [
                    {
                        "scene_number": 1,
                        "decision": (
                            AssetUserDecision
                            .MANUAL_UPLOAD
                            .value
                        ),
                        "manual_upload_path": (
                            str(
                                upload_file
                            )
                        ),
                    },
                ],
            },
        )
    )

    assert (
        second_result.success
        is True
    )

    # VOICE completed before the waiting checkpoint and therefore must
    # not execute again.
    assert (
        second_voice.execution_count
        == 0
    )

    # Existing asset state is resumed, so local/manual discovery must
    # not restart.
    assert (
        second_workflow.start_count
        == 0
    )

    assert (
        second_render.execution_count
        == 1
    )

    assert (
        len(
            job.scene_asset_states
        )
        == 1
    )

    resolved_state = (
        job.scene_asset_states[0]
    )

    assert (
        resolved_state.status
        == AssetWorkflowStatus.READY
    )

    assert (
        resolved_state.user_decision
        == (
            AssetUserDecision
            .MANUAL_UPLOAD
        )
    )

    assert (
        resolved_state.selected_candidate
        is not None
    )

    assert (
        resolved_state
        .selected_candidate
        .file_path
        == str(
            upload_file.resolve()
        )
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
        second_result.metadata[
            "resumed"
        ]
        is True
    )

    assert (
        second_result.metadata[
            "resume_stage"
        ]
        == (
            PipelineStageName
            .ASSET_SELECTION
            .value
        )
    )

    assert (
        second_result.metadata[
            "loaded_checkpoint_id"
        ]
        == str(
            waiting_checkpoint
            .checkpoint_id
        )
    )


def test_serialized_waiting_job_resumes_after_runtime_restart(
    tmp_path: Path,
) -> None:
    """
    Verify waiting-for-user recovery after both runtime and VideoJob
    reconstruction.

    The first execution reaches ASSET_SELECTION and persists a waiting
    checkpoint. The VideoJob is then serialized and reconstructed as a
    fresh model instance.

    A brand-new orchestrator must load the persisted checkpoint, preserve
    the waiting asset state, apply the supplied manual-upload decision,
    skip the already-completed VOICE stage, continue to RENDER, and
    complete successfully.
    """

    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_workflow = (
        WaitingAssetWorkflowService()
    )

    first_voice = (
        SuccessfulVoiceStage()
    )

    first_render = (
        SuccessfulRenderStage()
    )

    first_service = build_orchestrator(
        storage=storage,
        workflow=first_workflow,
        voice_stage=first_voice,
        render_stage=first_render,
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

    assert (
        first_voice.execution_count
        == 1
    )

    assert (
        first_workflow.start_count
        == 1
    )

    assert (
        first_render.execution_count
        == 0
    )

    waiting_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert (
        waiting_checkpoint
        is not None
    )

    assert (
        waiting_checkpoint.waiting_stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )

    assert (
        waiting_checkpoint.resumable
        is True
    )

    assert (
        len(
            job.scene_asset_states
        )
        == 1
    )

    original_state = (
        job.scene_asset_states[0]
    )

    assert (
        original_state.status
        == (
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        )
    )

    original_job_id = (
        job.id
    )

    serialized_job = (
        job.model_dump_json()
    )

    restarted_job = (
        VideoJob.model_validate_json(
            serialized_job
        )
    )

    assert (
        restarted_job
        is not job
    )

    assert (
        restarted_job.id
        == original_job_id
    )

    assert (
        len(
            restarted_job
            .scene_asset_states
        )
        == 1
    )

    restarted_state = (
        restarted_job
        .scene_asset_states[0]
    )

    assert (
        restarted_state.status
        == (
            AssetWorkflowStatus
            .WAITING_FOR_MANUAL_UPLOAD
        )
    )

    assert (
        restarted_state
        .manual_upload_requested
        is True
    )

    assert (
        restarted_state
        .selected_source
        == SceneSourceType.MANUAL_UPLOAD
    )

    upload_file = (
        tmp_path
        / "serialized_restart_manual_scene.mp4"
    )

    upload_file.write_bytes(
        b"serialized-restart-manual-video"
    )

    second_workflow = (
        WaitingAssetWorkflowService()
    )

    second_voice = (
        SuccessfulVoiceStage()
    )

    second_render = (
        SuccessfulRenderStage()
    )

    second_service = build_orchestrator(
        storage=storage,
        workflow=second_workflow,
        voice_stage=second_voice,
        render_stage=second_render,
    )

    second_result = (
        second_service.execute(
            restarted_job,
            user_input={
                "asset_decisions": [
                    {
                        "scene_number": 1,
                        "decision": (
                            AssetUserDecision
                            .MANUAL_UPLOAD
                            .value
                        ),
                        "manual_upload_path": (
                            str(
                                upload_file
                            )
                        ),
                    },
                ],
            },
        )
    )

    assert (
        second_result.success
        is True
    )

    # VOICE already completed before the waiting checkpoint.
    assert (
        second_voice.execution_count
        == 0
    )

    # The serialized SceneAssetState must be resumed instead of starting
    # the asset workflow from scratch.
    assert (
        second_workflow.start_count
        == 0
    )

    assert (
        second_render.execution_count
        == 1
    )

    assert (
        len(
            restarted_job
            .scene_asset_states
        )
        == 1
    )

    resolved_state = (
        restarted_job
        .scene_asset_states[0]
    )

    assert (
        resolved_state.status
        == AssetWorkflowStatus.READY
    )

    assert (
        resolved_state.user_decision
        == (
            AssetUserDecision
            .MANUAL_UPLOAD
        )
    )

    assert (
        resolved_state.selected_candidate
        is not None
    )

    assert (
        resolved_state
        .selected_candidate
        .file_path
        == str(
            upload_file.resolve()
        )
    )

    assert (
        restarted_job.status
        == JobStatus.COMPLETED
    )

    assert (
        restarted_job.current_stage
        == (
            WorkflowStage
            .READY_FOR_UPLOAD
        )
    )

    assert (
        restarted_job.render_result
        is not None
    )

    assert (
        restarted_job.render_result.success
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
        == (
            PipelineStageName
            .ASSET_SELECTION
            .value
        )
    )

    assert (
        second_result.metadata[
            "loaded_checkpoint_id"
        ]
        == str(
            waiting_checkpoint
            .checkpoint_id
        )
    )

    checkpoints = (
        storage.list_for_job(
            job_id=(
                restarted_job.id
            ),
        )
    )

    assert (
        len(checkpoints)
        == 2
    )

    latest_checkpoint = (
        storage.load_latest(
            job_id=(
                restarted_job.id
            ),
        )
    )

    assert (
        latest_checkpoint
        is not None
    )

    assert (
        latest_checkpoint.resumable
        is False
    )

    assert (
        latest_checkpoint.waiting_stage
        is None
    )

    assert (
        latest_checkpoint.failed_stage
        is None
    )
def test_resume_without_input_waits_again(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
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

    second_workflow = (
        WaitingAssetWorkflowService()
    )

    second_voice = (
        SuccessfulVoiceStage()
    )

    second_render = (
        SuccessfulRenderStage()
    )

    second_service = build_orchestrator(
        storage=storage,
        workflow=second_workflow,
        voice_stage=second_voice,
        render_stage=second_render,
    )

    second_result = (
        second_service.execute(
            job
        )
    )

    assert (
        second_result.success
        is False
    )

    assert (
        second_result.failed_stage
        == WorkflowStage.ASSET_GENERATION
    )

    assert (
        second_voice.execution_count
        == 0
    )

    assert (
        second_workflow.start_count
        == 0
    )

    assert (
        second_render.execution_count
        == 0
    )

    latest = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert latest is not None

    assert (
        latest.waiting_stage
        == (
            PipelineStageName
            .ASSET_SELECTION
        )
    )


def test_successful_resume_persists_terminal_checkpoint(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
    )

    first_service.execute(
        job
    )

    upload_file = (
        tmp_path
        / "terminal_manual_scene.mp4"
    )

    upload_file.write_bytes(
        b"terminal-manual-video"
    )

    second_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
    )

    result = (
        second_service.execute(
            job,
            user_input={
                "asset_decisions": [
                    {
                        "scene_number": 1,
                        "decision": (
                            "manual_upload"
                        ),
                        "manual_upload_path": (
                            str(
                                upload_file
                            )
                        ),
                    },
                ],
            },
        )
    )

    assert result.success is True

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
        latest.waiting_stage
        is None
    )

    assert (
        latest.failed_stage
        is None
    )

    assert (
        latest.resumable
        is False
    )

    assert (
        latest.completed_stages
        == [
            PipelineStageName.VOICE,
            (
                PipelineStageName
                .ASSET_SELECTION
            ),
            PipelineStageName.RENDER,
        ]
    )


def test_unknown_scene_input_fails_cleanly(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
    )

    first_service.execute(
        job
    )

    resumed_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
    )

    result = (
        resumed_service.execute(
            job,
            user_input={
                "asset_decisions": [
                    {
                        "scene_number": 999,
                        "decision": (
                            "skip_scene"
                        ),
                    },
                ],
            },
        )
    )

    assert (
        result.success
        is False
    )

    assert (
        "unknown scene number 999"
        in result.errors[-1]
    )


def test_explicit_terminal_checkpoint_rejects_stale_resume(
    tmp_path: Path,
) -> None:
    job = build_job()

    storage = build_storage(
        tmp_path
    )

    first_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
    )

    first_result = first_service.execute(
        job
    )

    assert first_result.success is False

    waiting_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert waiting_checkpoint is not None
    assert waiting_checkpoint.resumable is True

    first_upload = (
        tmp_path
        / "resolved_scene.mp4"
    )

    first_upload.write_bytes(
        b"resolved-scene-video"
    )

    second_service = build_orchestrator(
        storage=storage,
        workflow=(
            WaitingAssetWorkflowService()
        ),
        voice_stage=(
            SuccessfulVoiceStage()
        ),
        render_stage=(
            SuccessfulRenderStage()
        ),
    )

    second_result = second_service.execute(
        job,
        checkpoint_id=(
            waiting_checkpoint
            .checkpoint_id
        ),
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": (
                        AssetUserDecision
                        .MANUAL_UPLOAD
                        .value
                    ),
                    "manual_upload_path": (
                        str(
                            first_upload
                        )
                    ),
                },
            ],
        },
    )

    assert second_result.success is True

    terminal_checkpoint = (
        storage.load_latest(
            job_id=job.id,
        )
    )

    assert terminal_checkpoint is not None

    assert (
        terminal_checkpoint.resumable
        is False
    )

    resolved_state = (
        job.scene_asset_states[0]
    )

    assert (
        resolved_state.selected_candidate
        is not None
    )

    original_file_path = (
        resolved_state
        .selected_candidate
        .file_path
    )

    stale_upload = (
        tmp_path
        / "stale_scene.mp4"
    )

    stale_upload.write_bytes(
        b"stale-scene-video"
    )

    stale_workflow = (
        WaitingAssetWorkflowService()
    )

    stale_voice = (
        SuccessfulVoiceStage()
    )

    stale_render = (
        SuccessfulRenderStage()
    )

    stale_service = build_orchestrator(
        storage=storage,
        workflow=stale_workflow,
        voice_stage=stale_voice,
        render_stage=stale_render,
    )

    stale_result = stale_service.execute(
        job,
        checkpoint_id=(
            terminal_checkpoint
            .checkpoint_id
        ),
        user_input={
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": (
                        AssetUserDecision
                        .MANUAL_UPLOAD
                        .value
                    ),
                    "manual_upload_path": (
                        str(
                            stale_upload
                        )
                    ),
                },
            ],
        },
    )

    assert stale_result.success is False

    assert (
        "not resumable"
        in stale_result.errors[-1]
    )

    assert (
        stale_result.metadata[
            "checkpoint_phase"
        ]
        == "resume_preparation"
    )

    # Resume preparation must fail before any pipeline stage executes.
    assert stale_voice.execution_count == 0
    assert stale_workflow.start_count == 0
    assert stale_render.execution_count == 0

    # The stale decision must not replace the already resolved asset.
    assert (
        job.scene_asset_states[0]
        .selected_candidate
        is not None
    )

    assert (
        job.scene_asset_states[0]
        .selected_candidate
        .file_path
        == original_file_path
    )

    assert (
        original_file_path
        == str(
            first_upload.resolve()
        )
    )

    # A rejected stale resume must not create another checkpoint.
    checkpoints = (
        storage.list_for_job(
            job_id=job.id,
        )
    )

    assert len(checkpoints) == 2
def main() -> None:
    print()
    print(
        "Running Render Orchestrator "
        "Waiting Resume tests..."
    )
    print()

    print(
        "Run this suite with pytest because "
        "it uses the tmp_path fixture."
    )


if __name__ == "__main__":
    main()