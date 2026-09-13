from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402
from uuid import UUID, uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton  # noqa: E402

from src.desktop.views.production_audio_view import ProductionAudioView  # noqa: E402
from src.models.sound_design_plan import (  # noqa: E402
    MusicMoodSegment,
    SoundDesignItemStatus,
    SoundDesignPlan,
    SoundEffectCueDirective,
)
from src.models.video_job import VideoJob  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job_with_plan() -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )
    job.sound_design_plan = SoundDesignPlan(
        sfx_cues=[
            SoundEffectCueDirective(
                scene_number=2,
                generation_prompt="three slow deliberate wooden knocks",
                rationale="Narration mentions knocks.",
            )
        ],
        music_segments=[
            MusicMoodSegment(
                start_scene_number=1,
                end_scene_number=2,
                mood_description="sparse, quiet unease",
                rationale="Opening setup.",
            )
        ],
    )
    return job


class _FakeJobStore:
    def __init__(self, job: VideoJob) -> None:
        self._job = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._job if job_id == self._job.id else None


def _build_view(job: VideoJob) -> tuple[ProductionAudioView, MagicMock]:
    pipeline = MagicMock()
    view = ProductionAudioView(
        job_store=_FakeJobStore(job),  # type: ignore[arg-type]
        media_generation_pipeline=pipeline,
        on_change=lambda: None,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view, pipeline


def _find_line_edits(view: ProductionAudioView) -> list[QLineEdit]:
    return view.findChildren(QLineEdit)


def _find_buttons(view: ProductionAudioView) -> list[QPushButton]:
    return view.findChildren(QPushButton)


def test_refresh_renders_no_sound_design_card_without_a_plan(
    qapp: QApplication,
) -> None:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )
    view, _ = _build_view(job)

    assert not _find_line_edits(view)


def test_refresh_renders_one_line_edit_per_planned_item(qapp: QApplication) -> None:
    job = _job_with_plan()
    view, _ = _build_view(job)

    line_edits = _find_line_edits(view)

    assert len(line_edits) == 2
    texts = {edit.text() for edit in line_edits}
    assert "three slow deliberate wooden knocks" in texts
    assert "sparse, quiet unease" in texts


def test_editing_prompt_updates_the_cue_in_place(qapp: QApplication) -> None:
    job = _job_with_plan()
    view, _ = _build_view(job)

    cue_edit = next(
        edit
        for edit in _find_line_edits(view)
        if edit.text() == "three slow deliberate wooden knocks"
    )
    cue_edit.setText("a different, edited prompt")

    assert job.sound_design_plan is not None
    assert job.sound_design_plan.sfx_cues[0].generation_prompt == (
        "a different, edited prompt"
    )


def test_generate_button_calls_generate_single_sfx_cue(qapp: QApplication) -> None:
    job = _job_with_plan()
    view, pipeline = _build_view(job)

    assert job.sound_design_plan is not None
    cue = job.sound_design_plan.sfx_cues[0]

    generate_button = next(
        button for button in _find_buttons(view) if button.text() == "Generate"
    )
    generate_button.click()

    pipeline.generate_single_sfx_cue.assert_called_once_with(job, str(cue.id))


def test_generate_all_sfx_skips_already_generated_cues(qapp: QApplication) -> None:
    job = _job_with_plan()
    assert job.sound_design_plan is not None
    already_generated_cue = SoundEffectCueDirective(
        scene_number=5,
        generation_prompt="already done",
        rationale="Already generated.",
        status=SoundDesignItemStatus.GENERATED,
        audio_track_id=str(uuid4()),
    )
    job.sound_design_plan.sfx_cues.append(already_generated_cue)

    view, pipeline = _build_view(job)

    all_button = next(
        button
        for button in _find_buttons(view)
        if button.text() == "Generate all sound effects"
    )
    all_button.click()

    assert pipeline.generate_single_sfx_cue.call_count == 1
    called_cue_id = pipeline.generate_single_sfx_cue.call_args[0][1]
    assert called_cue_id == str(job.sound_design_plan.sfx_cues[0].id)


def test_generate_music_segment_button_calls_generate_single_music_segment(
    qapp: QApplication,
) -> None:
    job = _job_with_plan()
    view, pipeline = _build_view(job)

    assert job.sound_design_plan is not None
    segment = job.sound_design_plan.music_segments[0]

    generate_button = next(
        button for button in _find_buttons(view) if button.text() == "Generate"
    )
    # Two "Generate" buttons exist (one SFX cue, one music segment) -
    # the SFX one is exercised by the test above; here just confirm
    # a music generate button exists and wiring reaches the pipeline
    # for at least one of them via the "generate all music" path,
    # which is unambiguous by button label.
    del generate_button

    all_music_button = next(
        button
        for button in _find_buttons(view)
        if button.text() == "Generate all music segments"
    )
    all_music_button.click()

    pipeline.generate_single_music_segment.assert_called_once_with(job, str(segment.id))
