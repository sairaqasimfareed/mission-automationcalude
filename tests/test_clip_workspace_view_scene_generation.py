from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QLabel,
    QMessageBox,
    QPushButton,
)

from src.desktop.views.clip_workspace_view import ClipWorkspaceView  # noqa: E402
from src.models.asset_index import AssetIndex  # noqa: E402
from src.models.google_flow_generation import (  # noqa: E402
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.media_strategy import SceneSourceStatus, SceneSourceType  # noqa: E402
from src.models.muse_generation import (  # noqa: E402
    MuseGenerationAttempt,
    MuseGenerationRequest,
    MuseGenerationState,
)
from src.models.provider_profile import (  # noqa: E402
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.scene import Scene  # noqa: E402
from src.models.video_clip import VideoClip, VideoClipStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.services.asset_decision_service import AssetDecisionService  # noqa: E402
from src.services.asset_manager import AssetManager  # noqa: E402
from src.services.asset_search_service import AssetSearchService  # noqa: E402
from src.services.asset_storage_service import AssetStorageService  # noqa: E402
from src.services.google_flow_generation_orchestrator_service import (  # noqa: E402
    GoogleFlowAttemptCreditSensitiveError,
)
from src.services.local_asset_search_service import (  # noqa: E402
    LocalAssetSearchService,
)
from src.services.manual_upload_service import ManualUploadService  # noqa: E402
from src.services.registry.provider_registry import ProviderRegistry  # noqa: E402
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


def _ui_changed_stuck_attempt(scene_number: int) -> GoogleFlowGenerationAttempt:
    request = GoogleFlowGenerationRequest(
        scene_number=scene_number,
        prompt="A prompt.",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key=f"key-{scene_number}",
    )
    attempt = GoogleFlowGenerationAttempt(request=request, profile_id="flow.primary")

    return attempt.with_transition(
        GoogleFlowGenerationState.UI_CHANGED,
        detail="Flow's real UI no longer matches expectations.",
    )


def _split_scene_attempts(scene_number: int) -> list[GoogleFlowGenerationAttempt]:
    """Two sub-clip attempts for the same scene, distinguished by
    clip_sequence_index - both terminal via a one-hop interrupt-state
    transition, matching _stuck_attempt/_ui_changed_stuck_attempt's own
    simple construction pattern (no need for the full forward chain a
    READY/GENERATING state would require)."""

    attempts = []

    for index, state in (
        (0, GoogleFlowGenerationState.FAILED),
        (1, GoogleFlowGenerationState.UI_CHANGED),
    ):
        request = GoogleFlowGenerationRequest(
            scene_number=scene_number,
            clip_sequence_index=index,
            prompt="A prompt.",
            prompt_version="v1",
            profile_id="flow.primary",
            idempotency_key=f"key-{scene_number}-{index}",
        )
        attempt = GoogleFlowGenerationAttempt(
            request=request, profile_id="flow.primary"
        ).with_transition(state, detail="Simulated for the split-scene test.")
        attempts.append(attempt)

    return attempts


def _muse_planned_orphan_attempt(scene_number: int) -> MuseGenerationAttempt:
    """
    A Muse attempt that never got past PLANNED - the real shape
    submit() leaves behind when it raises before ever reaching
    replace_attempt() (e.g. the TargetClosedError bug this session
    found and fixed). Real-world finding, 2026-09-29: before this
    scene's _other_stuck_attempt() checked job.muse_generation_attempts
    too, a scene stuck like this showed a plain "Generate" button that
    silently did nothing - the same recovery path only ever worked for
    a stuck job.flow_generation_attempts entry.
    """

    request = MuseGenerationRequest(
        scene_number=scene_number,
        prompt="A prompt.",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"muse-key-{scene_number}",
    )

    return MuseGenerationAttempt(request=request, profile_id="muse.primary")


def _muse_auth_required_attempt(scene_number: int) -> MuseGenerationAttempt:
    request = MuseGenerationRequest(
        scene_number=scene_number,
        prompt="A prompt.",
        prompt_version="v1",
        profile_id="muse.primary",
        idempotency_key=f"muse-key-{scene_number}",
    )
    attempt = MuseGenerationAttempt(request=request, profile_id="muse.primary")

    return attempt.with_transition(
        MuseGenerationState.AUTH_REQUIRED,
        detail="Muse shows no sign of an authenticated session.",
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

    def __init__(
        self,
        *,
        fail_on_scene: int | None = None,
        raise_credit_sensitive_on_scene: int | None = None,
    ) -> None:
        self.generate_one_calls: list[int] = []
        self.generate_all_calls = 0
        self.generate_all_forced_profile_id: str | None = None
        self.retry_scene_after_auth_calls: list[int] = []
        self.abandon_stuck_attempt_calls: list[tuple[int, bool]] = []
        self._fail_on_scene = fail_on_scene
        self._raise_credit_sensitive_on_scene = raise_credit_sensitive_on_scene

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

    def abandon_stuck_attempt(
        self, job: VideoJob, scene_number: int, *, force: bool = False
    ) -> None:
        self.abandon_stuck_attempt_calls.append((scene_number, force))

        if self._raise_credit_sensitive_on_scene == scene_number and not force:
            stuck = next(
                attempt
                for attempt in job.flow_generation_attempts
                if attempt.request.scene_number == scene_number
            )
            raise GoogleFlowAttemptCreditSensitiveError(stuck)

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
        forced_profile_id: str | None = None,
        on_scene_complete: Callable[[VideoJob, int], None] | None = None,
    ) -> None:
        self.generate_all_calls += 1
        self.generate_all_forced_profile_id = forced_profile_id

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


def _asset_workflow_service_with_manual_upload(
    tmp_path: Path,
) -> SceneAssetWorkflowService:
    """
    Same as _asset_workflow_service(), plus a real ManualUploadService -
    needed only by the per-scene "Upload..." button tests, which
    exercise the actual manual-upload path (apply_decision() fails
    validation with no manual_upload_service configured at all).
    """

    index = AssetIndex()
    storage_service = AssetStorageService(
        storage_root=tmp_path / "project-assets", asset_index=index
    )

    return SceneAssetWorkflowService(
        asset_manager=AssetManager(local_search_service=LocalAssetSearchService(index)),
        decision_service=AssetDecisionService(),
        asset_search_service=AssetSearchService(),
        manual_upload_service=ManualUploadService(
            storage_service=storage_service, maximum_file_size_bytes=10_000
        ),
    )


def _build_view(
    job: VideoJob,
    *,
    service: _FakeSceneVideoGenerationService | None,
    job_store: _FakeJobStore | None = None,
    asset_workflow_service: SceneAssetWorkflowService | None = None,
    provider_registry: ProviderRegistry | None = None,
) -> ClipWorkspaceView:
    view = ClipWorkspaceView(
        job_store=job_store or _FakeJobStore(job),  # type: ignore[arg-type]
        asset_workflow_service=asset_workflow_service or _asset_workflow_service(),
        on_change=lambda: None,
        scene_video_generation_service=service,  # type: ignore[arg-type]
        provider_registry=provider_registry,
    )
    view.set_job(job.id)
    view.refresh(job)

    return view


def _find_buttons(view: ClipWorkspaceView) -> list[QPushButton]:
    return view.findChildren(QPushButton)


def _find_combos(view: ClipWorkspaceView) -> list[QComboBox]:
    return view.findChildren(QComboBox)


def _registry_with_both_providers() -> ProviderRegistry:
    return ProviderRegistry(
        profiles=[
            ProviderProfile(
                profile_id="flow.primary",
                display_name="flow.primary",
                provider_name="Google Flow",
                category=ProviderCategory.EXTERNAL_UI_VIDEO,
                enabled=True,
                health_status=ProviderHealthStatus.HEALTHY,
                browser_profile_reference="flow_profiles/flow.primary",
            ),
            ProviderProfile(
                profile_id="muse.primary",
                display_name="muse.primary",
                provider_name="Muse",
                category=ProviderCategory.EXTERNAL_UI_VIDEO,
                enabled=True,
                health_status=ProviderHealthStatus.HEALTHY,
                browser_profile_reference="muse_profiles/muse.primary",
            ),
        ]
    )


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


def test_shows_upload_button_next_to_the_generate_button(qapp: QApplication) -> None:
    job = _job(1, 2)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    upload_buttons = [b for b in _find_buttons(view) if b.text() == "Upload..."]
    assert len(upload_buttons) == 2


def test_clicking_upload_attaches_the_selected_file_to_that_scene(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clip_file = tmp_path / "my_clip.mp4"
    clip_file.write_bytes(b"clip-bytes")

    monkeypatch.setattr(
        "src.desktop.views.clip_workspace_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(clip_file), "Video files (*.mp4)"),
    )

    job = _job(1, 2)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(
        job,
        service=service,
        asset_workflow_service=_asset_workflow_service_with_manual_upload(tmp_path),
    )

    view._handle_upload_scene_clip(2)

    assert len(job.video_clips) == 1
    assert job.video_clips[0].scene_number == 2
    assert job.video_clips[0].source_type == SceneSourceType.MANUAL_UPLOAD


def test_clicking_upload_cancelled_is_a_noop(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.desktop.views.clip_workspace_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )

    job = _job(1)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    view._handle_upload_scene_clip(1)

    assert job.video_clips == []


def test_remove_button_is_disabled_without_a_resolved_clip(qapp: QApplication) -> None:
    job = _job(1)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    remove_button = next(b for b in _find_buttons(view) if b.text() == "Remove")
    assert remove_button.isEnabled() is False


def test_remove_button_enabled_after_upload_and_clears_the_scene(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clip_file = tmp_path / "my_clip.mp4"
    clip_file.write_bytes(b"clip-bytes")

    monkeypatch.setattr(
        "src.desktop.views.clip_workspace_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(clip_file), "Video files (*.mp4)"),
    )

    job = _job(1)
    service = _FakeSceneVideoGenerationService()
    asset_workflow_service = _asset_workflow_service_with_manual_upload(tmp_path)
    view = _build_view(
        job, service=service, asset_workflow_service=asset_workflow_service
    )

    view._handle_upload_scene_clip(1)
    assert job.video_clips  # sanity: the upload actually attached

    # A fresh view built from this now-uploaded job state (rather than
    # reusing the existing one, whose old button widgets are only
    # scheduled for deletion via Qt's deleteLater() and not reliably
    # gone by the next refresh) shows the Remove button enabled.
    uploaded_view = _build_view(
        job, service=service, asset_workflow_service=asset_workflow_service
    )
    remove_button = next(
        b for b in _find_buttons(uploaded_view) if b.text() == "Remove"
    )
    assert remove_button.isEnabled() is True

    view._handle_remove_scene_clip(1)

    assert job.video_clips == []
    assert job.scene_asset_states == []


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


def test_shows_abandon_attempt_for_a_scene_stuck_on_ui_changed(
    qapp: QApplication,
) -> None:
    """Real-world finding, 2026-09-28: a scene stuck at UI_CHANGED has
    no automated recovery path the way AUTH_REQUIRED does - the
    "Abandon attempt" button is the only way to unstick it."""

    job = _job(1, 2)
    job.flow_generation_attempts = [_ui_changed_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    buttons_by_text = [b.text() for b in _find_buttons(view)]

    assert buttons_by_text.count("Abandon attempt") == 1
    assert buttons_by_text.count("Generate") == 1  # scene 2, untouched


def test_shows_a_per_sub_clip_status_breakdown_for_a_split_scene(
    qapp: QApplication,
) -> None:
    """
    Multi-clip scene splitting (2026-09-29): a split scene's own
    aggregate status line reports only its most recent sub-clip's
    state - this breakdown gives the operator visibility into which
    specific sub-clip is stuck, mirroring the Prompts tab's own
    "Part X of Y" labeling for the same feature. Read-only: no extra
    buttons, matching the confirmed scope.
    """

    job = _job(1, 2)
    job.flow_generation_attempts = _split_scene_attempts(1)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    labels = [w.text() for w in view.findChildren(QLabel)]

    assert any("Part 1 of 2: needs_attention - failed" in text for text in labels)
    assert any("Part 2 of 2: needs_attention - ui_changed" in text for text in labels)
    # Scene 2 (an ordinary, unsplit scene) gets no breakdown at all -
    # exactly the 2 "Part" labels above, nothing more.
    assert sum(text.startswith("Part ") for text in labels) == 2


def test_shows_abandon_attempt_for_a_scene_stuck_on_a_muse_planned_orphan(
    qapp: QApplication,
) -> None:
    """
    Real-world finding, 2026-09-29: a Muse attempt orphaned at PLANNED
    (submit() raised before ever reaching replace_attempt()) used to
    fall through to a plain "Generate" button, since the button-
    visibility check only ever looked at job.flow_generation_attempts.
    Clicking that "Generate" button was a silent no-op - PLANNED is
    neither terminal nor pollable, so _drive_to_terminal() just
    returned the same stuck attempt unchanged with zero new log lines.
    """

    job = _job(1, 2)
    job.muse_generation_attempts = [_muse_planned_orphan_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(
        job, service=service, provider_registry=_registry_with_both_providers()
    )

    buttons_by_text = [b.text() for b in _find_buttons(view)]

    assert buttons_by_text.count("Abandon attempt") == 1
    assert buttons_by_text.count("Generate") == 1  # scene 2, untouched


def test_shows_retry_after_login_for_a_scene_stuck_on_muse_auth_required(
    qapp: QApplication,
) -> None:
    job = _job(1, 2)
    job.muse_generation_attempts = [_muse_auth_required_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(
        job, service=service, provider_registry=_registry_with_both_providers()
    )

    buttons_by_text = [b.text() for b in _find_buttons(view)]

    assert buttons_by_text.count("Retry after login") == 1
    assert buttons_by_text.count("Generate") == 1  # scene 2, untouched


def test_abandon_attempt_never_shown_for_a_scene_stuck_on_auth_required(
    qapp: QApplication,
) -> None:
    """AUTH_REQUIRED already has its own real recovery path - it must
    keep showing "Retry after login", not "Abandon attempt"."""

    job = _job(1)
    job.flow_generation_attempts = [_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    buttons_by_text = [b.text() for b in _find_buttons(view)]

    assert "Retry after login" in buttons_by_text
    assert "Abandon attempt" not in buttons_by_text


def test_clicking_abandon_attempt_clears_the_stuck_scene(qapp: QApplication) -> None:
    job = _job(1)
    job.flow_generation_attempts = [_ui_changed_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService()
    view = _build_view(job, service=service)

    abandon_button = next(
        b for b in _find_buttons(view) if b.text() == "Abandon attempt"
    )
    abandon_button.click()

    assert service.abandon_stuck_attempt_calls == [(1, False)]
    assert job.flow_generation_attempts == []

    resolved_view = _build_view(job, service=service)
    assert not any(b.text() == "Abandon attempt" for b in _find_buttons(resolved_view))


def test_clicking_abandon_attempt_confirms_before_forcing_a_credit_sensitive_case(
    qapp: QApplication,
) -> None:
    job = _job(1)
    job.flow_generation_attempts = [_ui_changed_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService(raise_credit_sensitive_on_scene=1)
    view = _build_view(job, service=service)

    abandon_button = next(
        b for b in _find_buttons(view) if b.text() == "Abandon attempt"
    )

    with patch(
        "src.desktop.views.clip_workspace_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.Yes,
    ):
        abandon_button.click()

    # First call refused (force=False), confirmed, then retried with
    # force=True - never silently forced without asking.
    assert service.abandon_stuck_attempt_calls == [(1, False), (1, True)]
    assert job.flow_generation_attempts == []


def test_declining_the_confirmation_leaves_the_stuck_attempt_untouched(
    qapp: QApplication,
) -> None:
    job = _job(1)
    job.flow_generation_attempts = [_ui_changed_stuck_attempt(1)]
    service = _FakeSceneVideoGenerationService(raise_credit_sensitive_on_scene=1)
    view = _build_view(job, service=service)

    abandon_button = next(
        b for b in _find_buttons(view) if b.text() == "Abandon attempt"
    )

    with patch(
        "src.desktop.views.clip_workspace_view.QMessageBox.question",
        return_value=QMessageBox.StandardButton.No,
    ):
        abandon_button.click()

    assert service.abandon_stuck_attempt_calls == [(1, False)]
    assert len(job.flow_generation_attempts) == 1  # never forced


def test_per_scene_account_combo_lists_both_providers_and_defaults_to_auto(
    qapp: QApplication,
) -> None:
    job = _job(1)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(
        job, service=service, provider_registry=_registry_with_both_providers()
    )

    combos = _find_combos(view)
    assert len(combos) == 2  # one "Generate all" combo + one per-scene combo

    # combos[0] is the Generate-all combo, combos[1] is scene 1's own.
    scene_combo = combos[1]
    labels = [scene_combo.itemText(i) for i in range(scene_combo.count())]

    assert labels[0] == "Auto"
    assert any("Google Flow" in label for label in labels)
    assert any("Muse" in label for label in labels)
    assert scene_combo.currentText() == "Auto"


def test_selecting_an_account_sets_the_scenes_preferred_profile_id(
    qapp: QApplication,
) -> None:
    job = _job(1)
    service = _FakeSceneVideoGenerationService()
    store = _FakeJobStore(job)
    view = _build_view(
        job,
        service=service,
        job_store=store,
        provider_registry=_registry_with_both_providers(),
    )

    # combos[0] is the Generate-all combo (built before any per-scene
    # combo, so it's always the first match); combos[1] is scene 1's
    # own combo.
    combos = _find_combos(view)
    scene_combo = combos[1]

    muse_index = scene_combo.findData("muse.primary")
    assert muse_index >= 0
    scene_combo.setCurrentIndex(muse_index)

    assert job.scenes[0].preferred_profile_id == "muse.primary"
    assert store.added == [job]


def test_generate_all_passes_the_chosen_account_as_forced_profile_id(
    qapp: QApplication,
) -> None:
    job = _job(1, 2)
    service = _FakeSceneVideoGenerationService()
    view = _build_view(
        job, service=service, provider_registry=_registry_with_both_providers()
    )

    # The Generate-all combo is built (and thus added to the layout)
    # before any per-scene combo, so it's always the first match.
    combos = _find_combos(view)
    all_combo = combos[0]

    muse_index = all_combo.findData("muse.primary")
    assert muse_index >= 0
    all_combo.setCurrentIndex(muse_index)

    generate_all_button = next(
        b for b in _find_buttons(view) if b.text() == "Generate all scenes"
    )
    generate_all_button.click()

    # The worker runs on a real QThread - pump the event loop until its
    # queued finished signal (and the resulting refresh) is delivered,
    # same pattern every other real-click test in this file uses.
    thread, _worker = next(iter(view._generation_threads.values()))
    thread.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert service.generate_all_forced_profile_id == "muse.primary"
