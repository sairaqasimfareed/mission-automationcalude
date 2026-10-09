"""
The project style sheet (2026-10-09): the world and look of the whole video, written once and
repeated in every prompt, drafted from the script (the operator may upload a script with no research
behind it). Only what the script supports is filled; a script that names no place or era leaves those
fields empty - forcing a region or year into a video that does not need one is worse than none - and
a field the operator wrote is never overwritten.
"""

from __future__ import annotations

import pytest

from src.models.project_look import ProjectLook
from src.models.visual_continuity import VisualState
from src.services.project_style_sheet_service import ProjectStyleSheetService
from tests.test_suggestions import (
    _job,
    _StubLLM,
    _studio,
    _texts,
)
from tests.test_suggestions import (
    qapp as qapp,  # noqa: PLC0414 - fixture
)

_FULL = """SETTING: A small farming village in the highlands of Cameroon, August 1986
BUILDINGS: Thatched mud-brick huts with red earth walls and corrugated tin roofs
CLIMATE: Humid highland air, banana trees, rolling green hills, low mist
LIGHTING: Flat overcast daylight with no hard shadows
PALETTE: Muted earth tones with a cool grey-green grade
CAMERA: Documentary realism, 35mm, slow push-ins
SOUND: Wind, distant birdsong and a faint stream, no music
"""


def _service(answer: str) -> tuple[ProjectStyleSheetService, _StubLLM]:
    llm = _StubLLM(answer)

    return ProjectStyleSheetService(llm_service=llm), llm  # type: ignore[arg-type]


# --------------------------------------------------------------------------- model


def test_a_look_has_no_setting_unless_one_is_given() -> None:
    look = ProjectLook(lighting="Overcast")

    assert (look.setting, look.architecture, look.climate, look.sound) == ("",) * 4
    assert look.is_empty is False
    assert ProjectLook().is_empty is True


def test_a_look_with_only_a_setting_field_is_not_empty() -> None:
    assert ProjectLook(sound="Wind").is_empty is False


def test_the_sentence_is_unchanged_for_the_old_three_fields() -> None:
    look = ProjectLook(
        lighting="Overcast", color_palette="Muted", camera_feel="Handheld"
    )

    assert look.as_prompt_sentence() == (
        "Visual style for the whole video - lighting: Overcast; colour palette: "
        "Muted; camera feel: Handheld."
    )


def test_the_sentence_names_every_filled_field_and_skips_empty_ones() -> None:
    look = ProjectLook(setting="Highland village", sound="Wind", lighting="Overcast")

    sentence = look.as_prompt_sentence()

    assert "setting: Highland village" in sentence
    assert "background sound: Wind" in sentence
    assert "lighting: Overcast" in sentence
    assert "climate" not in sentence
    assert ProjectLook().as_prompt_sentence() == ""


def test_the_descriptive_fields_hold_300_characters_and_the_style_fields_200() -> None:
    ProjectLook(setting="x" * 300)

    with pytest.raises(ValueError, match="300"):
        ProjectLook(setting="x" * 301)

    with pytest.raises(ValueError, match="200"):
        ProjectLook(lighting="x" * 201)


def test_a_look_saved_before_these_fields_existed_loads() -> None:
    look = ProjectLook.model_validate({"lighting": "Overcast"})

    assert look.setting == "" and look.sound == ""


# ---------------------------------------------------------------------- the draft


def test_a_full_reply_fills_every_field() -> None:
    service, _llm = _service(_FULL)

    look = service.draft(_job())

    assert look.setting.startswith("A small farming village in the highlands")
    assert look.architecture.startswith("Thatched mud-brick huts")
    assert "banana trees" in look.climate
    assert look.lighting == "Flat overcast daylight with no hard shadows"
    assert look.color_palette.startswith("Muted earth tones")
    assert look.camera_feel.startswith("Documentary realism")
    assert look.sound.startswith("Wind, distant birdsong")


def test_a_script_that_gives_no_place_or_era_leaves_those_fields_empty() -> None:
    reply = (
        "SETTING: NONE\nBUILDINGS: NONE\nCLIMATE: none\n"
        "LIGHTING: Soft studio light\nPALETTE: Clean whites and blues\n"
        "CAMERA: Locked-off, steady\nSOUND: unspecified\n"
    )
    service, _llm = _service(reply)

    look = service.draft(_job())

    assert (look.setting, look.architecture, look.climate, look.sound) == ("",) * 4
    assert look.lighting == "Soft studio light"


def test_a_reply_of_only_none_gives_an_empty_look() -> None:
    service, _llm = _service("NONE")

    assert service.draft(_job()).is_empty is True


def test_labels_wrapped_in_markdown_are_still_read() -> None:
    service, _llm = _service("**SETTING:** A fishing town\n- **SOUND:** Gulls\n")

    look = service.draft(_job())

    assert look.setting == "A fishing town"
    assert look.sound == "Gulls"


def test_a_long_value_is_cut_at_a_word_boundary_instead_of_being_rejected() -> None:
    long_value = "word " * 100
    service, _llm = _service(f"LIGHTING: {long_value}\nSETTING: {long_value}\n")

    look = service.draft(_job())

    assert 0 < len(look.lighting) <= 200 and not look.lighting.endswith(" ")
    assert 0 < len(look.setting) <= 300


def test_the_prompt_carries_the_script_the_settings_and_the_do_not_invent_rule() -> (
    None
):
    job = _job()
    assert job.visual_continuity_bible is not None
    job.visual_continuity_bible.clip_entries[0].incoming_state = VisualState(
        location="A rural village near Lake Nyos"
    )
    service, llm = _service("NONE")

    service.draft(job)

    prompt = llm.requests[0].prompt
    assert "Narration 1." in prompt
    assert "A rural village near Lake Nyos" in prompt
    assert "write NONE for that label" in prompt
    assert "Never guess a country, year or culture" in prompt


def test_a_failing_call_raises_a_plain_error() -> None:
    service = ProjectStyleSheetService(llm_service=_StubLLM("", success=False))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Drafting the style sheet failed"):
        service.draft(_job())


def test_a_project_with_no_scenes_cannot_be_drafted() -> None:
    service, _llm = _service(_FULL)

    with pytest.raises(ValueError, match="planned scenes"):
        service.draft(_job(scenes=0))


# ------------------------------------------------------ the operator's words win


def test_a_field_the_operator_wrote_is_kept_and_blanks_are_filled() -> None:
    service, _llm = _service(_FULL)
    drafted = service.draft(_job())
    existing = ProjectLook(lighting="My own light", sound="")

    merged = ProjectStyleSheetService.fill_blanks(existing, drafted)

    assert merged.lighting == "My own light"
    assert merged.setting == drafted.setting
    assert merged.sound == drafted.sound


def test_filling_blanks_with_no_existing_look_takes_the_whole_draft() -> None:
    service, _llm = _service(_FULL)
    drafted = service.draft(_job())

    merged = ProjectStyleSheetService.fill_blanks(None, drafted)

    fields = (
        "setting",
        "architecture",
        "climate",
        "lighting",
        "color_palette",
        "camera_feel",
        "sound",
    )
    assert {f: getattr(merged, f) for f in fields} == {
        f: getattr(drafted, f) for f in fields
    }


# ------------------------------------------------------------------- the pipeline


def _pipeline(answer: str):  # type: ignore[no-untyped-def]
    from src.services.content_intelligence_pipeline import ContentIntelligencePipeline

    pipeline = ContentIntelligencePipeline.__new__(ContentIntelligencePipeline)
    pipeline.project_style_sheet_service = ProjectStyleSheetService(
        llm_service=_StubLLM(answer)  # type: ignore[arg-type]
    )

    return pipeline


def test_the_stage_saves_the_drafted_look_on_the_project() -> None:
    job = _job()

    _pipeline(_FULL).run_style_sheet(job)

    assert job.project_look is not None
    assert job.project_look.setting.startswith("A small farming village")


def test_the_stage_leaves_the_project_without_a_look_when_the_script_gives_none() -> (
    None
):
    job = _job()

    _pipeline("NONE").run_style_sheet(job)

    assert job.project_look is None


def test_the_stage_keeps_what_the_operator_already_wrote() -> None:
    job = _job()
    job.project_look = ProjectLook(lighting="My own light")

    _pipeline(_FULL).run_style_sheet(job)

    assert job.project_look is not None
    assert job.project_look.lighting == "My own light"
    assert job.project_look.sound.startswith("Wind")


# ------------------------------------------------------------------------- the GUI


def test_the_look_section_shows_the_new_fields_and_the_draft_button(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    view, job, _errors = _studio(_job())
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_project_look_section(layout, job)  # noqa: SLF001

    texts = _texts(holder)
    for label in ("Setting", "Buildings and materials", "Climate and plants"):
        assert label in texts
    assert "Background sound" in texts
    assert "Draft the empty fields from my script" in texts


def test_saving_the_look_keeps_the_setting_fields(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio(_job())
    job.project_look = ProjectLook(setting="Highland village", sound="Wind")

    view._apply_project_look(job, {"lighting": "Overcast"})  # noqa: SLF001

    assert errors == []
    assert job.project_look is not None
    assert job.project_look.lighting == "Overcast"
    assert job.project_look.setting == "Highland village"
    assert job.project_look.sound == "Wind"


def test_using_a_suggested_look_does_not_blank_the_setting(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio(_job())
    job.project_look = ProjectLook(setting="Highland village")
    view._ensure_look_suggestions(job)  # noqa: SLF001
    chosen = job.look_suggestions[0]

    view._handle_use_look(chosen.id)  # noqa: SLF001

    assert errors == []
    assert job.project_look is not None
    assert job.project_look.setting == "Highland village"
    assert job.project_look.lighting == chosen.lighting


def test_the_draft_button_handler_does_not_crash_without_a_pipeline_answer(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio(_job())
    view._content_intelligence_pipeline = _pipeline("NONE")  # type: ignore[assignment]  # noqa: SLF001

    view._handle_draft_style_sheet()  # noqa: SLF001

    assert errors == []
    assert job.project_look is None


def test_the_draft_button_fills_the_look_and_the_prompts_pick_it_up(qapp) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio(_job())
    view._content_intelligence_pipeline = _pipeline(_FULL)  # type: ignore[assignment]  # noqa: SLF001

    view._handle_draft_style_sheet()  # noqa: SLF001

    assert errors == []
    assert job.project_look is not None
    assert job.project_look.climate.startswith("Humid highland")
