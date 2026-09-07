from __future__ import annotations

from pathlib import Path

from src.models.approval import ApprovalDecision, ApprovalState
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
    is_terminal_state,
)
from src.models.video_job import VideoJob
from src.providers.external_ui_generation_provider import ExternalUIGenerationProvider
from src.services.approval_service import ApprovalService
from src.services.asset_provenance_service import AssetProvenanceService
from src.services.budget.provider_budget_service import ProviderBudgetService
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
)
from src.services.google_flow_generation_ledger_service import (
    GoogleFlowGenerationLedgerService,
)
from src.services.media_technical_validation_service import (
    MediaTechnicalValidationService,
)

_AGENT_CONFIRMATION_DECISION_POINT = "external_ui_generation"


class GoogleFlowAgentConfirmationRequiredError(RuntimeError):
    """
    Raised before anything credit-sensitive happens when a request
    asks for Agent mode (GoogleFlowExecutionSettings.agent_mode=True)
    and the job's own approval policy has not auto-approved it.

    This app never flips Google Flow's own "Confirm before generating"
    account setting (a deliberate design choice - see
    docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4a and
    PROJECT_PROGRESS.md); this is the independent, provider-agnostic
    gate this codebase already has for exactly this kind of decision
    (ApprovalPolicyConfig/ApprovalService), applied here for the first
    time to a real, metered spend risk. Carries the resolved
    ApprovalDecision so a caller (a future GUI) can show the operator
    what needs their attention and why, matching the existing pattern
    for other approval-gated decision points.
    """

    def __init__(self, decision: ApprovalDecision) -> None:
        self.decision = decision

        super().__init__(
            "Agent-mode Google Flow generation requires human confirmation "
            f"first (policy: {decision.policy.value}, state: "
            f"{decision.state.value}) - see .decision for details."
        )


class GoogleFlowGenerationOrchestratorService:
    """
    Google Flow External UI Automation, GF-11/GF-12: the one real
    caller that ties routing (GF-3), the durable ledger (GF-1), budget
    protection (GF-11), and the provider adapter (GF-4) together.

    This is the "canonical generation orchestrator" the central design
    rule names: "Neither Google Flow nor the REST gateway may become a
    second creative, routing, budget, QC or production authority." All
    of those decisions are made here, once - the adapter it calls only
    ever executes an already-fully-resolved request.

    GF-12's own bulk-resume vocabulary (READY -> skip, SUBMITTED/
    GENERATING -> observe, SUBMISSION_UNCERTAIN -> reconcile, PLANNED
    -> evaluate gates and submit, QC_FAILED -> deliberate recovery)
    applies at the call-site level: a caller iterating many scenes
    uses GoogleFlowGenerationLedgerService's own query helpers to
    decide which action applies to each one *before* ever calling
    submit_new_attempt() here - this method IS the "evaluate gates and
    submit" branch of that vocabulary, and observe_attempt()/
    download_attempt() are the "observe"/"download" branches. A full
    queue/worker loop driving that decision automatically over many
    scenes is not built here - this class provides the three
    operations such a loop would call, not the loop itself.
    """

    def __init__(
        self,
        *,
        provider: ExternalUIGenerationProvider,
        account_router: GoogleFlowAccountRouterService,
        budget_service: ProviderBudgetService | None = None,
        max_in_flight_per_account: int = 1,
        technical_validation_service: MediaTechnicalValidationService | None = None,
        provenance_service: AssetProvenanceService | None = None,
    ) -> None:
        self._provider = provider
        self._account_router = account_router
        self._budget_service = budget_service
        self._max_in_flight_per_account = max_in_flight_per_account
        # GF-9: REUSE, not duplicated - the same technical-validation
        # and checksum services already used for manual-upload/stock
        # clips (Post-Script-Approval Production Plan Phases 6/8).
        # Default to real instances rather than None, matching this
        # codebase's own "no existing behavior for a default-off
        # posture to protect" reasoning (AudioCuePolicyService,
        # FlowBrowserWorker's own defaults) - a downloaded generation
        # has no prior "unvalidated" behavior worth preserving.
        self._technical_validation_service = (
            technical_validation_service or MediaTechnicalValidationService()
        )
        self._provenance_service = provenance_service or AssetProvenanceService()

    def submit_new_attempt(
        self,
        job: VideoJob,
        *,
        scene_number: int,
        prompt: str,
        prompt_version: str,
        idempotency_key: str,
        execution_settings: GoogleFlowExecutionSettings | None = None,
        reference_assets: list[GoogleFlowReferenceAsset] | None = None,
        negative_constraints: list[str] | None = None,
        locked_script_hash: str | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> GoogleFlowGenerationAttempt:
        """
        Route to an eligible account, gate on budget, create the
        ledger attempt, and drive it through the adapter's submit().

        Raises before anything credit-sensitive happens if: no
        eligible account exists (NoEligibleGoogleFlowAccountError),
        this scene already has a non-terminal attempt (ValueError,
        from create_attempt's own in-flight guard), the budget gate
        rejects the estimated cost (ValueError, from
        ProviderBudgetService.reserve()), or the request asks for
        Agent mode and the job's own approval policy has not
        auto-approved it (GoogleFlowAgentConfirmationRequiredError) -
        this app's own independent confirmation gate, never Flow's own
        account setting (see that error's own docstring). A
        reservation already made is released if the adapter's own
        submit() call raises an exception this orchestrator did not
        expect - never left stranded reserved-but-unspent.
        """

        if execution_settings is not None and execution_settings.agent_mode:
            decision = ApprovalService().open_decision(
                decision_point=_AGENT_CONFIRMATION_DECISION_POINT,
                policy=job.approval_policy.policy_for(
                    _AGENT_CONFIRMATION_DECISION_POINT
                ),
            )

            if decision.state != ApprovalState.APPROVED:
                raise GoogleFlowAgentConfirmationRequiredError(decision)

        in_flight_counts = self._in_flight_counts_by_profile(job)

        profile = self._account_router.select_account(
            in_flight_counts=in_flight_counts,
            max_in_flight_per_account=self._max_in_flight_per_account,
        )

        request = GoogleFlowGenerationRequest(
            scene_number=scene_number,
            locked_script_hash=locked_script_hash,
            prompt=prompt,
            prompt_version=prompt_version,
            negative_constraints=negative_constraints or [],
            reference_assets=reference_assets or [],
            execution_settings=execution_settings or GoogleFlowExecutionSettings(),
            profile_id=profile.profile_id,
            estimated_cost_usd=estimated_cost_usd,
            idempotency_key=idempotency_key,
        )

        # create_attempt() is where GF-1's own in-flight/idempotency-
        # key guards actually live - deliberately not duplicated here.
        attempt = GoogleFlowGenerationLedgerService.create_attempt(job, request)

        reserved = False

        if self._budget_service is not None and estimated_cost_usd > 0:
            # reserve() itself performs the check; it raises ValueError
            # with a clear reason when the estimated cost is blocked -
            # no separate check-then-reserve race to get wrong.
            self._budget_service.reserve(profile.profile_id, estimated_cost_usd)
            reserved = True

        try:
            result = self._provider.submit(request, attempt)
        except Exception:
            if reserved:
                # No positive evidence this ever reached a credit-
                # sensitive boundary inside the adapter (an exception
                # escaping submit() means it never returned a
                # SUBMISSION_UNCERTAIN/SUBMITTED attempt at all) - safe
                # to release rather than leave stranded.
                self._budget_service.release(  # type: ignore[union-attr]
                    profile.profile_id, estimated_cost_usd
                )
            raise

        GoogleFlowGenerationLedgerService.replace_attempt(job, result)

        return result

    def observe_attempt(
        self,
        job: VideoJob,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """Observe one in-flight attempt and persist whatever changed."""

        result = self._provider.observe(attempt)
        GoogleFlowGenerationLedgerService.replace_attempt(job, result)

        return result

    def download_attempt(
        self,
        job: VideoJob,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """Download one completed attempt's result and persist it."""

        result = self._provider.download(attempt)
        GoogleFlowGenerationLedgerService.replace_attempt(job, result)

        return result

    def validate_downloaded_attempt(
        self,
        job: VideoJob,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """
        GF-9: technical validation and checksum for a downloaded
        generation - REUSE, not a new implementation.
        MediaTechnicalValidationService/AssetProvenanceService already
        exist, already tested, and already do exactly this for every
        other acquisition path (manual upload, stock footage); Google
        Flow's download gets no separate, competing implementation.

        "Downloaded does NOT mean READY" (GF-9's own words): a failing
        technical validation transitions the attempt to QC_FAILED with
        an INVALID GoogleFlowQCResult carrying ffprobe's own findings -
        never silently accepted. A passing technical validation leaves
        the attempt at DOWNLOADED with technical_validation/checksum
        now populated, ready for a genuine semantic/multimodal QC pass
        (GF-10) to actually accept it into READY - that pass is a
        real, disclosed gap, not built here, since this codebase has
        no existing vision-capable QC integration to reuse and
        fabricating one would mean inventing an unverified capability
        rather than honestly deferring it.
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
            }
        )

        if not technical_validation.is_valid:
            qc_result = GoogleFlowQCResult(
                outcome=GoogleFlowQCOutcome.INVALID,
                findings=list(technical_validation.issues),
            )
            annotated = annotated.model_copy(
                update={
                    "qc_result": qc_result,
                    "failure": GoogleFlowFailure(
                        code=GoogleFlowFailureCode.DOWNLOAD_FAILED,
                        message=(
                            "Downloaded media failed technical validation: "
                            + "; ".join(technical_validation.issues)
                        ),
                        occurred_after_possible_credit_exposure=True,
                    ),
                }
            )
            annotated = annotated.with_transition(
                GoogleFlowGenerationState.QC_FAILED,
                detail="Technical validation failed - never reaches READY.",
            )

        GoogleFlowGenerationLedgerService.replace_attempt(job, annotated)

        return annotated

    @staticmethod
    def _in_flight_counts_by_profile(job: VideoJob) -> dict[str, int]:
        """
        In-flight counts derived from this one job's own ledger.

        A real, disclosed scoping limit (named in GF-3's own docs):
        this only sees attempts on the job it was given, not every
        job in the application - a Flow account shared across
        multiple projects' jobs needs a cross-job aggregation this
        orchestrator does not attempt, since it has no access to a
        job store here and has no business assuming one exists.
        """

        counts: dict[str, int] = {}

        for attempt in job.flow_generation_attempts:
            if is_terminal_state(attempt.state):
                continue

            counts[attempt.profile_id] = counts.get(attempt.profile_id, 0) + 1

        return counts
