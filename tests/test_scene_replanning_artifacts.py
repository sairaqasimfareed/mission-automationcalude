"""
Planning scenes again (merging on or off) renumbers them, but the voiceover, clip records and per-scene
records are keyed by scene NUMBER. Found live 2026-10-15 (Haunted wife): after merging, scene 3 (three
old scenes joined, about nine seconds) was sized from the 1.8 seconds of the OLD scene 3's voice, so the
shot plan, prompts and clips tab all disagreed. Records of scenes that changed must not follow their number.
"""

from __future__ import annotations

from src.models.asset_state import AssetWorkflowStatus, SceneAssetState
from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.services.invalidation_service import InvalidationService
from src.services.narration_duration_sync_service import (
    sync_real_narration_durations,
    voice_matches_scenes,
)
from tests.test_content_intelligence_pipeline import _job_with_script
from tests.test_scene_merge import _script, _segment

_LINES = (
    "The door was open. It had been locked. Nobody had a key. The room was cold. "
    "A lamp still burned. The bed was made. A letter lay on the floor. Its ink was fresh."
)


def _track(scene_number: int, seconds: float) -> AudioTrack:
    return AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=f"voice/{scene_number}.mp3",
        duration_seconds=seconds,
        status=AudioTrackStatus.READY,
        metadata={"scene_number": scene_number},
    )


def _state(job: VideoJob, scene_number: int) -> SceneAssetState:
    scene = next(s for s in job.scenes if s.scene_number == scene_number)

    return SceneAssetState(
        scene_id=str(scene.id),
        scene_number=scene_number,
        status=AssetWorkflowStatus.READY,
    )


def _clip(scene_number: int) -> VideoClip:
    return VideoClip(
        scene_number=scene_number,
        source_type=SceneSourceType.AI_GENERATE,
        duration_seconds=8,
        local_file=f"clips/{scene_number}.mp4",
        status=VideoClipStatus.READY,
    )


def _planned_job():  # type: ignore[no-untyped-def]
    pipeline, job = _job_with_script()
    job.generated_script = _script(_segment(1, 0, 60, _LINES), genre_id=job.genre_id)
    job = pipeline.run_scene_planning(job)

    return pipeline, job


def _voiced(job: VideoJob) -> None:
    job.audio_timeline = AudioTimeline(
        tracks=[_track(s.scene_number, 1.8 + s.scene_number) for s in job.scenes]
    )
    sync_real_narration_durations(job, overwrite=True)
    job.voice_file = "voice/all.mp3"
    job.scene_asset_states = [_state(job, s.scene_number) for s in job.scenes]
    job.video_clips = [_clip(s.scene_number) for s in job.scenes]


def test_planning_again_with_the_same_result_changes_nothing() -> None:
    pipeline, job = _planned_job()
    _voiced(job)
    states = len(job.scene_asset_states)

    pipeline.run_scene_planning(job)

    assert len(job.scene_asset_states) == states
    assert len(job.video_clips) == states
    assert not InvalidationService.is_stale(job, "audio_timeline")
    assert all(s.real_narration_duration_seconds is not None for s in job.scenes)


def test_merging_drops_records_of_changed_scenes_and_marks_the_voice_stale() -> None:
    pipeline, job = _planned_job()
    _voiced(job)
    before = len(job.scenes)

    pipeline.set_scene_merge(job, enabled=True, keep_beats=True)
    pipeline.run_scene_planning(job)

    assert len(job.scenes) < before
    assert InvalidationService.is_stale(job, "audio_timeline")
    assert InvalidationService.is_stale(job, "video_timeline") is False  # none existed
    numbers = {s.scene_number for s in job.scenes}
    assert {st.scene_number for st in job.scene_asset_states} <= numbers
    assert {c.scene_number for c in job.video_clips} <= numbers
    # The job still validates: no record points at a scene that is gone.
    VideoJob.model_validate(job.model_dump())


def test_the_old_voice_is_not_copied_onto_the_merged_scenes() -> None:
    pipeline, job = _planned_job()
    _voiced(job)

    pipeline.set_scene_merge(job, enabled=True, keep_beats=True)
    pipeline.run_scene_planning(job)
    sync_real_narration_durations(job)
    sync_real_narration_durations(job, overwrite=True)

    assert all(s.real_narration_duration_seconds is None for s in job.scenes)


def test_a_job_already_stamped_with_a_voice_for_more_scenes_is_healed() -> None:
    """The Haunted wife state: 19 voice tracks, 10 merged scenes, old lengths already on them."""

    _pipeline, job = _planned_job()
    job.audio_timeline = AudioTimeline(
        tracks=[_track(n, 2.0) for n in range(1, len(job.scenes) + 6)]
    )
    for scene in job.scenes:
        scene.real_narration_duration_seconds = 1.8

    assert voice_matches_scenes(job) is False
    sync_real_narration_durations(job)

    assert all(s.real_narration_duration_seconds is None for s in job.scenes)


def test_a_voice_that_fits_the_scenes_is_still_read() -> None:
    _pipeline, job = _planned_job()
    _voiced(job)

    assert voice_matches_scenes(job) is True
    assert all(s.real_narration_duration_seconds for s in job.scenes)


def test_a_fresh_voice_replaces_the_stale_flag_and_is_read_again() -> None:
    pipeline, job = _planned_job()
    _voiced(job)
    pipeline.set_scene_merge(job, enabled=True, keep_beats=True)
    pipeline.run_scene_planning(job)
    assert voice_matches_scenes(job) is False

    job.audio_timeline = AudioTimeline(
        tracks=[_track(s.scene_number, 5.0) for s in job.scenes]
    )
    InvalidationService.clear_stale(job, "audio_timeline")
    sync_real_narration_durations(job, overwrite=True)

    assert all(s.real_narration_duration_seconds == 5.0 for s in job.scenes)
