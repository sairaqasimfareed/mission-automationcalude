from __future__ import annotations

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.production_semantic_brief import ProductionSemanticBrief
from src.models.scene import Scene
from src.models.shot_planning import CinematicShotPlan
from src.models.visual_continuity import VisualContinuityBible

_STANDARD_NEGATIVE_CONSTRAINTS = (
    "no on-screen text, logos, or watermarks",
    "no identity drift from the described person/location",
    "no unrelated subjects or events",
    "no continuity discontinuities with the stated incoming state",
)


class CinematicPromptCompilationService:
    """
    Post-Script-Approval Production Plan, Phase 4: "Compile shot,
    continuity and semantic intent into the exact provider-facing
    cinematic instruction."

    Deliberately pure/deterministic - every input already exists as
    already-resolved structured data (ShotSpecification,
    ClipContinuityEntry, ProductionSemanticSegment); compiling a
    prompt from it is templated assembly, not a creative decision, so
    no LLM call is needed here. Scoring the *result* for quality is a
    separate, genuinely evaluative pass - see
    CinematicPromptQualityService - matching this engine's "writing
    and evaluation are separate passes" discipline throughout.
    """

    def compile(
        self,
        *,
        scenes: list[Scene],
        shot_plan: CinematicShotPlan,
        visual_continuity_bible: VisualContinuityBible,
        production_semantic_brief: ProductionSemanticBrief | None,
        script_lock_hash: str,
    ) -> CinematicPromptPackage:
        if not scenes:
            raise ValueError(
                "Cinematic prompt compilation requires at least one scene."
            )

        prompts = [
            self._compile_one(
                scene=scene,
                shot_plan=shot_plan,
                visual_continuity_bible=visual_continuity_bible,
                production_semantic_brief=production_semantic_brief,
                script_lock_hash=script_lock_hash,
            )
            for scene in sorted(scenes, key=lambda s: s.scene_number)
        ]

        return CinematicPromptPackage(
            script_lock_hash=script_lock_hash, prompts=prompts
        )

    @staticmethod
    def _compile_one(
        *,
        scene: Scene,
        shot_plan: CinematicShotPlan,
        visual_continuity_bible: VisualContinuityBible,
        production_semantic_brief: ProductionSemanticBrief | None,
        script_lock_hash: str,
    ) -> ResolvedCinematicPrompt:
        shot = shot_plan.shot_for_scene(scene.scene_number)
        continuity = visual_continuity_bible.entry_for_scene(scene.scene_number)

        segment = None
        if production_semantic_brief is not None:
            for candidate in production_semantic_brief.segments:
                if candidate.segment_number == scene.scene_number:
                    segment = candidate
                    break

        identity_names = continuity.entity_names if continuity is not None else []
        identities = [
            identity.canonical_description
            for identity in visual_continuity_bible.identities
            if identity.name in identity_names
        ]
        reference_asset_ids = [
            asset_id
            for identity in visual_continuity_bible.identities
            if identity.name in identity_names
            for asset_id in identity.reference_asset_ids
        ]

        environment = (
            continuity.outgoing_state.location
            if continuity is not None
            else "unspecified"
        )
        lighting = (
            continuity.outgoing_state.lighting
            if continuity is not None
            else "unspecified"
        )
        action = shot.action if shot is not None else scene.narration
        composition = shot.composition if shot is not None else "standard framing"
        lens = shot.lens if shot is not None else "35mm"
        camera = (
            f"{shot.shot_size.value.replace('_', ' ')} shot, "
            f"{shot.shot_angle.value.replace('_', ' ')}, {shot.movement.value} movement"
            if shot is not None
            else "medium shot, eye level, static"
        )
        duration = (
            shot.duration_seconds
            if shot is not None
            else float(scene.estimated_duration_seconds)
        )
        reveal_note = (
            f" This shot must not reveal information beyond: "
            f"{segment.narrative_intent}."
            if segment is not None and segment.reveal_protected
            else ""
        )

        prompt_text = (
            f"Identity: {', '.join(identities) or 'no recurring identity present'}. "
            f"Environment: {environment}. Lighting: {lighting}. "
            f"Action progression: {action}. Composition: {composition}. "
            f"Lens/camera: {lens}, {camera}. Duration: {duration:.0f} seconds."
            f"{reveal_note}"
        )

        return ResolvedCinematicPrompt(
            scene_number=scene.scene_number,
            script_lock_hash=script_lock_hash,
            prompt_text=prompt_text,
            negative_constraints=list(_STANDARD_NEGATIVE_CONSTRAINTS),
            reference_asset_ids=reference_asset_ids,
        )
