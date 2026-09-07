from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.models.google_flow_generation import (
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowQCOutcome,
    GoogleFlowQCResult,
)
from src.models.video_job import VideoJob
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )


def _request(**overrides: object) -> GoogleFlowGenerationRequest:
    defaults: dict[str, object] = {
        "scene_number": 1,
        "prompt": "A lighthouse at dusk, waves crashing below.",
        "prompt_version": "v1",
        "profile_id": "flow.primary",
        "idempotency_key": "req-1",
    }
    defaults.update(overrides)
    return GoogleFlowGenerationRequest(**defaults)  # type: ignore[arg-type]


# --- create_attempt ---


def test_create_attempt_appends_to_the_job() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    assert job.flow_generation_attempts == [attempt]
    assert attempt.attempt_number == 1
    assert attempt.state == GoogleFlowGenerationState.PLANNED


def test_create_attempt_refuses_a_second_in_flight_attempt_for_the_same_scene() -> None:
    job = _job()
    GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    with pytest.raises(ValueError, match="already has an in-flight"):
        GoogleFlowGenerationLedgerService.create_attempt(
            job, _request(idempotency_key="req-2")
        )


def test_create_attempt_refuses_a_reused_idempotency_key() -> None:
    job = _job()
    first = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    # Terminate the first attempt so the in-flight guard doesn't fire
    # first, isolating the idempotency-key check.
    job.flow_generation_attempts[0] = first.with_transition(
        GoogleFlowGenerationState.FAILED
    )

    with pytest.raises(ValueError, match="idempotency_key"):
        GoogleFlowGenerationLedgerService.create_attempt(job, _request())


def test_create_attempt_allows_regeneration_after_a_terminal_attempt() -> None:
    job = _job()
    first = GoogleFlowGenerationLedgerService.create_attempt(job, _request())
    job.flow_generation_attempts[0] = first.with_transition(
        GoogleFlowGenerationState.FAILED
    )

    second = GoogleFlowGenerationLedgerService.create_attempt(
        job, _request(idempotency_key="req-2")
    )

    assert second.attempt_number == 2
    assert len(job.flow_generation_attempts) == 2
    # The old, failed attempt is preserved, never overwritten.
    assert job.flow_generation_attempts[0].state == GoogleFlowGenerationState.FAILED


def test_create_attempt_allows_independent_scenes_concurrently() -> None:
    job = _job()
    GoogleFlowGenerationLedgerService.create_attempt(job, _request(scene_number=1))
    second = GoogleFlowGenerationLedgerService.create_attempt(
        job, _request(scene_number=2, idempotency_key="req-2")
    )

    assert len(job.flow_generation_attempts) == 2
    assert second.attempt_number == 1


# --- record_transition ---


def test_record_transition_replaces_in_place() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    updated = GoogleFlowGenerationLedgerService.record_transition(
        job, attempt.id, GoogleFlowGenerationState.SETTINGS_VERIFIED
    )

    assert len(job.flow_generation_attempts) == 1
    assert job.flow_generation_attempts[0] is updated
    assert updated.state == GoogleFlowGenerationState.SETTINGS_VERIFIED


def test_record_transition_never_overwrites_history() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    GoogleFlowGenerationLedgerService.record_transition(
        job, attempt.id, GoogleFlowGenerationState.SETTINGS_VERIFIED
    )
    final = GoogleFlowGenerationLedgerService.record_transition(
        job, attempt.id, GoogleFlowGenerationState.PROMPT_PREPARED
    )

    assert [entry.state for entry in final.state_history] == [
        GoogleFlowGenerationState.PLANNED,
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
    ]


def test_record_transition_raises_for_an_unknown_attempt() -> None:
    job = _job()

    with pytest.raises(ValueError, match="No Google Flow generation attempt"):
        GoogleFlowGenerationLedgerService.record_transition(
            job, uuid4(), GoogleFlowGenerationState.SETTINGS_VERIFIED
        )


def test_record_transition_rejects_an_illegal_jump() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    with pytest.raises(ValueError, match="Illegal Google Flow generation"):
        GoogleFlowGenerationLedgerService.record_transition(
            job, attempt.id, GoogleFlowGenerationState.SUBMITTED
        )


def test_record_transition_records_detail() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    updated = GoogleFlowGenerationLedgerService.record_transition(
        job,
        attempt.id,
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        detail="Selected model family 'standard'.",
    )

    assert updated.state_history[-1].detail == "Selected model family 'standard'."


# --- reconcile_on_restart (the credit-sensitive-state rule) ---


def _advance_to_submitting(job: VideoJob, attempt_id: UUID) -> None:
    for state in (
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
    ):
        GoogleFlowGenerationLedgerService.record_transition(job, attempt_id, state)


def test_reconcile_on_restart_flags_an_attempt_stuck_at_submitting() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())
    _advance_to_submitting(job, attempt.id)

    reconciled = GoogleFlowGenerationLedgerService.reconcile_on_restart(job)

    assert len(reconciled) == 1
    assert reconciled[0].state == GoogleFlowGenerationState.SUBMISSION_UNCERTAIN
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN
    )


def test_reconcile_on_restart_never_touches_a_settled_attempt() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())
    GoogleFlowGenerationLedgerService.record_transition(
        job, attempt.id, GoogleFlowGenerationState.SETTINGS_VERIFIED
    )

    reconciled = GoogleFlowGenerationLedgerService.reconcile_on_restart(job)

    assert reconciled == []
    assert job.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.SETTINGS_VERIFIED
    )


def test_reconcile_on_restart_is_idempotent() -> None:
    """Calling it again after a successful reconciliation must not
    touch the already-reconciled SUBMISSION_UNCERTAIN attempt again."""

    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())
    _advance_to_submitting(job, attempt.id)

    GoogleFlowGenerationLedgerService.reconcile_on_restart(job)
    second_pass = GoogleFlowGenerationLedgerService.reconcile_on_restart(job)

    assert second_pass == []


# --- query helpers ---


def test_attempts_for_scene_returns_oldest_first() -> None:
    job = _job()
    first = GoogleFlowGenerationLedgerService.create_attempt(job, _request())
    job.flow_generation_attempts[0] = first.with_transition(
        GoogleFlowGenerationState.FAILED
    )
    GoogleFlowGenerationLedgerService.create_attempt(
        job, _request(idempotency_key="req-2")
    )

    attempts = GoogleFlowGenerationLedgerService.attempts_for_scene(job, 1)

    assert [attempt.attempt_number for attempt in attempts] == [1, 2]


def test_attempts_for_scene_excludes_other_scenes() -> None:
    job = _job()
    GoogleFlowGenerationLedgerService.create_attempt(job, _request(scene_number=1))
    GoogleFlowGenerationLedgerService.create_attempt(
        job, _request(scene_number=2, idempotency_key="req-2")
    )

    assert len(GoogleFlowGenerationLedgerService.attempts_for_scene(job, 1)) == 1
    assert len(GoogleFlowGenerationLedgerService.attempts_for_scene(job, 2)) == 1


def test_latest_attempt_for_scene_returns_none_when_absent() -> None:
    job = _job()

    assert GoogleFlowGenerationLedgerService.latest_attempt_for_scene(job, 1) is None


def test_latest_attempt_for_scene_returns_the_highest_attempt_number() -> None:
    job = _job()
    first = GoogleFlowGenerationLedgerService.create_attempt(job, _request())
    job.flow_generation_attempts[0] = first.with_transition(
        GoogleFlowGenerationState.FAILED
    )
    second = GoogleFlowGenerationLedgerService.create_attempt(
        job, _request(idempotency_key="req-2")
    )

    latest = GoogleFlowGenerationLedgerService.latest_attempt_for_scene(job, 1)

    assert latest is not None
    assert latest.id == second.id


def test_ready_attempt_for_scene_returns_none_before_readiness() -> None:
    job = _job()
    GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    assert GoogleFlowGenerationLedgerService.ready_attempt_for_scene(job, 1) is None


def test_ready_attempt_for_scene_finds_the_ready_attempt() -> None:
    job = _job()
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, _request())

    for state in (
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
    ):
        GoogleFlowGenerationLedgerService.record_transition(job, attempt.id, state)

    job.flow_generation_attempts[0] = job.flow_generation_attempts[0].model_copy(
        update={"qc_result": GoogleFlowQCResult(outcome=GoogleFlowQCOutcome.PASS)}
    )
    GoogleFlowGenerationLedgerService.record_transition(
        job, attempt.id, GoogleFlowGenerationState.READY
    )

    found = GoogleFlowGenerationLedgerService.ready_attempt_for_scene(job, 1)

    assert found is not None
    assert found.state == GoogleFlowGenerationState.READY
