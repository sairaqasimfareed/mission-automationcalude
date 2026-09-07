from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowQCOutcome,
    GoogleFlowQCResult,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.video_job import VideoJob
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
    NoEligibleGoogleFlowAccountError,
)
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowAgentConfirmationRequiredError,
    GoogleFlowGenerationOrchestratorService,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.registry.provider_registry import ProviderRegistry

_GOOD_PROBE = json.dumps(
    {
        "format": {"duration": "8.0"},
        "streams": [
            {"codec_type": "video", "width": 1920, "height": 1080},
            {"codec_type": "audio"},
        ],
    }
)

_TOO_SHORT_PROBE = json.dumps(
    {
        "format": {"duration": "0.1"},
        "streams": [{"codec_type": "video", "width": 1920, "height": 1080}],
    }
)


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )


def _flow_profile(
    profile_id: str = "flow.primary", **overrides: object
) -> ProviderProfile:
    defaults: dict[str, object] = {
        "profile_id": profile_id,
        "display_name": profile_id,
        "provider_name": "Google Flow",
        "category": ProviderCategory.EXTERNAL_UI_VIDEO,
        "enabled": True,
        "health_status": ProviderHealthStatus.HEALTHY,
        "browser_profile_reference": f"flow_profiles/{profile_id}",
    }
    defaults.update(overrides)
    return ProviderProfile(**defaults)  # type: ignore[arg-type]


class FakeAdvancingProvider(ExternalUIGenerationProvider):
    """
    A fake provider that always advances an attempt straight to
    GENERATING - fast, deterministic, no real browser needed. The
    orchestrator's own logic (routing/budget/ledger persistence) is
    what these tests exercise, not the adapter itself (already tested
    against the real fixture in test_google_flow_adapter.py).
    """

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.submit_calls: list[GoogleFlowGenerationRequest] = []

    @property
    def provider_name(self) -> str:
        return "Fake Flow"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        return frozenset(
            {
                ExternalUIOperation.SUBMIT,
                ExternalUIOperation.OBSERVE,
                ExternalUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        return True

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.submit_calls.append(request)

        if self.fail:
            raise RuntimeError("simulated adapter failure")

        current = attempt
        for state in (
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            GoogleFlowGenerationState.PROMPT_PREPARED,
            GoogleFlowGenerationState.ANALYZING,
            GoogleFlowGenerationState.SUBMITTING,
            GoogleFlowGenerationState.SUBMITTED,
            GoogleFlowGenerationState.GENERATING,
        ):
            current = current.with_transition(state)

        return current

    def observe(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        return attempt.with_transition(GoogleFlowGenerationState.READY_TO_DOWNLOAD)

    def download(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        return attempt.with_transition(GoogleFlowGenerationState.DOWNLOADED)

    def cancel_or_abandon(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)
        raise AssertionError("unreachable")


def _orchestrator(
    *,
    provider: FakeAdvancingProvider | None = None,
    profiles: list[ProviderProfile] | None = None,
    budget_service: ProviderBudgetService | None = None,
    max_in_flight_per_account: int = 1,
) -> tuple[GoogleFlowGenerationOrchestratorService, FakeAdvancingProvider]:
    fake_provider = provider or FakeAdvancingProvider()
    # profiles=[] must mean "register nothing," not "use the
    # default" - `profiles or [...]` would silently treat an empty
    # list the same as None, since [] is falsy in Python.
    registered = [_flow_profile()] if profiles is None else profiles
    registry = ProviderRegistry(profiles=registered)
    router = GoogleFlowAccountRouterService(registry)

    return (
        GoogleFlowGenerationOrchestratorService(
            provider=fake_provider,
            account_router=router,
            budget_service=budget_service,
            max_in_flight_per_account=max_in_flight_per_account,
        ),
        fake_provider,
    )


def _submit(
    orchestrator: GoogleFlowGenerationOrchestratorService,
    job: VideoJob,
    *,
    scene_number: int = 1,
    idempotency_key: str = "req-1",
    estimated_cost_usd: float = 0.0,
    execution_settings: GoogleFlowExecutionSettings | None = None,
) -> GoogleFlowGenerationAttempt:
    return orchestrator.submit_new_attempt(
        job,
        scene_number=scene_number,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        idempotency_key=idempotency_key,
        estimated_cost_usd=estimated_cost_usd,
        execution_settings=execution_settings,
    )


def test_submit_new_attempt_routes_persists_and_returns_the_result() -> None:
    orchestrator, provider = _orchestrator()
    job = _job()

    result = _submit(orchestrator, job)

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert job.flow_generation_attempts == [result]
    assert provider.submit_calls[0].profile_id == "flow.primary"


def test_non_agent_mode_requests_are_never_gated_by_approval() -> None:
    """
    The Agent-mode confirmation gate only applies when
    execution_settings.agent_mode is explicitly True - a job's
    conservative default approval policy (REVIEW for
    external_ui_generation) must never block an ordinary, non-Agent
    submission.
    """

    orchestrator, provider = _orchestrator()
    job = _job()
    assert job.approval_policy.external_ui_generation == ApprovalPolicy.REVIEW

    result = _submit(
        orchestrator, job, execution_settings=GoogleFlowExecutionSettings()
    )

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert provider.submit_calls


def test_agent_mode_without_approval_raises_before_anything_credit_sensitive() -> None:
    orchestrator, provider = _orchestrator()
    job = _job()  # default approval_policy: external_ui_generation is REVIEW

    with pytest.raises(GoogleFlowAgentConfirmationRequiredError):
        _submit(
            orchestrator,
            job,
            execution_settings=GoogleFlowExecutionSettings(agent_mode=True),
        )

    # Never even reached routing/the ledger/the provider - this app's
    # own gate, checked before anything else.
    assert job.flow_generation_attempts == []
    assert provider.submit_calls == []


def test_agent_mode_confirmation_error_carries_the_resolved_decision() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()

    with pytest.raises(GoogleFlowAgentConfirmationRequiredError) as excinfo:
        _submit(
            orchestrator,
            job,
            execution_settings=GoogleFlowExecutionSettings(agent_mode=True),
        )

    decision = excinfo.value.decision
    assert decision.decision_point == "external_ui_generation"
    assert decision.policy == ApprovalPolicy.REVIEW
    assert decision.requires_human_action is True


def test_agent_mode_with_full_auto_policy_proceeds_without_raising() -> None:
    orchestrator, provider = _orchestrator()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()

    result = _submit(
        orchestrator,
        job,
        execution_settings=GoogleFlowExecutionSettings(agent_mode=True),
    )

    assert result.state == GoogleFlowGenerationState.GENERATING
    assert job.flow_generation_attempts == [result]
    assert provider.submit_calls


def test_submit_new_attempt_raises_when_no_account_is_eligible() -> None:
    orchestrator, _ = _orchestrator(profiles=[])
    job = _job()

    with pytest.raises(NoEligibleGoogleFlowAccountError):
        _submit(orchestrator, job)

    assert job.flow_generation_attempts == []


def test_submit_new_attempt_refuses_a_second_in_flight_attempt_for_the_scene() -> None:
    # A high per-account ceiling isolates GoogleFlowGenerationLedgerService's
    # own scene-level in-flight guard (GF-1) as the thing under test,
    # rather than the router's own account-level ceiling (also real,
    # but a different guard - see test_skips_an_account_at_its_in_flight_ceiling
    # in test_google_flow_account_router_service.py) firing first.
    orchestrator, _ = _orchestrator(
        provider=FakeAdvancingProvider(), max_in_flight_per_account=10
    )
    job = _job()
    _submit(orchestrator, job)

    with pytest.raises(ValueError, match="already has an in-flight"):
        _submit(orchestrator, job, idempotency_key="req-2")


def test_submit_new_attempt_gates_on_budget() -> None:
    registry = ProviderRegistry(profiles=[_flow_profile()])
    budget_service = ProviderBudgetService(registry)
    router = GoogleFlowAccountRouterService(registry)
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=FakeAdvancingProvider(),
        account_router=router,
        budget_service=budget_service,
    )
    job = _job()

    result = _submit(orchestrator, job, estimated_cost_usd=1.0)

    assert result.state == GoogleFlowGenerationState.GENERATING
    profile = registry.get("flow.primary")
    assert profile.daily_spent_usd == 1.0


def test_submit_new_attempt_blocks_when_budget_is_exceeded() -> None:
    registry = ProviderRegistry(profiles=[_flow_profile(per_request_budget_usd=0.5)])
    budget_service = ProviderBudgetService(registry)
    router = GoogleFlowAccountRouterService(registry)
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=FakeAdvancingProvider(),
        account_router=router,
        budget_service=budget_service,
    )
    job = _job()

    with pytest.raises(ValueError, match="per-request budget"):
        _submit(orchestrator, job, estimated_cost_usd=5.0)

    # No attempt was left stranded in the ledger for a request that
    # never actually proceeded past the budget gate... actually the
    # attempt IS created before the budget gate runs (ledger creation
    # happens first so the in-flight guard is authoritative), so it
    # must be present but must NOT have advanced past PLANNED.
    assert len(job.flow_generation_attempts) == 1
    assert job.flow_generation_attempts[0].state == GoogleFlowGenerationState.PLANNED


def test_submit_new_attempt_releases_budget_when_the_adapter_raises() -> None:
    registry = ProviderRegistry(profiles=[_flow_profile()])
    budget_service = ProviderBudgetService(registry)
    router = GoogleFlowAccountRouterService(registry)
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=FakeAdvancingProvider(fail=True),
        account_router=router,
        budget_service=budget_service,
    )
    job = _job()

    with pytest.raises(RuntimeError, match="simulated adapter failure"):
        _submit(orchestrator, job, estimated_cost_usd=2.0)

    profile = registry.get("flow.primary")
    assert profile.daily_spent_usd == 0.0


def test_observe_attempt_persists_the_result() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    submitted = _submit(orchestrator, job)

    observed = orchestrator.observe_attempt(job, submitted)

    assert observed.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.READY_TO_DOWNLOAD
    )


def test_download_attempt_persists_the_result() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    submitted = _submit(orchestrator, job)
    observed = orchestrator.observe_attempt(job, submitted)

    downloaded = orchestrator.download_attempt(job, observed)

    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.DOWNLOADED
    )


def test_in_flight_counts_exclude_terminal_attempts() -> None:
    # Distinct priorities make ordering deterministic - flow.primary
    # is always preferred over flow.backup as long as it's eligible,
    # so a wrong answer here can only mean the in-flight count was
    # computed incorrectly (still counting the now-terminal first
    # attempt), not an unrelated tie-break artifact.
    orchestrator, provider = _orchestrator(
        profiles=[
            _flow_profile("flow.primary", priority=1),
            _flow_profile("flow.backup", priority=2),
        ]
    )
    job = _job()

    first = _submit(orchestrator, job, scene_number=1)
    assert first.request.profile_id == "flow.primary"
    # Advance the first attempt to a terminal state directly on the
    # job's ledger, simulating it having already finished.
    terminal = first
    for state in (
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
    ):
        terminal = terminal.with_transition(state)
    terminal = terminal.model_copy(
        update={"qc_result": GoogleFlowQCResult(outcome=GoogleFlowQCOutcome.PASS)}
    )
    terminal = terminal.with_transition(GoogleFlowGenerationState.READY)
    GoogleFlowGenerationLedgerService.replace_attempt(job, terminal)

    # A second, independent scene should still be able to use
    # flow.primary, since its only attempt is now terminal (READY).
    second = _submit(orchestrator, job, scene_number=2, idempotency_key="req-2")

    assert second.request.profile_id == "flow.primary"


# --- validate_downloaded_attempt (GF-9: REUSE, not duplicated) ---


def _downloaded_attempt(
    orchestrator: GoogleFlowGenerationOrchestratorService,
    job: VideoJob,
    *,
    downloaded_file: str,
) -> GoogleFlowGenerationAttempt:
    submitted = _submit(orchestrator, job)
    downloaded = submitted
    for state in (
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
    ):
        downloaded = downloaded.with_transition(state)
    downloaded = downloaded.model_copy(update={"downloaded_file": downloaded_file})
    GoogleFlowGenerationLedgerService.replace_attempt(job, downloaded)

    return downloaded


def _orchestrator_with_stub_ffprobe(
    probe_output: str,
) -> tuple[GoogleFlowGenerationOrchestratorService, VideoJob]:
    registry = ProviderRegistry(profiles=[_flow_profile()])
    router = GoogleFlowAccountRouterService(registry)
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=FakeAdvancingProvider(),
        account_router=router,
        technical_validation_service=MediaTechnicalValidationService(
            runner=lambda command: probe_output
        ),
    )
    return orchestrator, _job()


def test_validate_downloaded_attempt_accepts_valid_media(tmp_path: Path) -> None:
    orchestrator, job = _orchestrator_with_stub_ffprobe(_GOOD_PROBE)
    file_path = tmp_path / "generation.mp4"
    file_path.write_bytes(b"fake but present video bytes")
    attempt = _downloaded_attempt(orchestrator, job, downloaded_file=str(file_path))

    result = orchestrator.validate_downloaded_attempt(job, attempt)

    assert result.state == GoogleFlowGenerationState.DOWNLOADED
    assert result.technical_validation is not None
    assert result.technical_validation.is_valid is True
    assert result.checksum is not None
    assert job.flow_generation_attempts[0].checksum == result.checksum


def test_validate_downloaded_attempt_rejects_invalid_media(tmp_path: Path) -> None:
    orchestrator, job = _orchestrator_with_stub_ffprobe(_TOO_SHORT_PROBE)
    file_path = tmp_path / "generation.mp4"
    file_path.write_bytes(b"fake but present video bytes")
    attempt = _downloaded_attempt(orchestrator, job, downloaded_file=str(file_path))

    result = orchestrator.validate_downloaded_attempt(job, attempt)

    assert result.state == GoogleFlowGenerationState.QC_FAILED
    assert result.qc_result is not None
    assert result.qc_result.outcome == GoogleFlowQCOutcome.INVALID
    assert result.failure is not None
    assert result.failure.occurred_after_possible_credit_exposure is True
    assert job.flow_generation_attempts[0].state == GoogleFlowGenerationState.QC_FAILED


def test_validate_downloaded_attempt_requires_a_downloaded_file() -> None:
    orchestrator, job = _orchestrator_with_stub_ffprobe(_GOOD_PROBE)
    submitted = _submit(orchestrator, job)

    with pytest.raises(ValueError, match="no downloaded_file"):
        orchestrator.validate_downloaded_attempt(job, submitted)
