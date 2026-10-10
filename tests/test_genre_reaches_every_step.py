"""
Every step that decides how the video looks must be told the genre (2026-10-10 audit, after a horror
project came out as a calm documentary). This drives the whole pipeline with a recording stub and checks,
request by request, which steps received the genre - so a step added or edited later cannot silently
stop hearing it.

Two kinds of step are checked:
- the steps that decide the LOOK (visual continuity, style sheet, shot planning, scene detail) must carry
  the genre's treatment direction when the genre has one, and nothing when it has none;
- the steps written before the script (audience promise ... script) already name the genre from the
  editorial profile and must keep doing so.
Steps that only extract facts, split structure or score prompts are deliberately not given a genre.
"""

from __future__ import annotations

from src.services.content_intelligence_pipeline import ContentIntelligencePipeline
from src.services.genre_visual_mood import genre_direction
from tests.test_content_intelligence_pipeline import _EchoStubLLMService, _job

# metadata["agent"] of every step that decides the look
_LOOK_STEPS = {
    "VisualContinuityService",
    "ProjectStyleSheetService",
    "ShotPlanningService",
    "SceneDetailService",
}

# steps written before the script: they read the genre profile (id and tone) in their prompt
_PRE_SCRIPT_STEPS = {
    "AudiencePromiseService",
    "StoryAngleGenerationService",
    "StoryBlueprintGenerationService",
}


def _run(genre_id: str) -> _EchoStubLLMService:
    stub = _EchoStubLLMService()
    pipeline = ContentIntelligencePipeline(llm_service=stub)  # type: ignore[arg-type]
    pipeline.run_all(_job(genre_id=genre_id))

    return stub


def _by_agent(stub: _EchoStubLLMService) -> dict[str, list[str]]:
    seen: dict[str, list[str]] = {}

    for request in stub.requests:
        agent = str(request.metadata.get("agent", ""))
        seen.setdefault(agent, []).append(request.prompt)

    return seen


def test_every_look_step_ran_in_the_pipeline() -> None:
    agents = set(_by_agent(_run("genre.horror")))

    assert _LOOK_STEPS <= agents, _LOOK_STEPS - agents


def test_every_look_step_carries_the_horror_direction() -> None:
    direction = genre_direction("genre.horror")
    seen = _by_agent(_run("genre.horror"))

    for agent in sorted(_LOOK_STEPS):
        assert seen[agent], agent
        assert all(direction in prompt for prompt in seen[agent]), agent


def test_a_genre_with_no_mood_adds_no_treatment_to_any_look_step() -> None:
    seen = _by_agent(_run("genre.medical"))

    for agent in sorted(_LOOK_STEPS):
        assert all(
            "Genre treatment" not in prompt for prompt in seen.get(agent, [])
        ), agent


def test_the_look_steps_get_a_different_direction_for_a_different_genre() -> None:
    horror = _by_agent(_run("genre.horror"))
    history = _by_agent(_run("genre.history"))

    for agent in sorted(_LOOK_STEPS):
        assert genre_direction("genre.history") in history[agent][0], agent
        assert genre_direction("genre.horror") not in history[agent][0], agent
        assert genre_direction("genre.history") not in horror[agent][0], agent


def test_the_steps_before_the_script_still_name_the_genre() -> None:
    seen = _by_agent(_run("genre.horror"))

    for agent in sorted(_PRE_SCRIPT_STEPS):
        assert seen[agent], agent
        assert all("genre.horror" in prompt for prompt in seen[agent]), agent
