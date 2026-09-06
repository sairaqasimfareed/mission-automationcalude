from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

from src.desktop.job_store import JsonJobStore
from src.models.approval import ApprovalPolicyConfig
from src.models.script_lock import ScriptProvenance
from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.llm.llm_service import LLMServiceResult
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

# Content Studio Redesign, Phase 19: "migration of compatible existing
# projects." VideoJob's every Content Studio Redesign field is
# optional with a backward-compatible default (the same additive
# discipline every phase in this session followed), so a project file
# written before any of that existed should still load - a real test
# of that claim needs an actual pre-redesign-shaped JSON file, not a
# VideoJob(...) construction (which would always include every current
# field by definition).
_LEGACY_PROJECT_JSON = {
    "id": str(uuid4()),
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "project_name": "Legacy Project",
    "channel_name": "Old Channel",
    "niche": "history",
    "topic": "The Roman Empire",
}


class _EchoStubLLMService:
    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = request.dry_run_response or "The Roman Empire fell in stages."

        if request.metadata.get("agent") == "AudiencePromiseService":
            content = content.replace(
                "PROMISE_STRENGTH: moderate", "PROMISE_STRENGTH: strong"
            )
        elif request.metadata.get("agent") == "HookEvaluationService":
            content = content.replace("SPOILER_RISK: 70", "SPOILER_RISK: 0")

        return LLMServiceResult(
            result=LLMCallResult(
                status=LLMCallStatus.SUCCESS,
                provider=LLMProvider.OPENAI,
                model="test-model",
                content=content,
            ),
            selected_profile_id="test-profile",
            all_providers_failed=False,
        )


def test_a_pre_redesign_project_file_loads_without_error(tmp_path: Path) -> None:
    job_id = _LEGACY_PROJECT_JSON["id"]
    (tmp_path / f"{job_id}.json").write_text(
        json.dumps(_LEGACY_PROJECT_JSON), encoding="utf-8"
    )

    store = JsonJobStore(storage_root=tmp_path)
    job = store.get(UUID(job_id))

    assert job is not None
    assert job.project_name == "Legacy Project"

    # Every Content Studio Redesign field defaults sensibly rather than
    # erroring or requiring a migration script.
    assert job.content_decisions == []
    assert job.script_lock is None
    assert job.script_version_history is None
    assert job.production_ambiguities == []
    assert job.script_intake_result is None


def test_a_migrated_project_completes_the_full_automation_engine(
    tmp_path: Path,
) -> None:
    """
    Not just "loads" - a migrated project must be able to run through
    the exact same ContentIntelligencePipeline.run_all() any new
    project uses, reaching a valid Script Lock, since Phase 19's
    "migration" requirement is about compatible existing projects
    continuing to work, not merely deserializing.
    """

    job_id = _LEGACY_PROJECT_JSON["id"]
    (tmp_path / f"{job_id}.json").write_text(
        json.dumps(_LEGACY_PROJECT_JSON), encoding="utf-8"
    )

    store = JsonJobStore(storage_root=tmp_path)
    job = store.get(UUID(job_id))
    assert job is not None

    job.approval_policy = ApprovalPolicyConfig.full_auto()

    pipeline = ContentIntelligencePipeline(
        llm_service=_EchoStubLLMService()  # type: ignore[arg-type]
    )
    job = pipeline.run_all(job)

    assert job.generated_script is not None
    assert job.scenes
    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.INTERNAL

    # Persist and reload - the now-populated redesign fields must
    # round-trip exactly like any project created after this phase.
    store.add(job)
    reloaded = JsonJobStore(storage_root=tmp_path).get(job.id)

    assert reloaded is not None
    assert reloaded.script_lock is not None
    assert (
        reloaded.script_lock.script_version_number
        == job.script_lock.script_version_number
    )
    assert len(reloaded.content_decisions) == len(job.content_decisions)
