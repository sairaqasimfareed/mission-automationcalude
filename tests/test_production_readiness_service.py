from __future__ import annotations

from src.models.approval import ApprovalPolicyConfig, HumanApprovalAction
from src.models.asset_state import (
    AssetFailureReason,
    AssetModuleFailure,
    AssetWorkflowStatus,
    SceneAssetState,
)
from src.models.audio_timeline import AudioTimeline
from src.models.blocker import BlockerCode, BlockerSeverity
from src.models.final_preview import FinalPreviewAction
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowStateTransition,
)
from src.models.manual_audio_requirement import (
    ManualAudioRequirement,
    ManualAudioRequirementType,
)
from src.models.media_strategy import SceneSourceType, VoiceStatus
from src.models.production_readiness import ReadinessState
from src.models.render_result import RenderResult, RenderStatus
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.approval_gate_service import ApprovalGateService
from src.services.final_preview_service import FinalPreviewService
from src.services.production_readiness_service import ProductionReadinessService


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    base.update(overrides)
    return VideoJob(**base)


def _scene(**overrides: object) -> Scene:
    base: dict[str, object] = dict(
        scene_number=1,
        title="Scene one",
        narration="Something happens.",
        visual_prompt="A dark hallway.",
        estimated_duration_seconds=8,
    )
    base.update(overrides)
    return Scene(**base)


def _script(status: ScriptStatus = ScriptStatus.DRAFT) -> Script:
    return Script(
        title="Test script",
        content="Hello world.",
        prompt_version="v1",
        status=status,
    )


def _flow_attempt(
    *,
    state: GoogleFlowGenerationState,
    scene_number: int = 1,
) -> GoogleFlowGenerationAttempt:
    return GoogleFlowGenerationAttempt(
        request=GoogleFlowGenerationRequest(
            scene_number=scene_number,
            prompt="A dark hallway.",
            prompt_version="v1",
            profile_id="flow.default",
            idempotency_key="idempotency-key-1",
        ),
        state=state,
        state_history=[
            GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
            GoogleFlowStateTransition(state=state),
        ],
        profile_id="flow.default",
    )


def _research() -> ResearchResult:
    return ResearchResult(
        topic="Test topic",
        research_summary="Summary.",
        prompt_version="v1",
        status=ResearchStatus.APPROVED,
    )


def test_bare_new_job_is_blocked_on_script() -> None:
    service = ProductionReadinessService()

    report = service.evaluate(_job())

    assert report.state == ReadinessState.BLOCKED
    codes = {b.code for b in report.blockers}
    assert BlockerCode.SCRIPT_NOT_GENERATED in codes


def test_legacy_script_satisfies_the_script_blocker() -> None:
    service = ProductionReadinessService()
    job = _job(script=_script(), research=_research())

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.SCRIPT_NOT_GENERATED not in codes


def test_no_scenes_is_blocking() -> None:
    service = ProductionReadinessService()
    job = _job(script=_script(), research=_research())

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.SCENES_NOT_PLANNED in codes


def test_pending_approval_produces_a_blocking_decision() -> None:
    service = ProductionReadinessService()
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())

    ApprovalGateService().gate(
        job=job, decision_point="research", stage="research", summary="x"
    )

    report = service.evaluate(job)

    approval_blockers = [
        b for b in report.blockers if b.code == BlockerCode.APPROVAL_PENDING
    ]
    assert len(approval_blockers) == 1
    assert approval_blockers[0].affected_artifact == "research"
    assert approval_blockers[0].severity == BlockerSeverity.BLOCKING


def test_resolving_the_approval_clears_its_blocker() -> None:
    service = ProductionReadinessService()
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())
    gate_service = ApprovalGateService()

    gate_service.gate(job=job, decision_point="research", stage="research", summary="x")
    gate_service.resolve(
        job=job, decision_point="research", action=HumanApprovalAction.APPROVE
    )

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.APPROVAL_PENDING not in codes


def test_scene_with_no_asset_state_is_not_ready() -> None:
    service = ProductionReadinessService()
    scene = _scene()
    job = _job(
        script=_script(status=ScriptStatus.APPROVED),
        research=_research(),
        scenes=[scene],
    )

    report = service.evaluate(job)

    asset_blockers = [
        b for b in report.blockers if b.code == BlockerCode.ASSET_NOT_READY
    ]
    assert len(asset_blockers) == 1
    assert asset_blockers[0].affected_artifact == f"scene:{scene.id}"


def test_scene_with_ready_asset_state_has_no_asset_blocker() -> None:
    service = ProductionReadinessService()
    scene = _scene()
    state = SceneAssetState(
        scene_id=str(scene.id),
        scene_number=scene.scene_number,
        status=AssetWorkflowStatus.READY,
    )
    job = _job(
        script=_script(status=ScriptStatus.APPROVED),
        research=_research(),
        scenes=[scene],
        scene_asset_states=[state],
    )

    report = service.evaluate(job)

    asset_blockers = [
        b
        for b in report.blockers
        if b.code in (BlockerCode.ASSET_NOT_READY, BlockerCode.ASSET_FAILURE)
    ]
    assert asset_blockers == []


def test_scene_with_a_recoverable_failure_is_a_warning_not_blocking() -> None:
    service = ProductionReadinessService()
    scene = _scene()
    failure = AssetModuleFailure(
        module_name="stock",
        reason=AssetFailureReason.STOCK_NO_RESULTS,
        message="No stock results found.",
        recoverable=True,
    )
    state = SceneAssetState(
        scene_id=str(scene.id),
        scene_number=scene.scene_number,
        status=AssetWorkflowStatus.FAILED_RECOVERABLE,
        active_failure=failure,
    )
    job = _job(
        script=_script(status=ScriptStatus.APPROVED),
        research=_research(),
        scenes=[scene],
        scene_asset_states=[state],
    )

    report = service.evaluate(job)

    failure_blockers = [
        b for b in report.blockers if b.code == BlockerCode.ASSET_FAILURE
    ]
    assert len(failure_blockers) == 1
    assert failure_blockers[0].severity == BlockerSeverity.WARNING
    assert failure_blockers[0].retryable is True


def test_scene_with_an_unrecoverable_failure_is_blocking() -> None:
    service = ProductionReadinessService()
    scene = _scene()
    failure = AssetModuleFailure(
        module_name="stock",
        reason=AssetFailureReason.STOCK_API_AUTHENTICATION_FAILED,
        message="Stock API authentication failed.",
        recoverable=False,
    )
    state = SceneAssetState(
        scene_id=str(scene.id),
        scene_number=scene.scene_number,
        status=AssetWorkflowStatus.FAILED_FATAL,
        active_failure=failure,
    )
    job = _job(
        script=_script(status=ScriptStatus.APPROVED),
        research=_research(),
        scenes=[scene],
        scene_asset_states=[state],
    )

    report = service.evaluate(job)

    failure_blockers = [
        b for b in report.blockers if b.code == BlockerCode.ASSET_FAILURE
    ]
    assert len(failure_blockers) == 1
    assert failure_blockers[0].severity == BlockerSeverity.BLOCKING
    assert report.state == ReadinessState.BLOCKED


def _ready_job() -> VideoJob:
    scene = _scene()
    state = SceneAssetState(
        scene_id=str(scene.id),
        scene_number=scene.scene_number,
        status=AssetWorkflowStatus.READY,
    )

    return _job(
        script=_script(status=ScriptStatus.APPROVED),
        research=_research(),
        scenes=[scene],
        scene_asset_states=[state],
        voice_status=VoiceStatus.READY,
        voice_file="voice.mp3",
        audio_timeline=AudioTimeline(tracks=[], total_duration_seconds=8.0),
        video_clips=[
            VideoClip(
                scene_number=scene.scene_number,
                source_type=SceneSourceType.MANUAL_UPLOAD,
                duration_seconds=8,
                local_file="clip.mp4",
            )
        ],
        video_timeline=VideoTimeline(clips=[], total_duration_seconds=8.0),
    )


def test_fully_ready_job_with_no_render_yet_is_ready_for_render() -> None:
    service = ProductionReadinessService()
    job = _ready_job()

    report = service.evaluate(job)

    assert report.blocking_issues == []
    assert report.state == ReadinessState.READY_FOR_RENDER


def test_job_with_a_failed_render_is_blocked() -> None:
    service = ProductionReadinessService()
    job = _ready_job()
    job.render_result = RenderResult(
        success=False,
        render_engine="ffmpeg",
        status=RenderStatus.FAILED,
        error_message="Encoder crashed.",
    )

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.RENDER_FAILED in codes
    assert report.state == ReadinessState.BLOCKED


def test_job_with_a_successful_render_is_ready_for_final_export() -> None:
    service = ProductionReadinessService()
    job = _ready_job()
    job.render_result = RenderResult(
        success=True,
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED,
        output_file="out.mp4",
    )

    report = service.evaluate(job)

    assert report.state == ReadinessState.READY_FOR_FINAL_EXPORT


def test_unfulfilled_manual_audio_requirement_is_blocking() -> None:
    service = ProductionReadinessService()
    job = _job(
        manual_audio_requirements=[
            ManualAudioRequirement(
                requirement_type=ManualAudioRequirementType.MUSIC,
                reason="No music provider is configured.",
                instructions="Configure a music provider.",
            )
        ]
    )

    report = service.evaluate(job)

    audio_blockers = [
        b for b in report.blockers if b.code == BlockerCode.MANUAL_AUDIO_REQUIRED
    ]
    assert len(audio_blockers) == 1
    assert audio_blockers[0].severity == BlockerSeverity.BLOCKING
    assert audio_blockers[0].affected_artifact == "music"
    assert report.state == ReadinessState.BLOCKED


def _job_with_approved_final_preview() -> tuple[VideoJob, FinalPreviewService]:
    job = _ready_job()
    job.render_result = RenderResult(
        success=True,
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED,
        output_file="out.mp4",
    )
    preview_service = FinalPreviewService()
    preview_service.create_preview(job)
    preview_service.resolve(job, FinalPreviewAction.APPROVE_FINAL)

    return job, preview_service


def test_an_approved_and_current_final_preview_is_not_blocking() -> None:
    service = ProductionReadinessService()
    job, _ = _job_with_approved_final_preview()

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.FINAL_PREVIEW_STALE not in codes


def test_an_approved_final_preview_that_no_longer_matches_the_render_is_blocking() -> (
    None
):
    service = ProductionReadinessService()
    job, _ = _job_with_approved_final_preview()

    job.video_timeline = VideoTimeline(
        clips=[], total_duration_seconds=8.0, output_resolution="1280x720"
    )

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.FINAL_PREVIEW_STALE in codes
    assert report.state == ReadinessState.BLOCKED


def test_a_pending_final_preview_is_not_blocking() -> None:
    service = ProductionReadinessService()
    job = _ready_job()
    job.render_result = RenderResult(
        success=True,
        render_engine="ffmpeg",
        status=RenderStatus.COMPLETED,
        output_file="out.mp4",
    )
    FinalPreviewService().create_preview(job)

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.FINAL_PREVIEW_STALE not in codes


def test_fulfilled_manual_audio_requirement_is_not_blocking() -> None:
    service = ProductionReadinessService()
    job = _job(
        manual_audio_requirements=[
            ManualAudioRequirement(
                requirement_type=ManualAudioRequirementType.MUSIC,
                reason="No music provider is configured.",
                instructions="Configure a music provider.",
                fulfilled=True,
                provided_file="music.mp3",
            )
        ]
    )

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.MANUAL_AUDIO_REQUIRED not in codes


def test_a_stuck_google_flow_attempt_produces_a_blocker() -> None:
    """
    MRA-PRE-7 (Pre-Installer Master Audit, GUI/operator-workflow audit)
    finding: job.flow_generation_attempts had zero GUI readers anywhere
    - an attempt reconciled to SUBMISSION_UNCERTAIN (GF-1's own crash-
    recovery outcome) was invisible to an operator. Proves the fix.
    """

    service = ProductionReadinessService()
    job = _job(
        flow_generation_attempts=[
            _flow_attempt(state=GoogleFlowGenerationState.SUBMISSION_UNCERTAIN),
        ],
    )

    report = service.evaluate(job)

    matching = [
        blocker
        for blocker in report.blockers
        if blocker.code == BlockerCode.GOOGLE_FLOW_ATTEMPT_NEEDS_ATTENTION
    ]

    assert len(matching) == 1
    assert "scene 1" in matching[0].message
    assert "submission uncertain" in matching[0].message
    assert matching[0].recovery_action is not None
    assert "duplicate paid generation" in matching[0].recovery_action


def test_a_healthy_google_flow_attempt_is_not_blocking() -> None:
    service = ProductionReadinessService()
    job = _job(
        flow_generation_attempts=[
            _flow_attempt(state=GoogleFlowGenerationState.GENERATING),
        ],
    )

    report = service.evaluate(job)

    codes = {b.code for b in report.blockers}
    assert BlockerCode.GOOGLE_FLOW_ATTEMPT_NEEDS_ATTENTION not in codes
