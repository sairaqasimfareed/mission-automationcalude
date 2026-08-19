from __future__ import annotations

import pytest

from src.models.audience_promise import AudiencePromise, PromiseStrength
from src.models.editorial_profile import EditorialProfile
from src.models.story_angle import StoryAngle, StoryAngleStyle
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.llm.llm_service import LLMServiceResult
from src.services.story_blueprint_generation_service import (
    StoryBlueprintGenerationService,
)
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


_FOUR_BEAT_RESPONSE = "\n---\n".join(
    [
        "BEAT_TYPE: hook\nSTART: 0\nEND: 7\nPURPOSE: Open cold.\nTENSION: 60",
        "BEAT_TYPE: setup\nSTART: 7\nEND: 20\nPURPOSE: Establish context.\nTENSION: 30",
        "BEAT_TYPE: climax\nSTART: 20\nEND: 28\nPURPOSE: The confrontation.\nTENSION: 95",
        "BEAT_TYPE: payoff\nSTART: 28\nEND: 30\nPURPOSE: Resolve it.\nTENSION: 50",
    ]
)


def test_generate_parses_multiple_beats_in_order() -> None:
    stub = _StubLLMService(content=_FOUR_BEAT_RESPONSE)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    blueprint = service.generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        target_duration_seconds=30,
        story_angle=_angle(),
        audience_promise=_promise(),
    )

    assert len(blueprint.beats) == 4
    assert blueprint.beats[0].purpose == "Open cold."
    assert blueprint.beats[-1].end_seconds == 30.0


def test_generate_skips_a_block_with_an_unrecognized_beat_type() -> None:
    content = "\n---\n".join(
        [
            "BEAT_TYPE: not_a_real_type\nSTART: 0\nEND: 5\nPURPOSE: Bad.\nTENSION: 50",
            "BEAT_TYPE: hook\nSTART: 0\nEND: 7\nPURPOSE: Open cold.\nTENSION: 60",
        ]
    )

    stub = _StubLLMService(content=content)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    blueprint = service.generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        target_duration_seconds=7,
        story_angle=_angle(),
        audience_promise=_promise(),
    )

    assert len(blueprint.beats) == 1
    assert blueprint.beats[0].beat_type.value == "hook"


def test_generate_includes_genre_and_duration_in_prompt() -> None:
    stub = _StubLLMService(content=_FOUR_BEAT_RESPONSE)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        target_duration_seconds=30,
        story_angle=_angle(),
        audience_promise=_promise(),
    )

    assert stub.last_request is not None
    assert "genre.mystery" in stub.last_request.prompt
    assert "30 seconds" in stub.last_request.prompt
    assert "The Missing Logbook" in stub.last_request.prompt


def test_generate_prompt_includes_narrative_architecture_and_pacing() -> None:
    stub = _StubLLMService(content=_FOUR_BEAT_RESPONSE)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    profile = _editorial_profile()

    service.generate(
        topic="The Mary Celeste",
        target_duration_seconds=30,
        story_angle=_angle(),
        audience_promise=_promise(),
        editorial_profile=profile,
    )

    assert stub.last_request is not None
    assert (
        profile.content_intelligence.narrative_architecture_hint
        in stub.last_request.prompt
    )
    assert "tension" in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Story blueprint generation failed"):
        service.generate(
            topic="The Mary Celeste",
            editorial_profile=_editorial_profile(),
            target_duration_seconds=30,
            story_angle=_angle(),
            audience_promise=_promise(),
        )


def test_generate_raises_when_no_beats_parsed() -> None:
    stub = _StubLLMService(content="This response has no valid blocks at all.")

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="no usable beats"):
        service.generate(
            topic="The Mary Celeste",
            editorial_profile=_editorial_profile(),
            target_duration_seconds=30,
            story_angle=_angle(),
            audience_promise=_promise(),
        )


def test_generate_raises_when_beats_would_fail_model_validation() -> None:
    """
    Overlapping beats are rejected by StoryBlueprint itself (already
    covered in test_story_blueprint_model.py) - this confirms the
    service lets that ValidationError propagate rather than silently
    swallowing it.
    """

    content = "\n---\n".join(
        [
            "BEAT_TYPE: hook\nSTART: 0\nEND: 10\nPURPOSE: A.\nTENSION: 60",
            "BEAT_TYPE: setup\nSTART: 5\nEND: 20\nPURPOSE: B.\nTENSION: 30",
        ]
    )

    stub = _StubLLMService(content=content)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(Exception, match="cannot overlap"):
        service.generate(
            topic="The Mary Celeste",
            editorial_profile=_editorial_profile(),
            target_duration_seconds=30,
            story_angle=_angle(),
            audience_promise=_promise(),
        )


def test_generate_raises_on_empty_topic() -> None:
    stub = _StubLLMService(content=_FOUR_BEAT_RESPONSE)

    service = StoryBlueprintGenerationService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cannot be empty"):
        service.generate(
            topic="   ",
            editorial_profile=_editorial_profile(),
            target_duration_seconds=30,
            story_angle=_angle(),
            audience_promise=_promise(),
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_FOUR_BEAT_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        StoryBlueprintGenerationService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_FOUR_BEAT_RESPONSE)

    service = StoryBlueprintGenerationService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        target_duration_seconds=30,
        story_angle=_angle(),
        audience_promise=_promise(),
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = StoryBlueprintGenerationService(llm_service=replay)  # type: ignore[arg-type]

    blueprint = replay_service.generate(
        topic="The Mary Celeste",
        editorial_profile=_editorial_profile(),
        target_duration_seconds=30,
        story_angle=_angle(),
        audience_promise=_promise(),
    )

    assert len(blueprint.beats) == 4
    assert blueprint.has_tension_variation is True
