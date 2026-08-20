from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from uuid import uuid4  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from src.desktop.job_store import InMemoryJobStore  # noqa: E402
from src.desktop.views.production_audio_view import ProductionAudioView  # noqa: E402
from src.models.audio_generation_summary import AudioComponentStatus  # noqa: E402
from src.models.media_strategy import (  # noqa: E402
    SceneSourceStatus,
    SceneSourceType,
    VoiceStatus,
)
from src.models.scene import Scene, SceneStatus  # noqa: E402
from src.models.video_clip import VideoClip, VideoClipStatus  # noqa: E402
from src.models.video_job import VideoJob  # noqa: E402
from src.models.voice_profile import VoiceProfile  # noqa: E402
from src.providers.dry_run_music_provider import DryRunMusicProvider  # noqa: E402
from src.providers.dry_run_sound_effect_provider import (  # noqa: E402
    DryRunSoundEffectProvider,
)
from src.providers.dry_run_voice_provider import DryRunVoiceProvider  # noqa: E402
from src.services.editing_directive_resolution_service import (  # noqa: E402
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService  # noqa: E402
from src.services.genre_directive_generation_service import (  # noqa: E402
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import (  # noqa: E402
    GenreProfileRegistryService,
)
from src.services.genre_timeline_pipeline_service import (  # noqa: E402
    GenreTimelinePipelineService,
)
from src.services.genre_voice_directive_generation_service import (  # noqa: E402
    GenreVoiceDirectiveGenerationService,
)
from src.services.media_generation_pipeline import MediaGenerationPipeline  # noqa: E402
from src.services.music_generation_service import MusicGenerationService  # noqa: E402
from src.services.sound_effect_generation_service import (  # noqa: E402
    SoundEffectGenerationService,
)
from src.services.voice_generation_service import VoiceGenerationService  # noqa: E402
from src.services.voice_resolution_runtime import (  # noqa: E402
    VoiceResolutionRuntimeFactory,
)
from src.services.voice_timeline_service import VoiceTimelineService  # noqa: E402

_GENRE_REGISTRY = GenreProfileRegistryService.with_default_profiles()


@pytest.fixture(scope="module")
def qapp() -> Iterator[QApplication]:
    app = QApplication.instance() or QApplication([])

    yield app  # type: ignore[misc]


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.desktop.views.production_audio_view.show_recoverable_error",
        lambda *args, **kwargs: None,
    )


def _pipeline() -> MediaGenerationPipeline:
    voice_resolution_runtime = VoiceResolutionRuntimeFactory().build(
        profiles=[
            VoiceProfile(
                profile_id="voice.neutral_narrator",
                display_name="Neutral Narrator",
                fallback_profile_id=None,
            )
        ]
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
        music_generation_service=MusicGenerationService(
            providers=[DryRunMusicProvider()]
        ),
        sound_effect_generation_service=SoundEffectGenerationService(
            providers=[DryRunSoundEffectProvider()]
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


def _job(*, with_scenes: bool = True, with_clips: bool = False) -> VideoJob:
    job = VideoJob(
        project_name="Mary Celeste Documentary",
        channel_name="Maritime Mysteries",
        niche="unsolved maritime disappearances",
        topic="The Mary Celeste",
        genre_id="genre.mystery",
    )

    if with_scenes:
        job.scenes = [_scene(1), _scene(2)]

    if with_clips:
        job.video_clips = [_clip(1), _clip(2)]

    return job


def _view(job_store: InMemoryJobStore) -> ProductionAudioView:
    return ProductionAudioView(
        job_store=job_store,
        media_generation_pipeline=_pipeline(),
        on_change=lambda: None,
    )


def _button(view: ProductionAudioView, text_fragment: str) -> QPushButton:
    QApplication.processEvents()

    matches = [
        button
        for button in view.findChildren(QPushButton)
        if text_fragment in button.text()
    ]

    return matches[-1]


def test_voice_button_enabled_only_with_scenes(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=False)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    assert _button(view, "Generate voiceover").isEnabled() is False


def test_timeline_button_requires_scenes_and_clips(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True, with_clips=False)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    assert _button(view, "Build editing timeline").isEnabled() is False


def test_running_voice_populates_job_and_refreshes(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_voice()

    assert job.voice_status == VoiceStatus.READY
    assert job.audio_timeline is not None


def test_running_the_full_sequence_produces_a_complete_audio_timeline(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True, with_clips=True)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_voice()
    view.refresh(job)
    view._handle_run_timeline()
    view.refresh(job)
    view._handle_run_music()
    view.refresh(job)
    view._handle_run_sound_effects()
    view.refresh(job)

    assert job.video_timeline is not None
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) >= 3
    assert not job.errors


def test_running_music_before_timeline_records_an_error_not_a_crash(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_music()

    assert len(job.errors) == 1
    assert "Music generation failed" in job.errors[0]


def test_unknown_job_id_does_not_crash_generation_handlers(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)
    view.set_job(uuid4())

    view._handle_run_voice()  # must not raise


def test_all_audio_button_enabled_only_with_scenes_and_clips(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True, with_clips=False)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    assert _button(view, "Generate all audio").isEnabled() is False


def test_running_all_audio_generates_everything_in_one_action(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True, with_clips=True)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_all_audio()

    assert job.video_timeline is not None
    assert job.audio_timeline is not None
    assert len(job.audio_timeline.tracks) >= 3
    assert not job.errors
    assert view._last_audio_summary is not None
    assert view._last_audio_summary.all_succeeded

    view.refresh(job)  # must not raise with a summary now present


def test_running_all_audio_twice_reuses_on_the_second_call(
    qapp: QApplication,
) -> None:
    job_store = InMemoryJobStore()
    job = _job(with_scenes=True, with_clips=True)
    job_store.add(job)

    view = _view(job_store)
    view.set_job(job.id)
    view.refresh(job)

    view._handle_run_all_audio()
    view._handle_run_all_audio()

    assert view._last_audio_summary is not None
    statuses = {r.status for r in view._last_audio_summary.results}
    assert statuses == {AudioComponentStatus.REUSED}


def test_unknown_job_id_does_not_crash_run_all_audio(qapp: QApplication) -> None:
    job_store = InMemoryJobStore()
    view = _view(job_store)
    view.set_job(uuid4())

    view._handle_run_all_audio()  # must not raise
