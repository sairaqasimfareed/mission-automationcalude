from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.main_window import MainWindow  # noqa: E402

# QMessageBox.warning() and QFileDialog.getOpenFileName() both open a
# real modal dialog and call exec(), which blocks forever under the
# offscreen Qt platform (no display to dismiss it). Every test in this
# module patches them out so a genuine application error, or a test
# that exercises the manual-upload file picker, can never hang the
# test suite - discovered the hard way while building this integration
# test.


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
        "src.desktop.views.project_detail_view.QMessageBox.warning",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "src.desktop.views.project_detail_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )


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

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    jobs = window._job_store.list_all()

    assert len(jobs) == 1

    job = jobs[0]

    assert job.research is None
    assert job.script is None

    window._open_project(job.id)

    assert window._detail_view._job_id == job.id

    window._detail_view._handle_run_research()
    assert job.research is not None

    window._detail_view._handle_run_script()
    assert job.script is not None

    window._detail_view._handle_run_originality()
    assert job.originality_review is not None

    window._detail_view._handle_plan_scenes()
    assert job.scenes

    window._detail_view._handle_generate_seo("Ocean enthusiasts")

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

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    job = window._job_store.list_all()[0]
    window._open_project(job.id)

    window._detail_view._handle_run_research()
    window._detail_view._handle_run_script()

    window._detail_view._handle_generate_thumbnail("Ocean enthusiasts")

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

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    job = window._job_store.list_all()[0]
    window._open_project(job.id)

    window._detail_view._handle_run_research()
    window._detail_view._handle_run_script()
    window._detail_view._handle_run_originality()
    window._detail_view._handle_plan_scenes()

    window._detail_view._handle_run_render()

    render_result = window._job_store.get_render_result(job.id)

    assert render_result is not None
    assert render_result.success is False

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    window._detail_view._handle_build_final_export()

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

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    job = window._job_store.list_all()[0]
    window._open_project(job.id)

    window._detail_view._handle_run_research()
    window._detail_view._handle_run_script()
    window._detail_view._handle_run_originality()
    window._detail_view._handle_plan_scenes()

    window._detail_view._handle_run_render()

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
        window._detail_view._manual_upload_paths[scene_number] = manual_upload_file

    window._detail_view._handle_submit_asset_decisions()

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

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    job = window._job_store.list_all()[0]
    window._open_project(job.id)

    window._detail_view._handle_run_research()
    window._detail_view._handle_run_script()
    window._detail_view._handle_run_originality()
    window._detail_view._handle_plan_scenes()

    window._detail_view._handle_run_render()

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    for scene_number in waiting_scene_numbers:
        window._detail_view._handle_search_stock(scene_number, "")

    for scene_number in waiting_scene_numbers:
        state = window._detail_view._scene_asset_state(job, scene_number)

        assert state is not None
        assert state.stock_candidates

        window._detail_view._handle_select_stock_candidate(scene_number, 0)

    window._detail_view._handle_submit_asset_decisions()

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

    window.show_new_project()
    form = window._form_view

    form._project_name.setText("Deep Sea Documentary")
    form._channel_name.setText("Ocean Channel")
    form._topic.setText("Deep sea creatures")
    form._video_type.setText("long-form documentary")
    form._niche.setText("ocean-life")
    form._duration_seconds.setValue(600)

    form._handle_create_clicked()

    job = window._job_store.list_all()[0]
    window._open_project(job.id)
    detail = window._detail_view

    detail._handle_run_research()
    detail._handle_run_script()
    detail._handle_run_originality()
    detail._handle_plan_scenes()

    detail._handle_run_render()

    waiting_scene_numbers = [
        state.scene_number
        for state in job.scene_asset_states
        if state.requires_user_decision
    ]

    assert waiting_scene_numbers

    for scene_number in waiting_scene_numbers:
        detail._handle_search_stock(scene_number, "")
        detail._handle_select_stock_candidate(scene_number, 0)

    detail._handle_submit_asset_decisions()

    render_result = window._job_store.get_render_result(job.id)
    assert render_result is not None
    assert render_result.success is True

    detail._handle_generate_seo("Ocean enthusiasts")
    seo_package = window._job_store.get_seo_package(job.id)
    assert seo_package is not None

    detail._handle_generate_thumbnail("Ocean enthusiasts")
    thumbnail = window._job_store.get_thumbnail(job.id)
    assert thumbnail is not None

    detail._handle_build_final_export()
    final_export = window._job_store.get_final_export(job.id)

    assert final_export is not None
    assert final_export.final_video_path
    assert not job.errors
