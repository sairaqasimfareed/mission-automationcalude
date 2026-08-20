from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.quality_center_view import QualityCenterView  # noqa: E402
from src.models.audio_timeline import AudioTimeline  # noqa: E402
from src.models.audio_track import AudioTrack, AudioTrackType  # noqa: E402
from src.models.final_preview import (
    FinalPreviewAction,
    FinalPreviewStatus,
)  # noqa: E402
from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.render_result import RenderResult  # noqa: E402
from src.models.video_clip import VideoClip  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.video_timeline import VideoTimeline  # noqa: E402
from src.models.video_timeline_item import VideoTimelineItem  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.desktop.views.quality_center_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )


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


def _clip() -> VideoClip:
    return VideoClip(
        scene_number=1,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=5,
        local_file="clip.mp4",
    )


def _rendered_job() -> VideoJob:
    return _job(
        video_timeline=VideoTimeline(
            items=[
                VideoTimelineItem(
                    clip=_clip(),
                    scene_number=1,
                    start_time_seconds=0.0,
                    end_time_seconds=5.0,
                )
            ]
        ),
        audio_timeline=AudioTimeline(
            tracks=[
                AudioTrack(
                    track_type=AudioTrackType.VOICEOVER,
                    source_file="voice.mp3",
                    start_time_seconds=0.0,
                    duration_seconds=5.0,
                )
            ]
        ),
        render_result=RenderResult(
            success=True, render_engine="ffmpeg", output_file="out.mp4"
        ),
    )


def _view(job_store: InMemoryJobStore) -> QualityCenterView:
    return QualityCenterView(job_store=job_store, on_change=lambda: None)


def test_final_preview_card_builds_without_error_before_any_render(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise


def test_create_final_preview_appends_a_pending_record(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _rendered_job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_create_final_preview()

    assert len(job.final_previews) == 1
    assert job.final_previews[0].status == FinalPreviewStatus.PENDING

    view.refresh(job)  # must not raise with a pending preview present


def test_resolve_approve_final_marks_the_preview_approved(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _rendered_job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_create_final_preview()
    view._handle_resolve_final_preview(FinalPreviewAction.APPROVE_FINAL)

    assert job.final_previews[-1].status == FinalPreviewStatus.APPROVED
    assert not job.errors

    view.refresh(job)  # must not raise with an approved preview present


def test_resolve_return_to_editing_marks_the_preview_returned(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _rendered_job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_create_final_preview()
    view._handle_resolve_final_preview(FinalPreviewAction.RETURN_TO_EDITING)

    assert job.final_previews[-1].status == FinalPreviewStatus.RETURNED_TO_EDITING


def test_creating_a_preview_without_timelines_records_an_error_not_a_crash(
    qapp: QApplication,
) -> None:
    # render_result.success can be true without either timeline being
    # set (e.g. a render triggered independently of this GUI) -
    # RenderIdentityService raises ValueError for that, which must
    # surface as a recorded error, not an unhandled exception.
    job_store = InMemoryJobStore()
    job = _job(
        render_result=RenderResult(
            success=True, render_engine="ffmpeg", output_file="out.mp4"
        )
    )
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_create_final_preview()

    assert job.final_previews == []
    assert len(job.errors) == 1
    assert "Could not create final preview" in job.errors[0]


def test_resolving_with_no_pending_preview_records_an_error_not_a_crash(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _rendered_job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_resolve_final_preview(FinalPreviewAction.APPROVE_FINAL)

    assert len(job.errors) == 1
    assert "Could not resolve final preview" in job.errors[0]


def test_unknown_job_id_does_not_crash_final_preview_handlers(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)
    view.set_job(uuid4())

    view._handle_create_final_preview()  # must not raise
    view._handle_resolve_final_preview(
        FinalPreviewAction.APPROVE_FINAL
    )  # must not raise
