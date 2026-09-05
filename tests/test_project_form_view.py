from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.project_form_view import ProjectFormView  # noqa: E402
from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig  # noqa: E402


class _StubProviderProfileManagementService:
    """
    Minimal stand-in for ProviderProfileManagementService - ProjectFormView
    only calls list_profiles() during construction, so a real
    registry/repository/secret-manager stack is unnecessary for testing
    the approval-mode behavior these tests exercise.
    """

    def list_profiles(self) -> list[object]:
        return []


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _view() -> ProjectFormView:
    return ProjectFormView(
        job_store=InMemoryJobStore(),
        provider_profile_management_service=_StubProviderProfileManagementService(),  # type: ignore[arg-type]
        on_created=lambda _job_id: None,
    )


def test_custom_approval_is_the_default_and_its_panel_is_visible(
    qapp: QApplication,
) -> None:
    view = _view()

    # isHidden(), not isVisible(): a bare, never-shown test widget's
    # isVisible() is always False regardless of setVisible() state,
    # since it depends on the whole ancestor chain actually being
    # shown - isHidden() reflects only this widget's own explicit
    # setVisible() call, which is what _handle_approval_mode_changed
    # actually controls.
    assert view._approval_mode.currentText() == "Custom Approval"
    assert view._custom_approval_frame.isHidden() is False


def test_custom_approval_panel_defaults_match_review_critical_stages(
    qapp: QApplication,
) -> None:
    """
    Regression test (found via user report): "Custom Approval" used to
    show no per-stage configuration UI at all - it silently reused the
    same fixed review_critical_stages() preset with no way to change
    any individual decision point. Every per-stage select must exist
    and default to that preset's own value for that field.
    """

    view = _view()
    defaults = ApprovalPolicyConfig.review_critical_stages()

    for field_name in (
        "topic",
        "content_strategy",
        "research_plan",
        "research",
        "story_angle",
        "narrative_architecture",
        "hook",
        "final_script",
        "production_plan",
        "budget",
        "final_preview",
        "publishing",
    ):
        assert field_name in view._decision_point_selects
        built_policy = view._build_approval_policy()
        assert getattr(built_policy, field_name) == getattr(defaults, field_name)


def test_selecting_a_preset_mode_hides_the_custom_panel(qapp: QApplication) -> None:
    view = _view()

    view._approval_mode.setCurrentText("Fully Automatic")

    assert view._custom_approval_frame.isHidden() is True

    view._approval_mode.setCurrentText("Custom Approval")

    assert view._custom_approval_frame.isHidden() is False


def test_preset_modes_still_return_their_own_fixed_policy(qapp: QApplication) -> None:
    view = _view()

    view._approval_mode.setCurrentText("Fully Automatic")
    assert view._build_approval_policy().topic == ApprovalPolicy.AUTO

    view._approval_mode.setCurrentText("Approve Every Step")
    assert view._build_approval_policy().topic == ApprovalPolicy.MANUAL


def test_changing_one_decision_point_select_changes_only_that_field(
    qapp: QApplication,
) -> None:
    view = _view()

    view._decision_point_selects["hook"].setCurrentText("Always require approval")

    built_policy = view._build_approval_policy()
    defaults = ApprovalPolicyConfig.review_critical_stages()

    assert built_policy.hook == ApprovalPolicy.MANUAL
    assert built_policy.topic == defaults.topic
    assert built_policy.research == defaults.research


def test_reset_restores_custom_approval_defaults(qapp: QApplication) -> None:
    view = _view()

    view._decision_point_selects["hook"].setCurrentText("Always require approval")
    view._approval_mode.setCurrentText("Fully Automatic")

    view.reset()

    assert view._approval_mode.currentText() == "Custom Approval"
    defaults = ApprovalPolicyConfig.review_critical_stages()
    assert view._build_approval_policy().hook == defaults.hook


def test_creating_a_project_with_a_custom_override_persists_it(
    qapp: QApplication,
) -> None:
    view = _view()

    view._project_name.setText("Test Project")
    view._channel_name.setText("Test Channel")
    view._topic.setText("Test Topic")
    view._video_type.setText("long-form documentary")
    view._niche.setText("Test Niche")
    view._decision_point_selects["hook"].setCurrentText("Always require approval")

    from uuid import UUID

    created_ids: list[UUID] = []
    view._on_created = created_ids.append

    view._handle_create_clicked()

    assert len(created_ids) == 1
    job = view._job_store.get(created_ids[0])
    assert job is not None
    assert job.approval_policy.hook == ApprovalPolicy.MANUAL
    assert (
        job.approval_policy.topic == ApprovalPolicyConfig.review_critical_stages().topic
    )
