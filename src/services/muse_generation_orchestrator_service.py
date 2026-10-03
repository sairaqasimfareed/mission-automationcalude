from __future__ import annotations

from pathlib import Path

from src.models.muse_generation import (
    MuseFailure,
    MuseFailureCode,
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
    MuseQCOutcome,
    MuseQCResult,
    MuseReferenceAsset,
    is_terminal_state,
)
from src.models.video_job import VideoJob
from src.providers.muse_ui_provider import MuseUIProvider
from src.services.asset_provenance_service import AssetProvenanceService
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)
from src.services.muse_account_router_service import MuseAccountRouterService
from src.services.muse_generation_ledger_service import MuseGenerationLedgerService

# Same real-world finding Google Flow's own orchestrator names: a
# scene stuck at UI_CHANGED (or any non-terminal state with no defined
# forward transition) has no automated recovery path and permanently
# occupies its account's single in-flight slot
# (MuseAccountRouterService's own max_in_flight_per_account), blocking
# every other scene on that account too.
_CREDIT_SENSITIVE_STATES = frozenset(
    {
        MuseGenerationState.SUBMITTING,
        MuseGenerationState.SUBMISSION_UNCERTAIN,
        MuseGenerationState.SUBMITTED,
        MuseGenerationState.GENERATING,
        MuseGenerationState.READY_TO_DOWNLOAD,
        MuseGenerationState.DOWNLOADED,
    }
)


class MuseAttemptCreditSensitiveError(RuntimeError):
    """
    Raised by abandon_attempt() when the stuck attempt's own history
    shows it reached a credit-sensitive state before getting stuck -
    same rule as GoogleFlowAttemptCreditSensitiveError.
    """

    def __init__(self, attempt: MuseGenerationAttempt) -> None:
        self.attempt = attempt

        super().__init__(
            "This Muse attempt's own history shows it reached a real, "
            "credit-sensitive submission state before getting stuck at "
            f"{attempt.state.value} - it may already be a real generation "
            "in progress or complete. Verify in the real Muse account "
            "before abandoning; pass force=True once confirmed safe. See "
            ".attempt for details."
        )


class MuseGenerationOrchestratorService:
    """
    Ties routing, the durable ledger, budget protection, and the
    provider adapter together for Muse - mirrors
    GoogleFlowGenerationOrchestratorService exactly (same "canonical
    generation orchestrator" role, same GF-12-style operation
    vocabulary), operating on Muse's own models/ledger/router.

    No Agent-mode confirmation gate here (unlike Google Flow's own
    GoogleFlowAgentConfirmationRequiredError) - confirmed live that
    Muse's real UI exposes no such toggle to gate in the first place.
    """

    def __init__(
        self,
        *,
        provider: MuseUIProvider,
        account_router: MuseAccountRouterService,
        budget_service: ProviderBudgetService | None = None,
        max_in_flight_per_account: int = 1,
        technical_validation_service: MediaTechnicalValidationService | None = None,
        provenance_service: AssetProvenanceService | None = None,
    ) -> None:
        self._provider = provider
        self._account_router = account_router
        self._budget_service = budget_service
        self._max_in_flight_per_account = max_in_flight_per_account
        self._technical_validation_service = (
            technical_validation_service or MediaTechnicalValidationService()
        )
        self._provenance_service = provenance_service or AssetProvenanceService()

    def submit_new_attempt(
        self,
        job: VideoJob,
        *,
        scene_number: int,
        clip_sequence_index: int = 0,
        prompt: str,
        prompt_version: str,
        idempotency_key: str,
        reference_assets: list[MuseReferenceAsset] | None = None,
        locked_script_hash: str | None = None,
        estimated_cost_usd: float = 0.0,
        preferred_profile_id: str | None = None,
    ) -> MuseGenerationAttempt:
        """
        Route to an eligible account, gate on budget, create the
        ledger attempt, and drive it through the adapter's submit().

        Raises before anything credit-sensitive happens if: no
        eligible account exists (NoEligibleMuseAccountError), this
        scene already has a non-terminal attempt (ValueError, from
        create_attempt's own in-flight guard), or the budget gate
        rejects the estimated cost (ValueError, from
        ProviderBudgetService.reserve()). A reservation already made
        is released if the adapter's own submit() call raises an
        exception this orchestrator did not expect.

        preferred_profile_id: same manual-override contract as Google
        Flow's own submit_new_attempt() parameter of the same name.
        """

        in_flight_counts = self._in_flight_counts_by_profile(job)

        profile = self._account_router.select_account(
            in_flight_counts=in_flight_counts,
            max_in_flight_per_account=self._max_in_flight_per_account,
            preferred_profile_id=preferred_profile_id,
        )

        request = MuseGenerationRequest(
            scene_number=scene_number,
            clip_sequence_index=clip_sequence_index,
            locked_script_hash=locked_script_hash,
            prompt=prompt,
            prompt_version=prompt_version,
            reference_assets=reference_assets or [],
            profile_id=profile.profile_id,
            estimated_cost_usd=estimated_cost_usd,
            idempotency_key=idempotency_key,
        )

        # create_attempt() is where the in-flight/idempotency-key
        # guards actually live - deliberately not duplicated here.
        attempt = MuseGenerationLedgerService.create_attempt(job, request)

        reserved = False

        if self._budget_service is not None and estimated_cost_usd > 0:
            self._budget_service.reserve(profile.profile_id, estimated_cost_usd)
            reserved = True

        try:
            result = self._provider.submit(request, attempt)
        except Exception:
            if reserved:
                self._budget_service.release(  # type: ignore[union-attr]
                    profile.profile_id, estimated_cost_usd
                )
            raise

        MuseGenerationLedgerService.replace_attempt(job, result)

        return result

    def resume_after_auth(
        self,
        job: VideoJob,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """
        Resume one attempt stuck at AUTH_REQUIRED, once the operator
        has re-authenticated the account in the real Muse browser
        session - same reasoning as Google Flow's own resume_after_
        auth(): AUTH_REQUIRED is only ever set before the credit-
        sensitive SUBMITTING boundary, so replaying submit() on it
        cannot risk a duplicate paid generation.
        """

        if attempt.state != MuseGenerationState.AUTH_REQUIRED:
            raise ValueError(
                "resume_after_auth() only applies to an attempt at "
                f"AUTH_REQUIRED (this attempt is at {attempt.state.value})."
            )

        if not self._provider.check_profile_health(attempt.profile_id):
            raise RuntimeError(
                "This account still shows no sign of an authenticated "
                "session - log back into Muse (Meta Account) in the "
                "Muse browser profile, then retry."
            )

        result = self._provider.submit(attempt.request, attempt)
        MuseGenerationLedgerService.replace_attempt(job, result)

        return result

    def abandon_attempt(
        self,
        job: VideoJob,
        attempt: MuseGenerationAttempt,
        *,
        force: bool = False,
    ) -> MuseGenerationAttempt:
        """
        Mark a stuck, non-terminal attempt FAILED so a fresh Generate
        click can start a brand-new attempt for its scene - same
        credit-sensitive-state safety gate as Google Flow's own
        abandon_attempt().
        """

        if is_terminal_state(attempt.state):
            raise ValueError(
                "Only a non-terminal attempt can be abandoned (this "
                f"attempt is already at {attempt.state.value})."
            )

        reached_credit_sensitive_state = any(
            transition.state in _CREDIT_SENSITIVE_STATES
            for transition in attempt.state_history
        )

        if reached_credit_sensitive_state and not force:
            raise MuseAttemptCreditSensitiveError(attempt)

        result = attempt.with_transition(
            MuseGenerationState.FAILED,
            detail=(
                "Abandoned by operator: stuck at "
                f"{attempt.state.value} with no automated recovery path."
            ),
        )
        MuseGenerationLedgerService.replace_attempt(job, result)

        return result

    def observe_attempt(
        self,
        job: VideoJob,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """Observe one in-flight attempt and persist whatever changed."""

        result = self._provider.observe(attempt)
        MuseGenerationLedgerService.replace_attempt(job, result)

        return result

    def download_attempt(
        self,
        job: VideoJob,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """Download one completed attempt's result and persist it."""

        result = self._provider.download(attempt)
        MuseGenerationLedgerService.replace_attempt(job, result)

        return result

    def validate_downloaded_attempt(
        self,
        job: VideoJob,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """
        Technical validation and checksum for a downloaded generation -
        REUSE, not a new implementation, same as Google Flow's own
        validate_downloaded_attempt().
        """

        if attempt.downloaded_file is None:
            raise ValueError("Cannot validate an attempt with no downloaded_file set.")

        technical_validation = self._technical_validation_service.validate(
            Path(attempt.downloaded_file)
        )
        checksum = self._provenance_service.compute_checksum(attempt.downloaded_file)

        annotated = attempt.model_copy(
            update={
                "technical_validation": technical_validation,
                "checksum": checksum,
                # Set once, from the first (untrimmed) download - a re-validation
                # after a local trim must not overwrite it.
                "source_checksum": attempt.source_checksum or checksum,
            }
        )

        if not technical_validation.is_valid:
            qc_result = MuseQCResult(
                outcome=MuseQCOutcome.INVALID,
                findings=list(technical_validation.issues),
            )
            annotated = annotated.model_copy(
                update={
                    "qc_result": qc_result,
                    "failure": MuseFailure(
                        code=MuseFailureCode.DOWNLOAD_FAILED,
                        message=(
                            "Downloaded media failed technical validation: "
                            + "; ".join(technical_validation.issues)
                        ),
                        occurred_after_possible_credit_exposure=True,
                    ),
                }
            )
            annotated = annotated.with_transition(
                MuseGenerationState.QC_FAILED,
                detail="Technical validation failed - never reaches READY.",
            )

        MuseGenerationLedgerService.replace_attempt(job, annotated)

        return annotated

    @staticmethod
    def _in_flight_counts_by_profile(job: VideoJob) -> dict[str, int]:
        """
        In-flight counts derived from this one job's own ledger - same
        disclosed cross-job scoping limit as Google Flow's own
        equivalent.
        """

        counts: dict[str, int] = {}

        for attempt in job.muse_generation_attempts:
            if is_terminal_state(attempt.state):
                continue

            counts[attempt.profile_id] = counts.get(attempt.profile_id, 0) + 1

        return counts
