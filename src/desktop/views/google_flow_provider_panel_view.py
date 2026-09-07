from __future__ import annotations

import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
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
from src.models.provider_profile import ProviderCategory
from src.models.provider_profile_management import (
    ProviderProfileSummary,
    ProviderProfileUpsertCommand,
)
from src.providers.google_flow.locators import (
    RECOMMENDED_UNLIMITED_MODEL_FAMILY,
    VERIFIED_FLOW_BASE_URL,
    VERIFIED_MODEL_FAMILIES,
)
from src.providers.google_flow.real_adapter import GoogleFlowRealUIAdapter
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
# initiative: "Check Connection" drives a REAL
# FlowBrowserWorker/GoogleFlowRealUIAdapter against whatever URL the
# operator enters when adding an account - never a URL guessed or
# hardcoded here. This panel asks the operator for the URL explicitly
# rather than fabricating one. Check Connection uses
# GoogleFlowRealUIAdapter (src/providers/google_flow/real_adapter.py),
# built from real, verified selectors
# (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md) - not GoogleFlowUIAdapter,
# whose GoogleFlowLocators selectors remain fixture-only and are for
# tests/fixtures/fake_flow_ui.html, never the real product.
#
# REAL-WORLD FINDING, 2026-09-07: "Open Login" originally drove that
# same Playwright browser through the sign-in step too - a human
# actually tried it and Google rejected it outright ("Couldn't sign
# you in - This browser or app may not be secure"), Google's own
# policy of blocking sign-in from automation-flagged browsers.
# "Open Login" therefore no longer touches Playwright at all - it
# launches the operator's own REAL, already-installed Chrome (see
# src/browser/manual_signin_bootstrap.py) against the exact same
# profile directory FlowBrowserWorker reuses for Check Connection, so
# the human signs in normally, in a genuinely non-automated window,
# with their own password and any 2-step verification never seen by
# this app.


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

        # Real, verified model choices (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md)
        # - every account gets its own choice here, since different
        # accounts can have different subscription tiers/entitlements
        # (e.g. one account's unlimited tier only applies to
        # "Veo 3.1 - Lite", another might prefer "Veo 3.1 - Quality"
        # even if metered). Never hardcoded to one model for every
        # account.
        self._model_family_select = QComboBox()
        self._model_family_select.addItems(list(VERIFIED_MODEL_FAMILIES))
        form.addRow("Model", self._model_family_select)

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
        self._model_family_select.setCurrentText(
            profile.metadata.get("model_family")
            # Same "real, verified default, still fully editable"
            # pattern as the Flow URL field above - a fresh account
            # starts at the recommended unlimited-tier model rather
            # than whatever Flow's own UI happens to default to, but
            # any account can be switched to any of the 4 real models.
            or RECOMMENDED_UNLIMITED_MODEL_FAMILY
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
        model_family = self._model_family_select.currentText()

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
                        "flow_url": flow_url,
                        "model_family": model_family,
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
        # .resolve() is required here, not cosmetic: a relative
        # user-data-dir handed to a *subprocess* (real Chrome, a
        # separate OS process) can resolve against a different
        # working directory than this app's own - confirmed by a real
        # sign-in that landed in the wrong Chrome profile, leaving
        # this directory empty, when a relative path was used.
        # FlowBrowserWorker's own Playwright calls are unaffected (all
        # in-process, sharing this app's one cwd) - this fix is
        # specifically for the cross-process boundary Popen crosses.
        directory = profile_directory(profile_id).resolve()
        directory.mkdir(parents=True, exist_ok=True)

        chrome_executable = find_real_chrome_executable()

        if chrome_executable is None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))
            QMessageBox.warning(
                self,
                "Google Chrome Not Found",
                "Google blocks sign-in from this app's own automated "
                "browser (confirmed: \"Couldn't sign you in - this "
                'browser or app may not be secure"), so signing in '
                "needs your own real Chrome, which could not be found "
                "automatically. Install Google Chrome, or open it "
                "yourself with --user-data-dir pointed at the profile "
                f"folder that has just been opened for you:\n\n{directory}",
            )
            return

        command = manual_sign_in_command(chrome_executable, directory, flow_url)
        clipboard = QApplication.clipboard()

        if clipboard is not None:
            clipboard.setText(command)

        try:
            self._launch_real_chrome(chrome_executable, directory, flow_url)
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
            "Google rejects sign-in attempts from this app's own "
            "automated browser, even with a visible window - "
            "confirmed: \"Couldn't sign you in - this browser or app "
            'may not be secure."\n\n'
            "A real Chrome window has been opened for you instead. "
            "Sign in to Google there exactly as you normally would "
            "(your own password and any 2-step verification - this "
            "app never sees it), then CLOSE that Chrome window "
            "completely and come back here and click Check "
            "Connection.\n\n"
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
        self, chrome_executable: str, directory: Path, flow_url: str
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
                flow_url,
            ]
        )

    def _handle_check_connection_clicked(self) -> None:
        if self._selected_profile_id is None:
            return

        flow_url = self._flow_url_input.text().strip()

        if not flow_url:
            self._show_status("Set the Flow URL above first.", role="warning")
            return

        # GoogleFlowRealUIAdapter, not the fixture-shaped
        # GoogleFlowUIAdapter - Check Connection is exactly the real-
        # account health check this real adapter was built for (see
        # docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md). The fixture adapter's
        # own auth_required_banner selector never exists on the real
        # product, so it always reported "healthy" regardless of
        # actual authentication - this is the fix for that.
        adapter = GoogleFlowRealUIAdapter(
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
