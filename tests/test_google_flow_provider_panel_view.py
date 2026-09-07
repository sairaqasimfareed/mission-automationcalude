from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
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


class _FakeFuture:
    """A concurrent.futures.Future stand-in that resolves immediately,
    synchronously, on whatever thread calls .result() - the panel's
    own logic is what's under test here, not FlowBrowserWorker's real
    threading (already covered by test_flow_browser_worker.py)."""

    def __init__(self, value: object = None, *, error: Exception | None = None):
        self._value = value
        self._error = error

    def result(self, timeout: float | None = None) -> object:
        if self._error is not None:
            raise self._error

        return self._value


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

    view._handle_open_login_clicked()  # noqa: SLF001

    assert "Flow URL" in view._status.text()  # noqa: SLF001


def test_open_login_opens_a_context_and_navigates(qapp: QApplication) -> None:
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

    fake_context = MagicMock()
    fake_context.pages = []
    fake_page = MagicMock()
    fake_context.new_page.return_value = fake_page

    worker = MagicMock()
    worker.open_persistent_context.return_value = _FakeFuture(fake_context)
    worker.submit.side_effect = lambda fn: _FakeFuture(fn())

    view = _view(qapp, service=service, worker=worker)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    view._handle_open_login_clicked()  # noqa: SLF001

    fake_page.goto.assert_called_once_with("https://example.invalid/flow")
    assert "Browser opened" in view._status.text()  # noqa: SLF001


def test_open_login_reports_a_browser_launch_failure(qapp: QApplication) -> None:
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
    worker.open_persistent_context.return_value = _FakeFuture(
        error=RuntimeError("no display")
    )

    view = _view(qapp, service=service, worker=worker)
    view.refresh()
    view._list.setCurrentRow(0)  # noqa: SLF001

    view._handle_open_login_clicked()  # noqa: SLF001

    assert "Could not open" in view._status.text()  # noqa: SLF001


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
        "src.desktop.views.google_flow_provider_panel_view.GoogleFlowUIAdapter"
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
