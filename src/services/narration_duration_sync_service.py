from __future__ import annotations

from src.models.video_job import VideoJob
from src.services.voice_timeline_service import VoiceTimelineService


def sync_real_narration_durations(job: VideoJob, *, overwrite: bool = False) -> int:
    """
    Copy each scene's real, measured voiceover length onto
    Scene.real_narration_duration_seconds.

    Real-world finding, 2026-10-03: that field is what clip generation sizes
    each video clip from (and what the Prompts/Content tabs preview), but only
    the render-time voice step ever set it. Generating the voiceover from the
    Audio tab - the audio-first path - left every scene's field empty, so clips
    and previews silently fell back to the script's word-count estimate (a
    1-second "Honey" scene estimated at 4s, a scene estimated at 9s that really
    runs 7.7s).

    By default only fills scenes that have no real duration yet (safe to call
    repeatedly, e.g. for a project whose voice was generated before this
    existed). overwrite=True re-reads every scene - used right after the voice
    was regenerated, when any earlier value is stale. A scene without a single,
    unambiguous voice track is left alone. Returns how many scenes changed.
    """

    if job.audio_timeline is None:
        return 0

    timeline_service = VoiceTimelineService()
    changed = 0

    for scene in job.scenes:
        if scene.real_narration_duration_seconds is not None and not overwrite:
            continue

        try:
            track = timeline_service.get_scene_voice(
                job.audio_timeline, scene_number=scene.scene_number
            )
        except (KeyError, ValueError):
            continue

        if track.duration_seconds is None or track.duration_seconds <= 0:
            continue

        if scene.real_narration_duration_seconds != track.duration_seconds:
            scene.real_narration_duration_seconds = track.duration_seconds
            changed += 1

    return changed
