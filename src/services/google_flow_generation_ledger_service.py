from __future__ import annotations

from uuid import UUID

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    is_terminal_state,
)
from src.models.video_job import VideoJob


class GoogleFlowGenerationLedgerService:
    """
    Google Flow External UI Automation, GF-1: durable, restart-safe
    attempt persistence and the state-machine invariants that make it
    credit-safe.

    Persistence itself is deliberately not this service's job - it
    only ever mutates `VideoJob.flow_generation_attempts` in memory,
    the exact same pattern every other VideoJob-mutating service in
    this codebase already uses (ScriptLockService, VoiceTimelineService,
    InvalidationService, ...). The caller (a future orchestrator/GUI
    handler) is responsible for persisting the job through
    `JsonJobStore` immediately before and after a credit-sensitive
    transition, per this initiative's own "persist immediately before
    that operation; persist again after positive evidence" rule - this
    service does not introduce a second, competing persistence
    mechanism (no new database, no separate ledger file), matching
    this codebase's "adapt to what already exists" convention.

    The only intended writer of `job.flow_generation_attempts`. Direct
    list mutation anywhere else would bypass every invariant enforced
    here.
    """

    @staticmethod
    def create_attempt(
        job: VideoJob,
        request: GoogleFlowGenerationRequest,
    ) -> GoogleFlowGenerationAttempt:
        """
        Start a new attempt for this request's scene.

        This is also the regeneration mechanism - deliberately the
        only creation path, called again for a scene that already has
        one or more terminal (READY/QC_FAILED/FAILED) attempts. A new
        attempt for a scene with a still-in-flight (non-terminal)
        attempt is refused outright - "never fail over/duplicate while
        a previous submission is uncertain" holds structurally, not by
        caller discipline alone.
        """

        existing_for_scene = [
            attempt
            for attempt in job.flow_generation_attempts
            if attempt.request.scene_number == request.scene_number
        ]

        in_flight = [
            attempt
            for attempt in existing_for_scene
            if not is_terminal_state(attempt.state)
        ]

        if in_flight:
            raise ValueError(
                f"Scene {request.scene_number} already has an in-flight "
                f"Google Flow attempt (state={in_flight[0].state.value}) - "
                "resolve or reconcile it before starting a new one."
            )

        reused_idempotency_key = any(
            attempt.request.idempotency_key == request.idempotency_key
            for attempt in existing_for_scene
        )

        if reused_idempotency_key:
            raise ValueError(
                "A new Google Flow attempt must use an idempotency_key "
                "that no prior attempt for this scene has already used."
            )

        attempt = GoogleFlowGenerationAttempt(
            request=request,
            profile_id=request.profile_id,
            attempt_number=len(existing_for_scene) + 1,
        )

        job.flow_generation_attempts.append(attempt)

        return attempt

    @staticmethod
    def record_transition(
        job: VideoJob,
        attempt_id: UUID,
        next_state: GoogleFlowGenerationState,
        *,
        detail: str | None = None,
    ) -> GoogleFlowGenerationAttempt:
        """
        Advance one attempt by exactly one validated transition,
        replacing its entry in place - never appending a duplicate,
        never deleting history. Raises if the attempt doesn't exist or
        the transition is illegal (GoogleFlowGenerationAttempt.
        with_transition's own validation).
        """

        index = GoogleFlowGenerationLedgerService._find_index(job, attempt_id)
        updated = job.flow_generation_attempts[index].with_transition(
            next_state, detail=detail
        )
        job.flow_generation_attempts[index] = updated

        return updated

    @staticmethod
    def reconcile_on_restart(
        job: VideoJob,
    ) -> list[GoogleFlowGenerationAttempt]:
        """
        The credit-sensitive-state rule's own restart behavior: any
        attempt found still sitting at SUBMITTING means the
        application stopped somewhere between "about to click
        generate" and "positive evidence the click landed" - it is
        never trusted to still be genuinely in progress (nothing is
        running to progress it), and is never blindly assumed to have
        failed either, since the click may well have succeeded.
        Reconciled to SUBMISSION_UNCERTAIN so a later phase (GF-7's
        real reconciliation, which needs the actual Flow adapter to
        check) - never a blind automatic resubmission.

        Returns every attempt this call actually changed.
        """

        reconciled: list[GoogleFlowGenerationAttempt] = []

        for index, attempt in enumerate(job.flow_generation_attempts):
            if attempt.state != GoogleFlowGenerationState.SUBMITTING:
                continue

            updated = attempt.with_transition(
                GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
                detail=(
                    "Reconciled on restart: the application stopped while "
                    "this attempt was mid-submission, with no positive "
                    "evidence either way."
                ),
            )
            job.flow_generation_attempts[index] = updated
            reconciled.append(updated)

        return reconciled

    @staticmethod
    def attempts_for_scene(
        job: VideoJob,
        scene_number: int,
    ) -> list[GoogleFlowGenerationAttempt]:
        """Every attempt ever made for one scene, oldest first."""

        return sorted(
            (
                attempt
                for attempt in job.flow_generation_attempts
                if attempt.request.scene_number == scene_number
            ),
            key=lambda attempt: attempt.attempt_number,
        )

    @staticmethod
    def latest_attempt_for_scene(
        job: VideoJob,
        scene_number: int,
    ) -> GoogleFlowGenerationAttempt | None:
        """The most recent attempt for one scene, or None if it never had one."""

        attempts = GoogleFlowGenerationLedgerService.attempts_for_scene(
            job, scene_number
        )

        return attempts[-1] if attempts else None

    @staticmethod
    def ready_attempt_for_scene(
        job: VideoJob,
        scene_number: int,
    ) -> GoogleFlowGenerationAttempt | None:
        """
        The accepted (READY) attempt for one scene, if any - what a
        future bulk-resume pass (GF-12) uses to decide "skip, already
        done" rather than starting a redundant regeneration.
        """

        for attempt in job.flow_generation_attempts:
            if (
                attempt.request.scene_number == scene_number
                and attempt.state == GoogleFlowGenerationState.READY
            ):
                return attempt

        return None

    @staticmethod
    def _find_index(job: VideoJob, attempt_id: UUID) -> int:
        for index, attempt in enumerate(job.flow_generation_attempts):
            if attempt.id == attempt_id:
                return index

        raise ValueError(
            f"No Google Flow generation attempt found with id={attempt_id}."
        )
