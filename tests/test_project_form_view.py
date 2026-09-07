from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.project_form_view import (  # noqa: E402
    _DECISION_POINT_FIELDS,
    ProjectFormView,
)
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


# GUI-6 (Unified GUI & Release Hardening): tab-order audit --------------------


def _focus_chain_from(start: QWidget, *, max_steps: int = 200) -> list[QWidget]:
    """
    Walk the real Qt focus chain from `start`, keeping only widgets a
    Tab key press would actually stop on.

    `QWidget.nextInFocusChain()` returns every widget in construction
    order, focusable or not (a QLabel included) - real keyboard Tab
    navigation (`QWidget.focusNextPrevChild()`) walks that same chain
    but skips anything whose `focusPolicy()` is `NoFocus`. Filtering
    here reproduces what a keyboard-only user actually experiences,
    not the raw internal chain.
    """

    chain: list[QWidget] = []
    widget: QWidget = start

    for _ in range(max_steps):
        # Qt's real focus chain is circular for a well-formed widget
        # tree - nextInFocusChain() is typed as possibly returning
        # None, but never actually does here.
        next_widget = widget.nextInFocusChain()
        assert next_widget is not None
        widget = next_widget

        if widget is start:
            break
        if widget.focusPolicy() != Qt.FocusPolicy.NoFocus:
            chain.append(widget)

    return chain


def test_tab_order_follows_the_forms_visual_top_to_bottom_layout(
    qapp: QApplication,
) -> None:
    """
    Keyboard-only users tab through fields in visual order. Qt derives
    tab order purely from widget construction order - there is no
    explicit setTabOrder() anywhere in this codebase - so a field
    added to this form in a different order than it is visually placed
    would silently break keyboard navigation with no visible symptom
    for a mouse user to ever notice. This locks in that the real,
    effective focus chain (the same one a Tab key press walks) matches
    the form's declared, visual field order - found correct on
    inspection, not assumed; this test is what keeps it that way.
    """

    view = _view()
    view.show()

    # _focus_chain_from() walks the chain starting AFTER `start`, so
    # `_project_name` itself (the starting point) is intentionally not
    # part of the expected sequence below - `_channel_name` is the
    # first widget it would actually walk to.
    chain = _focus_chain_from(view._project_name)

    expected_named_fields: list[QWidget] = [
        view._channel_name,
        view._topic,
        view._video_type,
        view._niche,
        view._genre,
        view._duration_seconds,
        view._language,
        view._target_country,
        view._target_audience,
        view._platform,
        view._approval_mode,
        *(
            view._decision_point_selects[field_name]
            for field_name, _label in _DECISION_POINT_FIELDS
        ),
        view._primary_llm,
        view._reviewer_llm,
        view._fallback_llm,
    ]

    # The real chain also contains widgets with no `_field_name` (a
    # QSpinBox's own internal line-edit sub-widget, in particular) -
    # filter the walked chain down to just the named fields we care
    # about and check their RELATIVE order survives that filtering,
    # rather than requiring an exact, brittle full-chain match.
    named_fields_in_chain = [
        widget for widget in chain if widget in expected_named_fields
    ]

    assert named_fields_in_chain == expected_named_fields
