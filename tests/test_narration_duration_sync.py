"""
Real narration durations, 2026-10-03: generating the voiceover from the Audio
tab stored each scene's real length only on its audio track, never on the
scene - so clip generation and the Prompts/Content tabs silently used the
script's word-count estimates (a 1s "Honey" scene estimated at 4s).
"""

from __future__ import annotations

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.scene import Scene
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider
from src.services.enriched_scene_prompt_service import EnrichedScenePromptService
from src.services.narration_duration_sync_service import (
    sync_real_narration_durations,
)


def _scene(number: int, *, estimate: int = 8) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration {number}.",
        visual_prompt=f"Visual {number}.",
        estimated_duration_seconds=estimate,
    )


def _voice(scene_number: int | None, seconds: float) -> AudioTrack:
    metadata = {} if scene_number is None else {"scene_number": scene_number}

    return AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=f"voice/{scene_number}.mp3",
        duration_seconds=seconds,
        status=AudioTrackStatus.READY,
        metadata=metadata,
    )


def _job(scenes: list[Scene], tracks: list[AudioTrack] | None) -> VideoJob:
    job = VideoJob(
        project_name="Test",
        channel_name="Channel",
        niche="testing",
        topic="A topic",
    )
    job.scenes = scenes

    if tracks is not None:
        job.audio_timeline = AudioTimeline(tracks=tracks)

    return job


class TestSync:
    def test_copies_each_scenes_real_length_onto_the_scene(self) -> None:
        job = _job([_scene(1), _scene(2)], [_voice(1, 7.66), _voice(2, 1.07)])

        changed = sync_real_narration_durations(job)

        assert changed == 2
        assert [s.real_narration_duration_seconds for s in job.scenes] == [7.66, 1.07]

    def test_is_idempotent_and_does_not_overwrite_by_default(self) -> None:
        job = _job([_scene(1)], [_voice(1, 7.66)])
        job.scenes[0].real_narration_duration_seconds = 5.0

        assert sync_real_narration_durations(job) == 0
        assert job.scenes[0].real_narration_duration_seconds == 5.0

    def test_overwrite_replaces_a_stale_value_after_regeneration(self) -> None:
        job = _job([_scene(1)], [_voice(1, 7.66)])
        job.scenes[0].real_narration_duration_seconds = 5.0

        assert sync_real_narration_durations(job, overwrite=True) == 1
        assert job.scenes[0].real_narration_duration_seconds == 7.66

    def test_no_audio_timeline_changes_nothing(self) -> None:
        job = _job([_scene(1)], None)

        assert sync_real_narration_durations(job) == 0
        assert job.scenes[0].real_narration_duration_seconds is None

    def test_a_scene_without_a_voice_track_is_left_alone(self) -> None:
        job = _job([_scene(1), _scene(2)], [_voice(1, 3.0)])

        sync_real_narration_durations(job)

        assert job.scenes[0].real_narration_duration_seconds == 3.0
        assert job.scenes[1].real_narration_duration_seconds is None

    def test_a_scene_with_two_voice_tracks_is_left_alone(self) -> None:
        job = _job([_scene(1)], [_voice(1, 3.0), _voice(1, 4.0)])

        assert sync_real_narration_durations(job) == 0
        assert job.scenes[0].real_narration_duration_seconds is None

    @pytest.mark.parametrize("seconds", [0.0, -1.0])
    def test_a_non_positive_length_is_ignored(self, seconds: float) -> None:
        job = _job([_scene(1)], None)
        track = _voice(1, 1.0)
        track.duration_seconds = seconds
        job.audio_timeline = AudioTimeline(tracks=[track])

        assert sync_real_narration_durations(job) == 0

    def test_non_voice_tracks_are_ignored(self) -> None:
        music = AudioTrack(
            track_type=AudioTrackType.BACKGROUND_MUSIC,
            source_file="m.mp3",
            duration_seconds=30.0,
            status=AudioTrackStatus.READY,
            metadata={"scene_number": 1},
        )
        job = _job([_scene(1)], [music])

        assert sync_real_narration_durations(job) == 0


def test_the_preview_uses_the_real_length_from_the_voice_track() -> None:
    """A 4s estimate for a scene that really runs 1.07s: the real length is read
    from the voice track with no manual step, and the Muse preview is sized from
    it - at Muse's 3s minimum clip length (2026-10-04), not the bare 1.07s."""

    job = _job([_scene(2, estimate=4)], [_voice(2, 1.07)])
    job.video_provider = VideoProvider.MUSE

    entry = EnrichedScenePromptService().build_entry(job=job, scene=job.scenes[0])

    assert job.scenes[0].real_narration_duration_seconds == 1.07
    assert entry.execution_duration_seconds == 3.0
