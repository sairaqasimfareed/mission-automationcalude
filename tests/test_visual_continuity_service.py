from __future__ import annotations

import pytest

from src.models.continuity_bible import (
    ContinuityBible,
    ContinuityEntry,
    ContinuityEntryType,
)
from src.models.scene import Scene
from src.services.llm.llm_service import LLMServiceResult
from src.services.visual_continuity_service import VisualContinuityService
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


def _scene(number: int, narration: str) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=narration,
        visual_prompt="A ship at sea.",
        estimated_duration_seconds=10,
    )


def _continuity_bible() -> ContinuityBible:
    return ContinuityBible(
        topic="The Mary Celeste",
        entries=[
            ContinuityEntry(
                entry_type=ContinuityEntryType.CHARACTER,
                name="Captain Briggs",
                description="Captain of the Mary Celeste.",
                first_mentioned_segment=1,
            ),
            ContinuityEntry(
                entry_type=ContinuityEntryType.LOCATION,
                name="The Mary Celeste",
                description="A merchant brigantine.",
                first_mentioned_segment=1,
            ),
        ],
        prompt_version="continuity_bible_extraction_prompt_v1.0.0",
    )


_VALID_RESPONSE = "\n---\n".join(
    [
        (
            "SCENE: 1\n"
            "WARDROBE: Captain's uniform.\n"
            "CONDITION: Calm.\n"
            "LOCATION: The deck.\n"
            "TIME_OF_DAY: Morning.\n"
            "WEATHER: Clear.\n"
            "LIGHTING: Bright daylight.\n"
            "PROPS: compass\n"
            "VEHICLES: none\n"
            "SHOT_ACTION: Captain Briggs surveys the horizon.\n"
            "ENTITIES_PRESENT: Captain Briggs, The Mary Celeste"
        ),
        (
            "SCENE: 2\n"
            "WARDROBE: Captain's uniform, now damp.\n"
            "CONDITION: Alert.\n"
            "LOCATION: The deck.\n"
            "TIME_OF_DAY: Morning.\n"
            "WEATHER: Storm approaching.\n"
            "LIGHTING: Overcast.\n"
            "PROPS: compass, spyglass\n"
            "VEHICLES: none\n"
            "SHOT_ACTION: Captain Briggs spots dark clouds.\n"
            "ENTITIES_PRESENT: Captain Briggs"
        ),
    ]
)


def test_build_creates_one_entry_per_scene() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = VisualContinuityService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.build(
        scenes=[_scene(1, "The captain surveys."), _scene(2, "Clouds gather.")],
        continuity_bible=_continuity_bible(),
        script_lock_hash="hash123",
    )

    assert len(bible.clip_entries) == 2
    assert bible.script_lock_hash == "hash123"


def test_identities_are_built_from_continuity_bible() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = VisualContinuityService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.build(
        scenes=[_scene(1, "The captain surveys.")],
        continuity_bible=_continuity_bible(),
        script_lock_hash="hash123",
    )

    assert {p.name for p in bible.people} == {"Captain Briggs"}
    assert {loc.name for loc in bible.locations} == {"The Mary Celeste"}


def test_first_scene_incoming_state_is_a_fresh_default() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = VisualContinuityService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.build(
        scenes=[_scene(1, "The captain surveys.")],
        continuity_bible=_continuity_bible(),
        script_lock_hash="hash123",
    )

    entry = bible.entry_for_scene(1)
    assert entry is not None
    assert entry.incoming_state.wardrobe == "unspecified"


def test_adjacent_handoff_equality_holds_by_construction() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = VisualContinuityService(llm_service=stub)  # type: ignore[arg-type]

    bible = service.build(
        scenes=[_scene(1, "The captain surveys."), _scene(2, "Clouds gather.")],
        continuity_bible=_continuity_bible(),
        script_lock_hash="hash123",
    )

    entry_1 = bible.entry_for_scene(1)
    entry_2 = bible.entry_for_scene(2)
    assert entry_1 is not None and entry_2 is not None
    assert entry_1.outgoing_state == entry_2.incoming_state


def test_build_requires_at_least_one_scene() -> None:
    stub = _StubLLMService(content=_VALID_RESPONSE)
    service = VisualContinuityService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="at least one scene"):
        service.build(
            scenes=[], continuity_bible=_continuity_bible(), script_lock_hash="hash123"
        )


def test_build_raises_on_provider_failure() -> None:
    stub = _StubLLMService(content="", success=False)
    service = VisualContinuityService(llm_service=stub)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Visual continuity build failed"):
        service.build(
            scenes=[_scene(1, "The captain surveys.")],
            continuity_bible=_continuity_bible(),
            script_lock_hash="hash123",
        )


def test_negative_estimated_cost_is_rejected() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        VisualContinuityService(
            llm_service=_StubLLMService(content=""),  # type: ignore[arg-type]
            estimated_cost_usd=-1.0,
        )
