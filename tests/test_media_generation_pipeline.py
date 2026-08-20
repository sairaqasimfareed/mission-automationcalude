from __future__ import annotations

import pytest

from src.models.audio_generation_summary import AudioComponentStatus
from src.models.audio_track import AudioTrackType
from src.models.editorial_critique import (
    CriticFinding,
    EditorialCritique,
    FindingSeverity,
)
from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.manual_audio_requirement import ManualAudioRequirementType
from src.models.media_strategy import SceneSourceStatus, SceneSourceType, VoiceStatus
from src.models.scene import Scene, SceneStatus
from src.models.story_blueprint import StoryBeatType
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_job import VideoJob
from src.models.voice_profile import VoiceProfile
from src.providers.dry_run_music_provider import DryRunMusicProvider
from src.providers.dry_run_sound_effect_provider import DryRunSoundEffectProvider
from src.providers.dry_run_voice_provider import DryRunVoiceProvider
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.genre_voice_directive_generation_service import (
    GenreVoiceDirectiveGenerationService,
)
from src.services.media_generation_pipeline import MediaGenerationPipeline
from src.services.music_generation_service import MusicGenerationService
from src.services.script_version_service import ScriptVersionService
from src.services.sound_effect_generation_service import SoundEffectGenerationService
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_resolution_runtime import VoiceResolutionRuntimeFactory
from src.services.voice_timeline_service import VoiceTimelineService

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _neutral_voice_profile() -> VoiceProfile:
    return VoiceProfile(
        profile_id="voice.neutral_narrator",
        display_name="Neutral Narrator",
        fallback_profile_id=None,
    )


def _pipeline(
    *, with_music: bool = True, with_sound_effects: bool = True
) -> MediaGenerationPipeline:
    voice_resolution_runtime = VoiceResolutionRuntimeFactory().build(
        profiles=[_neutral_voice_profile()]
    )

    return MediaGenerationPipeline(
        voice_directive_generation_service=GenreVoiceDirectiveGenerationService(
            genre_registry=_GENRE_REGISTRY,
            voice_profile_registry=voice_resolution_runtime.voice_profile_registry,
        ),
        voice_resolution_runtime=voice_resolution_runtime,
        voice_generation_service=VoiceGenerationService(
            providers=[DryRunVoiceProvider()]
        ),
        voice_timeline_service=VoiceTimelineService(),
        genre_timeline_service=GenreTimelinePipelineService(
            genre_directive_service=GenreDirectiveGenerationService(
                genre_registry=_GENRE_REGISTRY
            ),
            directive_resolution_service=EditingDirectiveResolutionService(
                effect_registry=EffectRegistryService.with_default_presets()
            ),
        ),
        music_generation_service=(
            MusicGenerationService(providers=[DryRunMusicProvider()])
            if with_music
            else None
        ),
        sound_effect_generation_service=(
            SoundEffectGenerationService(providers=[DryRunSoundEffectProvider()])
            if with_sound_effects
            else None
        ),
    )


def _scene(number: int, duration: int = 8) -> Scene:
    return Scene(
        scene_number=number,
        title=f"Scene {number}",
        narration=f"Narration for scene {number}.",
        visual_prompt=f"Visual prompt for scene {number}.",
        estimated_duration_seconds=duration,
        status=SceneStatus.READY,
    )


def _clip(number: int, duration: int = 8) -> VideoClip:
    return VideoClip(
        scene_number=number,
        source_type=SceneSourceType.MANUAL_UPLOAD,
        duration_seconds=duration,
        prompt=f"Scene {number}",
        provider="Manual Upload",
        local_file=f"assets/videos/manual/scene_{number:03}.mp4",
        source_status=SceneSourceStatus.READY,
        status=VideoClipStatus.READY,
    )


def _job(*scenes: Scene, genre_id: str = "genre.mystery") -> VideoJob:
    job = VideoJob(
        project_name="ocean-project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
        genre_id=genre_id,
    )
    job.scenes = list(scenes)

    return job


def test_run_voice_requires_scenes() -> None:
    with pytest.raises(RuntimeError, match="requires planned scenes"):
        _pipeline().run_voice(_job())


def test_run_voice_populates_audio_timeline_and_status() -> None:
    job = _job(_scene(1), _scene(2))

    result = _pipeline().run_voice(job)

    assert result.voice_status == VoiceStatus.READY
    assert result.voice_file is not None
    assert result.audio_timeline is not None
    voice_tracks = [
        track
        for track in result.audio_timeline.tracks
        if track.track_type == AudioTrackType.VOICEOVER
    ]
    assert len(voice_tracks) == 2


def test_run_timeline_requires_scenes() -> None:
    with pytest.raises(RuntimeError, match="requires planned scenes"):
        _pipeline().run_timeline(_job())


def test_run_timeline_requires_video_clips() -> None:
    job = _job(_scene(1))

    with pytest.raises(RuntimeError, match="requires resolved video clips"):
        _pipeline().run_timeline(job)


def test_run_timeline_builds_a_video_timeline() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]

    result = _pipeline().run_timeline(job)

    assert result.video_timeline is not None
    assert len(result.video_timeline.items) == 2


def test_run_music_requires_a_configured_provider() -> None:
    job = _job(_scene(1))
    job.video_clips = [_clip(1)]
    pipeline = _pipeline(with_music=False)
    pipeline.run_timeline(job)

    with pytest.raises(RuntimeError, match="No music provider"):
        pipeline.run_music(job)


def test_run_music_requires_a_built_timeline() -> None:
    job = _job(_scene(1))

    with pytest.raises(RuntimeError, match="requires a built video timeline"):
        _pipeline().run_music(job)


def test_run_music_attaches_one_background_track() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()
    pipeline.run_timeline(job)

    result = pipeline.run_music(job)

    assert result.audio_timeline is not None
    music_tracks = [
        track
        for track in result.audio_timeline.tracks
        if track.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]
    assert len(music_tracks) == 1


def test_run_sound_effects_requires_a_configured_provider() -> None:
    job = _job(_scene(1))
    job.video_clips = [_clip(1)]
    pipeline = _pipeline(with_sound_effects=False)
    pipeline.run_timeline(job)

    with pytest.raises(RuntimeError, match="No sound-effect provider"):
        pipeline.run_sound_effects(job)


def test_run_sound_effects_requires_a_built_timeline() -> None:
    job = _job(_scene(1))

    with pytest.raises(RuntimeError, match="requires a built video timeline"):
        _pipeline().run_sound_effects(job)


def test_run_sound_effects_attaches_cues() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()
    pipeline.run_timeline(job)

    result = pipeline.run_sound_effects(job)

    assert result.audio_timeline is not None
    sound_effect_tracks = [
        track
        for track in result.audio_timeline.tracks
        if track.track_type == AudioTrackType.SOUND_EFFECT
    ]
    assert len(sound_effect_tracks) > 0


def test_full_sequence_produces_a_multi_track_audio_timeline() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()

    pipeline.run_voice(job)
    pipeline.run_timeline(job)
    pipeline.run_music(job)
    pipeline.run_sound_effects(job)

    assert job.audio_timeline is not None
    track_types = {track.track_type for track in job.audio_timeline.tracks}
    assert track_types == {
        AudioTrackType.VOICEOVER,
        AudioTrackType.BACKGROUND_MUSIC,
        AudioTrackType.SOUND_EFFECT,
    }


def _generated_script() -> GeneratedScript:
    return GeneratedScript(
        topic="Test topic",
        genre_id="genre.mystery",
        target_duration_seconds=30,
        segments=[
            ScriptSegment(
                segment_number=1,
                start_seconds=0,
                end_seconds=30,
                narrative_function=StoryBeatType.HOOK,
                narration="Something happens.",
                tension_level=60,
            )
        ],
        prompt_version="script_generation_prompt_v1.0.0",
    )


def test_run_all_audio_generates_every_component_from_scratch() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()

    summary = pipeline.run_all_audio(job)

    statuses = {result.component: result.status for result in summary.results}
    assert statuses == {
        "voice": AudioComponentStatus.GENERATED,
        "timeline": AudioComponentStatus.GENERATED,
        "music": AudioComponentStatus.GENERATED,
        "sound_effects": AudioComponentStatus.GENERATED,
    }
    assert summary.all_succeeded


def test_run_all_audio_reuses_a_still_valid_voiceover() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()
    pipeline.run_voice(job)
    voice_file_before = job.voice_file

    summary = pipeline.run_all_audio(job)

    voice_result = next(r for r in summary.results if r.component == "voice")
    assert voice_result.status == AudioComponentStatus.REUSED
    assert job.voice_file == voice_file_before


def test_run_all_audio_reuses_everything_on_a_second_call() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()
    pipeline.run_all_audio(job)

    summary = pipeline.run_all_audio(job)

    statuses = {result.status for result in summary.results}
    assert statuses == {AudioComponentStatus.REUSED}


def test_run_all_audio_regenerates_voice_after_a_script_revision() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()

    version_service = ScriptVersionService()
    job.script_version_history = version_service.start_history(
        topic="Test topic", script=_generated_script()
    )

    pipeline.run_voice(job)
    assert job.voice_script_version == 1

    critique = EditorialCritique(
        topic="Test topic",
        prompt_version="critique_prompt_v1.0.0",
        dimension_scores={"narrative_coherence": 50},
        findings=[
            CriticFinding(
                dimension="narrative_coherence",
                severity=FindingSeverity.MAJOR,
                segment_number=1,
                problem="Something is wrong.",
                reason="It matters.",
                recommended_correction="Fix it.",
            )
        ],
    )
    job.script_version_history = version_service.add_revision(
        history=job.script_version_history,
        revised_script=_generated_script(),
        critique=critique,
    )

    summary = pipeline.run_all_audio(job)

    voice_result = next(r for r in summary.results if r.component == "voice")
    assert voice_result.status == AudioComponentStatus.GENERATED
    assert job.voice_script_version == 2


def test_run_all_audio_records_a_manual_requirement_when_no_music_provider() -> None:
    job = _job(_scene(1))
    job.video_clips = [_clip(1)]
    pipeline = _pipeline(with_music=False)

    summary = pipeline.run_all_audio(job)

    music_result = next(r for r in summary.results if r.component == "music")
    assert music_result.status == AudioComponentStatus.MANUAL_REQUIRED
    assert len(job.manual_audio_requirements) == 1
    assert (
        job.manual_audio_requirements[0].requirement_type
        == ManualAudioRequirementType.MUSIC
    )
    assert not summary.all_succeeded


def test_run_all_audio_does_not_duplicate_a_manual_requirement_on_repeat_calls() -> (
    None
):
    job = _job(_scene(1))
    job.video_clips = [_clip(1)]
    pipeline = _pipeline(with_music=False)

    pipeline.run_all_audio(job)
    pipeline.run_all_audio(job)

    assert len(job.manual_audio_requirements) == 1


def test_run_voice_twice_replaces_rather_than_duplicates_tracks() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()

    pipeline.run_voice(job)
    pipeline.run_voice(job)

    assert job.audio_timeline is not None
    voice_tracks = [
        track
        for track in job.audio_timeline.tracks
        if track.track_type == AudioTrackType.VOICEOVER
    ]
    assert len(voice_tracks) == 2  # one per scene, not four


def test_run_music_twice_replaces_rather_than_duplicates_the_track() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()
    pipeline.run_timeline(job)

    pipeline.run_music(job)
    pipeline.run_music(job)

    assert job.audio_timeline is not None
    music_tracks = [
        track
        for track in job.audio_timeline.tracks
        if track.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]
    assert len(music_tracks) == 1


def test_run_sound_effects_twice_replaces_rather_than_duplicates_cues() -> None:
    job = _job(_scene(1), _scene(2))
    job.video_clips = [_clip(1), _clip(2)]
    pipeline = _pipeline()
    pipeline.run_timeline(job)

    pipeline.run_sound_effects(job)
    first_count = len(
        [
            t
            for t in job.audio_timeline.tracks  # type: ignore[union-attr]
            if t.track_type == AudioTrackType.SOUND_EFFECT
        ]
    )
    pipeline.run_sound_effects(job)
    second_count = len(
        [
            t
            for t in job.audio_timeline.tracks  # type: ignore[union-attr]
            if t.track_type == AudioTrackType.SOUND_EFFECT
        ]
    )

    assert first_count > 0
    assert second_count == first_count


def test_run_all_audio_reports_failures_individually_without_raising() -> None:
    job = _job()  # no scenes, no video clips
    pipeline = _pipeline()

    summary = pipeline.run_all_audio(job)  # must not raise

    assert len(summary.results) == 4
    voice_result = next(r for r in summary.results if r.component == "voice")
    timeline_result = next(r for r in summary.results if r.component == "timeline")
    assert voice_result.status == AudioComponentStatus.FAILED
    assert timeline_result.status == AudioComponentStatus.FAILED
    assert not summary.all_succeeded
