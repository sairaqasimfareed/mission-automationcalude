from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.desktop.approval_mode_labels import APPROVAL_MODE_PRESETS
from src.desktop.job_store import JobStore
from src.desktop.widgets import button, card, heading, muted
from src.models.advanced_settings import AdvancedSettings
from src.models.approval import ApprovalPolicy, ApprovalPolicyConfig
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

# Every ApprovalPolicyConfig decision point, in the pipeline order a
# project actually reaches them, paired with a human-readable label -
# what "Custom Approval" actually configures. Previously this option
# silently reused the same fixed review_critical_stages() preset as
# its own default with no way to change any individual decision point
# despite its name implying otherwise (found via user report) - this
# panel is what makes the name true.
_DECISION_POINT_FIELDS: list[tuple[str, str]] = [
    ("topic", "Topic"),
    ("content_strategy", "Content strategy"),
    ("research_plan", "Research brief"),
    ("research", "Research"),
    ("story_angle", "Story angle"),
    ("narrative_architecture", "Narrative architecture"),
    ("hook", "Hook"),
    ("final_script", "Final script"),
    ("production_plan", "Production plan"),
    ("budget", "Budget"),
    ("final_preview", "Final preview"),
    ("publishing", "Publishing"),
]

_POLICY_LABELS: dict[ApprovalPolicy, str] = {
    ApprovalPolicy.AUTO: "Auto-continue",
    ApprovalPolicy.REVIEW: "Review if uncertain",
    ApprovalPolicy.MANUAL: "Always require approval",
}
_LABEL_TO_POLICY = {label: policy for policy, label in _POLICY_LABELS.items()}


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

        # Scrollable, matching ContentStudioView's own established
        # pattern - found via user report: this form's total content
        # (Project details + the new 12-row Custom Approval panel + AI
        # configuration) now exceeds a fixed window's height, and
        # without a scroll area Qt's layout engine compresses/clips
        # rows silently instead of showing them, rather than any
        # widget actually failing to render.
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        content_container = QWidget()
        layout = QVBoxLayout(content_container)
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
        self._approval_mode.currentTextChanged.connect(
            self._handle_approval_mode_changed
        )
        form.addRow("Approval mode", self._approval_mode)

        card_layout.addLayout(form)

        layout.addWidget(frame)

        self._custom_approval_frame, custom_approval_layout = card(
            "Custom approval - per stage", icon_name="settings"
        )
        custom_approval_layout.addWidget(
            muted(
                "Choose how much human review each stage requires. "
                "'Review if uncertain' still auto-continues when the "
                "generated result looks confident."
            )
        )

        custom_approval_form = QFormLayout()
        custom_approval_form.setSpacing(10)
        custom_approval_form.setLabelAlignment(_LEFT)

        defaults = ApprovalPolicyConfig.review_critical_stages()
        self._decision_point_selects: dict[str, QComboBox] = {}

        for field_name, field_label in _DECISION_POINT_FIELDS:
            select = QComboBox()
            select.addItems(list(_POLICY_LABELS.values()))
            select.setCurrentText(_POLICY_LABELS[getattr(defaults, field_name)])
            custom_approval_form.addRow(field_label, select)
            self._decision_point_selects[field_name] = select

        custom_approval_layout.addLayout(custom_approval_form)
        layout.addWidget(self._custom_approval_frame)
        self._handle_approval_mode_changed(self._approval_mode.currentText())

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

        scroll_area.setWidget(content_container)
        outer_layout.addWidget(scroll_area)

    def _handle_approval_mode_changed(self, mode: str) -> None:
        self._custom_approval_frame.setVisible(mode == "Custom Approval")

    def _build_approval_policy(self) -> ApprovalPolicyConfig:
        mode = self._approval_mode.currentText()

        if mode != "Custom Approval":
            return APPROVAL_MODE_PRESETS[mode]()

        def policy_for(field_name: str) -> ApprovalPolicy:
            return _LABEL_TO_POLICY[
                self._decision_point_selects[field_name].currentText()
            ]

        return ApprovalPolicyConfig(
            topic=policy_for("topic"),
            content_strategy=policy_for("content_strategy"),
            research_plan=policy_for("research_plan"),
            research=policy_for("research"),
            story_angle=policy_for("story_angle"),
            narrative_architecture=policy_for("narrative_architecture"),
            hook=policy_for("hook"),
            final_script=policy_for("final_script"),
            production_plan=policy_for("production_plan"),
            budget=policy_for("budget"),
            final_preview=policy_for("final_preview"),
            publishing=policy_for("publishing"),
        )

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

        defaults = ApprovalPolicyConfig.review_critical_stages()
        for field_name, select in self._decision_point_selects.items():
            select.setCurrentText(_POLICY_LABELS[getattr(defaults, field_name)])

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
            job.approval_policy = self._build_approval_policy()
        except (ValidationError, ValueError) as error:
            QMessageBox.warning(
                self,
                "Could not create project",
                str(error),
            )

            return

        self._job_store.add(job)
        self._on_created(job.id)
