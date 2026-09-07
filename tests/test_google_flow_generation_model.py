from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowFailure,
    GoogleFlowFailureCode,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowQCOutcome,
    GoogleFlowQCResult,
    GoogleFlowReferenceAsset,
    GoogleFlowReferenceRole,
    GoogleFlowStateTransition,
    is_valid_transition,
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


def _attempt(**overrides: object) -> GoogleFlowGenerationAttempt:
    defaults: dict[str, object] = {
        "request": _request(),
        "profile_id": "flow.primary",
    }
    defaults.update(overrides)
    return GoogleFlowGenerationAttempt(**defaults)  # type: ignore[arg-type]


# --- GoogleFlowGenerationRequest ---


def test_request_constructs_with_required_fields() -> None:
    request = _request()

    assert request.scene_number == 1
    assert request.locked_script_hash is None
    assert request.execution_settings.model_family is None
    assert request.negative_constraints == []
    assert request.reference_assets == []


def test_request_rejects_blank_prompt() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _request(prompt="   ")


def test_request_prompt_hash_is_deterministic_and_content_sensitive() -> None:
    a = _request(prompt="Same prompt text.")
    b = _request(prompt="Same prompt text.")
    c = _request(prompt="Different prompt text.")

    assert a.prompt_hash == b.prompt_hash
    assert a.prompt_hash != c.prompt_hash


def test_request_negative_constraints_dedupe_and_strip() -> None:
    request = _request(negative_constraints=["  blurry  ", "blurry", "", "extra limbs"])

    assert request.negative_constraints == ["blurry", "extra limbs"]


def test_request_estimated_cost_cannot_be_negative() -> None:
    with pytest.raises(ValidationError):
        _request(estimated_cost_usd=-1.0)


def test_request_rejects_blank_idempotency_key() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _request(idempotency_key="   ")


# --- GoogleFlowExecutionSettings ---


def test_execution_settings_default_to_all_unset() -> None:
    settings = GoogleFlowExecutionSettings()

    assert settings.model_family is None
    assert settings.duration_seconds is None


def test_execution_settings_blank_text_becomes_none() -> None:
    settings = GoogleFlowExecutionSettings(model_family="   ", aspect_ratio="16:9")

    assert settings.model_family is None
    assert settings.aspect_ratio == "16:9"


def test_execution_settings_rejects_non_positive_duration() -> None:
    with pytest.raises(ValidationError):
        GoogleFlowExecutionSettings(duration_seconds=0)


# --- GoogleFlowReferenceAsset ---


def test_reference_asset_requires_checksum_and_path() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        GoogleFlowReferenceAsset(
            source_path="   ",
            checksum="abc123",
            role=GoogleFlowReferenceRole.CHARACTER,
        )


def test_reference_asset_defaults_to_version_one() -> None:
    asset = GoogleFlowReferenceAsset(
        source_path="assets/hero.png",
        checksum="abc123",
        role=GoogleFlowReferenceRole.CHARACTER,
    )

    assert asset.version == 1


# --- GoogleFlowFailure ---


def test_failure_requires_a_message() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        GoogleFlowFailure(code=GoogleFlowFailureCode.UI_CHANGED, message="   ")


def test_failure_defaults_to_no_credit_exposure() -> None:
    failure = GoogleFlowFailure(
        code=GoogleFlowFailureCode.TRANSIENT_NAVIGATION_FAILURE,
        message="Navigation timed out before submission.",
    )

    assert failure.occurred_after_possible_credit_exposure is False
    assert failure.recoverable is True


def test_failure_can_flag_possible_credit_exposure() -> None:
    failure = GoogleFlowFailure(
        code=GoogleFlowFailureCode.SUBMISSION_UNCERTAIN,
        message="Process terminated during the submit boundary.",
        occurred_after_possible_credit_exposure=True,
        recoverable=False,
    )

    assert failure.occurred_after_possible_credit_exposure is True


# --- GoogleFlowQCResult ---


def test_qc_result_pass_is_accepted() -> None:
    result = GoogleFlowQCResult(outcome=GoogleFlowQCOutcome.PASS)

    assert result.accepted is True


def test_qc_result_non_pass_is_not_accepted() -> None:
    for outcome in (
        GoogleFlowQCOutcome.HUMAN_REVIEW,
        GoogleFlowQCOutcome.RETRY_REQUIRED,
        GoogleFlowQCOutcome.REPLACE_REQUIRED,
        GoogleFlowQCOutcome.INVALID,
    ):
        assert GoogleFlowQCResult(outcome=outcome).accepted is False


# --- State machine: is_valid_transition ---


def test_happy_path_transitions_are_valid() -> None:
    happy_path = [
        GoogleFlowGenerationState.PLANNED,
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.ANALYZING,
        GoogleFlowGenerationState.CONFIRMATION_REQUIRED,
        GoogleFlowGenerationState.CONFIRMING,
        GoogleFlowGenerationState.SUBMITTING,
        GoogleFlowGenerationState.SUBMITTED,
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
        GoogleFlowGenerationState.DOWNLOADED,
        GoogleFlowGenerationState.READY,
    ]

    for current, following in zip(happy_path, happy_path[1:], strict=False):
        assert is_valid_transition(current, following), (current, following)


def test_confirmation_optional_path_is_valid() -> None:
    """GF-20: some Flow configurations skip confirmation entirely."""

    assert is_valid_transition(
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
    )
    assert is_valid_transition(
        GoogleFlowGenerationState.ANALYZING,
        GoogleFlowGenerationState.SUBMITTING,
    )


def test_interrupt_states_are_reachable_from_mid_flight() -> None:
    for interrupt in (
        GoogleFlowGenerationState.AUTH_REQUIRED,
        GoogleFlowGenerationState.HUMAN_ACTION_REQUIRED,
        GoogleFlowGenerationState.UI_CHANGED,
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
        GoogleFlowGenerationState.FAILED,
    ):
        assert is_valid_transition(GoogleFlowGenerationState.ANALYZING, interrupt)
        assert is_valid_transition(GoogleFlowGenerationState.GENERATING, interrupt)


def test_terminal_states_never_transition_again() -> None:
    for terminal in (
        GoogleFlowGenerationState.READY,
        GoogleFlowGenerationState.QC_FAILED,
        GoogleFlowGenerationState.FAILED,
    ):
        for other in GoogleFlowGenerationState:
            assert not is_valid_transition(terminal, other)


def test_skipping_a_forward_step_is_invalid() -> None:
    assert not is_valid_transition(
        GoogleFlowGenerationState.PLANNED,
        GoogleFlowGenerationState.SUBMITTED,
    )
    assert not is_valid_transition(
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.GENERATING,
    )


def test_ui_changed_is_a_dead_end_requiring_a_new_attempt() -> None:
    assert not is_valid_transition(
        GoogleFlowGenerationState.UI_CHANGED,
        GoogleFlowGenerationState.PLANNED,
    )


# --- GoogleFlowGenerationAttempt ---


def test_attempt_starts_at_planned_with_one_history_entry() -> None:
    attempt = _attempt()

    assert attempt.state == GoogleFlowGenerationState.PLANNED
    assert [entry.state for entry in attempt.state_history] == [
        GoogleFlowGenerationState.PLANNED
    ]
    assert attempt.attempt_number == 1


def test_attempt_state_must_match_last_history_entry() -> None:
    with pytest.raises(
        ValidationError, match="must match the most recent state_history entry"
    ):
        _attempt(
            state=GoogleFlowGenerationState.SUBMITTED,
            state_history=[
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED)
            ],
        )


def test_attempt_history_must_start_at_planned() -> None:
    with pytest.raises(ValidationError, match="must start at PLANNED"):
        _attempt(
            state=GoogleFlowGenerationState.SETTINGS_VERIFIED,
            state_history=[
                GoogleFlowStateTransition(
                    state=GoogleFlowGenerationState.SETTINGS_VERIFIED
                )
            ],
        )


def test_attempt_history_cannot_be_empty() -> None:
    with pytest.raises(ValidationError, match="cannot be empty"):
        _attempt(state_history=[])


def test_ready_attempt_requires_an_accepted_qc_result() -> None:
    with pytest.raises(ValidationError, match="requires a passing qc_result"):
        _attempt(
            state=GoogleFlowGenerationState.READY,
            state_history=[
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.READY),
            ],
        )


def test_ready_attempt_rejects_a_non_accepted_qc_result() -> None:
    with pytest.raises(ValidationError, match="requires an accepted qc_result"):
        _attempt(
            state=GoogleFlowGenerationState.READY,
            state_history=[
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.READY),
            ],
            qc_result=GoogleFlowQCResult(outcome=GoogleFlowQCOutcome.INVALID),
        )


def test_ready_attempt_with_accepted_qc_result_is_valid() -> None:
    attempt = _attempt(
        state=GoogleFlowGenerationState.READY,
        state_history=[
            GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
            GoogleFlowStateTransition(state=GoogleFlowGenerationState.READY),
        ],
        qc_result=GoogleFlowQCResult(outcome=GoogleFlowQCOutcome.PASS),
    )

    assert attempt.state == GoogleFlowGenerationState.READY


def test_qc_failed_attempt_requires_a_non_accepted_qc_result() -> None:
    with pytest.raises(ValidationError, match="requires a non-accepted qc_result"):
        _attempt(
            state=GoogleFlowGenerationState.QC_FAILED,
            state_history=[
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED),
                GoogleFlowStateTransition(state=GoogleFlowGenerationState.QC_FAILED),
            ],
        )


# --- with_transition ---


def test_with_transition_appends_history_and_returns_a_new_object() -> None:
    original = _attempt()
    advanced = original.with_transition(GoogleFlowGenerationState.SETTINGS_VERIFIED)

    assert advanced is not original
    assert original.state == GoogleFlowGenerationState.PLANNED
    assert advanced.state == GoogleFlowGenerationState.SETTINGS_VERIFIED
    assert len(advanced.state_history) == 2
    assert advanced.state_history[0].state == GoogleFlowGenerationState.PLANNED
    assert (
        advanced.state_history[1].state == GoogleFlowGenerationState.SETTINGS_VERIFIED
    )


def test_with_transition_rejects_an_illegal_jump() -> None:
    original = _attempt()

    with pytest.raises(ValueError, match="Illegal Google Flow generation"):
        original.with_transition(GoogleFlowGenerationState.SUBMITTED)


def test_with_transition_never_overwrites_prior_history() -> None:
    original = _attempt()
    step_one = original.with_transition(GoogleFlowGenerationState.SETTINGS_VERIFIED)
    step_two = step_one.with_transition(GoogleFlowGenerationState.PROMPT_PREPARED)

    assert [entry.state for entry in step_two.state_history] == [
        GoogleFlowGenerationState.PLANNED,
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
    ]
    # Earlier objects in the chain remain unmutated.
    assert len(original.state_history) == 1
    assert len(step_one.state_history) == 2


def test_with_transition_detail_is_recorded() -> None:
    original = _attempt()
    advanced = original.with_transition(
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        detail="Selected model family 'standard'.",
    )

    assert advanced.state_history[-1].detail == "Selected model family 'standard'."


def test_regeneration_increments_attempt_number_on_a_new_object() -> None:
    """
    Regeneration is deliberate and creates a NEW attempt, never a
    resumed one - proven here as attempt_number simply being a field
    on a freshly constructed attempt, not a mutation.
    """

    first = _attempt(attempt_number=1)
    second = _attempt(
        attempt_number=2,
        request=_request(idempotency_key="req-2"),
    )

    assert first.attempt_number == 1
    assert second.attempt_number == 2
    assert first.request.idempotency_key != second.request.idempotency_key
