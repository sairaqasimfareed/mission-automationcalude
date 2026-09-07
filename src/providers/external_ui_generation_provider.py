from __future__ import annotations

from abc import abstractmethod
from enum import Enum

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
)
from src.providers.base_provider import BaseProvider


class ExternalUIOperation(str, Enum):
    """
    One provider-neutral operation an EXTERNAL_UI generation provider
    may support - GF-0's own contract: "Not every provider must
    support every operation. Unsupported operations must be
    explicit."
    """

    SUBMIT = "submit"
    OBSERVE = "observe"
    DOWNLOAD = "download"
    CANCEL_OR_ABANDON = "cancel_or_abandon"


class ExternalUIOperationNotSupportedError(NotImplementedError):
    """
    Raised when the orchestrator asks a provider for an operation it
    has explicitly declared it does not support, rather than that
    provider silently no-op'ing or raising a bare NotImplementedError
    with no further context.
    """

    def __init__(self, *, provider_name: str, operation: ExternalUIOperation) -> None:
        self.provider_name = provider_name
        self.operation = operation

        super().__init__(
            f"{provider_name} does not support the " f"'{operation.value}' operation."
        )


class ExternalUIGenerationProvider(BaseProvider):
    """
    Provider-neutral generation contract for any EXTERNAL_UI video
    provider (Google Flow today; any future browser-driven provider
    tomorrow), conceptually equivalent to GF-0/section 5's
    health/submit/observe/download/cancel_or_abandon shape.

    The application orchestrator (GF-1's persistent attempt ledger and
    the GenerationOrchestratorService that owns it) decides *when* to
    call each of these and what to do with the result. This class
    only defines what one provider execution step looks like -
    exactly the "browser selectors must never become the application's
    business logic" boundary GF-48 names, extended to any concrete
    subclass, not only the eventual Google Flow adapter.
    """

    @property
    @abstractmethod
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        """Which operations this provider actually implements."""

    def ensure_supported(self, operation: ExternalUIOperation) -> None:
        if operation not in self.supported_operations:
            raise ExternalUIOperationNotSupportedError(
                provider_name=self.provider_name,
                operation=operation,
            )

    @abstractmethod
    def check_profile_health(self, profile_id: str) -> bool:
        """
        Whether the given account profile is currently authenticated
        and usable - the per-account counterpart to the inherited
        health_check(), since one EXTERNAL_UI provider class may back
        several independent, separately authenticated accounts
        (GF-3's multi-account registry).
        """

    @abstractmethod
    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """
        Drive one attempt forward through settings verification,
        prompt/reference preparation, analysis, confirmation (when
        present), and the actual credit-sensitive submission -
        returning a new attempt reflecting exactly how far it
        genuinely got, per GoogleFlowGenerationAttempt.with_transition.

        Must call self.ensure_supported(ExternalUIOperation.SUBMIT)
        first.
        """

    @abstractmethod
    def observe(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """
        Read-only, repeatable, restart-safe observation of an
        in-flight attempt's Flow-side state (GF-8). Must never mutate
        provider-side state - only ever reads and reports.

        Must call self.ensure_supported(ExternalUIOperation.OBSERVE)
        first.
        """

    @abstractmethod
    def download(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """
        Download a completed generation's result (GF-9). Idempotent:
        downloading an already-downloaded, still-completed attempt
        must be safe to call again.

        Must call self.ensure_supported(ExternalUIOperation.DOWNLOAD)
        first.
        """

    @abstractmethod
    def cancel_or_abandon(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        """
        Best-effort cancellation/abandonment of an in-flight attempt.
        Not every provider can truly cancel a paid generation already
        in flight - a provider that cannot must still implement this
        method honestly (e.g. marking the attempt FAILED locally
        without claiming the remote generation was stopped), or omit
        CANCEL_OR_ABANDON from supported_operations entirely.

        Must call
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)
        first.
        """
