from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.quality_center_view import QualityCenterView  # noqa: E402
from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.video_clip import VideoClip, VideoClipStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _job() -> VideoJob:
    return VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )


def _scene(scene_number: int, *, duration_seconds: int) -> Scene:
    return Scene(
        scene_number=scene_number,
        title=f"Scene {scene_number}",
        narration="Narration text.",
        visual_prompt="A visual prompt.",
        estimated_duration_seconds=duration_seconds,
    )


def _clip(scene_number: int, *, duration_seconds: int) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=duration_seconds,
        local_file="/downloads/clip.mp4",
        status=VideoClipStatus.READY,
    )


def test_duration_mismatch_card_builds_without_error_for_a_bare_job(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)
    view.refresh(job)  # must not raise


def test_duration_mismatch_card_shows_no_mismatches_when_clip_matches_plan(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.scenes = [_scene(1, duration_seconds=8)]
    job.video_clips = [_clip(1, duration_seconds=8)]
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)
    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("No duration mismatches" in text for text in labels)


def test_duration_mismatch_card_shows_a_real_scene_mismatch(qapp: QApplication) -> None:
    """
    Real-world finding this session: a scene planned at 18s whose real
    Google Flow clip was clamped to 8s used to go completely unnoticed
    anywhere in the app - proves the fix all the way through the real
    widget tree, not just at the DurationMismatchPolicyService layer.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job.scenes = [_scene(1, duration_seconds=18)]
    job.video_clips = [_clip(1, duration_seconds=8)]
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)
    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("Scene 1" in text for text in labels)
    assert any("Planned 18s" in text and "actual 8s" in text for text in labels)
    # A 10s gap on an 18s scene exceeds the service's own 50% severe
    # ratio, so it's BLOCK, not a silently-applied TRIM/HOLD_LAST_FRAME.
    assert any("Blocked" in text for text in labels)


def test_duration_mismatch_card_shows_a_small_post_ceiling_fix_mismatch(
    qapp: QApplication,
) -> None:
    """
    The scene-planner 8s ceiling fix means new scenes only ever drift
    by the small amount Flow's own clamp introduces (nearest of
    4/6/8s) - a much smaller gap than the pre-fix example above, and
    small enough to stay a TRIM/HOLD_LAST_FRAME recommendation rather
    than BLOCK.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job.scenes = [_scene(1, duration_seconds=6)]
    job.video_clips = [_clip(1, duration_seconds=8)]
    job_store.add(job)

    view = QualityCenterView(job_store=job_store, on_change=lambda: None)
    view.set_job(job.id)
    view.refresh(job)

    labels = [label.text() for label in view.findChildren(QLabel)]

    assert any("Planned 6s" in text and "actual 8s" in text for text in labels)
    assert any("Trim narration" in text for text in labels)
