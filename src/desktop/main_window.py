from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QToolBar

from src.desktop import services
from src.desktop.icons import app_icon, primary_icon
from src.desktop.job_store import JobStore
from src.desktop.theme import ThemeMode, apply_theme
from src.desktop.views.dashboard_view import DashboardView
from src.desktop.views.google_flow_provider_panel_view import (
    GoogleFlowProviderPanelView,
)
from src.desktop.views.project_form_view import ProjectFormView
from src.desktop.views.project_workspace_view import ProjectWorkspaceView
from src.desktop.views.provider_manager_view import ProviderManagerView
from src.desktop.views.settings_view import SettingsView
from src.desktop.views.voice_manager_view import VoiceManagerView


class MainWindow(QMainWindow):
    """
    Mission Automation desktop control panel.

    Backend/UI boundary: this window and its views depend only on
    src.desktop.services (which wraps ContentPipeline,
    SEOPackageService, ThumbnailPackageService,
    PipelineCheckpointStorageService, and the durable JobStore).
    Nothing here imports FFmpeg, a provider SDK, or other
    implementation details directly - core services stay unaware a
    desktop UI exists.
    """

    def __init__(self, *, job_store: JobStore | None = None) -> None:
        super().__init__()

        self.setWindowTitle("Mission Automation")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self.setMinimumSize(900, 600)

        self._job_store = (
            job_store if job_store is not None else services.get_job_store()
        )

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._dashboard_view = DashboardView(
            job_store=self._job_store,
            checkpoint_storage=services.get_checkpoint_storage_service(),
            on_open_project=self._open_project,
        )

        self._form_view = ProjectFormView(
            job_store=self._job_store,
            provider_profile_management_service=(
                services.get_provider_profile_management_service()
            ),
            on_created=self._open_project,
        )

        self._detail_view = ProjectWorkspaceView(
            job_store=self._job_store,
            reviewer_service=services.get_reviewer_service(),
            topic_candidate_generation_service=(
                services.get_topic_candidate_generation_service()
            ),
            fact_check_service=services.get_fact_check_service(),
            content_pipeline=services.get_content_pipeline(),
            content_intelligence_pipeline=(
                services.get_content_intelligence_pipeline()
            ),
            render_runtime_factory=services.get_render_runtime_factory(),
            asset_workflow_service=services.get_asset_workflow_service(),
            media_generation_pipeline=services.get_media_generation_pipeline(),
            final_export_service=services.get_final_export_service(),
            seo_package_service=services.get_seo_package_service(),
            thumbnail_package_service=services.get_thumbnail_package_service(),
            on_back=self.show_dashboard,
        )

        self._settings_view = SettingsView(
            get_configuration=services.get_runtime_configuration,
            get_theme_mode=services.get_theme_preference_store().load,
            on_theme_mode_changed=self._handle_theme_mode_changed,
        )

        self._provider_manager_view = ProviderManagerView(
            management_service=services.get_provider_profile_management_service(),
        )

        self._google_flow_provider_panel_view = GoogleFlowProviderPanelView(
            management_service=services.get_provider_profile_management_service(),
            browser_worker=services.get_google_flow_browser_worker(),
        )

        self._voice_manager_view = VoiceManagerView(
            voice_provider_mapping_service=(
                services.get_voice_provider_mapping_service()
            ),
            voice_profile_registry=services.get_voice_profile_registry_service(),
            genre_profile_registry=services.get_runtime_configuration().genre_registry,
        )

        for view in (
            self._dashboard_view,
            self._form_view,
            self._detail_view,
            self._settings_view,
            self._provider_manager_view,
            self._google_flow_provider_panel_view,
            self._voice_manager_view,
        ):
            self._stack.addWidget(view)

        self._build_toolbar()
        self.show_dashboard()

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)

        dashboard_action = QAction(primary_icon("dashboard"), "Dashboard", self)
        dashboard_action.triggered.connect(self.show_dashboard)
        toolbar.addAction(dashboard_action)

        new_project_action = QAction(primary_icon("add"), "New Project", self)
        new_project_action.triggered.connect(self.show_new_project)
        toolbar.addAction(new_project_action)

        provider_manager_action = QAction(primary_icon("shield"), "Providers", self)
        provider_manager_action.triggered.connect(self.show_provider_manager)
        toolbar.addAction(provider_manager_action)

        google_flow_action = QAction(primary_icon("shield"), "Google Flow", self)
        google_flow_action.triggered.connect(self.show_google_flow_provider_panel)
        toolbar.addAction(google_flow_action)

        voice_manager_action = QAction(primary_icon("audio"), "Voices", self)
        voice_manager_action.triggered.connect(self.show_voice_manager)
        toolbar.addAction(voice_manager_action)

        settings_action = QAction(primary_icon("settings"), "Settings", self)
        settings_action.triggered.connect(self.show_settings)
        toolbar.addAction(settings_action)

    def show_dashboard(self) -> None:
        self._dashboard_view.refresh()
        self._stack.setCurrentWidget(self._dashboard_view)

    def show_new_project(self) -> None:
        self._form_view.reset()
        self._stack.setCurrentWidget(self._form_view)

    def show_settings(self) -> None:
        self._settings_view.refresh()
        self._stack.setCurrentWidget(self._settings_view)

    def show_provider_manager(self) -> None:
        self._provider_manager_view.refresh()
        self._stack.setCurrentWidget(self._provider_manager_view)

    def show_google_flow_provider_panel(self) -> None:
        self._google_flow_provider_panel_view.refresh()
        self._stack.setCurrentWidget(self._google_flow_provider_panel_view)

    def show_voice_manager(self) -> None:
        self._voice_manager_view.refresh()
        self._stack.setCurrentWidget(self._voice_manager_view)

    def _open_project(self, job_id: UUID) -> None:
        self._detail_view.set_job(job_id)
        self._stack.setCurrentWidget(self._detail_view)

    def _handle_theme_mode_changed(self, mode: ThemeMode) -> None:
        """
        Persist and immediately apply a new theme preference (GUI-1).

        `QApplication.instance()` is always non-None here - this
        method only runs in response to a user interacting with an
        already-constructed SettingsView, which requires a running
        QApplication. apply_theme() re-colors the palette/stylesheet
        live; icons only fully catch up after a restart, per its own
        docstring - SettingsView's note text says so directly rather
        than silently under-delivering.
        """

        services.get_theme_preference_store().save(mode)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, mode)
