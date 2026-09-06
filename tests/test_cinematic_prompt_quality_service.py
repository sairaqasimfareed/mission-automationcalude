from __future__ import annotations

import pytest

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.services.cinematic_prompt_quality_service import CinematicPromptQualityService
from src.services.llm.llm_service import LLMServiceResult
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


class _StubLLMService:
    def __init__(self, *, content: str, success: bool = True) -> None:
        self._content = content
        self._success = success

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
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


def _package() -> CinematicPromptPackage:
    return CinematicPromptPackage(
        script_lock_hash="hash123",
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1,
                script_lock_hash="hash123",
                prompt_text="A ship's captain surveys the horizon at dawn.",
            )
        ],
    )


_VALID_RESPONSE = (
    "SCENE: 1\n"
    "SPECIFICITY: 80\n"
    "CONTINUITY: 75\n"
    "ACTION: 85\n"
    "CAMERA: 70\n"
    "LIGHTING: 90\n"
    "REVEAL_SAFETY: 95"
)


def test_evaluate_attaches_scores_to_matching_prompt() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = CinematicPromptQualityService(llm_service=stub)  # type: ignore[arg-type]

    scored = service.evaluate(_package())

    prompt = scored.prompt_for_scene(1)
    assert prompt is not None
    assert prompt.specificity_score == 80
    assert prompt.reveal_safety_score == 95
    assert prompt.is_scored is True


def test_evaluate_does_not_mutate_the_original_package() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = CinematicPromptQualityService(llm_service=stub)  # type: ignore[arg-type]

    original = _package()
    service.evaluate(original)

    original_prompt = original.prompt_for_scene(1)
    assert original_prompt is not None
    assert original_prompt.is_scored is False


def test_evaluate_leaves_unscored_a_prompt_the_response_skipped() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)  # only covers scene 1
    service = CinematicPromptQualityService(llm_service=stub)  # type: ignore[arg-type]

    package = CinematicPromptPackage(
        script_lock_hash="hash123",
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1, script_lock_hash="hash123", prompt_text="Scene one."
            ),
            ResolvedCinematicPrompt(
                scene_number=2, script_lock_hash="hash123", prompt_text="Scene two."
            ),
        ],
    )

    scored = service.evaluate(package)

    scored_prompt_1 = scored.prompt_for_scene(1)
    scored_prompt_2 = scored.prompt_for_scene(2)
    assert scored_prompt_1 is not None and scored_prompt_2 is not None
    assert scored_prompt_1.is_scored is True
    assert scored_prompt_2.is_scored is False


def test_evaluate_requires_at_least_one_prompt() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = CinematicPromptQualityService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least one prompt"):
        service.evaluate(CinematicPromptPackage(script_lock_hash="hash123"))


def test_evaluate_raises_on_provider_failure() -> None:
    stub = _StubLLMService(content="", success=False)
    service = CinematicPromptQualityService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(
        RuntimeError, match="Cinematic prompt quality evaluation failed"
    ):
        service.evaluate(_package())
