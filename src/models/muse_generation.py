from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.media_technical_validation import MediaTechnicalValidationResult

# Muse (muse.ai) External UI Automation - a second, parallel
# EXTERNAL_UI_VIDEO provider stack alongside Google Flow's
# (src/models/google_flow_generation.py), NOT a generalization of it -
# see this session's own architecture investigation: the Flow-specific
# naming goes all the way into VideoJob.flow_generation_attempts'
# concrete type, and generalizing that (plus the ledger/orchestrator
# built directly on top of it) would mean refactoring an already-
# stable, just-fixed, live-tested subsystem for no functional gain
# right now. Muse implements the same SHAPE (submit/observe/download/
# cancel, an append-only state-history attempt, a durable ledger) with
# its own concrete types, exactly like adapter.py and real_adapter.py
# already coexist as two concrete GoogleFlow implementations with no
# shared generic base beyond the abstract provider interface.
#
# Same hard boundary as Google Flow: nothing here ever stores a Meta
# password, an MFA/email-OTP value, a CAPTCHA answer, a cookie, or an
# auth token. A real browser session lives entirely in a local,
# persistent Chromium profile directory outside this model layer.
#
# State machine is deliberately SIMPLER than Google Flow's - confirmed
# live 2026-09-29: Muse's real UI is a chat box (type a prompt, press
# enter) with no separate settings panel, confirmation dialog, or
# "Agent mode" toggle Flow's own UI has. There is nothing to model for
# SETTINGS_VERIFIED/PROMPT_PREPARED/ANALYZING/CONFIRMATION_REQUIRED/
# CONFIRMING/HUMAN_ACTION_REQUIRED - copying those states over from
# Flow would model UI mechanics Muse doesn't actually have.


class MuseGenerationState(str, Enum):
    """One Muse generation attempt's lifecycle state."""

    PLANNED = "planned"
    SUBMITTING = "submitting"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    SUBMITTED = "submitted"
    GENERATING = "generating"
    READY_TO_DOWNLOAD = "ready_to_download"
    DOWNLOADED = "downloaded"
    QC_FAILED = "qc_failed"
    READY = "ready"
    AUTH_REQUIRED = "auth_required"
    UI_CHANGED = "ui_changed"
    FAILED = "failed"


# Terminal states: this attempt object will never transition again.
# QC_FAILED is terminal for *this* attempt - deliberate regeneration
# creates a new attempt/version, it is never resumed in place (same
# rule as Google Flow's own _TERMINAL_STATES).
_TERMINAL_STATES = frozenset(
    {
        MuseGenerationState.READY,
        MuseGenerationState.QC_FAILED,
        MuseGenerationState.FAILED,
    }
)

# "Interrupt" states reachable from any non-terminal state - triggered
# by an external condition (auth expired, the Muse UI's structure no
# longer matches expectations, or the credit-sensitive submit boundary
# was crossed with no positive evidence either way) rather than by
# ordinary forward progress.
_INTERRUPT_STATES = frozenset(
    {
        MuseGenerationState.AUTH_REQUIRED,
        MuseGenerationState.UI_CHANGED,
        MuseGenerationState.SUBMISSION_UNCERTAIN,
        MuseGenerationState.FAILED,
    }
)

_FORWARD_TRANSITIONS: dict[MuseGenerationState, frozenset[MuseGenerationState]] = {
    MuseGenerationState.PLANNED: frozenset({MuseGenerationState.SUBMITTING}),
    MuseGenerationState.SUBMITTING: frozenset({MuseGenerationState.SUBMITTED}),
    MuseGenerationState.SUBMITTED: frozenset({MuseGenerationState.GENERATING}),
    MuseGenerationState.GENERATING: frozenset({MuseGenerationState.READY_TO_DOWNLOAD}),
    MuseGenerationState.READY_TO_DOWNLOAD: frozenset({MuseGenerationState.DOWNLOADED}),
    MuseGenerationState.DOWNLOADED: frozenset(
        {MuseGenerationState.READY, MuseGenerationState.QC_FAILED}
    ),
    # Reconciliation exits - a reconciled uncertain/interrupted attempt
    # resumes forward progress from wherever positive evidence says it
    # actually reached, never a blind restart from PLANNED (that would
    # risk a duplicate paid submission).
    MuseGenerationState.SUBMISSION_UNCERTAIN: frozenset(
        {
            MuseGenerationState.SUBMITTED,
            MuseGenerationState.GENERATING,
            MuseGenerationState.FAILED,
        }
    ),
    # Real-world finding, 2026-09-29: resume_after_auth() re-calls
    # submit() on the SAME attempt object without resetting its state
    # first - and submit()'s own first real transition (both the fake
    # test provider and the real adapter) targets SUBMITTING directly,
    # not PLANNED. AUTH_REQUIRED is only ever set before that boundary
    # (submit() checks authentication before doing anything else), so
    # resuming straight to SUBMITTING carries the exact same "never
    # crossed the credit-sensitive boundary yet" guarantee Google
    # Flow's own resume_after_auth() docstring relies on.
    MuseGenerationState.AUTH_REQUIRED: frozenset({MuseGenerationState.SUBMITTING}),
    MuseGenerationState.UI_CHANGED: frozenset(),
}


def is_terminal_state(state: MuseGenerationState) -> bool:
    """Whether an attempt in this state will never transition again."""

    return state in _TERMINAL_STATES


def is_valid_transition(
    current: MuseGenerationState,
    next_state: MuseGenerationState,
) -> bool:
    """
    Whether next_state may legally follow current.

    A terminal state never transitions again. Any non-terminal state
    may always fall into one of the interrupt states (AUTH_REQUIRED/
    UI_CHANGED/SUBMISSION_UNCERTAIN/FAILED) - those are triggered by
    external conditions that can genuinely occur at almost any point,
    not by this attempt's own forward logic. Everything else must
    follow _FORWARD_TRANSITIONS exactly.
    """

    if current in _TERMINAL_STATES:
        return False

    if next_state in _INTERRUPT_STATES:
        return True

    return next_state in _FORWARD_TRANSITIONS.get(current, frozenset())


class MuseFailureCode(str, Enum):
    """Stable, greppable identifier for one kind of Muse generation failure."""

    UI_CHANGED = "ui_changed"
    AUTH_REQUIRED = "auth_required"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    REFERENCE_DROPPED = "reference_dropped"
    TRANSIENT_NAVIGATION_FAILURE = "transient_navigation_failure"
    DOWNLOAD_FAILED = "download_failed"
    QC_FAILED = "qc_failed"
    BUDGET_BLOCKED = "budget_blocked"
    PROFILE_COOLDOWN = "profile_cooldown"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class MuseFailure(MissionBaseModel):
    """
    One typed Muse failure - same shape discipline as
    GoogleFlowFailure: occurred_after_possible_credit_exposure is what
    a retry policy uses to decide "retryable, no cost implication"
    versus "must be reconciled, never blindly retried."
    """

    code: MuseFailureCode
    message: str

    occurred_after_possible_credit_exposure: bool = False

    recoverable: bool = True
    requires_human_action: bool = False

    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Muse failure message cannot be empty.")

        return cleaned


class MuseReferenceRole(str, Enum):
    """Semantic role of one reference asset submitted to Muse."""

    CHARACTER = "character"
    LOCATION = "location"
    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    OTHER = "other"


class MuseReferenceAsset(MissionBaseModel):
    """
    One reference asset (image/file) to attach alongside a Muse
    prompt - canonical identity, not a bare file path, matching
    GoogleFlowReferenceAsset's own "detectable, never silently
    dropped" discipline.
    """

    source_path: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    role: MuseReferenceRole
    version: int = Field(default=1, ge=1)

    # Which continuity-bible identity (a character or place) this reference
    # stands for, so the Clip check can say WHO was attached to a scene.
    # None for a reference that is not an identity's (e.g. a sub-clip's seam
    # frame) and for requests recorded before this field existed.
    identity_name: str | None = None

    @field_validator("source_path", "checksum")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Reference asset text fields cannot be empty.")

        return cleaned


class MuseGenerationRequest(MissionBaseModel):
    """
    Everything Mission Automation's own production authority has
    already decided about one requested clip, before Muse ever sees
    it. The Muse adapter is a pure executor of this already-resolved
    request - it must never rewrite the prompt or invent settings.

    No MuseExecutionSettings field (unlike Google Flow's
    GoogleFlowExecutionSettings) - confirmed live 2026-09-29 that
    Muse's real UI exposes no settings panel at all (no model/duration/
    aspect-ratio controls observed): it is a chat box, prompt in,
    fixed-length clip out. Adding a settings model now would be
    fabricating unverified specifics; one can be added later if a real
    control is ever found.
    """

    scene_number: int = Field(ge=1)

    # Mirrors GoogleFlowGenerationRequest's own field of the same name
    # for future multi-clip splitting parity - default 0 means "the
    # only request for this scene."
    clip_sequence_index: int = Field(default=0, ge=0)

    locked_script_hash: str | None = None

    prompt: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    reference_assets: list[MuseReferenceAsset] = Field(default_factory=list)

    profile_id: str = Field(min_length=1)

    estimated_cost_usd: float = Field(default=0.0, ge=0.0)

    idempotency_key: str = Field(min_length=1)

    @field_validator("prompt", "prompt_version", "profile_id", "idempotency_key")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Muse generation request text cannot be empty.")

        return cleaned

    @property
    def prompt_hash(self) -> str:
        """A deterministic hash of the exact prompt text."""

        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


class MuseQCOutcome(str, Enum):
    """Disposition of one Muse-generated clip's semantic QC."""

    PASS = "pass"
    HUMAN_REVIEW = "human_review"
    RETRY_REQUIRED = "retry_required"
    REPLACE_REQUIRED = "replace_required"
    INVALID = "invalid"


class MuseQCResult(MissionBaseModel):
    """
    Semantic/multimodal QC verdict for one downloaded Muse clip. Only
    a PASS outcome may ever produce a READY attempt; every other
    outcome is preserved, never silently discarded.
    """

    outcome: MuseQCOutcome
    findings: list[str] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.outcome == MuseQCOutcome.PASS


class MuseStateTransition(MissionBaseModel):
    """One append-only entry in a MuseGenerationAttempt's history."""

    state: MuseGenerationState
    detail: str | None = None


class MuseGenerationAttempt(MissionBaseModel):
    """
    One durable, restart-safe Muse generation attempt.

    state_history is append-only and is the actual source of truth
    for "what has already happened"; `state` always mirrors
    state_history[-1].state, enforced by a validator. A regeneration
    after QC_FAILED/FAILED never reuses this object - it is a
    brand-new MuseGenerationAttempt with attempt_number incremented
    and a fresh idempotency_key on its own request.
    """

    request: MuseGenerationRequest
    attempt_number: int = Field(default=1, ge=1)

    state: MuseGenerationState = MuseGenerationState.PLANNED
    state_history: list[MuseStateTransition] = Field(
        default_factory=lambda: [MuseStateTransition(state=MuseGenerationState.PLANNED)]
    )

    profile_id: str = Field(min_length=1)

    downloaded_file: str | None = None
    checksum: str | None = None

    # The checksum of the file exactly as Muse delivered it, before any
    # local trim. `checksum` is re-computed after a trim (it describes what
    # gets attached), so the SAME Muse video downloaded for two scenes and
    # trimmed to two different lengths has two different checksums - this one
    # stays equal, which is what duplicate detection must compare.
    source_checksum: str | None = None

    technical_validation: MediaTechnicalValidationResult | None = None
    qc_result: MuseQCResult | None = None

    failure: MuseFailure | None = None

    @field_validator("profile_id")
    @classmethod
    def clean_profile_id(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Muse generation attempt profile_id is required.")

        return cleaned

    @model_validator(mode="after")
    def validate_attempt(self) -> MuseGenerationAttempt:
        if not self.state_history:
            raise ValueError("Muse generation attempt state_history cannot be empty.")

        if self.state_history[0].state != MuseGenerationState.PLANNED:
            raise ValueError("Muse generation attempt history must start at PLANNED.")

        if self.state_history[-1].state != self.state:
            raise ValueError(
                "Muse generation attempt state must match the most recent "
                "state_history entry."
            )

        if self.state == MuseGenerationState.READY and self.qc_result is None:
            raise ValueError("A READY attempt requires a passing qc_result.")

        if (
            self.state == MuseGenerationState.READY
            and self.qc_result is not None
            and not self.qc_result.accepted
        ):
            raise ValueError("A READY attempt requires an accepted qc_result.")

        if self.state == MuseGenerationState.QC_FAILED and (
            self.qc_result is None or self.qc_result.accepted
        ):
            raise ValueError("A QC_FAILED attempt requires a non-accepted qc_result.")

        return self

    def with_transition(
        self,
        next_state: MuseGenerationState,
        *,
        detail: str | None = None,
    ) -> MuseGenerationAttempt:
        """
        Return a new attempt with one additional, validated transition
        appended. Returns a copy rather than mutating in place.
        """

        if not is_valid_transition(self.state, next_state):
            raise ValueError(
                f"Illegal Muse generation state transition: "
                f"{self.state.value} -> {next_state.value}."
            )

        new_history = [
            *self.state_history,
            MuseStateTransition(state=next_state, detail=detail),
        ]

        return self.model_copy(
            update={"state": next_state, "state_history": new_history}
        )
