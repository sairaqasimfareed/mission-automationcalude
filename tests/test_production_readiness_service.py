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
