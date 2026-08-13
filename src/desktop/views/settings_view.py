from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.desktop.widgets import badge, heading
from src.services.runtime_configuration_loader import RuntimeConfiguration

_COLUMNS = ["Profile ID", "Provider", "Category", "Enabled", "Health", "Secret"]


class SettingsView(QWidget):
    """
    Read-only provider settings view.

    Derived from RuntimeConfigurationLoader (Sprint 21). Secret values
    are never displayed here, only whether a secret is configured.
    """

    def __init__(
        self,
        *,
        get_configuration: Callable[[], RuntimeConfiguration],
    ) -> None:
        super().__init__()

        self._get_configuration = get_configuration

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)

        layout.addWidget(heading("Provider settings"))

        self._dry_run_label = badge("")
        layout.addWidget(self._dry_run_label)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    def refresh(self) -> None:
        """Reload provider profiles from runtime configuration."""

        configuration: RuntimeConfiguration = self._get_configuration()

        self._dry_run_label.setText(
            f"Dry run: {configuration.advanced_settings.dry_run}"
        )

        profiles = configuration.provider_profiles

        self._table.setRowCount(len(profiles))

        for row, profile in enumerate(profiles):
            self._table.setItem(row, 0, QTableWidgetItem(profile.profile_id))
            self._table.setItem(row, 1, QTableWidgetItem(profile.provider_name))
            self._table.setItem(row, 2, QTableWidgetItem(profile.category.value))
            self._table.setItem(row, 3, QTableWidgetItem(str(profile.enabled)))
            self._table.setItem(row, 4, QTableWidgetItem(profile.health_status.value))
            self._table.setItem(
                row,
                5,
                QTableWidgetItem(
                    "configured" if profile.secret_reference else "not configured"
                ),
            )
