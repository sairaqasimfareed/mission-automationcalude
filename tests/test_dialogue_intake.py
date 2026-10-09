"""
Character-Oriented Video mode, step 2 (2026-10-09): the imported `NAME: line` script becomes one
segment per scene with its attributed lines, and the scene planner turns each such segment into
exactly one scene. The scene's narration is the spoken words with the names left out, so voice
timing, clip sizing and the subtitles keep working unchanged on what is actually said.
"""

from __future__ import annotations

import pytest

from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.media_strategy import SceneSourceType
from src.models.script_intake import ScriptIntakeMode
from src.models.video_job import VideoJob
from src.services.dialogue_script_parser import DialogueScriptError
from src.services.script_intake_service import ScriptIntakeService
from tests.test_scene_planner_generated_script import _editorial_profile
from tests.test_suggestions import _StubLLM

_SCRIPT = """WALTER: Postmaster says the afternoon train is late again.

WALTER: We cannot hold the post past six.
FRANK: Then you had better start sorting.

FRANK: I will be on the platform.
"""


def _service() -> ScriptIntakeService:
    return ScriptIntakeService(llm_service=_StubLLM("NONE"))  # type: ignore[arg-type]


def _normalize(text: str = _SCRIPT, *, character_oriented: bool = True):  # type: ignore[no-untyped-def]
    return _service().normalize_text_to_script(
        raw_text=text,
        topic="The post office",
        genre_id="genre.history",
        target_duration_seconds=60,
        character_oriented=character_oriented,
    )


def _job(*, character_oriented: bool) -> VideoJob:
    return VideoJob(
        project_name="Post office",
        channel_name="Channel",
        niche="history",
        topic="The post office",
        genre_id="genre.history",
        character_oriented=character_oriented,
    )


# ------------------------------------------------------------------------- import


def test_each_block_becomes_one_segment_with_its_attributed_lines() -> None:
    script = _normalize()

    assert [len(s.dialogue) for s in script.segments] == [1, 2, 1]
    assert [line.speaker for line in script.segments[1].dialogue] == ["Walter", "Frank"]
    assert script.prompt_version == "script_intake_dialogue_prompt_v1.0.0"


def test_the_narration_is_the_spoken_words_without_the_names() -> None:
    script = _normalize()

    assert script.segments[1].narration == (
        "We cannot hold the post past six. Then you had better start sorting."
    )
    assert "Walter" not in script.full_narration
    assert "FRANK" not in script.full_narration


def test_segments_are_timed_by_their_words_and_do_not_overlap() -> None:
    script = _normalize()

    ends = [s.end_seconds for s in script.segments]
    starts = [s.start_seconds for s in script.segments]

    assert starts[0] == 0.0
    assert starts[1:] == ends[:-1]
    assert all(e > s for s, e in zip(starts, ends, strict=True))


def test_a_line_with_no_speaker_stops_the_import_with_its_line_number() -> None:
    with pytest.raises(DialogueScriptError, match="Line 2 has no speaker"):
        _normalize("WALTER: One.\nthe train left")


def test_an_ordinary_import_is_unchanged_and_keeps_its_text() -> None:
    script = _normalize(
        "WALTER: Not dialogue.\n\nSecond paragraph.", character_oriented=False
    )

    assert [s.dialogue for s in script.segments] == [[], []]
    assert script.segments[0].narration == "WALTER: Not dialogue."


def test_the_intake_follows_the_projects_character_flag() -> None:
    dialogue = _service().intake(
        job=_job(character_oriented=True),
        raw_text=_SCRIPT,
        mode=ScriptIntakeMode.TRUST_MY_SCRIPT,
    )
    plain = _service().intake(
        job=_job(character_oriented=False),
        raw_text="One paragraph.\n\nAnother paragraph.",
        mode=ScriptIntakeMode.TRUST_MY_SCRIPT,
    )

    assert [len(s.dialogue) for s in dialogue.script.segments] == [1, 2, 1]
    assert all(not s.dialogue for s in plain.script.segments)


def test_a_project_saved_before_the_flag_existed_is_not_character_oriented() -> None:
    data = _job(character_oriented=False).model_dump(mode="json")
    data.pop("character_oriented")

    assert VideoJob.model_validate(data).character_oriented is False


# ---------------------------------------------------------------------------- planning


def _plan(script, genre_id: str = "genre.history"):  # type: ignore[no-untyped-def]
    return ScenePlannerAgent().plan_from_generated_script(
        script, _editorial_profile(genre_id)
    )


def test_every_exchange_is_one_scene_carrying_its_lines() -> None:
    scenes = _plan(_normalize())

    assert [s.scene_number for s in scenes] == [1, 2, 3]
    assert [[line.speaker for line in s.dialogue] for s in scenes] == [
        ["Walter"],
        ["Walter", "Frank"],
        ["Frank"],
    ]
    assert scenes[1].narration == (
        "We cannot hold the post past six. Then you had better start sorting."
    )


def test_a_long_exchange_is_not_split_by_sentence() -> None:
    long_line = " ".join(f"This is sentence number {n}." for n in range(1, 13))
    scenes = _plan(_normalize(f"WALTER: {long_line}\nFRANK: Understood."))

    assert len(scenes) == 1
    assert scenes[0].narration.count("sentence number") == 12
    assert scenes[0].estimated_duration_seconds > 8  # sized by its words, not capped


def test_a_short_exchange_gets_at_least_the_clip_minimum() -> None:
    scenes = _plan(_normalize("WALTER: Yes."))

    assert scenes[0].estimated_duration_seconds >= 4


@pytest.mark.parametrize(
    "genre", ["genre.history", "genre.documentary", "genre.mystery"]
)
def test_a_spoken_scene_is_always_generated_whatever_the_genre_default(
    genre: str,
) -> None:
    scenes = _plan(_normalize(), genre)

    assert {s.source_type for s in scenes} == {SceneSourceType.AI_GENERATE}


def test_an_ordinary_script_is_planned_exactly_as_before() -> None:
    script = _normalize(
        "The ship was found adrift. Its sails were still set.", character_oriented=False
    )

    scenes = _plan(script)

    assert scenes and all(not s.dialogue for s in scenes)
