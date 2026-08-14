from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from uuid import UUID  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.main_window import MainWindow  # noqa: E402
from src.desktop.views.project_workspace_view import (  # noqa: E402
    ProjectWorkspaceView,
)
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_progress import (  # noqa: E402
    RenderProgress,
    RenderProgressStatus,
)
from src.services.render_orchestrator_service import (  # noqa: E402
    RenderOrchestratorService,
)

# QMessageBox.warning() and QFileDialog.getOpenFileName() both open a
# real modal dialog and call exec(), which blocks forever under the
# offscreen Qt platform (no display to dismiss it). Every test in this
# module patches them out so a genuine application error, or a test
# that exercises the manual-upload file picker, can never hang the
# test suite - discovered the hard way while building this integration
# test. Each workspace view (ContentStudioView, RenderWorkspaceView,
# PackagingView) imports QMessageBox itself, so each needs its own
# patch target rather than one shared module.


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.desktop.views.project_form_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.render_workspace_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.render_workspace_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "src.desktop.views.packaging_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )


def _create_project(window: MainWindow) -> None:
    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()


def _wait_for_render(
    workspace: ProjectWorkspaceView,
    job_id: UUID,
    qapp: QApplication,
    *,
    timeout_seconds: float = 5.0,
) -> None:
    """
    Pump the Qt event loop until job_id's render worker thread finishes.

    _handle_run_render()/_handle_submit_asset_decisions() now start a
    background QThread and return immediately - every test that reads
    job state the pipeline mutates (render_result, scene_asset_states,
    video_clips, ...) must wait for that thread's finished/failed
    signal to actually be delivered on the main thread first.
    """

    deadline = time.monotonic() + timeout_seconds

    while job_id in workspace.render_workspace._render_threads:
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Render for job {job_id} did not complete within "
                f"{timeout_seconds}s."
            )

        qapp.processEvents()
        time.sleep(0.01)

    qapp.processEvents()


def test_main_window_constructs_and_navigates(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    window = MainWindow(job_store=InMemoryJobStore())

    window.show_new_project()
    assert window._stack.currentWidget() is window._form_view

    window.show_settings()
    assert window._stack.currentWidget() is window._settings_view

    window.show_dashboard()
    assert window._stack.currentWidget() is window._dashboard_view


def test_create_project_runs_workflow_steps_and_generates_seo(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    jobs = window._job_store.list_all()

    assert len(jobs) == 1

    job = jobs[0]

    assert job.research is None
    assert job.script is None

    window._open_project(job.id)

    assert window._detail_view._job_id == job.id

    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    assert job.research is not None

    workspace.content_studio._handle_run_script()
    assert job.script is not None

    workspace.content_studio._handle_run_originality()
    assert job.originality_review is not None

    workspace.content_studio._handle_plan_scenes()
    assert job.scenes

    workspace.packaging._handle_generate_seo("Ocean enthusiasts")

    seo_package = window._job_store.get_seo_package(job.id)

    assert seo_package is not None
    assert seo_package.selected_title is not None

    window.show_dashboard()

    assert window._dashboard_view._table.rowCount() == 1


def test_thumbnail_generation_succeeds_in_dry_run(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    Thumbnail concept generation used to fail unconditionally under
    MISSION_AUTOMATION_DRY_RUN: DryRunProviderAdapter's generic filler
    text has no CONCEPT/HOOK/PROMPT labels, so the concept parser found
    nothing. ThumbnailConceptGenerationService now supplies a properly
    labeled dry_run_response (see dry_run_provider.py /
    thumbnail_concept_generation_service.py), which fixes the one gap
    that previously made a full dry-run pipeline run - through final
    export - impossible.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    workspace.content_studio._handle_run_script()

    workspace.packaging._handle_generate_thumbnail("Ocean enthusiasts")

    thumbnail = window._job_store.get_thumbnail(job.id)

    assert thumbnail is not None
    assert thumbnail.concept.hook_text
    assert not job.errors


def test_render_pauses_for_manual_upload_without_local_assets(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    The default local-first composition has no local asset library
    content, so scenes with no local match pause waiting for a user
    decision (manual upload or stock search) rather than hard-failing.
    This confirms that pause is normalized into a
    RenderOrchestrationResult (not an exception, not a hang), surfaced
    as per-scene choices, and that final export correctly refuses to
    build before a render actually succeeds.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    workspace.content_studio._handle_run_script()
    workspace.content_studio._handle_run_originality()
    workspace.content_studio._handle_plan_scenes()

    workspace.render_workspace._handle_run_render()
    _wait_for_render(workspace, job.id, qapp)

    render_result = window._job_store.get_render_result(job.id)

    assert render_result is not None
    assert render_result.success is False

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    workspace.packaging._handle_build_final_export()

    assert window._job_store.get_final_export(job.id) is None


def test_manual_upload_resolves_asset_stage_and_completes_render(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    Proves every render-pipeline gap closed this session adds up to a
    genuinely successful render from the desktop UI, not just "gets
    further than before": the asset-to-timeline bridge
    (SceneAssetVideoClipBuilderService), the transition.cut no-op fix,
    and dry-run rendering using the legacy RenderService instead of
    real FFmpeg (which would otherwise fail trying to read dry-run
    voice generation's placeholder "dry-run://voice/..." paths as real
    audio).
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    workspace.content_studio._handle_run_script()
    workspace.content_studio._handle_run_originality()
    workspace.content_studio._handle_plan_scenes()

    workspace.render_workspace._handle_run_render()
    _wait_for_render(workspace, job.id, qapp)

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    manual_upload_file = str(
        Path(__file__).resolve().parent.parent
        / "assets"
        / "videos"
        / "manual"
        / "scene_001.mp4"
    )

    for scene_number in waiting_scene_numbers:
        workspace.render_workspace._manual_upload_paths[scene_number] = (
            manual_upload_file
        )

    workspace.render_workspace._handle_submit_asset_decisions()
    _wait_for_render(workspace, job.id, qapp)

    render_result = window._job_store.get_render_result(job.id)

    assert render_result is not None
    assert job.video_clips
    assert len(job.video_clips) == len(waiting_scene_numbers)
    assert render_result.success is True
    assert render_result.render_result is not None
    assert render_result.render_result.output_file is not None


def test_stock_search_and_select_completes_render(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    Proves the stock-footage path (the other half of "manual upload or
    search stock" per scene) works end to end through the desktop UI:
    searching populates SceneAssetState.stock_candidates in place,
    selecting a result records the choice, and submitting acquires it
    (SceneAssetWorkflowService.apply_decision()'s new USE_STOCK ->
    acquire_selected_stock() auto-chain) within the same render call
    that resumes from the paused asset stage.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    workspace.content_studio._handle_run_script()
    workspace.content_studio._handle_run_originality()
    workspace.content_studio._handle_plan_scenes()

    workspace.render_workspace._handle_run_render()
    _wait_for_render(workspace, job.id, qapp)

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    for scene_number in waiting_scene_numbers:
        workspace.render_workspace._handle_search_stock(scene_number, "")

    for scene_number in waiting_scene_numbers:
        state = workspace.render_workspace._scene_asset_state(job, scene_number)

        assert state is not None
        assert state.stock_candidates

        workspace.render_workspace._handle_select_stock_candidate(scene_number, 0)

    workspace.render_workspace._handle_submit_asset_decisions()
    _wait_for_render(workspace, job.id, qapp)

    render_result = window._job_store.get_render_result(job.id)

    assert render_result is not None
    assert render_result.success is True
    assert job.video_clips
    assert all(clip.source_type.value == "stock_footage" for clip in job.video_clips)


def test_full_pipeline_reaches_final_export(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    Drives the complete pipeline through the desktop UI, exactly as a
    user would click through it: create -> research -> script ->
    originality review -> scene planning -> render (paused for asset
    decisions) -> resolve via stock search -> SEO -> thumbnail ->
    final export. Every stage before this test was already proven
    individually; this proves they chain together into one successful
    run all the way to a built FinalExportPackage, with no errors
    recorded on the job and the render itself succeeding - not just
    "gets further than before".
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    workspace.content_studio._handle_run_script()
    workspace.content_studio._handle_run_originality()
    workspace.content_studio._handle_plan_scenes()

    workspace.render_workspace._handle_run_render()
    _wait_for_render(workspace, job.id, qapp)

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    for scene_number in waiting_scene_numbers:
        workspace.render_workspace._handle_search_stock(scene_number, "")
        workspace.render_workspace._handle_select_stock_candidate(scene_number, 0)

    workspace.render_workspace._handle_submit_asset_decisions()
    _wait_for_render(workspace, job.id, qapp)

    render_result = window._job_store.get_render_result(job.id)
    assert render_result is not None
    assert render_result.success is True

    workspace.packaging._handle_generate_seo("Ocean enthusiasts")
    seo_package = window._job_store.get_seo_package(job.id)
    assert seo_package is not None

    workspace.packaging._handle_generate_thumbnail("Ocean enthusiasts")
    thumbnail = window._job_store.get_thumbnail(job.id)
    assert thumbnail is not None

    workspace.packaging._handle_build_final_export()
    final_export = window._job_store.get_final_export(job.id)

    assert final_export is not None
    assert final_export.final_video_path
    assert not job.errors

    # Quality Center is a genuinely new trigger (PolicyService existed
    # in the backend but was wired into no UI before this workspace
    # split) - confirm it evaluates the completed job without error.
    workspace.quality_center._handle_run_check()
    assert job.policy_report is not None

    # Clip Workspace, Production Audio, and Editing Timeline are review
    # panels over the same job/render data - confirm switching to each
    # renders the fully-populated state without crashing.
    for _nav_button, target in workspace._nav_buttons:
        workspace._show_workspace(target)

    assert window._stack.currentWidget() is window._detail_view


def test_workspace_views_refresh_without_crashing_on_a_fresh_project(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    Clip Workspace, Production Audio, and Editing Timeline are new
    review panels with no prior test coverage for the empty/minimal
    state (no scenes, no clips, no audio_timeline, no video_timeline).
    A freshly created project exercises exactly that state for all
    seven workspaces at once.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    for _label, _icon, target in workspace._workspaces:
        workspace._show_workspace(target)

    assert workspace._stack.currentWidget() is workspace.packaging


def test_render_progress_updates_live_and_survives_cross_workspace_refresh(
    qapp: QApplication,
    no_blocking_dialogs: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Proves the QThread/Signal wiring actually delivers RenderProgress
    across threads to the live widgets (not just that it compiles), and
    that the two correctness guards found during design review hold:
    a render in flight must survive an unrelated workspace's on_change
    (every workspace shares the same on_change callback, so this is
    easy to break by accident) and must still write its result and
    refresh the UI once it completes.

    MISSION_AUTOMATION_DRY_RUN never invokes real FFmpeg (the legacy
    render stub instant-completes with no intermediate state), so
    RenderOrchestratorService.execute() is replaced with a fake that
    emits real RenderProgress ticks with a short real sleep between
    them - enough wall-clock time for the polling loop below to
    observe the in-progress state before the fake call returns.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    workspace.content_studio._handle_run_research()
    workspace.content_studio._handle_run_script()
    workspace.content_studio._handle_run_originality()
    workspace.content_studio._handle_plan_scenes()

    def fake_execute(
        self: RenderOrchestratorService,
        job: object,
        *,
        dry_run: bool = False,
        checkpoint_id: object | None = None,
        user_input: object | None = None,
        progress_callback: object | None = None,
    ) -> RenderOrchestrationResult:
        assert progress_callback is not None

        progress_callback(
            RenderProgress(
                status=RenderProgressStatus.RUNNING,
                progress_percent=25.0,
                elapsed_seconds=1.0,
                processed_duration_seconds=5.0,
                total_duration_seconds=20.0,
                speed=1.5,
            )
        )
        time.sleep(0.2)
        progress_callback(
            RenderProgress(
                status=RenderProgressStatus.RUNNING,
                progress_percent=75.0,
                elapsed_seconds=3.0,
                processed_duration_seconds=15.0,
                total_duration_seconds=20.0,
                speed=2.0,
            )
        )
        time.sleep(0.05)

        # A real success requires job.render_result plus a fully
        # rendered video/audio timeline, which this fake never
        # produces (it only exists to prove progress-signal delivery
        # and the two UI guards, not to exercise a real render).
        # model_construct bypasses that unrelated validation chain
        # rather than fabricating a fake VideoTimeline/AudioTimeline
        # just to satisfy it.
        return RenderOrchestrationResult.model_construct(
            success=True,
            status=JobStatus.COMPLETED,
            current_stage=WorkflowStage.READY_FOR_UPLOAD,
            completed_stages=[],
            failed_stage=None,
            job=job,
            render_result=None,
            elapsed_seconds=3.5,
            warnings=[],
            errors=[],
            metadata={},
        )

    monkeypatch.setattr(RenderOrchestratorService, "execute", fake_execute)

    workspace.render_workspace._handle_run_render()

    assert job.id in workspace.render_workspace._rendering_job_ids
    progress_bar_identity = workspace.render_workspace._progress_bar

    observed_progress_percent: float | None = None
    deadline = time.monotonic() + 2.0

    while time.monotonic() < deadline:
        qapp.processEvents()

        if workspace.render_workspace._progress_bar.value() > 0:
            observed_progress_percent = workspace.render_workspace._progress_bar.value()

            break

        time.sleep(0.005)

    assert observed_progress_percent is not None
    assert observed_progress_percent > 0
    assert "Speed:" in workspace.render_workspace._progress_speed_label.text()

    # A different workspace's on_change must not tear down this
    # workspace's live progress widgets while the render is still
    # running (Gap B) - PolicyService.evaluate() only needs a script,
    # which content_studio already produced above.
    workspace.quality_center._handle_run_check()

    assert job.id in workspace.render_workspace._rendering_job_ids
    assert workspace.render_workspace._progress_bar is progress_bar_identity

    _wait_for_render(workspace, job.id, qapp)

    assert job.id not in workspace.render_workspace._rendering_job_ids

    render_result = window._job_store.get_render_result(job.id)

    assert render_result is not None
    assert render_result.success is True
    assert job.policy_report is not None
