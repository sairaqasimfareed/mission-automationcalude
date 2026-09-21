from __future__ import annotations

from src.services.llm.llm_service import LLMServiceResult
from src.services.narration_condensation_service import (
    NarrationCondensationService,
)
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


class _StubLLMService:
    def __init__(self, *, content: str | None, success: bool = True) -> None:
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


_ORIGINAL = (
    "The real problem wasn't smart birds. It was poor coordination "
    "between farmers and soldiers, and birds outside range."
)


def test_condense_returns_the_provider_rewrite() -> None:
    llm_service = _StubLLMService(content="The real issue was poor coordination.")

    service = NarrationCondensationService(llm_service=llm_service)

    condensed = service.condense(
        narration_text=_ORIGINAL,
        available_seconds=3.0,
    )

    assert condensed == "The real issue was poor coordination."


def test_condense_prompt_states_a_word_budget_and_preserves_information() -> None:
    llm_service = _StubLLMService(content="Condensed.")

    service = NarrationCondensationService(llm_service=llm_service)

    service.condense(narration_text=_ORIGINAL, available_seconds=3.0)

    assert llm_service.last_request is not None

    # ~2.3 words/sec * 0.9 safety margin * 3.0s ≈ 6 words.
    assert "6 words" in llm_service.last_request.prompt
    assert "do not drop" in llm_service.last_request.system_prompt.lower()
    assert "never invent new information" in (
        llm_service.last_request.system_prompt.lower()
    )


def test_condense_returns_none_on_provider_failure() -> None:
    llm_service = _StubLLMService(content=None, success=False)

    service = NarrationCondensationService(llm_service=llm_service)

    condensed = service.condense(narration_text=_ORIGINAL, available_seconds=3.0)

    assert condensed is None


def test_condense_returns_none_for_empty_response() -> None:
    llm_service = _StubLLMService(content="   ")

    service = NarrationCondensationService(llm_service=llm_service)

    condensed = service.condense(narration_text=_ORIGINAL, available_seconds=3.0)

    assert condensed is None


def test_condense_returns_none_for_empty_narration() -> None:
    llm_service = _StubLLMService(content="Should not be called")

    service = NarrationCondensationService(llm_service=llm_service)

    condensed = service.condense(narration_text="   ", available_seconds=3.0)

    assert condensed is None


def test_condense_returns_none_for_non_positive_duration() -> None:
    llm_service = _StubLLMService(content="Should not be called")

    service = NarrationCondensationService(llm_service=llm_service)

    condensed = service.condense(narration_text=_ORIGINAL, available_seconds=0.0)

    assert condensed is None
