from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseQCOutcome,
    MuseQCResult,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.video_job import VideoJob
from src.providers.muse_ui_provider import MuseUIOperation, MuseUIProvider
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.muse_account_router_service import (
    MuseAccountRouterService,
    NoEligibleMuseAccountError,
)
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService
from src.services.muse_generation_orchestrator_service import (
    MuseAttemptCreditSensitiveError,
    MuseGenerationOrchestratorService,
)
from src.services.registry.provider_registry import ProviderRegistry

_GOOD_PROBE = json.dumps(
    {
        "format": {"duration": "10.0"},
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


def _muse_profile(
    profile_id: str = "muse.primary", **overrides: object
) -> ProviderProfile:
    defaults: dict[str, object] = {
        "profile_id": profile_id,
        "display_name": profile_id,
        "provider_name": "Muse",
        "category": ProviderCategory.EXTERNAL_UI_VIDEO,
        "enabled": True,
        "health_status": ProviderHealthStatus.HEALTHY,
        "browser_profile_reference": f"muse_profiles/{profile_id}",
    }
    defaults.update(overrides)
    return ProviderProfile(**defaults)  # type: ignore[arg-type]


class FakeAdvancingProvider(MuseUIProvider):
    """
    A fake provider that always advances an attempt straight to
    GENERATING - fast, deterministic, no real browser needed. The
    orchestrator's own logic (routing/budget/ledger persistence) is
    what these tests exercise, not the adapter itself.
    """

    def __init__(
        self,
        *,
        fail: bool = False,
        healthy: bool = True,
        auth_required_first: bool = False,
    ) -> None:
        self.fail = fail
        self.healthy = healthy
        self._auth_required_first = auth_required_first
        self.submit_calls: list[MuseGenerationRequest] = []
        self.check_profile_health_calls: list[str] = []

    @property
    def provider_name(self) -> str:
        return "Fake Muse"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[MuseUIOperation]:
        return frozenset(
            {
                MuseUIOperation.SUBMIT,
                MuseUIOperation.OBSERVE,
                MuseUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        self.check_profile_health_calls.append(profile_id)
        return self.healthy

    def submit(
        self,
        request: MuseGenerationRequest,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        self.submit_calls.append(request)

        if self.fail:
            raise RuntimeError("simulated adapter failure")

        if self._auth_required_first and len(self.submit_calls) == 1:
            return attempt.with_transition(
                MuseGenerationState.AUTH_REQUIRED,
                detail="Muse shows no sign of an authenticated session.",
            )

        current = attempt
        for state in (
            MuseGenerationState.SUBMITTING,
            MuseGenerationState.SUBMITTED,
            MuseGenerationState.GENERATING,
        ):
            current = current.with_transition(state)

        return current

    def observe(self, attempt: MuseGenerationAttempt) -> MuseGenerationAttempt:
        return attempt.with_transition(MuseGenerationState.READY_TO_DOWNLOAD)

    def download(self, attempt: MuseGenerationAttempt) -> MuseGenerationAttempt:
        return attempt.with_transition(MuseGenerationState.DOWNLOADED)

    def cancel_or_abandon(
        self, attempt: MuseGenerationAttempt
    ) -> MuseGenerationAttempt:
        self.ensure_supported(MuseUIOperation.CANCEL_OR_ABANDON)
        raise AssertionError("unreachable")


def _orchestrator(
    *,
    provider: FakeAdvancingProvider | None = None,
    profiles: list[ProviderProfile] | None = None,
    budget_service: ProviderBudgetService | None = None,
    max_in_flight_per_account: int = 1,
) -> tuple[MuseGenerationOrchestratorService, FakeAdvancingProvider]:
    fake_provider = provider or FakeAdvancingProvider()
    registered = [_muse_profile()] if profiles is None else profiles
    registry = ProviderRegistry(profiles=registered)
    router = MuseAccountRouterService(registry)

    return (
        MuseGenerationOrchestratorService(
            provider=fake_provider,
            account_router=router,
            budget_service=budget_service,
            max_in_flight_per_account=max_in_flight_per_account,
        ),
        fake_provider,
    )


def _submit(
    orchestrator: MuseGenerationOrchestratorService,
    job: VideoJob,
    *,
    scene_number: int = 1,
    idempotency_key: str = "req-1",
    estimated_cost_usd: float = 0.0,
) -> MuseGenerationAttempt:
    return orchestrator.submit_new_attempt(
        job,
        scene_number=scene_number,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        idempotency_key=idempotency_key,
        estimated_cost_usd=estimated_cost_usd,
    )


def test_submit_new_attempt_routes_persists_and_returns_the_result() -> None:
    orchestrator, provider = _orchestrator()
    job = _job()

    result = _submit(orchestrator, job)

    assert result.state == MuseGenerationState.GENERATING
    assert job.muse_generation_attempts == [result]
    assert provider.submit_calls[0].profile_id == "muse.primary"


def test_submit_new_attempt_raises_when_no_account_is_eligible() -> None:
    orchestrator, _ = _orchestrator(profiles=[])
    job = _job()

    with pytest.raises(NoEligibleMuseAccountError):
        _submit(orchestrator, job)

    assert job.muse_generation_attempts == []


def test_submit_new_attempt_refuses_a_second_in_flight_attempt_for_the_scene() -> None:
    orchestrator, _ = _orchestrator(
        provider=FakeAdvancingProvider(), max_in_flight_per_account=10
    )
    job = _job()
    _submit(orchestrator, job)

    with pytest.raises(ValueError, match="already has an in-flight"):
        _submit(orchestrator, job, idempotency_key="req-2")


def test_submit_new_attempt_gates_on_budget() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile()])
    budget_service = ProviderBudgetService(registry)
    router = MuseAccountRouterService(registry)
    orchestrator = MuseGenerationOrchestratorService(
        provider=FakeAdvancingProvider(),
        account_router=router,
        budget_service=budget_service,
    )
    job = _job()

    result = _submit(orchestrator, job, estimated_cost_usd=1.0)

    assert result.state == MuseGenerationState.GENERATING
    profile = registry.get("muse.primary")
    assert profile.daily_spent_usd == 1.0


def test_submit_new_attempt_blocks_when_budget_is_exceeded() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile(per_request_budget_usd=0.5)])
    budget_service = ProviderBudgetService(registry)
    router = MuseAccountRouterService(registry)
    orchestrator = MuseGenerationOrchestratorService(
        provider=FakeAdvancingProvider(),
        account_router=router,
        budget_service=budget_service,
    )
    job = _job()

    with pytest.raises(ValueError, match="per-request budget"):
        _submit(orchestrator, job, estimated_cost_usd=5.0)

    assert len(job.muse_generation_attempts) == 1
    assert job.muse_generation_attempts[0].state == MuseGenerationState.PLANNED


def test_submit_new_attempt_releases_budget_when_the_adapter_raises() -> None:
    registry = ProviderRegistry(profiles=[_muse_profile()])
    budget_service = ProviderBudgetService(registry)
    router = MuseAccountRouterService(registry)
    orchestrator = MuseGenerationOrchestratorService(
        provider=FakeAdvancingProvider(fail=True),
        account_router=router,
        budget_service=budget_service,
    )
    job = _job()

    with pytest.raises(RuntimeError, match="simulated adapter failure"):
        _submit(orchestrator, job, estimated_cost_usd=2.0)

    profile = registry.get("muse.primary")
    assert profile.daily_spent_usd == 0.0


def test_observe_attempt_persists_the_result() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    submitted = _submit(orchestrator, job)

    observed = orchestrator.observe_attempt(job, submitted)

    assert observed.state == MuseGenerationState.READY_TO_DOWNLOAD
    assert (
        job.muse_generation_attempts[0].state == MuseGenerationState.READY_TO_DOWNLOAD
    )


def test_download_attempt_persists_the_result() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    submitted = _submit(orchestrator, job)
    observed = orchestrator.observe_attempt(job, submitted)

    downloaded = orchestrator.download_attempt(job, observed)

    assert downloaded.state == MuseGenerationState.DOWNLOADED
    assert job.muse_generation_attempts[0].state == MuseGenerationState.DOWNLOADED


def test_resume_after_auth_resubmits_and_persists_once_healthy() -> None:
    provider = FakeAdvancingProvider(auth_required_first=True)
    orchestrator, _ = _orchestrator(provider=provider)
    job = _job()

    stuck = _submit(orchestrator, job)
    assert stuck.state == MuseGenerationState.AUTH_REQUIRED

    resumed = orchestrator.resume_after_auth(job, stuck)

    assert resumed.state == MuseGenerationState.GENERATING
    assert job.muse_generation_attempts == [resumed]
    assert provider.check_profile_health_calls == ["muse.primary"]
    assert len(provider.submit_calls) == 2


def test_resume_after_auth_rejects_an_attempt_not_at_auth_required() -> None:
    orchestrator, provider = _orchestrator()
    job = _job()
    generating = _submit(orchestrator, job)
    assert generating.state == MuseGenerationState.GENERATING

    with pytest.raises(ValueError, match="AUTH_REQUIRED"):
        orchestrator.resume_after_auth(job, generating)

    assert provider.check_profile_health_calls == []
    assert len(provider.submit_calls) == 1


def test_resume_after_auth_refuses_to_resubmit_while_still_unhealthy() -> None:
    provider = FakeAdvancingProvider(auth_required_first=True, healthy=False)
    orchestrator, _ = _orchestrator(provider=provider)
    job = _job()
    stuck = _submit(orchestrator, job)
    assert stuck.state == MuseGenerationState.AUTH_REQUIRED

    with pytest.raises(RuntimeError, match="no sign of an authenticated session"):
        orchestrator.resume_after_auth(job, stuck)

    assert len(provider.submit_calls) == 1
    assert job.muse_generation_attempts[0].state == MuseGenerationState.AUTH_REQUIRED


def _planned_attempt(job: VideoJob, *, scene_number: int = 1) -> MuseGenerationAttempt:
    request = MuseGenerationRequest(
        scene_number=scene_number,
        prompt="A lighthouse at dusk.",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"req-{scene_number}",
    )

    return MuseGenerationLedgerService.create_attempt(job, request)


def test_abandon_attempt_marks_a_never_submitted_attempt_failed() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    planned = _planned_attempt(job)
    assert planned.state == MuseGenerationState.PLANNED

    abandoned = orchestrator.abandon_attempt(job, planned)

    assert abandoned.state == MuseGenerationState.FAILED
    assert job.muse_generation_attempts[0].state == MuseGenerationState.FAILED
    assert "Abandoned by operator" in (abandoned.state_history[-1].detail or "")


def test_abandon_attempt_allows_a_fresh_attempt_afterwards() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    planned = _planned_attempt(job)
    orchestrator.abandon_attempt(job, planned)

    fresh = _submit(orchestrator, job, idempotency_key="req-fresh")

    assert fresh.state == MuseGenerationState.GENERATING
    assert len(job.muse_generation_attempts) == 2


def test_abandon_attempt_refuses_a_stuck_ui_changed_that_never_submitted() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    planned = _planned_attempt(job)
    stuck = planned.with_transition(MuseGenerationState.UI_CHANGED)
    MuseGenerationLedgerService.replace_attempt(job, stuck)

    abandoned = orchestrator.abandon_attempt(job, stuck)

    assert abandoned.state == MuseGenerationState.FAILED


def test_abandon_attempt_refuses_by_default_once_generation_actually_started() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    submitted = _submit(orchestrator, job)
    assert submitted.state == MuseGenerationState.GENERATING
    stuck = submitted.with_transition(MuseGenerationState.UI_CHANGED)
    MuseGenerationLedgerService.replace_attempt(job, stuck)

    with pytest.raises(MuseAttemptCreditSensitiveError) as excinfo:
        orchestrator.abandon_attempt(job, stuck)

    assert excinfo.value.attempt.id == stuck.id
    assert job.muse_generation_attempts[0].state == MuseGenerationState.UI_CHANGED


def test_abandon_attempt_force_overrides_the_credit_sensitive_refusal() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    submitted = _submit(orchestrator, job)
    stuck = submitted.with_transition(MuseGenerationState.UI_CHANGED)
    MuseGenerationLedgerService.replace_attempt(job, stuck)

    abandoned = orchestrator.abandon_attempt(job, stuck, force=True)

    assert abandoned.state == MuseGenerationState.FAILED


def test_abandon_attempt_rejects_an_already_terminal_attempt() -> None:
    orchestrator, _ = _orchestrator()
    job = _job()
    planned = _planned_attempt(job)
    failed = planned.with_transition(MuseGenerationState.FAILED)
    MuseGenerationLedgerService.replace_attempt(job, failed)

    with pytest.raises(ValueError, match="non-terminal attempt"):
        orchestrator.abandon_attempt(job, failed)


def test_in_flight_counts_exclude_terminal_attempts() -> None:
    orchestrator, provider = _orchestrator(
        profiles=[
            _muse_profile("muse.primary", priority=1),
            _muse_profile("muse.backup", priority=2),
        ]
    )
    job = _job()

    first = _submit(orchestrator, job, scene_number=1)
    assert first.request.profile_id == "muse.primary"
    terminal = first
    for state in (
        MuseGenerationState.READY_TO_DOWNLOAD,
        MuseGenerationState.DOWNLOADED,
    ):
        terminal = terminal.with_transition(state)
    terminal = terminal.model_copy(
        update={"qc_result": MuseQCResult(outcome=MuseQCOutcome.PASS)}
    )
    terminal = terminal.with_transition(MuseGenerationState.READY)
    MuseGenerationLedgerService.replace_attempt(job, terminal)

    second = _submit(orchestrator, job, scene_number=2, idempotency_key="req-2")

    assert second.request.profile_id == "muse.primary"


# --- validate_downloaded_attempt (REUSE, not duplicated) ---


def _downloaded_attempt(
    orchestrator: MuseGenerationOrchestratorService,
    job: VideoJob,
    *,
    downloaded_file: str,
) -> MuseGenerationAttempt:
    submitted = _submit(orchestrator, job)
    downloaded = submitted
    for state in (
        MuseGenerationState.READY_TO_DOWNLOAD,
        MuseGenerationState.DOWNLOADED,
    ):
        downloaded = downloaded.with_transition(state)
    downloaded = downloaded.model_copy(update={"downloaded_file": downloaded_file})
    MuseGenerationLedgerService.replace_attempt(job, downloaded)

    return downloaded


def _orchestrator_with_stub_ffprobe(
    probe_output: str,
) -> tuple[MuseGenerationOrchestratorService, VideoJob]:
    registry = ProviderRegistry(profiles=[_muse_profile()])
    router = MuseAccountRouterService(registry)
    orchestrator = MuseGenerationOrchestratorService(
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

    assert result.state == MuseGenerationState.DOWNLOADED
    assert result.technical_validation is not None
    assert result.technical_validation.is_valid is True
    assert result.checksum is not None
    assert job.muse_generation_attempts[0].checksum == result.checksum


def test_validate_downloaded_attempt_rejects_invalid_media(tmp_path: Path) -> None:
    orchestrator, job = _orchestrator_with_stub_ffprobe(_TOO_SHORT_PROBE)
    file_path = tmp_path / "generation.mp4"
    file_path.write_bytes(b"fake but present video bytes")
    attempt = _downloaded_attempt(orchestrator, job, downloaded_file=str(file_path))

    result = orchestrator.validate_downloaded_attempt(job, attempt)

    assert result.state == MuseGenerationState.QC_FAILED
    assert result.qc_result is not None
    assert result.qc_result.outcome == MuseQCOutcome.INVALID
    assert result.failure is not None
    assert result.failure.occurred_after_possible_credit_exposure is True
    assert job.muse_generation_attempts[0].state == MuseGenerationState.QC_FAILED


def test_validate_downloaded_attempt_requires_a_downloaded_file() -> None:
    orchestrator, job = _orchestrator_with_stub_ffprobe(_GOOD_PROBE)
    submitted = _submit(orchestrator, job)

    with pytest.raises(ValueError, match="no downloaded_file"):
        orchestrator.validate_downloaded_attempt(job, submitted)
