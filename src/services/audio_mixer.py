from __future__ import annotations

import time

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.render_result import (
    RenderResult,
    RenderStatus,
)


class AudioMixer:
    """
    Dry-run audio mixer.

    Real FFmpeg mixing will replace this implementation later.
    """

    def mix(self, timeline: AudioTimeline) -> RenderResult:
        if not timeline.tracks:
            return RenderResult(
                success=False,
                render_engine="ffmpeg-audio",
                status=RenderStatus.FAILED,
                error_message="Audio timeline contains no tracks.",
            )

        not_ready_tracks = [
            track
            for track in timeline.tracks
            if track.status != AudioTrackStatus.READY
        ]

        if not_ready_tracks:
            return RenderResult(
                success=False,
                render_engine="ffmpeg-audio",
                status=RenderStatus.FAILED,
                error_message="One or more audio tracks are not ready.",
            )

        has_voiceover = any(
            track.track_type == AudioTrackType.VOICEOVER
            for track in timeline.tracks
        )

        if not has_voiceover:
            return RenderResult(
                success=False,
                render_engine="ffmpeg-audio",
                status=RenderStatus.FAILED,
                error_message="Voiceover track is missing.",
            )

        started_at = time.perf_counter()
        time.sleep(0.05)

        duration = timeline.calculate_duration()
        timeline.output_file = "outputs/audio/final_mix.wav"

        return RenderResult(
            success=True,
            output_file=timeline.output_file,
            render_engine="ffmpeg-audio",
            render_time_seconds=time.perf_counter() - started_at,
            duration_seconds=int(duration),
            status=RenderStatus.COMPLETED,
            warnings=[
                "Dry-run mixer: no real audio file was generated."
            ],
        )