"""
Character-Oriented Video mode, Slice 2 (2026-10-09): appearance, outfit and voice for every speaking
character, drafted from the script and repeated word for word in each prompt they are in - the voice
comes only from the prompt (Muse has no voice-ID input), and live a long, exact voice line kept one
voice the same across clips and two voices apart in one clip. The drafting fills only what is empty,
never overwrites what the operator wrote, and never guesses a gender from a name. An operator can also
upload a picture of a character instead of waiting for a frame from a generated clip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.dialogue import DialogueLine
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.models.visual_continuity import (
    CanonicalEntityIdentity,
    CanonicalEntityType,
    ClipContinuityEntry,
    VisualContinuityBible,
    VisualState,
)
from src.services.character_sheet_service import (
    CharacterSheet,
    CharacterSheetService,
)
from src.services.dialogue_prompt import dialogue_prompt_text
from src.services.recurring_identity_service import RecurringIdentityService
from src.services.speaker_identity_service import placeholder_description
from tests.test_recurring_identity_service import _Selector
from tests.test_suggestions import _StubLLM
from tests.test_suggestions import qapp as qapp  # noqa: PLC0414 - fixture

_APPEARANCE = (
    "A lean man of about sixty with a grey moustache, deep-set eyes and thinning grey hair "
    "combed flat, stooped at the shoulders."
)
_OUTFIT = (
    "A flat wool cap, a grey-green wool jacket with a brass eagle badge, a dark tie."
)
_VOICE = (
    "An older man's low, dry baritone, slow and deliberate, clear enunciation, quiet volume, "
    "a faint rural Idaho accent."
)


def _lines(*pairs: tuple[str, str]) -> list[DialogueLine]:
    return [DialogueLine(speaker=s, text=t) for s, t in pairs]


def _person(name: str, **kwargs) -> CanonicalEntityIdentity:  # type: ignore[no-untyped-def]
    fields = {"canonical_description": placeholder_description(name), **kwargs}

    return CanonicalEntityIdentity(
        entity_type=CanonicalEntityType.PERSON, name=name, is_manual=True, **fields
    )


def _job(identities: list[CanonicalEntityIdentity] | None = None) -> VideoJob:
    dialogue = {
        1: _lines(("Walter", "The train is late.")),
        2: _lines(("Walter", "Hold the post."), ("Frank", "Then start sorting.")),
    }
    job = VideoJob(
        project_name="Post office",
        channel_name="Channel",
        niche="history",
        topic="The post office",
        genre_id="genre.history",
        character_oriented=True,
    )
    job.scenes = [
        Scene(
            scene_number=n,
            title=f"Scene {n}",
            narration=" ".join(line.text for line in lines),
            visual_prompt="v",
            estimated_duration_seconds=8,
            dialogue=lines,
        )
        for n, lines in dialogue.items()
    ]
    job.visual_continuity_bible = VisualContinuityBible(
        script_lock_hash="a" * 64,
        identities=(
            identities
            if identities is not None
            else [_person("Walter"), _person("Frank")]
        ),
        clip_entries=[
            ClipContinuityEntry(
                scene_number=n,
                incoming_state=VisualState(),
                shot_action=f"Shot {n}.",
                outgoing_state=VisualState(),
                entity_names=["Walter", "Frank"] if n == 2 else ["Walter"],
                on_screen_entity_names=["Walter", "Frank"] if n == 2 else ["Walter"],
            )
            for n in dialogue
        ],
    )

    return job


def _reply(name: str = "Walter") -> str:
    return (
        f"NAME: {name}\nAPPEARANCE: {_APPEARANCE}\nOUTFIT: {_OUTFIT}\nVOICE: {_VOICE}"
    )


def _service(
    reply: str | None, *, fail: bool = False
) -> tuple[CharacterSheetService, _StubLLM]:
    llm = _StubLLM(reply or "", success=not fail)

    return CharacterSheetService(llm_service=llm), llm  # type: ignore[arg-type]


def _identity(job: VideoJob, name: str) -> CanonicalEntityIdentity:
    assert job.visual_continuity_bible is not None

    return next(i for i in job.visual_continuity_bible.identities if i.name == name)


# ------------------------------------------------------------------------- the model


def test_an_identity_has_no_outfit_or_voice_until_one_is_written() -> None:
    identity = _person("Walter")

    assert (identity.outfit, identity.voice) == ("", "")


def test_outfit_and_voice_are_cleaned() -> None:
    identity = _person("Walter", outfit="  A  wool   cap ", voice=" Low  baritone ")

    assert (identity.outfit, identity.voice) == ("A wool cap", "Low baritone")


def test_an_identity_saved_before_these_fields_existed_loads() -> None:
    data = _person("Walter").model_dump(mode="json")
    data.pop("outfit")
    data.pop("voice")

    loaded = CanonicalEntityIdentity.model_validate(data)

    assert (loaded.outfit, loaded.voice) == ("", "")


# ------------------------------------------------------------------- who needs a sheet


def test_a_speaker_with_a_placeholder_description_needs_a_sheet() -> None:
    needing = CharacterSheetService.characters_needing_a_sheet(_job())

    assert [i.name for i in needing] == ["Walter", "Frank"]


def test_a_complete_speaker_does_not() -> None:
    done = _person(
        "Walter", canonical_description=_APPEARANCE, outfit=_OUTFIT, voice=_VOICE
    )
    job = _job([done, _person("Frank")])

    assert [i.name for i in CharacterSheetService.characters_needing_a_sheet(job)] == [
        "Frank"
    ]


def test_a_character_with_an_appearance_but_no_voice_still_needs_one() -> None:
    partly = _person("Walter", canonical_description=_APPEARANCE, outfit=_OUTFIT)
    job = _job([partly, _person("Frank")])

    assert "Walter" in [
        i.name for i in CharacterSheetService.characters_needing_a_sheet(job)
    ]


def test_a_person_who_never_speaks_is_not_drafted() -> None:
    job = _job([_person("Walter"), _person("Frank"), _person("Bystander")])

    names = [i.name for i in CharacterSheetService.characters_needing_a_sheet(job)]

    assert "Bystander" not in names


# --------------------------------------------------------------------------- drafting


def test_a_full_reply_gives_a_sheet_per_character() -> None:
    service, _llm = _service(_reply("Walter") + "\n---\n" + _reply("Frank"))

    sheets = service.draft(_job())

    assert [s.name for s in sheets] == ["Walter", "Frank"]
    assert sheets[0].voice.startswith("An older man's low, dry baritone")
    assert sheets[0].outfit.startswith("A flat wool cap")


def test_labels_wrapped_in_markdown_are_read() -> None:
    reply = f"**NAME:** Walter\n**APPEARANCE:** {_APPEARANCE}\n**VOICE:** {_VOICE}"
    service, _llm = _service(reply)

    sheets = service.draft(_job([_person("Walter")]))

    assert sheets[0].appearance.startswith("A lean man")
    assert sheets[0].outfit == ""


def test_a_none_reply_gives_no_sheets() -> None:
    service, _llm = _service("NONE")

    assert service.draft(_job()) == []


def test_a_name_that_was_not_asked_for_is_ignored() -> None:
    service, _llm = _service(_reply("Stranger"))

    assert service.draft(_job()) == []


def test_a_field_that_says_none_is_left_empty() -> None:
    reply = f"NAME: Walter\nAPPEARANCE: {_APPEARANCE}\nOUTFIT: NONE\nVOICE: unspecified"
    service, _llm = _service(reply)

    sheet = service.draft(_job([_person("Walter")]))[0]

    assert sheet.outfit == "" and sheet.voice == "" and sheet.appearance


def test_nothing_is_called_when_nobody_needs_a_sheet() -> None:
    done = [
        _person(
            "Walter", canonical_description=_APPEARANCE, outfit=_OUTFIT, voice=_VOICE
        ),
        _person(
            "Frank", canonical_description=_APPEARANCE, outfit=_OUTFIT, voice=_VOICE
        ),
    ]
    service, llm = _service(_reply())

    assert service.draft(_job(done)) == []
    assert llm.requests == []


def test_a_failing_call_raises_a_plain_error() -> None:
    service, _llm = _service("", fail=True)

    with pytest.raises(RuntimeError, match="Drafting the character sheets failed"):
        service.draft(_job())


def test_the_prompt_shows_their_lines_and_what_is_already_decided_and_forbids_guessing() -> (
    None
):
    job = _job(
        [_person("Walter", outfit="A wool cap."), _person("Frank")],
    )
    service, llm = _service("NONE")

    service.draft(job)

    prompt = llm.requests[0].prompt
    assert '- "The train is late."' in prompt
    assert "Already decided (keep): outfit: A wool cap." in prompt
    assert "never guess anyone's gender" in prompt
    assert "no speaking-speed numbers" in prompt


# ---------------------------------------------------------------------------- applying


def test_a_sheet_fills_the_empty_fields_of_the_matching_person() -> None:
    job = _job()
    sheet = CharacterSheet("Walter", _APPEARANCE, _OUTFIT, _VOICE)

    changed = CharacterSheetService.apply(job, [sheet])

    walter = _identity(job, "Walter")
    assert changed == ["Walter"]
    assert walter.canonical_description == _APPEARANCE
    assert walter.outfit == _OUTFIT and walter.voice == _VOICE
    assert _identity(job, "Frank").voice == ""


def test_what_the_operator_wrote_is_never_overwritten() -> None:
    job = _job(
        [
            _person(
                "Walter",
                canonical_description="My own description of him.",
                voice="My voice.",
            ),
            _person("Frank"),
        ]
    )

    CharacterSheetService.apply(
        job, [CharacterSheet("Walter", _APPEARANCE, _OUTFIT, _VOICE)]
    )

    walter = _identity(job, "Walter")
    assert walter.canonical_description == "My own description of him."
    assert walter.voice == "My voice."
    assert walter.outfit == _OUTFIT  # the one empty field is filled


def test_a_sheet_for_someone_not_in_the_bible_changes_nothing() -> None:
    job = _job()

    assert (
        CharacterSheetService.apply(job, [CharacterSheet("Ghost", _APPEARANCE)]) == []
    )


def test_applying_twice_changes_nothing_the_second_time() -> None:
    job = _job()
    sheet = CharacterSheet("Walter", _APPEARANCE, _OUTFIT, _VOICE)
    CharacterSheetService.apply(job, [sheet])

    assert CharacterSheetService.apply(job, [sheet]) == []


# ----------------------------------------------------------------- the prompt wording


def test_each_speakers_voice_is_repeated_word_for_word_in_the_dialogue_wording() -> (
    None
):
    text = dialogue_prompt_text(
        _lines(("Walter", "Hold the post."), ("Frank", "Then start sorting.")),
        voices={
            "Walter": _VOICE,
            "Frank": "A young man's bright tenor, quick and clear.",
        },
    )

    assert f"Walter's voice: {_VOICE.rstrip('.')}." in text
    assert "Frank's voice: A young man's bright tenor, quick and clear." in text
    assert text.index("Walter's voice:") < text.index("Only one person speaks")


def test_a_speaker_without_a_voice_gets_no_voice_sentence() -> None:
    text = dialogue_prompt_text(_lines(("Walter", "x")), voices={"Frank": "Bright."})

    assert "Walter's voice:" not in text and "Frank's voice:" not in text


def _compile(job: VideoJob, number: int) -> str:
    from src.models.shot_planning import CinematicShotPlan
    from src.services.cinematic_prompt_compilation_service import (
        CinematicPromptCompilationService,
    )
    from tests.test_cinematic_prompt_compilation_service import _shot_plan

    base = _shot_plan().shots[0]
    plan = CinematicShotPlan(
        script_lock_hash="hash123",
        shots=[
            base.model_copy(update={"scene_number": s.scene_number}) for s in job.scenes
        ],
    )
    assert job.visual_continuity_bible is not None
    package = CinematicPromptCompilationService().compile(
        scenes=job.scenes,
        shot_plan=plan,
        visual_continuity_bible=job.visual_continuity_bible,
        production_semantic_brief=None,
        script_lock_hash="hash123",
    )
    prompt = package.prompt_for_scene(number)
    assert prompt is not None

    return prompt.prompt_text


def test_the_compiled_prompt_carries_the_appearance_the_outfit_and_the_voice() -> None:
    job = _job(
        [
            _person(
                "Walter",
                canonical_description=_APPEARANCE,
                outfit=_OUTFIT,
                voice=_VOICE,
            ),
            _person("Frank"),
        ]
    )

    text = _compile(job, 1)

    assert _APPEARANCE.rstrip(".") in text
    assert f"Outfit: {_OUTFIT.rstrip('.')}" in text
    assert f"Walter's voice: {_VOICE.rstrip('.')}." in text


def test_a_voice_found_under_a_longer_bible_name_is_still_used() -> None:
    job = _job([_person("Walter Hale", voice=_VOICE), _person("Frank")])
    for entry in job.visual_continuity_bible.clip_entries:  # type: ignore[union-attr]
        entry.entity_names = [
            n.replace("Walter", "Walter Hale") for n in entry.entity_names
        ]

    assert f"Walter's voice: {_VOICE.rstrip('.')}." in _compile(job, 1)


def test_a_character_without_an_outfit_adds_no_outfit_words() -> None:
    assert "Outfit:" not in _compile(_job(), 1)


# ------------------------------------------------------------- the recurring-identity service


def _identities(tmp_path: Path) -> RecurringIdentityService:
    return RecurringIdentityService(
        selection_service=_Selector(tmp_path),  # type: ignore[arg-type]
        storage_root=tmp_path / "frames",
    )


def test_adding_a_character_can_carry_an_outfit_and_a_voice(tmp_path: Path) -> None:
    job = _job([])

    identity = _identities(tmp_path).add(
        job,
        name="Nora",
        kind=CanonicalEntityType.PERSON,
        description=_APPEARANCE,
        scene_text="1-2",
        outfit=_OUTFIT,
        voice=_VOICE,
    )

    assert (identity.outfit, identity.voice) == (_OUTFIT, _VOICE)


def test_editing_without_the_fields_keeps_them(tmp_path: Path) -> None:
    job = _job([_person("Walter", outfit=_OUTFIT, voice=_VOICE)])

    identity = _identities(tmp_path).update(
        job, "Walter", new_name="Walter", description=_APPEARANCE, scene_text="1-2"
    )

    assert (identity.outfit, identity.voice) == (_OUTFIT, _VOICE)


def test_editing_with_empty_fields_clears_them(tmp_path: Path) -> None:
    job = _job([_person("Walter", outfit=_OUTFIT, voice=_VOICE)])

    identity = _identities(tmp_path).update(
        job,
        "Walter",
        new_name="Walter",
        description=_APPEARANCE,
        scene_text="1-2",
        outfit="",
        voice="",
    )

    assert (identity.outfit, identity.voice) == ("", "")


def test_an_outfit_or_voice_that_is_too_long_is_refused(tmp_path: Path) -> None:
    job = _job([])

    with pytest.raises(ValueError, match="outfit"):
        _identities(tmp_path).add(
            job,
            name="Nora",
            kind=CanonicalEntityType.PERSON,
            description=_APPEARANCE,
            scene_text="1",
            outfit="x" * 401,
        )

    with pytest.raises(ValueError, match="voice"):
        _identities(tmp_path).add(
            job,
            name="Nora",
            kind=CanonicalEntityType.PERSON,
            description=_APPEARANCE,
            scene_text="1",
            voice="x" * 501,
        )


# --------------------------------------------------------------------- cast picture upload


def _picture(tmp_path: Path, name: str = "cast.png") -> Path:
    path = tmp_path / name
    # different bytes per file name: identical pictures are stored once
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + f"pixels of {name}".encode())

    return path


def test_an_uploaded_picture_becomes_the_characters_reference(tmp_path: Path) -> None:
    job = _job()
    service = _identities(tmp_path)

    result = service.set_reference_from_file(job, "Walter", str(_picture(tmp_path)))

    walter = _identity(job, "Walter")
    assert result.attached is True
    assert len(walter.reference_asset_ids) == 1
    asset = job.extracted_frame_asset_index.get(walter.reference_asset_ids[0])
    assert asset is not None and Path(asset.file_path).is_file()


def test_a_second_upload_replaces_the_first(tmp_path: Path) -> None:
    job = _job()
    service = _identities(tmp_path)
    service.set_reference_from_file(job, "Walter", str(_picture(tmp_path, "a.png")))
    first = list(_identity(job, "Walter").reference_asset_ids)

    service.set_reference_from_file(job, "Walter", str(_picture(tmp_path, "b.jpg")))

    assert _identity(job, "Walter").reference_asset_ids != first
    assert len(_identity(job, "Walter").reference_asset_ids) == 1


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda tmp: str(tmp / "missing.png"), "could not be found"),
        (lambda tmp: str(_text_file(tmp)), "PNG, JPG or WebP"),
    ],
)
def test_a_missing_or_wrong_kind_of_file_is_a_plain_error(tmp_path: Path, make, message: str) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError, match=message):
        _identities(tmp_path).set_reference_from_file(_job(), "Walter", make(tmp_path))


def _text_file(tmp: Path) -> Path:
    path = tmp / "notes.txt"
    path.write_text("not a picture")

    return path


def test_a_picture_for_someone_not_in_the_bible_is_a_plain_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="no character or place named Ghost"):
        _identities(tmp_path).set_reference_from_file(
            _job(), "Ghost", str(_picture(tmp_path))
        )


# --------------------------------------------------------------------------- the pipeline


def _pipeline(tmp_path: Path, reply: str):  # type: ignore[no-untyped-def]
    from tests.test_content_intelligence_pipeline import _job as pipeline_job
    from tests.test_content_intelligence_pipeline import _pipeline as make_pipeline

    pipeline, _ = make_pipeline()
    job = pipeline.run_all(pipeline_job())
    pipeline.recurring_identity_service = _identities(tmp_path)
    pipeline.character_sheet_service = CharacterSheetService(
        llm_service=_StubLLM(reply)  # type: ignore[arg-type]
    )
    job.character_oriented = True
    job.scenes[0].dialogue = _lines(("Walter", "The train is late."))
    job.scenes[1].dialogue = _lines(("Walter", "Hold the post."), ("Frank", "Sort it."))

    return pipeline, job


def test_the_visual_continuity_step_drafts_the_sheets_for_a_character_project(
    tmp_path: Path,
) -> None:
    pipeline, job = _pipeline(tmp_path, _reply("Walter") + "\n---\n" + _reply("Frank"))

    pipeline.run_visual_continuity(job)

    walter = _identity(job, "Walter")
    assert walter.voice.startswith("An older man's low, dry baritone")
    assert walter.outfit.startswith("A flat wool cap")
    assert walter.canonical_description.startswith("A lean man")


def test_an_ordinary_project_is_never_drafted(tmp_path: Path) -> None:
    pipeline, job = _pipeline(tmp_path, _reply("Walter"))
    job.character_oriented = False

    pipeline.run_visual_continuity(job)

    assert all(
        i.name != "Walter"
        for i in job.visual_continuity_bible.identities  # type: ignore[union-attr]
    )


def test_a_failing_draft_does_not_fail_the_bible(tmp_path: Path) -> None:
    pipeline, job = _pipeline(tmp_path, "")
    pipeline.character_sheet_service = CharacterSheetService(
        llm_service=_StubLLM("", success=False)  # type: ignore[arg-type]
    )

    pipeline.run_visual_continuity(job)  # must not raise

    assert job.visual_continuity_bible is not None
    assert _identity(job, "Walter").voice == ""


def test_the_stage_alone_writes_the_sheets_and_keeps_the_operators_words(
    tmp_path: Path,
) -> None:
    pipeline, job = _pipeline(tmp_path, _reply("Walter"))
    pipeline.run_visual_continuity(job)  # links the speakers, drafts once
    walter = _identity(job, "Walter")
    walter.voice = "My own voice words."

    pipeline.character_sheet_service = CharacterSheetService(
        llm_service=_StubLLM(_reply("Walter"))  # type: ignore[arg-type]
    )
    pipeline.run_character_sheets(job)

    assert _identity(job, "Walter").voice == "My own voice words."


# ------------------------------------------------------------------- the speech budget


def test_an_over_long_exchange_is_flagged_on_the_prompts_tab_once(
    tmp_path: Path,
) -> None:
    from src.models.cinematic_prompt import (
        CinematicPromptPackage,
        ResolvedCinematicPrompt,
    )
    from src.models.enriched_scene_prompt import EnrichedScenePrompt
    from src.services.prompt_completeness_service import (
        FindingCode,
        PromptCompletenessService,
    )

    class _Enriched:
        def build_entries(self, *, job, scene):  # type: ignore[no-untyped-def]
            return [
                EnrichedScenePrompt(
                    scene_number=scene.scene_number,
                    clip_sequence_index=index,
                    base_prompt_text="x" * 800,
                )
                for index in (0, 1)
            ]

    job = _job()
    job.video_provider = VideoProvider.MUSE
    job.scenes[0].dialogue = _lines(("Walter", " ".join(["word"] * 40)))
    job.scenes[0].estimated_duration_seconds = 16
    job.cinematic_prompt_package = CinematicPromptPackage(
        script_lock_hash="hash123",
        prompts=[
            ResolvedCinematicPrompt(
                scene_number=1, script_lock_hash="hash123", prompt_text="x"
            )
        ],
    )

    report = PromptCompletenessService(_Enriched()).report(job)  # type: ignore[arg-type]

    first = [f.code for f in report.findings_for(1, 0)]
    second = [f.code for f in report.findings_for(1, 1)]
    assert FindingCode.SPEECH_TOO_LONG in first
    assert FindingCode.SPEECH_TOO_LONG not in second
    assert FindingCode.SPEECH_TOO_LONG not in [
        f.code for f in report.findings_for(2, 0)
    ]


# --------------------------------------------------------------------------- the screen


def _studio_with_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    from tests.test_suggestions import _studio

    view, job, errors = _studio(_job())
    job.character_oriented = True
    view._recurring_identity_service = _identities(tmp_path)  # noqa: SLF001

    return view, job, errors


def test_the_people_section_lists_the_outfit_and_voice_and_offers_the_new_buttons(
    qapp, tmp_path: Path  # type: ignore[no-untyped-def]
) -> None:
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _texts

    view, job, _errors = _studio_with_service(tmp_path)
    _identity(job, "Walter").outfit = _OUTFIT
    _identity(job, "Walter").voice = _VOICE
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_recurring_identities_section(layout, job)  # noqa: SLF001

    texts = _texts(holder)
    assert any(f"Outfit: {_OUTFIT}" in t and f"Voice: {_VOICE}" in t for t in texts)
    assert "Upload a picture" in texts
    assert "Draft appearance, outfit and voice from my script" in texts


def test_an_ordinary_project_has_no_draft_button(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from tests.test_suggestions import _texts

    view, job, _errors = _studio_with_service(tmp_path)
    job.character_oriented = False
    holder = QWidget()
    layout = QVBoxLayout(holder)

    view._render_recurring_identities_section(layout, job)  # noqa: SLF001

    assert "Draft appearance, outfit and voice from my script" not in _texts(holder)


def test_saving_the_form_stores_the_outfit_and_voice(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio_with_service(tmp_path)
    view._recurring_form = {  # noqa: SLF001
        "name": "Nora",
        "kind": "person",
        "description": _APPEARANCE,
        "scenes": "1-2",
        "outfit": _OUTFIT,
        "voice": _VOICE,
    }

    view._handle_save_identity()  # noqa: SLF001

    assert errors == []
    nora = _identity(job, "Nora")
    assert (nora.outfit, nora.voice) == (_OUTFIT, _VOICE)


def test_editing_an_identity_shows_its_outfit_and_voice_in_the_form(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, job, _errors = _studio_with_service(tmp_path)
    _identity(job, "Walter").outfit = _OUTFIT
    _identity(job, "Walter").voice = _VOICE

    view._handle_edit_identity("Walter")  # noqa: SLF001

    assert view._recurring_form["outfit"] == _OUTFIT  # noqa: SLF001
    assert view._recurring_form["voice"] == _VOICE  # noqa: SLF001


def test_the_draft_button_writes_the_sheets(qapp, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    view, job, errors = _studio_with_service(tmp_path)

    class _Pipeline:
        def run_character_sheets(self, target):  # type: ignore[no-untyped-def]
            CharacterSheetService.apply(
                target, [CharacterSheet("Walter", _APPEARANCE, _OUTFIT, _VOICE)]
            )

            return target

    view._content_intelligence_pipeline = _Pipeline()  # type: ignore[assignment]  # noqa: SLF001

    view._handle_draft_character_sheets()  # noqa: SLF001

    assert errors == []
    assert _identity(job, "Walter").voice == _VOICE


def test_the_upload_button_uses_the_chosen_picture(qapp, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QFileDialog

    view, job, errors = _studio_with_service(tmp_path)
    picture = _picture(tmp_path)
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *a, **k: (str(picture), "")
    )

    view._handle_upload_identity_picture("Walter")  # noqa: SLF001

    assert errors == []
    assert len(_identity(job, "Walter").reference_asset_ids) == 1


def test_cancelling_the_upload_dialog_changes_nothing(qapp, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QFileDialog

    view, job, errors = _studio_with_service(tmp_path)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: ("", ""))

    view._handle_upload_identity_picture("Walter")  # noqa: SLF001

    assert errors == []
    assert _identity(job, "Walter").reference_asset_ids == []
