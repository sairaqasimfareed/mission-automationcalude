from __future__ import annotations

from uuid import UUID

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QToolBar

from src.desktop import services
from src.desktop.icons import app_icon, primary_icon
from src.desktop.job_store import JobStore
from src.desktop.views.dashboard_view import DashboardView
from src.desktop.views.project_form_view import ProjectFormView
from src.desktop.views.project_workspace_view import ProjectWorkspaceView
from src.desktop.views.provider_manager_view import ProviderManagerView
from src.desktop.views.settings_view import SettingsView


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
        )

        self._provider_manager_view = ProviderManagerView(
            management_service=services.get_provider_profile_management_service(),
        )

        for view in (
            self._dashboard_view,
            self._form_view,
            self._detail_view,
            self._settings_view,
            self._provider_manager_view,
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

    def _open_project(self, job_id: UUID) -> None:
        self._detail_view.set_job(job_id)
        self._stack.setCurrentWidget(self._detail_view)
