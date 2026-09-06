from __future__ import annotations

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.production_semantic_brief_service import (
    ProductionSemanticBriefService,
)

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _segment(
    *,
    number: int,
    start: float,
    end: float,
    narrative_function: StoryBeatType,
    tension_level: int = 50,
    related_curiosity_loop: str | None = None,
    source_claim_references: list[str] | None = None,
) -> ScriptSegment:
    return ScriptSegment(
        segment_number=number,
        start_seconds=start,
        end_seconds=end,
        narrative_function=narrative_function,
        narration="Something happens here.",
        tension_level=tension_level,
        related_curiosity_loop=related_curiosity_loop,
        source_claim_references=source_claim_references or [],
    )


def _script(*segments: ScriptSegment) -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=int(max(segment.end_seconds for segment in segments)),
        segments=list(segments),
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _blueprint(*beats: StoryBeat) -> StoryBlueprint:
    return StoryBlueprint(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=int(max(beat.end_seconds for beat in beats)),
        beats=list(beats),
        prompt_version="story_blueprint_prompt_v1.0.0",
    )


def test_generates_one_segment_per_script_segment() -> None:
    service = ProductionSemanticBriefService()
    script = _script(
        _segment(number=1, start=0.0, end=10.0, narrative_function=StoryBeatType.HOOK),
        _segment(
            number=2, start=10.0, end=20.0, narrative_function=StoryBeatType.SETUP
        ),
    )
    genre_profile = _GENRE_REGISTRY.get("genre.mystery")

    brief = service.generate(
        script=script,
        genre_profile=genre_profile,
        script_lock_hash="hash123",
    )

    assert len(brief.segments) == 2
    assert brief.segments[0].beat_type == "hook"
    assert brief.segments[1].beat_type == "setup"
    assert brief.script_lock_hash == "hash123"


def test_carries_reveal_protection_and_supporting_claims_through() -> None:
    service = ProductionSemanticBriefService()
    script = _script(
        _segment(
            number=1,
            start=0.0,
            end=10.0,
            narrative_function=StoryBeatType.HOOK,
            related_curiosity_loop="What happened to the crew?",
            source_claim_references=["fact-1", "fact-2"],
        ),
    )
    genre_profile = _GENRE_REGISTRY.get("genre.mystery")

    brief = service.generate(
        script=script, genre_profile=genre_profile, script_lock_hash="hash123"
    )

    segment = brief.segments[0]
    assert segment.reveal_protected is True
    assert segment.related_curiosity_loop == "What happened to the crew?"
    assert segment.supporting_claims == ["fact-1", "fact-2"]


def test_binds_beat_id_by_time_range_when_blueprint_supplied() -> None:
    service = ProductionSemanticBriefService()
    script = _script(
        _segment(number=1, start=0.0, end=10.0, narrative_function=StoryBeatType.HOOK),
        _segment(
            number=2, start=10.0, end=20.0, narrative_function=StoryBeatType.SETUP
        ),
    )
    hook_beat = StoryBeat(
        beat_type=StoryBeatType.HOOK,
        start_seconds=0.0,
        end_seconds=10.0,
        purpose="Grab attention.",
        tension_level=70,
    )
    setup_beat = StoryBeat(
        beat_type=StoryBeatType.SETUP,
        start_seconds=10.0,
        end_seconds=20.0,
        purpose="Establish context.",
        tension_level=40,
    )
    blueprint = _blueprint(hook_beat, setup_beat)
    genre_profile = _GENRE_REGISTRY.get("genre.mystery")

    brief = service.generate(
        script=script,
        genre_profile=genre_profile,
        script_lock_hash="hash123",
        story_blueprint=blueprint,
    )

    assert brief.segments[0].beat_id == hook_beat.id
    assert brief.segments[1].beat_id == setup_beat.id


def test_beat_id_is_none_without_a_blueprint() -> None:
    service = ProductionSemanticBriefService()
    script = _script(
        _segment(number=1, start=0.0, end=10.0, narrative_function=StoryBeatType.HOOK),
    )
    genre_profile = _GENRE_REGISTRY.get("genre.mystery")

    brief = service.generate(
        script=script, genre_profile=genre_profile, script_lock_hash="hash123"
    )

    assert brief.segments[0].beat_id is None


def test_two_generations_from_identical_input_produce_the_same_hash() -> None:
    service = ProductionSemanticBriefService()
    script = _script(
        _segment(number=1, start=0.0, end=10.0, narrative_function=StoryBeatType.HOOK),
    )
    genre_profile = _GENRE_REGISTRY.get("genre.mystery")

    brief_a = service.generate(
        script=script, genre_profile=genre_profile, script_lock_hash="hash123"
    )
    brief_b = service.generate(
        script=script, genre_profile=genre_profile, script_lock_hash="hash123"
    )

    assert brief_a.content_hash == brief_b.content_hash
