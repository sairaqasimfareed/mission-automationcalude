"""
One continuous music track (2026-10-07). Music used to be one short ElevenLabs
sound-generation clip per planned mood (18 s at most, looped), joined with fades - seven
pieces for a 1:24 video, one of which faded to near-silence before its slot ended. The
documented music composition endpoint (POST /v1/music, 3 s to 10 min) makes one track from
a description, so a project can now ask for one composed track for the whole video.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from src.models.audio_track import AudioTrack, AudioTrackType  # noqa: E402
from src.models.music_mode import MusicMode  # noqa: E402
from src.models.provider_profile import ProviderCategory, ProviderProfile  # noqa: E402
from src.models.sound_design_plan import (  # noqa: E402
    MusicMoodSegment,
    SoundDesignItemStatus,
    SoundDesignPlan,
)
from src.pipeline.music_stage import MusicPipelineStage  # noqa: E402
from src.pipeline.pipeline_stage import PipelineStageStatus  # noqa: E402
from src.providers.dry_run_music_provider import DryRunMusicProvider  # noqa: E402
from src.providers.elevenlabs_sound_generation_provider import (  # noqa: E402
    ElevenLabsMusicProvider,
)
from src.providers.music_provider import MusicProvider  # noqa: E402
from src.services.continuous_music_service import (  # noqa: E402
    ContinuousMusicService,
)
from src.services.http.http_provider_executor import (  # noqa: E402
    HttpTransportResponse,
    PreparedHttpRequest,
)
from src.services.music_generation_service import MusicGenerationService  # noqa: E402
from tests.test_music_stage import (  # noqa: E402
    FakeMusicProvider,
    _context,
    _job_with_timeline,
)


class _ComposingProvider(MusicProvider):
    """A provider that can compose a full-length track; records what it was asked."""

    def __init__(self) -> None:
        self.composed: list[tuple[str, float]] = []
        self.short_clips = 0

    @property
    def provider_name(self) -> str:
        return "composer"

    def health_check(self) -> bool:
        return True

    def generate_music(self, *, library_query: str, duration_seconds: float) -> str:
        self.short_clips += 1

        return "dry-run://music/short.mp3"

    def generate_composed_music(self, *, prompt: str, duration_seconds: float) -> str:
        self.composed.append((prompt, duration_seconds))

        return "dry-run://music/composed.mp3"


def _plan() -> SoundDesignPlan:
    return SoundDesignPlan(
        music_segments=[
            MusicMoodSegment(
                start_scene_number=1,
                end_scene_number=2,
                mood_description="calm, quiet piano",
                rationale="Opening.",
            ),
            MusicMoodSegment(
                start_scene_number=3,
                end_scene_number=3,
                mood_description="a little warmer, hopeful",
                rationale="The remedy.",
            ),
        ]
    )


def _job(scenes: int = 3, mode: MusicMode = MusicMode.CONTINUOUS):  # type: ignore[no-untyped-def]
    job = _job_with_timeline(scene_count=scenes, music_enabled=True)
    job.sound_design_plan = _plan()
    job.music_mode = mode

    return job


# ------------------------------------------------------------ the provider


class _Transport:
    def __init__(self, *, status: int = 200) -> None:
        self.requests: list[PreparedHttpRequest] = []
        self._status = status

    def __call__(self, request: PreparedHttpRequest) -> HttpTransportResponse:
        self.requests.append(request)

        return HttpTransportResponse(
            status_code=self._status, content=b"ID3-composed-audio", headers={}
        )


def _elevenlabs(tmp_path: Path, transport: _Transport) -> ElevenLabsMusicProvider:
    return ElevenLabsMusicProvider(
        profile=ProviderProfile(
            profile_id="eleven.music",
            display_name="Eleven music",
            provider_name="elevenlabs",
            category=ProviderCategory.MUSIC,
            secret_reference="ref",
        ),
        api_key="key",
        transport=transport,  # type: ignore[arg-type]
        output_directory=tmp_path,
    )


def test_elevenlabs_composes_one_track_from_the_music_endpoint(tmp_path: Path) -> None:
    transport = _Transport()
    provider = _elevenlabs(tmp_path, transport)

    path = provider.generate_composed_music(prompt="calm piano", duration_seconds=84.0)

    request = transport.requests[0]
    assert request.url.endswith("/v1/music")  # not /v1/sound-generation
    assert request.headers["xi-api-key"] == "key"
    assert request.json_body == {
        "prompt": "calm piano",
        "music_length_ms": 84000,
        "force_instrumental": True,
    }
    assert Path(path).read_bytes() == b"ID3-composed-audio"


@pytest.mark.parametrize("seconds", [2.0, 601.0])
def test_a_length_the_music_endpoint_cannot_make_is_refused_before_any_call(
    tmp_path: Path, seconds: float
) -> None:
    transport = _Transport()

    with pytest.raises(ValueError, match="between 3 seconds and 10 minutes"):
        _elevenlabs(tmp_path, transport).generate_composed_music(
            prompt="x", duration_seconds=seconds
        )

    assert transport.requests == []


def test_an_error_from_the_music_endpoint_is_reported(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="music composition"):
        _elevenlabs(tmp_path, _Transport(status=402)).generate_composed_music(
            prompt="x", duration_seconds=30.0
        )


def test_a_provider_that_only_makes_short_clips_says_so() -> None:
    provider = FakeMusicProvider()

    with pytest.raises(NotImplementedError, match="cannot compose"):
        provider.generate_composed_music(prompt="x", duration_seconds=30.0)


def test_the_dry_run_provider_can_compose() -> None:
    assert (
        DryRunMusicProvider()
        .generate_composed_music(prompt="x", duration_seconds=30.0)
        .startswith("dry-run://music/")
    )


# ---------------------------------------------------- the generation service


def _instruction():  # type: ignore[no-untyped-def]
    from src.models.resolved_editing_blueprint import (
        ResolvedMusicInstruction,
        ResolvedPresetReference,
    )

    return ResolvedMusicInstruction(
        preset=ResolvedPresetReference(
            directive_path="x",
            requested_preset_id="p",
            resolved_preset_id="p",
            found_exact_match=False,
            implementation={"library_query": "calm piano", "loop": True},
        ),
    )


def test_a_composed_track_is_one_unlooped_track_of_the_full_length() -> None:
    provider = _ComposingProvider()
    service = MusicGenerationService(providers=[provider])

    result = service.generate(_instruction(), duration_seconds=84.0, composed=True)

    assert result.success is True
    track = result.audio_track
    assert track is not None
    assert track.duration_seconds == 84.0
    assert track.loop_enabled is False  # even though the preset says "loop"
    assert provider.composed == [("calm piano", 84.0)]
    assert provider.short_clips == 0


def test_a_provider_that_cannot_compose_fails_with_a_reason_the_caller_can_use() -> (
    None
):
    service = MusicGenerationService(providers=[FakeMusicProvider()])

    result = service.generate(_instruction(), duration_seconds=84.0, composed=True)

    assert result.success is False
    assert result.failure is not None
    assert result.failure.reason == "composition_unsupported"


def test_without_composed_the_short_clip_path_is_exactly_as_before() -> None:
    provider = _ComposingProvider()
    service = MusicGenerationService(providers=[provider])

    result = service.generate(
        _instruction(), duration_seconds=18.0, track_duration_seconds=84.0
    )

    assert result.audio_track is not None
    assert result.audio_track.loop_enabled is True
    assert provider.short_clips == 1
    assert provider.composed == []


# ----------------------------------------------------------- the description


def test_the_description_lists_each_mood_with_the_time_it_covers() -> None:
    job = _job()

    prompt = ContinuousMusicService.prompt_for(job, style_hint="calm medical piano")

    assert prompt.startswith("Instrumental background music for a narrated video")
    assert "Style: calm medical piano." in prompt
    assert "0:00-0:16 calm, quiet piano" in prompt
    assert "0:16-0:24 a little warmer, hopeful" in prompt
    assert prompt.endswith("It ends gently.")


def test_without_a_sound_design_plan_the_description_is_just_the_style() -> None:
    job = _job()
    job.sound_design_plan = None

    prompt = ContinuousMusicService.prompt_for(job, style_hint="calm piano")

    assert "calm piano" in prompt
    assert "moods" not in prompt


def test_the_description_stays_inside_the_limit_however_many_moods() -> None:
    job = _job(scenes=8)
    job.sound_design_plan = SoundDesignPlan(
        music_segments=[
            MusicMoodSegment(
                start_scene_number=n,
                end_scene_number=n,
                mood_description="a very long description of a mood " * 10,
                rationale="x",
            )
            for n in range(1, 9)
        ]
    )

    assert len(ContinuousMusicService.prompt_for(job)) <= 1800


# --------------------------------------------------------------- the service


def test_the_service_asks_for_one_track_the_length_of_the_video() -> None:
    provider = _ComposingProvider()
    job = _job()
    service = ContinuousMusicService(
        music_generation_service=MusicGenerationService(providers=[provider])
    )

    track = service.generate(job, style_hint="calm piano")

    assert provider.composed[0][1] == 24.0  # 3 scenes of 8 s
    assert track.start_time_seconds == 0.0
    assert track.duration_seconds == 24.0
    assert track.metadata["continuous"] is True


def test_each_crossfade_shortens_the_track_by_its_overlap() -> None:
    provider = _ComposingProvider()
    job = _job()
    service = ContinuousMusicService(
        music_generation_service=MusicGenerationService(providers=[provider])
    )

    track = service.generate(job, transition_seconds=0.6)

    assert track.duration_seconds == pytest.approx(24.0 - 2 * 0.6)


def test_a_video_longer_than_the_endpoint_allows_is_refused_with_a_way_out() -> None:
    job = _job(scenes=80)  # 640 s
    service = ContinuousMusicService(
        music_generation_service=MusicGenerationService(
            providers=[_ComposingProvider()]
        )
    )

    with pytest.raises(RuntimeError, match="Use separate pieces"):
        service.generate(job)


def test_attaching_replaces_every_other_music_track_and_marks_the_moods_covered() -> (
    None
):
    job = _job()
    service = ContinuousMusicService(
        music_generation_service=MusicGenerationService(
            providers=[_ComposingProvider()]
        )
    )
    old = AudioTrack(
        track_type=AudioTrackType.BACKGROUND_MUSIC,
        source_file="old.mp3",
        duration_seconds=8.0,
    )
    voice = AudioTrack(
        track_type=AudioTrackType.VOICEOVER, source_file="v.mp3", duration_seconds=8.0
    )
    from src.models.audio_timeline import AudioTimeline

    job.audio_timeline = AudioTimeline(tracks=[old, voice])

    track = service.generate(job)
    service.attach(job, track)

    assert job.audio_timeline is not None
    music = [
        t
        for t in job.audio_timeline.tracks
        if t.track_type == AudioTrackType.BACKGROUND_MUSIC
    ]
    assert music == [track]
    assert voice in job.audio_timeline.tracks
    assert job.sound_design_plan is not None
    assert all(
        s.status == SoundDesignItemStatus.GENERATED
        and s.audio_track_id == str(track.id)
        for s in job.sound_design_plan.music_segments
    )


# ------------------------------------------------------------ the music stage


def test_the_stage_makes_one_track_in_continuous_mode() -> None:
    provider = _ComposingProvider()
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[provider])
    )
    job = _job()

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["continuous"] is True
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) == 1
    assert provider.short_clips == 0


def test_the_stage_falls_back_to_pieces_when_the_provider_cannot_compose() -> None:
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[FakeMusicProvider()])
    )
    job = _job()

    result = stage.execute(_context(job))

    assert result.status == PipelineStageStatus.COMPLETED
    assert result.metadata["attached_count"] == 2  # the two moods, as pieces
    assert any("separate pieces" in warning for warning in result.warnings)
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) == 2


def test_pieces_mode_never_asks_for_a_composed_track() -> None:
    provider = _ComposingProvider()
    stage = MusicPipelineStage(
        generation_service=MusicGenerationService(providers=[provider])
    )
    job = _job(mode=MusicMode.PIECES)

    stage.execute(_context(job))

    assert provider.composed == []
    assert provider.short_clips == 2


def test_a_project_saved_before_the_music_mode_existed_makes_pieces() -> None:
    from src.models.video_job import VideoJob

    data = _job(mode=MusicMode.PIECES).model_dump(mode="json")
    data.pop("music_mode")
    data.pop("sound_design_plan")  # keeps the reload free of timeline validation
    data.pop("video_timeline")
    data.pop("scenes")
    data.pop("video_clips")
    data.pop("audio_timeline", None)
    data.pop("script", None)
    data.pop("research", None)
    data.pop("voice_file", None)

    assert VideoJob.model_validate(data).music_mode == MusicMode.PIECES


# ------------------------------------------------- the Audio tab and the pipeline


def test_a_single_mood_cannot_be_regenerated_in_continuous_mode() -> None:
    from src.services.media_generation_pipeline import MediaGenerationPipeline

    pipeline: Any = MediaGenerationPipeline.__new__(MediaGenerationPipeline)
    pipeline.music_generation_service = MusicGenerationService(
        providers=[_ComposingProvider()]
    )
    job = _job()

    with pytest.raises(RuntimeError, match="one continuous track"):
        pipeline.generate_single_music_segment(
            job, str(job.sound_design_plan.music_segments[0].id)  # type: ignore[union-attr]
        )


# ------------------------------------------------------------------ the screens


def test_project_settings_offers_the_music_mode_and_saves_the_choice(qapp) -> None:  # type: ignore[no-untyped-def]
    from PySide6.QtWidgets import QComboBox, QPushButton

    from src.desktop.job_store import InMemoryJobStore
    from tests.test_content_studio_content_intelligence_gui import _job as studio_job
    from tests.test_content_studio_content_intelligence_gui import _view as studio_view

    store = InMemoryJobStore()
    job = studio_job()
    store.add(job)
    view = studio_view(store)
    view.set_job(job.id)
    view.refresh(job)

    combo = next(
        c
        for c in view.findChildren(QComboBox)
        if c.count() == 2
        and c.itemText(1) == "One continuous track for the whole video"
    )
    assert combo.currentData() == MusicMode.PIECES

    combo.setCurrentIndex(combo.findData(MusicMode.CONTINUOUS))
    next(
        b for b in view.findChildren(QPushButton) if b.text() == "Save settings"
    ).click()

    assert job.music_mode == MusicMode.CONTINUOUS


def test_generate_all_music_on_the_audio_tab_makes_the_one_track_in_continuous_mode(  # type: ignore[no-untyped-def]
    qapp,
) -> None:
    from tests.test_production_audio_view_generated_audio import _job as audio_job
    from tests.test_production_audio_view_generated_audio import _view as audio_view

    job = audio_job([])
    job.sound_design_plan = _plan()
    job.music_mode = MusicMode.CONTINUOUS
    view = audio_view(job)

    view._handle_generate_all_music(job)  # noqa: SLF001

    view._media_generation_pipeline.run_music.assert_called_once_with(
        job
    )  # noqa: SLF001
    view._media_generation_pipeline.generate_single_music_segment.assert_not_called()  # noqa: SLF001


from tests.test_content_studio_content_intelligence_gui import (  # noqa: E402
    qapp as qapp,  # noqa: PLC0414 - fixture
)
