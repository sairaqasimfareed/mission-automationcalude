"""Changing the video shape of an existing project (2026-10-24)."""

from __future__ import annotations

from src.models.specification_enums import AspectRatio
from src.models.video_job import VideoJob
from src.services.video_shape_service import change_video_shape, resolution_for_shape


def _job() -> VideoJob:
    return VideoJob(
        project_name="Radium",
        channel_name="Channel",
        niche="history",
        topic="Radium",
    )


def test_a_resolution_is_turned_only_when_its_orientation_is_the_other_way() -> None:
    assert resolution_for_shape("1920x1080", AspectRatio.PORTRAIT) == "1080x1920"
    assert resolution_for_shape("1280x720", AspectRatio.PORTRAIT) == "720x1280"
    assert resolution_for_shape("1080x1920", AspectRatio.LANDSCAPE) == "1920x1080"
    assert resolution_for_shape("1080x1920", AspectRatio.PORTRAIT) == "1080x1920"
    assert resolution_for_shape("1920x1080", AspectRatio.LANDSCAPE) == "1920x1080"
    assert resolution_for_shape("garbage", AspectRatio.PORTRAIT) == "garbage"
    assert resolution_for_shape("1080x1080", AspectRatio.PORTRAIT) == "1080x1080"


def test_changing_to_vertical_sets_the_shape_and_the_size_and_flags_the_render() -> (
    None
):
    from src.models.video_timeline import VideoTimeline

    job = _job()
    job.video_timeline = VideoTimeline(output_resolution="1920x1080")

    assert change_video_shape(job, AspectRatio.PORTRAIT) is True
    assert job.aspect_ratio == AspectRatio.PORTRAIT
    assert job.output_resolution == "1080x1920"
    assert job.nominal_clip_resolution == "1080x1920"
    assert any(r.artifact == "video_timeline" for r in job.stale_artifacts)


def test_choosing_the_shape_it_already_has_changes_nothing() -> None:
    job = _job()

    assert change_video_shape(job, AspectRatio.LANDSCAPE) is False
    assert job.stale_artifacts == []
    assert job.output_resolution == "1920x1080"


def test_a_plain_string_shape_is_stored_as_the_enum() -> None:
    job = _job()

    change_video_shape(job, "9:16")  # type: ignore[arg-type]

    assert type(job.aspect_ratio) is AspectRatio
