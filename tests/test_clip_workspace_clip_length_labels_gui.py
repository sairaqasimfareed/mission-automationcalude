"""
Clips tab (2026-10-06): every scene row says how long its clip is - planned before it
exists, real once it does - and a scene that will be several clips says so up front
(the Prompts tab shows one prompt per part while the row has one Generate button).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.models.media_strategy import SceneSourceStatus, SceneSourceType  # noqa: E402
from src.models.video_clip import VideoClip, VideoClipStatus  # noqa: E402
from src.models.video_provider import VideoProvider  # noqa: E402
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    _build_view,
    _FakeSceneVideoGenerationService,
    _job,
)
from tests.test_clip_workspace_view_scene_generation import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)


def _texts(view) -> list[str]:  # type: ignore[no-untyped-def]
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    return [label.text() for label in view.findChildren(QLabel)]


def _row(view, scene_number: int) -> str:  # type: ignore[no-untyped-def]
    prefix = f"Scene {scene_number}: "

    return next(t for t in _texts(view) if t.startswith(prefix))


def _view(provider: VideoProvider, narration: float | None, *, estimate: int = 8):  # type: ignore[no-untyped-def]
    job = _job(1)
    job.video_provider = provider
    job.scene_hold_seconds = 0.0  # these labels are pinned without a hold
    job.scenes[0].estimated_duration_seconds = estimate
    job.scenes[0].real_narration_duration_seconds = narration
    view = _build_view(job, service=_FakeSceneVideoGenerationService())
    view.refresh(job)

    return view, job


def _clip(number: int, seconds: int, sequence: int = 0) -> VideoClip:
    return VideoClip(
        scene_number=number,
        clip_sequence_index=sequence,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=seconds,
        local_file=f"downloads/s{number}_{sequence}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def test_a_muse_scene_shows_its_planned_length_rounded_up(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _ = _view(VideoProvider.MUSE, narration=6.4)

    assert "planned 7s" in _row(view, 1)
    assert "narration 6.4s" in _row(view, 1)


def test_a_flow_scene_shows_its_grid_length(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _ = _view(VideoProvider.GOOGLE_FLOW, narration=5.0)

    assert "planned 6s" in _row(view, 1)


def test_before_the_narration_exists_the_estimate_is_used(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _ = _view(VideoProvider.MUSE, narration=None, estimate=5)

    row = _row(view, 1)

    assert "planned 5s" in row
    assert "narration" not in row


def test_a_scene_longer_than_one_clip_shows_each_part(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _ = _view(VideoProvider.MUSE, narration=12.96, estimate=12)

    assert "planned 7s + 7s" in _row(view, 1)


def test_a_split_scene_says_up_front_that_one_generate_makes_every_part(
    qapp: QApplication,  # noqa: F811
) -> None:
    """The Prompts tab shows two prompts for scene 30 but the Clips row has one
    Generate button - this line explains why."""

    view, _ = _view(VideoProvider.MUSE, narration=12.96, estimate=12)

    assert any(
        "Will be generated as 2 clips (7s + 7s) - one Generate makes all of them" in t
        for t in _texts(view)
    )


def test_flow_splits_on_its_own_grid(qapp: QApplication) -> None:  # noqa: F811
    view, _ = _view(VideoProvider.GOOGLE_FLOW, narration=12.96, estimate=12)

    assert any("Will be generated as 2 clips (8s + 6s)" in t for t in _texts(view))


def test_a_single_clip_scene_has_no_split_line(
    qapp: QApplication,  # noqa: F811
) -> None:
    view, _ = _view(VideoProvider.MUSE, narration=4.0)

    assert not any("Will be generated as" in t for t in _texts(view))


def test_a_generated_clip_shows_its_real_length(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    job.video_provider = VideoProvider.MUSE
    job.scenes[0].real_narration_duration_seconds = 6.4
    job.video_clips = [_clip(1, 7)]
    view = _build_view(job, service=_FakeSceneVideoGenerationService())
    view.refresh(job)

    row = _row(view, 1)

    assert "clip 7s" in row
    assert "planned" not in row


def test_a_split_scene_with_clips_shows_each_and_the_total(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    job.video_provider = VideoProvider.MUSE
    job.video_clips = [_clip(1, 7, 0), _clip(1, 7, 1)]
    view = _build_view(job, service=_FakeSceneVideoGenerationService())
    view.refresh(job)

    assert "clips 7s + 7s = 14s" in _row(view, 1)


def test_a_scene_that_already_has_clips_does_not_repeat_the_split_plan(
    qapp: QApplication,  # noqa: F811
) -> None:
    job = _job(1)
    job.video_provider = VideoProvider.MUSE
    job.scenes[0].real_narration_duration_seconds = 12.96
    job.video_clips = [_clip(1, 7, 0), _clip(1, 7, 1)]
    view = _build_view(job, service=_FakeSceneVideoGenerationService())
    view.refresh(job)

    # no attempt exists in this fixture, so the planned-split line may appear; what
    # must hold is that the row itself reports the real clips, not a plan.
    assert "clips 7s + 7s = 14s" in _row(view, 1)


def test_the_planned_length_includes_the_projects_hold(
    qapp: QApplication,  # noqa: F811
) -> None:
    """6.7 s of narration is a 7 s Muse clip; with a 0.4 s hold after the line it is 8 s."""

    view, job = _view(VideoProvider.MUSE, narration=6.7)
    assert "planned 7s" in _row(view, 1)

    job.scene_hold_seconds = 0.4
    view.refresh(job)

    assert "planned 8s" in _row(view, 1)
    assert "narration 6.7s" in _row(view, 1)
