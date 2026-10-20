from __future__ import annotations

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.genre_timeline_pipeline import (
    GenreTimelinePipelineResult,
    GenreTimelinePipelineStatus,
)
from src.models.resolved_editing_blueprint import (
    ResolvedAnimationInstruction,
    ResolvedSceneEditingBlueprint,
    ResolvedVisualEffectInstruction,
)
from src.models.scene import Scene
from src.models.timeline_validation import (
    TimelineValidationResult,
)
from src.models.video_clip import VideoClip
from src.models.video_timeline import VideoTimeline
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.timeline_builder_service import (
    TimelineBuilderService,
)
from src.services.timeline_directive_service import (
    TimelineDirectiveService,
)
from src.services.timeline_validation_service import (
    TimelineValidationService,
)


class GenreTimelinePipelineService:
    """
    Orchestrate the complete genre-aware editing timeline flow.

    Flow:

    Scenes and clips
    -> genre directive generation
    -> directive validation and resolution
    -> timeline construction
    -> blueprint attachment
    -> strict render-readiness validation
    """

    def __init__(
        self,
        *,
        genre_directive_service: GenreDirectiveGenerationService,
        directive_resolution_service: EditingDirectiveResolutionService,
        timeline_builder_service: TimelineBuilderService | None = None,
        timeline_directive_service: TimelineDirectiveService | None = None,
        timeline_validation_service: TimelineValidationService | None = None,
    ) -> None:
        self.genre_directive_service = genre_directive_service

        self.directive_resolution_service = directive_resolution_service

        self.timeline_builder_service = (
            timeline_builder_service or TimelineBuilderService()
        )

        self.timeline_directive_service = (
            timeline_directive_service or TimelineDirectiveService()
        )

        self.timeline_validation_service = (
            timeline_validation_service or TimelineValidationService()
        )

    def build(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
        genre_id: str,
        overrides_by_scene: (
            dict[
                int,
                SceneEditingDirectives,
            ]
            | None
        ) = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> GenreTimelinePipelineResult:
        """Build one complete genre-aware editing timeline."""

        normalized_genre_id = genre_id.strip().lower()

        if not normalized_genre_id:
            raise ValueError("Genre timeline pipeline requires " "a genre ID.")

        self._validate_inputs(
            scenes=scenes,
            clips=clips,
        )

        ordered_scenes = sorted(
            scenes,
            key=lambda scene: scene.scene_number,
        )

        directives = self.genre_directive_service.generate_many(
            scenes=ordered_scenes,
            genre_id=normalized_genre_id,
            overrides_by_scene=(overrides_by_scene),
        )

        scene_by_number = {scene.scene_number: scene for scene in ordered_scenes}

        blueprints: list[ResolvedSceneEditingBlueprint] = []

        for directive in directives:
            scene = scene_by_number[directive.scene_number]

            blueprint = self.directive_resolution_service.resolve(
                directive,
                scene_duration_seconds=float(scene.estimated_duration_seconds),
            )

            blueprints.append(blueprint)

        timeline = self.timeline_builder_service.build(
            clips,
            output_resolution=(output_resolution),
            frame_rate=frame_rate,
        )

        self.timeline_directive_service.attach_many(
            timeline,
            blueprints=blueprints,
            require_all_timeline_scenes=True,
        )

        self._fit_effects_to_clips(timeline)

        validation = self.timeline_validation_service.validate(
            timeline,
            require_editing_blueprints=True,
            warn_on_blueprint_fallbacks=(warn_on_blueprint_fallbacks),
        )

        warnings = self._collect_warnings(
            directives=directives,
            blueprints=blueprints,
            validation=validation,
        )

        status = self._determine_status(
            validation_is_valid=(validation.is_valid),
            all_items_render_ready=(validation.all_enabled_items_render_ready),
            warnings=warnings,
        )

        return GenreTimelinePipelineResult(
            requested_genre_id=(normalized_genre_id),
            status=status,
            timeline=timeline,
            directives=directives,
            blueprints=blueprints,
            validation=validation,
            warnings=warnings,
            metadata={
                "scene_count": len(scenes),
                "clip_count": len(clips),
                "directive_count": (len(directives)),
                "blueprint_count": (len(blueprints)),
                "output_resolution": (output_resolution),
                "frame_rate": frame_rate,
                "timeline_duration_seconds": (timeline.total_duration_seconds),
                "effect_fallback_count": sum(
                    blueprint.fallback_count for blueprint in blueprints
                ),
                "render_ready_item_count": (validation.render_ready_item_count),
                "validation_issue_count": (validation.issue_count),
            },
        )

    @staticmethod
    def _fit_effects_to_clips(timeline: VideoTimeline) -> None:
        """Nothing may be timed longer than its own clip. A scene's effects, camera move and animation
        are timed from the scene's word-count estimate, but a clip can be shorter (a regenerated clip, a
        stock clip) and the second part of a split scene shares the first part's blueprint: the render
        rejects an animation longer than its clip ("Animation execution extends beyond scene
        duration", seen live 2026-10-20). An item that needs it gets its own copy, cut to fit.
        """

        for item in timeline.items:
            blueprint = item.editing_blueprint

            if blueprint is None:
                continue

            limit = float(item.duration_seconds)
            fitted = blueprint.model_copy(deep=True)
            changed = False

            timed: list[
                ResolvedAnimationInstruction | ResolvedVisualEffectInstruction
            ] = [
                *fitted.animations,
                *fitted.visual_effects,
            ]

            for instruction in timed:
                if instruction.duration_seconds is None:
                    continue

                end = instruction.start_offset_seconds + instruction.duration_seconds

                if end > limit and instruction.start_offset_seconds < limit:
                    instruction.duration_seconds = (
                        limit - instruction.start_offset_seconds
                    )
                    changed = True

            camera = fitted.camera

            if (
                camera.end_offset_seconds is not None
                and camera.end_offset_seconds > limit
            ):
                camera.end_offset_seconds = limit
                changed = True

            if changed:
                item.editing_blueprint = fitted

    def _validate_inputs(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
    ) -> None:
        """Validate scene and clip collections."""

        if not scenes:
            raise ValueError("Genre timeline pipeline requires " "at least one scene.")

        if not clips:
            raise ValueError(
                "Genre timeline pipeline requires " "at least one video clip."
            )

        scene_numbers = [scene.scene_number for scene in scenes]

        clip_scene_numbers = [clip.scene_number for clip in clips]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError("Genre timeline scenes must use " "unique scene numbers.")

        # A scene longer than one clip is several clips with the same scene number, told apart by
        # clip_sequence_index (multi-clip scenes): only the pair has to be unique.
        clip_identities = [
            (clip.scene_number, clip.clip_sequence_index) for clip in clips
        ]

        if len(clip_identities) != len(set(clip_identities)):
            raise ValueError(
                "Genre timeline clips must use unique scene numbers (and clip positions "
                "within a scene)."
            )

        scene_number_set = set(scene_numbers)

        clip_scene_number_set = set(clip_scene_numbers)

        missing_clip_scenes = scene_number_set - clip_scene_number_set

        extra_clip_scenes = clip_scene_number_set - scene_number_set

        if missing_clip_scenes:
            missing_text = ", ".join(
                str(scene_number) for scene_number in sorted(missing_clip_scenes)
            )

            raise ValueError("Video clips are missing for " f"scenes: {missing_text}")

        if extra_clip_scenes:
            extra_text = ", ".join(
                str(scene_number) for scene_number in sorted(extra_clip_scenes)
            )

            raise ValueError("Video clips reference unknown " f"scenes: {extra_text}")

        # A clip's real duration is deliberately allowed to diverge from
        # the scene's planned estimate - SceneAssetVideoClipBuilderService
        # (2026-09-14) intentionally sizes every clip from its acquired
        # asset's own real, probed duration rather than the scene's
        # word-count-based plan, precisely because stock/manual footage
        # is never that precise and TimelineBuilderService already sizes
        # each timeline slot from the clip's real duration, not the
        # scene's estimate. A hard equality check here (previously
        # TIME_TOLERANCE_SECONDS = 0.001) predates that fix and blocked
        # every real-world stock/manual scene whose asset wasn't an
        # exact-second match - found live via a resumed render.
        # DurationMismatchPolicyService is this codebase's real,
        # designed-for-purpose tool for flagging a severe mismatch;
        # this validator's job is limited to scene/clip identity, not
        # duration.

    @staticmethod
    def _collect_warnings(
        *,
        directives: list[SceneEditingDirectives],
        blueprints: list[ResolvedSceneEditingBlueprint],
        validation: TimelineValidationResult,
    ) -> list[str]:
        """Collect unique warnings from all pipeline stages."""

        warnings: list[str] = []

        for directive in directives:
            for warning in directive.warnings:
                if warning not in warnings:
                    warnings.append(warning)

        for blueprint in blueprints:
            for warning in blueprint.warnings:
                if warning not in warnings:
                    warnings.append(warning)

        for issue in validation.warnings:
            if issue.message not in warnings:
                warnings.append(issue.message)

        return warnings

    @staticmethod
    def _determine_status(
        *,
        validation_is_valid: bool,
        all_items_render_ready: bool,
        warnings: list[str],
    ) -> GenreTimelinePipelineStatus:
        """Determine final pipeline status."""

        if not validation_is_valid or not all_items_render_ready:
            return GenreTimelinePipelineStatus.FAILED

        if warnings:
            return GenreTimelinePipelineStatus.COMPLETED_WITH_WARNINGS

        return GenreTimelinePipelineStatus.COMPLETED
