from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.editorial_profile import EditorialProfile
from src.models.research import ResearchResult, ResearchSource, ResearchStatus
from src.models.research_evidence import ResearchFact
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.hook_generation_service import HookGenerationService
from src.services.llm.llm_service import LLMServiceResult
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


def _angle() -> StoryAngle:
    return StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the ship's missing final log entry.",
    )


def _promise() -> AudiencePromise:
    return AudiencePromise(
        topic="The Mary Celeste",
        target_audience="Mystery enthusiasts",
        platform="youtube",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        intended_emotion="Dread",
        central_curiosity="Why did the crew vanish?",
        primary_question="What really happened aboard the ship?",
        viewer_benefit="A satisfying, verified explanation.",
        expected_payoff="The disputed final theory.",
        promise_strength=PromiseStrength.STRONG,
        prompt_version="audience_promise_prompt_v1.0.0",
    )


def _research() -> ResearchResult:
    return ResearchResult(
        topic="The Mary Celeste",
        research_summary="An overview of the ship's disappearance.",
        key_facts=["The crew was never found."],
        interesting_angles=["The missing logbook."],
        potential_hooks=["What happened to the crew?"],
        risk_notes=["Claims should be verified."],
        sources=[ResearchSource(title="Test source", confidence_score=70)],
        fact_confidence_score=70,
        prompt_version="research_prompt_v2.0.0",
        status=ResearchStatus.APPROVED,
    )


_THREE_HOOK_BLOCK = "\n---\n".join(
    [
        "TEXT: The crew vanished without a trace.",
        "TEXT: One logbook entry explains everything - and nothing.",
        "TEXT: What the investigators found made no sense.",
    ]
)


def test_generate_parses_multiple_hook_blocks() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    hooks = service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        hook_count=3,
    )

    assert len(hooks) == 3
    assert hooks[0].text == "The crew vanished without a trace."


def test_generate_truncates_to_hook_count() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    hooks = service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        hook_count=1,
    )

    assert len(hooks) == 1


def test_generate_includes_context_in_prompt() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert stub.last_request is not None
    assert "Why did the crew vanish?" in stub.last_request.prompt
    assert "The Missing Logbook" in stub.last_request.prompt


def test_generate_prompt_includes_genre_hook_archetypes() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    profile = _editorial_profile()

    service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=profile,
    )

    assert stub.last_request is not None
    for archetype in profile.content_intelligence.preferred_hook_archetypes:
        assert archetype.value in stub.last_request.prompt
    for archetype in profile.content_intelligence.forbidden_hook_archetypes:
        assert archetype.value in stub.last_request.prompt
    assert profile.script.hook_style in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Hook generation failed"):
        service.generate(
            topic="The Mary Celeste",
            story_angle=_angle(),
            audience_promise=_promise(),
            research=_research(),
            editorial_profile=_editorial_profile(),
        )


def test_generate_raises_when_no_hooks_parsed() -> None:
    stub = _StubLLMService(content="This response has no valid blocks at all.")

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable hooks"):
        service.generate(
            topic="The Mary Celeste",
            story_angle=_angle(),
            audience_promise=_promise(),
            research=_research(),
            editorial_profile=_editorial_profile(),
        )


def test_generate_rejects_hook_count_below_one() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least 1"):
        service.generate(
            topic="The Mary Celeste",
            story_angle=_angle(),
            audience_promise=_promise(),
            research=_research(),
            editorial_profile=_editorial_profile(),
            hook_count=0,
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        HookGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        hook_count=5,
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = HookGenerationService(llm_service=replay)  # type: ignore[arg-type]

    hooks = replay_service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        hook_count=5,
    )

    assert len(hooks) == 5


def _research_with_facts() -> ResearchResult:
    research = _research()
    research.structured_facts = [
        ResearchFact(text="The ship was found seaworthy."),
        ResearchFact(text="The crew was never found."),
    ]
    return research


def test_generate_without_facts_leaves_fact_ids_empty() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    hooks = service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert all(hook.fact_ids == [] for hook in hooks)
    assert stub.last_request is not None
    assert "FACT_IDS" not in stub.last_request.prompt


def test_generate_binds_fact_ids_from_labeled_response() -> None:
    research = _research_with_facts()
    content = (
        "TEXT: The crew vanished without a trace.\nFACT_IDS: 1\n"
        "---\n"
        "TEXT: What the investigators found made no sense.\nFACT_IDS: 1, 2"
    )
    stub = _StubLLMService(content=content)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    hooks = service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=research,
        editorial_profile=_editorial_profile(),
    )

    assert hooks[0].fact_ids == [research.structured_facts[0].id]
    assert hooks[1].fact_ids == [
        research.structured_facts[0].id,
        research.structured_facts[1].id,
    ]


def test_generate_parses_hook_archetype() -> None:
    content = "TEXT: The crew vanished without a trace.\nHOOK_ARCHETYPE: mystery"
    stub = _StubLLMService(content=content)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    hooks = service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    from src.models.genre_profile import HookArchetype

    assert hooks[0].type == HookArchetype.MYSTERY


def test_generate_ignores_an_unrecognized_archetype() -> None:
    content = (
        "TEXT: The crew vanished without a trace.\nHOOK_ARCHETYPE: not_a_real_type"
    )
    stub = _StubLLMService(content=content)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    hooks = service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
    )

    assert hooks[0].type is None


def test_generate_prompt_includes_additional_instructions() -> None:
    stub = _StubLLMService(content=_THREE_HOOK_BLOCK)

    service = HookGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        story_angle=_angle(),
        audience_promise=_promise(),
        research=_research(),
        editorial_profile=_editorial_profile(),
        additional_instructions="Make it more suspenseful.",
    )

    assert stub.last_request is not None
    assert "Make it more suspenseful." in stub.last_request.prompt
