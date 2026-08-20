from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, model_validator

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.base import MissionBaseModel
from src.models.video_clip import VideoClipStatus
from src.models.video_timeline import VideoTimeline


class MasterEditPlanStatus(str, Enum):
    """Lifecycle state of one master editing plan."""

    DRAFT = "draft"
    VALIDATED = "validated"
    READY_FOR_RENDER = "ready_for_render"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class MasterEditPlan(MissionBaseModel):
    """
    Unified provider-independent production editing plan.

    The plan combines the existing video and audio timelines into
    one render-preparation object. It does not execute FFmpeg,
    transitions, effects, subtitles, audio mixing, or rendering.
    """

    schema_version: str = "1.0"

    video_timeline: VideoTimeline
    audio_timeline: AudioTimeline

    status: MasterEditPlanStatus = MasterEditPlanStatus.DRAFT

    duration_tolerance_seconds: float = Field(
        default=0.5,
        ge=0.0,
        le=60.0,
    )

    video_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    audio_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    total_duration_seconds: float = Field(
        default=0.0,
        ge=0.0,
    )

    scene_count: int = Field(
        default=0,
        ge=0,
    )

    enabled_video_item_count: int = Field(
        default=0,
        ge=0,
    )

    audio_track_count: int = Field(
        default=0,
        ge=0,
    )

    video_ready: bool = False
    editing_ready: bool = False
    voice_ready: bool = False
    audio_ready: bool = False
    duration_compatible: bool = False
    ready_for_render: bool = False

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_master_edit_plan(
        self,
    ) -> MasterEditPlan:
        """Prevent internally contradictory plan states."""

        if self.scene_count < 0:
            raise ValueError("Master edit plan scene count " "cannot be negative.")

        if (
            self.status == MasterEditPlanStatus.READY_FOR_RENDER
            and not self.ready_for_render
        ):
            raise ValueError("READY_FOR_RENDER status requires " "render readiness.")

        if self.ready_for_render and not self.video_ready:
            raise ValueError(
                "A render-ready master edit plan " "requires a ready video timeline."
            )

        if self.ready_for_render and not self.editing_ready:
            raise ValueError(
                "A render-ready master edit plan "
                "requires resolved editing blueprints."
            )

        if self.ready_for_render and not self.voice_ready:
            raise ValueError(
                "A render-ready master edit plan " "requires ready voice tracks."
            )

        if self.ready_for_render and not self.audio_ready:
            raise ValueError(
                "A render-ready master edit plan " "requires ready audio tracks."
            )

        if self.ready_for_render and not self.duration_compatible:
            raise ValueError(
                "A render-ready master edit plan "
                "requires compatible timeline durations."
            )

        if (
            self.status == MasterEditPlanStatus.COMPLETED
            and not self.video_timeline.output_file
        ):
            raise ValueError(
                "A completed master edit plan requires " "a final video output file."
            )

        return self

    def refresh_summary(self) -> None:
        """Recalculate plan counts, durations, and readiness."""

        self.video_duration_seconds = self.video_timeline.calculate_duration()

        self.audio_duration_seconds = self.audio_timeline.calculate_duration()

        self.total_duration_seconds = max(
            self.video_duration_seconds,
            self.audio_duration_seconds,
        )

        enabled_items = self.video_timeline.ordered_items()

        self.enabled_video_item_count = len(enabled_items)

        self.scene_count = len({item.scene_number for item in enabled_items})

        self.audio_track_count = len(self.audio_timeline.tracks)

        self.video_ready = bool(enabled_items) and all(
            item.clip.status == VideoClipStatus.READY
            and (bool(item.clip.local_file) or bool(item.clip.source_url))
            for item in enabled_items
        )

        self.editing_ready = bool(enabled_items) and all(
            item.is_render_ready for item in enabled_items
        )

        voice_tracks = [
            track
            for track in self.audio_timeline.tracks
            if (track.track_type == AudioTrackType.VOICEOVER)
        ]

        self.voice_ready = bool(voice_tracks) and all(
            track.status == AudioTrackStatus.READY
            and bool(track.source_file.strip())
            and track.duration_seconds > 0.0
            and track.start_time_seconds >= 0.0
            for track in voice_tracks
        )

        self.audio_ready = bool(self.audio_timeline.tracks) and all(
            track.status == AudioTrackStatus.READY
            and bool(track.source_file.strip())
            and track.duration_seconds > 0.0
            and track.start_time_seconds >= 0.0
            for track in (self.audio_timeline.tracks)
        )

        self.duration_compatible = self._durations_are_compatible()

        self.ready_for_render = all(
            (
                self.video_ready,
                self.editing_ready,
                self.voice_ready,
                self.audio_ready,
                self.duration_compatible,
                self.scene_count > 0,
            )
        )

        if self.ready_for_render:
            self.status = MasterEditPlanStatus.READY_FOR_RENDER
        elif (
            self.video_ready
            or self.audio_ready
            or self.editing_ready
            or self.voice_ready
        ):
            self.status = MasterEditPlanStatus.VALIDATED
        else:
            self.status = MasterEditPlanStatus.DRAFT

    def _durations_are_compatible(
        self,
    ) -> bool:
        """Check whether audio fits inside the video timeline."""

        if self.video_duration_seconds <= 0.0 or self.audio_duration_seconds <= 0.0:
            return False

        return self.audio_duration_seconds <= (
            self.video_duration_seconds + self.duration_tolerance_seconds
        )

    @property
    def video_item_count(self) -> int:
        """Return total explicit video timeline items."""

        return len(self.video_timeline.items)

    @property
    def total_track_count(self) -> int:
        """Return total video and audio placements."""

        return self.video_item_count + len(self.audio_timeline.tracks)

    @property
    def voice_track_count(self) -> int:
        """Return the number of voiceover tracks."""

        return sum(
            1
            for track in self.audio_timeline.tracks
            if (track.track_type == AudioTrackType.VOICEOVER)
        )

    @property
    def music_track_count(self) -> int:
        """Return the number of background-music tracks."""

        return sum(
            1
            for track in self.audio_timeline.tracks
            if (track.track_type == AudioTrackType.BACKGROUND_MUSIC)
        )

    @property
    def sound_effect_track_count(self) -> int:
        """Return the number of sound-effect tracks."""

        return sum(
            1
            for track in self.audio_timeline.tracks
            if (track.track_type == AudioTrackType.SOUND_EFFECT)
        )

    @property
    def has_video(self) -> bool:
        """Return whether video placements are available."""

        return bool(self.video_timeline.items or self.video_timeline.clips)

    @property
    def has_audio(self) -> bool:
        """Return whether audio tracks are available."""

        return bool(self.audio_timeline.tracks)

    @property
    def is_empty(self) -> bool:
        """Return whether the plan has no media."""

        return not self.has_video and not self.has_audio

    @property
    def duration_difference_seconds(
        self,
    ) -> float:
        """Return audio duration minus video duration."""

        return self.audio_duration_seconds - self.video_duration_seconds
