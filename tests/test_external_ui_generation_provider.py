from __future__ import annotations

import pytest

from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
    ExternalUIOperationNotSupportedError,
)


def _request() -> GoogleFlowGenerationRequest:
    return GoogleFlowGenerationRequest(
        scene_number=1,
        prompt="A quiet harbor at sunrise.",
        prompt_version="v1",
        profile_id="fake.primary",
        idempotency_key="req-1",
    )


def _attempt() -> GoogleFlowGenerationAttempt:
    return GoogleFlowGenerationAttempt(request=_request(), profile_id="fake.primary")


class FullySupportedFakeProvider(ExternalUIGenerationProvider):
    """A fake provider that declares and implements every operation."""

    @property
    def provider_name(self) -> str:
        return "Fake External UI Provider"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        return frozenset(
            {
                ExternalUIOperation.SUBMIT,
                ExternalUIOperation.OBSERVE,
                ExternalUIOperation.DOWNLOAD,
                ExternalUIOperation.CANCEL_OR_ABANDON,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        return profile_id == "fake.primary"

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.SUBMIT)

        return attempt.with_transition(GoogleFlowGenerationState.SETTINGS_VERIFIED)

    def observe(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.OBSERVE)

        return attempt

    def download(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.DOWNLOAD)

        return attempt

    def cancel_or_abandon(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)

        return attempt.with_transition(GoogleFlowGenerationState.FAILED)


class DownloadOnlyFakeProvider(ExternalUIGenerationProvider):
    """A fake provider that only supports downloading a known result."""

    @property
    def provider_name(self) -> str:
        return "Download-Only Fake Provider"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        return frozenset({ExternalUIOperation.DOWNLOAD})

    def check_profile_health(self, profile_id: str) -> bool:
        return True

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.SUBMIT)

        return attempt

    def observe(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.OBSERVE)

        return attempt

    def download(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.DOWNLOAD)

        return attempt

    def cancel_or_abandon(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)

        return attempt


def test_fully_supported_provider_executes_every_operation() -> None:
    provider = FullySupportedFakeProvider()
    attempt = _attempt()

    submitted = provider.submit(_request(), attempt)
    assert submitted.state == GoogleFlowGenerationState.SETTINGS_VERIFIED

    observed = provider.observe(submitted)
    assert observed.state == GoogleFlowGenerationState.SETTINGS_VERIFIED

    downloaded = provider.download(observed)
    assert downloaded is observed

    cancelled = provider.cancel_or_abandon(downloaded)
    assert cancelled.state == GoogleFlowGenerationState.FAILED


def test_check_profile_health_distinguishes_profiles() -> None:
    provider = FullySupportedFakeProvider()

    assert provider.check_profile_health("fake.primary") is True
    assert provider.check_profile_health("fake.unknown") is False


def test_unsupported_operation_raises_explicitly() -> None:
    provider = DownloadOnlyFakeProvider()
    attempt = _attempt()

    with pytest.raises(ExternalUIOperationNotSupportedError) as excinfo:
        provider.submit(_request(), attempt)

    assert excinfo.value.operation == ExternalUIOperation.SUBMIT
    assert "does not support" in str(excinfo.value)


def test_supported_operation_does_not_raise() -> None:
    provider = DownloadOnlyFakeProvider()
    attempt = _attempt()

    # Should not raise.
    provider.download(attempt)


def test_ensure_supported_error_names_the_provider() -> None:
    provider = DownloadOnlyFakeProvider()

    with pytest.raises(ExternalUIOperationNotSupportedError, match="Download-Only"):
        provider.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)
