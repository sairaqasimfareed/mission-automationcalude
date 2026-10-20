"""Use a video edited outside the app as the project's finished video."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.models.enums import JobStatus, WorkflowStage
from src.models.media_technical_validation import MediaTechnicalValidationResult
from src.models.render_result import RenderResult, RenderStatus
from src.models.video_job import VideoJob
from src.services.edited_video_service import (
    EditedVideoService,
    edited_video_in_use,
)
from src.services.subtitle_burn_action_service import SubtitleBurnActionService


class _FakeValidation:
    def __init__(self, *, duration: float = 88.0, video: bool = True) -> None:
        self._duration = duration
        self._video = video

    def validate(self, file_path: Path) -> MediaTechnicalValidationResult:
        return MediaTechnicalValidationResult(
            is_readable=file_path.is_file(),
            duration_seconds=self._duration,
            has_video_stream=self._video,
            has_audio_stream=True,
        )


def _job(output: Path) -> VideoJob:
    job = VideoJob(
        project_name="P",
        channel_name="C",
        niche="n",
        topic="t",
        status=JobStatus.COMPLETED,
        current_stage=WorkflowStage.READY_FOR_UPLOAD,
    )
    job.render_result = RenderResult(
        success=True,
        status=RenderStatus.COMPLETED,
        output_file=output.as_posix(),
        render_engine="ffmpeg",
        duration_seconds=80,
    )

    return job


def _files(tmp_path: Path) -> tuple[Path, Path]:
    output = tmp_path / "final_video.mp4"
    output.write_bytes(b"the app's own render")
    edited = tmp_path / "capcut_export.mp4"
    edited.write_bytes(b"the video edited in capcut, longer than the render")

    return output, edited


def _service(**kwargs: object) -> EditedVideoService:
    return EditedVideoService(media_validation_service=_FakeValidation(**kwargs))  # type: ignore[arg-type]


def test_the_edited_video_takes_the_renders_place_and_the_original_is_kept(
    tmp_path: Path,
) -> None:
    output, edited = _files(tmp_path)
    job = _job(output)

    updated = _service().use_edited_video(job, str(edited))

    assert output.read_bytes() == edited.read_bytes()
    assert (
        tmp_path / "final_video_app_original.mp4"
    ).read_bytes() == b"the app's own render"
    assert (tmp_path / "final_video_edited.mp4").read_bytes() == edited.read_bytes()
    assert updated.duration_seconds == 88
    assert job.render_result is not None and job.render_result.duration_seconds == 88
    assert edited_video_in_use(job) is True


def test_a_second_edited_video_does_not_replace_the_kept_app_render(
    tmp_path: Path,
) -> None:
    output, edited = _files(tmp_path)
    job = _job(output)
    service = _service()
    service.use_edited_video(job, str(edited))
    second = tmp_path / "second.mp4"
    second.write_bytes(b"a second edit")

    service.use_edited_video(job, str(second))

    assert (
        tmp_path / "final_video_app_original.mp4"
    ).read_bytes() == b"the app's own render"
    assert output.read_bytes() == b"a second edit"


def test_a_new_render_ends_the_edited_state_but_the_edited_copy_survives(
    tmp_path: Path,
) -> None:
    output, edited = _files(tmp_path)
    job = _job(output)
    _service().use_edited_video(job, str(edited))

    output.write_bytes(
        b"a brand new app render"
    )  # what a re-render does to final_video.mp4

    assert edited_video_in_use(job) is False
    assert (tmp_path / "final_video_edited.mp4").read_bytes() == edited.read_bytes()


def test_the_apps_own_render_can_be_brought_back(tmp_path: Path) -> None:
    output, edited = _files(tmp_path)
    job = _job(output)
    service = _service(duration=80.0)
    service.use_edited_video(job, str(edited))

    service.restore_app_render(job)

    assert output.read_bytes() == b"the app's own render"
    assert edited_video_in_use(job) is False
    assert job.edited_video_path is None


def test_a_missing_or_unreadable_file_is_refused_and_nothing_changes(
    tmp_path: Path,
) -> None:
    output, _edited = _files(tmp_path)
    job = _job(output)

    with pytest.raises(ValueError, match="could not be found"):
        _service().use_edited_video(job, str(tmp_path / "nope.mp4"))

    not_video = tmp_path / "audio.mp4"
    not_video.write_bytes(b"x")

    with pytest.raises(ValueError, match="read as a video"):
        _service(video=False).use_edited_video(job, str(not_video))

    assert output.read_bytes() == b"the app's own render"
    assert not (tmp_path / "final_video_app_original.mp4").exists()


def test_it_needs_a_finished_render_first(tmp_path: Path) -> None:
    job = VideoJob(project_name="P", channel_name="C", niche="n", topic="t")
    edited = tmp_path / "e.mp4"
    edited.write_bytes(b"x")

    with pytest.raises(ValueError, match="Render the video first"):
        _service().use_edited_video(job, str(edited))


def test_burning_the_apps_subtitles_is_skipped_while_the_edited_video_is_in_use(
    tmp_path: Path,
) -> None:
    from src.models.absolute_subtitle_cue import AbsoluteSubtitleCue

    output, edited = _files(tmp_path)
    job = _job(output)
    assert job.render_result is not None
    job.render_result = job.render_result.model_copy(
        update={
            "subtitle_cues": [
                AbsoluteSubtitleCue(text="a line", start_seconds=0.0, end_seconds=1.0)
            ]
        }
    )

    assert SubtitleBurnActionService.unavailable_reason(job) is None

    _service().use_edited_video(job, str(edited))

    reason = SubtitleBurnActionService.unavailable_reason(job)
    assert reason is not None and "edited video is in use" in reason


def test_mtimes_survive_the_copies_so_the_in_use_check_is_stable(
    tmp_path: Path,
) -> None:
    output, edited = _files(tmp_path)
    os.utime(edited, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    job = _job(output)

    _service().use_edited_video(job, str(edited))

    assert output.stat().st_mtime_ns == edited.stat().st_mtime_ns
