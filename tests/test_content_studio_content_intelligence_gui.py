from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import patch  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.content_studio_view import (  # noqa: E402
    _CI_STAGES,
    ContentStudioView,
)
from src.models.approval import ApprovalPolicyConfig  # noqa: E402
from src.models.artifact_lifecycle import ArtifactType  # noqa: E402
from src.models.media_strategy import SceneSourceType  # noqa: E402
from src.models.scene import Scene  # noqa: E402
from src.models.script_lock import ScriptProvenance  # noqa: E402
from src.models.script_version import VersionReason  # noqa: E402
from src.models.video_clip import VideoClip  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.video_timeline import VideoTimeline  # noqa: E402
from src.services.content_intelligence_pipeline import (  # noqa: E402
    ContentIntelligencePipeline,
)
from src.services.content_pipeline import ContentPipeline  # noqa: E402
from src.services.fact_check_service import FactCheckService  # noqa: E402
from src.services.llm.llm_service import LLMServiceResult  # noqa: E402
from src.services.reviewer_service import ReviewerService  # noqa: E402
from src.services.topic_candidate_generation_service import (  # noqa: E402
    TopicCandidateGenerationService,
)
from src.shared.llm.models import (  # noqa: E402
    LLMCallResult,
    LLMCallStatus,
    LLMProvider,
)
from src.shared.llm.request import LLMRequest  # noqa: E402


class _EchoStubLLMService:
    """Mirrors test_content_intelligence_pipeline.py's stub - echoes
    each request's own dry_run_response so every retrofitted service's
    parser accepts it."""

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        content = request.dry_run_response or (
            "The Mary Celeste was found adrift, seaworthy, with no crew aboard."
        )

        if request.metadata.get("agent") == "AudiencePromiseService":
            # AudiencePromiseService's own dry-run response models a
            # MODERATE promise (confidence 0.6), below
            # ApprovalService's 0.7 auto-continue threshold - swap in
            # STRONG so approval-gating tests exercise story_angle's
            # own REVIEW gate specifically, not an earlier AUTO one.
            content = content.replace(
                "PROMISE_STRENGTH: moderate", "PROMISE_STRENGTH: strong"
            )
        elif request.metadata.get("agent") == "HookEvaluationService":
            # Same reasoning as test_content_intelligence_pipeline.py's
            # own stub: the service's placeholder dry-run scores every
            # dimension (including SPOILER_RISK) at 70, which zeroes
            # overall_score/confidence_score by construction
            # (raw_average - spoiler_risk = 0) - fine in isolation, but
            # a full run_all() test needs a hook that can plausibly
            # auto-continue past the hook gate.
            content = content.replace("SPOILER_RISK: 70", "SPOILER_RISK: 0")

        result = LLMCallResult(
            status=LLMCallStatus.SUCCESS,
            provider=LLMProvider.OPENAI,
            model="test-model",
            content=content,
        )

        return LLMServiceResult(
            result=result,
            selected_profile_id="test-profile",
            all_providers_failed=False,
        )


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _view(job_store: InMemoryJobStore) -> ContentStudioView:
    stub = _EchoStubLLMService()

    return ContentStudioView(
        job_store=job_store,
        content_pipeline=ContentPipeline(llm_service=stub),  # type: ignore[arg-type]
        content_intelligence_pipeline=ContentIntelligencePipeline(
            llm_service=stub  # type: ignore[arg-type]
        ),
        reviewer_service=ReviewerService(llm_service=stub),  # type: ignore[arg-type]
        topic_candidate_generation_service=TopicCandidateGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
        fact_check_service=FactCheckService(llm_service=stub),  # type: ignore[arg-type]
        on_change=lambda: None,
    )


def _job() -> VideoJob:
    return VideoJob(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
        target_duration_seconds=180,
        target_audience="mystery enthusiasts",
    )


def test_refresh_builds_without_error_before_any_stage_runs(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise


def test_selecting_a_stage_updates_the_selected_index(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    assert view._selected_ci_stage_index == 0

    view._handle_select_ci_stage(3)

    assert view._selected_ci_stage_index == 3


def _run_pending_timer(*args: object, **kwargs: object) -> None:
    """
    Patches QTimer.singleShot in these tests to call its callback
    immediately - refresh()'s own real fix defers the scroll restore
    to the next event-loop tick (deliberately, see its docstring), and
    a test has no reliable way to wait for that tick without either
    this patch or a real, potentially-flaky event-loop wait.
    """

    callback = args[-1] if args else kwargs["callback"]
    assert callable(callback)
    callback()


def test_refresh_preserves_scroll_position_for_the_same_job(
    qapp: QApplication,
) -> None:
    """
    Real-world finding: every action on this screen (selecting a
    topic, running a stage, saving an edit) calls refresh(), which
    tears down and rebuilds every card from scratch - the view was
    silently snapping back to the top after every single click.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view.resize(400, 200)
    view.show()
    qapp.processEvents()

    view._scroll_area.verticalScrollBar().setValue(123)  # noqa: SLF001
    scrolled_to = view._scroll_area.verticalScrollBar().value()  # noqa: SLF001
    assert scrolled_to > 0  # sanity: there was real scrollable content

    with patch(
        "src.desktop.views.content_studio_view.QTimer.singleShot",
        side_effect=_run_pending_timer,
    ):
        view.refresh(job)  # simulates any button-triggered rebuild

    assert view._scroll_area.verticalScrollBar().value() == scrolled_to  # noqa: SLF001


def test_scroll_restore_applies_via_range_changed(qapp: QApplication) -> None:
    """
    The primary mechanism, exercised directly - rangeChanged firing
    (Qt's own authoritative "the scrollable range was just
    recalculated" signal) must apply the restore, and the
    QTimer.singleShot fallback must then correctly stop listening
    without erroring on an already-disconnected signal.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    with patch(
        "src.desktop.views.content_studio_view.QTimer.singleShot"
    ) as fake_single_shot:
        view._schedule_scroll_restore(77)  # noqa: SLF001

        # rangeChanged fires for real here - no patching needed, this
        # is Qt's own real signal on a real (if offscreen) QScrollBar.
        view._scroll_area.verticalScrollBar().setRange(0, 500)  # noqa: SLF001
        assert view._scroll_area.verticalScrollBar().value() == 77  # noqa: SLF001

        # The fallback timer's own stop-listening callback must be a
        # safe no-op once the value has already been correctly applied
        # (disconnecting an already-disconnected signal must not raise).
        fallback_callback = fake_single_shot.call_args.args[-1]
        fallback_callback()
        assert view._scroll_area.verticalScrollBar().value() == 77  # noqa: SLF001


def test_scroll_restore_survives_an_intermediate_zero_range_firing(
    qapp: QApplication,
) -> None:
    """
    Real-world finding, confirmed via runtime diagnostic logging: on a
    real project (not a small test job), rangeChanged sometimes fires
    FIRST with maximum() == 0 - an intermediate, still-collapsing state
    mid-rebuild - before growing to its true final size on a LATER
    firing. Disconnecting after only the first firing (an earlier
    version of this fix) meant the restore got silently clamped to 0
    and never got a second chance - exactly the reported "still resets
    to top" symptom. The fix must keep listening and reapply on every
    firing, so a later, correctly-sized firing still sticks.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    with patch("src.desktop.views.content_studio_view.QTimer.singleShot"):
        view._schedule_scroll_restore(1138)  # noqa: SLF001

        scroll_bar = view._scroll_area.verticalScrollBar()  # noqa: SLF001

        # The intermediate, still-collapsed state a real rebuild can
        # transiently pass through.
        scroll_bar.setRange(0, 0)
        assert scroll_bar.value() == 0  # correctly clamped, not yet the bug

        # The range then grows to its true final size on a later
        # firing - the restore must still land correctly here, not
        # stay stuck at 0 from the earlier, premature firing.
        scroll_bar.setRange(0, 1781)
        assert scroll_bar.value() == 1138


def test_refresh_resets_scroll_position_when_switching_projects(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)
    other_job = _job()
    job_store.add(other_job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view.resize(400, 200)
    view.show()
    qapp.processEvents()
    view._scroll_area.verticalScrollBar().setValue(123)  # noqa: SLF001

    view.set_job(other_job.id)

    with patch(
        "src.desktop.views.content_studio_view.QTimer.singleShot",
        side_effect=_run_pending_timer,
    ):
        view.refresh(other_job)

    # A genuinely different job must start at the top, never wherever
    # the previous project's scroll happened to be.
    assert view._scroll_area.verticalScrollBar().value() == 0  # noqa: SLF001


def test_run_audience_promise_stage_populates_job(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")

    assert job.audience_promise is not None
    assert job.editorial_profile_snapshot is not None


def test_review_is_a_noop_without_a_configured_reviewer(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_ci_stage("audience_promise")

    view._handle_review_ci_stage(
        stage_key="audience_promise",
        artifact_type=ArtifactType.AUDIENCE_STRATEGY,
        field_name="audience_promise",
    )

    assert view._last_review_by_stage == {}


def test_review_is_a_noop_when_the_artifact_does_not_exist_yet(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.provider_preferences.reviewer.reviewer_profile_id = "reviewer-main"
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_review_ci_stage(
        stage_key="audience_promise",
        artifact_type=ArtifactType.AUDIENCE_STRATEGY,
        field_name="audience_promise",
    )

    assert view._last_review_by_stage == {}


def test_reviewing_a_stage_stores_and_renders_the_result(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.provider_preferences.reviewer.reviewer_profile_id = "reviewer-main"
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_ci_stage("audience_promise")

    view._handle_review_ci_stage(
        stage_key="audience_promise",
        artifact_type=ArtifactType.AUDIENCE_STRATEGY,
        field_name="audience_promise",
    )

    assert "audience_promise" in view._last_review_by_stage
    result = view._last_review_by_stage["audience_promise"]
    assert len(result.strengths) == 1

    # Re-rendering the panel (as refresh() already did inside the
    # handler via on_change) must not raise and must not lose the
    # stored result.
    view.refresh(job)
    assert "audience_promise" in view._last_review_by_stage


def test_resolve_review_artifact_prefers_creative_direction_over_bare_angle(
    qapp: QApplication,
) -> None:
    """
    Regression test (found via external audit): reviewing the
    "story_angles" stage previously always fed the Reviewer the bare
    selected StoryAngle, even after Phase 6 added CreativeDirection
    (narrative thesis, constraints, combined-angle note) as a richer
    wrapper - so that data was never actually reviewable.
    """
    from src.models.creative_direction import CreativeDirection
    from src.models.story_angle import StoryAngle, StoryAngleStyle

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)

    angle = StoryAngle(
        style=StoryAngleStyle.MYSTERY,
        title="The Missing Logbook",
        description="Told through the ship's missing final log entry.",
    )
    job.selected_story_angle = angle

    # Before Creative Direction exists, the bare angle is still what
    # gets reviewed - nothing regresses for a project that hasn't used
    # the Phase 6 workflow yet.
    resolved = view._resolve_review_artifact(
        job, "story_angles", "selected_story_angle"
    )
    assert resolved is angle

    job.creative_direction = CreativeDirection(
        selected_angle=angle,
        narrative_thesis="The crew's fate was sealed by the missing logbook.",
        constraints=["No supernatural framing"],
    )

    resolved = view._resolve_review_artifact(
        job, "story_angles", "selected_story_angle"
    )
    assert resolved is job.creative_direction


def test_switching_projects_clears_stale_review_results(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.provider_preferences.reviewer.reviewer_profile_id = "reviewer-main"
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_ci_stage("audience_promise")

    view._handle_review_ci_stage(
        stage_key="audience_promise",
        artifact_type=ArtifactType.AUDIENCE_STRATEGY,
        field_name="audience_promise",
    )
    assert view._last_review_by_stage

    other_job = _job()
    job_store.add(other_job)
    view.set_job(other_job.id)

    assert view._last_review_by_stage == {}


def test_running_stages_in_order_reaches_a_generated_script(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    for stage_key, _label in _CI_STAGES:
        if stage_key == "revision":
            # Revision only has work to do when the critique raised a
            # finding - the echo stub's dry-run critique never does,
            # so running it here would be running it out of order on
            # purpose, not exercising the normal sequence.
            continue

        view._handle_run_ci_stage(stage_key)
        view.refresh(job)

    assert job.generated_script is not None
    assert job.continuity_bible is not None
    assert job.continuity_validation is not None
    assert job.editorial_critique is not None
    assert job.script_quality_report is not None
    assert job.packaging_hypothesis is not None
    assert len(job.scenes) > 0
    assert not job.errors
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 1


def test_toggling_the_script_version_lock_flips_its_state(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")
    view._handle_run_ci_stage("narrative_architecture")
    view._handle_run_ci_stage("hooks")
    view._handle_run_ci_stage("script")

    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is False

    view._handle_toggle_script_version_lock()
    assert job.script_version_history.is_locked is True

    view._handle_toggle_script_version_lock()
    assert job.script_version_history.is_locked is False


def test_running_a_stage_out_of_order_records_an_error_not_a_crash(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # show_recoverable_error() opens a real modal dialog and blocks
    # forever under the offscreen Qt platform (no display to dismiss
    # it) - same guard test_desktop_app_integration.py's
    # no_blocking_dialogs fixture applies for every other view.
    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    # Script requires every upstream stage - none have run yet.
    view._handle_run_ci_stage("script")

    assert job.generated_script is None
    assert len(job.errors) == 1
    assert "Content Intelligence stage failed" in job.errors[0]


def test_unknown_job_id_does_not_crash_stage_handlers(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)
    view.set_job(uuid4())

    view._handle_run_ci_stage("audience_promise")  # must not raise


def test_approval_history_card_builds_without_error_when_empty(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise, even with no content_decisions yet

    assert job.content_decisions == []


def test_running_a_review_gated_stage_records_a_pending_decision(
    qapp: QApplication,
) -> None:
    from src.services.approval_gate_service import ApprovalGateService

    job_store = InMemoryJobStore()
    job = _job()  # default policy REVIEWs story_angle
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")
    view.refresh(job)

    pending = ApprovalGateService.latest_pending(job)
    assert pending is not None
    assert pending.approval is not None
    assert pending.approval.decision_point == "story_angle"


def test_approve_button_handler_resolves_the_pending_decision(
    qapp: QApplication,
) -> None:
    from src.models.approval import ApprovalState
    from src.services.approval_gate_service import ApprovalGateService

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")

    assert ApprovalGateService.is_blocked(job, "story_angle") is True

    from src.models.approval import HumanApprovalAction

    view._handle_resolve_approval(HumanApprovalAction.APPROVE)

    assert ApprovalGateService.is_blocked(job, "story_angle") is False
    latest = job.content_decisions[-1]
    assert latest.approval is not None
    assert latest.approval.state == ApprovalState.APPROVED
    view.refresh(job)  # must not raise now that the decision is resolved


def test_resolve_approval_with_no_pending_decision_is_a_noop(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    from src.models.approval import HumanApprovalAction

    view._handle_resolve_approval(HumanApprovalAction.APPROVE)  # must not raise

    assert job.content_decisions == []


def test_generate_topic_candidates_populates_job(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_generate_topic_candidates(replace_existing=False)

    assert len(job.topic_candidates) == 3
    assert all(
        candidate.overall_score is not None for candidate in job.topic_candidates
    )


def test_generate_more_topic_candidates_appends_rather_than_replaces(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_generate_topic_candidates(replace_existing=False)
    view._handle_generate_topic_candidates(replace_existing=False)

    assert len(job.topic_candidates) == 6


def test_regenerate_all_topic_candidates_replaces_the_existing_list(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_generate_topic_candidates(replace_existing=False)
    view._handle_generate_topic_candidates(replace_existing=True)

    assert len(job.topic_candidates) == 3


def test_selecting_a_topic_candidate_records_it_as_selected(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_generate_topic_candidates(replace_existing=False)
    candidate = job.topic_candidates[0]
    view._handle_select_topic_candidate(candidate)

    assert job.selected_topic_candidate is candidate


def test_using_a_custom_topic_adds_it_unscored_and_selects_it(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    from PySide6.QtWidgets import QLineEdit

    text_input = QLineEdit("The lighthouse keeper who vanished")
    view._handle_use_custom_topic(text_input)

    assert job.selected_topic_candidate is not None
    assert job.selected_topic_candidate.is_custom is True
    assert job.selected_topic_candidate.overall_score is None
    assert job.topic_candidates[-1] is job.selected_topic_candidate


def test_using_a_blank_custom_topic_is_a_noop(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    from PySide6.QtWidgets import QLineEdit

    text_input = QLineEdit("   ")
    view._handle_use_custom_topic(text_input)

    assert job.topic_candidates == []
    assert job.selected_topic_candidate is None


def test_topic_card_builds_without_error_after_generation_and_selection(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_generate_topic_candidates(replace_existing=False)
    view._handle_select_topic_candidate(job.topic_candidates[0])
    view.refresh(job)  # must not raise with a populated topic card


def test_selecting_a_story_angle_overrides_the_pipelines_auto_selection(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")

    assert len(job.story_angles) > 1
    auto_selected = job.selected_story_angle
    assert auto_selected is not None
    other_angle = next(a for a in job.story_angles if a.title != auto_selected.title)

    view._handle_select_story_angle(other_angle)

    assert job.selected_story_angle is other_angle


def test_writing_a_custom_angle_appends_and_selects_it(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QComboBox, QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    from src.models.story_angle import StoryAngleStyle

    style_select = QComboBox()
    style_select.addItems([style.value for style in StoryAngleStyle])
    style_select.setCurrentText(StoryAngleStyle.HORROR.value)

    title_input = QLineEdit("The Dread Below")
    description_input = QLineEdit("A horror-focused framing of the disappearance.")

    original_count = len(job.story_angles)

    view._handle_write_custom_angle(
        style_select=style_select,
        title_input=title_input,
        description_input=description_input,
    )

    assert len(job.story_angles) == original_count + 1
    assert job.selected_story_angle is not None
    assert job.selected_story_angle.title == "The Dread Below"


def test_writing_a_custom_angle_with_blank_title_records_an_error_not_a_crash(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # show_recoverable_error() opens a real modal dialog and blocks
    # forever under the offscreen Qt platform - same guard as
    # test_running_a_stage_out_of_order_records_an_error_not_a_crash.
    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )

    from PySide6.QtWidgets import QComboBox, QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    from src.models.story_angle import StoryAngleStyle

    style_select = QComboBox()
    style_select.addItems([style.value for style in StoryAngleStyle])

    title_input = QLineEdit("")
    description_input = QLineEdit("A description without a title.")

    view._handle_write_custom_angle(
        style_select=style_select,
        title_input=title_input,
        description_input=description_input,
    )

    assert job.story_angles == []
    assert job.errors


def test_combining_two_story_angles_creates_a_creative_direction(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")

    base_angle = job.selected_story_angle
    assert base_angle is not None
    other_angle = next(a for a in job.story_angles if a.title != base_angle.title)

    view._handle_combine_story_angles(other_angle)

    assert job.creative_direction is not None
    combined_note = job.creative_direction.combined_angle_note
    assert combined_note is not None
    assert job.creative_direction.selected_angle.title == base_angle.title
    assert other_angle.title in combined_note
    assert base_angle.title in combined_note


def test_combining_without_a_selected_angle_is_a_noop(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    from src.models.story_angle import StoryAngle, StoryAngleStyle

    other_angle = StoryAngle(
        style=StoryAngleStyle.HORROR,
        title="An angle",
        description="A description.",
    )

    view._handle_combine_story_angles(other_angle)

    assert job.creative_direction is None


def test_saving_creative_direction_records_thesis_and_constraints(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")

    thesis_input = QLineEdit("The crew's fate was sealed by the missing logbook.")
    constraints_input = QLineEdit("No supernatural framing, Keep under 8 minutes")

    view._handle_save_creative_direction(
        thesis_input=thesis_input, constraints_input=constraints_input
    )

    assert job.creative_direction is not None
    assert job.creative_direction.narrative_thesis == (
        "The crew's fate was sealed by the missing logbook."
    )
    assert job.creative_direction.constraints == [
        "No supernatural framing",
        "Keep under 8 minutes",
    ]


def test_saving_creative_direction_without_a_selected_angle_is_a_noop(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    thesis_input = QLineEdit("A thesis.")
    constraints_input = QLineEdit("")

    view._handle_save_creative_direction(
        thesis_input=thesis_input, constraints_input=constraints_input
    )

    assert job.creative_direction is None


def test_story_angles_panel_builds_without_error_with_creative_direction_set(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")

    thesis_input = QLineEdit("A thesis.")
    constraints_input = QLineEdit("")

    view._handle_save_creative_direction(
        thesis_input=thesis_input, constraints_input=constraints_input
    )
    view.refresh(job)  # must not raise with a populated creative direction section


def test_adding_a_research_question_appends_a_stable_id_question(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    assert job.research_plan is not None

    original_count = len(job.research_plan.structured_questions)
    text_input = QLineEdit("What became of the lifeboat?")

    view._handle_add_research_question(text_input)

    assert len(job.research_plan.structured_questions) == original_count + 1
    assert job.research_plan.structured_questions[-1].text == (
        "What became of the lifeboat?"
    )
    assert job.research_plan.research_questions[-1] == "What became of the lifeboat?"


def test_adding_a_blank_research_question_is_a_noop(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    assert job.research_plan is not None

    original_count = len(job.research_plan.structured_questions)

    view._handle_add_research_question(QLineEdit("   "))

    assert len(job.research_plan.structured_questions) == original_count


def test_editing_a_research_question_preserves_its_id(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    assert job.research_plan is not None

    target = job.research_plan.structured_questions[0]
    original_id = target.id

    view._handle_edit_research_question(original_id, QLineEdit("A revised question?"))

    updated = job.research_plan.structured_questions[0]
    assert updated.id == original_id
    assert updated.text == "A revised question?"
    assert job.research_plan.research_questions[0] == "A revised question?"


def test_removing_the_last_research_question_records_an_error_not_a_crash(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    assert job.research_plan is not None

    # Remove every question one at a time - all but the last must
    # succeed, and the last removal must be rejected rather than
    # leaving an empty, unusable brief.
    question_ids = [q.id for q in job.research_plan.structured_questions]

    for question_id in question_ids[:-1]:
        view._handle_remove_research_question(question_id)

    assert len(job.research_plan.structured_questions) == 1

    view._handle_remove_research_question(question_ids[-1])

    assert len(job.research_plan.structured_questions) == 1
    assert job.errors


def test_research_plan_auto_approves_and_research_stage_is_runnable(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")

    assert job.research is not None


def test_approve_research_brief_unblocks_the_research_stage(
    qapp: QApplication,
) -> None:
    from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig

    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig(research_plan=ApprovalPolicy.REVIEW)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view.refresh(job)

    from src.services.approval_gate_service import ApprovalGateService

    assert ApprovalGateService.is_blocked(job, "research_plan") is True

    view._handle_approve_research_brief()

    assert ApprovalGateService.is_blocked(job, "research_plan") is False

    view._handle_run_ci_stage("research")

    assert job.research is not None


def _run_through_research(view: ContentStudioView, job: VideoJob) -> None:
    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    assert job.research is not None


def test_adding_a_research_source_appends_it_accepted(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    original_count = len(job.research.sources)

    view._handle_add_research_source(
        title_input=QLineEdit("A new primary source"),
        url_input=QLineEdit("https://example.com/source"),
    )

    assert len(job.research.sources) == original_count + 1
    added = job.research.sources[-1]
    assert added.title == "A new primary source"
    from src.models.research import SourceStatus

    assert added.status == SourceStatus.ACCEPTED


def test_toggling_a_source_status_rejects_then_restores(qapp: QApplication) -> None:
    from src.models.research import SourceStatus

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    source = job.research.sources[0]
    assert source.status == SourceStatus.ACCEPTED

    view._handle_toggle_source_status(source.id)
    assert job.research.sources[0].status == SourceStatus.REJECTED

    view._handle_toggle_source_status(source.id)
    assert job.research.sources[0].status == SourceStatus.ACCEPTED


def test_adding_a_manual_research_edit_starts_unverified(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    view._handle_add_manual_research_edit(QLineEdit("A note I typed myself."))

    assert len(job.research.manual_edits) == 1
    assert job.research.manual_edits[0].is_verified is False


def test_fact_check_again_on_a_supported_claim_adds_a_structured_fact(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    view._handle_add_manual_research_edit(QLineEdit("The ship was seaworthy."))
    edit_id = job.research.manual_edits[0].id

    # The shared echo stub always returns the dry-run fact-check
    # response, which is a supported result - see FactCheckService's
    # own _DRY_RUN_RESPONSE.
    view._handle_fact_check_again(edit_id)

    assert job.research.manual_edits[0].is_verified is True
    assert job.research.manual_edits[0].verification_notes is not None
    assert len(job.research.structured_facts) == 1
    assert job.research.structured_facts[0].is_supported is True


def test_fact_check_again_on_an_unsupported_claim_leaves_it_unverified(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    from src.models.research_evidence import FactCheckResult

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    view._handle_add_manual_research_edit(QLineEdit("An unverifiable claim."))
    edit_id = job.research.manual_edits[0].id

    view._fact_check_service.check = lambda **kwargs: FactCheckResult(  # type: ignore[method-assign]
        claim_text=kwargs["claim_text"],
        is_supported=False,
        confidence=10,
        matched_source_ids=[],
        reasoning="No source supports this.",
    )

    view._handle_fact_check_again(edit_id)

    assert job.research.manual_edits[0].is_verified is False
    assert job.research.manual_edits[0].verification_notes == "No source supports this."
    assert job.research.structured_facts == []


def test_fact_check_supported_with_no_matched_sources_stays_unverified(
    qapp: QApplication,
) -> None:
    """
    Regression test (found via external audit): a FactCheckResult that
    says is_supported=True but names no matched_source_ids used to mark
    the manual edit "verified" (green) while creating a ResearchFact
    with empty evidence, which itself shows as unsupported (amber) -
    a visible contradiction from one click. Both must now agree: not
    verified, and no phantom fact created.
    """

    from PySide6.QtWidgets import QLineEdit

    from src.models.research_evidence import FactCheckResult

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    view._handle_add_manual_research_edit(QLineEdit("An ambiguously-supported claim."))
    edit_id = job.research.manual_edits[0].id

    view._fact_check_service.check = lambda **kwargs: FactCheckResult(  # type: ignore[method-assign]
        claim_text=kwargs["claim_text"],
        is_supported=True,
        confidence=60,
        matched_source_ids=[],
        reasoning="This seems generally true.",
    )

    view._handle_fact_check_again(edit_id)

    assert job.research.manual_edits[0].is_verified is False
    assert job.research.structured_facts == []


def test_adding_and_removing_a_research_gap(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    view._handle_add_research_gap(QLineEdit("No information on the lifeboat's fate."))

    assert job.research.research_gaps == ["No information on the lifeboat's fate."]

    view._handle_remove_research_gap("No information on the lifeboat's fate.")

    assert job.research.research_gaps == []


def test_research_panel_builds_without_error_with_evidence_ledger_populated(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_research(view, job)
    assert job.research is not None

    view._handle_add_research_source(
        title_input=QLineEdit("Another source"), url_input=QLineEdit("")
    )
    view._handle_add_manual_research_edit(QLineEdit("A claim to check."))
    edit_id = job.research.manual_edits[0].id
    view._handle_fact_check_again(edit_id)
    view._handle_add_research_gap(QLineEdit("A remaining gap."))

    view.refresh(job)  # must not raise with a fully populated evidence ledger


def test_regenerating_narrative_architecture_with_instructions(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")
    view._handle_run_ci_stage("narrative_architecture")

    assert job.story_blueprint is not None
    research_before = job.research

    view._handle_regenerate_narrative_architecture(
        QLineEdit("Compress the slow middle section.")
    )

    assert job.story_blueprint is not None
    assert job.research is research_before


def test_narrative_architecture_panel_builds_without_error_with_evidence_bound(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")
    view._handle_run_ci_stage("narrative_architecture")

    view.refresh(job)  # must not raise with beats + reveal map populated


def _run_through_hooks(view: ContentStudioView, job: VideoJob) -> None:
    view._handle_run_ci_stage("audience_promise")
    view._handle_run_ci_stage("research_plan")
    view._handle_run_ci_stage("research")
    view._handle_run_ci_stage("story_angles")
    view._handle_run_ci_stage("narrative_architecture")
    view._handle_run_ci_stage("hooks")


def test_selecting_a_hook_overrides_the_pipelines_auto_selection(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_hooks(view, job)

    assert job.selected_hook is not None
    auto_selected_text = job.selected_hook.hook_text
    other_hook = next(h for h in job.hook_candidates if h.text != auto_selected_text)

    view._handle_select_hook(other_hook)

    assert job.selected_hook is not None
    assert job.selected_hook.hook_text == other_hook.text


def test_writing_a_custom_hook_appends_and_selects_it_unscored(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_hooks(view, job)

    original_count = len(job.hook_candidates)

    view._handle_write_custom_hook(QLineEdit("The night the lighthouse went dark."))

    assert len(job.hook_candidates) == original_count + 1
    assert job.selected_hook is not None
    assert job.selected_hook.hook_text == "The night the lighthouse went dark."
    assert job.selected_hook.is_custom is True


def test_writing_a_blank_custom_hook_is_a_noop(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_hooks(view, job)

    original_count = len(job.hook_candidates)

    view._handle_write_custom_hook(QLineEdit("   "))

    assert len(job.hook_candidates) == original_count


def test_generate_more_hooks_appends_and_reevaluates_all_candidates(
    qapp: QApplication,
) -> None:
    from src.models.hook import HookCandidate

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_hooks(view, job)

    original_count = len(job.hook_candidates)

    # The shared echo-stub always returns the same 5 canned dry-run
    # hook texts, which HookEvaluationService's legitimate text-based
    # dedup would then collapse - stub generation directly here so
    # "Generate more" produces genuinely distinct text, the way a real
    # LLM call would.
    view._content_intelligence_pipeline.hook_generation_service.generate = (  # type: ignore[method-assign]
        lambda **kwargs: [HookCandidate(text="A brand new hook candidate.")]
    )

    view._handle_generate_more_hooks()

    assert len(job.hook_candidates) > original_count
    assert len(job.hook_evaluations) == len(job.hook_candidates)


def test_rewrite_hooks_with_instructions_regenerates_the_candidate_set(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_hooks(view, job)

    view._handle_rewrite_hooks_with_instructions(QLineEdit("Make it more suspenseful."))

    assert job.selected_hook is not None
    assert len(job.hook_evaluations) == len(job.hook_candidates)


def test_hooks_panel_builds_without_error_after_generate_more_and_custom_hook(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_hooks(view, job)

    view._handle_generate_more_hooks()
    view._handle_write_custom_hook(QLineEdit("A hook I wrote myself."))

    view.refresh(job)  # must not raise with a mixed generated+custom hook set


def _run_through_writing_directives(view: ContentStudioView, job: VideoJob) -> None:
    _run_through_hooks(view, job)
    view._handle_run_ci_stage("writing_directives")


def test_running_writing_directives_produces_system_and_overridable_directives(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_writing_directives(view, job)

    assert job.writing_directives is not None
    assert len(job.writing_directives.system_directives) == 3


def test_adding_and_removing_a_project_writing_rule(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_add_project_writing_rule(
        QLineEdit("Keep the runtime under 8 minutes.")
    )

    assert job.project_writing_rules == ["Keep the runtime under 8 minutes."]

    view._handle_remove_project_writing_rule("Keep the runtime under 8 minutes.")

    assert job.project_writing_rules == []


def test_adding_a_blank_project_writing_rule_is_a_noop(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_add_project_writing_rule(QLineEdit("   "))

    assert job.project_writing_rules == []


def test_adding_and_removing_a_user_writing_directive(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_add_user_writing_directive(QLineEdit("Avoid rhetorical questions."))

    assert job.user_writing_directives == ["Avoid rhetorical questions."]

    view._handle_remove_user_writing_directive("Avoid rhetorical questions.")

    assert job.user_writing_directives == []


def test_writing_directives_resolution_includes_project_rules_and_user_directives(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_add_project_writing_rule(
        QLineEdit("Keep the runtime under 8 minutes.")
    )
    view._handle_add_user_writing_directive(QLineEdit("Avoid rhetorical questions."))

    _run_through_writing_directives(view, job)

    assert job.writing_directives is not None
    all_text = " ".join(d.text for d in job.writing_directives.directives)
    # The echo-stub's dry-run response doesn't literally echo these
    # back, but resolution must not fail with them populated, and the
    # inputs themselves must be preserved on the job regardless.
    assert "Keep the runtime under 8 minutes." in job.project_writing_rules
    assert "Avoid rhetorical questions." in job.user_writing_directives
    assert all_text  # sanity: a real directive set was produced


def test_writing_directives_panel_builds_without_error(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_writing_directives(view, job)

    view.refresh(job)  # must not raise with a populated directive set


def _run_through_script(view: ContentStudioView, job: VideoJob) -> None:
    _run_through_writing_directives(view, job)
    view._handle_run_ci_stage("script")
    # The script panel (and its per-segment editors) only builds while
    # "script" is the selected CI stage - _render_ci_script_panel is
    # gated the same way every other per-stage panel in this view is.
    script_index = next(
        index for index, (key, _label) in enumerate(_CI_STAGES) if key == "script"
    )
    view._handle_select_ci_stage(script_index)


def test_script_editor_panel_builds_without_error(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)

    view.refresh(job)  # must not raise with a populated script + editors built

    assert job.generated_script is not None
    assert set(view._script_segment_editors) == {
        segment.segment_number for segment in job.generated_script.segments
    }


def test_selection_edit_updates_only_the_target_segment(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target = job.generated_script.segments[0].segment_number
    other_narrations_before = {
        segment.segment_number: segment.narration
        for segment in job.generated_script.segments
        if segment.segment_number != target
    }

    from src.models.script_selection_edit import SelectionEditOperation

    view._handle_script_selection_edit(target, SelectionEditOperation.REWRITE)

    assert job.generated_script is not None
    other_narrations_after = {
        segment.segment_number: segment.narration
        for segment in job.generated_script.segments
        if segment.segment_number != target
    }
    assert other_narrations_after == other_narrations_before
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2


def test_custom_selection_edit_uses_the_instruction_input(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target = job.generated_script.segments[0].segment_number
    instruction_input = QLineEdit("Make it sound like a news anchor.")

    view._handle_script_custom_selection_edit(target, instruction_input)

    assert instruction_input.text() == ""
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2


def test_custom_selection_edit_with_blank_instruction_is_a_noop(
    qapp: QApplication,
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target = job.generated_script.segments[0].segment_number

    view._handle_script_custom_selection_edit(target, QLineEdit("   "))

    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 1


def test_save_typed_edit_records_a_manual_edit_version(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target_segment = job.generated_script.segments[0].segment_number
    editor = view._script_segment_editors[target_segment]
    editor.setPlainText("A person typed this narration directly.")

    view._handle_save_script_segment_edit(target_segment)

    assert job.generated_script is not None
    edited = next(
        s for s in job.generated_script.segments if s.segment_number == target_segment
    )
    assert edited.narration == "A person typed this narration directly."
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2
    assert (
        job.script_version_history.current_version.reason == VersionReason.MANUAL_EDIT
    )


def test_save_typed_edit_invalidates_downstream_production_artifacts(
    qapp: QApplication,
) -> None:
    """
    Regression test (found via external audit): unlike
    run_revision()/run_script_selection_edit()/run_script_restore(),
    this GUI-only, non-LLM typed-edit path never called
    InvalidationService - a person could retype a segment's narration
    after scenes/clips/timeline already existed and none of them
    would be flagged stale. Mirrors
    test_run_revision_invalidates_only_the_downstream_artifacts_that_exist
    in test_invalidation_matrix_wiring.py.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target_segment = job.generated_script.segments[0].segment_number

    # Simulate a person who already ran scene planning and clip
    # resolution before going back to hand-edit a segment - the exact
    # re-entry scenario on_script_changed() exists to catch.
    job.scenes = [
        Scene(
            scene_number=1,
            title="Scene one",
            narration="Something happens.",
            visual_prompt="A dark hallway.",
            estimated_duration_seconds=8,
        )
    ]
    job.video_clips = [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=5,
            local_file="clip.mp4",
        )
    ]
    job.video_timeline = VideoTimeline()

    editor = view._script_segment_editors[target_segment]
    editor.setPlainText("A person typed this narration directly.")

    view._handle_save_script_segment_edit(target_segment)

    stale_names = {record.artifact for record in job.stale_artifacts}
    assert stale_names == {"scenes", "video_clips", "video_timeline"}
    assert all(record.triggered_by == "script_change" for record in job.stale_artifacts)


def test_save_typed_edit_with_unchanged_text_is_a_noop(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target_segment = job.generated_script.segments[0].segment_number

    view._handle_save_script_segment_edit(target_segment)

    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 1


def test_restore_version_button_creates_a_new_version(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    original_narration = job.generated_script.full_narration
    target_segment = job.generated_script.segments[0].segment_number

    from src.models.script_selection_edit import SelectionEditOperation

    view._handle_script_selection_edit(target_segment, SelectionEditOperation.REWRITE)
    assert job.generated_script.full_narration != original_narration

    view._handle_restore_script_version(1)

    assert job.generated_script is not None
    assert job.generated_script.full_narration == original_narration
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 3
    assert job.script_version_history.current_version.reason == VersionReason.RESTORE


def test_compare_versions_produces_a_diff(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)

    assert job.generated_script is not None
    target_segment = job.generated_script.segments[0].segment_number

    from src.models.script_selection_edit import SelectionEditOperation

    view._handle_script_selection_edit(target_segment, SelectionEditOperation.REWRITE)
    view.refresh(job)  # rebuilds the compare selectors for the new version

    assert view._script_compare_from is not None
    assert view._script_compare_to is not None
    view._script_compare_from.setCurrentIndex(0)
    view._script_compare_to.setCurrentIndex(view._script_compare_to.count() - 1)

    view._handle_compare_script_versions()

    assert view._last_script_comparison is not None
    assert view._last_script_comparison.has_changes is True


def test_locked_version_hides_edit_controls(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)

    view._handle_toggle_script_version_lock()
    view.refresh(job)

    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is True
    assert job.generated_script is not None

    for editor in view._script_segment_editors.values():
        assert editor.isReadOnly() is True


class _FindingStubLLMService:
    """
    Mirrors test_content_intelligence_pipeline.py's stub of the same
    name: echoes every stage except EditorialCritiqueService, which
    returns one fixed blocking narrative_coherence finding, so the
    Quality Gate panel has a real, actionable finding to render.
    """

    def __init__(self) -> None:
        self.echo = _EchoStubLLMService()

    def generate(
        self,
        request: LLMRequest,
        *,
        estimated_cost_usd: float = 0.0,
        profile_ids: list[str] | None = None,
    ) -> LLMServiceResult:
        if request.metadata.get("agent") == "EditorialCritiqueService":
            content = (
                "FACTUAL_CONFIDENCE: 80\n"
                "HOOK_STRENGTH: 80\n"
                "RETENTION_ARCHITECTURE: 80\n"
                "EMOTIONAL_PROGRESSION: 80\n"
                "RESEARCH_GROUNDING: 80\n"
                "NARRATIVE_COHERENCE: 80\n"
                "AUDIENCE_FIT: 80\n"
                "VISUAL_OPPORTUNITY_DENSITY: 80\n"
                "CHARACTER_DEPTH: 80\n"
                "PAYOFF_STRENGTH: 80\n"
                "CONTINUITY: 80\n"
                "---\n"
                "DIMENSION: narrative_coherence\n"
                "SEVERITY: blocking\n"
                "SEGMENT_NUMBER: none\n"
                "PROBLEM: Unsupported claim about the crew's fate.\n"
                "REASON: No source in research backs this claim.\n"
                "RECOMMENDED_CORRECTION: Remove or attribute the claim."
            )

            result = LLMCallResult(
                status=LLMCallStatus.SUCCESS,
                provider=LLMProvider.OPENAI,
                model="test-model",
                content=content,
            )

            return LLMServiceResult(
                result=result,
                selected_profile_id="test-profile",
                all_providers_failed=False,
            )

        return self.echo.generate(
            request, estimated_cost_usd=estimated_cost_usd, profile_ids=profile_ids
        )


def _view_with_finding_stub(job_store: InMemoryJobStore) -> ContentStudioView:
    stub = _FindingStubLLMService()

    return ContentStudioView(
        job_store=job_store,
        content_pipeline=ContentPipeline(llm_service=stub),  # type: ignore[arg-type]
        content_intelligence_pipeline=ContentIntelligencePipeline(
            llm_service=stub  # type: ignore[arg-type]
        ),
        reviewer_service=ReviewerService(llm_service=stub),  # type: ignore[arg-type]
        topic_candidate_generation_service=TopicCandidateGenerationService(
            llm_service=stub  # type: ignore[arg-type]
        ),
        fact_check_service=FactCheckService(llm_service=stub),  # type: ignore[arg-type]
        on_change=lambda: None,
    )


def _job_with_quality_gate_finding(view: ContentStudioView, job: VideoJob) -> None:
    _run_through_script(view, job)
    view._handle_run_ci_stage("editorial_critique")
    view._handle_run_ci_stage("quality_gate")
    quality_gate_index = next(
        index for index, (key, _label) in enumerate(_CI_STAGES) if key == "quality_gate"
    )
    view._handle_select_ci_stage(quality_gate_index)


def test_quality_gate_panel_renders_a_checkbox_per_unresolved_finding(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view_with_finding_stub(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _job_with_quality_gate_finding(view, job)
    view.refresh(job)

    assert job.script_quality_report is not None
    assert len(job.script_quality_report.blocking_findings) == 1
    assert len(view._quality_finding_checkboxes) == 1


def test_apply_selected_fixes_revises_only_the_checked_findings(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view_with_finding_stub(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _job_with_quality_gate_finding(view, job)
    view.refresh(job)

    for checkbox in view._quality_finding_checkboxes.values():
        checkbox.setChecked(True)

    view._handle_apply_selected_fixes()

    assert job.editorial_critique is None
    assert job.script_quality_report is None
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 2


def test_fix_all_safe_issues_is_a_noop_when_the_only_finding_is_blocking(
    qapp: QApplication,
) -> None:
    """
    The stub's one finding is BLOCKING, which is never "safe to
    auto-fix" - Fix All Safe Issues must not touch it.
    """

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view_with_finding_stub(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _job_with_quality_gate_finding(view, job)
    view.refresh(job)

    view._handle_fix_all_safe_issues()

    assert job.script_quality_report is not None
    assert job.script_version_history is not None
    assert job.script_version_history.current_version.version_number == 1


def test_ignore_with_reason_records_a_resolution(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view_with_finding_stub(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _job_with_quality_gate_finding(view, job)
    view.refresh(job)

    assert job.script_quality_report is not None
    finding_id = job.script_quality_report.blocking_findings[0].id

    view._handle_ignore_quality_finding(
        finding_id, QLineEdit("Acceptable creative license for this project.")
    )

    assert job.script_quality_report is not None
    resolution = job.script_quality_report.resolution_for(finding_id)
    assert resolution is not None
    assert resolution.reason == "Acceptable creative license for this project."


def test_ignore_with_a_blank_reason_is_a_noop(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view_with_finding_stub(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _job_with_quality_gate_finding(view, job)
    view.refresh(job)

    assert job.script_quality_report is not None
    finding_id = job.script_quality_report.blocking_findings[0].id

    view._handle_ignore_quality_finding(finding_id, QLineEdit("   "))

    assert job.script_quality_report.resolution_for(finding_id) is None


def test_return_to_script_selects_the_script_stage(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view_with_finding_stub(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _job_with_quality_gate_finding(view, job)

    view._handle_return_to_script()

    script_index = next(
        index for index, (key, _label) in enumerate(_CI_STAGES) if key == "script"
    )
    assert view._selected_ci_stage_index == script_index


def _confirm_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )


def _confirm_no(monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )


def test_lock_script_with_confirmation_locks_the_current_version(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)
    _confirm_yes(monkeypatch)

    view._handle_lock_script(QLineEdit())

    assert job.script_lock is not None
    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is True


def test_lock_script_declining_confirmation_leaves_it_unlocked(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)
    _confirm_no(monkeypatch)

    view._handle_lock_script(QLineEdit())

    assert job.script_lock is None


def test_unlock_script_with_confirmation_clears_the_lock(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)
    _confirm_yes(monkeypatch)
    view._handle_lock_script(QLineEdit())
    assert job.script_lock is not None

    view._handle_unlock_script()

    assert job.script_lock is None
    assert job.script_version_history is not None
    assert job.script_version_history.is_locked is False


def test_unlock_script_declining_confirmation_leaves_it_locked(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)
    _confirm_yes(monkeypatch)
    view._handle_lock_script(QLineEdit())
    assert job.script_lock is not None

    _confirm_no(monkeypatch)
    view._handle_unlock_script()

    assert job.script_lock is not None


def test_script_lock_section_renders_without_error_when_locked(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)
    _confirm_yes(monkeypatch)
    view._handle_lock_script(QLineEdit())

    view.refresh(job)  # must not raise while rendering the locked state


def _select_script_stage(view: ContentStudioView) -> None:
    script_index = next(
        index for index, (key, _label) in enumerate(_CI_STAGES) if key == "script"
    )
    view._handle_select_ci_stage(script_index)


def test_script_intake_section_renders_before_any_script_exists(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    assert view._script_intake_editor is not None
    assert view._script_intake_mode_select is not None


def test_import_script_creates_a_generated_script(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    assert view._script_intake_editor is not None
    view._script_intake_editor.setPlainText("Imported narration text.")

    view._handle_import_script()

    assert job.generated_script is not None
    assert job.generated_script.full_narration == "Imported narration text."
    assert job.script_intake_result is not None
    assert job.script_version_history is not None


def test_import_script_with_blank_text_is_a_noop(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    view._handle_import_script()

    assert job.generated_script is None


def test_script_intake_summary_renders_after_import(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    assert view._script_intake_editor is not None
    view._script_intake_editor.setPlainText("Imported narration text for the summary.")
    view._handle_import_script()

    view.refresh(job)  # must not raise while rendering the intake summary

    assert job.script_intake_result is not None


def test_imported_script_lock_defaults_to_external_provenance(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    assert view._script_intake_editor is not None
    view._script_intake_editor.setPlainText("Imported narration text.")
    view._handle_import_script()
    view.refresh(job)
    _confirm_yes(monkeypatch)

    view._handle_lock_script(QLineEdit())

    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.EXTERNAL


def test_generated_script_lock_stays_internal(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Regression test: _handle_lock_script() used to hardcode
    provenance=INTERNAL, silently overriding run_script_lock()'s own
    EXTERNAL-for-an-imported-script inference. This proves the normal
    Content Production path (no intake involved at all) still locks
    INTERNAL now that the hardcoded override is gone.
    """

    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    view.refresh(job)
    _confirm_yes(monkeypatch)

    view._handle_lock_script(QLineEdit())

    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.INTERNAL


def test_upload_script_file_reads_text_into_the_intake_editor(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script_file = tmp_path / "script.txt"
    script_file.write_text("Uploaded narration text.", encoding="utf-8")

    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(script_file), "Text files (*.txt)"),
    )

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    view._handle_upload_script_file()

    assert view._script_intake_editor is not None
    assert view._script_intake_editor.toPlainText() == "Uploaded narration text."


def test_upload_script_file_cancelled_is_a_noop(
    qapp: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "src.desktop.views.content_studio_view.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _select_script_stage(view)
    view.refresh(job)

    view._handle_upload_script_file()

    assert view._script_intake_editor is not None
    assert view._script_intake_editor.toPlainText() == ""


def _select_production_readiness_stage(view: ContentStudioView) -> None:
    index = next(
        i for i, (key, _label) in enumerate(_CI_STAGES) if key == "production_readiness"
    )
    view._handle_select_ci_stage(index)


def test_production_readiness_panel_renders_before_any_ambiguities(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    _select_production_readiness_stage(view)
    view.refresh(job)  # must not raise


def test_run_production_readiness_stage_detects_ambiguities(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    _select_production_readiness_stage(view)
    view.refresh(job)

    view._handle_run_ci_stage("production_readiness")

    assert len(job.production_ambiguities) >= 1


def test_resolve_ambiguity_manually_from_the_panel(qapp: QApplication) -> None:
    from PySide6.QtWidgets import QLineEdit

    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    _select_production_readiness_stage(view)
    view.refresh(job)
    view._handle_run_ci_stage("production_readiness")

    target_id = job.production_ambiguities[0].id
    view._handle_resolve_ambiguity_manually(
        target_id, QLineEdit("Confirmed by the editor.")
    )

    resolved = next(a for a in job.production_ambiguities if a.id == target_id)
    assert resolved.status.value == "resolved_manually"


def test_resolve_ambiguity_by_ai_from_the_panel(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    _select_production_readiness_stage(view)
    view.refresh(job)
    view._handle_run_ci_stage("production_readiness")

    target_id = job.production_ambiguities[0].id
    view._handle_resolve_ambiguity_by_ai(target_id)

    resolved = next(a for a in job.production_ambiguities if a.id == target_id)
    assert resolved.status.value == "resolved_by_ai"
    assert resolved.resolution_note is not None


def test_production_readiness_panel_renders_after_resolving_ambiguities(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_through_script(view, job)
    _select_production_readiness_stage(view)
    view.refresh(job)
    view._handle_run_ci_stage("production_readiness")

    target_id = job.production_ambiguities[0].id
    view._handle_resolve_ambiguity_by_ai(target_id)

    view.refresh(job)  # must not raise while rendering a resolved ambiguity


def test_automation_status_renders_before_any_stage_runs(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise


def test_run_automation_runs_the_whole_pipeline(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_automation()

    assert job.generated_script is not None
    assert job.scenes


def test_run_automation_pauses_and_status_reflects_it(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.manual_editorial()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_automation()
    view.refresh(job)  # must not raise while rendering the paused state

    status = view._content_intelligence_pipeline.compute_automation_status(job)
    assert status.is_paused is True


def test_run_automation_resume_does_not_regenerate_completed_stages(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_automation()
    first_script = job.generated_script

    view._handle_run_automation()

    assert job.generated_script is first_script


# --- Phase 18: Activity History ---


def test_activity_history_card_builds_without_error_when_empty(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise, even with no content_decisions yet

    assert job.content_decisions == []


def test_activity_history_shows_generation_events_beyond_approval_gates(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_automation()
    view.refresh(job)  # must not raise while rendering the full timeline

    stages_recorded = {record.stage for record in job.content_decisions}

    # Stages that never had an approval gate of their own (Phase 18's
    # actual gap) must still show up in the ledger.
    assert "scene_planning" in stages_recorded
    assert "continuity_bible" in stages_recorded
    assert "quality_gate" in stages_recorded


def test_activity_history_category_filter_persists_across_refresh(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()

    view._handle_activity_history_category_filter_changed("generation")

    assert view._activity_history_category_filter == "generation"

    view.refresh(job)  # must not raise while filtered

    assert view._activity_history_category_filter == "generation"


def test_activity_history_stage_filter_persists_across_refresh(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()

    view._handle_activity_history_stage_filter_changed("scene_planning")

    assert view._activity_history_stage_filter == "scene_planning"

    view.refresh(job)  # must not raise while filtered


def test_set_job_resets_activity_history_filters(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view._activity_history_category_filter = "lock"
    view._activity_history_stage_filter = "script_lock"

    view.set_job(uuid4())

    assert view._activity_history_category_filter == "all"
    assert view._activity_history_stage_filter == "all"


def test_script_lock_and_unlock_are_recorded_in_activity_history(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()

    # Content Studio Redesign, Phase 19: full_auto() automation now
    # runs the script all the way through run_script_lock() itself
    # (see ContentIntelligencePipeline.run_all()), so the lock already
    # exists here - no separate explicit lock call is needed.
    pipeline = view._content_intelligence_pipeline
    assert job.script_lock is not None
    assert job.script_lock.provenance == ScriptProvenance.INTERNAL

    lock_records = [
        record
        for record in job.content_decisions
        if record.stage == "script_lock" and record.effective_category.value == "lock"
    ]
    assert len(lock_records) == 1

    pipeline.run_script_unlock(job)

    unlock_records = [
        record
        for record in job.content_decisions
        if record.stage == "script_lock" and record.effective_category.value == "unlock"
    ]
    assert len(unlock_records) == 1

    view.refresh(job)  # must not raise with lock/unlock events present


# --- Phase 19: legacy pipeline redirect notice ---


def test_legacy_pipeline_notice_shows_on_a_fresh_project(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise while the notice renders

    assert ContentStudioView._should_show_legacy_pipeline_notice(job) is True


def test_legacy_pipeline_notice_is_suppressed_once_a_path_is_chosen(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_ci_stage("audience_promise")

    assert ContentStudioView._should_show_legacy_pipeline_notice(job) is False

    view.refresh(job)  # must not raise once the notice is suppressed


# --- Post-Script-Approval Production Plan, Phase 0: Production Handoff ---


def test_production_handoff_card_is_absent_without_a_script(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise; job.generated_script is None


def test_production_handoff_reaches_package_ready_after_full_automation(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view.refresh(job)  # must not raise while the handoff card renders

    from src.models.production_handoff import ProductionHandoffState

    status = view._content_intelligence_pipeline.compute_production_handoff_status(job)
    assert status.state == ProductionHandoffState.PACKAGE_READY


def test_retry_production_handoff_button_replans_scenes(qapp: QApplication) -> None:
    from src.models.production_handoff import ProductionHandoffState

    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()

    pipeline = view._content_intelligence_pipeline
    pipeline.invalidation_service.on_script_changed(job)
    status = pipeline.compute_production_handoff_status(job)
    assert status.state == ProductionHandoffState.BUILDING_PACKAGE

    view.refresh(job)
    view._handle_run_ci_stage("scene_planning")

    status_after = pipeline.compute_production_handoff_status(job)
    assert status_after.state == ProductionHandoffState.PACKAGE_READY


# --- Post-Script-Approval Production Plan, Phase 1: Production Semantic Brief ---


def test_production_directives_section_renders_generate_button_when_absent(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view.refresh(job)  # must not raise; script_lock exists, brief does not yet

    assert job.script_lock is not None
    assert job.production_semantic_brief is None


def test_generate_production_directives_populates_the_brief(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()

    view._handle_generate_production_semantic_brief()

    assert job.production_semantic_brief is not None
    assert len(job.production_semantic_brief.segments) == len(
        job.generated_script.segments
    )

    view.refresh(job)  # must not raise while the brief renders


def test_generate_production_directives_is_a_noop_without_a_job(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)

    view._handle_generate_production_semantic_brief()  # must not raise


# --- Post-Script-Approval Production Plan, Phase 2: Visual Continuity Bible ---


def test_visual_continuity_section_absent_without_scenes_or_lock(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise; nothing to show yet


def test_generate_visual_continuity_populates_the_bible(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()

    view._handle_generate_visual_continuity()

    assert job.visual_continuity_bible is not None
    assert len(job.visual_continuity_bible.clip_entries) == len(job.scenes)

    view.refresh(job)  # must not raise while the bible renders


def test_generate_visual_continuity_is_a_noop_without_a_job(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)

    view._handle_generate_visual_continuity()  # must not raise


# --- Post-Script-Approval Production Plan, Phase 3: Cinematic Shot Plan ---


def test_shot_planning_section_absent_without_visual_continuity(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view.refresh(job)  # must not raise; no visual continuity bible yet


def test_generate_shot_plan_populates_the_plan(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view._handle_generate_visual_continuity()

    view._handle_generate_shot_plan()

    assert job.cinematic_shot_plan is not None
    assert job.cinematic_shot_plan.has_exactly_one_shot_per_scene is True

    view.refresh(job)  # must not raise while the plan renders


def test_generate_shot_plan_is_a_noop_without_a_job(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)

    view._handle_generate_shot_plan()  # must not raise


# --- Post-Script-Approval Production Plan, Phase 4: Cinematic Prompt Package ---


def _run_to_shot_plan(view: ContentStudioView) -> None:
    view._handle_run_automation()
    view._handle_generate_visual_continuity()
    view._handle_generate_shot_plan()


def test_cinematic_prompt_section_absent_without_a_shot_plan(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view.refresh(job)  # must not raise; no shot plan yet


def test_compile_cinematic_prompts_populates_the_package(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_to_shot_plan(view)

    view._handle_compile_cinematic_prompts()

    assert job.cinematic_prompt_package is not None
    assert len(job.cinematic_prompt_package.prompts) == len(job.scenes)

    view.refresh(job)  # must not raise while the package renders


def test_score_cinematic_prompts_attaches_scores(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    _run_to_shot_plan(view)
    view._handle_compile_cinematic_prompts()

    view._handle_score_cinematic_prompts()

    assert job.cinematic_prompt_package is not None
    assert any(p.is_scored for p in job.cinematic_prompt_package.prompts)

    view.refresh(job)  # must not raise while scores render


def test_compile_cinematic_prompts_is_a_noop_without_a_job(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)

    view._handle_compile_cinematic_prompts()  # must not raise


def test_score_cinematic_prompts_is_a_noop_without_a_job(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)

    view._handle_score_cinematic_prompts()  # must not raise


# --- Post-Script-Approval Production Plan, Phase 5: Clip Materialization ---


def test_clip_materialization_section_renders_after_scenes_exist(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view.refresh(job)  # must not raise; scenes exist from full automation

    status = view._content_intelligence_pipeline.compute_clip_materialization_status(
        job
    )
    assert status.total_clips == len(job.scenes)


def test_clip_materialization_section_absent_without_scenes(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)  # must not raise; no scenes yet


# --- Post-Script-Approval Production Plan, Phase 6: Fulfillment Budget Gate ---


def test_clip_materialization_shows_budget_when_configured(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job()
    job.approval_policy = ApprovalPolicyConfig.full_auto()
    job.maximum_visual_budget = 100.0
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)
    view._handle_run_automation()
    view.refresh(job)  # must not raise while the budget banner renders

    status = view._content_intelligence_pipeline.compute_clip_materialization_status(
        job
    )
    assert status.has_budget_cap is True
