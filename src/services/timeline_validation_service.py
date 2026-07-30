from __future__ import annotations

from collections import defaultdict

from src.models.timeline_validation import (
    TimelineValidationCode,
    TimelineValidationIssue,
    TimelineValidationResult,
    TimelineValidationSeverity,
)
from src.models.video_clip import VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class TimelineValidationService:
    """
    Validate explicit video timeline placement.

    Editing-blueprint validation is optional so existing timeline
    workflows remain backward compatible.
    """

    TIME_TOLERANCE_SECONDS = 0.001

    def validate(
        self,
        timeline: VideoTimeline,
        *,
        require_gap_free_primary_track: bool = True,
        require_editing_blueprints: bool = False,
        warn_on_blueprint_fallbacks: bool = True,
    ) -> TimelineValidationResult:
        """Validate one video timeline and return a report."""

        enabled_items = [
            item
            for item in timeline.items
            if item.enabled
        ]

        result = TimelineValidationResult(
            is_valid=True,
            item_count=len(timeline.items),
            enabled_item_count=len(enabled_items),
            total_duration_seconds=(
                timeline.calculate_duration()
            ),
        )

        if not enabled_items:
            result.errors.append(
                TimelineValidationIssue(
                    code=TimelineValidationCode.NO_ITEMS,
                    severity=(
                        TimelineValidationSeverity.ERROR
                    ),
                    message=(
                        "The timeline does not contain "
                        "any enabled video items."
                    ),
                )
            )

            result.is_valid = False
            return result

        result.track_count = len(
            {
                item.track_index
                for item in enabled_items
            }
        )

        self._validate_individual_items(
            items=enabled_items,
            result=result,
        )

        self._validate_duplicate_scenes(
            items=enabled_items,
            result=result,
        )

        self._validate_track_placement(
            items=enabled_items,
            result=result,
            require_gap_free_primary_track=(
                require_gap_free_primary_track
            ),
        )

        self._validate_editing_blueprints(
            items=enabled_items,
            result=result,
            require_editing_blueprints=(
                require_editing_blueprints
            ),
            warn_on_blueprint_fallbacks=(
                warn_on_blueprint_fallbacks
            ),
        )

        result.is_valid = len(result.errors) == 0

        return result

    def _validate_individual_items(
        self,
        *,
        items: list[VideoTimelineItem],
        result: TimelineValidationResult,
    ) -> None:
        """Validate item and clip-level timeline requirements."""

        for item in items:
            duration = (
                item.end_time_seconds
                - item.start_time_seconds
            )

            if duration <= 0:
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .INVALID_DURATION
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "Timeline item duration must "
                            "be greater than zero."
                        ),
                        scene_number=item.scene_number,
                        start_time_seconds=(
                            item.start_time_seconds
                        ),
                        end_time_seconds=(
                            item.end_time_seconds
                        ),
                    )
                )

            expected_duration = float(
                item.clip.duration_seconds
            )

            if (
                abs(
                    duration
                    - expected_duration
                )
                > self.TIME_TOLERANCE_SECONDS
            ):
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .CLIP_DURATION_MISMATCH
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "Timeline item duration does not "
                            "match its video clip duration."
                        ),
                        scene_number=item.scene_number,
                        metadata={
                            "timeline_duration_seconds": (
                                duration
                            ),
                            "clip_duration_seconds": (
                                expected_duration
                            ),
                        },
                    )
                )

            if (
                item.clip.status
                != VideoClipStatus.READY
            ):
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .CLIP_NOT_READY
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "Only READY video clips can be "
                            "used in the active timeline."
                        ),
                        scene_number=item.scene_number,
                        metadata={
                            "clip_status": (
                                item.clip.status.value
                            ),
                        },
                    )
                )

            if (
                not item.clip.local_file
                and not item.clip.source_url
            ):
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .MISSING_CLIP_SOURCE
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "Timeline clip does not contain "
                            "a local file or source URL."
                        ),
                        scene_number=item.scene_number,
                    )
                )

    @staticmethod
    def _validate_duplicate_scenes(
        *,
        items: list[VideoTimelineItem],
        result: TimelineValidationResult,
    ) -> None:
        """Find duplicate scenes on the same video track."""

        scenes_by_track: dict[
            int,
            set[int],
        ] = defaultdict(set)

        for item in items:
            track_scenes = scenes_by_track[
                item.track_index
            ]

            if item.scene_number in track_scenes:
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .DUPLICATE_SCENE
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "The same scene appears more than "
                            "once on the same video track."
                        ),
                        scene_number=item.scene_number,
                        metadata={
                            "track_index": item.track_index,
                        },
                    )
                )
            else:
                track_scenes.add(
                    item.scene_number
                )

    def _validate_track_placement(
        self,
        *,
        items: list[VideoTimelineItem],
        result: TimelineValidationResult,
        require_gap_free_primary_track: bool,
    ) -> None:
        """Detect gaps and overlaps within individual tracks."""

        items_by_track: dict[
            int,
            list[VideoTimelineItem],
        ] = defaultdict(list)

        for item in items:
            items_by_track[
                item.track_index
            ].append(item)

        for track_index, track_items in (
            items_by_track.items()
        ):
            ordered_items = sorted(
                track_items,
                key=lambda item: (
                    item.start_time_seconds,
                    item.end_time_seconds,
                    item.layer_index,
                    item.scene_number,
                ),
            )

            previous_item: (
                VideoTimelineItem | None
            ) = None

            for item in ordered_items:
                if previous_item is None:
                    if (
                        track_index == 0
                        and require_gap_free_primary_track
                        and item.start_time_seconds
                        > self.TIME_TOLERANCE_SECONDS
                    ):
                        initial_gap = (
                            item.start_time_seconds
                        )

                        result.gap_duration_seconds += (
                            initial_gap
                        )

                        result.errors.append(
                            TimelineValidationIssue(
                                code=(
                                    TimelineValidationCode
                                    .TIMELINE_GAP
                                ),
                                severity=(
                                    TimelineValidationSeverity
                                    .ERROR
                                ),
                                message=(
                                    "The primary video track "
                                    "does not begin at zero."
                                ),
                                scene_number=(
                                    item.scene_number
                                ),
                                start_time_seconds=0.0,
                                end_time_seconds=(
                                    item.start_time_seconds
                                ),
                                metadata={
                                    "track_index": (
                                        track_index
                                    ),
                                    "gap_duration_seconds": (
                                        initial_gap
                                    ),
                                },
                            )
                        )

                    previous_item = item
                    continue

                difference = (
                    item.start_time_seconds
                    - previous_item.end_time_seconds
                )

                if (
                    difference
                    > self.TIME_TOLERANCE_SECONDS
                ):
                    result.gap_duration_seconds += (
                        difference
                    )

                    issue = TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .TIMELINE_GAP
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                            if (
                                track_index == 0
                                and (
                                    require_gap_free_primary_track
                                )
                            )
                            else (
                                TimelineValidationSeverity
                                .WARNING
                            )
                        ),
                        message=(
                            "A gap was detected between "
                            "timeline items."
                        ),
                        scene_number=(
                            previous_item.scene_number
                        ),
                        related_scene_number=(
                            item.scene_number
                        ),
                        start_time_seconds=(
                            previous_item.end_time_seconds
                        ),
                        end_time_seconds=(
                            item.start_time_seconds
                        ),
                        metadata={
                            "track_index": track_index,
                            "gap_duration_seconds": (
                                difference
                            ),
                        },
                    )

                    if (
                        issue.severity
                        == TimelineValidationSeverity.ERROR
                    ):
                        result.errors.append(issue)
                    else:
                        result.warnings.append(issue)

                elif (
                    difference
                    < -self.TIME_TOLERANCE_SECONDS
                ):
                    overlap_duration = abs(
                        difference
                    )

                    result.overlap_duration_seconds += (
                        overlap_duration
                    )

                    result.errors.append(
                        TimelineValidationIssue(
                            code=(
                                TimelineValidationCode
                                .TIMELINE_OVERLAP
                            ),
                            severity=(
                                TimelineValidationSeverity.ERROR
                            ),
                            message=(
                                "An overlap was detected between "
                                "items on the same video track."
                            ),
                            scene_number=(
                                previous_item.scene_number
                            ),
                            related_scene_number=(
                                item.scene_number
                            ),
                            start_time_seconds=(
                                item.start_time_seconds
                            ),
                            end_time_seconds=(
                                previous_item.end_time_seconds
                            ),
                            metadata={
                                "track_index": track_index,
                                "overlap_duration_seconds": (
                                    overlap_duration
                                ),
                            },
                        )
                    )

                if (
                    item.end_time_seconds
                    > previous_item.end_time_seconds
                ):
                    previous_item = item

    @staticmethod
    def _validate_editing_blueprints(
        *,
        items: list[VideoTimelineItem],
        result: TimelineValidationResult,
        require_editing_blueprints: bool,
        warn_on_blueprint_fallbacks: bool,
    ) -> None:
        """Validate resolved editing blueprints on timeline items."""

        for item in items:
            blueprint = item.editing_blueprint

            if blueprint is None:
                if require_editing_blueprints:
                    result.errors.append(
                        TimelineValidationIssue(
                            code=(
                                TimelineValidationCode
                                .MISSING_EDITING_BLUEPRINT
                            ),
                            severity=(
                                TimelineValidationSeverity.ERROR
                            ),
                            message=(
                                "The enabled timeline scene "
                                "does not contain an editing "
                                "blueprint."
                            ),
                            scene_number=item.scene_number,
                        )
                    )

                continue

            result.blueprint_count += 1

            if (
                blueprint.scene_number
                != item.scene_number
            ):
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .EDITING_BLUEPRINT_SCENE_MISMATCH
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "The editing blueprint scene number "
                            "does not match its timeline item."
                        ),
                        scene_number=item.scene_number,
                        related_scene_number=(
                            blueprint.scene_number
                        ),
                    )
                )

                continue

            if not blueprint.is_resolved:
                result.errors.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .UNRESOLVED_EDITING_BLUEPRINT
                        ),
                        severity=(
                            TimelineValidationSeverity.ERROR
                        ),
                        message=(
                            "The timeline scene contains an "
                            "unresolved editing blueprint."
                        ),
                        scene_number=item.scene_number,
                        metadata={
                            "blueprint_status": (
                                blueprint.status.value
                            ),
                        },
                    )
                )

                continue

            result.render_ready_item_count += 1

            result.blueprint_fallback_count += (
                blueprint.fallback_count
            )

            if (
                warn_on_blueprint_fallbacks
                and blueprint.fallback_count > 0
            ):
                result.warnings.append(
                    TimelineValidationIssue(
                        code=(
                            TimelineValidationCode
                            .EDITING_BLUEPRINT_FALLBACK_USED
                        ),
                        severity=(
                            TimelineValidationSeverity.WARNING
                        ),
                        message=(
                            "The editing blueprint uses one "
                            "or more safe fallback presets."
                        ),
                        scene_number=item.scene_number,
                        metadata={
                            "fallback_count": (
                                blueprint.fallback_count
                            ),
                            "blueprint_status": (
                                blueprint.status.value
                            ),
                        },
                    )
                )