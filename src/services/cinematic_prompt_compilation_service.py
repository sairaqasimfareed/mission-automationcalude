from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from src.models.cinematic_prompt import CinematicPromptPackage, ResolvedCinematicPrompt
from src.models.production_semantic_brief import ProductionSemanticBrief
from src.models.scene import Scene
from src.models.shot_planning import (
    CinematicShotPlan,
    ShotSpecification,
    TemporalActionBeat,
)
from src.models.visual_continuity import VisualContinuityBible


class _ResolvedSceneFields(NamedTuple):
    """
    Everything about one scene's compiled prompt that never varies
    per sub-clip window - identity, environment, lighting,
    composition, lens/camera, and the reveal-safety note. Shared by
    _compile_one() (the single, whole-scene prompt) and
    compile_sub_clip_prompts() (Phase 5: one prompt per real sub-clip
    of a split scene) so both build their prompt text from exactly
    the same resolved fields, differing only in how they describe
    action/duration for their own window.
    """

    shot: ShotSpecification | None
    identities: list[str]
    reference_asset_ids: list[str]
    environment: str
    lighting: str
    composition: str
    lens: str
    camera: str
    reveal_note: str
    action: str


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
    def _resolve_common_fields(
        *,
        scene: Scene,
        shot_plan: CinematicShotPlan,
        visual_continuity_bible: VisualContinuityBible,
        production_semantic_brief: ProductionSemanticBrief | None,
    ) -> _ResolvedSceneFields:
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
        composition = shot.composition if shot is not None else "standard framing"
        lens = shot.lens if shot is not None else "35mm"
        camera = (
            f"{shot.shot_size.value.replace('_', ' ')} shot, "
            f"{shot.shot_angle.value.replace('_', ' ')}, {shot.movement.value} movement"
            if shot is not None
            else "medium shot, eye level, static"
        )
        reveal_note = (
            f" This shot must not reveal information beyond: "
            f"{segment.narrative_intent}."
            if segment is not None and segment.reveal_protected
            else ""
        )
        action = shot.action if shot is not None else scene.narration

        return _ResolvedSceneFields(
            shot=shot,
            identities=identities,
            reference_asset_ids=reference_asset_ids,
            environment=environment,
            lighting=lighting,
            composition=composition,
            lens=lens,
            camera=camera,
            reveal_note=reveal_note,
            action=action,
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
        common = CinematicPromptCompilationService._resolve_common_fields(
            scene=scene,
            shot_plan=shot_plan,
            visual_continuity_bible=visual_continuity_bible,
            production_semantic_brief=production_semantic_brief,
        )

        raw_duration = (
            common.shot.duration_seconds
            if common.shot is not None
            else float(scene.estimated_duration_seconds)
        )
        duration = (
            duration_seconds_resolver(raw_duration)
            if duration_seconds_resolver is not None
            else raw_duration
        )

        action_progression_line = (
            CinematicPromptCompilationService._render_shot_progression(
                common.shot.temporal_action_beats,
                duration,
                raw_duration_seconds=raw_duration,
            )
            if use_shot_by_shot_beats and common.shot is not None
            else None
        )
        action_line = (
            action_progression_line
            if action_progression_line is not None
            else f"Action progression: {common.action}."
        )

        prompt_text = (
            f"Identity: {', '.join(common.identities) or 'no recurring identity present'}. "
            f"Environment: {common.environment}. Lighting: {common.lighting}. "
            f"{action_line} Composition: {common.composition}. "
            f"Lens/camera: {common.lens}, {common.camera}. "
            f"Duration: {duration:.0f} seconds."
            f"{common.reveal_note}"
        )

        return ResolvedCinematicPrompt(
            scene_number=scene.scene_number,
            script_lock_hash=script_lock_hash,
            prompt_text=prompt_text,
            negative_constraints=list(_STANDARD_NEGATIVE_CONSTRAINTS),
            reference_asset_ids=common.reference_asset_ids,
        )

    def compile_sub_clip_prompts(
        self,
        *,
        scene: Scene,
        shot_plan: CinematicShotPlan,
        visual_continuity_bible: VisualContinuityBible,
        production_semantic_brief: ProductionSemanticBrief | None,
        script_lock_hash: str,
        sub_clip_durations: list[float],
    ) -> list[ResolvedCinematicPrompt]:
        """
        Phase 5 (multi-clip scene splitting): one ResolvedCinematicPrompt
        PER SUB-CLIP for a scene whose real narration exceeds one
        clip's max duration (see SceneClipSplitPlanningService) - each
        describing only its own real slice of the scene's shot-
        progression beats, correctly re-based to start at 0 for that
        sub-clip.

        Real-world finding, 2026-09-26: before this method existed,
        both the automated multi-clip submission path and the Prompts
        tab sent every sub-clip of a split scene the identical
        description of the ENTIRE scene (just the trailing duration
        number differed) - a later sub-clip was never actually told to
        show anything different from the first, since there was only
        ever one compiled prompt per scene, describing the whole
        thing. This is the fix: sub_clip_durations is the already-
        decided split plan (SceneClipSplitPlanningService.plan()) -
        this method only renders one prompt per window it's given, it
        does not decide durations itself.

        Continuity for sub-clip 2 onward is handled honestly, not
        fabricated: the real seam-continuity reference (the previous
        sub-clip's own last frame) only exists once that sub-clip has
        actually been generated and downloaded - this method has no
        way to know that file for a purely manual workflow, so it adds
        a plain-text instruction instead of inventing a reference this
        service was never given.
        """

        common = CinematicPromptCompilationService._resolve_common_fields(
            scene=scene,
            shot_plan=shot_plan,
            visual_continuity_bible=visual_continuity_bible,
            production_semantic_brief=production_semantic_brief,
        )

        prompts: list[ResolvedCinematicPrompt] = []
        window_start = 0.0
        total_sub_clips = len(sub_clip_durations)

        for index, sub_duration in enumerate(sub_clip_durations):
            window_end = window_start + sub_duration

            action_progression_line = (
                CinematicPromptCompilationService._render_shot_progression_window(
                    common.shot.temporal_action_beats,
                    window_start_seconds=window_start,
                    window_end_seconds=window_end,
                )
                if common.shot is not None
                else None
            )
            action_line = (
                action_progression_line
                if action_progression_line is not None
                else f"Action progression: {common.action}."
            )

            continuation_note = (
                " This clip continues directly from the previous one - "
                "for visual continuity, use the previous clip's own "
                "last frame as a reference image if your generator "
                "supports it."
                if index > 0
                else ""
            )

            prompt_text = (
                f"Identity: {', '.join(common.identities) or 'no recurring identity present'}. "
                f"Environment: {common.environment}. Lighting: {common.lighting}. "
                f"{action_line} Composition: {common.composition}. "
                f"Lens/camera: {common.lens}, {common.camera}. "
                f"Duration: {sub_duration:.0f} seconds "
                f"(part {index + 1} of {total_sub_clips})."
                f"{common.reveal_note}{continuation_note}"
            )

            prompts.append(
                ResolvedCinematicPrompt(
                    scene_number=scene.scene_number,
                    clip_sequence_index=index,
                    script_lock_hash=script_lock_hash,
                    prompt_text=prompt_text,
                    negative_constraints=list(_STANDARD_NEGATIVE_CONSTRAINTS),
                    reference_asset_ids=common.reference_asset_ids,
                )
            )

            window_start = window_end

        return prompts

    @staticmethod
    def _render_shot_progression(
        beats: list[TemporalActionBeat],
        duration_seconds: float,
        *,
        raw_duration_seconds: float,
    ) -> str | None:
        """
        Renders ShotPlanningService's own per-shot beats as
        "Shot progression: [0-2s] ...; [2-5s] ...", replacing the flat
        "Action progression: ..." line - reuses infrastructure that
        already exists and is already populated, rather than inventing
        a parallel mechanism.

        Returns None (falls back to the flat action line) whenever
        beats can't be rendered at all - no beats (an older/legacy
        shot, or a shot the LLM produced no beats for), or either
        duration is non-positive.

        Real-world finding, 2026-09-26: beats whose start_offset_seconds
        fell at or past duration_seconds used to be filtered out
        entirely here, not shortened - silently dropping whatever real
        narrative content those beats alone carried whenever
        duration_seconds_resolver (above) clamped a scene down (e.g.
        Google Flow's verified duration cap). Confirmed live: a 13s
        shot planned across six beats (one per icon in an infographic
        sequence) compiled down to a prompt describing only the first
        four once clamped to Flow's 8s cap - the last two icons were
        never mentioned anywhere in the compiled text a person would
        copy for manual generation, nor in what the real Flow
        submission itself sends.

        Fixed by rescaling every beat's timing proportionally to
        duration_seconds instead of dropping the tail - every beat's
        real content always survives compilation, described as
        happening faster/more compressed than ShotPlanningService
        originally planned, never dropped outright. `raw_duration_seconds`
        is the shot's own un-clamped planned duration (what the beats'
        own offsets are timed against); when duration_seconds hasn't
        actually been clamped down from it (the common case), the
        scale factor is exactly 1.0 and every beat renders at its
        original timing, identical to before this fix.
        """

        if not beats:
            return None

        if raw_duration_seconds <= 0 or duration_seconds <= 0:
            return None

        # Only ever compress, never stretch beyond what was actually
        # planned - a duration_seconds_resolver that (unusually) grows
        # the duration instead of clamping it must not be read as
        # license to slow every beat down to fill the extra time.
        scale = min(duration_seconds / raw_duration_seconds, 1.0)

        usable = sorted(beats, key=lambda beat: beat.start_offset_seconds)

        rendered = [
            f"[{beat.start_offset_seconds * scale:g}-"
            f"{beat.end_offset_seconds * scale:g}s] {beat.description}"
            for beat in usable
        ]

        return f"Shot progression: {'; '.join(rendered)}."

    @staticmethod
    def _render_shot_progression_window(
        beats: list[TemporalActionBeat],
        *,
        window_start_seconds: float,
        window_end_seconds: float,
    ) -> str | None:
        """
        Renders only the portion of `beats` that overlaps
        [window_start_seconds, window_end_seconds), re-based so the
        window's own start reads as 0 - the building block
        compile_sub_clip_prompts() uses so each sub-clip's prompt
        describes exactly its own slice of the scene's real content,
        never the whole scene again and never nothing at all.

        A beat that only partially overlaps the window is trimmed to
        the window's own edges, not dropped or rendered past it -
        the same "never contradict this clip's own real duration"
        discipline _render_shot_progression enforces for the whole-
        scene case.

        Returns None when no beat overlaps the window at all (a real
        gap in the shot plan for this stretch) or the window itself is
        empty/inverted - falls back to the flat action line, the same
        safe default _render_shot_progression uses.
        """

        if not beats or window_end_seconds <= window_start_seconds:
            return None

        overlapping = [
            beat
            for beat in sorted(beats, key=lambda beat: beat.start_offset_seconds)
            if beat.start_offset_seconds < window_end_seconds
            and beat.end_offset_seconds > window_start_seconds
        ]

        if not overlapping:
            return None

        rendered = [
            f"[{max(beat.start_offset_seconds, window_start_seconds) - window_start_seconds:g}-"
            f"{min(beat.end_offset_seconds, window_end_seconds) - window_start_seconds:g}s] "
            f"{beat.description}"
            for beat in overlapping
        ]

        return f"Shot progression: {'; '.join(rendered)}."
