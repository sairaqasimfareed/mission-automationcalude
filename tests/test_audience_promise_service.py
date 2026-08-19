from __future__ import annotations

import pytest

from src.models.audience_promise import PromiseStrength
from src.services.audience_promise_service import AudiencePromiseService
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()
_EDITORIAL_PROFILE = EditorialProfileCompositionService().compose(
    genre=_GENRE_REGISTRY.get("genre.mystery")
)


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success
        self.last_request: LLMRequest | None = None

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        self.last_request = request

        status = (
            LLMCallStatus.SUCCESS if self._success else LLMCallStatus.PROVIDER_ERROR
        )

        result = LLMCallResult(
            status=status,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=self._content if self._success else None,
            error_message=None if self._success else "Provider unavailable.",
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="openai-main" if self._success else None,
            all_providers_failed=not self._success,
        )


_STRONG_PROMISE = (
    "INTENDED_EMOTION: Dread\n"
    "CENTRAL_CURIOSITY: Why did the crew vanish?\n"
    "PRIMARY_QUESTION: What really happened aboard the ship?\n"
    "VIEWER_BENEFIT: A satisfying, verified explanation.\n"
    "EXPECTED_PAYOFF: The disputed final theory, weighed against evidence.\n"
    "PROMISE_STRENGTH: strong\n"
    "WEAKNESS_REASONS: none"
)

_DEFAULT_KWARGS = dict(
    topic="The Mary Celeste",
    target_audience="Mystery enthusiasts",
    platform="youtube",
    editorial_profile=_EDITORIAL_PROFILE,
    target_duration_seconds=180,
)


def test_determine_parses_a_strong_promise() -> None:
    stub = _StubLLMService(content=_STRONG_PROMISE)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    promise = service.determine(**_DEFAULT_KWARGS)

    assert promise.promise_strength == PromiseStrength.STRONG
    assert promise.is_weak is False
    assert promise.weakness_reasons == []
    assert promise.central_curiosity == "Why did the crew vanish?"
    assert promise.confidence_score == 0.9


def test_determine_parses_a_weak_promise_with_reasons() -> None:
    content = (
        "INTENDED_EMOTION: Mild interest\n"
        "CENTRAL_CURIOSITY: What happened next?\n"
        "PRIMARY_QUESTION: How did it end?\n"
        "VIEWER_BENEFIT: General information.\n"
        "EXPECTED_PAYOFF: A summary.\n"
        "PROMISE_STRENGTH: weak\n"
        "WEAKNESS_REASONS: generic framing, no real unanswered question, "
        "widely covered topic"
    )

    stub = _StubLLMService(content=content)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    promise = service.determine(**_DEFAULT_KWARGS)

    assert promise.promise_strength == PromiseStrength.WEAK
    assert promise.is_weak is True
    assert len(promise.weakness_reasons) == 3
    assert "generic framing" in promise.weakness_reasons
    assert promise.confidence_score == 0.25


def test_determine_includes_context_in_prompt() -> None:
    stub = _StubLLMService(content=_STRONG_PROMISE)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    service.determine(**_DEFAULT_KWARGS)

    assert stub.last_request is not None
    assert "The Mary Celeste" in stub.last_request.prompt
    assert "genre.mystery" in stub.last_request.prompt
    assert "180 seconds" in stub.last_request.prompt
    assert _EDITORIAL_PROFILE.script.tone.value in stub.last_request.prompt
    assert (
        _EDITORIAL_PROFILE.content_intelligence.cta_policy.value
        in stub.last_request.prompt
    )


def test_determine_prompt_differs_by_genre_tone() -> None:
    horror_profile = EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.horror")
    )
    documentary_profile = EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.documentary")
    )

    horror_stub = _StubLLMService(content=_STRONG_PROMISE)
    documentary_stub = _StubLLMService(content=_STRONG_PROMISE)

    horror_service = AudiencePromiseService(llm_service=horror_stub)  # type: ignore[arg-type]
    documentary_service = AudiencePromiseService(llm_service=documentary_stub)  # type: ignore[arg-type]

    kwargs = dict(_DEFAULT_KWARGS)
    del kwargs["editorial_profile"]

    horror_service.determine(editorial_profile=horror_profile, **kwargs)
    documentary_service.determine(editorial_profile=documentary_profile, **kwargs)

    assert horror_stub.last_request is not None
    assert documentary_stub.last_request is not None
    assert horror_stub.last_request.prompt != documentary_stub.last_request.prompt
    assert horror_profile.script.tone.value in horror_stub.last_request.prompt
    assert documentary_profile.script.tone.value in documentary_stub.last_request.prompt


def test_determine_raises_on_missing_required_field() -> None:
    content = (
        "INTENDED_EMOTION: Dread\n"
        "CENTRAL_CURIOSITY: Why did the crew vanish?\n"
        "PROMISE_STRENGTH: strong"
    )

    stub = _StubLLMService(content=content)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="missing required fields"):
        service.determine(**_DEFAULT_KWARGS)


def test_determine_raises_on_unrecognized_strength() -> None:
    content = _STRONG_PROMISE.replace(
        "PROMISE_STRENGTH: strong", "PROMISE_STRENGTH: extremely strong"
    )

    stub = _StubLLMService(content=content)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="unrecognized PROMISE_STRENGTH"):
        service.determine(**_DEFAULT_KWARGS)


def test_determine_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Audience promise generation failed"):
        service.determine(**_DEFAULT_KWARGS)


def test_determine_raises_on_empty_content() -> None:
    stub = _StubLLMService(content="   ")

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="empty content"):
        service.determine(**_DEFAULT_KWARGS)


def test_determine_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_STRONG_PROMISE)

    service = AudiencePromiseService(llm_service=stub)  # type: ignore[arg-type]

    kwargs = dict(_DEFAULT_KWARGS)
    kwargs["topic"] = "   "

    with pytest.raises(ValueError, match="cannot be empty"):
        service.determine(**kwargs)


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_STRONG_PROMISE)

    with pytest.raises(ValueError, match="cannot be negative"):
        AudiencePromiseService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    """
    Regression test, mirroring ThumbnailConceptGenerationService's
    equivalent: DryRunProviderAdapter returns LLMRequest's
    dry_run_response verbatim when set, so this proves that response
    round-trips through _parse() successfully under
    MISSION_AUTOMATION_DRY_RUN.
    """

    probe = _StubLLMService(content=_STRONG_PROMISE)

    service = AudiencePromiseService(llm_service=probe)  # type: ignore[arg-type]

    service.determine(**_DEFAULT_KWARGS)

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = AudiencePromiseService(llm_service=replay)  # type: ignore[arg-type]

    promise = replay_service.determine(**_DEFAULT_KWARGS)

    assert promise.promise_strength == PromiseStrength.MODERATE
