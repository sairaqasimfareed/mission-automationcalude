from __future__ import annotations

from abc import abstractmethod
from enum import Enum

from src.models.muse_generation import MuseGenerationAttempt, MuseGenerationRequest
from src.providers.base_provider import BaseProvider


class MuseUIOperation(str, Enum):
    """
    One provider-neutral operation a Muse UI provider may support -
    same "not every provider must support every operation, unsupported
    operations must be explicit" contract as ExternalUIOperation
    (external_ui_generation_provider.py).
    """

    SUBMIT = "submit"
    OBSERVE = "observe"
    DOWNLOAD = "download"
    CANCEL_OR_ABANDON = "cancel_or_abandon"


class MuseUIOperationNotSupportedError(NotImplementedError):
    """
    Raised when the orchestrator asks a provider for an operation it
    has explicitly declared it does not support.
    """

    def __init__(self, *, provider_name: str, operation: MuseUIOperation) -> None:
        self.provider_name = provider_name
        self.operation = operation

        super().__init__(
            f"{provider_name} does not support the '{operation.value}' operation."
        )


class MuseUIProvider(BaseProvider):
    """
    Provider-neutral generation contract for Muse (muse.ai) - same
    method SHAPE as ExternalUIGenerationProvider (health/submit/
    observe/download/cancel_or_abandon), typed to Muse's own concrete
    request/attempt models rather than Google Flow's.

    Deliberately a sibling interface, not a subclass or generic
    specialization of ExternalUIGenerationProvider - see this
    codebase's own 2026-09-29 architecture investigation:
    ExternalUIGenerationProvider's method signatures are concretely
    typed to GoogleFlowGenerationRequest/Attempt, not a shared generic
    base, and generalizing it would mean refactoring an already-stable,
    just-fixed, live-tested subsystem for no functional gain right now.
    A second concrete class with the same shape achieves the same
    "one pattern per media type" intent without that risk - exactly
    how adapter.py and real_adapter.py already coexist as two concrete
    GoogleFlow implementations with no shared generic base beyond
    the abstract interface itself.
    """

    @property
    @abstractmethod
    def supported_operations(self) -> frozenset[MuseUIOperation]:
        """Which operations this provider actually implements."""

    def ensure_supported(self, operation: MuseUIOperation) -> None:
        if operation not in self.supported_operations:
            raise MuseUIOperationNotSupportedError(
                provider_name=self.provider_name,
                operation=operation,
            )

    @abstractmethod
    def check_profile_health(self, profile_id: str) -> bool:
        """
        Whether the given account profile is currently authenticated
        and usable.
        """

    @abstractmethod
    def submit(
        self,
        request: MuseGenerationRequest,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """
        Drive one attempt forward through prompt/reference preparation
        and the actual credit-sensitive submission - returning a new
        attempt reflecting exactly how far it genuinely got, per
        MuseGenerationAttempt.with_transition.

        Must call self.ensure_supported(MuseUIOperation.SUBMIT) first.
        """

    @abstractmethod
    def observe(
        self,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """
        Read-only, repeatable, restart-safe observation of an
        in-flight attempt's Muse-side state. Must never mutate
        provider-side state - only ever reads and reports.

        Must call self.ensure_supported(MuseUIOperation.OBSERVE) first.
        """

    @abstractmethod
    def download(
        self,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """
        Download a completed generation's result. Idempotent:
        downloading an already-downloaded, still-completed attempt
        must be safe to call again.

        Must call self.ensure_supported(MuseUIOperation.DOWNLOAD)
        first.
        """

    @abstractmethod
    def cancel_or_abandon(
        self,
        attempt: MuseGenerationAttempt,
    ) -> MuseGenerationAttempt:
        """
        Best-effort cancellation/abandonment of an in-flight attempt.
        A provider that cannot truly cancel a paid generation already
        in flight must still implement this honestly (e.g. marking the
        attempt FAILED locally without claiming the remote generation
        was stopped), or omit CANCEL_OR_ABANDON from
        supported_operations entirely.

        Must call self.ensure_supported(MuseUIOperation.CANCEL_OR_ABANDON)
        first.
        """
