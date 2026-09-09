from __future__ import annotations

import hashlib
from enum import Enum

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.media_technical_validation import MediaTechnicalValidationResult

# Google Flow External UI Automation - GF-0: Product Boundary, Threat
# Model & Contracts.
#
# Google Flow is an EXTERNAL_UI provider, not an official documented
# video-generation API (ProviderCategory.EXTERNAL_UI_VIDEO,
# src/models/provider_profile.py, keeps this distinction explicit
# rather than conflating it with ProviderCategory.VIDEO). Automation
# operates through the normal authenticated Google Flow web UI only.
#
# Hard boundary, enforced by this whole module's design, not just
# documented: nothing here ever stores a Google password, an MFA
# value, a CAPTCHA answer, a cookie, or an auth token.
# GoogleFlowAccountProfile (GF-2/GF-3) persists only safe profile
# metadata; a real browser session lives entirely in a local,
# persistent Chromium profile directory outside this model layer.
#
# Worker/async execution model (recorded here per GF-0's own
# checklist, even though the executing code lands in GF-2): every
# service and provider in this codebase (voice/music/SFX/stock/
# thumbnail generation, the whole render pipeline) is synchronous -
# there is no asyncio anywhere in src/. Introducing asyncio only for
# Google Flow would fight that architecture, not extend it, and is
# exactly the kind of ad-hoc event-loop mixing GF-1's own "reproduce
# the Playwright Sync API inside the asyncio loop" warning describes.
# The chosen design is Playwright's Sync API, driven inside a
# dedicated background worker thread (src/browser/flow_worker.py,
# GF-2) - not the GUI thread, not asyncio - so a multi-minute Flow
# generation never blocks PySide6's own Qt event loop, matching this
# codebase's existing "no background-threading exists yet, added only
# when a concrete need appears" posture (see docs/REMAINING_GAPS.md).


class GoogleFlowGenerationState(str, Enum):
    """
    One Google Flow generation attempt's lifecycle state.

    Names match the two authoritative implementation-plan documents
    verbatim ("Exact names may differ. Behavior may not." - kept
    identical anyway, for direct traceability against the spec).
    """

    PLANNED = "planned"
    SETTINGS_VERIFIED = "settings_verified"
    PROMPT_PREPARED = "prompt_prepared"
    ANALYZING = "analyzing"
    CONFIRMATION_REQUIRED = "confirmation_required"
    CONFIRMING = "confirming"
    SUBMITTING = "submitting"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    SUBMITTED = "submitted"
    GENERATING = "generating"
    READY_TO_DOWNLOAD = "ready_to_download"
    DOWNLOADED = "downloaded"
    QC_FAILED = "qc_failed"
    READY = "ready"
    AUTH_REQUIRED = "auth_required"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    UI_CHANGED = "ui_changed"
    FAILED = "failed"


# Terminal states: this attempt object will never transition again.
# QC_FAILED is terminal for *this* attempt - "deliberate regeneration
# creates a new attempt/version" (GF-10/GF-26), it is never resumed in
# place.
_TERMINAL_STATES = frozenset(
    {
        GoogleFlowGenerationState.READY,
        GoogleFlowGenerationState.QC_FAILED,
        GoogleFlowGenerationState.FAILED,
    }
)

# "Interrupt" states reachable from any non-terminal state - each one
# is triggered by an external condition (auth expired, the Flow UI's
# structure no longer matches expectations, a human decision is
# needed, or the credit-sensitive submit boundary was crossed with no
# positive evidence either way) rather than by ordinary forward
# progress. GF-7/GF-8 own the actual reconciliation logic that decides
# what happens next from one of these; this module only defines that
# reaching them from mid-flight is always structurally valid.
_INTERRUPT_STATES = frozenset(
    {
        GoogleFlowGenerationState.AUTH_REQUIRED,
        GoogleFlowGenerationState.HUMAN_ACTION_REQUIRED,
        GoogleFlowGenerationState.UI_CHANGED,
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
        GoogleFlowGenerationState.FAILED,
    }
)

# The ordinary, no-surprises happy path. GF-6's "confirmation may be
# absent" is modeled as an alternate edge (PROMPT_PREPARED can also
# reach SUBMITTING directly), not a second parallel enum.
_FORWARD_TRANSITIONS: dict[
    GoogleFlowGenerationState, frozenset[GoogleFlowGenerationState]
] = {
    GoogleFlowGenerationState.PLANNED: frozenset(
        {GoogleFlowGenerationState.SETTINGS_VERIFIED}
    ),
    GoogleFlowGenerationState.SETTINGS_VERIFIED: frozenset(
        {GoogleFlowGenerationState.PROMPT_PREPARED}
    ),
    GoogleFlowGenerationState.PROMPT_PREPARED: frozenset(
        {
            GoogleFlowGenerationState.ANALYZING,
            # Confirmation-optional path (GF-20): some Flow/account
            # configurations generate immediately with no separate
            # analysis/confirmation step.
            GoogleFlowGenerationState.SUBMITTING,
        }
    ),
    GoogleFlowGenerationState.ANALYZING: frozenset(
        {
            GoogleFlowGenerationState.CONFIRMATION_REQUIRED,
            # Analysis can also resolve straight to submission when
            # this account's Flow configuration needs no confirmation
            # click at all.
            GoogleFlowGenerationState.SUBMITTING,
        }
    ),
    GoogleFlowGenerationState.CONFIRMATION_REQUIRED: frozenset(
        {GoogleFlowGenerationState.CONFIRMING}
    ),
    GoogleFlowGenerationState.CONFIRMING: frozenset(
        {GoogleFlowGenerationState.SUBMITTING}
    ),
    GoogleFlowGenerationState.SUBMITTING: frozenset(
        {GoogleFlowGenerationState.SUBMITTED}
    ),
    GoogleFlowGenerationState.SUBMITTED: frozenset(
        {GoogleFlowGenerationState.GENERATING}
    ),
    GoogleFlowGenerationState.GENERATING: frozenset(
        {GoogleFlowGenerationState.READY_TO_DOWNLOAD}
    ),
    GoogleFlowGenerationState.READY_TO_DOWNLOAD: frozenset(
        {GoogleFlowGenerationState.DOWNLOADED}
    ),
    GoogleFlowGenerationState.DOWNLOADED: frozenset(
        {GoogleFlowGenerationState.READY, GoogleFlowGenerationState.QC_FAILED}
    ),
    # Reconciliation exits (GF-7): a reconciled uncertain/interrupted
    # attempt resumes forward progress from wherever positive evidence
    # says it actually reached - never a blind restart from PLANNED,
    # since that would risk a duplicate paid submission.
    GoogleFlowGenerationState.SUBMISSION_UNCERTAIN: frozenset(
        {
            GoogleFlowGenerationState.SUBMITTED,
            GoogleFlowGenerationState.GENERATING,
            GoogleFlowGenerationState.FAILED,
        }
    ),
    GoogleFlowGenerationState.AUTH_REQUIRED: frozenset(
        {
            GoogleFlowGenerationState.PLANNED,
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            GoogleFlowGenerationState.PROMPT_PREPARED,
        }
    ),
    GoogleFlowGenerationState.UI_CHANGED: frozenset(),
    GoogleFlowGenerationState.HUMAN_ACTION_REQUIRED: frozenset(
        {
            GoogleFlowGenerationState.CONFIRMATION_REQUIRED,
            GoogleFlowGenerationState.SUBMITTING,
        }
    ),
}


def is_terminal_state(state: GoogleFlowGenerationState) -> bool:
    """Whether an attempt in this state will never transition again."""

    return state in _TERMINAL_STATES


def is_valid_transition(
    current: GoogleFlowGenerationState,
    next_state: GoogleFlowGenerationState,
) -> bool:
    """
    Whether next_state may legally follow current.

    A terminal state never transitions again. Any non-terminal state
    may always fall into one of the interrupt states (AUTH_REQUIRED/
    HUMAN_ACTION_REQUIRED/UI_CHANGED/SUBMISSION_UNCERTAIN/FAILED) -
    those are triggered by external conditions that can genuinely
    occur at almost any point, not by this attempt's own forward
    logic, so enumerating every source state for each of them would
    only duplicate this same rule five times. Everything else must
    follow _FORWARD_TRANSITIONS exactly.
    """

    if current in _TERMINAL_STATES:
        return False

    if next_state in _INTERRUPT_STATES:
        return True

    return next_state in _FORWARD_TRANSITIONS.get(current, frozenset())


class GoogleFlowFailureCode(str, Enum):
    """
    Stable, greppable identifier for one kind of Google Flow
    generation failure - mirrors this codebase's existing
    AssetFailureReason/BlockerCode convention (typed failures, never a
    bare exception message) for a domain those enums don't cover.
    """

    FLOW_SETTINGS_UNAVAILABLE = "flow_settings_unavailable"
    FLOW_SETTINGS_MISMATCH = "flow_settings_mismatch"
    UI_CHANGED = "ui_changed"
    AUTH_REQUIRED = "auth_required"
    HUMAN_ACTION_REQUIRED = "human_action_required"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    REFERENCE_DROPPED = "reference_dropped"
    TRANSIENT_NAVIGATION_FAILURE = "transient_navigation_failure"
    DOWNLOAD_FAILED = "download_failed"
    QC_FAILED = "qc_failed"
    BUDGET_BLOCKED = "budget_blocked"
    PROFILE_COOLDOWN = "profile_cooldown"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class GoogleFlowFailure(MissionBaseModel):
    """
    One typed Google Flow failure - the same shape discipline as
    AssetModuleFailure (module_name/reason/message/recoverable/
    recovery_options), extended with the one thing this domain's own
    credit-sensitive-state rule (GF-1 section 8) explicitly requires
    tracking: whether the failure happened before or after this
    attempt could possibly have consumed provider credit. That single
    boolean is what GF-11's retry policy uses to decide "retryable, no
    cost implication" versus "must be reconciled, never blindly
    retried."
    """

    code: GoogleFlowFailureCode
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
            raise ValueError("Google Flow failure message cannot be empty.")

        return cleaned


class GoogleFlowReferenceRole(str, Enum):
    """Semantic role of one reference asset submitted to Google Flow."""

    CHARACTER = "character"
    LOCATION = "location"
    STYLE = "style"
    FIRST_FRAME = "first_frame"
    LAST_FRAME = "last_frame"
    OTHER = "other"


class GoogleFlowReferenceAsset(MissionBaseModel):
    """
    One reference asset (image/file) to submit alongside a Google Flow
    prompt - canonical identity, not a bare file path, so a dropped or
    stale reference is detectable rather than silently ignored (GF-17:
    "Missing/dropped reference: STOP before generation").
    """

    source_path: str = Field(min_length=1)
    checksum: str = Field(min_length=1)
    role: GoogleFlowReferenceRole
    version: int = Field(default=1, ge=1)

    @field_validator("source_path", "checksum")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Reference asset text fields cannot be empty.")

        return cleaned


class GoogleFlowExecutionSettings(MissionBaseModel):
    """
    Typed, persisted Google Flow execution settings for one generation
    request.

    Every field is deliberately an open string, not a closed enum -
    this codebase has no verified, current knowledge of Google Flow's
    real model/mode/aspect-ratio vocabulary (the same "don't fabricate
    unverified specifics" discipline already used for
    ElevenLabsVoiceTranslationService's unsupported_controls). The
    Flow adapter (GF-4/GF-5) is the one place that maps a value here
    onto an actual visible Flow control, and is where a real,
    versioned vocabulary belongs once it's been observed against the
    live product - not guessed here.
    """

    model_family: str | None = None
    generation_mode: str | None = None
    duration_seconds: float | None = Field(default=None, gt=0.0)
    aspect_ratio: str | None = None
    generation_feature: str | None = None
    reference_mode: str | None = None
    # Added once genuinely observed against the real, authenticated
    # product (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md) - real Flow's
    # settings popover exposes resolution (e.g. "360p"/"720p") and a
    # variation count (how many videos one submission generates for
    # the same prompt, confirmed NOT to be a simple credit multiplier)
    # as their own distinct controls, not folded into any existing
    # field above. Still open, not a closed enum, for the same reason
    # every other field here is.
    resolution: str | None = None
    # Real-world finding: Flow's own current default, confirmed
    # directly against a real "New project" (a fresh project with no
    # settings ever touched), is x2 - two videos generated per
    # submission for the same prompt, not one. Every part of this
    # codebase's own Google Flow architecture (one scene -> one
    # generation attempt -> one downloaded clip, GoogleFlowGenerationLedgerService's
    # whole model) assumes exactly one result per submission -
    # leaving variation_count unset (this field's own prior default,
    # None) meant "never explicitly select an x-count", silently
    # trusting whatever Flow's own current default happened to be.
    # That is fine when the default genuinely is x1, but was actively
    # wrong the moment Flow's own default became x2 - every default-
    # settings submission through this codebase would generate two
    # videos (not necessarily double credits - GOOGLE_FLOW_REAL_UI_FINDINGS.md's
    # own earlier finding confirmed variation_count is NOT a simple
    # credits multiplier - but still two result tiles where this
    # codebase's own observe()/download() logic expects exactly one).
    # Defaulting to 1 here means every construction site, including
    # the bare GoogleFlowExecutionSettings() fallback
    # GoogleFlowGenerationOrchestratorService.submit_new_attempt() uses
    # when no caller-supplied settings exist, now always explicitly
    # requests x1 - correct regardless of whatever Flow's own current
    # UI default is or later becomes.
    variation_count: int = Field(default=1, gt=0)
    # Real, verified control (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md
    # section 3/4a): the "Agent" toggle. None means "leave Flow's own
    # current toggle state alone" (this class's usual "never touch a
    # setting the caller didn't ask for" rule) - True/False are
    # explicit requests to turn it on/off. Agent mode can trigger a
    # real confirmation-before-generating screen (an Agent-mode-only,
    # explicitly configurable Flow setting, section 4a) - see
    # GoogleFlowGenerationOrchestratorService's own agent-mode
    # approval gate, which this field feeds.
    agent_mode: bool | None = None

    @field_validator(
        "model_family",
        "generation_mode",
        "aspect_ratio",
        "generation_feature",
        "reference_mode",
        "resolution",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = value.strip()

        return cleaned or None


class GoogleFlowGenerationRequest(MissionBaseModel):
    """
    Everything Mission Automation's own production authority has
    already decided about one requested clip, before Google Flow ever
    sees it.

    The Flow adapter (GF-4 onward) is a pure executor of this already-
    resolved request - it must never rewrite the prompt, invent
    settings, or decide creative intent (GF-48's central design rule).
    """

    scene_number: int = Field(ge=1)

    # Binds this request to the exact locked script it was planned
    # against (Scene.locked_script_hash's own convention) - None only
    # for a project that never locked, matching every other
    # Post-Script-Approval artifact's own honest-null convention.
    locked_script_hash: str | None = None

    prompt: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)

    negative_constraints: list[str] = Field(default_factory=list)

    reference_assets: list[GoogleFlowReferenceAsset] = Field(default_factory=list)

    execution_settings: GoogleFlowExecutionSettings = Field(
        default_factory=GoogleFlowExecutionSettings
    )

    profile_id: str = Field(min_length=1)

    estimated_cost_usd: float = Field(default=0.0, ge=0.0)

    # A stable key for this exact creative request - reused across an
    # attempt's own crash-reconciliation, never regenerated per retry.
    # A NEW attempt/version (GF-26) always gets a new idempotency_key,
    # since deliberate regeneration is a different request, not a
    # retry of this one.
    idempotency_key: str = Field(min_length=1)

    @field_validator("prompt", "prompt_version", "profile_id", "idempotency_key")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Google Flow generation request text cannot be empty.")

        return cleaned

    @field_validator("negative_constraints")
    @classmethod
    def clean_negative_constraints(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if normalized and normalized not in cleaned:
                cleaned.append(normalized)

        return cleaned

    @property
    def prompt_hash(self) -> str:
        """
        A deterministic hash of the exact prompt text - the same
        "hash the real content, not id/created_at" pattern
        GeneratedScript.content_hash already uses, so a prompt cannot
        silently drift from what this hash attests to.
        """

        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


class GoogleFlowQCOutcome(str, Enum):
    """Disposition of one Google-Flow-generated clip's semantic QC."""

    PASS = "pass"
    HUMAN_REVIEW = "human_review"
    RETRY_REQUIRED = "retry_required"
    REPLACE_REQUIRED = "replace_required"
    INVALID = "invalid"


class GoogleFlowQCResult(MissionBaseModel):
    """
    Semantic/multimodal QC verdict for one downloaded Google Flow
    clip, evaluated against this request's own prompt/reference/shot
    authority (GF-10). Only a PASS outcome may ever produce a READY
    attempt; every other outcome is preserved, never silently
    discarded (GF-25: "Preserve rejected media and attempt history").
    """

    outcome: GoogleFlowQCOutcome
    findings: list[str] = Field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.outcome == GoogleFlowQCOutcome.PASS


class GoogleFlowStateTransition(MissionBaseModel):
    """One append-only entry in a GoogleFlowGenerationAttempt's history."""

    state: GoogleFlowGenerationState
    detail: str | None = None


class GoogleFlowGenerationAttempt(MissionBaseModel):
    """
    One durable, restart-safe Google Flow generation attempt.

    state_history is append-only and is the actual source of truth
    for "what has already happened" (GF-1's own persistence contract);
    `state` always mirrors state_history[-1].state, enforced by a
    validator rather than trusted to stay in sync by convention alone.
    A regeneration after QC_FAILED/FAILED never reuses this object -
    it is a brand-new GoogleFlowGenerationAttempt with attempt_number
    incremented and a fresh idempotency_key on its own request.
    """

    request: GoogleFlowGenerationRequest
    attempt_number: int = Field(default=1, ge=1)

    state: GoogleFlowGenerationState = GoogleFlowGenerationState.PLANNED
    state_history: list[GoogleFlowStateTransition] = Field(
        default_factory=lambda: [
            GoogleFlowStateTransition(state=GoogleFlowGenerationState.PLANNED)
        ]
    )

    profile_id: str = Field(min_length=1)

    downloaded_file: str | None = None
    checksum: str | None = None

    technical_validation: MediaTechnicalValidationResult | None = None
    qc_result: GoogleFlowQCResult | None = None

    failure: GoogleFlowFailure | None = None

    @field_validator("profile_id")
    @classmethod
    def clean_profile_id(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Google Flow generation attempt profile_id is required.")

        return cleaned

    @model_validator(mode="after")
    def validate_attempt(self) -> GoogleFlowGenerationAttempt:
        if not self.state_history:
            raise ValueError(
                "Google Flow generation attempt state_history cannot be empty."
            )

        if self.state_history[0].state != GoogleFlowGenerationState.PLANNED:
            raise ValueError(
                "Google Flow generation attempt history must start at PLANNED."
            )

        if self.state_history[-1].state != self.state:
            raise ValueError(
                "Google Flow generation attempt state must match the most "
                "recent state_history entry."
            )

        if self.state == GoogleFlowGenerationState.READY and self.qc_result is None:
            raise ValueError("A READY attempt requires a passing qc_result.")

        if (
            self.state == GoogleFlowGenerationState.READY
            and self.qc_result is not None
            and not self.qc_result.accepted
        ):
            raise ValueError("A READY attempt requires an accepted qc_result.")

        if self.state == GoogleFlowGenerationState.QC_FAILED and (
            self.qc_result is None or self.qc_result.accepted
        ):
            raise ValueError("A QC_FAILED attempt requires a non-accepted qc_result.")

        return self

    def with_transition(
        self,
        next_state: GoogleFlowGenerationState,
        *,
        detail: str | None = None,
    ) -> GoogleFlowGenerationAttempt:
        """
        Return a new attempt with one additional, validated transition
        appended.

        Returns a copy rather than mutating in place - matches this
        codebase's established append-only-history convention
        (ContentDecisionRecord, ScriptVersionHistory) of never
        rewriting a record that already exists, only ever adding to
        it.
        """

        if not is_valid_transition(self.state, next_state):
            raise ValueError(
                f"Illegal Google Flow generation state transition: "
                f"{self.state.value} -> {next_state.value}."
            )

        new_history = [
            *self.state_history,
            GoogleFlowStateTransition(state=next_state, detail=detail),
        ]

        return self.model_copy(
            update={"state": next_state, "state_history": new_history}
        )
