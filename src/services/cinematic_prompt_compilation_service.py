from __future__ import annotations

from collections.abc import Callable

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.production_semantic_brief import ProductionSemanticBrief
from src.models.scene import Scene
from src.models.shot_planning import CinematicShotPlan, TemporalActionBeat
from src.models.visual_continuity import VisualContinuityBible

_STANDARD_NEGATIVE_CONSTRAINTS = (
    "no on-screen text, logos, or watermarks",
    "no identity drift from the described person/location",
    "no unrelated subjects or events",
    "no continuity discontinuities with the stated incoming state",
)

# Real-world finding pending, 2026-09-14: ShotPlanningService already
# generates per-shot TemporalActionBeat timecodes (e.g. "0-2s establish,
# 2-5s action, 5-8s reveal") but nothing ever rendered them into the
# compiled prompt text sent to Google Flow - only the shot's single
# flat `action` string was used. Whether Veo actually respects precise
# sub-second timecodes inside one short clip, rather than treating them
# as inert text, has not yet been verified against a real generation.
# This flag is the single switch to flip back to the flat `action` line
# for every shot once that's tested - no code restructuring needed,
# same "one manually-flipped constant" discipline as
# ScenePlannerAgent's own _MAXIMUM_SCENE_DURATION_SECONDS.
_USE_SHOT_BY_SHOT_BEATS = True


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
        duration_seconds_resolver: Callable[[float], float] | None = None,
        use_shot_by_shot_beats: bool = _USE_SHOT_BY_SHOT_BEATS,
    ) -> CinematicPromptPackage:
        """
        duration_seconds_resolver, when given, overrides the shot
        plan's own raw duration with whatever a specific provider will
        actually honor (e.g. Google Flow's clamp to its own fixed
        4/6/8s set) - kept as an injected function rather than this
        service importing any provider-specific constant itself, so it
        stays provider-agnostic (matching ScenePlannerAgent's own
        "browser selectors must never become the application's
        business logic" discipline) while still guaranteeing the
        compiled "Duration: Ns" text matches what a caller who DOES
        know the target provider will actually request.
        """

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
                duration_seconds_resolver=duration_seconds_resolver,
                use_shot_by_shot_beats=use_shot_by_shot_beats,
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
        duration_seconds_resolver: Callable[[float], float] | None = None,
        use_shot_by_shot_beats: bool = _USE_SHOT_BY_SHOT_BEATS,
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
        raw_duration = (
            shot.duration_seconds
            if shot is not None
            else float(scene.estimated_duration_seconds)
        )
        duration = (
            duration_seconds_resolver(raw_duration)
            if duration_seconds_resolver is not None
            else raw_duration
        )
        reveal_note = (
            f" This shot must not reveal information beyond: "
            f"{segment.narrative_intent}."
            if segment is not None and segment.reveal_protected
            else ""
        )

        action_progression_line = (
            CinematicPromptCompilationService._render_shot_progression(
                shot.temporal_action_beats, duration
            )
            if use_shot_by_shot_beats and shot is not None
            else None
        )
        action_line = (
            action_progression_line
            if action_progression_line is not None
            else f"Action progression: {action}."
        )

        prompt_text = (
            f"Identity: {', '.join(identities) or 'no recurring identity present'}. "
            f"Environment: {environment}. Lighting: {lighting}. "
            f"{action_line} Composition: {composition}. "
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

    @staticmethod
    def _render_shot_progression(
        beats: list[TemporalActionBeat], duration_seconds: float
    ) -> str | None:
        """
        Renders ShotPlanningService's own per-shot beats as
        "Shot progression: [0-2s] ...; [2-5s] ...", replacing the flat
        "Action progression: ..." line - reuses infrastructure that
        already exists and is already populated, rather than inventing
        a parallel mechanism.

        Returns None (falls back to the flat action line) whenever
        beats can't be rendered without contradicting the shot's own
        final duration - continuity must never be violated: a beat
        describing action past the clip's real end would tell Veo to
        continue past a duration this shot will never actually run
        for, the same class of self-contradiction the duration-text
        mismatch fix above exists to prevent. Also falls back on no
        beats at all (an older/legacy shot, or a shot the LLM produced
        no beats for) - the flat action line is always a safe,
        already-proven prompt shape.
        """

        if not beats:
            return None

        usable = [
            beat
            for beat in sorted(beats, key=lambda beat: beat.start_offset_seconds)
            if beat.start_offset_seconds < duration_seconds
        ]

        if not usable:
            return None

        rendered = [
            f"[{beat.start_offset_seconds:g}-"
            f"{min(beat.end_offset_seconds, duration_seconds):g}s] {beat.description}"
            for beat in usable
        ]

        return f"Shot progression: {'; '.join(rendered)}."
