from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.browser.flow_profile_paths import UnsafeProfileIdError, profile_directory
from src.desktop.widgets import badge, button, card, heading, muted, row, status_label
from src.models.provider_profile import ProviderCategory
from src.models.provider_profile_management import (
    ProviderProfileSummary,
    ProviderProfileUpsertCommand,
)
from src.providers.google_flow.adapter import GoogleFlowUIAdapter
from src.providers.google_flow.locators import VERIFIED_FLOW_BASE_URL
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)

# Google Flow External UI Automation, GF-13: "Providers -> Google Flow
# -> Add/Connect Account -> Open Login -> manual Google authentication
# -> persistent authenticated browser profile -> Check Connection ->
# READY." Kept structurally separate from ProviderManagerView (which
# always shows an "API key" field, wrong for a category that
# authenticates via a persistent browser profile, never a secret -
# GF-13's own "Google Flow must NOT display an API Key field").
#
# IMPORTANT, matching every other Google Flow doc-string in this
# initiative: "Open Login"/"Check Connection" drive a REAL
# FlowBrowserWorker/GoogleFlowUIAdapter against whatever URL the
# operator enters when adding an account - never a URL guessed or
# hardcoded here. Nobody building this has verified Google Flow's
# real product URL or DOM, so this panel asks the operator for the
# URL explicitly rather than fabricating one, and GoogleFlowLocators'
# own selectors remain fixture-verified only (GF-4) until GF-17's
# real-account certification updates them.


class GoogleFlowProviderPanelView(QWidget):
    def __init__(
        self,
        *,
        management_service: ProviderProfileManagementService,
        browser_worker: FlowBrowserWorker,
    ) -> None:
        super().__init__()

        self._service = management_service
        self._browser_worker = browser_worker
        self._profiles: list[ProviderProfileSummary] = []
        self._selected_profile_id: str | None = None
        self._flow_urls: dict[str, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        outer.addWidget(heading("Google Flow Accounts"))
        outer.addWidget(
            muted(
                "Configure one or more Google Flow accounts. Each account "
                "authenticates through its own persistent browser profile - "
                "never an API key."
            )
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_list_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 480])

    # --- construction ---

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        add_button = button("Add account", variant="primary", icon_name="add")
        add_button.clicked.connect(self._handle_add_clicked)
        layout.addLayout(row(add_button))

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._handle_selection_changed)
        layout.addWidget(self._list, stretch=1)

        return panel

    def _build_detail_panel(self) -> QWidget:
        frame, card_layout = card("Account", icon_name="shield")

        self._health_badge = badge("")
        card_layout.addLayout(row(self._health_badge))

        form = QFormLayout()
        form.setSpacing(10)

        self._display_name_value = muted("")
        form.addRow("Account", self._display_name_value)

        self._flow_url_input = QLineEdit()
        self._flow_url_input.setPlaceholderText(VERIFIED_FLOW_BASE_URL)
        form.addRow("Flow URL", self._flow_url_input)

        self._priority_input = QSpinBox()
        self._priority_input.setRange(1, 1000)
        form.addRow("Priority", self._priority_input)

        self._enabled_checkbox = QCheckBox("Enabled")
        form.addRow("", self._enabled_checkbox)

        card_layout.addLayout(form)

        self._status = status_label("", role="success")
        self._status.hide()
        card_layout.addWidget(self._status)

        open_login_button = button("Open Login")
        open_login_button.clicked.connect(self._handle_open_login_clicked)

        check_button = button("Check Connection", icon_name="check")
        check_button.clicked.connect(self._handle_check_connection_clicked)

        save_button = button("Save", variant="primary")
        save_button.clicked.connect(self._handle_save_clicked)

        delete_button = button("Delete", variant="danger")
        delete_button.clicked.connect(self._handle_delete_clicked)

        card_layout.addLayout(
            row(open_login_button, check_button, save_button, delete_button)
        )

        self._detail_frame = frame
        self._detail_frame.setEnabled(False)

        return frame

    # --- data ---

    def refresh(self) -> None:
        """Reload Google Flow accounts from the management service."""

        self._profiles = [
            profile
            for profile in self._service.list_profiles()
            if profile.category == ProviderCategory.EXTERNAL_UI_VIDEO
        ]

        self._list.blockSignals(True)
        self._list.clear()

        for profile in self._profiles:
            item = QListWidgetItem(
                f"{profile.display_name}  ·  {profile.health_status.value}"
            )
            item.setData(Qt.ItemDataRole.UserRole, profile.profile_id)
            self._list.addItem(item)

        self._list.blockSignals(False)

        if self._selected_profile_id is not None:
            self._select_profile_id(self._selected_profile_id)
        else:
            self._detail_frame.setEnabled(False)

    def _select_profile_id(self, profile_id: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self._list.setCurrentItem(item)
                return

    # --- handlers ---

    def _handle_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._selected_profile_id = None
            self._detail_frame.setEnabled(False)
            return

        profile_id = current.data(Qt.ItemDataRole.UserRole)
        self._selected_profile_id = profile_id
        self._detail_frame.setEnabled(True)
        self._status.hide()

        profile = next(p for p in self._profiles if p.profile_id == profile_id)

        self._display_name_value.setText(
            f"{profile.display_name} ({profile.profile_id})"
        )
        self._priority_input.setValue(profile.priority)
        self._enabled_checkbox.setChecked(profile.enabled)
        self._flow_url_input.setText(
            self._flow_urls.get(profile_id)
            or profile.metadata.get("flow_url")
            # A real, verified default now that the base URL has
            # actually been confirmed by visiting the public Google
            # Flow marketing page (no login involved) - still just a
            # starting point the operator can edit, never forced.
            or VERIFIED_FLOW_BASE_URL
        )
        self._health_badge.setText(profile.health_status.value)

    def _handle_add_clicked(self) -> None:
        profile_id, accepted = QInputDialog.getText(
            self, "Add Google Flow Account", "Account id (e.g. flow.primary):"
        )

        if not accepted or not profile_id.strip():
            return

        display_name, accepted = QInputDialog.getText(
            self, "Add Google Flow Account", "Display name:"
        )

        if not accepted or not display_name.strip():
            return

        try:
            directory = profile_directory(profile_id.strip())
        except UnsafeProfileIdError as error:
            QMessageBox.warning(self, "Add Google Flow Account", str(error))
            return

        try:
            self._service.upsert_profile(
                ProviderProfileUpsertCommand(
                    profile_id=profile_id.strip(),
                    display_name=display_name.strip(),
                    provider_name="Google Flow",
                    category=ProviderCategory.EXTERNAL_UI_VIDEO,
                    enabled=False,
                    browser_profile_reference=str(directory),
                )
            )
        except ValueError as error:
            QMessageBox.warning(self, "Add Google Flow Account", str(error))
            return

        self.refresh()
        self._select_profile_id(profile_id.strip())

    def _handle_save_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        profile_id = self._selected_profile_id
        profile = next(p for p in self._profiles if p.profile_id == profile_id)
        flow_url = self._flow_url_input.text().strip()
        self._flow_urls[profile_id] = flow_url

        try:
            self._service.upsert_profile(
                ProviderProfileUpsertCommand(
                    profile_id=profile_id,
                    display_name=profile.display_name,
                    provider_name=profile.provider_name,
                    category=ProviderCategory.EXTERNAL_UI_VIDEO,
                    enabled=self._enabled_checkbox.isChecked(),
                    priority=self._priority_input.value(),
                    browser_profile_reference=profile.browser_profile_reference,
                    metadata={**profile.metadata, "flow_url": flow_url},
                )
            )
        except ValueError as error:
            QMessageBox.warning(self, "Save", str(error))
            return

        self._show_status("Saved.", role="success")
        self.refresh()

    def _handle_delete_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        confirmation = QMessageBox.question(
            self,
            "Delete Google Flow Account",
            "Remove this account? Its persistent browser profile on "
            "disk is not deleted.",
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        self._service.delete_profile(self._selected_profile_id)
        self._selected_profile_id = None
        self.refresh()

    def _handle_open_login_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        flow_url = self._flow_url_input.text().strip()

        if not flow_url:
            self._show_status(
                "Set the Flow URL above and Save before opening login.",
                role="warning",
            )
            return

        profile_id = self._selected_profile_id
        directory = profile_directory(profile_id)

        try:
            context = self._browser_worker.open_persistent_context(
                profile_id, directory, headless=False
            ).result(timeout=30.0)

            def _navigate() -> None:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(flow_url)

            self._browser_worker.submit(_navigate).result(timeout=30.0)
        except Exception as error:  # noqa: BLE001
            self._show_status(f"Could not open the browser: {error}", role="error")
            return

        self._show_status(
            "Browser opened - complete Google sign-in there, then use "
            "Check Connection.",
            role="success",
        )

    def _handle_check_connection_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        flow_url = self._flow_url_input.text().strip()

        if not flow_url:
            self._show_status("Set the Flow URL above first.", role="warning")
            return

        adapter = GoogleFlowUIAdapter(
            worker=self._browser_worker,
            base_url=flow_url,
            headless=False,
        )

        try:
            healthy = adapter.check_profile_health(self._selected_profile_id)
        except Exception as error:  # noqa: BLE001
            self._show_status(f"Check failed: {error}", role="error")
            return

        if healthy:
            self._show_status("Connection looks healthy.", role="success")
        else:
            self._show_status(
                "Not authenticated (or the page layout is unrecognized) - "
                "use Open Login.",
                role="warning",
            )

    def _show_status(self, text: str, *, role: str) -> None:
        self._status.setText(text)
        self._status.setProperty("role", role)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._status.show()
