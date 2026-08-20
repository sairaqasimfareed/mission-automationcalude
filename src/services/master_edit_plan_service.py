from __future__ import annotations

from pathlib import Path
from typing import Any

from src.models.audio_timeline import AudioTimeline
from src.models.master_edit_plan import (
    MasterEditPlan,
    MasterEditPlanStatus,
)
from src.models.video_timeline import VideoTimeline


class MasterEditPlanService:
    """
    Build and manage unified master editing plans.

    This service combines the existing video and audio timelines
    into one provider-independent render-preparation object.

    It does not execute effects, transitions, audio mixing,
    FFmpeg commands, rendering, or exporting.
    """

    def build(
        self,
        *,
        video_timeline: VideoTimeline,
        audio_timeline: AudioTimeline,
        duration_tolerance_seconds: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> MasterEditPlan:
        """
        Build and summarize one master editing plan.

        The supplied timelines remain the authoritative timeline
        objects referenced by the resulting plan.
        """

        if duration_tolerance_seconds < 0.0:
            raise ValueError("Master edit duration tolerance " "cannot be negative.")

        plan = MasterEditPlan(
            video_timeline=video_timeline,
            audio_timeline=audio_timeline,
            duration_tolerance_seconds=(duration_tolerance_seconds),
            metadata=dict(metadata or {}),
        )

        return self.refresh(
            plan,
        )

    def refresh(
        self,
        plan: MasterEditPlan,
    ) -> MasterEditPlan:
        """
        Recalculate all plan summaries and readiness flags.

        Rendering and completed plans are immutable workflow
        checkpoints and cannot be refreshed.
        """

        if plan.status == MasterEditPlanStatus.RENDERING:
            raise ValueError("A rendering master edit plan " "cannot be refreshed.")

        if plan.status == MasterEditPlanStatus.COMPLETED:
            raise ValueError("A completed master edit plan " "cannot be refreshed.")

        plan.refresh_summary()

        plan.warnings = self._build_warnings(plan)

        plan.metadata["scene_count"] = plan.scene_count

        plan.metadata["enabled_video_item_count"] = plan.enabled_video_item_count

        plan.metadata["audio_track_count"] = plan.audio_track_count

        plan.metadata["voice_track_count"] = plan.voice_track_count

        plan.metadata["music_track_count"] = plan.music_track_count

        plan.metadata["sound_effect_track_count"] = plan.sound_effect_track_count

        plan.metadata["video_duration_seconds"] = plan.video_duration_seconds

        plan.metadata["audio_duration_seconds"] = plan.audio_duration_seconds

        plan.metadata["duration_difference_seconds"] = plan.duration_difference_seconds

        plan.metadata["duration_compatible"] = plan.duration_compatible

        plan.metadata["ready_for_render"] = plan.ready_for_render

        return plan

    def validate_render_ready(
        self,
        plan: MasterEditPlan,
        *,
        refresh_first: bool = True,
    ) -> MasterEditPlan:
        """
        Validate that a plan may enter the rendering lifecycle.

        A detailed error is raised when one or more readiness
        requirements are not satisfied.
        """

        if refresh_first:
            self.refresh(plan)

        failures = self._readiness_failures(plan)

        if failures:
            failure_text = " ".join(failures)

            raise ValueError(
                "Master edit plan is not ready " f"for rendering. {failure_text}"
            )

        return plan

    def mark_rendering(
        self,
        plan: MasterEditPlan,
    ) -> MasterEditPlan:
        """Mark a fully ready master edit plan as rendering."""

        self.validate_render_ready(
            plan,
            refresh_first=True,
        )

        plan.status = MasterEditPlanStatus.RENDERING

        plan.metadata["render_started"] = True

        plan.metadata["render_completed"] = False

        return plan

    def mark_completed(
        self,
        plan: MasterEditPlan,
        *,
        output_file: str,
    ) -> MasterEditPlan:
        """
        Mark a rendering plan as completed.

        The normalized final output path is stored on the existing
        video timeline so the plan model remains consistent with
        its completed-state validator.
        """

        if plan.status != MasterEditPlanStatus.RENDERING:
            raise ValueError(
                "Only a rendering master edit plan " "can be marked as completed."
            )

        cleaned_output_file = output_file.strip()

        if not cleaned_output_file:
            raise ValueError(
                "Completed master edit plan requires " "a final output file."
            )

        normalized_output_file = Path(cleaned_output_file).as_posix()

        plan.video_timeline.output_file = normalized_output_file

        plan.status = MasterEditPlanStatus.COMPLETED

        plan.metadata["render_started"] = True

        plan.metadata["render_completed"] = True

        plan.metadata["final_output_file"] = normalized_output_file

        return plan

    def mark_failed(
        self,
        plan: MasterEditPlan,
        *,
        error_message: str,
        failure_metadata: dict[str, Any] | None = None,
    ) -> MasterEditPlan:
        """Mark a master edit plan as failed."""

        cleaned_error_message = error_message.strip()

        if not cleaned_error_message:
            raise ValueError("Master edit failure message " "cannot be empty.")

        if plan.status == MasterEditPlanStatus.COMPLETED:
            raise ValueError(
                "A completed master edit plan " "cannot be marked as failed."
            )

        plan.status = MasterEditPlanStatus.FAILED

        failure_warning = "Master edit plan failed: " f"{cleaned_error_message}"

        if failure_warning not in plan.warnings:
            plan.warnings.append(failure_warning)

        plan.metadata["failure_message"] = cleaned_error_message

        plan.metadata["failure_details"] = dict(failure_metadata or {})

        plan.metadata["render_completed"] = False

        return plan

    def summary(
        self,
        plan: MasterEditPlan,
        *,
        refresh_first: bool = False,
    ) -> dict[str, Any]:
        """Return a serializable summary of one master edit plan."""

        if refresh_first:
            self.refresh(plan)

        return {
            "plan_id": str(plan.id),
            "schema_version": (plan.schema_version),
            "status": plan.status.value,
            "scene_count": (plan.scene_count),
            "video_item_count": (plan.video_item_count),
            "enabled_video_item_count": (plan.enabled_video_item_count),
            "audio_track_count": (plan.audio_track_count),
            "voice_track_count": (plan.voice_track_count),
            "music_track_count": (plan.music_track_count),
            "sound_effect_track_count": (plan.sound_effect_track_count),
            "total_track_count": (plan.total_track_count),
            "video_duration_seconds": (plan.video_duration_seconds),
            "audio_duration_seconds": (plan.audio_duration_seconds),
            "total_duration_seconds": (plan.total_duration_seconds),
            "duration_difference_seconds": (plan.duration_difference_seconds),
            "duration_tolerance_seconds": (plan.duration_tolerance_seconds),
            "video_ready": (plan.video_ready),
            "editing_ready": (plan.editing_ready),
            "voice_ready": (plan.voice_ready),
            "audio_ready": (plan.audio_ready),
            "duration_compatible": (plan.duration_compatible),
            "ready_for_render": (plan.ready_for_render),
            "has_video": (plan.has_video),
            "has_audio": (plan.has_audio),
            "is_empty": (plan.is_empty),
            "output_file": (plan.video_timeline.output_file),
            "warning_count": len(plan.warnings),
            "warnings": list(plan.warnings),
            "metadata": dict(plan.metadata),
        }

    @staticmethod
    def can_render(
        plan: MasterEditPlan,
    ) -> bool:
        """Return whether the plan is currently render-ready."""

        return plan.ready_for_render and plan.status == (
            MasterEditPlanStatus.READY_FOR_RENDER
        )

    @staticmethod
    def _readiness_failures(
        plan: MasterEditPlan,
    ) -> list[str]:
        """Return human-readable render-readiness failures."""

        failures: list[str] = []

        if plan.scene_count <= 0:
            failures.append("No enabled video scenes are available.")

        if not plan.video_ready:
            failures.append("The video timeline is not ready.")

        if not plan.editing_ready:
            failures.append(
                "One or more enabled video scenes " "lack resolved editing blueprints."
            )

        if not plan.voice_ready:
            failures.append("The audio timeline lacks ready " "voiceover tracks.")

        if not plan.audio_ready:
            failures.append("One or more audio tracks are not ready.")

        if not plan.duration_compatible:
            failures.append(
                "The audio timeline exceeds the video "
                "duration beyond the configured tolerance."
            )

        if not plan.ready_for_render:
            failures.append(
                "The combined production plan has not "
                "satisfied all render-readiness checks."
            )

        return failures

    @staticmethod
    def _build_warnings(
        plan: MasterEditPlan,
    ) -> list[str]:
        """Build stable, unique plan warnings."""

        warnings: list[str] = []

        def add_warning(
            message: str,
        ) -> None:
            cleaned_message = message.strip()

            if cleaned_message and cleaned_message not in warnings:
                warnings.append(cleaned_message)

        if not plan.has_video:
            add_warning("Master edit plan contains no " "video media.")

        if not plan.has_audio:
            add_warning("Master edit plan contains no " "audio tracks.")

        if plan.has_video and plan.enabled_video_item_count == 0:
            add_warning("Master edit plan contains no " "enabled video timeline items.")

        if not plan.video_ready:
            add_warning("One or more video clips are not " "ready for production.")

        if not plan.editing_ready:
            add_warning(
                "One or more enabled video scenes "
                "lack resolved editing instructions."
            )

        if plan.voice_track_count == 0:
            add_warning("Master edit plan contains no " "voiceover tracks.")
        elif not plan.voice_ready:
            add_warning("One or more voiceover tracks are " "not ready.")

        if plan.audio_track_count > 0 and not plan.audio_ready:
            add_warning("One or more audio tracks are " "not ready.")

        if plan.video_duration_seconds > 0.0 and plan.audio_duration_seconds <= 0.0:
            add_warning("Video media exists without a usable " "audio timeline.")

        if plan.audio_duration_seconds > (
            plan.video_duration_seconds + plan.duration_tolerance_seconds
        ):
            add_warning(
                "Audio duration exceeds video duration "
                "beyond the configured tolerance."
            )

        if (
            plan.video_duration_seconds > 0.0
            and plan.audio_duration_seconds > 0.0
            and (plan.video_duration_seconds - plan.audio_duration_seconds)
            > plan.duration_tolerance_seconds
        ):
            add_warning(
                "Audio ends before the video timeline. "
                "Silence or additional audio may be "
                "required."
            )

        if plan.ready_for_render:
            add_warning(
                "Master edit plan is structurally "
                "ready, but renderer-specific checks "
                "have not yet been executed."
            )

        return warnings
