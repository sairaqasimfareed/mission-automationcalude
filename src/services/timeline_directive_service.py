from __future__ import annotations

from src.models.resolved_editing_blueprint import (
    BlueprintResolutionStatus,
    ResolvedSceneEditingBlueprint,
)
from src.models.video_timeline import VideoTimeline
from src.models.video_timeline_item import (
    VideoTimelineItem,
)


class TimelineDirectiveService:
    """
    Attaches resolved editing blueprints to timeline items.

    This service does not generate renderer commands. It only
    connects provider-independent editing instructions with the
    correct timeline scenes.
    """

    def attach_blueprint(
        self,
        timeline: VideoTimeline,
        *,
        blueprint: ResolvedSceneEditingBlueprint,
        replace: bool = False,
    ) -> VideoTimelineItem:
        """
        Attach one resolved blueprint to its timeline scene.

        Phase 5 (multi-clip scene splitting), real-world finding,
        2026-09-21: a split scene contributes several timeline items
        sharing one scene_number (one per sub-clip) - a blueprint is a
        per-SCENE creative decision (color grade, transitions, etc.),
        so it is attached to every one of that scene's items, not just
        one. _find_item used to raise outright the moment more than
        one item shared a scene_number ("Multiple timeline items use
        the same scene number") - confirmed this would have hard-
        failed transition/render planning for every real split scene,
        since TransitionExecutionService requires every item to carry
        a blueprint. Returns the PRIMARY item (clip_sequence_index 0)
        for callers that only need one representative item back -
        identical to this method's own return value before this field
        existed, since every scene had exactly one item then.
        """

        if not blueprint.is_resolved:
            raise ValueError(
                "Only resolved editing blueprints may " "be attached to a timeline."
            )

        items = self._find_items(
            timeline=timeline,
            scene_number=blueprint.scene_number,
        )

        if any(item.editing_blueprint is not None for item in items) and not replace:
            raise ValueError(
                "The timeline scene already contains " "an editing blueprint."
            )

        for item in items:
            item.editing_blueprint = blueprint

            item.transition_in = blueprint.transition_in.preset.resolved_preset_id

            item.transition_out = blueprint.transition_out.preset.resolved_preset_id

            item.metadata["editing_blueprint_attached"] = True

            item.metadata["editing_blueprint_status"] = blueprint.status.value

            item.metadata["editing_blueprint_fallback_count"] = blueprint.fallback_count

            item.metadata["editing_blueprint_exact_match_count"] = (
                blueprint.exact_match_count
            )

            item.metadata["editing_blueprint_schema_version"] = blueprint.schema_version

        return min(items, key=lambda item: item.clip_sequence_index)

    def attach_many(
        self,
        timeline: VideoTimeline,
        *,
        blueprints: list[ResolvedSceneEditingBlueprint],
        replace: bool = False,
        require_all_timeline_scenes: bool = False,
    ) -> list[VideoTimelineItem]:
        """
        Attach multiple blueprints.

        Duplicate blueprint scene numbers are rejected before any
        timeline item is modified.
        """

        scene_numbers = [blueprint.scene_number for blueprint in blueprints]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Duplicate editing blueprint scene numbers " "cannot be attached."
            )

        if require_all_timeline_scenes:
            enabled_scene_numbers = {
                item.scene_number for item in timeline.items if item.enabled
            }

            blueprint_scene_numbers = set(scene_numbers)

            missing_scene_numbers = enabled_scene_numbers - blueprint_scene_numbers

            extra_scene_numbers = blueprint_scene_numbers - enabled_scene_numbers

            if missing_scene_numbers:
                missing_text = ", ".join(
                    str(scene_number) for scene_number in sorted(missing_scene_numbers)
                )

                raise ValueError(
                    "Editing blueprints are missing for "
                    f"timeline scenes: {missing_text}"
                )

            if extra_scene_numbers:
                extra_text = ", ".join(
                    str(scene_number) for scene_number in sorted(extra_scene_numbers)
                )

                raise ValueError(
                    "Editing blueprints reference unknown "
                    f"timeline scenes: {extra_text}"
                )

        attached_items: list[VideoTimelineItem] = []

        for blueprint in blueprints:
            attached_items.append(
                self.attach_blueprint(
                    timeline,
                    blueprint=blueprint,
                    replace=replace,
                )
            )

        return attached_items

    def detach_blueprint(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
        clear_transition_fields: bool = True,
    ) -> ResolvedSceneEditingBlueprint:
        """
        Remove and return one attached blueprint - from every timeline
        item sharing this scene_number (Phase 5: a split scene's
        several sub-clip items), not just one.
        """

        items = self._find_items(
            timeline=timeline,
            scene_number=scene_number,
        )

        blueprint = items[0].editing_blueprint

        if blueprint is None:
            raise ValueError(
                "The timeline scene does not contain " "an editing blueprint."
            )

        for item in items:
            item.editing_blueprint = None

            if clear_transition_fields:
                item.transition_in = None
                item.transition_out = None

            metadata_keys = [
                key for key in item.metadata if key.startswith("editing_blueprint_")
            ]

            for key in metadata_keys:
                item.metadata.pop(
                    key,
                    None,
                )

        return blueprint

    def mark_applied(
        self,
        timeline: VideoTimeline,
        *,
        scene_number: int,
    ) -> VideoTimelineItem:
        """
        Mark a scene blueprint as applied by an editing engine, on
        every timeline item sharing this scene_number (Phase 5: a
        split scene's several sub-clip items).

        Actual FFmpeg or renderer execution will be implemented
        in a later module.
        """

        items = self._find_items(
            timeline=timeline,
            scene_number=scene_number,
        )

        blueprint = items[0].editing_blueprint

        if blueprint is None:
            raise ValueError(
                "The timeline scene does not contain " "an editing blueprint."
            )

        blueprint.status = BlueprintResolutionStatus.APPLIED

        for item in items:
            item.metadata["editing_blueprint_status"] = blueprint.status.value

        return min(items, key=lambda item: item.clip_sequence_index)

    def scenes_without_blueprints(
        self,
        timeline: VideoTimeline,
        *,
        enabled_only: bool = True,
    ) -> list[int]:
        """Return scene numbers lacking editing blueprints."""

        scene_numbers = {
            item.scene_number
            for item in timeline.items
            if (item.editing_blueprint is None and (item.enabled or not enabled_only))
        }

        return sorted(scene_numbers)

    def render_ready_items(
        self,
        timeline: VideoTimeline,
    ) -> list[VideoTimelineItem]:
        """Return enabled items with resolved blueprints."""

        return [item for item in timeline.ordered_items() if item.is_render_ready]

    @staticmethod
    def _find_items(
        *,
        timeline: VideoTimeline,
        scene_number: int,
    ) -> list[VideoTimelineItem]:
        """
        Return every timeline item sharing one scene number, ordered
        by clip_sequence_index.

        Phase 5 (multi-clip scene splitting): more than one match is
        no longer an error - a split scene legitimately contributes
        several sub-clip items sharing one scene_number, distinguished
        only by clip_sequence_index. Every caller here treats a
        blueprint as a per-scene decision applied uniformly across all
        of a scene's own items, never as a reason to pick just one.
        """

        matches = sorted(
            (item for item in timeline.items if item.scene_number == scene_number),
            key=lambda item: item.clip_sequence_index,
        )

        if not matches:
            raise KeyError("Timeline scene was not found: " f"{scene_number}")

        return matches
