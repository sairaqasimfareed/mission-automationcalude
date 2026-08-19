from __future__ import annotations

from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.editorial_profile import EditorialProfile
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.story_blueprint import StoryBeatType
from src.services.editorial_profile_composition_service import (
    EditorialProfileCompositionService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _editorial_profile(genre_id: str = "genre.mystery") -> EditorialProfile:
    # genre.mystery: scene_density_per_minute=6.5,
    # average_visual_duration_seconds defaults to 6.0 (not overridden
    # for mystery).
    return EditorialProfileCompositionService().compose(
        genre=_GENRE_REGISTRY.get(genre_id)
    )


def _script(*segments: ScriptSegment) -> GeneratedScript:
    return GeneratedScript(
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=int(max(segment.end_seconds for segment in segments)),
        segments=list(segments),
        prompt_version="script_generation_prompt_v1.0.0",
    )


def _segment(
    *,
    number: int,
    start: float,
    end: float,
    narrative_function: StoryBeatType,
    narration: str,
    tension_level: int = 50,
) -> ScriptSegment:
    return ScriptSegment(
        segment_number=number,
        start_seconds=start,
        end_seconds=end,
        narrative_function=narrative_function,
        narration=narration,
        tension_level=tension_level,
    )


def test_plan_reconstructs_full_narration_without_duplication() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=60,
        narrative_function=StoryBeatType.SETUP,
        narration=(
            "The ship was found adrift. Its sails were still set. No crew "
            "was ever found aboard."
        ),
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    reconstructed = " ".join(scene.narration for scene in scenes)
    assert reconstructed == segment.narration


def test_plan_produces_multiple_scenes_for_a_long_multi_sentence_segment() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=120,
        narrative_function=StoryBeatType.ESCALATION,
        narration=(
            "The captain vanished. The logbook stopped mid-entry. The "
            "lifeboat was missing. No struggle was found on deck. Every "
            "cabin was untouched. The cargo remained perfectly sealed."
        ),
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    # 6 sentences, density asks for more sub-scenes than that, so the
    # sentence count is the binding cap: one sentence per scene.
    assert len(scenes) == 6


def test_plan_never_produces_more_scenes_than_sentences() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=300,
        narrative_function=StoryBeatType.HOOK,
        narration="Only one sentence exists here.",
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    assert len(scenes) == 1
    assert scenes[0].narration == segment.narration


def test_plan_caps_scene_count_by_average_visual_duration_floor() -> None:
    # Density alone would ask for 30 * 40 / 60 = 20 sub-scenes, but the
    # average_visual_duration_seconds floor (10s) allows at most
    # 40 // 10 = 4 - proving the floor actually binds, not just that
    # both numbers happen to agree.
    base_profile = _editorial_profile()
    capped_content_intelligence = base_profile.content_intelligence.model_copy(
        update={
            "scene_density_per_minute": 30.0,
            "average_visual_duration_seconds": 10.0,
        }
    )
    editorial_profile = base_profile.model_copy(
        update={"content_intelligence": capped_content_intelligence}
    )

    segment = _segment(
        number=1,
        start=0,
        end=40,
        narrative_function=StoryBeatType.REVEAL,
        narration=("One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten."),
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, editorial_profile)

    assert len(scenes) == 4


def test_plan_sets_narrative_function_from_segment() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=30,
        narrative_function=StoryBeatType.CLIMAX,
        narration="The final theory is revealed at last.",
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    assert all(scene.narrative_function == "climax" for scene in scenes)


def test_plan_scene_numbers_are_sequential_across_segments() -> None:
    first = _segment(
        number=1,
        start=0,
        end=30,
        narrative_function=StoryBeatType.HOOK,
        narration="The crew vanished without a trace.",
    )
    second = _segment(
        number=2,
        start=30,
        end=60,
        narrative_function=StoryBeatType.PAYOFF,
        narration="A waterspout scare is the leading theory.",
    )
    script = _script(first, second)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    assert [scene.scene_number for scene in scenes] == list(range(1, len(scenes) + 1))


def test_plan_scene_durations_sum_to_segment_duration() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=90,
        narrative_function=StoryBeatType.SETUP,
        narration="First fact here. Second fact here. Third fact here.",
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    total = sum(scene.estimated_duration_seconds for scene in scenes)
    assert total == 90


def test_high_tension_scene_gets_dynamic_camera_direction() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=30,
        narrative_function=StoryBeatType.CLIMAX,
        narration="The truth is finally revealed.",
        tension_level=90,
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    assert "urgent" in scenes[0].camera_direction.lower()


def test_low_tension_scene_gets_calm_camera_direction() -> None:
    segment = _segment(
        number=1,
        start=0,
        end=30,
        narrative_function=StoryBeatType.AFTERSHOCK,
        narration="The mystery is finally at rest.",
        tension_level=15,
    )
    script = _script(segment)

    agent = ScenePlannerAgent()
    scenes = agent.plan_from_generated_script(script, _editorial_profile())

    assert "static" in scenes[0].camera_direction.lower()
