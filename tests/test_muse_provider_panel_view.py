from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402
from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from src.desktop.views.muse_provider_panel_view import (
    MuseProviderPanelView,  # noqa: E402
)
from src.models.provider_profile import ProviderCategory  # noqa: E402
from src.models.provider_profile_management import (  # noqa: E402
    ProviderProfileUpsertCommand,
)
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
) -> MuseProviderPanelView:
    return MuseProviderPanelView(
        management_service=service or _management_service(),
        browser_worker=worker or MagicMock(),
    )


def _muse_view_with_account(
    qapp: QApplication, *, worker: MagicMock | None = None
) -> tuple[MuseProviderPanelView, ProviderProfileManagementService]:
    service = _management_service()
    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="muse.primary",
            display_name="Muse Primary",
            provider_name="Muse",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="muse_profiles/muse.primary",
        )
    )

    view = _view(qapp, service=service, worker=worker or MagicMock())
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    return view, service


def test_starts_with_the_detail_panel_disabled(qapp: QApplication) -> None:
    view = _view(qapp)

    assert view._detail_frame.isEnabled() is False  # noqa: SLF001


def test_refresh_populates_the_list_with_only_muse_accounts(
    qapp: QApplication,
) -> None:
    service = _management_service()

    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="muse.primary",
            display_name="Muse Primary",
            provider_name="Muse",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=False,
            browser_profile_reference="muse_profiles/muse.primary",
        )
    )
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
    assert view._profiles[0].profile_id == "muse.primary"  # noqa: SLF001


def test_selecting_an_account_populates_the_detail_panel(qapp: QApplication) -> None:
    service = _management_service()
    service.upsert_profile(
        ProviderProfileUpsertCommand(
            profile_id="muse.primary",
            display_name="Muse Primary",
            provider_name="Muse",
            category=ProviderCategory.EXTERNAL_UI_VIDEO,
            enabled=True,
            priority=5,
            browser_profile_reference="muse_profiles/muse.primary",
        )
    )

    view = _view(qapp, service=service)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    assert view._detail_frame.isEnabled() is True  # noqa: SLF001
    assert view._priority_input.value() == 5  # noqa: SLF001
    assert view._enabled_checkbox.isChecked() is True  # noqa: SLF001


def test_save_persists_priority_and_enabled(qapp: QApplication) -> None:
    view, service = _muse_view_with_account(qapp)

    view._priority_input.setValue(3)  # noqa: SLF001
    view._enabled_checkbox.setChecked(True)  # noqa: SLF001
    view._handle_save_clicked()  # noqa: SLF001

    saved = service.get_profile("muse.primary")
    assert saved.priority == 3
    assert saved.enabled is True


def test_open_login_launches_real_chrome_for_manual_sign_in(
    qapp: QApplication,
) -> None:
    """Same real-world finding as Google Flow's own panel: Muse's real
    sign-in needs the operator's own real, non-automated Chrome -
    never FlowBrowserWorker/Playwright for the sign-in step itself."""

    worker = MagicMock()
    view, _service = _muse_view_with_account(qapp, worker=worker)

    with (
        patch(
            "src.desktop.views.muse_provider_panel_view.find_real_chrome_executable",
            return_value=r"C:\fake\chrome.exe",
        ),
        patch("src.desktop.views.muse_provider_panel_view.subprocess.Popen") as popen,
        patch(
            "src.desktop.views.muse_provider_panel_view.QMessageBox.information"
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
    launched_directory = Path(user_data_dir_args[0].removeprefix("--user-data-dir="))
    assert launched_directory.is_absolute()
    assert launched_args[-1] == "https://muse.ai"
    information.assert_called_once()
    worker.open_persistent_context.assert_not_called()
    assert "Real Chrome opened" in view._status.text()  # noqa: SLF001


def test_open_login_without_chrome_installed_shows_a_warning(
    qapp: QApplication,
) -> None:
    view, _service = _muse_view_with_account(qapp)

    with (
        patch(
            "src.desktop.views.muse_provider_panel_view.find_real_chrome_executable",
            return_value=None,
        ),
        patch("src.desktop.views.muse_provider_panel_view.QDesktopServices.openUrl"),
        patch(
            "src.desktop.views.muse_provider_panel_view.QMessageBox.warning"
        ) as warning,
    ):
        view._handle_open_login_clicked()  # noqa: SLF001

    warning.assert_called_once()


def test_open_login_reports_a_chrome_launch_failure(qapp: QApplication) -> None:
    view, _service = _muse_view_with_account(qapp)

    with (
        patch(
            "src.desktop.views.muse_provider_panel_view.find_real_chrome_executable",
            return_value=r"C:\fake\chrome.exe",
        ),
        patch(
            "src.desktop.views.muse_provider_panel_view.subprocess.Popen",
            side_effect=OSError("no such file"),
        ),
    ):
        view._handle_open_login_clicked()  # noqa: SLF001

    assert "Could not launch Chrome" in view._status.text()  # noqa: SLF001


def test_check_connection_reports_healthy(qapp: QApplication) -> None:
    view, _service = _muse_view_with_account(qapp, worker=MagicMock())

    with patch(
        "src.desktop.views.muse_provider_panel_view.MuseRealUIAdapter"
    ) as adapter_class:
        adapter_class.return_value.check_profile_health.return_value = True
        view._handle_check_connection_clicked()  # noqa: SLF001

    assert "healthy" in view._status.text().lower()  # noqa: SLF001


def test_check_connection_reports_unhealthy(qapp: QApplication) -> None:
    view, _service = _muse_view_with_account(qapp, worker=MagicMock())

    with patch(
        "src.desktop.views.muse_provider_panel_view.MuseRealUIAdapter"
    ) as adapter_class:
        adapter_class.return_value.check_profile_health.return_value = False
        view._handle_check_connection_clicked()  # noqa: SLF001

    assert "Not authenticated" in view._status.text()  # noqa: SLF001


def test_delete_removes_the_account(qapp: QApplication) -> None:
    view, service = _muse_view_with_account(qapp)

    with patch(
        "src.desktop.views.muse_provider_panel_view.QMessageBox.question"
    ) as question:
        question.return_value = QMessageBox.StandardButton.Yes
        view._handle_delete_clicked()  # noqa: SLF001

    assert service.list_profiles() == []
