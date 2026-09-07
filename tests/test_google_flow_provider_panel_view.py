from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from src.desktop.views.google_flow_provider_panel_view import (  # noqa: E402
    GoogleFlowProviderPanelView,
)
from src.models.provider_profile import ProviderCategory  # noqa: E402
from src.services.provider_profile_management_service import (  # noqa: E402
    ProviderProfileManagementService,
)
from src.services.registry.provider_profile_repository import (  # noqa: E402
    InMemoryProviderProfileRepository,
)
from src.services.registry.provider_registry import ProviderRegistry  # noqa: E402
from src.services.secrets.provider_secret_manager import (  # noqa: E402
    InMemorySecretStore,
    ProviderSecretManager,
)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


def _management_service() -> ProviderProfileManagementService:
    return ProviderProfileManagementService(
        registry=ProviderRegistry(),
        repository=InMemoryProviderProfileRepository(),
        secret_manager=ProviderSecretManager(InMemorySecretStore()),
    )


def _view(
    qapp: QApplication,
    *,
    service: ProviderProfileManagementService | None = None,
    worker: MagicMock | None = None,
) -> GoogleFlowProviderPanelView:
    return GoogleFlowProviderPanelView(
        management_service=service or _management_service(),
        browser_worker=worker or MagicMock(),
    )


def test_starts_with_the_detail_panel_disabled(qapp: QApplication) -> None:
    view = _view(qapp)

    assert view._detail_frame.isEnabled() is False  # noqa: SLF001


def test_refresh_populates_the_list_with_only_flow_accounts(
    qapp: QApplication,
) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )
    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="llm-main",
            display_name="LLM Main",
            provider_name="OpenAI",
            category=ProviderCategory.LLM,
            enabled=True,
            secret_value="sk-test-secret-123",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()

    assert view._list.count() == 1  # noqa: SLF001
    assert view._profiles[0].profile_id == "flow.primary"  # noqa: SLF001


def test_selecting_an_account_populates_the_detail_panel(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            priority=5,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://example.invalid/flow"},
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._detail_frame.isEnabled() is True  # noqa: SLF001
    assert view._priority_input.value() == 5  # noqa: SLF001
    assert view._enabled_checkbox.isChecked() is True  # noqa: SLF001
    assert view._flow_url_input.text() == "https://example.invalid/flow"  # noqa: SLF001


def test_selecting_an_account_with_no_saved_url_prefills_the_verified_default(
    qapp: QApplication,
) -> None:
    """
    flow.google.com was confirmed real by actually visiting the
    public Google Flow marketing page (no login involved) - a newly
    added account with no flow_url saved yet starts from that real
    default rather than an empty field, though it stays fully
    editable and is never silently forced.
    """

    from src.providers.google_flow.locators import VERIFIED_FLOW_BASE_URL

    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._flow_url_input.text() == VERIFIED_FLOW_BASE_URL  # noqa: SLF001


def test_selecting_an_account_with_no_saved_model_prefills_the_recommended_default(
    qapp: QApplication,
) -> None:
    """
    Every account gets its own model choice (accounts can have
    different subscription tiers/entitlements) - a newly added
    account with no model_family saved yet starts at the confirmed
    unlimited-tier recommendation rather than whatever Flow's own UI
    happens to default a new project to, but any of the 4 real models
    can be picked per account.
    """

    from src.providers.google_flow.locators import RECOMMENDED_UNLIMITED_MODEL_FAMILY

    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert (
        view._model_family_select.currentText()  # noqa: SLF001
        == RECOMMENDED_UNLIMITED_MODEL_FAMILY
    )


def test_selecting_an_account_shows_its_own_saved_model(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"model_family": "Veo 3.1 - Quality"},
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert (
        view._model_family_select.currentText() == "Veo 3.1 - Quality"
    )  # noqa: SLF001


def test_save_persists_the_model_family_per_account(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    view._model_family_select.setCurrentText("Veo 3.1 - Fast")  # noqa: SLF001
    view._handle_save_clicked()  # noqa: SLF001

    saved = service.get_profile("flow.primary")
    assert saved.metadata.get("model_family") == "Veo 3.1 - Fast"


def test_agent_default_checkbox_starts_unchecked(qapp: QApplication) -> None:
    """
    Matches Flow's own real default (Agent off,
    docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 3) - this app never
    forces Agent on for a new account.
    """

    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._agent_default_checkbox.isChecked() is False  # noqa: SLF001


def test_selecting_an_account_shows_its_own_saved_agent_default(
    qapp: QApplication,
) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"agent_mode": "true"},
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._agent_default_checkbox.isChecked() is True  # noqa: SLF001


def test_save_persists_the_agent_default_per_account(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    view._agent_default_checkbox.setChecked(True)  # noqa: SLF001
    view._handle_save_clicked()  # noqa: SLF001

    saved = service.get_profile("flow.primary")
    assert saved.metadata.get("agent_mode") == "true"


def test_save_persists_the_flow_url_and_priority(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    view._flow_url_input.setText("https://example.invalid/flow")  # noqa: SLF001
    view._priority_input.setValue(3)  # noqa: SLF001
    view._handle_save_clicked()  # noqa: SLF001

    saved = service.get_profile("flow.primary")
    assert saved.priority == 3
    assert saved.metadata.get("flow_url") == "https://example.invalid/flow"


def test_open_login_without_a_flow_url_shows_a_warning(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001
    # A newly-added account with no saved flow_url is pre-filled with
    # the real, verified default (flow.google.com) rather than left
    # blank - simulate an operator who deliberately cleared it, since
    # that's the actual condition this warning guards against.
    view._flow_url_input.clear()  # noqa: SLF001

    view._handle_open_login_clicked()  # noqa: SLF001

    assert "Flow URL" in view._status.text()  # noqa: SLF001


def test_open_login_launches_real_chrome_for_manual_sign_in(
    qapp: QApplication,
) -> None:
    """
    Google rejects sign-in from Playwright's automated browser
    (confirmed 2026-09-07 by a real attempt: "Couldn't sign you in -
    this browser or app may not be secure") - Open Login must launch
    the operator's own real, non-automated Chrome instead, never touch
    FlowBrowserWorker/Playwright for the sign-in step itself.
    """

    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://example.invalid/flow"},
        )
    )

    worker = MagicMock()
    view = _view(qapp, service=service, worker=worker)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    with (
        patch(
            "src.desktop.views.google_flow_provider_panel_view."
            "find_real_chrome_executable",
            return_value=r"C:\fake\chrome.exe",
        ),
        patch(
            "src.desktop.views.google_flow_provider_panel_view.subprocess.Popen"
        ) as popen,
        patch(
            "src.desktop.views.google_flow_provider_panel_view.QMessageBox.information"
        ) as information,
    ):
        view._handle_open_login_clicked()  # noqa: SLF001

    popen.assert_called_once()
    launched_args = popen.call_args.args[0]
    assert launched_args[0] == r"C:\fake\chrome.exe"
    user_data_dir_args = [
        arg for arg in launched_args if arg.startswith("--user-data-dir=")
    ]
    assert len(user_data_dir_args) == 1
    # Regression guard for a real bug: a *relative* --user-data-dir
    # handed to a subprocess (a separate OS process) can resolve
    # against a different working directory than this app's own,
    # confirmed in practice by a real sign-in landing in the wrong
    # Chrome profile - it must always be absolute.
    launched_directory = Path(user_data_dir_args[0].removeprefix("--user-data-dir="))
    assert launched_directory.is_absolute()
    assert launched_args[-1] == "https://example.invalid/flow"
    information.assert_called_once()
    worker.open_persistent_context.assert_not_called()
    assert "Real Chrome opened" in view._status.text()  # noqa: SLF001


def test_open_login_without_chrome_installed_shows_a_warning(
    qapp: QApplication,
) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://example.invalid/flow"},
        )
    )

    view = _view(qapp, service=service, worker=MagicMock())
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    with (
        patch(
            "src.desktop.views.google_flow_provider_panel_view."
            "find_real_chrome_executable",
            return_value=None,
        ),
        patch(
            "src.desktop.views.google_flow_provider_panel_view."
            "QDesktopServices.openUrl"
        ),
        patch(
            "src.desktop.views.google_flow_provider_panel_view.QMessageBox.warning"
        ) as warning,
    ):
        view._handle_open_login_clicked()  # noqa: SLF001

    warning.assert_called_once()


def test_open_login_reports_a_chrome_launch_failure(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://example.invalid/flow"},
        )
    )

    view = _view(qapp, service=service, worker=MagicMock())
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    with (
        patch(
            "src.desktop.views.google_flow_provider_panel_view."
            "find_real_chrome_executable",
            return_value=r"C:\fake\chrome.exe",
        ),
        patch(
            "src.desktop.views.google_flow_provider_panel_view.subprocess.Popen",
            side_effect=OSError("no such file"),
        ),
    ):
        view._handle_open_login_clicked()  # noqa: SLF001

    assert "Could not launch Chrome" in view._status.text()  # noqa: SLF001


def test_check_connection_without_a_flow_url_shows_a_warning(
    qapp: QApplication,
) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001
    view._flow_url_input.clear()  # noqa: SLF001

    view._handle_check_connection_clicked()  # noqa: SLF001

    assert "Flow URL" in view._status.text()  # noqa: SLF001


def test_check_connection_reports_healthy(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://example.invalid/flow"},
        )
    )

    view = _view(qapp, service=service, worker=MagicMock())
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    with patch(
        "src.desktop.views.google_flow_provider_panel_view.GoogleFlowRealUIAdapter"
    ) as adapter_class:
        adapter_class.return_value.check_profile_health.return_value = True
        view._handle_check_connection_clicked()  # noqa: SLF001

    assert "healthy" in view._status.text().lower()  # noqa: SLF001


def test_delete_removes_the_account(qapp: QApplication) -> None:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    with patch(
        "src.desktop.views.google_flow_provider_panel_view.QMessageBox.question"
    ) as question:
        from PySide6.QtWidgets import QMessageBox

        question.return_value = QMessageBox.StandardButton.Yes
        view._handle_delete_clicked()  # noqa: SLF001

    assert service.list_profiles() == []


def _flow_view_with_url(
    qapp: QApplication, *, worker: MagicMock | None = None
) -> tuple[GoogleFlowProviderPanelView, ProviderProfileManagementService]:
    service = _management_service()
    from src.models.provider_profile_management import ProviderProfileUpsertCommand

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="flow.primary",
            display_name="Flow Primary",
            provider_name="Google Flow",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="flow_profiles/flow.primary",
            metadata={"flow_url": "https://example.invalid/flow"},
        )
    )

    view = _view(qapp, service=service, worker=worker or MagicMock())
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    return view, service


def test_set_flow_confirmation_never_without_a_flow_url_shows_a_warning(
    qapp: QApplication,
) -> None:
    view, _ = _flow_view_with_url(qapp)
    view._flow_url_input.clear()  # noqa: SLF001

    view._handle_set_flow_confirmation_never_clicked()  # noqa: SLF001

    assert "Flow URL" in view._status.text()  # noqa: SLF001


def test_set_flow_confirmation_never_requires_explicit_confirmation(
    qapp: QApplication,
) -> None:
    """
    This changes a real setting on the operator's Google account - it
    must never proceed without an explicit Yes, even though the
    button itself was already an explicit click.
    """

    view, _ = _flow_view_with_url(qapp)

    with (
        patch(
            "src.desktop.views.google_flow_provider_panel_view.QMessageBox.question"
        ) as question,
        patch(
            "src.desktop.views.google_flow_provider_panel_view.GoogleFlowRealUIAdapter"
        ) as adapter_class,
    ):
        from PySide6.QtWidgets import QMessageBox

        question.return_value = QMessageBox.StandardButton.No
        view._handle_set_flow_confirmation_never_clicked()  # noqa: SLF001

    adapter_class.assert_not_called()


def test_set_flow_confirmation_never_calls_the_real_adapter_when_confirmed(
    qapp: QApplication,
) -> None:
    view, _ = _flow_view_with_url(qapp)

    with (
        patch(
            "src.desktop.views.google_flow_provider_panel_view.QMessageBox.question"
        ) as question,
        patch(
            "src.desktop.views.google_flow_provider_panel_view.GoogleFlowRealUIAdapter"
        ) as adapter_class,
    ):
        from PySide6.QtWidgets import QMessageBox

        question.return_value = QMessageBox.StandardButton.Yes
        view._handle_set_flow_confirmation_never_clicked()  # noqa: SLF001

    adapter_class.return_value.set_confirm_before_generating.assert_called_once_with(
        "flow.primary", always=False
    )
    assert "Never" in view._status.text()  # noqa: SLF001


def test_set_flow_confirmation_never_reports_a_failure(qapp: QApplication) -> None:
    view, _ = _flow_view_with_url(qapp)

    with (
        patch(
            "src.desktop.views.google_flow_provider_panel_view.QMessageBox.question"
        ) as question,
        patch(
            "src.desktop.views.google_flow_provider_panel_view.GoogleFlowRealUIAdapter"
        ) as adapter_class,
    ):
        from PySide6.QtWidgets import QMessageBox

        question.return_value = QMessageBox.StandardButton.Yes
        adapter_class.return_value.set_confirm_before_generating.side_effect = (
            RuntimeError("could not find the Never radio")
        )
        view._handle_set_flow_confirmation_never_clicked()  # noqa: SLF001

    assert "Could not change" in view._status.text()  # noqa: SLF001
