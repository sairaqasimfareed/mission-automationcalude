from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from src.models.muse_generation import (
    MuseGenerationRequest,
    MuseGenerationState,
    MuseQCOutcome,
    MuseQCResult,
)
from src.models.video_job import VideoJob
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )


def _request(**overrides: object) -> MuseGenerationRequest:
    defaults: dict[str, object] = {
        "scene_number": 1,
        "prompt": "A lighthouse at dusk, waves crashing below.",
        "prompt_version": "v1",
        "profile_id": "muse.primary",
        "idempotency_key": "req-1",
    }
    defaults.update(overrides)
    return MuseGenerationRequest(**defaults)  # type: ignore[arg-type]


# --- create_attempt ---


def test_create_attempt_appends_to_the_job() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    assert job.muse_generation_attempts == [attempt]
    assert attempt.attempt_number == 1
    assert attempt.state == MuseGenerationState.PLANNED


def test_create_attempt_refuses_a_second_in_flight_attempt_for_the_same_scene() -> None:
    job = _job()
    MuseGenerationLedgerService.create_attempt(job, _request())

    with pytest.raises(ValueError, match="already has an in-flight"):
        MuseGenerationLedgerService.create_attempt(
            job, _request(idempotency_key="req-2")
        )


def test_create_attempt_refuses_a_reused_idempotency_key() -> None:
    job = _job()
    first = MuseGenerationLedgerService.create_attempt(job, _request())

    # Terminate the first attempt so the in-flight guard doesn't fire
    # first, isolating the idempotency-key check.
    job.muse_generation_attempts[0] = first.with_transition(MuseGenerationState.FAILED)

    with pytest.raises(ValueError, match="idempotency_key"):
        MuseGenerationLedgerService.create_attempt(job, _request())


def test_create_attempt_allows_regeneration_after_a_terminal_attempt() -> None:
    job = _job()
    first = MuseGenerationLedgerService.create_attempt(job, _request())
    job.muse_generation_attempts[0] = first.with_transition(MuseGenerationState.FAILED)

    second = MuseGenerationLedgerService.create_attempt(
        job, _request(idempotency_key="req-2")
    )

    assert second.attempt_number == 2
    assert len(job.muse_generation_attempts) == 2
    # The old, failed attempt is preserved, never overwritten.
    assert job.muse_generation_attempts[0].state == MuseGenerationState.FAILED


def test_create_attempt_allows_independent_scenes_concurrently() -> None:
    job = _job()
    MuseGenerationLedgerService.create_attempt(job, _request(scene_number=1))
    second = MuseGenerationLedgerService.create_attempt(
        job, _request(scene_number=2, idempotency_key="req-2")
    )

    assert len(job.muse_generation_attempts) == 2
    assert second.attempt_number == 1


# --- record_transition ---


def test_record_transition_replaces_in_place() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    updated = MuseGenerationLedgerService.record_transition(
        job, attempt.id, MuseGenerationState.SUBMITTING
    )

    assert len(job.muse_generation_attempts) == 1
    assert job.muse_generation_attempts[0] is updated
    assert updated.state == MuseGenerationState.SUBMITTING


def test_record_transition_never_overwrites_history() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    MuseGenerationLedgerService.record_transition(
        job, attempt.id, MuseGenerationState.SUBMITTING
    )
    final = MuseGenerationLedgerService.record_transition(
        job, attempt.id, MuseGenerationState.SUBMITTED
    )

    assert [entry.state for entry in final.state_history] == [
        MuseGenerationState.PLANNED,
        MuseGenerationState.SUBMITTING,
        MuseGenerationState.SUBMITTED,
    ]


def test_record_transition_raises_for_an_unknown_attempt() -> None:
    job = _job()

    with pytest.raises(ValueError, match="No Muse generation attempt"):
        MuseGenerationLedgerService.record_transition(
            job, uuid4(), MuseGenerationState.SUBMITTING
        )


def test_record_transition_rejects_an_illegal_jump() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    with pytest.raises(ValueError, match="Illegal Muse generation"):
        MuseGenerationLedgerService.record_transition(
            job, attempt.id, MuseGenerationState.GENERATING
        )


def test_record_transition_records_detail() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    updated = MuseGenerationLedgerService.record_transition(
        job,
        attempt.id,
        MuseGenerationState.SUBMITTING,
        detail="Typed the prompt and pressed enter.",
    )

    assert updated.state_history[-1].detail == "Typed the prompt and pressed enter."


# --- reconcile_on_restart (the credit-sensitive-state rule) ---


def _advance_to_submitting(job: VideoJob, attempt_id: UUID) -> None:
    MuseGenerationLedgerService.record_transition(
        job, attempt_id, MuseGenerationState.SUBMITTING
    )


def test_reconcile_on_restart_flags_an_attempt_stuck_at_submitting() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())
    _advance_to_submitting(job, attempt.id)

    reconciled = MuseGenerationLedgerService.reconcile_on_restart(job)

    assert len(reconciled) == 1
    assert reconciled[0].state == MuseGenerationState.SUBMISSION_UNCERTAIN
    assert job.muse_generation_attempts[0].state == (
        MuseGenerationState.SUBMISSION_UNCERTAIN
    )


def test_reconcile_on_restart_never_touches_a_settled_attempt() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())
    MuseGenerationLedgerService.record_transition(
        job, attempt.id, MuseGenerationState.SUBMITTING
    )
    MuseGenerationLedgerService.record_transition(
        job, attempt.id, MuseGenerationState.SUBMITTED
    )

    reconciled = MuseGenerationLedgerService.reconcile_on_restart(job)

    assert reconciled == []
    assert job.muse_generation_attempts[0].state == MuseGenerationState.SUBMITTED


def test_reconcile_on_restart_is_idempotent() -> None:
    """Calling it again after a successful reconciliation must not
    touch the already-reconciled SUBMISSION_UNCERTAIN attempt again."""

    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())
    _advance_to_submitting(job, attempt.id)

    MuseGenerationLedgerService.reconcile_on_restart(job)
    second_pass = MuseGenerationLedgerService.reconcile_on_restart(job)

    assert second_pass == []


# --- query helpers ---


def test_attempts_for_scene_returns_oldest_first() -> None:
    job = _job()
    first = MuseGenerationLedgerService.create_attempt(job, _request())
    job.muse_generation_attempts[0] = first.with_transition(MuseGenerationState.FAILED)
    MuseGenerationLedgerService.create_attempt(job, _request(idempotency_key="req-2"))

    attempts = MuseGenerationLedgerService.attempts_for_scene(job, 1)

    assert [attempt.attempt_number for attempt in attempts] == [1, 2]


def test_attempts_for_scene_excludes_other_scenes() -> None:
    job = _job()
    MuseGenerationLedgerService.create_attempt(job, _request(scene_number=1))
    MuseGenerationLedgerService.create_attempt(
        job, _request(scene_number=2, idempotency_key="req-2")
    )

    assert len(MuseGenerationLedgerService.attempts_for_scene(job, 1)) == 1
    assert len(MuseGenerationLedgerService.attempts_for_scene(job, 2)) == 1


def test_latest_attempt_for_scene_returns_none_when_absent() -> None:
    job = _job()

    assert MuseGenerationLedgerService.latest_attempt_for_scene(job, 1) is None


def test_latest_attempt_for_scene_returns_the_highest_attempt_number() -> None:
    job = _job()
    first = MuseGenerationLedgerService.create_attempt(job, _request())
    job.muse_generation_attempts[0] = first.with_transition(MuseGenerationState.FAILED)
    second = MuseGenerationLedgerService.create_attempt(
        job, _request(idempotency_key="req-2")
    )

    latest = MuseGenerationLedgerService.latest_attempt_for_scene(job, 1)

    assert latest is not None
    assert latest.id == second.id


def test_ready_attempt_for_scene_returns_none_before_readiness() -> None:
    job = _job()
    MuseGenerationLedgerService.create_attempt(job, _request())

    assert MuseGenerationLedgerService.ready_attempt_for_scene(job, 1) is None


# --- replace_attempt ---


def test_replace_attempt_stores_the_given_attempt() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    externally_advanced = attempt.with_transition(
        MuseGenerationState.SUBMITTING
    ).with_transition(MuseGenerationState.SUBMITTED)

    MuseGenerationLedgerService.replace_attempt(job, externally_advanced)

    assert job.muse_generation_attempts[0] is externally_advanced
    assert job.muse_generation_attempts[0].state == MuseGenerationState.SUBMITTED


def test_replace_attempt_raises_for_an_unknown_attempt() -> None:
    job = _job()
    unrelated = MuseGenerationLedgerService.create_attempt(_job(), _request())

    with pytest.raises(ValueError, match="No Muse generation attempt"):
        MuseGenerationLedgerService.replace_attempt(job, unrelated)


def test_ready_attempt_for_scene_finds_the_ready_attempt() -> None:
    job = _job()
    attempt = MuseGenerationLedgerService.create_attempt(job, _request())

    for state in (
        MuseGenerationState.SUBMITTING,
        MuseGenerationState.SUBMITTED,
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
        MuseGenerationState.DOWNLOADED,
    ):
        MuseGenerationLedgerService.record_transition(job, attempt.id, state)

    job.muse_generation_attempts[0] = job.muse_generation_attempts[0].model_copy(
        update={"qc_result": MuseQCResult(outcome=MuseQCOutcome.PASS)}
    )
    MuseGenerationLedgerService.record_transition(
        job, attempt.id, MuseGenerationState.READY
    )

    found = MuseGenerationLedgerService.ready_attempt_for_scene(job, 1)

    assert found is not None
    assert found.state == MuseGenerationState.READY
