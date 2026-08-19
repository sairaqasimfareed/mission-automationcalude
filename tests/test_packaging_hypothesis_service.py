from __future__ import annotations

import pytest

from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.hook import HookEvaluation
from src.models.story_blueprint import StoryBeatType
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.llm.llm_service import LLMServiceResult
from src.services.packaging_hypothesis_service import PackagingHypothesisService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _editorial_profile() -> EditorialProfile:
    return EditorialProfileCompositionService().compose(
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


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=30,
                narrative_function=StoryBeatType.HOOK,
                narration="The crew vanished without a trace.",
                tension_level=60,
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _hook_evaluation() -> HookEvaluation:
    return HookEvaluation(
        hook_text="The crew vanished without a trace.",
        immediate_curiosity=85,
        specificity=80,
        stakes=75,
        clarity=80,
        emotional_impact=70,
        novelty=75,
        relevance=85,
        audience_fit=80,
        factual_support=90,
        spoiler_risk=10,
        rejected=False,
        reasoning="Strong, specific hook grounded in verified facts.",
    )


_VALID_RESPONSE = (
    "VIEWER_PROMISE: You'll learn the leading theory for the crew's fate.\n"
    "TITLE_TERRITORIES: The disappearance framing | The evidence framing\n"
    "THUMBNAIL_CONCEPTS: Empty deck, fog | Captain's logbook close-up\n"
    "CURIOSITY_MECHANISM: An unresolved question the title poses directly.\n"
    "EXPECTED_EMOTION: Intrigue\n"
    "DIFFERENTIATION_ANGLE: Focuses on the physical evidence, not folklore."
)


def test_generate_parses_all_fields() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)

    service = PackagingHypothesisService(llm_service=stub)  # type: ignore[arg-type]

    hypothesis = service.generate(
        topic="The Mary Celeste",
        script=_script(),
        selected_hook=_hook_evaluation(),
        editorial_profile=_editorial_profile(),
    )

    assert hypothesis.viewer_promise.startswith("You'll learn")
    assert hypothesis.title_territories == [
        "The disappearance framing",
        "The evidence framing",
    ]
    assert hypothesis.thumbnail_concepts == [
        "Empty deck, fog",
        "Captain's logbook close-up",
    ]
    assert hypothesis.expected_emotion == "Intrigue"


def test_generate_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)

    service = PackagingHypothesisService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.generate(
            topic="   ",
            script=_script(),
            selected_hook=_hook_evaluation(),
            editorial_profile=_editorial_profile(),
        )


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = PackagingHypothesisService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Packaging hypothesis generation failed"):
        service.generate(
            topic="The Mary Celeste",
            script=_script(),
            selected_hook=_hook_evaluation(),
            editorial_profile=_editorial_profile(),
        )


def test_generate_raises_when_a_required_field_is_missing() -> None:
    content = "VIEWER_PROMISE: A promise.\nTITLE_TERRITORIES: One territory"

    stub = _StubLLMService(content=content)

    service = PackagingHypothesisService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="missing required fields"):
        service.generate(
            topic="The Mary Celeste",
            script=_script(),
            selected_hook=_hook_evaluation(),
            editorial_profile=_editorial_profile(),
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        PackagingHypothesisService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_VALID_RESPONSE)

    service = PackagingHypothesisService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        script=_script(),
        selected_hook=_hook_evaluation(),
        editorial_profile=_editorial_profile(),
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = PackagingHypothesisService(llm_service=replay)  # type: ignore[arg-type]

    hypothesis = replay_service.generate(
        topic="The Mary Celeste",
        script=_script(),
        selected_hook=_hook_evaluation(),
        editorial_profile=_editorial_profile(),
    )

    assert len(hypothesis.title_territories) > 0
