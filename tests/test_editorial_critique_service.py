from __future__ import annotations

import pytest

from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.research import ResearchResult, ResearchSource, ResearchStatus
from src.models.story_blueprint import StoryBeatType
from src.services.editorial_critique_service import EditorialCritiqueService
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.llm.llm_service import LLMServiceResult
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _mystery_profile() -> EditorialProfile:
    # genre.mystery has a CharacterPolicy set, so character-dependent
    # dimensions are scored for it.
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.mystery")
    )


def _documentary_profile() -> EditorialProfile:
    # genre.documentary has no CharacterPolicy - character_depth and
    # payoff_strength must never be requested or scored for it.
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get("genre.documentary")
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


def _script() -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=15,
                narrative_function=StoryBeatType.HOOK,
                narration="The crew vanished without a trace.",
                tension_level=60,
            ),
            ScriptSegment(
                segment_number=2,
                start_seconds=15,
                end_seconds=30,
                narrative_function=StoryBeatType.PAYOFF,
                narration="The crew vanished without a trace, again.",
                tension_level=80,
            ),
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


_SCORE_BLOCK = "\n".join(
    f"{label}: 75"
    for label in (
        "FACTUAL_CONFIDENCE",
        "HOOK_STRENGTH",
        "RETENTION_ARCHITECTURE",
        "EMOTIONAL_PROGRESSION",
        "RESEARCH_GROUNDING",
        "NARRATIVE_COHERENCE",
        "AUDIENCE_FIT",
        "VISUAL_OPPORTUNITY_DENSITY",
        "CHARACTER_DEPTH",
        "PAYOFF_STRENGTH",
        "CONTINUITY",
    )
)

_FINDING_BLOCK = (
    "DIMENSION: narrative_coherence\n"
    "SEVERITY: major\n"
    "SEGMENT_NUMBER: 2\n"
    "PROBLEM: Segment 2 repeats segment 1's sentence verbatim.\n"
    "REASON: Repetition this close together reads as an editing error.\n"
    "RECOMMENDED_CORRECTION: Rewrite segment 2 to add new information."
)

_RESPONSE_WITH_FINDING = f"{_SCORE_BLOCK}\n---\n{_FINDING_BLOCK}"


def test_critique_parses_dimension_scores() -> None:
    stub = _StubLLMService(content=_SCORE_BLOCK)

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    critique = service.critique(
        script=_script(), research=_research(), editorial_profile=_mystery_profile()
    )

    assert critique.dimension_scores["factual_confidence"] == 75
    assert critique.dimension_scores["hook_strength"] == 75


def test_critique_scores_character_dependent_dimensions_when_policy_is_set() -> None:
    stub = _StubLLMService(content=_SCORE_BLOCK)

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    critique = service.critique(
        script=_script(), research=_research(), editorial_profile=_mystery_profile()
    )

    assert "character_depth" in critique.dimension_scores
    assert "payoff_strength" in critique.dimension_scores


def test_critique_omits_character_dependent_dimensions_without_policy() -> None:
    stub = _StubLLMService(content=_SCORE_BLOCK)

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    critique = service.critique(
        script=_script(),
        research=_research(),
        editorial_profile=_documentary_profile(),
    )

    assert "character_depth" not in critique.dimension_scores
    assert "payoff_strength" not in critique.dimension_scores

    assert stub.last_request is not None
    assert "CHARACTER_DEPTH" not in stub.last_request.prompt
    assert "PAYOFF_STRENGTH" not in stub.last_request.prompt


def test_critique_parses_a_finding_block() -> None:
    stub = _StubLLMService(content=_RESPONSE_WITH_FINDING)

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    critique = service.critique(
        script=_script(), research=_research(), editorial_profile=_mystery_profile()
    )

    assert len(critique.findings) == 1
    finding = critique.findings[0]
    assert finding.dimension.value == "narrative_coherence"
    assert finding.severity.value == "major"
    assert finding.segment_number == 2


def test_critique_with_no_findings_returns_empty_findings_list() -> None:
    stub = _StubLLMService(content=_SCORE_BLOCK)

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    critique = service.critique(
        script=_script(), research=_research(), editorial_profile=_mystery_profile()
    )

    assert critique.findings == []


def test_critique_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Editorial critique failed"):
        service.critique(
            script=_script(), research=_research(), editorial_profile=_mystery_profile()
        )


def test_critique_raises_when_no_scores_parse() -> None:
    stub = _StubLLMService(content="nonsense response with no labels")

    service = EditorialCritiqueService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no parseable dimension scores"):
        service.critique(
            script=_script(), research=_research(), editorial_profile=_mystery_profile()
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_SCORE_BLOCK)

    with pytest.raises(ValueError, match="cannot be negative"):
        EditorialCritiqueService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_SCORE_BLOCK)

    service = EditorialCritiqueService(llm_service=probe)  # type: ignore[arg-type]

    service.critique(
        script=_script(), research=_research(), editorial_profile=_mystery_profile()
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = EditorialCritiqueService(llm_service=replay)  # type: ignore[arg-type]

    critique = replay_service.critique(
        script=_script(), research=_research(), editorial_profile=_mystery_profile()
    )

    assert len(critique.dimension_scores) > 0
