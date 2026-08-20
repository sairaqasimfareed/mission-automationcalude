from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.media_strategy import SceneSourceType, VoiceStatus
from src.models.render_result import RenderResult
from src.models.research import ResearchResult, ResearchStatus
from src.models.scene import Scene
from src.models.script import Script, ScriptStatus
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.invalidation_service import InvalidationService


def _job(**overrides: object) -> VideoJob:
    base: dict[str, object] = dict(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    base.update(overrides)
    return VideoJob(**base)


def _research() -> ResearchResult:
    return ResearchResult(
        topic="Test topic",
        research_summary="Summary.",
        prompt_version="v1",
        status=ResearchStatus.APPROVED,
    )


def _script() -> Script:
    return Script(
        title="Test script",
        content="Hello world.",
        prompt_version="v1",
        status=ScriptStatus.APPROVED,
    )


def _scene() -> Scene:
    return Scene(
        scene_number=1,
        title="Scene one",
        narration="Something happens.",
        visual_prompt="A dark hallway.",
        estimated_duration_seconds=8,
    )


def _video_clips() -> list[VideoClip]:
    return [
        VideoClip(
            scene_number=1,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=5,
            local_file="clip.mp4",
        )
    ]


def _job_with_timeline(**overrides: object) -> VideoJob:
    """A job with a real video_timeline, satisfying every upstream
    cross-field validator VideoJob enforces along the way."""

    base: dict[str, object] = dict(
        research=_research(),
        script=_script(),
        scenes=[_scene()],
        video_clips=_video_clips(),
        video_timeline=VideoTimeline(),
    )
    base.update(overrides)

    if "render_result" in base and "audio_timeline" not in base:
        base["voice_status"] = VoiceStatus.READY
        base["voice_file"] = "voice.mp3"
        base["audio_timeline"] = AudioTimeline()

    return _job(**base)


def test_on_script_changed_marks_only_fields_that_currently_have_a_value() -> None:
    job = _job_with_timeline()
    service = InvalidationService()

    records = service.on_script_changed(job)

    artifacts = {r.artifact for r in records}
    assert artifacts == {"scenes", "video_clips", "video_timeline"}
    assert job.stale_artifacts == records


def test_on_script_changed_is_a_noop_when_nothing_downstream_exists() -> None:
    job = _job()
    service = InvalidationService()

    records = service.on_script_changed(job)

    assert records == []
    assert job.stale_artifacts == []


def test_on_script_changed_does_not_duplicate_an_existing_stale_record() -> None:
    job = _job_with_timeline()
    service = InvalidationService()

    service.on_script_changed(job)
    second_call_records = service.on_script_changed(job)

    assert second_call_records == []
    assert len(job.stale_artifacts) == 3


def test_on_scene_replaced_marks_video_timeline_and_render_result() -> None:
    job = _job_with_timeline(render_result=RenderResult(render_engine="ffmpeg"))
    service = InvalidationService()

    records = service.on_scene_replaced(job, scene_number=3)

    artifacts = {r.artifact for r in records}
    assert artifacts == {"video_timeline", "render_result"}
    assert all(r.triggered_by == "scene_replacement" for r in records)
    assert all("Scene 3" in r.reason for r in records)


def test_on_scene_replaced_never_flags_video_clips() -> None:
    # video_clips is deliberately excluded from the scene-replacement
    # matrix - SceneAssetVideoClipBuilderService rebuilds it
    # synchronously in the same call that triggers this invalidation,
    # so it's never actually stale by the time this runs.
    job = _job_with_timeline()
    service = InvalidationService()

    records = service.on_scene_replaced(job, scene_number=1)

    assert all(r.artifact != "video_clips" for r in records)


def test_on_audio_regenerated_marks_render_result() -> None:
    job = _job_with_timeline(render_result=RenderResult(render_engine="ffmpeg"))
    service = InvalidationService()

    records = service.on_audio_regenerated(job)

    artifacts = {r.artifact for r in records}
    assert artifacts == {"render_result"}
    assert all(r.triggered_by == "audio_regeneration" for r in records)


def test_on_audio_regenerated_never_flags_video_timeline() -> None:
    # video_timeline is deliberately excluded: GenreTimelinePipelineService
    # builds it purely from scenes/clips/genre_id and embeds no audio
    # data, so regenerating audio never actually makes an already-built
    # timeline stale.
    job = _job_with_timeline()
    service = InvalidationService()

    records = service.on_audio_regenerated(job)

    assert all(r.artifact != "video_timeline" for r in records)


def test_on_audio_regenerated_never_flags_audio_timeline_itself() -> None:
    job = _job(
        voice_status=VoiceStatus.READY,
        voice_file="voice.mp3",
        audio_timeline=AudioTimeline(),
    )
    service = InvalidationService()

    records = service.on_audio_regenerated(job)

    assert all(r.artifact != "audio_timeline" for r in records)


def test_is_stale_true_after_marking_and_false_before() -> None:
    job = _job_with_timeline()
    service = InvalidationService()

    assert InvalidationService.is_stale(job, "video_timeline") is False

    service.on_script_changed(job)

    assert InvalidationService.is_stale(job, "video_timeline") is True


def test_clear_stale_removes_only_the_named_artifact() -> None:
    job = _job_with_timeline(render_result=RenderResult(render_engine="ffmpeg"))
    service = InvalidationService()
    service.on_script_changed(job)
    service.on_scene_replaced(job, scene_number=1)

    service.clear_stale(job, "video_timeline")

    assert InvalidationService.is_stale(job, "video_timeline") is False
    assert InvalidationService.is_stale(job, "render_result") is True


def test_clear_stale_on_an_artifact_that_was_never_stale_is_a_noop() -> None:
    job = _job()
    service = InvalidationService()

    service.clear_stale(job, "video_timeline")  # must not raise

    assert job.stale_artifacts == []
