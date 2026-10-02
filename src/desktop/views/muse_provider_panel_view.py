from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
from src.browser.manual_signin_bootstrap import (
    find_real_chrome_executable,
    manual_sign_in_command,
)
from src.desktop.widgets import badge, button, card, heading, muted, row, status_label
from src.models.provider_profile import ProviderCategory, ProviderHealthStatus
from src.models.provider_profile_management import (
    ProviderProfileSummary,
    ProviderProfileUpsertCommand,
)
from src.providers.muse.real_adapter import (
    DEFAULT_MUSE_PROFILES_ROOT,
    MuseRealUIAdapter,
)
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)

# Muse (muse.ai) External UI Automation - same real, screenshot-
# verified structure as GoogleFlowProviderPanelView, simplified for
# what Muse's real UI actually has: no settings panel to pick a model
# family from, and no "Confirm before generating" account-level toggle
# to expose a separate button for - neither has been found to exist on
# the real product (see locators.py's own docstring), so nothing here
# fabricates a control for either.
#
# 2026-09-30: an editable "Muse URL" field was added for parity with
# Google Flow's own per-account URL field, even though muse.ai itself
# has no per-account/per-project URL the way Flow does - every real
# Muse account lands at the same https://muse.ai. Every account
# defaults to that same real URL and most operators will never need to
# change it; the field stays editable per-account (mirroring Flow's
# own pattern exactly, including Open Login/Check Connection both
# requiring it to be set) for the same reasons Flow's is: a staging URL
# during troubleshooting, or a future muse.ai workspace/subdomain this
# app hasn't seen yet.
#
# Same real-world finding as Google Flow's own panel: Muse's login is
# Meta Account + email OTP - never automated. "Open Login" launches
# the operator's own real, already-installed Chrome (never this app's
# own automated browser) against the exact same profile directory
# MuseRealUIAdapter/FlowBrowserWorker reuse for Check Connection, so
# the human signs in normally, with their own password and the OTP
# code, never seen by this app.
_MUSE_BASE_URL = "https://muse.ai"


class MuseProviderPanelView(QWidget):
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
        self._muse_urls: dict[str, str] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(16)

        outer.addWidget(heading("Muse Accounts"))
        outer.addWidget(
            muted(
                "Configure one or more Muse (muse.ai) accounts. Each "
                "account authenticates through its own persistent "
                "browser profile - never a password stored here."
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

        self._muse_url_input = QLineEdit()
        self._muse_url_input.setPlaceholderText(_MUSE_BASE_URL)
        form.addRow("Muse URL", self._muse_url_input)

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
        """Reload Muse accounts from the management service."""

        self._profiles = [
            profile
            for profile in self._service.list_profiles()
            if profile.category == ProviderCategory.EXTERNAL_UI_VIDEO
            and profile.provider_name == "Muse"
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
        self._muse_url_input.setText(
            self._muse_urls.get(profile_id)
            or profile.metadata.get("muse_url")
            or _MUSE_BASE_URL
        )
        self._health_badge.setText(profile.health_status.value)

    def _handle_add_clicked(self) -> None:
        profile_id, accepted = QInputDialog.getText(
            self, "Add Muse Account", "Account id (e.g. muse.primary):"
        )

        if not accepted or not profile_id.strip():
            return

        display_name, accepted = QInputDialog.getText(
            self, "Add Muse Account", "Display name:"
        )

        if not accepted or not display_name.strip():
            return

        try:
            directory = profile_directory(
                profile_id.strip(), root=DEFAULT_MUSE_PROFILES_ROOT
            )
        except UnsafeProfileIdError as error:
            QMessageBox.warning(self, "Add Muse Account", str(error))
            return

        try:
            self._service.upsert_profile(
                ProviderProfileUpsertCommand(
                    profile_id=profile_id.strip(),
                    display_name=display_name.strip(),
                    provider_name="Muse",
                    category=ProviderCategory.EXTERNAL_UI_VIDEO,
                    enabled=False,
                    browser_profile_reference=str(directory),
                )
            )
        except ValueError as error:
            QMessageBox.warning(self, "Add Muse Account", str(error))
            return

        self.refresh()
        self._select_profile_id(profile_id.strip())

    def _handle_save_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        profile_id = self._selected_profile_id
        profile = next(p for p in self._profiles if p.profile_id == profile_id)
        muse_url = self._muse_url_input.text().strip()
        self._muse_urls[profile_id] = muse_url

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
                    metadata={
                        **profile.metadata,
                        "muse_url": muse_url,
                    },
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
            "Delete Muse Account",
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

        muse_url = self._muse_url_input.text().strip()

        if not muse_url:
            self._show_status(
                "Set the Muse URL above and Save before opening login.",
                role="warning",
            )
            return

        profile_id = self._selected_profile_id
        # .resolve() is required here, not cosmetic - same real-world
        # finding as Google Flow's own Open Login: a relative user-
        # data-dir handed to a subprocess (real Chrome, a separate OS
        # process) can resolve against a different working directory
        # than this app's own.
        directory = profile_directory(
            profile_id, root=DEFAULT_MUSE_PROFILES_ROOT
        ).resolve()
        directory.mkdir(parents=True, exist_ok=True)

        chrome_executable = find_real_chrome_executable()

        if chrome_executable is None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
            QMessageBox.warning(
                self,
                "Google Chrome Not Found",
                "Muse's real sign-in (Meta Account + email code) needs "
                "your own real Chrome, which could not be found "
                "automatically. Install Google Chrome, or open it "
                "yourself with --user-data-dir pointed at the profile "
                f"folder that has just been opened for you:\n\n{directory}",
            )
            return

        command = manual_sign_in_command(chrome_executable, directory, muse_url)
        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(command)

        try:
            self._launch_real_chrome(chrome_executable, directory, muse_url)
        except OSError as error:
            self._show_status(
                f"Could not launch Chrome automatically ({error}) - the "
                "sign-in command has been copied to your clipboard; run "
                "it yourself, sign in, close that window fully, then "
                "use Check Connection.",
                role="error",
            )
            return

        QMessageBox.information(
            self,
            "Sign In With Your Real Chrome",
            "A real Chrome window has been opened for you. Sign in to "
            "Muse there exactly as you normally would (your Meta "
            "Account password and the emailed code - this app never "
            "sees either), then CLOSE that Chrome window completely "
            "and come back here and click Check Connection.\n\n"
            "If you already had Chrome open elsewhere, please fully "
            "quit every Chrome window (check the system tray too) and "
            "click Open Login again before signing in - otherwise "
            "Chrome can silently sign you in to your regular, "
            "everyday profile instead of the one this app will "
            "actually check.\n\n"
            "The sign-in command has also been copied to your "
            "clipboard in case you need to run it again.",
        )

        self._show_status(
            "Real Chrome opened for manual sign-in - close it fully "
            "after signing in, then use Check Connection.",
            role="success",
        )

    def _launch_real_chrome(
        self, chrome_executable: str, directory: Path, muse_url: str
    ) -> None:
        """
        Launch the operator's own, already-installed Chrome - never
        Playwright's Chromium - against the given profile directory.

        Split out from _handle_open_login_clicked so tests can patch
        subprocess.Popen without also needing a real Chrome binary on
        the test machine.
        """

        subprocess.Popen(  # noqa: S603
            [
                chrome_executable,
                f"--user-data-dir={directory}",
                "--no-first-run",
                "--no-default-browser-check",
                muse_url,
            ]
        )

    def _handle_check_connection_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        muse_url = self._muse_url_input.text().strip()

        if not muse_url:
            self._show_status("Set the Muse URL above first.", role="warning")
            return

        adapter = MuseRealUIAdapter(
            worker=self._browser_worker,
            base_url=muse_url,
            headless=False,
        )

        try:
            healthy = adapter.check_profile_health(self._selected_profile_id)
        except Exception as error:  # noqa: BLE001
            self._show_status(f"Check failed: {error}", role="error")
            return

        # Same real fix as Google Flow's own Check Connection: persist
        # the result onto the profile - ProviderProfile.usable requires
        # health_status HEALTHY/DEGRADED, so an unpersisted check would
        # leave a real, working account permanently unusable to the
        # account router.
        updated_summary = self._service.set_health_status(
            self._selected_profile_id,
            (
                ProviderHealthStatus.HEALTHY
                if healthy
                else ProviderHealthStatus.UNHEALTHY
            ),
        )
        self._health_badge.setText(
            f"{updated_summary.display_name}  ·  {updated_summary.health_status.value}"
        )

        if healthy:
            self._show_status("Connection looks healthy.", role="success")
        else:
            self._show_status(
                "Not authenticated (or the page layout is unrecognized) - "
                "click Open Login to sign in with your real Chrome, "
                "then try Check Connection again.",
                role="warning",
            )

    def _show_status(self, text: str, *, role: str) -> None:
        self._status.setText(text)
        self._status.setProperty("role", role)
        self._status.style().unpolish(self._status)
        self._status.style().polish(self._status)
        self._status.show()
