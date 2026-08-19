from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.models.asset_state import SceneAssetState
from src.models.audience_promise import AudiencePromise
from src.models.audio_timeline import AudioTimeline
from src.models.base import MissionBaseModel
from src.models.content_decision_record import ContentDecisionRecord
from src.models.editing_directives import SceneEditingDirectives
from src.models.editorial_critique import EditorialCritique
from src.models.editorial_profile import EditorialProfile
from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    WorkflowStage,
)
from src.models.generated_script import GeneratedScript
from src.models.hook import HookCandidate, HookEvaluation
from src.models.information_reveal_map import InformationRevealMap
from src.models.media_strategy import (
    SceneSourceType,
    VisualStrategy,
    VoiceStatus,
    VoiceStrategy,
)
from src.models.originality import OriginalityResult
from src.models.policy import PolicyComplianceReport
from src.models.re_hook import ReHookPlan
from src.models.render_result import RenderResult
from src.models.research import ResearchResult, ResearchStatus
from src.models.research_plan import ResearchPlan
from src.models.retention_audit import RetentionAuditReport
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.script_quality_report import ScriptQualityReport
from src.models.story_angle import StoryAngle, StoryAngleEvaluation
from src.models.story_blueprint import StoryBlueprint
from src.models.video_clip import VideoClip
from src.models.video_timeline import VideoTimeline


class VideoJob(MissionBaseModel):
    """Central workflow object for one Mission Automation video."""

    project_name: str
    channel_name: str
    niche: str
    topic: str

    platform: Platform = Platform.YOUTUBE
    language: str = "English"
    target_country: str = "United States"
    production_mode: ProductionMode = ProductionMode.PREMIUM

    genre_id: str = "genre.default"

    # Neither field previously existed on VideoJob - ProjectSpecification
    # captures a preferred duration at creation time but VideoJob never
    # persisted it, and there was no target-audience concept at all.
    # Every content-intelligence service downstream needs both.
    target_duration_seconds: int = Field(default=600, gt=0)
    target_audience: str = "general audience"

    status: JobStatus = JobStatus.PENDING
    current_stage: WorkflowStage = WorkflowStage.RESEARCH

    visual_strategy: VisualStrategy = VisualStrategy.HYBRID
    default_visual_source: SceneSourceType = SceneSourceType.MANUAL_UPLOAD
    maximum_visual_budget: float = 0.0

    voice_strategy: VoiceStrategy = VoiceStrategy.MANUAL_UPLOAD
    voice_status: VoiceStatus = VoiceStatus.PENDING
    voice_file: str | None = None
    voice_provider: str | None = None

    research: ResearchResult | None = None
    script: Script | None = None
    originality_review: OriginalityResult | None = None

    # Content Intelligence engine artifacts (sprints 2-7 + A1-A3). Kept
    # alongside the fields above rather than replacing them - the
    # older research/script pipeline stays available until the new
    # engine is proven end-to-end (see ContentIntelligencePipeline).
    editorial_profile_snapshot: EditorialProfile | None = None
    audience_promise: AudiencePromise | None = None
    research_plan: ResearchPlan | None = None
    story_angles: list[StoryAngle] = Field(default_factory=list)
    story_angle_evaluations: list[StoryAngleEvaluation] = Field(default_factory=list)
    selected_story_angle: StoryAngle | None = None
    reveal_map: InformationRevealMap | None = None
    story_blueprint: StoryBlueprint | None = None
    retention_audit: RetentionAuditReport | None = None
    hook_candidates: list[HookCandidate] = Field(default_factory=list)
    hook_evaluations: list[HookEvaluation] = Field(default_factory=list)
    selected_hook: HookEvaluation | None = None
    re_hook_plan: ReHookPlan | None = None
    generated_script: GeneratedScript | None = None
    editorial_critique: EditorialCritique | None = None
    script_quality_report: ScriptQualityReport | None = None

    content_decisions: list[ContentDecisionRecord] = Field(default_factory=list)

    scenes: list[Scene] = Field(default_factory=list)
    scene_asset_states: list[SceneAssetState] = Field(default_factory=list)
    video_clips: list[VideoClip] = Field(default_factory=list)
    scene_editing_overrides: dict[int, SceneEditingDirectives] = Field(
        default_factory=dict
    )

    audio_timeline: AudioTimeline | None = None
    video_timeline: VideoTimeline | None = None
    render_result: RenderResult | None = None

    policy_report: PolicyComplianceReport | None = None

    retry_count: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("genre_id")
    @classmethod
    def validate_genre_id(cls, value: str) -> str:
        normalized = value.strip().lower()

        if not normalized.startswith("genre."):
            raise ValueError("Genre ID must start with 'genre.'.")

        if normalized == "genre.":
            raise ValueError("Genre ID requires a name.")

        return normalized

    @model_validator(mode="after")
    def validate_workflow_state(self) -> VideoJob:
        """Prevent invalid workflow and media states."""

        if self.script is not None:
            if self.research is None:
                raise ValueError("A script cannot exist without research.")

            if self.research.status != ResearchStatus.APPROVED:
                raise ValueError("A script requires approved research.")

        if self.originality_review is not None:
            if self.script is None:
                raise ValueError("Originality review requires a script.")

            if self.script.status != ScriptStatus.APPROVED:
                raise ValueError("Originality review requires an approved script.")

        if self.scenes:
            if self.script is None:
                raise ValueError("Scenes cannot exist without a script.")

            if self.script.status != ScriptStatus.APPROVED:
                raise ValueError("Scene planning requires an approved script.")

        if self.scene_asset_states and not self.scenes:
            raise ValueError("Scene asset states cannot exist without scenes.")

        if self.scene_asset_states:
            scene_numbers = {scene.scene_number for scene in self.scenes}

            state_numbers = {state.scene_number for state in self.scene_asset_states}

            if not state_numbers.issubset(scene_numbers):
                raise ValueError(
                    "Every scene asset state must reference "
                    "an existing scene number."
                )

        if self.video_clips and not self.scenes:
            raise ValueError("Video clips cannot exist without planned scenes.")

        if self.scene_editing_overrides:
            scene_numbers = {scene.scene_number for scene in self.scenes}
            override_numbers = set(self.scene_editing_overrides)

            if not override_numbers.issubset(scene_numbers):
                raise ValueError(
                    "Every scene editing override must reference "
                    "an existing scene number."
                )

            mismatched = {
                scene_number
                for scene_number, override in self.scene_editing_overrides.items()
                if override.scene_number != scene_number
            }

            if mismatched:
                raise ValueError(
                    "Scene editing override scene_number must match " "its dict key."
                )

        if (
            self.voice_strategy == VoiceStrategy.MANUAL_UPLOAD
            and self.voice_status == VoiceStatus.READY
            and not self.voice_file
        ):
            raise ValueError("Manual voiceover cannot be READY without a file.")

        if (
            self.voice_strategy == VoiceStrategy.AUTO_GENERATE
            and self.voice_status == VoiceStatus.READY
            and not self.voice_file
        ):
            raise ValueError("Generated voiceover cannot be READY without a file.")

        if self.audio_timeline is not None and not self.voice_file:
            raise ValueError("Audio timeline requires a voiceover file.")

        if self.video_timeline is not None and not self.video_clips:
            raise ValueError("Video timeline requires ready video clips.")

        if self.render_result is not None:
            if self.video_timeline is None:
                raise ValueError("Render result requires a video timeline.")

            if self.audio_timeline is None:
                raise ValueError("Render result requires an audio timeline.")

        if self.policy_report is not None:
            if self.policy_report.source_mode != self.production_mode:
                raise ValueError(
                    "Policy source_mode must match " "VideoJob production_mode."
                )

        return self
