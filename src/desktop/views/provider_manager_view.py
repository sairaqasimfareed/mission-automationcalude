from __future__ import annotations

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.desktop.widgets import badge, button, card, heading, muted, row, separator
from src.models.provider_profile import ProviderCategory
from src.models.provider_profile_management import (
    ProviderProfileSummary,
    ProviderProfileUpsertCommand,
)
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)

_LEFT = Qt.AlignmentFlag.AlignLeft


class ProviderManagerView(QWidget):
    """
    Desktop Provider Manager: create, edit, enable/disable, and delete
    provider profiles.

    Profiles are durable (JsonProviderProfileRepository) and their
    secrets live in the OS credential vault (KeyringSecretStore), both
    wired together through ProviderProfileManagementService - see
    src/desktop/services.py. Editing a profile here changes what the
    rest of the application actually selects for content generation,
    since the management service shares its ProviderRegistry with the
    running production runtime.
    """

    def __init__(
        self,
        *,
        management_service: ProviderProfileManagementService,
    ) -> None:
        super().__init__()

        self._service = management_service
        self._profiles: list[ProviderProfileSummary] = []
        self._selected_profile_id: str | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        outer.addWidget(heading("Provider Manager"))
        outer.addWidget(
            muted(
                "Configure the external providers Mission Automation uses "
                "for content generation."
            )
        )

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter, stretch=1)

        splitter.addWidget(self._build_list_panel())
        splitter.addWidget(self._build_form_panel())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 560])

    def _build_list_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        new_button = button("New provider", variant="primary", icon_name="add")
        new_button.clicked.connect(self._handle_new_clicked)
        layout.addLayout(row(new_button))

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._handle_selection_changed)
        layout.addWidget(self._list, stretch=1)

        return panel

    def _build_form_panel(self) -> QWidget:
        frame, card_layout = card("Provider profile", icon_name="settings")

        self._health_badge = badge("")
        card_layout.addLayout(row(self._health_badge))

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(_LEFT)

        self._profile_id = QLineEdit()
        form.addRow("Profile ID", self._profile_id)

        self._display_name = QLineEdit()
        form.addRow("Display name", self._display_name)

        self._provider_name = QLineEdit()
        form.addRow("Provider name", self._provider_name)

        self._category = QComboBox()
        for category in ProviderCategory:
            self._category.addItem(category.value, category)
        form.addRow("Category", self._category)

        self._default_model = QLineEdit()
        self._default_model.setPlaceholderText("Optional")
        form.addRow("Default model", self._default_model)

        self._base_url = QLineEdit()
        self._base_url.setPlaceholderText("Optional")
        form.addRow("Base URL", self._base_url)

        self._secret_value = QLineEdit()
        self._secret_value.setEchoMode(QLineEdit.EchoMode.Password)
        self._secret_value.setPlaceholderText("Leave blank to keep the existing key")
        form.addRow("API key", self._secret_value)

        self._priority = QSpinBox()
        self._priority.setRange(1, 1000)
        self._priority.setValue(100)
        form.addRow("Priority", self._priority)

        self._daily_budget = QDoubleSpinBox()
        self._daily_budget.setRange(0.0, 1_000_000.0)
        self._daily_budget.setPrefix("$ ")
        self._daily_budget.setDecimals(2)
        form.addRow("Daily budget", self._daily_budget)

        self._monthly_budget = QDoubleSpinBox()
        self._monthly_budget.setRange(0.0, 1_000_000.0)
        self._monthly_budget.setPrefix("$ ")
        self._monthly_budget.setDecimals(2)
        form.addRow("Monthly budget", self._monthly_budget)

        self._capabilities = QLineEdit()
        self._capabilities.setPlaceholderText("comma-separated, e.g. text, vision")
        form.addRow("Capabilities", self._capabilities)

        self._enabled = QCheckBox("Enabled")
        form.addRow("", self._enabled)

        card_layout.addLayout(form)
        card_layout.addWidget(separator())

        self._secret_status = muted("")
        card_layout.addWidget(self._secret_status)

        save_button = button("Save", variant="primary", icon_name="check")
        save_button.clicked.connect(self._handle_save_clicked)

        test_button = button("Test configuration", icon_name="shield")
        test_button.clicked.connect(self._handle_test_clicked)

        delete_button = button("Delete", variant="danger")
        delete_button.clicked.connect(self._handle_delete_clicked)

        card_layout.addLayout(row(save_button, test_button, delete_button))

        return frame

    def refresh(self) -> None:
        """Reload provider profiles from the management service."""

        self._profiles = self._service.list_profiles()

        self._list.blockSignals(True)
        self._list.clear()

        for profile in self._profiles:
            item = QListWidgetItem(
                f"{profile.display_name}  ·  {profile.category.value}"
            )
            item.setData(Qt.ItemDataRole.UserRole, profile.profile_id)
            self._list.addItem(item)

        self._list.blockSignals(False)

        if self._selected_profile_id and any(
            profile.profile_id == self._selected_profile_id
            for profile in self._profiles
        ):
            self._select_profile_id(self._selected_profile_id)
        elif self._profiles:
            self._select_profile_id(self._profiles[0].profile_id)
        else:
            self._selected_profile_id = None
            self._reset_form(editing_existing=False)

    def _select_profile_id(self, profile_id: str) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)

            if item.data(Qt.ItemDataRole.UserRole) == profile_id:
                self._list.setCurrentItem(item)
                return

    def _handle_selection_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            self._selected_profile_id = None
            self._reset_form(editing_existing=False)
            return

        profile_id = current.data(Qt.ItemDataRole.UserRole)
        self._selected_profile_id = profile_id

        profile = next(
            (
                candidate
                for candidate in self._profiles
                if candidate.profile_id == profile_id
            ),
            None,
        )

        if profile is not None:
            self._load_profile_into_form(profile)

    def _handle_new_clicked(self) -> None:
        self._selected_profile_id = None
        self._list.setCurrentRow(-1)
        self._reset_form(editing_existing=False)

    def _load_profile_into_form(self, profile: ProviderProfileSummary) -> None:
        self._profile_id.setText(profile.profile_id)
        self._profile_id.setReadOnly(True)
        self._display_name.setText(profile.display_name)
        self._provider_name.setText(profile.provider_name)

        category_index = self._category.findData(profile.category)

        if category_index >= 0:
            self._category.setCurrentIndex(category_index)

        self._default_model.setText(profile.default_model or "")
        self._base_url.setText(profile.base_url or "")
        self._secret_value.clear()
        self._priority.setValue(profile.priority)
        self._daily_budget.setValue(profile.daily_budget_usd)
        self._monthly_budget.setValue(profile.monthly_budget_usd)
        self._capabilities.setText(", ".join(profile.capabilities))
        self._enabled.setChecked(profile.enabled)

        self._health_badge.setText(profile.health_status.value)
        self._secret_status.setText(
            f"Secret: {profile.masked_secret}"
            if profile.has_secret
            else "Secret: not configured"
        )

    def _reset_form(self, *, editing_existing: bool) -> None:
        self._profile_id.clear()
        self._profile_id.setReadOnly(editing_existing)
        self._display_name.clear()
        self._provider_name.clear()
        self._category.setCurrentIndex(0)
        self._default_model.clear()
        self._base_url.clear()
        self._secret_value.clear()
        self._priority.setValue(100)
        self._daily_budget.setValue(0.0)
        self._monthly_budget.setValue(0.0)
        self._capabilities.clear()
        self._enabled.setChecked(False)
        self._health_badge.setText("")
        self._secret_status.setText("")

    def _handle_save_clicked(self) -> None:
        capabilities = [
            value.strip()
            for value in self._capabilities.text().split(",")
            if value.strip()
        ]

        try:
            command = ProviderProfileUpsertCommand(
                profile_id=self._profile_id.text(),
                display_name=self._display_name.text(),
                provider_name=self._provider_name.text(),
                category=self._category.currentData(),
                enabled=self._enabled.isChecked(),
                priority=self._priority.value(),
                base_url=self._base_url.text(),
                default_model=self._default_model.text(),
                daily_budget_usd=self._daily_budget.value(),
                monthly_budget_usd=self._monthly_budget.value(),
                capabilities=capabilities,
                secret_value=self._secret_value.text(),
            )

            summary = self._service.upsert_profile(command)
        except (ValidationError, ValueError) as error:
            QMessageBox.warning(self, "Could not save provider", str(error))

            return

        self._selected_profile_id = summary.profile_id
        self.refresh()

    def _handle_test_clicked(self) -> None:
        if self._selected_profile_id is None:
            QMessageBox.information(
                self,
                "Test configuration",
                "Save the provider profile first.",
            )

            return

        try:
            result = self._service.check_health(self._selected_profile_id)
        except KeyError as error:
            QMessageBox.warning(self, "Could not test provider", str(error))

            return

        self._health_badge.setText(result.status.value)

        QMessageBox.information(self, "Test configuration", result.message)

    def _handle_delete_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        confirmation = QMessageBox.question(
            self,
            "Delete provider",
            (
                f"Delete provider profile '{self._selected_profile_id}'? "
                "This also removes its stored secret."
            ),
        )

        if confirmation != QMessageBox.StandardButton.Yes:
            return

        self._service.delete_profile(self._selected_profile_id)
        self._selected_profile_id = None
        self.refresh()
