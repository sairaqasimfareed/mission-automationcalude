from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from src.models.approval import ApprovalPolicyConfig
from src.models.artifact_lifecycle import ArtifactVersionRecord
from src.models.asset_state import SceneAssetState
from src.models.audience_promise import AudiencePromise
from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.audio_timeline import AudioTimeline
from src.models.base import MissionBaseModel
from src.models.cinematic_prompt import CinematicPromptPackage
from src.models.content_decision_record import ContentDecisionRecord
from src.models.continuity_bible import ContinuityBible, ContinuityValidationResult
from src.models.creative_direction import CreativeDirection
from src.models.editing_directives import SceneEditingDirectives
from src.models.editorial_critique import EditorialCritique
from src.models.editorial_profile import EditorialProfile
from src.models.enums import (
    JobStatus,
    Platform,
    ProductionMode,
    ScriptOrigin,
    WorkflowStage,
)
from src.models.final_preview import FinalPreview
from src.models.generated_script import GeneratedScript
from src.models.google_flow_generation import GoogleFlowGenerationAttempt
from src.models.hook import HookCandidate, HookEvaluation
from src.models.information_reveal_map import InformationRevealMap
from src.models.invalidation import StaleArtifact
from src.models.manual_audio_requirement import ManualAudioRequirement
from src.models.media_strategy import (
    SceneSourceType,
    VisualStrategy,
    VoiceStatus,
    VoiceStrategy,
)
from src.models.originality import OriginalityResult
from src.models.packaging_hypothesis import PackagingHypothesis
from src.models.policy import PolicyComplianceReport
from src.models.production_ambiguity import ProductionAmbiguity
from src.models.production_semantic_brief import ProductionSemanticBrief
from src.models.provider_preferences import ProviderPreferences
from src.models.re_hook import ReHookPlan
from src.models.render_result import RenderResult
from src.models.research import ResearchResult, ResearchStatus
from src.models.research_plan import ResearchPlan
from src.models.retention_audit import RetentionAuditReport
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.script_intake import ScriptIntakeResult
from src.models.script_lock import ScriptLock
from src.models.script_quality_report import ScriptQualityReport
from src.models.script_version import ScriptVersionHistory
from src.models.shot_planning import CinematicShotPlan
from src.models.sound_design_plan import SoundDesignPlan
from src.models.story_angle import StoryAngle, StoryAngleEvaluation
from src.models.story_blueprint import StoryBlueprint
from src.models.thumbnail import ThumbnailTextPosition
from src.models.topic_candidate import TopicCandidate
from src.models.video_clip import VideoClip
from src.models.video_timeline import VideoTimeline
from src.models.visual_continuity import VisualContinuityBible
from src.models.writing_directives import WritingDirectiveSet


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

    # Real-world finding, 2026-09-14: nothing anywhere let a user
    # choose this - project_render_runtime_factory.py/
    # render_workflow_stage_factory.py/TimelinePipelineStage all
    # defaulted output_resolution to "1920x1080" at every layer, with
    # no caller ever overriding it, so every render silently upscaled
    # from whatever a scene's real source actually was (Google Flow's
    # own clips render at 720p). A plain WIDTHxHEIGHT string, matching
    # VideoTimeline.output_resolution's own convention exactly (that
    # field is the resolved OUTPUT of building the timeline; this one
    # is the upstream, user-facing choice that drives it) - the GUI
    # constrains the picker to a fixed preset list rather than free
    # text, so no format validator is needed here.
    output_resolution: str = "1920x1080"

    # Distinct from production_mode above (render quality/cost
    # tradeoff) - this controls how much human review each content
    # decision point requires. Defaults to the conservative
    # "Custom Approval" preset (see ApprovalPolicyConfig.
    # review_critical_stages) rather than a bare ApprovalPolicyConfig()
    # construction, so the default is nameable the same way a user
    # picks it from the settings panel.
    approval_policy: ApprovalPolicyConfig = Field(
        default_factory=ApprovalPolicyConfig.review_critical_stages
    )

    # Content Studio Redesign, Phase 2: project-level Primary/Reviewer/
    # Fallback LLM roles and per-category provider preferences.
    # ProjectSpecification already carried a ProviderPreferences value
    # at creation time, but ProjectSpecificationJobMapper silently
    # discarded it - VideoJob never actually persisted it before this
    # field existed.
    provider_preferences: ProviderPreferences = Field(
        default_factory=ProviderPreferences
    )

    # How this project's script was (or will be) obtained - see
    # ScriptOrigin. Every project defaults to INTERNAL until the
    # "Import Approved Script" alternate path (Phase 15) exists.
    script_origin: ScriptOrigin = ScriptOrigin.INTERNAL

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
    voice_script_version: int | None = None

    manual_audio_requirements: list[ManualAudioRequirement] = Field(
        default_factory=list
    )

    research: ResearchResult | None = None
    script: Script | None = None
    originality_review: OriginalityResult | None = None

    # Content Intelligence engine artifacts (sprints 2-7 + A1-A3). Kept
    # alongside the fields above rather than replacing them - the
    # older research/script pipeline stays available until the new
    # engine is proven end-to-end (see ContentIntelligencePipeline).
    editorial_profile_snapshot: EditorialProfile | None = None

    # Content Studio Redesign, Phase 5: Topic Intelligence Workspace.
    # `topic` above remains the free-text seed idea typed at project
    # creation; these fields hold the AI-scored candidates generated
    # from it and whichever one (AI-generated or user-authored via
    # TopicCandidate.custom()) was actually selected. Deliberately not
    # wired into ContentIntelligencePipeline.run_all() yet - selecting
    # a topic candidate does not change `topic` itself, so the
    # existing pipeline keeps working unchanged whether or not a
    # project has used this workspace (see content_studio_view.py's
    # Topic card for the honest-scoping note on why this stays a
    # standalone panel rather than a new pipeline stage for now).
    topic_candidates: list[TopicCandidate] = Field(default_factory=list)
    selected_topic_candidate: TopicCandidate | None = None

    audience_promise: AudiencePromise | None = None
    research_plan: ResearchPlan | None = None
    story_angles: list[StoryAngle] = Field(default_factory=list)
    story_angle_evaluations: list[StoryAngleEvaluation] = Field(default_factory=list)
    selected_story_angle: StoryAngle | None = None

    # Content Studio Redesign, Phase 6: Audience & Creative Strategy
    # Workspace. Separate from selected_story_angle above (which the
    # pipeline still auto-picks via story angle evaluation scoring) -
    # creative_direction is only set once a human explicitly confirms
    # (or overrides via Select/Combine/Write My Own) a narrative
    # thesis and constraints for that choice, and is versioned/
    # approved independently per the redesign's own requirement.
    creative_direction: CreativeDirection | None = None
    reveal_map: InformationRevealMap | None = None
    story_blueprint: StoryBlueprint | None = None
    retention_audit: RetentionAuditReport | None = None
    hook_candidates: list[HookCandidate] = Field(default_factory=list)
    hook_evaluations: list[HookEvaluation] = Field(default_factory=list)
    selected_hook: HookEvaluation | None = None
    re_hook_plan: ReHookPlan | None = None

    # Content Studio Redesign, Phase 11: Script Workspace - Writing
    # Directives. project_writing_rules/user_writing_directives are
    # the raw, human-edited inputs (PROJECT/USER sources);
    # writing_directives is the resolved artifact
    # WritingDirectivesService.resolve() produces from them plus the
    # genre defaults and the fixed system directives - distinct from
    # Story Architecture per this phase's own goal.
    project_writing_rules: list[str] = Field(default_factory=list)
    user_writing_directives: list[str] = Field(default_factory=list)
    writing_directives: WritingDirectiveSet | None = None

    generated_script: GeneratedScript | None = None
    editorial_critique: EditorialCritique | None = None
    script_quality_report: ScriptQualityReport | None = None
    packaging_hypothesis: PackagingHypothesis | None = None
    script_version_history: ScriptVersionHistory | None = None
    # Content Studio Redesign, Phase 14: the hard Content Production /
    # Media Production boundary. None means the script is not locked.
    script_lock: ScriptLock | None = None
    # Content Studio Redesign, Phase 15: set only for a script that
    # entered via Script Intake (paste/upload) rather than Content
    # Production - None means no external script was ever imported.
    script_intake_result: ScriptIntakeResult | None = None
    # Content Studio Redesign, Phase 16: production-relevant questions
    # the script's own text does not settle - append-only, like every
    # other audit trail in this codebase.
    production_ambiguities: list[ProductionAmbiguity] = Field(default_factory=list)
    continuity_bible: ContinuityBible | None = None
    continuity_validation: ContinuityValidationResult | None = None
    # Post-Script-Approval Production Plan, Phase 1: time-bounded
    # production intent for the locked script - None until generated,
    # requires script_lock to exist first.
    production_semantic_brief: ProductionSemanticBrief | None = None
    # Post-Script-Approval Production Plan, Phase 2: the authoritative
    # per-clip visual state machine - None until generated, requires
    # scenes to exist first.
    visual_continuity_bible: VisualContinuityBible | None = None
    # Post-Script-Approval Production Plan, Phase 3: one shot
    # specification per planned clip - None until generated, requires
    # a visual continuity bible to exist first.
    cinematic_shot_plan: CinematicShotPlan | None = None
    # Post-Script-Approval Production Plan, Phase 4: one resolved,
    # provider-facing prompt per shot - None until compiled, requires
    # a cinematic shot plan to exist first. Quality scores are added
    # by a separate evaluation pass and may be absent even once the
    # package itself exists.
    cinematic_prompt_package: CinematicPromptPackage | None = None

    content_decisions: list[ContentDecisionRecord] = Field(default_factory=list)
    stale_artifacts: list[StaleArtifact] = Field(default_factory=list)

    # Content Studio Redesign, Phase 1: the canonical artifact-lifecycle
    # ledger. Append-only, same convention as content_decisions/
    # stale_artifacts above - a version's status advances by replacing
    # its entry in this list (matching id, new status), never by
    # deleting anything. Deliberately not yet wired into any real
    # content-intelligence stage - see docs/CONTENT_STUDIO_REDESIGN_BASELINE.md;
    # this field exists so ArtifactLifecycleService/
    # ArtifactDependencyGraphService have somewhere real to persist to
    # once a workspace starts registering versions into it.
    artifact_versions: list[ArtifactVersionRecord] = Field(default_factory=list)

    scenes: list[Scene] = Field(default_factory=list)
    scene_asset_states: list[SceneAssetState] = Field(default_factory=list)
    video_clips: list[VideoClip] = Field(default_factory=list)
    scene_editing_overrides: dict[int, SceneEditingDirectives] = Field(
        default_factory=dict
    )

    audio_timeline: AudioTimeline | None = None
    video_timeline: VideoTimeline | None = None
    render_result: RenderResult | None = None

    # REQ-10(a): independent, per-project, genre-independent mux-time
    # audio inclusion toggles - see AudioInclusionPreferences' own
    # docstring. Real dataclass default (not None) so an existing job
    # loaded from storage before this field existed gets today's
    # real, implicit behavior (every generated track type included)
    # rather than an extra None-check at every call site.
    audio_inclusion_preferences: AudioInclusionPreferences = Field(
        default_factory=AudioInclusionPreferences
    )

    # REQ-00 Stage 1: a video-only render's own result, kept distinct
    # from render_result (which still means the real, final composite
    # render - Stage 2's audio mux and Stage 3's subtitle burn-in don't
    # exist yet, so render_result stays the only thing anything today
    # treats as "the finished video"). Populated only by
    # RenderPipelineStage.execute_video_only(), which nothing calls
    # yet - no real caller (REQ-0A's review gate, Stage 2's own mux
    # service) is built yet either.
    video_only_render_result: RenderResult | None = None

    # REQ-3 (cinematic letterboxing), 2026-09-22: real per-project
    # override switch on top of the genre's own
    # GenreEditingProfile.letterbox_enabled_by_default. None (the
    # default) means "inherit the genre's own default" - an existing
    # job loaded from storage before this field existed keeps behaving
    # exactly as its genre already specifies, no extra migration
    # needed. True/False is an explicit user choice that always wins
    # over the genre default, resolved once per render by whichever
    # caller builds the render workflow (RenderWorkflowStageFactory.
    # build(), same resolution-order pattern as transition_duration_
    # seconds' own genre-profile lookup).
    letterbox_enabled: bool | None = None

    # Subtitle on/off toggle, 2026-09-23: real per-project switch for
    # whether the final video burns subtitles in at all - defaults to
    # True, reproducing every render's real prior behavior (subtitles
    # were always unconditionally baked in before this field existed).
    # Reuses RenderGraphBuilderService/FilterGraphBuilderService's own
    # include_subtitles relaxation (REQ-00 Stage 1 built it; this is
    # the first caller to expose it as a real per-project choice on
    # the LIVE composite render() path rather than an all-or-nothing
    # Stage 1/Stage 2 split). Takes effect on the NEXT render, not
    # retroactively on an already-rendered video.
    subtitles_enabled: bool = True

    # Caption style manual override, 2026-09-26: real per-project
    # switch on top of the genre's own GenreEditingProfile.
    # subtitle_preset_id - same "None inherits the genre default"
    # resolution-order pattern as letterbox_enabled above. None (the
    # default) means "use whatever the genre auto-selects," matching
    # every job's real behavior before this field existed. When set,
    # must be a real registered subtitle.* preset ID (see
    # EffectRegistryService.list_by_category(EffectCategory.SUBTITLE))
    # - applied to every scene uniformly via ProjectRenderRuntimeFactory.
    # build()'s own overrides_by_scene construction, since
    # GenreEditingProfile.subtitle_preset_id itself is one fixed value
    # per genre, never scene-varying.
    subtitle_style_override_preset_id: str | None = None

    # REQ-4 (opening title card), 2026-09-22: real per-project opt-in
    # - unlike letterboxing above, there is no genre default here, and
    # it defaults OFF. Genre doesn't decide whether to spend real,
    # billed generation cost (a dedicated title-card image AND a
    # dedicated music sting, every enabled render) - that's a per-
    # project decision only the user makes, matching the explicit,
    # opt-in shape of REQ-10(a)'s own "Generate voiceover/music/SFX"
    # buttons rather than REQ-1/2/3's genre-default-with-override
    # shape.
    title_card_enabled: bool = False

    # Manual override for the title card's own title text. None (the
    # default) means "resolve automatically" - the real resolution
    # order (SEOPackage.selected_title if one has been generated for
    # this job, else topic) lives in resolve_title_card_text()
    # (src/services/title_card_text_resolution_service.py), not here,
    # since SEOPackage is stored separately from VideoJob (via the job
    # store, not an embedded field) and this model has no business
    # reaching into that storage itself.
    title_card_text: str | None = None

    # Manual override for the title card's own text block position.
    # None (the default) means CENTER, the design default. Reuses
    # ThumbnailTextPosition (the same concept thumbnails already use)
    # rather than a new title-card-only position type.
    title_card_text_position: ThumbnailTextPosition | None = None

    # Manual override for the title card's own background image -
    # 2026-09-23, added alongside REQ-12's own manual-background-image
    # option for the same real gap. None (the default) means "generate
    # a dedicated AI image" (OpeningTitleCardService's own existing
    # behavior, unchanged) - a real local file path here is used
    # directly instead, skipping image generation entirely.
    title_card_image_path: str | None = None

    # REQ-12 (top10 countdown rank cards), 2026-09-23: set at project
    # creation time (New Project form, only shown for genre.top10) -
    # same "None means auto-generate, a real path means use this
    # instead" shape as title_card_image_path above. One background
    # image is shared across all 10 rank cards by design (guarantees
    # visual consistency across the whole countdown - see
    # voice_profile_differentiation memory's own real-world finding on
    # why 10 independently-generated Flow clips would risk visual
    # drift), so this is a single path, not a per-rank list.
    top10_countdown_background_image_path: str | None = None

    # REQ-12: whether each rank card includes a real "Number {N}."
    # voiceover line, independent of the main render's own voiceover/
    # music/SFX toggles (AudioInclusionPreferences) - those govern the
    # main render's audio; this is a distinct, smaller element (a
    # handful of short generated lines, not the narration track).
    # Defaults on when the countdown feature itself is active
    # (genre_id == "genre.top10" - there is no separate master enable
    # toggle; the format IS the countdown, unlike title_card_enabled's
    # genre-agnostic opt-in).
    top10_countdown_include_numbering_voiceover: bool = True

    # Content-aware sound design (scene-specific SFX cues + a music
    # mood curve, generated from the actual script) - optional. None
    # means the render pipeline falls back to genre-level
    # SoundEffectDirective/MusicDirective behavior unchanged.
    sound_design_plan: SoundDesignPlan | None = None

    final_previews: list[FinalPreview] = Field(default_factory=list)

    # Google Flow External UI Automation, GF-1: the durable, restart-safe
    # attempt ledger. Append-only in spirit, same convention as
    # content_decisions/scene_asset_states above - an attempt advances by
    # replacing its entry in this list (matching id, new state_history),
    # never by deleting anything; a deliberate regeneration always adds a
    # brand-new entry rather than replacing an existing one.
    # GoogleFlowGenerationLedgerService is the only intended writer.
    flow_generation_attempts: list[GoogleFlowGenerationAttempt] = Field(
        default_factory=list
    )

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

    @field_validator("subtitle_style_override_preset_id")
    @classmethod
    def validate_subtitle_style_override_preset_id(
        cls, value: str | None
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip().lower()

        if not normalized.startswith("subtitle."):
            raise ValueError("Caption style override must start " "with 'subtitle.'.")

        if normalized == "subtitle.":
            raise ValueError("Caption style override requires a name.")

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
            # Content Studio Redesign, Phase 19: this check predates
            # ContentIntelligencePipeline.run_scene_planning(), which
            # derives scenes from generated_script (the new pipeline's
            # own script artifact), not the legacy script field
            # ContentPipeline produces - a project that never touches
            # ContentPipeline at all (every new-pipeline project) has
            # scenes with self.script always None by construction, so
            # this validator must accept either provenance rather than
            # only the legacy one. Found via a real round-trip
            # failure: a run_all()-completed job could not be
            # serialized and reloaded through JsonJobStore at all.
            if self.script is None and self.generated_script is None:
                raise ValueError("Scenes cannot exist without a script.")

            if self.script is not None and self.script.status != ScriptStatus.APPROVED:
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

        if self.video_only_render_result is not None and self.video_timeline is None:
            raise ValueError("Video-only render result requires a video timeline.")

        if self.policy_report is not None:
            if self.policy_report.source_mode != self.production_mode:
                raise ValueError(
                    "Policy source_mode must match " "VideoJob production_mode."
                )

        return self
