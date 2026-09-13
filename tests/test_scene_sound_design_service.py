from __future__ import annotations

import pytest

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityEntryType,
)
from src.models.editing_directives import DirectiveIntensity, DirectiveTimingMode
from src.models.scene import Scene
from src.services.llm.llm_service import LLMServiceResult
from src.services.scene_sound_design_service import SceneSoundDesignService
from src.shared.llm.models import LLMCallResult, LLMCallStatus, LLMProvider
from src.shared.llm.request import LLMRequest


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


def _scenes() -> list[Scene]:
    return [
        Scene(
            scene_number=1,
            title="The attic hatch",
            narration="I moved into the house knowing the attic hatch had been painted shut.",
            visual_prompt="An old attic hatch painted shut.",
            estimated_duration_seconds=8,
        ),
        Scene(
            scene_number=2,
            title="Three knocks",
            narration="Then, at 3 a.m., I heard three slow knocks from directly above my ceiling.",
            visual_prompt="A man lying awake at night.",
            estimated_duration_seconds=8,
        ),
    ]


_TWO_BLOCK_RESPONSE = "\n---\n".join(
    [
        "TYPE: SFX\n"
        "SCENE: 2\n"
        "PROMPT: three slow deliberate wooden knocks from directly above, "
        "hollow and tense\n"
        "PRESET_ID: NONE\n"
        "TIMING: relative_percent\n"
        "POSITION_PERCENT: 40\n"
        "VOLUME: 75\n"
        "INTENSITY: high\n"
        "RATIONALE: Narration says 'three slow knocks from directly above'.",
        "TYPE: MUSIC\n"
        "START_SCENE: 1\n"
        "END_SCENE: 2\n"
        "MOOD: sparse, quiet unease, distant low drone\n"
        "INTENSITY: low\n"
        "RATIONALE: Opening setup, no threat revealed yet.",
    ]
)


def test_generate_parses_sfx_cue_and_music_segment() -> None:
    stub = _StubLLMService(content=_TWO_BLOCK_RESPONSE)

    service = SceneSoundDesignService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.generate(
        scenes=_scenes(),
        genre_tone="suspenseful",
        genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
    )

    assert len(plan.sfx_cues) == 1
    cue = plan.sfx_cues[0]
    assert cue.scene_number == 2
    assert "knocks" in cue.generation_prompt
    assert cue.preset_id is None
    assert cue.timing_mode == DirectiveTimingMode.RELATIVE_PERCENT
    assert cue.relative_position_percent == 40.0
    assert cue.intensity == DirectiveIntensity.HIGH

    assert len(plan.music_segments) == 1
    segment = plan.music_segments[0]
    assert segment.start_scene_number == 1
    assert segment.end_scene_number == 2
    assert segment.intensity == DirectiveIntensity.LOW


def test_generate_skips_cue_referencing_unknown_scene() -> None:
    response = (
        "TYPE: SFX\n"
        "SCENE: 99\n"
        "PROMPT: an unreachable scene cue\n"
        "RATIONALE: Should be skipped."
    )

    stub = _StubLLMService(content=response)

    service = SceneSoundDesignService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.generate(
        scenes=_scenes(),
        genre_tone="suspenseful",
        genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
    )

    assert plan.sfx_cues == []
    assert any("unknown scene" in warning for warning in plan.warnings)


def test_generate_reuses_existing_preset_id_when_given() -> None:
    response = (
        "TYPE: SFX\n"
        "SCENE: 1\n"
        "PROMPT: fallback prompt\n"
        "PRESET_ID: sfx.door_creak\n"
        "TIMING: scene_start\n"
        "VOLUME: 60\n"
        "INTENSITY: medium\n"
        "RATIONALE: The attic hatch is a door."
    )

    stub = _StubLLMService(content=response)

    service = SceneSoundDesignService(llm_service=stub)  # type: ignore[arg-type]

    plan = service.generate(
        scenes=_scenes(),
        genre_tone="suspenseful",
        genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
        available_preset_ids=["sfx.door_creak", "sfx.heartbeat_low"],
    )

    assert plan.sfx_cues[0].preset_id == "sfx.door_creak"


def test_generate_includes_continuity_bible_in_prompt() -> None:
    stub = _StubLLMService(content=_TWO_BLOCK_RESPONSE)

    service = SceneSoundDesignService(llm_service=stub)  # type: ignore[arg-type]

    bible = ContinuityBible(
        topic="The Attic Door",
        prompt_version="continuity_bible_prompt_v1.0.0",
        entries=[
            ContinuityEntry(
                entry_type=ContinuityEntryType.LOCATION,
                name="The attic",
                description="A cramped, dusty attic above the bedroom.",
                first_mentioned_segment=1,
            )
        ],
    )

    service.generate(
        scenes=_scenes(),
        genre_tone="suspenseful",
        genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
        continuity_bible=bible,
    )

    assert stub.last_request is not None
    assert "The attic" in stub.last_request.prompt


def test_generate_raises_when_provider_fails() -> None:
    stub = _StubLLMService(content="", success=False)

    service = SceneSoundDesignService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Sound design generation failed"):
        service.generate(
            scenes=_scenes(),
            genre_tone="suspenseful",
            genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
        )


def test_generate_rejects_empty_scene_list() -> None:
    stub = _StubLLMService(content=_TWO_BLOCK_RESPONSE)

    service = SceneSoundDesignService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least one scene"):
        service.generate(
            scenes=[],
            genre_tone="suspenseful",
            genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
        )


def test_constructor_rejects_negative_estimated_cost() -> None:
    stub = _StubLLMService(content=_TWO_BLOCK_RESPONSE)

    with pytest.raises(ValueError, match="cannot be negative"):
        SceneSoundDesignService(
            llm_service=stub,  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )


def test_dry_run_response_is_itself_parseable() -> None:
    probe = _StubLLMService(content=_TWO_BLOCK_RESPONSE)

    service = SceneSoundDesignService(llm_service=probe)  # type: ignore[arg-type]

    service.generate(
        scenes=_scenes(),
        genre_tone="suspenseful",
        genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
    )

    assert probe.last_request is not None
    assert probe.last_request.dry_run_response is not None

    replay = _StubLLMService(content=probe.last_request.dry_run_response)
    replay_service = SceneSoundDesignService(llm_service=replay)  # type: ignore[arg-type]

    plan = replay_service.generate(
        scenes=_scenes(),
        genre_tone="suspenseful",
        genre_narrative_architecture_hint="disturbance -> escalation -> revelation",
    )

    assert len(plan.sfx_cues) == 1
    assert len(plan.music_segments) == 1
