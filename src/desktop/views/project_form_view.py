from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.desktop.job_store import JobStore
from src.desktop.widgets import button, card, heading, muted
from src.models.advanced_settings import AdvancedSettings
from src.models.audience_settings import AudienceSettings
from src.models.budget_settings import BudgetSettings
from src.models.duration_config import DurationConfig, DurationMode
from src.models.general_settings import GeneralSettings
from src.models.music_settings import MusicSettings
from src.models.packaging_settings import PackagingSettings
from src.models.project_specification import ProjectSpecification
from src.models.provider_preferences import ProviderPreferences
from src.models.upload_settings import UploadSettings
from src.models.video_settings import VideoSettings
from src.models.visual_settings import VisualSettings
from src.models.voice_settings import VoiceSettings
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)

_DEFAULT_GENRE_IDS = [
    profile.genre_id
    for profile in GenreProfileRegistryService.with_default_profiles().list_all()
]

_LEFT = Qt.AlignmentFlag.AlignLeft


class ProjectFormView(QWidget):
    """
    Project creation form.

    Submitting only maps the entered values into a ProjectSpecification
    and then a VideoJob - it does not run any content generation.
    Research, script, originality review, and scene planning are each
    separate, explicitly triggered steps on ContentStudioView (part of
    ProjectWorkspaceView), so current stage and progress are genuinely
    observable (Sprint 26) rather than hidden inside one atomic call.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        on_created: Callable[[UUID], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._on_created = on_created
        self._job_mapper = ProjectSpecificationJobMapper()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        layout.addWidget(heading("New Project"))
        layout.addWidget(
            muted("Describe the video you want produced. Nothing runs yet.")
        )

        frame, card_layout = card("Project details", icon_name="add")

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(_LEFT)

        self._project_name = QLineEdit()
        form.addRow("Project name", self._project_name)

        self._channel_name = QLineEdit()
        form.addRow("Channel name", self._channel_name)

        self._topic = QLineEdit()
        form.addRow("Topic", self._topic)

        self._video_type = QLineEdit()
        self._video_type.setPlaceholderText("e.g. long-form documentary")
        form.addRow("Video type", self._video_type)

        self._niche = QLineEdit()
        form.addRow("Niche", self._niche)

        self._genre = QComboBox()
        self._genre.addItems(_DEFAULT_GENRE_IDS)
        form.addRow("Genre", self._genre)

        self._duration_seconds = QSpinBox()
        self._duration_seconds.setRange(30, 36000)
        self._duration_seconds.setValue(600)
        form.addRow("Target duration (seconds)", self._duration_seconds)

        self._language = QLineEdit("English")
        form.addRow("Language", self._language)

        self._target_country = QLineEdit("United States")
        form.addRow("Target country", self._target_country)

        self._target_audience = QLineEdit("General audience")
        form.addRow("Target audience", self._target_audience)

        card_layout.addLayout(form)

        layout.addWidget(frame)

        create_button = button("Create project", variant="primary", icon_name="add")
        create_button.clicked.connect(self._handle_create_clicked)
        layout.addWidget(create_button, alignment=_LEFT)

        layout.addStretch()

    def reset(self) -> None:
        """Clear all fields for a fresh project."""

        self._project_name.clear()
        self._channel_name.clear()
        self._topic.clear()
        self._video_type.clear()
        self._niche.clear()

        if _DEFAULT_GENRE_IDS:
            self._genre.setCurrentIndex(0)

        self._duration_seconds.setValue(600)
        self._language.setText("English")
        self._target_country.setText("United States")
        self._target_audience.setText("General audience")

    def _handle_create_clicked(self) -> None:
        try:
            specification = ProjectSpecification(
                general=GeneralSettings(
                    project_name=self._project_name.text(),
                    channel_name=self._channel_name.text(),
                    topic=self._topic.text(),
                    video_type=self._video_type.text(),
                ),
                duration=DurationConfig(
                    mode=DurationMode.EXACT,
                    target_duration_seconds=self._duration_seconds.value(),
                ),
                audience=AudienceSettings(
                    language=self._language.text(),
                    target_country=self._target_country.text(),
                    target_audience=self._target_audience.text(),
                ),
                video=VideoSettings(),
                visual=VisualSettings(),
                voice=VoiceSettings(),
                music=MusicSettings(),
                providers=ProviderPreferences(),
                upload=UploadSettings(),
                packaging=PackagingSettings(),
                budget=BudgetSettings(),
                advanced=AdvancedSettings(),
            )

            job = self._job_mapper.map(specification, niche=self._niche.text())
        except (ValidationError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Could not create project",
                str(error),
            )

            return

        self._job_store.add(job)
        self._on_created(job.id)
