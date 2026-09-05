from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.content_studio_view import (  # noqa: E402
    _CI_STAGES,
    ContentStudioView,
)
from src.models.artifact_lifecycle import ArtifactType  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
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
