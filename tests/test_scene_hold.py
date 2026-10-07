"""
Room between scenes (2026-10-07): clips are sized to the narration, so a video was the
narration back to back with no designed pause. A short per-genre hold after each line
lets a clip run a little longer than its words; it is dropped when it would turn a
one-clip scene into several, and it can be set per project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.scene_clip_split_planning_service import SceneClipSplitPlanningService
from src.services.scene_hold import (
    GENRE_HOLD_SECONDS,
    HOLD_CHOICES,
    clip_sizing_seconds,
    hold_seconds,
)


def _plan_flow(seconds: float) -> list[float]:
    return SceneClipSplitPlanningService.plan(seconds)


def _plan_muse(seconds: float) -> list[float]:
    return SceneClipSplitPlanningService.plan(
        seconds, max_single_clip_seconds=10.0, clamp=lambda value: value
    )


def _job(genre: str = "genre.medical", hold: float | None = None) -> VideoJob:
    return VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id=genre,
        scene_hold_seconds=hold,
    )


def _scene(narration: float | None) -> Scene:
    scene = Scene(
        scene_number=1,
        title="Scene 1",
        narration="Narration.",
        visual_prompt="Visual.",
        estimated_duration_seconds=8,
    )
    scene.real_narration_duration_seconds = narration

    return scene


# --------------------------------------------------------------- the hold itself


def test_every_genre_has_a_hold_and_the_slow_ones_hold_longest() -> None:
    for profile in GenreProfileRegistryService.with_default_profiles().list_all():
        assert profile.genre_id in GENRE_HOLD_SECONDS, profile.genre_id

    assert GENRE_HOLD_SECONDS["genre.default"] == 0.0
    assert GENRE_HOLD_SECONDS["genre.medical"] < GENRE_HOLD_SECONDS["genre.horror"]
    assert (
        GENRE_HOLD_SECONDS["genre.reaction"] < GENRE_HOLD_SECONDS["genre.storytelling"]
    )
    assert all(0.0 <= value <= 1.5 for value in GENRE_HOLD_SECONDS.values())


def test_the_projects_own_choice_wins_over_the_genre() -> None:
    assert hold_seconds(_job("genre.horror")) == 1.0
    assert hold_seconds(_job("genre.horror", hold=0.0)) == 0.0
    assert hold_seconds(_job("genre.medical", hold=1.2)) == 1.2


def test_an_unknown_genre_has_no_hold() -> None:
    assert hold_seconds(_job("genre.nope")) == 0.0


def test_the_choices_offer_the_genre_default_first() -> None:
    assert HOLD_CHOICES[0] == ("Genre default", None)
    assert [value for _label, value in HOLD_CHOICES] == [None, 0.0, 0.4, 0.8, 1.2]


def test_a_project_can_not_hold_for_an_absurd_time() -> None:
    with pytest.raises(ValueError):
        _job(hold=10.0)

    with pytest.raises(ValueError):
        _job(hold=-1.0)


# ------------------------------------------------------------------ the sizing


def test_nothing_is_sized_until_the_narration_is_measured() -> None:
    assert clip_sizing_seconds(_job(), _scene(None), _plan_muse) is None


def test_the_hold_is_added_to_the_narration() -> None:
    assert clip_sizing_seconds(_job(), _scene(5.0), _plan_muse) == pytest.approx(5.4)
    assert clip_sizing_seconds(_job("genre.horror"), _scene(5.0), _plan_muse) == (
        pytest.approx(6.0)
    )


def test_no_hold_leaves_the_narration_exactly_as_before() -> None:
    assert clip_sizing_seconds(_job(hold=0.0), _scene(5.0), _plan_muse) == 5.0
    assert clip_sizing_seconds(_job("genre.default"), _scene(5.0), _plan_muse) == 5.0


def test_the_hold_is_dropped_when_it_would_split_a_muse_scene() -> None:
    """9.8 s fits one 10 s clip; 9.8 + 0.4 would need two."""

    assert clip_sizing_seconds(_job(), _scene(9.8), _plan_muse) == 9.8


def test_the_hold_is_dropped_when_it_would_split_a_flow_scene() -> None:
    """7.8 s fits Flow's 8 s clip; 7.8 + 0.4 would need two."""

    assert clip_sizing_seconds(_job(), _scene(7.8), _plan_flow) == 7.8


def test_a_scene_that_is_already_split_keeps_its_hold_when_the_count_is_unchanged() -> (
    None
):
    sized = clip_sizing_seconds(_job(), _scene(12.0), _plan_muse)

    assert sized == pytest.approx(12.4)
    assert len(_plan_muse(sized or 0)) == len(_plan_muse(12.0)) == 2


# ------------------------------------------------------- what a provider is sent


def _muse_prompt(tmp_path: Path, job: VideoJob, narration: float) -> str:
    from src.models.muse_generation import MuseGenerationState
    from tests.test_muse_scene_video_generation_service import (
        _real_video_file,
        _ScriptedProvider,
        _service,
    )
    from tests.test_muse_scene_video_generation_service import (
        _scene as muse_scene,
    )

    provider = _ScriptedProvider(
        observe_sequence=[
            MuseGenerationState.GENERATING,
            MuseGenerationState.READY_TO_DOWNLOAD,
        ]
    )
    provider.downloaded_file = str(_real_video_file(tmp_path))
    service = _service(provider)
    scene = muse_scene(1)
    scene.real_narration_duration_seconds = narration
    job.scenes = [scene]
    service.generate_one(job, 1)

    return provider.submitted_prompts[0]


def test_muse_is_asked_for_a_clip_that_includes_the_hold(tmp_path: Path) -> None:
    held = _muse_prompt(tmp_path, _job("genre.horror"), 4.0)  # 4.0 + 1.0 hold
    plain = _muse_prompt(tmp_path, _job("genre.horror", hold=0.0), 4.0)

    assert "Duration: 5 seconds" in held
    assert "Duration: 4 seconds" in plain


# ------------------------------------------------------------ Project settings


def test_project_settings_offers_the_hold_and_saves_the_choice(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox, QPushButton

    from src.desktop.job_store import InMemoryJobStore
    from tests.test_content_studio_content_intelligence_gui import _job as studio_job
    from tests.test_content_studio_content_intelligence_gui import _view as studio_view

    store = InMemoryJobStore()
    job = studio_job()
    store.add(job)
    view = studio_view(store)
    view.set_job(job.id)
    view.refresh(job)

    combo = next(
        c
        for c in view.findChildren(QComboBox)
        if c.count() == len(HOLD_CHOICES) and c.itemText(0) == "Genre default"
    )
    assert combo.currentData() is None

    combo.setCurrentIndex(combo.findData(0.8))
    save = next(
        b for b in view.findChildren(QPushButton) if b.text() == "Save settings"
    )
    save.click()

    assert job.scene_hold_seconds == 0.8


from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)
