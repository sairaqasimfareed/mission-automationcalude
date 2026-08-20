from __future__ import annotations

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.final_preview import FinalPreviewAction, FinalPreviewStatus
from src.models.media_strategy import SceneSourceType
from src.models.render_result import RenderResult
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import VideoTimelineItem
from src.services.final_preview_service import FinalPreviewService
from src.services.invalidation_service import InvalidationService


def _job(**overrides: object) -> VideoJob:
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )

    for field_name, value in overrides.items():
        setattr(job, field_name, value)

    return job


def _clip(local_file: str = "clip.mp4") -> VideoClip:
    return VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=5,
        local_file=local_file,
    )


def _video_timeline(*, local_file: str = "clip.mp4") -> VideoTimeline:
    return VideoTimeline(
        items=[
            VideoTimelineItem(
                clip=_clip(local_file=local_file),
                scene_number=1,
                start_time_seconds=0.0,
                end_time_seconds=5.0,
            )
        ]
    )


def _audio_timeline() -> AudioTimeline:
    return AudioTimeline(
        tracks=[
            AudioTrack(
                track_type=AudioTrackType.VOICEOVER,
                source_file="voice.mp3",
                start_time_seconds=0.0,
                duration_seconds=5.0,
            )
        ]
    )


def _rendered_job(*, local_file: str = "clip.mp4") -> VideoJob:
    return _job(
        video_timeline=_video_timeline(local_file=local_file),
        audio_timeline=_audio_timeline(),
        render_result=RenderResult(
            success=True, render_engine="ffmpeg", output_file="out.mp4"
        ),
    )


def test_create_preview_requires_a_successful_render() -> None:
    job = _job(render_result=RenderResult(success=False, render_engine="ffmpeg"))

    with pytest.raises(RuntimeError, match="requires a successful render"):
        FinalPreviewService().create_preview(job)


def test_create_preview_wraps_a_missing_timeline_as_a_runtime_error() -> None:
    # RenderIdentityService.compute() raises ValueError for a missing
    # timeline; create_preview must present a single RuntimeError
    # contract to its own callers rather than leaking that type.
    job = _job(
        render_result=RenderResult(
            success=True, render_engine="ffmpeg", output_file="out.mp4"
        )
    )

    with pytest.raises(RuntimeError, match="requires a built video timeline"):
        FinalPreviewService().create_preview(job)


def test_create_preview_requires_an_output_file() -> None:
    job = _job(
        video_timeline=_video_timeline(),
        audio_timeline=_audio_timeline(),
        render_result=RenderResult(success=True, render_engine="ffmpeg"),
    )

    with pytest.raises(RuntimeError, match="requires a render output file"):
        FinalPreviewService().create_preview(job)


def test_create_preview_appends_a_pending_record() -> None:
    job = _rendered_job()
    service = FinalPreviewService()

    preview = service.create_preview(job)

    assert preview.status == FinalPreviewStatus.PENDING
    assert preview.output_file == "out.mp4"
    assert job.final_previews == [preview]
    assert len(preview.render_identity) == 64


def test_resolve_approve_final_marks_approved() -> None:
    job = _rendered_job()
    service = FinalPreviewService()
    service.create_preview(job)

    resolved = service.resolve(job, FinalPreviewAction.APPROVE_FINAL)

    assert resolved.status == FinalPreviewStatus.APPROVED
    assert resolved.action == FinalPreviewAction.APPROVE_FINAL
    assert len(job.final_previews) == 2  # pending record preserved


@pytest.mark.parametrize(
    "action",
    [
        FinalPreviewAction.RETURN_TO_EDITING,
        FinalPreviewAction.REPLACE_SCENE,
        FinalPreviewAction.REGENERATE_AUDIO,
    ],
)
def test_resolve_editing_actions_mark_returned_to_editing(
    action: FinalPreviewAction,
) -> None:
    job = _rendered_job()
    service = FinalPreviewService()
    service.create_preview(job)

    resolved = service.resolve(job, action)

    assert resolved.status == FinalPreviewStatus.RETURNED_TO_EDITING
    assert resolved.action == action


def test_resolve_raises_when_no_preview_exists() -> None:
    job = _rendered_job()
    service = FinalPreviewService()

    with pytest.raises(ValueError, match="No final preview exists"):
        service.resolve(job, FinalPreviewAction.APPROVE_FINAL)


def test_resolve_raises_when_latest_preview_already_resolved() -> None:
    job = _rendered_job()
    service = FinalPreviewService()
    service.create_preview(job)
    service.resolve(job, FinalPreviewAction.APPROVE_FINAL)

    with pytest.raises(ValueError, match="not pending"):
        service.resolve(job, FinalPreviewAction.APPROVE_FINAL)


def test_is_current_false_when_no_preview_exists() -> None:
    job = _rendered_job()

    assert FinalPreviewService().is_current(job) is False


def test_is_current_true_immediately_after_creation() -> None:
    job = _rendered_job()
    service = FinalPreviewService()
    service.create_preview(job)

    assert service.is_current(job) is True


def test_is_current_false_after_the_render_inputs_change() -> None:
    job = _rendered_job(local_file="clip_a.mp4")
    service = FinalPreviewService()
    service.create_preview(job)

    job.video_timeline = _video_timeline(local_file="clip_b.mp4")

    assert service.is_current(job) is False


def test_is_current_false_when_render_result_is_flagged_stale() -> None:
    job = _rendered_job()
    service = FinalPreviewService()
    service.create_preview(job)

    InvalidationService().on_scene_replaced(job, scene_number=1)

    assert service.is_current(job) is False


def test_latest_preview_returns_none_before_any_preview() -> None:
    job = _rendered_job()

    assert FinalPreviewService.latest_preview(job) is None


def test_latest_preview_returns_the_most_recent_record() -> None:
    job = _rendered_job()
    service = FinalPreviewService()
    service.create_preview(job)
    resolved = service.resolve(job, FinalPreviewAction.APPROVE_FINAL)

    assert FinalPreviewService.latest_preview(job) is resolved
