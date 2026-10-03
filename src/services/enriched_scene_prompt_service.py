from __future__ import annotations

from collections.abc import Callable

from src.models.cinematic_prompt import ResolvedCinematicPrompt
from src.models.enriched_scene_prompt import EnrichedScenePrompt
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.providers.google_flow.locators import VERIFIED_DURATIONS_SECONDS
from src.services.narration_duration_sync_service import (
    sync_real_narration_durations,
)
from src.services.scene_video_generation_service import SceneVideoGenerationService
from src.services.video_provider_rules import (
    VideoProviderRules,
    resolve_scene_video_provider,
    rules_for,
)


class EnrichedScenePromptService:
    """
    REQ-9 (full compiled prompt screen): assemble every real piece of
    a scene's generation instruction for a human to read/copy -
    negative constraints, transitions, full continuity state, resolved
    reference assets, execution settings, and quality scores, none of
    which make it into `ResolvedCinematicPrompt.prompt_text` today.

    Read-only and display-only - never mutates `prompt_text` or any
    other field the real automated generation path
    (SceneVideoGenerationService._submit()) actually reads. Reuses
    that same service's own reference-asset resolution and model-
    family resolution directly (cross-class "private" method reuse,
    the established precedent in this codebase - e.g.
    RenderGraphBuilderService._audio_node() from AudioMuxRenderService)
    rather than a second, parallel implementation that could drift
    from what a real submission would actually send.
    """

    def __init__(
        self,
        *,
        scene_video_generation_service: SceneVideoGenerationService | None = None,
        provider_name_for_profile: Callable[[str], str | None] | None = None,
    ) -> None:
        self._scene_video_generation_service = scene_video_generation_service
        # Maps an account profile id to its provider name, so a scene
        # pinned to a specific account is previewed with THAT provider's
        # rules. Without it, only the project's own provider is known.
        self._provider_name_for_profile = provider_name_for_profile

    def provider_for(self, job: VideoJob, scene: Scene) -> VideoProvider:
        """Which provider will generate this scene - the same resolution
        the generation dispatcher uses."""

        return resolve_scene_video_provider(job, scene, self._provider_name_for_profile)

    def build_entry(
        self,
        *,
        job: VideoJob,
        scene: Scene,
    ) -> EnrichedScenePrompt:
        sync_real_narration_durations(job)
        resolved_prompt = self._resolved_prompt_for(job, scene)
        rules = rules_for(self.provider_for(job, scene))

        return self._entry(
            job=job,
            scene=scene,
            resolved_prompt=resolved_prompt,
            duration_seconds=rules.single_clip_seconds(self._duration_seconds(scene)),
            rules=rules,
        )

    def build_entries(
        self,
        *,
        job: VideoJob,
        scene: Scene,
    ) -> list[EnrichedScenePrompt]:
        """
        Phase 5 (multi-clip scene splitting) counterpart to
        build_entry(): a scene whose real narration exceeds Google
        Flow's max single-clip duration compiles to several
        sub-clip-specific prompts (see
        CinematicPromptCompilationService.compile_sub_clip_prompts())
        rather than one whole-scene prompt that silently loses
        whatever narration falls past the clamp - this is the Prompts
        tab's window onto that same split-aware compilation the
        automated submission path
        (SceneVideoGenerationService._resolve_sub_clip_prompts())
        already uses, reused here rather than re-implemented so the
        two paths can never drift apart.

        A scene that does not need splitting returns a single-element
        list (build_entry()'s own result) - the exact behavior every
        scene had before Phase 5 existed.
        """

        sync_real_narration_durations(job)
        duration_seconds = self._duration_seconds(scene)
        rules = rules_for(self.provider_for(job, scene))

        if not rules.needs_split(duration_seconds):
            return [self.build_entry(job=job, scene=scene)]

        if self._scene_video_generation_service is None:
            return [self.build_entry(job=job, scene=scene)]

        sub_clip_durations = rules.plan_clips(duration_seconds)

        resolved_prompts = (
            self._scene_video_generation_service._resolve_sub_clip_prompts(
                job, scene, sub_clip_durations
            )
        )

        if resolved_prompts is None:
            return [self.build_entry(job=job, scene=scene)]

        return [
            self._entry(
                job=job,
                scene=scene,
                resolved_prompt=resolved_prompt,
                duration_seconds=sub_clip_durations[
                    resolved_prompt.clip_sequence_index
                ],
                rules=rules,
                # Every sub-clip after the first is submitted with the
                # previous clip's last frame as a reference image.
                has_seam_reference=resolved_prompt.clip_sequence_index > 0,
            )
            for resolved_prompt in resolved_prompts
        ]

    def _entry(
        self,
        *,
        job: VideoJob,
        scene: Scene,
        resolved_prompt: ResolvedCinematicPrompt | None,
        duration_seconds: float,
        rules: VideoProviderRules,
        has_seam_reference: bool = False,
    ) -> EnrichedScenePrompt:
        base_prompt_text = (
            resolved_prompt.prompt_text
            if resolved_prompt is not None
            else scene.visual_prompt
        )

        shot = (
            job.cinematic_shot_plan.shot_for_scene(scene.scene_number)
            if job.cinematic_shot_plan is not None
            else None
        )

        continuity = (
            job.visual_continuity_bible.entry_for_scene(scene.scene_number)
            if job.visual_continuity_bible is not None
            else None
        )

        reference_assets = (
            self._scene_video_generation_service._resolve_reference_assets(job, scene)
            if self._scene_video_generation_service is not None
            else []
        )

        model_family = (
            self._scene_video_generation_service._configured_model_family()
            if self._scene_video_generation_service is not None
            else None
        )

        # Google Flow silently refuses image ingredients on a clip shorter
        # than its longest one, so any clip submitted with a reference
        # (an identity's reference frame, or the previous sub-clip's last
        # frame) is always requested at that maximum - mirrors
        # SceneVideoGenerationService._submit(). Muse has no duration
        # control, so nothing is forced there.
        if rules.provider == VideoProvider.GOOGLE_FLOW and (
            reference_assets or has_seam_reference
        ):
            duration_seconds = float(max(VERIFIED_DURATIONS_SECONDS))

        # Worded exactly as a submission would send it (stated duration,
        # last shot beat, and - for Muse - the trim instruction).
        base_prompt_text = rules.finalize_prompt(base_prompt_text, duration_seconds)

        return EnrichedScenePrompt(
            scene_number=scene.scene_number,
            clip_sequence_index=(
                resolved_prompt.clip_sequence_index
                if resolved_prompt is not None
                else 0
            ),
            base_prompt_text=base_prompt_text,
            negative_constraints=(
                list(resolved_prompt.negative_constraints)
                if resolved_prompt is not None
                else []
            ),
            transition_in=shot.transition_in if shot is not None else None,
            transition_out=shot.transition_out if shot is not None else None,
            continuity_incoming=(
                continuity.incoming_state if continuity is not None else None
            ),
            continuity_outgoing=(
                continuity.outgoing_state if continuity is not None else None
            ),
            reference_assets=reference_assets,
            execution_provider_label=rules.summary,
            execution_model_family=model_family,
            execution_duration_seconds=duration_seconds,
            # aspect_ratio/resolution are genuinely unset anywhere ahead
            # of a real submission today (confirmed via code:
            # SceneVideoGenerationService._submit() never sets either) -
            # left None rather than fabricated, so this screen never
            # shows a value the real pipeline doesn't actually honor.
            execution_aspect_ratio=None,
            execution_resolution=None,
            specificity_score=(
                resolved_prompt.specificity_score
                if resolved_prompt is not None
                else None
            ),
            continuity_score=(
                resolved_prompt.continuity_score
                if resolved_prompt is not None
                else None
            ),
            action_score=(
                resolved_prompt.action_score if resolved_prompt is not None else None
            ),
            camera_score=(
                resolved_prompt.camera_score if resolved_prompt is not None else None
            ),
            lighting_score=(
                resolved_prompt.lighting_score if resolved_prompt is not None else None
            ),
            reveal_safety_score=(
                resolved_prompt.reveal_safety_score
                if resolved_prompt is not None
                else None
            ),
            is_blocked=(
                resolved_prompt.is_blocked if resolved_prompt is not None else None
            ),
        )

    @staticmethod
    def _duration_seconds(scene: Scene) -> float:
        return (
            scene.real_narration_duration_seconds
            if scene.real_narration_duration_seconds is not None
            else float(scene.estimated_duration_seconds)
        )

    @staticmethod
    def _resolved_prompt_for(
        job: VideoJob,
        scene: Scene,
    ) -> ResolvedCinematicPrompt | None:
        if job.cinematic_prompt_package is None:
            return None

        return job.cinematic_prompt_package.prompt_for_scene(scene.scene_number)
