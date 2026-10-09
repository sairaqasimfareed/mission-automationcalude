"""
Character-Oriented Video mode, step 3 (2026-10-09): the project-creation toggle and the preset it
applies - the clip's own audio is the speech (the narrator voiceover is muted at the final mix but
still generated, because its length sizes the clips), the pause after each line is off, and the
clips are generated with Muse, the provider this mode was tested on.
"""

from __future__ import annotations

from uuid import UUID

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.services.character_mode_preset import apply_character_mode_preset
from src.services.scene_hold import hold_seconds
from tests.test_project_form_view import _view
from tests.test_project_form_view import qapp as qapp  # noqa: PLC0414 - fixture


def _job(**kwargs) -> VideoJob:  # type: ignore[no-untyped-def]
    fields = {"genre_id": "genre.history", **kwargs}

    return VideoJob(
        project_name="Post office",
        channel_name="Channel",
        niche="history",
        topic="The post office",
        **fields,
    )


# ------------------------------------------------------------------------- the preset


def test_the_preset_makes_the_clips_own_audio_the_speech() -> None:
    job = apply_character_mode_preset(_job())

    prefs = job.audio_inclusion_preferences
    assert job.character_oriented is True
    assert prefs.include_native_clip_audio is True
    assert prefs.include_voiceover is False


def test_the_preset_leaves_the_operators_music_and_effects_choices_alone() -> None:
    job = _job(
        audio_inclusion_preferences=AudioInclusionPreferences(
            include_music=False, include_sound_effects=True
        )
    )

    apply_character_mode_preset(job)

    assert job.audio_inclusion_preferences.include_music is False
    assert job.audio_inclusion_preferences.include_sound_effects is True


def test_the_preset_turns_the_pause_after_each_line_off_even_for_a_slow_genre() -> None:
    job = _job(genre_id="genre.mystery")  # the genre default is a long hold
    assert hold_seconds(job) > 0

    apply_character_mode_preset(job)

    assert hold_seconds(job) == 0.0


def test_the_preset_generates_the_clips_with_muse() -> None:
    job = _job()
    assert job.video_provider == VideoProvider.GOOGLE_FLOW

    apply_character_mode_preset(job)

    assert job.video_provider == VideoProvider.MUSE


def test_an_ordinary_project_keeps_every_default() -> None:
    job = _job()

    assert job.character_oriented is False
    assert job.audio_inclusion_preferences.include_voiceover is True
    assert job.audio_inclusion_preferences.include_native_clip_audio is False
    assert job.video_provider == VideoProvider.GOOGLE_FLOW


# ------------------------------------------------------------------------ the form


def _fill(view) -> None:  # type: ignore[no-untyped-def]
    view._project_name.setText("Post office")
    view._channel_name.setText("Channel")
    view._topic.setText("The post office")
    view._video_type.setText("drama")
    view._niche.setText("history")
    view._genre.setCurrentText("genre.history")


def _create(view) -> VideoJob:  # type: ignore[no-untyped-def]
    ids: list[UUID] = []
    view._on_created = ids.append
    view._handle_create_clicked()
    job = view._job_store.get(ids[0])
    assert job is not None

    return job


def test_the_toggle_is_off_by_default_and_has_its_own_card(qapp) -> None:  # type: ignore[no-untyped-def]
    view = _view()

    assert view._character_oriented.isChecked() is False
    assert "Characters speak on camera" in view._character_oriented.text()


def test_creating_a_project_with_the_toggle_on_applies_the_preset(qapp) -> None:  # type: ignore[no-untyped-def]
    view = _view()
    _fill(view)
    view._character_oriented.setChecked(True)

    job = _create(view)

    assert job.character_oriented is True
    assert job.audio_inclusion_preferences.include_native_clip_audio is True
    assert job.audio_inclusion_preferences.include_voiceover is False
    assert job.video_provider == VideoProvider.MUSE
    assert hold_seconds(job) == 0.0


def test_creating_a_project_with_the_toggle_off_changes_nothing(qapp) -> None:  # type: ignore[no-untyped-def]
    view = _view()
    _fill(view)

    job = _create(view)

    assert job.character_oriented is False
    assert job.audio_inclusion_preferences.include_voiceover is True
    assert job.video_provider == VideoProvider.GOOGLE_FLOW


def test_the_toggle_works_with_any_genre(qapp) -> None:  # type: ignore[no-untyped-def]
    view = _view()
    _fill(view)
    view._genre.setCurrentText("genre.horror")
    view._character_oriented.setChecked(True)

    job = _create(view)

    assert job.genre_id == "genre.horror"
    assert job.character_oriented is True


def test_the_script_box_tells_the_operator_how_to_write_dialogue(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget

    from tests.test_suggestions import _studio

    for flag, expected in (
        (True, "NAME: what they say"),
        (False, "Paste your script here"),
    ):
        view, job, _errors = _studio(_job())
        job.character_oriented = flag
        holder = QWidget()
        layout = QVBoxLayout(holder)

        view._render_script_intake_section(layout, job)  # noqa: SLF001

        placeholder = holder.findChildren(QTextEdit)[0].placeholderText()
        assert expected in placeholder
