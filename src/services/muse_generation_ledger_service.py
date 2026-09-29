from __future__ import annotations

from uuid import UUID

from src.models.muse_generation import (
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    is_terminal_state,
)
from src.models.video_job import VideoJob


class MuseGenerationLedgerService:
    """
    Durable, restart-safe Muse attempt persistence and the state-
    machine invariants that make it credit-safe - mirrors
    GoogleFlowGenerationLedgerService exactly, operating on
    job.muse_generation_attempts instead of job.flow_generation_attempts.

    The only intended writer of `job.muse_generation_attempts`. Direct
    list mutation anywhere else would bypass every invariant enforced
    here.
    """

    @staticmethod
    def create_attempt(
        job: VideoJob,
        request: MuseGenerationRequest,
    ) -> MuseGenerationAttempt:
        """
        Start a new attempt for this request's scene.

        This is also the regeneration mechanism - deliberately the
        only creation path, called again for a scene that already has
        one or more terminal (READY/QC_FAILED/FAILED) attempts. A new
        attempt for a scene with a still-in-flight (non-terminal)
        attempt is refused outright.
        """

        existing_for_scene = [
            attempt
            for attempt in job.muse_generation_attempts
            if (attempt.request.scene_number, attempt.request.clip_sequence_index)
            == (request.scene_number, request.clip_sequence_index)
        ]

        in_flight = [
            attempt
            for attempt in existing_for_scene
            if not is_terminal_state(attempt.state)
        ]

        if in_flight:
            raise ValueError(
                f"Scene {request.scene_number} already has an in-flight "
                f"Muse attempt (state={in_flight[0].state.value}) - resolve "
                "or reconcile it before starting a new one."
            )

        reused_idempotency_key = any(
            attempt.request.idempotency_key == request.idempotency_key
            for attempt in existing_for_scene
        )

        if reused_idempotency_key:
            raise ValueError(
                "A new Muse attempt must use an idempotency_key that no "
                "prior attempt for this scene has already used."
            )

        attempt = MuseGenerationAttempt(
            request=request,
            profile_id=request.profile_id,
            attempt_number=len(existing_for_scene) + 1,
        )

        job.muse_generation_attempts.append(attempt)

        return attempt

    @staticmethod
    def record_transition(
        job: VideoJob,
        attempt_id: UUID,
        next_state: MuseGenerationState,
        *,
        detail: str | None = None,
    ) -> MuseGenerationAttempt:
        """
        Advance one attempt by exactly one validated transition,
        replacing its entry in place - never appending a duplicate,
        never deleting history.
        """

        index = MuseGenerationLedgerService._find_index(job, attempt_id)
        updated = job.muse_generation_attempts[index].with_transition(
            next_state, detail=detail
        )
        job.muse_generation_attempts[index] = updated

        return updated

    @staticmethod
    def replace_attempt(
        job: VideoJob,
        attempt: MuseGenerationAttempt,
    ) -> None:
        """
        Store an attempt whose own transitions were already validated
        elsewhere. Raises if no attempt with this id exists yet - this
        replaces an existing entry, it never creates one.
        """

        index = MuseGenerationLedgerService._find_index(job, attempt.id)
        job.muse_generation_attempts[index] = attempt

    @staticmethod
    def reconcile_on_restart(
        job: VideoJob,
    ) -> list[MuseGenerationAttempt]:
        """
        Any attempt found still sitting at SUBMITTING means the
        application stopped somewhere between "about to submit" and
        "positive evidence the submission landed" - never trusted to
        still be genuinely in progress, never blindly assumed to have
        failed either. Reconciled to SUBMISSION_UNCERTAIN.

        Returns every attempt this call actually changed.
        """

        reconciled: list[MuseGenerationAttempt] = []

        for index, attempt in enumerate(job.muse_generation_attempts):
            if attempt.state != MuseGenerationState.SUBMITTING:
                continue

            updated = attempt.with_transition(
                MuseGenerationState.SUBMISSION_UNCERTAIN,
                detail=(
                    "Reconciled on restart: the application stopped while "
                    "this attempt was mid-submission, with no positive "
                    "evidence either way."
                ),
            )
            job.muse_generation_attempts[index] = updated
            reconciled.append(updated)

        return reconciled

    @staticmethod
    def attempts_for_scene(
        job: VideoJob,
        scene_number: int,
        *,
        clip_sequence_index: int = 0,
    ) -> list[MuseGenerationAttempt]:
        """Every attempt ever made for one (scene_number, clip_sequence_index)
        sub-clip, oldest first."""

        return sorted(
            (
                attempt
                for attempt in job.muse_generation_attempts
                if (attempt.request.scene_number, attempt.request.clip_sequence_index)
                == (scene_number, clip_sequence_index)
            ),
            key=lambda attempt: attempt.attempt_number,
        )

    @staticmethod
    def latest_attempt_for_scene(
        job: VideoJob,
        scene_number: int,
        *,
        clip_sequence_index: int = 0,
    ) -> MuseGenerationAttempt | None:
        """The most recent attempt for one sub-clip, or None if it never had one."""

        attempts = MuseGenerationLedgerService.attempts_for_scene(
            job, scene_number, clip_sequence_index=clip_sequence_index
        )

        return attempts[-1] if attempts else None

    @staticmethod
    def ready_attempt_for_scene(
        job: VideoJob,
        scene_number: int,
        *,
        clip_sequence_index: int = 0,
    ) -> MuseGenerationAttempt | None:
        """The accepted (READY) attempt for one sub-clip, if any."""

        for attempt in job.muse_generation_attempts:
            if (
                attempt.request.scene_number,
                attempt.request.clip_sequence_index,
            ) == (
                scene_number,
                clip_sequence_index,
            ) and attempt.state == MuseGenerationState.READY:
                return attempt

        return None

    @staticmethod
    def _find_index(job: VideoJob, attempt_id: UUID) -> int:
        for index, attempt in enumerate(job.muse_generation_attempts):
            if attempt.id == attempt_id:
                return index

        raise ValueError(f"No Muse generation attempt found with id={attempt_id}.")
