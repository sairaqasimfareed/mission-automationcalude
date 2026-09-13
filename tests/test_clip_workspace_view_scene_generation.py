from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.desktop.views.clip_workspace_view import ClipWorkspaceView  # noqa: E402
from src.models.asset_index import AssetIndex  # noqa: E402
from src.models.media_strategy import SceneSourceStatus, SceneSourceType  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.video_clip import VideoClip, VideoClipStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.asset_decision_service import AssetDecisionService  # noqa: E402
from src.services.asset_manager import AssetManager  # noqa: E402
from src.services.asset_search_service import AssetSearchService  # noqa: E402
from src.services.local_asset_search_service import (  # noqa: E402
    LocalAssetSearchService,
)
from src.services.scene_asset_workflow_service import (  # noqa: E402
    SceneAssetWorkflowService,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _scene(number: int) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration for scene {number}.",
        visual_prompt=f"Visual prompt for scene {number}.",
        estimated_duration_seconds=8,
    )


def _job(*scene_numbers: int) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
        genre_id="genre.horror",
    )
    job.scenes = [_scene(number) for number in scene_numbers]
    return job


class _FakeJobStore:
    def __init__(self, job: VideoJob) -> None:
        self._job = job

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._job if job_id == self._job.id else None


class _FakeSceneVideoGenerationService:
    """
    Duck-typed stand-in for SceneVideoGenerationService: instant,
    in-process "generation" that attaches a real-shaped VideoClip
    directly, so these tests exercise the view/worker/threading wiring
    without a real Google Flow provider or any real waiting.
    """

    def __init__(self) -> None:
        self.generate_one_calls: list[int] = []
        self.generate_all_calls = 0

    def generate_one(self, job: VideoJob, scene_number: int) -> None:
        self.generate_one_calls.append(scene_number)
        job.video_clips = [
            clip for clip in job.video_clips if clip.scene_number != scene_number
        ] + [
            VideoClip(
                scene_number=scene_number,
                source_type=SceneSourceType.AI_GENERATE,
                duration_seconds=8,
                local_file=f"downloads/scene_{scene_number}.mp4",
                source_status=SceneSourceStatus.READY,
                status=VideoClipStatus.READY,
            )
        ]

    def generate_all(self, job: VideoJob) -> None:
        self.generate_all_calls += 1

        for scene in job.scenes:
            self.generate_one(job, scene.scene_number)


def _asset_workflow_service() -> SceneAssetWorkflowService:
    return SceneAssetWorkflowService(
        asset_manager=AssetManager(
            local_search_service=LocalAssetSearchService(asset_source=AssetIndex())
        ),
        decision_service=AssetDecisionService(),
        asset_search_service=AssetSearchService(),
    )


def _build_view(
    job: VideoJob, *, service: _FakeSceneVideoGenerationService | None
) -> ClipWorkspaceView:
    view = ClipWorkspaceView(
        job_store=_FakeJobStore(job),  # type: ignore[arg-type]
        asset_workflow_service=_asset_workflow_service(),
        on_change=lambda: None,
        scene_video_generation_service=service,  # type: ignore[arg-type]
    )
    view.set_job(job.id)
    view.refresh(job)

    return view


def _find_buttons(view: ClipWorkspaceView) -> list[QPushButton]:
    return view.findChildren(QPushButton)


def test_shows_not_configured_message_without_a_service(qapp: QApplication) -> None:
    job = _job(1)
    view = _build_view(job, service=None)

    assert not any(
        button.text() in ("Generate", "Regenerate", "Generate all scenes")
        for button in _find_buttons(view)
    )


def test_shows_generate_button_per_scene_with_a_service(qapp: QApplication) -> None:
    job = _job(1, 2)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    generate_buttons = [b for b in _find_buttons(view) if b.text() == "Generate"]
    assert len(generate_buttons) == 2

    all_button = next(
        b for b in _find_buttons(view) if b.text() == "Generate all scenes"
    )
    assert all_button.isEnabled()


def test_clicking_generate_runs_the_worker_and_attaches_a_clip(
    qapp: QApplication,
) -> None:
    job = _job(1)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    generate_button = next(b for b in _find_buttons(view) if b.text() == "Generate")
    generate_button.click()

    # The worker runs on a real QThread - pump the event loop until its
    # queued finished signal (and the resulting refresh) is delivered.
    thread, _worker = next(iter(view._generation_threads.values()))
    thread.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert service.generate_one_calls == [1]
    assert job.video_clips
    assert job.video_clips[0].scene_number == 1
    assert job.video_clips[0].source_type == SceneSourceType.AI_GENERATE


def test_clicking_generate_all_processes_every_scene(qapp: QApplication) -> None:
    job = _job(1, 2)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    all_button = next(
        b for b in _find_buttons(view) if b.text() == "Generate all scenes"
    )
    all_button.click()

    thread, _worker = next(iter(view._generation_threads.values()))
    thread.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert service.generate_all_calls == 1
    assert len(job.video_clips) == 2
