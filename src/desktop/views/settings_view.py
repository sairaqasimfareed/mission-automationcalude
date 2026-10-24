from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.desktop.notifications import notify_success
from src.desktop.theme import ThemeMode
from src.desktop.widgets import button, muted, small_muted, subheading
from src.services.runtime_configuration_loader import RuntimeConfiguration
from src.services.style_line_store import MAX_STYLE_LINE_CHARACTERS

_COLUMNS = ["Profile ID", "Provider", "Category", "Enabled", "Health", "Secret"]

_THEME_MODE_LABELS: dict[ThemeMode, str] = {
    ThemeMode.SYSTEM: "Match system",
    ThemeMode.LIGHT: "Light",
    ThemeMode.DARK: "Dark",
}


class SettingsView(QWidget):
    """
    Provider settings (read-only) plus the app's own theme preference
    (GUI-1: Light/System theme).

    Provider data is derived from RuntimeConfigurationLoader (Sprint
    21) - secret values are never displayed here, only whether a
    secret is configured.
    """

    def __init__(
        self,
        *,
        get_configuration: Callable[[], RuntimeConfiguration],
        get_theme_mode: Callable[[], ThemeMode] | None = None,
        on_theme_mode_changed: Callable[[ThemeMode], None] | None = None,
        get_style_line: Callable[[], str] | None = None,
        save_style_line: Callable[[str], str] | None = None,
    ) -> None:
        super().__init__()

        self._get_configuration = get_configuration
        self._get_theme_mode = get_theme_mode
        self._on_theme_mode_changed = on_theme_mode_changed
        self._get_style_line = get_style_line
        self._save_style_line = save_style_line

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        layout.addWidget(subheading("Appearance"))

        theme_row = QHBoxLayout()
        theme_row.setSpacing(12)
        theme_row.addWidget(muted("Theme"))

        self._theme_combo = QComboBox()
        for mode, label in _THEME_MODE_LABELS.items():
            self._theme_combo.addItem(label, mode.value)
        theme_row.addWidget(self._theme_combo)
        theme_row.addStretch()
        layout.addLayout(theme_row)

        self._theme_note = small_muted(
            "Changing the theme updates colors immediately. Icons "
            "fully match the new theme after a restart."
        )
        layout.addWidget(self._theme_note)

        if self._get_theme_mode is not None:
            current_mode = self._get_theme_mode()
            index = self._theme_combo.findData(current_mode.value)
            if index >= 0:
                self._theme_combo.setCurrentIndex(index)

        self._theme_combo.currentIndexChanged.connect(self._handle_theme_selected)

        if self._save_style_line is not None:
            layout.addWidget(subheading("Style line for every clip"))
            layout.addWidget(
                small_muted(
                    "One line added as the very first words of every clip prompt, in every "
                    "project - for example: Hand-drawn 2D animation, heavy black ink outlines, "
                    "flat cel colour, never photorealistic or live action. Leave it empty for "
                    "none. It applies to prompts built from now on; in a project that is already "
                    "open, press Save project look (Content tab) to rebuild its prompts. Clips "
                    "that were already generated do not change."
                )
            )
            style_row = QHBoxLayout()
            self._style_line_edit = QLineEdit()
            self._style_line_edit.setMaxLength(MAX_STYLE_LINE_CHARACTERS)
            self._style_line_edit.setPlaceholderText("e.g. Hand-drawn 2D animation ...")
            if self._get_style_line is not None:
                self._style_line_edit.setText(self._get_style_line())
            style_row.addWidget(self._style_line_edit, stretch=1)
            self._style_line_button = button("Save style line", variant="primary")
            self._style_line_button.clicked.connect(self._handle_style_line_saved)
            style_row.addWidget(self._style_line_button)
            layout.addLayout(style_row)

        layout.addWidget(subheading("Provider settings"))

        self._dry_run_label = small_muted("")
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

    def _handle_style_line_saved(self) -> None:
        if self._save_style_line is None:
            return

        kept = self._save_style_line(self._style_line_edit.text())
        self._style_line_edit.setText(kept)
        notify_success("Style line saved" if kept else "Style line removed")

    def _handle_theme_selected(self, _index: int) -> None:
        if self._on_theme_mode_changed is None:
            return

        mode = ThemeMode(self._theme_combo.currentData())
        self._on_theme_mode_changed(mode)

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
