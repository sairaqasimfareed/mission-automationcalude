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
from src.models.approval import HumanApprovalAction  # noqa: E402
from src.models.enums import JobStatus, WorkflowStage  # noqa: E402
from src.models.final_preview import FinalPreviewAction  # noqa: E402
from src.models.google_flow_generation import (  # noqa: E402
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.render_orchestration_result import (  # noqa: E402
    RenderOrchestrationResult,
)
from src.models.render_progress import (  # noqa: E402
    RenderProgress,
    RenderProgressStatus,
)
from src.models.video_job import VideoJob  # noqa: E402
from src.services.approval_gate_service import ApprovalGateService  # noqa: E402
from src.services.google_flow_generation_ledger_service import (  # noqa: E402
    GoogleFlowGenerationLedgerService,
)
from src.services.render_orchestrator_service import (  # noqa: E402
    RenderOrchestratorService,
)

# QMessageBox.warning()/show_recoverable_error() and
# QFileDialog.getOpenFileName() both open a real modal dialog and call
# exec(), which blocks forever under the offscreen Qt platform (no
# display to dismiss it). Every test in this module patches them out
# so a genuine application error, or a test that exercises the
# manual-upload file picker, can never hang the test suite -
# discovered the hard way while building this integration test. Each
# workspace view imports its own dialog function, so each needs its
# own patch target rather than one shared module. project_form_view
# still calls QMessageBox.warning() directly (it predates
# show_recoverable_error and has no meaningful retry action); every
# other workspace view now routes step failures through
# show_recoverable_error() instead.


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
        "src.desktop.views.content_studio_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.render_workspace_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.render_workspace_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "src.desktop.views.packaging_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.quality_center_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.clip_workspace_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.production_audio_view.show_recoverable_error",
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
    """
    GUI-0 (Unified GUI & Release Hardening, live inventory): every
    MainWindow toolbar action, not just some of them - a real,
    confirmed gap this test used to leave open (Providers and Google
    Flow were reachable in the real app but never exercised here).
    """

    window = MainWindow(job_store=InMemoryJobStore())

    window.show_new_project()
    assert window._stack.currentWidget() is window._form_view

    window.show_settings()
    assert window._stack.currentWidget() is window._settings_view

    window.show_provider_manager()
    assert window._stack.currentWidget() is window._provider_manager_view

    window.show_google_flow_provider_panel()
    assert window._stack.currentWidget() is window._google_flow_provider_panel_view

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
    final export -> final preview approval. Every stage before this
    test was already proven individually; this proves they chain
    together into one successful run all the way to a built
    FinalExportPackage plus an APPROVED FinalPreview bound to the
    exact render that produced it, with no errors recorded on the job
    and the render itself succeeding - not just "gets further than
    before".

    Content-intelligence approval gating (the "approve" step in the
    production-hardening spec's golden-path wording) is deliberately
    not chained into this test: it belongs to the newer
    ContentIntelligencePipeline stack, a separate, already
    individually-tested path from the legacy ContentPipeline this test
    drives (see test_content_intelligence_pipeline.py's own approval-
    gate tests, test_approval_gate_service.py, and
    test_content_studio_content_intelligence_gui.py) - stitching both
    pipelines into a single golden-path run would test an integration
    that doesn't exist in the real app (a project uses one pipeline or
    the other, never both for the same run).
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

    # Final preview: bind a preview to this exact render, then approve
    # it - the last named step in the golden path ("final preview")
    # that nothing else in this run exercises end-to-end through the
    # GUI.
    workspace.quality_center._handle_create_final_preview()
    assert job.final_previews
    latest_preview = job.final_previews[-1]
    assert latest_preview.render_identity

    workspace.quality_center._handle_resolve_final_preview(
        FinalPreviewAction.APPROVE_FINAL
    )
    assert job.final_previews[-1].status.value == "approved"

    # Clip Workspace, Production Audio, and Editing Timeline are review
    # panels over the same job/render data - confirm switching to each
    # renders the fully-populated state without crashing.
    for _nav_button, target in workspace._nav_buttons:
        workspace._show_workspace(target)

    assert window._stack.currentWidget() is window._detail_view


def _run_content_intelligence_pipeline_to_scene_planning(
    window: MainWindow, qapp: QApplication
) -> tuple[ProjectWorkspaceView, VideoJob]:
    """
    Shared setup for both tests below: drives ContentIntelligencePipeline
    all the way through Script Lock and scene planning via the real GUI
    "Run automation" / "Approve" loop - Content Studio's own real
    mechanism for ContentIntelligencePipeline.run_all() plus
    ApprovalGateService's pending-decision resolution, matching how a
    human operator would actually clear each review gate in turn, not
    a direct service-level bypass of the approval mechanism.
    """

    _create_project(window)

    job = window._job_store.list_all()[0]
    # genre.documentary's own real, genre-specific
    # default_scene_source_type is STOCK_FOOTAGE (confirmed by
    # inspection: genre.mystery/horror/reaction/storytelling default
    # to MANUAL_UPLOAD instead - a deliberate per-genre policy, not a
    # bug), so this exercises the same stock-footage asset-resolution
    # flow test_full_pipeline_reaches_final_export already proves.
    job.genre_id = "genre.documentary"
    window._open_project(job.id)
    workspace = window._detail_view
    content_studio = workspace.content_studio

    for _ in range(15):
        content_studio._handle_run_automation()

        if job.errors:
            break

        pending = ApprovalGateService.latest_pending(job)

        if pending is None or pending.approval is None:
            break

        content_studio._content_intelligence_pipeline.resolve_approval(
            job, pending.approval.decision_point, HumanApprovalAction.APPROVE
        )
    else:
        pytest.fail(
            "Automation did not reach a stable, gate-free state within "
            "15 run/approve cycles - either a real regression or a new "
            "decision point this test needs to know about."
        )

    return workspace, job


def test_content_intelligence_pipeline_reaches_script_lock_and_scene_planning(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    MRA-PRE-3 (Pre-Installer Master Audit, canonical lifecycle audit)
    real finding: test_full_pipeline_reaches_final_export (above)
    deliberately drives the LEGACY ContentPipeline, not the current,
    canonical ContentIntelligencePipeline stack MRA-PRE-1's own
    authority audit confirmed is the one every new project actually
    uses. That left the first half of the plan's own literal objective
    ("trace a real project from script approval through Phase 15")
    never actually proven for the pipeline real projects use today.
    This proves that first half: audience promise through Script Lock
    through real, genre-aware scene planning, with zero errors.

    The second half (render through final export) is a SEPARATE test,
    marked xfail - see
    test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render
    below for why.
    """

    window = MainWindow(job_store=InMemoryJobStore())
    _, job = _run_content_intelligence_pipeline_to_scene_planning(window, qapp)

    assert not job.errors
    assert job.script_lock is not None
    assert job.scenes


@pytest.mark.xfail(
    strict=True,
    reason=(
        "The ORIGINAL MRA-PRE-3 finding this test's docstring names "
        "(ScenePlannerAgent scene duration not reconciled against "
        "narration length) is CONFIRMED FIXED - the exact 'Estimated "
        "narration duration exceeds the scene duration' error is gone "
        "from this run, and 2 new direct unit tests on ScenePlannerAgent "
        "(test_scene_planner_generated_script.py) independently prove "
        "the fix. Left xfail because removing that blocker surfaced a "
        "SEPARATE, different, not-yet-diagnosed one: render now fails "
        "later, at asset acquisition, with 'The selected stock footage "
        "could not be acquired.' - a real but distinct issue, out of "
        "scope for the duration fix this test was originally written "
        "to prove. Diagnosing/fixing that is tracked as its own future "
        "item, not folded into this marker's original reason."
    ),
)
def test_content_intelligence_pipeline_scenes_pass_voice_validation_at_render(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    The second half of MRA-PRE-3's own objective: proves the SAME
    render -> asset-decision resolution -> SEO -> thumbnail -> final
    export -> final preview sequence
    test_full_pipeline_reaches_final_export already proves for the
    legacy pipeline also works for scenes the CURRENT, canonical
    pipeline produced - and that every accepted artifact reloads
    correctly from a genuinely fresh store read (MRA-PRE-3's own
    restart-safety requirement), not just the in-memory object this
    test mutates throughout.

    The ORIGINAL blocker this test was written to prove
    (docs/MRA_PRE_3_LIFECYCLE_AUDIT.md: ScenePlannerAgent sizing scenes
    from genre density alone, with no reconciliation against actual
    narration length) is fixed - see ScenePlannerAgent._subdivide_segment()'s
    own docstring. This test still xfails, now for a different,
    separate reason - see the marker above.
    """

    window = MainWindow(job_store=InMemoryJobStore())
    workspace, job = _run_content_intelligence_pipeline_to_scene_planning(window, qapp)

    assert not job.errors
    assert job.script_lock is not None
    assert job.scenes

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

    workspace.packaging._handle_generate_seo("Mystery enthusiasts")
    seo_package = window._job_store.get_seo_package(job.id)
    assert seo_package is not None
    # Provenance (MRA-PRE-3's own persistence/provenance requirement):
    # the SEO package must trace back to the exact script lock that
    # authorized this production run, not merely exist.
    assert job.script_lock is not None
    assert seo_package.source_script_lock_hash == job.script_lock.script_content_hash

    workspace.packaging._handle_generate_thumbnail("Mystery enthusiasts")
    thumbnail = window._job_store.get_thumbnail(job.id)
    assert thumbnail is not None

    workspace.packaging._handle_build_final_export()
    final_export = window._job_store.get_final_export(job.id)

    assert final_export is not None
    assert final_export.final_video_path
    assert not job.errors

    workspace.quality_center._handle_run_check()
    assert job.policy_report is not None

    workspace.quality_center._handle_create_final_preview()
    assert job.final_previews
    latest_preview = job.final_previews[-1]
    assert latest_preview.render_identity

    workspace.quality_center._handle_resolve_final_preview(
        FinalPreviewAction.APPROVE_FINAL
    )
    assert job.final_previews[-1].status.value == "approved"

    # Restart-safety (MRA-PRE-3's own acceptance gate: "restart-safe"):
    # every accepted artifact this run produced must reload correctly
    # from a genuinely fresh store read, not just the in-memory object
    # this test has been mutating throughout.
    reloaded_job = window._job_store.get(job.id)
    assert reloaded_job is not None
    assert reloaded_job.script_lock is not None
    assert reloaded_job.script_lock.script_content_hash == (
        job.script_lock.script_content_hash
    )
    assert len(reloaded_job.scenes) == len(job.scenes)
    assert reloaded_job.final_previews[-1].status.value == "approved"


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

    for _label, _icon, _tab_name, target in workspace._workspaces:
        workspace._show_workspace(target)

    assert workspace._stack.currentWidget() is workspace.packaging


def test_main_window_remains_functional_at_its_documented_minimum_size(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    GUI-6 (Unified GUI & Release Hardening): MainWindow declares its
    own minimum size (900x600, see main_window.py's own
    setMinimumSize call) - this confirms the app actually stays usable
    there rather than merely refusing to shrink further. Navigates
    every toolbar destination and every workspace tab at exactly that
    size and confirms nothing crashes and the central widget never
    collapses to a degenerate (zero-area) geometry, which would be the
    concrete symptom of a layout silently failing to fit its own
    declared minimum.
    """

    window = MainWindow(job_store=InMemoryJobStore())
    window.resize(900, 600)
    window.show()

    def _assert_sane_central_widget_geometry() -> None:
        size = window._stack.currentWidget().size()
        assert size.width() > 0
        assert size.height() > 0

    window.show_dashboard()
    _assert_sane_central_widget_geometry()

    window.show_provider_manager()
    _assert_sane_central_widget_geometry()

    window.show_google_flow_provider_panel()
    _assert_sane_central_widget_geometry()

    window.show_settings()
    _assert_sane_central_widget_geometry()

    _create_project(window)
    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    _assert_sane_central_widget_geometry()

    workspace = window._detail_view
    for _label, _icon, _tab_name, target in workspace._workspaces:
        workspace._show_workspace(target)
        assert workspace._stack.currentWidget().size().height() > 0


def test_reopening_a_project_reconciles_a_flow_attempt_stuck_at_submitting(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    MRA-PRE-2 (Pre-Installer Master Audit, persistence/restart audit)
    real finding: GoogleFlowGenerationLedgerService.reconcile_on_restart()
    has existed and been tested in isolation since GF-1, but nothing in
    the real application ever called it - a project reopened after the
    app closed or crashed while a Google Flow attempt was mid-
    submission would show that attempt stuck at SUBMITTING forever,
    never self-correcting to the honest SUBMISSION_UNCERTAIN state the
    service was built to produce. Fixed by wiring the call into
    ProjectWorkspaceView.set_job() (the real "a project is being
    (re)opened" moment) - this drives that fix through the actual
    MainWindow -> _open_project -> ProjectWorkspaceView.set_job() path,
    not just the ledger service in isolation.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)
    job = window._job_store.list_all()[0]

    request = GoogleFlowGenerationRequest(
        scene_number=1,
        prompt="A lighthouse at dusk, waves crashing below.",
        prompt_version="v1",
        profile_id="flow.primary",
        idempotency_key="req-1",
    )
    attempt = GoogleFlowGenerationLedgerService.create_attempt(job, request)

    for state in (
        GoogleFlowGenerationState.SETTINGS_VERIFIED,
        GoogleFlowGenerationState.PROMPT_PREPARED,
        GoogleFlowGenerationState.SUBMITTING,
    ):
        GoogleFlowGenerationLedgerService.record_transition(job, attempt.id, state)

    window._job_store.add(job)
    assert (
        window._job_store.get(job.id).flow_generation_attempts[0].state  # type: ignore[union-attr]
        == GoogleFlowGenerationState.SUBMITTING
    )

    # Simulates the app having been closed and reopened to this same
    # project - the real path a restart takes, not a direct service call.
    window._open_project(job.id)

    reopened = window._job_store.get(job.id)
    assert reopened is not None
    assert reopened.flow_generation_attempts[0].state == (
        GoogleFlowGenerationState.SUBMISSION_UNCERTAIN
    )


def test_project_header_row_reflects_summary_and_rebuilds_on_refresh(
    qapp: QApplication,
    no_blocking_dialogs: None,
) -> None:
    """
    The persistent header row (ProjectHeaderService) is rebuilt from
    scratch on every refresh() rather than mutated in place - this
    confirms it renders the expected fields for a fresh project and
    that repeated refresh() calls don't leak widgets into the layout.
    """

    window = MainWindow(job_store=InMemoryJobStore())

    _create_project(window)

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    workspace = window._detail_view

    header_texts = [
        workspace._header_row_layout.itemAt(i).widget().text()  # type: ignore[union-attr]
        for i in range(workspace._header_row_layout.count())
        if workspace._header_row_layout.itemAt(i).widget() is not None
    ]

    assert any(text.startswith("Mode:") for text in header_texts)
    assert any(text.startswith("Stage:") for text in header_texts)
    assert any(text.startswith("Approval:") for text in header_texts)
    assert any(text.startswith("Next approval:") for text in header_texts)
    assert any(text.startswith("Quality:") for text in header_texts)
    assert any(text.startswith("Budget:") for text in header_texts)
    assert any(text.startswith("Automation:") for text in header_texts)
    assert any(text.startswith("Readiness:") for text in header_texts)

    widget_count_before = workspace._header_row_layout.count()
    workspace.refresh()
    widget_count_after = workspace._header_row_layout.count()

    assert widget_count_after == widget_count_before


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
