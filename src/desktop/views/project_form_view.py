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

from src.desktop.approval_mode_labels import APPROVAL_MODE_PRESETS
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
from src.models.provider_preferences import (
    ProviderPreferences,
    ReviewerConfiguration,
)
from src.models.provider_profile import ProviderCategory
from src.models.upload_settings import UploadPlatform, UploadSettings
from src.models.video_settings import VideoSettings
from src.models.visual_settings import VisualSettings
from src.models.voice_settings import VoiceSettings
from src.services.genre_profile_registry_service import (
    GenreProfileRegistryService,
)
from src.services.project_specification_job_mapper import (
    ProjectSpecificationJobMapper,
)
from src.services.provider_profile_management_service import (
    ProviderProfileManagementService,
)

_DEFAULT_GENRE_IDS = [
    profile.genre_id
    for profile in GenreProfileRegistryService.with_default_profiles().list_all()
]

_PLATFORM_CHOICES = [
    UploadPlatform.YOUTUBE.value,
    UploadPlatform.FACEBOOK.value,
    UploadPlatform.TIKTOK.value,
]

_NO_PROVIDER_CHOICE = "System default"

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
        provider_profile_management_service: ProviderProfileManagementService,
        on_created: Callable[[UUID], None],
    ) -> None:
        super().__init__()

        self._job_store = job_store
        self._provider_profile_management_service = provider_profile_management_service
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

        self._platform = QComboBox()
        self._platform.addItems(_PLATFORM_CHOICES)
        form.addRow("Platform", self._platform)

        self._approval_mode = QComboBox()
        self._approval_mode.addItems(list(APPROVAL_MODE_PRESETS))
        self._approval_mode.setCurrentText("Custom Approval")
        form.addRow("Approval mode", self._approval_mode)

        card_layout.addLayout(form)

        layout.addWidget(frame)

        ai_frame, ai_card_layout = card("AI configuration", icon_name="settings")
        ai_form = QFormLayout()
        ai_form.setSpacing(10)
        ai_form.setLabelAlignment(_LEFT)

        llm_profile_choices = [_NO_PROVIDER_CHOICE] + [
            profile.profile_id
            for profile in (self._provider_profile_management_service.list_profiles())
            if profile.category == ProviderCategory.LLM
        ]

        self._primary_llm = QComboBox()
        self._primary_llm.addItems(llm_profile_choices)
        ai_form.addRow("Primary LLM", self._primary_llm)

        self._reviewer_llm = QComboBox()
        self._reviewer_llm.addItems(llm_profile_choices)
        ai_form.addRow("Reviewer LLM", self._reviewer_llm)

        self._fallback_llm = QComboBox()
        self._fallback_llm.addItems(llm_profile_choices)
        ai_form.addRow("Fallback LLM", self._fallback_llm)

        ai_card_layout.addLayout(ai_form)
        ai_card_layout.addWidget(
            muted(
                'Leave any role as "System default" to use whatever the '
                "application is already configured with - a project never "
                "requires explicit provider selection to be created."
            )
        )

        layout.addWidget(ai_frame)

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

        self._platform.setCurrentIndex(0)
        self._approval_mode.setCurrentText("Custom Approval")
        self._primary_llm.setCurrentIndex(0)
        self._reviewer_llm.setCurrentIndex(0)
        self._fallback_llm.setCurrentIndex(0)

    def _build_provider_preferences(self) -> ProviderPreferences:
        """
        Every role defaults to "System default" (None) - a project
        never requires explicit provider selection, matching the
        redesign's own "Reviewer provider/model or None, Fallback
        provider/model or None" wording. Primary/Fallback map onto the
        llm category's existing preferred/fallback fields; Reviewer is
        the one genuinely new role (ReviewerConfiguration).
        """

        preferences = ProviderPreferences()

        primary = self._primary_llm.currentText()
        if primary != _NO_PROVIDER_CHOICE:
            preferences.llm.preferred_profile_id = primary

        fallback = self._fallback_llm.currentText()
        if fallback != _NO_PROVIDER_CHOICE:
            preferences.llm.fallback_profile_ids = [fallback]

        reviewer = self._reviewer_llm.currentText()
        if reviewer != _NO_PROVIDER_CHOICE:
            preferences.reviewer = ReviewerConfiguration(reviewer_profile_id=reviewer)

        return preferences

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
                providers=self._build_provider_preferences(),
                upload=UploadSettings(
                    platform=UploadPlatform(self._platform.currentText())
                ),
                packaging=PackagingSettings(),
                budget=BudgetSettings(),
                advanced=AdvancedSettings(),
            )

            job = self._job_mapper.map(specification, niche=self._niche.text())
            job.genre_id = self._genre.currentText()
            job.approval_policy = APPROVAL_MODE_PRESETS[
                self._approval_mode.currentText()
            ]()
        except (ValidationError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Could not create project",
                str(error),
            )

            return

        self._job_store.add(job)
        self._on_created(job.id)
