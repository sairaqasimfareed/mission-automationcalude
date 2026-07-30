from __future__ import annotations

from src.models.editing_directives import (
    SceneEditingDirectives,
)
from src.models.genre_timeline_pipeline import (
    GenreTimelinePipelineResult,
    GenreTimelinePipelineStatus,
)
from src.models.resolved_editing_blueprint import (
    ResolvedSceneEditingBlueprint,
)
from src.models.scene import Scene
from src.models.timeline_validation import (
    TimelineValidationResult,
)
from src.models.video_clip import VideoClip
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

    TIME_TOLERANCE_SECONDS = 0.001

    def __init__(
        self,
        *,
        genre_directive_service: (
            GenreDirectiveGenerationService
        ),
        directive_resolution_service: (
            EditingDirectiveResolutionService
        ),
        timeline_builder_service: (
            TimelineBuilderService | None
        ) = None,
        timeline_directive_service: (
            TimelineDirectiveService | None
        ) = None,
        timeline_validation_service: (
            TimelineValidationService | None
        ) = None,
    ) -> None:
        self.genre_directive_service = (
            genre_directive_service
        )

        self.directive_resolution_service = (
            directive_resolution_service
        )

        self.timeline_builder_service = (
            timeline_builder_service
            or TimelineBuilderService()
        )

        self.timeline_directive_service = (
            timeline_directive_service
            or TimelineDirectiveService()
        )

        self.timeline_validation_service = (
            timeline_validation_service
            or TimelineValidationService()
        )

    def build(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
        genre_id: str,
        overrides_by_scene: dict[
            int,
            SceneEditingDirectives,
        ]
        | None = None,
        output_resolution: str = "1920x1080",
        frame_rate: int = 30,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> GenreTimelinePipelineResult:
        """Build one complete genre-aware editing timeline."""

        normalized_genre_id = (
            genre_id.strip().lower()
        )

        if not normalized_genre_id:
            raise ValueError(
                "Genre timeline pipeline requires "
                "a genre ID."
            )

        self._validate_inputs(
            scenes=scenes,
            clips=clips,
        )

        ordered_scenes = sorted(
            scenes,
            key=lambda scene: scene.scene_number,
        )

        directives = (
            self.genre_directive_service
            .generate_many(
                scenes=ordered_scenes,
                genre_id=normalized_genre_id,
                overrides_by_scene=(
                    overrides_by_scene
                ),
            )
        )

        scene_by_number = {
            scene.scene_number: scene
            for scene in ordered_scenes
        }

        blueprints: list[
            ResolvedSceneEditingBlueprint
        ] = []

        for directive in directives:
            scene = scene_by_number[
                directive.scene_number
            ]

            blueprint = (
                self.directive_resolution_service
                .resolve(
                    directive,
                    scene_duration_seconds=float(
                        scene
                        .estimated_duration_seconds
                    ),
                )
            )

            blueprints.append(
                blueprint
            )

        timeline = (
            self.timeline_builder_service.build(
                clips,
                output_resolution=(
                    output_resolution
                ),
                frame_rate=frame_rate,
            )
        )

        self.timeline_directive_service.attach_many(
            timeline,
            blueprints=blueprints,
            require_all_timeline_scenes=True,
        )

        validation = (
            self.timeline_validation_service
            .validate(
                timeline,
                require_editing_blueprints=True,
                warn_on_blueprint_fallbacks=(
                    warn_on_blueprint_fallbacks
                ),
            )
        )

        warnings = self._collect_warnings(
            directives=directives,
            blueprints=blueprints,
            validation=validation,
        )

        status = self._determine_status(
            validation_is_valid=(
                validation.is_valid
            ),
            all_items_render_ready=(
                validation
                .all_enabled_items_render_ready
            ),
            warnings=warnings,
        )

        return GenreTimelinePipelineResult(
            requested_genre_id=(
                normalized_genre_id
            ),
            status=status,
            timeline=timeline,
            directives=directives,
            blueprints=blueprints,
            validation=validation,
            warnings=warnings,
            metadata={
                "scene_count": len(scenes),
                "clip_count": len(clips),
                "directive_count": (
                    len(directives)
                ),
                "blueprint_count": (
                    len(blueprints)
                ),
                "output_resolution": (
                    output_resolution
                ),
                "frame_rate": frame_rate,
                "timeline_duration_seconds": (
                    timeline
                    .total_duration_seconds
                ),
                "effect_fallback_count": sum(
                    blueprint.fallback_count
                    for blueprint in blueprints
                ),
                "render_ready_item_count": (
                    validation
                    .render_ready_item_count
                ),
                "validation_issue_count": (
                    validation.issue_count
                ),
            },
        )

    def _validate_inputs(
        self,
        *,
        scenes: list[Scene],
        clips: list[VideoClip],
    ) -> None:
        """Validate scene and clip collections."""

        if not scenes:
            raise ValueError(
                "Genre timeline pipeline requires "
                "at least one scene."
            )

        if not clips:
            raise ValueError(
                "Genre timeline pipeline requires "
                "at least one video clip."
            )

        scene_numbers = [
            scene.scene_number
            for scene in scenes
        ]

        clip_scene_numbers = [
            clip.scene_number
            for clip in clips
        ]

        if len(scene_numbers) != len(
            set(scene_numbers)
        ):
            raise ValueError(
                "Genre timeline scenes must use "
                "unique scene numbers."
            )

        if len(clip_scene_numbers) != len(
            set(clip_scene_numbers)
        ):
            raise ValueError(
                "Genre timeline clips must use "
                "unique scene numbers."
            )

        scene_number_set = set(
            scene_numbers
        )

        clip_scene_number_set = set(
            clip_scene_numbers
        )

        missing_clip_scenes = (
            scene_number_set
            - clip_scene_number_set
        )

        extra_clip_scenes = (
            clip_scene_number_set
            - scene_number_set
        )

        if missing_clip_scenes:
            missing_text = ", ".join(
                str(scene_number)
                for scene_number in sorted(
                    missing_clip_scenes
                )
            )

            raise ValueError(
                "Video clips are missing for "
                f"scenes: {missing_text}"
            )

        if extra_clip_scenes:
            extra_text = ", ".join(
                str(scene_number)
                for scene_number in sorted(
                    extra_clip_scenes
                )
            )

            raise ValueError(
                "Video clips reference unknown "
                f"scenes: {extra_text}"
            )

        scene_duration_by_number = {
            scene.scene_number: float(
                scene.estimated_duration_seconds
            )
            for scene in scenes
        }

        for clip in clips:
            expected_duration = (
                scene_duration_by_number[
                    clip.scene_number
                ]
            )

            actual_duration = float(
                clip.duration_seconds
            )

            if (
                abs(
                    expected_duration
                    - actual_duration
                )
                > self.TIME_TOLERANCE_SECONDS
            ):
                raise ValueError(
                    "Scene and clip durations must "
                    "match before timeline generation. "
                    f"Scene {clip.scene_number}: "
                    f"scene={expected_duration}, "
                    f"clip={actual_duration}."
                )

    @staticmethod
    def _collect_warnings(
        *,
        directives: list[
            SceneEditingDirectives
        ],
        blueprints: list[
            ResolvedSceneEditingBlueprint
        ],
        validation: TimelineValidationResult,
    ) -> list[str]:
        """Collect unique warnings from all pipeline stages."""

        warnings: list[str] = []

        for directive in directives:
            for warning in directive.warnings:
                if warning not in warnings:
                    warnings.append(
                        warning
                    )

        for blueprint in blueprints:
            for warning in blueprint.warnings:
                if warning not in warnings:
                    warnings.append(
                        warning
                    )

        for issue in validation.warnings:
            if issue.message not in warnings:
                warnings.append(
                    issue.message
                )

        return warnings

    @staticmethod
    def _determine_status(
        *,
        validation_is_valid: bool,
        all_items_render_ready: bool,
        warnings: list[str],
    ) -> GenreTimelinePipelineStatus:
        """Determine final pipeline status."""

        if (
            not validation_is_valid
            or not all_items_render_ready
        ):
            return (
                GenreTimelinePipelineStatus
                .FAILED
            )

        if warnings:
            return (
                GenreTimelinePipelineStatus
                .COMPLETED_WITH_WARNINGS
            )

        return (
            GenreTimelinePipelineStatus
            .COMPLETED
        )