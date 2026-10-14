"""
The stronger scene visual writer (2026-10-14), after the first real comparison on Haunted wife (Haiku 5.5
against a table written outside the app): it put the museum of the story's present-day frame into three
scenes set in the past, showed the unseen wife clearly in about half the scenes, and wrote atmosphere where
the narration names a specific event. It now sees only colour and camera feel (never the two-world setting),
is told each scene's own place, writes the whole script in one call, labels how visible a presence is, and a
cap on visible glimpses is enforced in code with one repair call.
"""

from __future__ import annotations

import logging

from src.models.project_look import ProjectLook
from src.models.scene import Scene
from src.services.scene_visual_writer_service import (
    SceneVisualWriterService,
    VisualRange,
    glimpse_cap,
)
from tests.test_scene_detail import _job, _ScriptedLLM


def _service(llm: _ScriptedLLM, **kwargs) -> SceneVisualWriterService:  # type: ignore[no-untyped-def]
    return SceneVisualWriterService(llm_service=llm, **kwargs)  # type: ignore[arg-type]


def _scenes_job(count: int):  # type: ignore[no-untyped-def]
    job = _job(3)
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=f"Narration {n}.",
            visual_prompt="v",
            estimated_duration_seconds=8,
        )
        for n in range(1, count + 1)
    ]

    return job


def _reply(numbers: list[int]) -> str:
    return "\n---\n".join(f"SCENE: {n}\nVISUAL: Visual {n}." for n in numbers)


def _labelled(levels: dict[int, str]) -> str:
    return "\n---\n".join(
        f"SCENE: {n}\nPRESENCE: {level}\nVISUAL: Visual {n} ({level})."
        for n, level in levels.items()
    )


# --------------------------------------------------------------------------- batching


def test_the_whole_script_goes_in_one_call_up_to_forty_scenes() -> None:
    """One call lets the writer pace a presence across the whole video."""

    llm = _ScriptedLLM([_reply(list(range(1, 41)))])

    found = _service(llm).write(_scenes_job(40), visual_range=VisualRange.STORY_ONLY)

    assert len(llm.requests) == 1
    assert sorted(found) == list(range(1, 41))


def test_a_longer_script_is_written_in_batches_of_forty() -> None:
    llm = _ScriptedLLM([_reply(list(range(1, 41))), _reply([41])])

    found = _service(llm).write(_scenes_job(41), visual_range=VisualRange.STORY_ONLY)

    assert len(llm.requests) == 2
    assert sorted(found) == list(range(1, 42))
    assert "Write the visual for scenes 41 ONLY" in llm.requests[1].prompt


# ---------------------------------------------------------------------- the prompt


def test_the_two_world_setting_never_reaches_the_writer_only_colour_and_camera() -> (
    None
):
    job = _job(2)
    job.project_look = ProjectLook(
        setting="Ancient Egypt with a present-day museum frame",
        architecture="Mudbrick; the museum interior is modern",
        lighting="Dim lamp glow; cold flat gallery light in the museum",
        color_palette="Desaturated ochres",
        camera_feel="Slow documentary push-ins",
        sound="the hush of an empty gallery",
    )
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(job, visual_range=VisualRange.CINEMATIC)

    prompt = llm.requests[0].prompt
    assert "Desaturated ochres" in prompt and "Slow documentary push-ins" in prompt
    assert "museum" not in prompt.lower()
    assert "gallery" not in prompt.lower()


def test_each_scene_is_told_its_own_place_from_the_continuity_bible() -> None:
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(_job(2), visual_range=VisualRange.STORY_ONLY)

    prompt = llm.requests[0].prompt
    assert "1. Narration 1.  [set in: The village]" in prompt
    assert "decide the place and era from the narration itself" in prompt


def test_a_scene_with_no_known_place_gets_no_set_in_note() -> None:
    job = _job(2)
    assert job.visual_continuity_bible is not None
    for entry in job.visual_continuity_bible.clip_entries:
        entry.outgoing_state.location = "unspecified"
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(job, visual_range=VisualRange.STORY_ONLY)

    prompt = llm.requests[0].prompt
    assert "1. Narration 1." in prompt
    assert "Narration 1.  [set in" not in prompt


def test_the_prompt_demands_a_specific_event_variety_and_plain_names() -> None:
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(_job(3), visual_range=VisualRange.STORY_ONLY)

    prompt = llm.requests[0].prompt
    for rule in (
        "Show the SPECIFIC thing the narration says",
        "ONE concrete event or detail",
        "not a dark room where nothing happens",
        "Neighbouring scenes must differ",
        "decided by ITS OWN narration",
        "never by the project's labels",
        "at most 40 words",
    ):
        assert rule in prompt, rule


def test_glimpse_cap_is_one_scene_in_four_and_at_least_one() -> None:
    assert [glimpse_cap(n) for n in (3, 4, 8, 19, 40)] == [1, 1, 2, 4, 10]


def test_the_cinematic_prompt_states_the_cap_and_asks_for_a_presence_label() -> None:
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(_scenes_job(19), visual_range=VisualRange.CINEMATIC)

    prompt = llm.requests[0].prompt
    assert "At most 4 of the 19 scenes may show a VISIBLE glimpse" in prompt
    assert "NEVER shown clearly" in prompt
    assert "merely names her is not a reason to show her" in prompt
    assert "PRESENCE: <none | effect | glimpse>" in prompt


def test_the_story_only_prompt_has_no_presence_rules_or_label() -> None:
    llm = _ScriptedLLM(["NONE"])

    _service(llm).write(_scenes_job(19), visual_range=VisualRange.STORY_ONLY)

    prompt = llm.requests[0].prompt
    assert "THE PRESENCE" not in prompt and "PRESENCE:" not in prompt


# --------------------------------------------------------------- the cap, in code


def test_within_the_cap_there_is_one_call_and_no_repair() -> None:
    llm = _ScriptedLLM(
        [_labelled({1: "glimpse", 2: "glimpse", 3: "effect", 4: "none"})]
    )

    found = _service(llm).write(_scenes_job(8), visual_range=VisualRange.CINEMATIC)

    assert len(llm.requests) == 1
    assert found[1] == "Visual 1 (glimpse)."


def test_more_glimpses_than_the_cap_get_one_repair_for_the_extra_scenes() -> None:
    first = _labelled(
        {1: "glimpse", 2: "glimpse", 3: "glimpse", 4: "glimpse", 5: "none"}
    )
    repair = (
        "SCENE: 3\nVISUAL: The lamp flame leans.\n---\nSCENE: 4\nVISUAL: The jar rolls."
    )
    llm = _ScriptedLLM([first, repair])

    found = _service(llm).write(_scenes_job(8), visual_range=VisualRange.CINEMATIC)

    assert len(llm.requests) == 2
    repair_prompt = llm.requests[1].prompt
    assert "Only 2 of these scenes may show a VISIBLE glimpse" in repair_prompt
    assert all(f"SCENE {n} (" in repair_prompt for n in (1, 2, 3, 4))
    assert "SCENE 5 (" not in repair_prompt
    assert found[1] == "Visual 1 (glimpse)." and found[2] == "Visual 2 (glimpse)."
    assert found[3] == "The lamp flame leans." and found[4] == "The jar rolls."
    assert found[5] == "Visual 5 (none)."
    assert str(llm.requests[1].metadata["workflow"]).endswith("repair")


def test_a_failed_repair_keeps_the_original_visuals(caplog) -> None:  # type: ignore[no-untyped-def]
    llm = _ScriptedLLM([_labelled({1: "glimpse", 2: "glimpse", 3: "glimpse"}), None])

    with caplog.at_level(logging.WARNING):
        found = _service(llm).write(_scenes_job(8), visual_range=VisualRange.CINEMATIC)

    assert sorted(found) == [1, 2, 3]
    assert found[3] == "Visual 3 (glimpse)."
    assert "the repair failed" in caplog.text


def test_a_partial_repair_rewrites_only_what_it_returned() -> None:
    first = _labelled({1: "glimpse", 2: "glimpse", 3: "glimpse", 4: "glimpse"})
    llm = _ScriptedLLM([first, "SCENE: 4\nVISUAL: A flame leans."])

    found = _service(llm).write(_scenes_job(8), visual_range=VisualRange.CINEMATIC)

    assert found[4] == "A flame leans."
    assert found[3] == "Visual 3 (glimpse)."


def test_story_only_never_repairs_whatever_the_reply_says() -> None:
    llm = _ScriptedLLM([_labelled({n: "glimpse" for n in range(1, 8)})])

    found = _service(llm).write(_scenes_job(8), visual_range=VisualRange.STORY_ONLY)

    assert len(llm.requests) == 1 and len(found) == 7


def test_a_reply_with_no_presence_labels_is_not_repaired() -> None:
    llm = _ScriptedLLM([_reply(list(range(1, 9)))])

    found = _service(llm).write(_scenes_job(8), visual_range=VisualRange.CINEMATIC)

    assert len(llm.requests) == 1 and len(found) == 8


def test_a_long_script_in_two_batches_gives_each_batch_its_share_of_the_cap() -> None:
    first = _labelled({n: ("glimpse" if n <= 10 else "none") for n in range(1, 41)})
    second = _labelled({n: ("glimpse" if n <= 52 else "none") for n in range(41, 81)})
    repair = "SCENE: 51\nVISUAL: A flame leans.\n---\nSCENE: 52\nVISUAL: A jar rolls."
    llm = _ScriptedLLM([first, second, repair])

    _service(llm).write(_scenes_job(80), visual_range=VisualRange.CINEMATIC)

    # the cap is 20 for 80 scenes: each batch of 40 may show 10; batch one is at 10, batch two shows 12
    assert len(llm.requests) == 3
    assert "Only 10 of these scenes" in llm.requests[2].prompt
