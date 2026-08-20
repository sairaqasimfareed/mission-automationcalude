from __future__ import annotations

import hashlib
import json

from src.models.audio_timeline import AudioTimeline
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline


class RenderIdentityService:
    """
    Computes a deterministic SHA-256 identity for one job's current
    render inputs - video timeline identity + audio timeline identity
    + render settings, per the production-hardening spec's Phase 6
    requirement.

    Deliberately excludes the produced output file from the hash
    itself: the identity must be computable from inputs alone (so a
    caller can ask "would a fresh render still match?" without having
    already produced one), and hashing the actual output file's bytes
    would require file I/O this service has no need for. The output
    file a render actually produced is recorded separately, alongside
    the identity, by whatever creates a FinalPreview from it - not
    treated as an input to the identity computation.

    Read-only and stateless: never mutates the job, never caches a
    result - recomputed fresh every call, matching
    ProductionReadinessService/InvalidationService.is_stale()'s
    "never trust a stale verdict" convention elsewhere in this
    codebase.
    """

    def compute(self, job: VideoJob) -> str:
        if job.video_timeline is None:
            raise ValueError("Render identity requires a built video timeline.")

        if job.audio_timeline is None:
            raise ValueError("Render identity requires an audio timeline.")

        payload = {
            "video_timeline": self._video_timeline_identity(job.video_timeline),
            "audio_timeline": self._audio_timeline_identity(job.audio_timeline),
            "render_settings": {
                "production_mode": job.production_mode.value,
                "resolution": job.video_timeline.output_resolution,
                "frame_rate": job.video_timeline.frame_rate,
            },
        }

        canonical = json.dumps(payload, sort_keys=True, default=str)

        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _video_timeline_identity(timeline: VideoTimeline) -> list[dict[str, object]]:
        return [
            {
                "scene_number": item.scene_number,
                "track_index": item.track_index,
                "start_time_seconds": item.start_time_seconds,
                "end_time_seconds": item.end_time_seconds,
                "clip_source": item.clip.local_file or item.clip.source_url,
                "clip_source_type": item.clip.source_type.value,
            }
            for item in sorted(
                timeline.items,
                key=lambda item: (item.track_index, item.start_time_seconds),
            )
        ]

    @staticmethod
    def _audio_timeline_identity(timeline: AudioTimeline) -> list[dict[str, object]]:
        return [
            {
                "track_type": track.track_type.value,
                "source_file": track.source_file,
                "start_time_seconds": track.start_time_seconds,
                "duration_seconds": track.duration_seconds,
                "volume": track.volume,
            }
            for track in sorted(
                timeline.tracks,
                key=lambda track: (track.track_type.value, track.start_time_seconds),
            )
        ]
