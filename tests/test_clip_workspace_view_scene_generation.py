from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Iterator  # noqa: E402
from unittest.mock import patch  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.desktop.views.clip_workspace_view import ClipWorkspaceView  # noqa: E402
from src.models.asset_index import AssetIndex  # noqa: E402
from src.models.google_flow_generation import (  # noqa: E402
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
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


def _stuck_attempt(scene_number: int) -> GoogleFlowGenerationAttempt:
    request = GoogleFlowGenerationRequest(
        scene_number=scene_number,
        prompt="A prompt.",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key=f"key-{scene_number}",
    )
    attempt = GoogleFlowGenerationAttempt(request=request, profile_id="flow.primary")

    return attempt.with_transition(
        GoogleFlowGenerationState.AUTH_REQUIRED,
        detail="Flow shows no sign of an authenticated session.",
    )


class _FakeJobStore:
    def __init__(self, job: VideoJob) -> None:
        self._job = job
        self.added: list[VideoJob] = []

    def get(self, job_id: UUID) -> VideoJob | None:
        return self._job if job_id == self._job.id else None

    def add(self, job: VideoJob) -> None:
        self.added.append(job)


class _FakeSceneVideoGenerationService:
    """
    Duck-typed stand-in for SceneVideoGenerationService: instant,
    in-process "generation" that attaches a real-shaped VideoClip
    directly, so these tests exercise the view/worker/threading wiring
    without a real Google Flow provider or any real waiting.
    """

    def __init__(self, *, fail_on_scene: int | None = None) -> None:
        self.generate_one_calls: list[int] = []
        self.generate_all_calls = 0
        self.retry_scene_after_auth_calls: list[int] = []
        self._fail_on_scene = fail_on_scene

    def retry_scene_after_auth(self, job: VideoJob, scene_number: int) -> None:
        self.retry_scene_after_auth_calls.append(scene_number)

        # A resumed, now-successful attempt: attach a clip and drop the
        # stuck ledger entry, same real end state generate_one() itself
        # leaves behind on success.
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
        job.flow_generation_attempts = [
            attempt
            for attempt in job.flow_generation_attempts
            if attempt.request.scene_number != scene_number
        ]

    def generate_one(self, job: VideoJob, scene_number: int) -> None:
        if scene_number == self._fail_on_scene:
            self.generate_one_calls.append(scene_number)
            raise RuntimeError(f"Simulated failure on scene {scene_number}.")

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

    def generate_all(
        self,
        job: VideoJob,
        *,
        on_scene_complete: Callable[[VideoJob, int], None] | None = None,
    ) -> None:
        self.generate_all_calls += 1

        for scene in job.scenes:
            self.generate_one(job, scene.scene_number)

            if on_scene_complete is not None:
                on_scene_complete(job, scene.scene_number)


def _asset_workflow_service() -> SceneAssetWorkflowService:
    return SceneAssetWorkflowService(
        asset_manager=AssetManager(
            local_search_service=LocalAssetSearchService(asset_source=AssetIndex())
        ),
        decision_service=AssetDecisionService(),
        asset_search_service=AssetSearchService(),
    )


def _build_view(
    job: VideoJob,
    *,
    service: _FakeSceneVideoGenerationService | None,
    job_store: _FakeJobStore | None = None,
) -> ClipWorkspaceView:
    view = ClipWorkspaceView(
        job_store=job_store or _FakeJobStore(job),  # type: ignore[arg-type]
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


def test_generate_all_persists_progress_after_every_scene(
    qapp: QApplication,
) -> None:
    """
    Each completed scene must reach the job store as it finishes, not
    only once the whole batch is done - otherwise a crash partway
    through a real, multi-minute batch loses every already-completed
    scene's work (the real bug this checkpointing fixes).
    """

    job = _job(1, 2, 3)
    service = _FakeSceneVideoGenerationService()
    store = _FakeJobStore(job)
    view = _build_view(job, service=service, job_store=store)

    all_button = next(
        b for b in _find_buttons(view) if b.text() == "Generate all scenes"
    )
    all_button.click()

    thread, _worker = next(iter(view._generation_threads.values()))
    thread.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert service.generate_all_calls == 1
    # One add() per completed scene, plus the final "batch finished" save.
    assert len(store.added) >= 3
    assert len(store.added[0].video_clips) == 1
    assert len(store.added[-1].video_clips) == 3


def test_generate_all_keeps_earlier_scene_progress_when_a_later_scene_fails(
    qapp: QApplication,
) -> None:
    """
    Reproduces the real-world failure this fix targets: scene 3 fails
    partway through a 3-scene "Generate All" run. Scenes 1 and 2's
    real work must still have reached the job store, not be silently
    lost because nothing persisted until the batch finished.
    """

    job = _job(1, 2, 3)
    service = _FakeSceneVideoGenerationService(fail_on_scene=3)
    store = _FakeJobStore(job)
    view = _build_view(job, service=service, job_store=store)

    all_button = next(
        b for b in _find_buttons(view) if b.text() == "Generate all scenes"
    )

    # A real failure here routes into show_recoverable_error(), a real
    # QMessageBox.exec() that blocks forever under headless
    # (offscreen) Qt with no button click ever arriving - not slow,
    # a genuine permanent hang. Monkeypatched out so this test
    # exercises the persistence fix, not a real dialog.
    with patch("src.desktop.views.clip_workspace_view.show_recoverable_error"):
        all_button.click()

        thread, _worker = next(iter(view._generation_threads.values()))
        thread.wait(2000)
        for _ in range(20):
            qapp.processEvents()

    assert service.generate_one_calls == [1, 2, 3]
    assert store.added, "scenes 1 and 2 must have been checkpointed"

    scene_numbers_seen = {
        clip.scene_number for snapshot in store.added for clip in snapshot.video_clips
    }
    assert scene_numbers_seen == {1, 2}

    assert any("Simulated failure on scene 3" in error for error in job.errors)


def test_shows_retry_after_login_for_a_scene_stuck_on_auth_required(
    qapp: QApplication,
) -> None:
    job = _job(1, 2)
    job.flow_generation_attempts = [_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    buttons_by_text = [b.text() for b in _find_buttons(view)]

    # Scene 1 (stuck) shows the recovery action, not the ordinary one;
    # scene 2 (untouched) is unaffected.
    assert buttons_by_text.count("Retry after login") == 1
    assert buttons_by_text.count("Generate") == 1


def test_clicking_retry_after_login_resumes_the_stuck_scene(
    qapp: QApplication,
) -> None:
    job = _job(1)
    job.flow_generation_attempts = [_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    retry_button = next(
        b for b in _find_buttons(view) if b.text() == "Retry after login"
    )
    retry_button.click()

    thread, _worker = next(iter(view._generation_threads.values()))
    thread.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert service.retry_scene_after_auth_calls == [1]
    assert service.generate_one_calls == []  # the recovery path, not the normal one
    assert job.video_clips
    assert job.video_clips[0].scene_number == 1
    assert job.flow_generation_attempts == []  # the stuck entry was cleared

    # A fresh view built from this now-resolved job state (rather than
    # reusing the existing one, whose old button widgets are only
    # scheduled for deletion via Qt's deleteLater() and not reliably
    # gone by the next processEvents() pump) shows no recovery button.
    resolved_view = _build_view(job, service=service)
    assert not any(
        b.text() == "Retry after login" for b in _find_buttons(resolved_view)
    )
