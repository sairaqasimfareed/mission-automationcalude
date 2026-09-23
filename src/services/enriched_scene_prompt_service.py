from __future__ import annotations

from src.models.cinematic_prompt import ResolvedCinematicPrompt
from src.models.enriched_scene_prompt import EnrichedScenePrompt
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.services.scene_video_generation_service import SceneVideoGenerationService


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
    ) -> None:
        self._scene_video_generation_service = scene_video_generation_service

    def build_entry(
        self,
        *,
        job: VideoJob,
        scene: Scene,
    ) -> EnrichedScenePrompt:
        resolved_prompt = self._resolved_prompt_for(job, scene)

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

        duration_seconds = (
            scene.real_narration_duration_seconds
            if scene.real_narration_duration_seconds is not None
            else float(scene.estimated_duration_seconds)
        )

        return EnrichedScenePrompt(
            scene_number=scene.scene_number,
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
    def _resolved_prompt_for(
        job: VideoJob,
        scene: Scene,
    ) -> ResolvedCinematicPrompt | None:
        if job.cinematic_prompt_package is None:
            return None

        return job.cinematic_prompt_package.prompt_for_scene(scene.scene_number)
