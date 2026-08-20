from __future__ import annotations

from pathlib import Path
from uuid import UUID

from src.desktop.job_store import JsonJobStore
from src.models.approval import ApprovalPolicyConfig, HumanApprovalAction
from src.models.video_job import VideoJob
from src.services.approval_gate_service import ApprovalGateService
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.llm.llm_service import LLMServiceResult
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_CANNED_RESEARCH_SUMMARY = (
    "The Mary Celeste was found adrift and abandoned in 1872, seaworthy "
    "and fully provisioned, with no sign of the crew."
)


class _EchoStubLLMService:
    """Mirrors test_content_intelligence_pipeline.py's stub - see that
    file's docstring for why one stub can drive the whole pipeline."""

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        if request.dry_run_response is not None:
            content = request.dry_run_response
            if request.metadata.get("agent") == "AudiencePromiseService":
                content = content.replace(
                    "PROMISE_STRENGTH: moderate", "PROMISE_STRENGTH: strong"
                )
        elif request.metadata.get("agent") == "ResearchAgent":
            content = _CANNED_RESEARCH_SUMMARY
        else:
            content = ""

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="test-profile",
            all_providers_failed=False,
        )


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
        approval_policy=ApprovalPolicyConfig.full_auto(),
    )
    base.update(overrides)
    return VideoJob(**base)


def _pipeline() -> ContentIntelligencePipeline:
    return ContentIntelligencePipeline(
        llm_service=_EchoStubLLMService()  # type: ignore[arg-type]
    )


def _reload_from_a_fresh_store(storage_root: Path, job_id: UUID) -> VideoJob:
    """
    Simulate an application restart: a brand-new JsonJobStore instance
    (no warm in-memory cache) pointed at the same directory a prior
    process wrote to. JsonJobStore's cache is per-instance (see its own
    docstring), so calling .get() on the *same* store the test already
    holds would just hand back the identical cached object rather than
    proving anything was actually durable - this is why a genuinely
    separate store instance is required here, not a shortcut.
    """

    fresh_store = JsonJobStore(storage_root=storage_root)
    reloaded = fresh_store.get(job_id)
    assert reloaded is not None

    return reloaded


def test_restart_preserves_content_intelligence_artifacts(tmp_path: Path) -> None:
    pipeline = _pipeline()
    job = _job()

    job = pipeline.run_audience_promise(job)
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)
    job = pipeline.run_narrative_architecture(job)

    store = JsonJobStore(storage_root=tmp_path)
    store.add(job)

    reloaded = _reload_from_a_fresh_store(tmp_path, job.id)

    assert reloaded.audience_promise is not None
    assert reloaded.audience_promise.model_dump() == job.audience_promise.model_dump()

    assert reloaded.research is not None
    assert reloaded.research.research_summary == _CANNED_RESEARCH_SUMMARY

    assert reloaded.story_angles is not None
    assert len(reloaded.story_angles) == len(job.story_angles)
    assert reloaded.selected_story_angle is not None
    assert reloaded.selected_story_angle.title == job.selected_story_angle.title

    assert reloaded.story_blueprint is not None
    assert len(reloaded.story_blueprint.beats) == len(job.story_blueprint.beats)
    assert reloaded.reveal_map is not None
    assert len(reloaded.reveal_map.curiosity_loops) == len(
        job.reveal_map.curiosity_loops
    )


def test_pipeline_resumes_from_a_restarted_job_and_completes_the_next_stage(
    tmp_path: Path,
) -> None:
    pipeline = _pipeline()
    job = _job()

    job = pipeline.run_audience_promise(job)
    job = pipeline.run_research(job)
    job = pipeline.run_story_angles(job)

    store = JsonJobStore(storage_root=tmp_path)
    store.add(job)

    reloaded = _reload_from_a_fresh_store(tmp_path, job.id)

    # A genuinely fresh pipeline instance too - not just fresh data -
    # since restart-safety means "a new process can pick this up",
    # not just "the same process can re-read its own state."
    resumed_pipeline = _pipeline()
    resumed = resumed_pipeline.run_narrative_architecture(reloaded)

    assert resumed.story_blueprint is not None
    assert len(resumed.story_blueprint.beats) > 0
    assert resumed.reveal_map is not None
    assert len(resumed.reveal_map.curiosity_loops) > 0


def test_pending_approval_decision_survives_a_restart(tmp_path: Path) -> None:
    pipeline = _pipeline()
    job = _job(approval_policy=ApprovalPolicyConfig.manual_editorial())

    job = pipeline.run_audience_promise(job)

    pending_before = ApprovalGateService.latest_pending(job)
    assert pending_before is not None
    assert pending_before.approval is not None
    assert pending_before.approval.decision_point == "content_strategy"

    store = JsonJobStore(storage_root=tmp_path)
    store.add(job)

    reloaded = _reload_from_a_fresh_store(tmp_path, job.id)

    pending_after = ApprovalGateService.latest_pending(reloaded)
    assert pending_after is not None
    assert pending_after.approval is not None
    assert pending_after.approval.decision_point == "content_strategy"

    # The restart didn't just preserve the pending record - resolving
    # it on the reloaded job still works, proving the gate itself
    # (not just the data underneath it) survived intact.
    resumed_pipeline = _pipeline()
    resumed_pipeline.resolve_approval(
        reloaded, "content_strategy", HumanApprovalAction.APPROVE
    )

    assert ApprovalGateService.latest_pending(reloaded) is None
