from __future__ import annotations

from uuid import uuid4

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.enums import Platform
from src.models.genre_profile import GenreSEOProfile, GenreThumbnailProfile
from src.models.render_result import RenderResult, RenderStatus
from src.models.scene import Scene, SceneStatus
from src.models.video_timeline import VideoTimeline
from src.models.voice_generation import (
    VoiceGenerationFailure,
    VoiceGenerationFailureReason,
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.services.seo.seo_context_builder import SEOContext
from src.services.top10_countdown_service import Top10CountdownService


class _FakeImageGenerationService:
    def __init__(self, *, image_file: str) -> None:
        self._image_file = image_file
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        context: SEOContext,
        *,
        width: int,
        height: int,
        selected_seo_title: str | None = None,
    ) -> str:
        self.calls.append(
            {"width": width, "height": height, "selected_seo_title": selected_seo_title}
        )

        return self._image_file


class _FakeNumberingVoiceoverService:
    def __init__(self, *, result_by_rank: dict[int, VoiceGenerationResult]) -> None:
        self._result_by_rank = result_by_rank
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        *,
        rank: int,
        voice_profile_id: str,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        self.calls.append(
            {
                "rank": rank,
                "voice_profile_id": voice_profile_id,
                "provider_name": provider_name,
            }
        )

        return self._result_by_rank[rank]


class _FakeRankCardRenderService:
    def __init__(self, *, result_by_rank: dict[int, RenderResult]) -> None:
        self._result_by_rank = result_by_rank
        self.calls: list[dict[str, object]] = []

    def build(self, *, rank: int, **kwargs: object) -> RenderResult:
        self.calls.append({"rank": rank, **kwargs})

        return self._result_by_rank[rank]


class _FakeProductionRenderService:
    def __init__(self, *, result: RenderResult) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def render_top10_countdown(self, **kwargs: object) -> RenderResult:
        self.calls.append(kwargs)

        return self._result


def _seo_context() -> SEOContext:
    return SEOContext(
        video_job_id=uuid4(),
        topic="Top 10 unit test items.",
        niche="top10",
        genre_id="genre.top10",
        target_audience="General audience.",
        target_country="US",
        language="English",
        language_code="en",
        platform=Platform.YOUTUBE,
        script_title="Top 10 Unit Test",
        script_content="Full narration text.",
        research_summary="Real research summary.",
        key_facts=["Fact one."],
        scene_count=2,
        estimated_duration_seconds=60,
        genre_seo_profile=GenreSEOProfile(),
        genre_thumbnail_profile=GenreThumbnailProfile(),
    )


def _scenes() -> list[Scene]:
    return [
        Scene(
            scene_number=1,
            title="Hook",
            narration="Welcome.",
            visual_prompt="A hook shot.",
            estimated_duration_seconds=5,
            status=SceneStatus.READY,
            list_rank=None,
        ),
        Scene(
            scene_number=2,
            title="Rank ten item",
            narration="Number ten.",
            visual_prompt="A reveal shot.",
            estimated_duration_seconds=5,
            status=SceneStatus.READY,
            list_rank=10,
        ),
    ]


def _voice_success(*, rank: int, output_file: str) -> VoiceGenerationResult:
    return VoiceGenerationResult(
        success=True,
        scene_number=rank,
        status=VoiceGenerationStatus.COMPLETED,
        output_file=output_file,
        audio_track=AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file=output_file,
            duration_seconds=1.0,
            status=AudioTrackStatus.READY,
        ),
    )


def _voice_failure(*, rank: int) -> VoiceGenerationResult:
    return VoiceGenerationResult(
        success=False,
        scene_number=rank,
        status=VoiceGenerationStatus.FAILED,
        failure=VoiceGenerationFailure(
            reason=VoiceGenerationFailureReason.NO_PROVIDER_AVAILABLE,
            message="No compatible voice provider is available.",
        ),
    )


def _card_success(*, output_file: str) -> RenderResult:
    return RenderResult(
        success=True,
        output_file=output_file,
        render_engine="ffmpeg",
        duration_seconds=2,
        status=RenderStatus.COMPLETED,
    )


def _final_success(*, output_file: str = "/tmp/final_countdown.mp4") -> RenderResult:
    return RenderResult(
        success=True,
        output_file=output_file,
        render_engine="ffmpeg",
        duration_seconds=12,
        status=RenderStatus.COMPLETED,
    )


def test_build_generates_one_card_per_rank_then_splices_via_countdown_render() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/bg.png")

    voiceover_service = _FakeNumberingVoiceoverService(
        result_by_rank={10: _voice_success(rank=10, output_file="/tmp/number10.wav")}
    )

    card_service = _FakeRankCardRenderService(
        result_by_rank={10: _card_success(output_file="/tmp/rank10.mp4")}
    )

    production_render_service = _FakeProductionRenderService(result=_final_success())

    service = Top10CountdownService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        numbering_voiceover_service=voiceover_service,  # type: ignore[arg-type]
        rank_card_render_service=card_service,  # type: ignore[arg-type]
        production_render_service=production_render_service,  # type: ignore[arg-type]
    )

    result = service.build(
        scenes=_scenes(),
        video_timeline=VideoTimeline(clips=[], items=[]),
        audio_timeline=AudioTimeline(tracks=[]),
        voice_blueprints=[],
        seo_context=_seo_context(),
        voice_profile_id="voice.neutral_narrator",
        output_file="/tmp/final_countdown.mp4",
    )

    assert result.success is True
    assert result.output_file == "/tmp/final_countdown.mp4"

    assert len(card_service.calls) == 1
    assert card_service.calls[0]["rank"] == 10
    assert card_service.calls[0]["background_image_file"] == "/tmp/bg.png"
    assert card_service.calls[0]["voiceover_file"] == "/tmp/number10.wav"

    render_call = production_render_service.calls[0]
    assert render_call["rank_by_scene_number"] == {2: 10}

    rank_card_results = render_call["rank_card_results"]
    assert isinstance(rank_card_results, dict)
    assert rank_card_results[10].output_file == "/tmp/rank10.mp4"


def test_image_override_skips_generation() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/generated.png")

    voiceover_service = _FakeNumberingVoiceoverService(
        result_by_rank={10: _voice_success(rank=10, output_file="/tmp/number10.wav")}
    )

    card_service = _FakeRankCardRenderService(
        result_by_rank={10: _card_success(output_file="/tmp/rank10.mp4")}
    )

    service = Top10CountdownService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        numbering_voiceover_service=voiceover_service,  # type: ignore[arg-type]
        rank_card_render_service=card_service,  # type: ignore[arg-type]
        production_render_service=_FakeProductionRenderService(  # type: ignore[arg-type]
            result=_final_success()
        ),
    )

    service.build(
        scenes=_scenes(),
        video_timeline=VideoTimeline(clips=[], items=[]),
        audio_timeline=AudioTimeline(tracks=[]),
        voice_blueprints=[],
        seo_context=_seo_context(),
        voice_profile_id="voice.neutral_narrator",
        output_file="/tmp/final_countdown.mp4",
        image_override="/tmp/manual.png",
    )

    assert image_service.calls == []
    assert card_service.calls[0]["background_image_file"] == "/tmp/manual.png"


def test_voiceover_disabled_skips_generation_and_passes_none_to_the_card() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/bg.png")

    voiceover_service = _FakeNumberingVoiceoverService(result_by_rank={})

    card_service = _FakeRankCardRenderService(
        result_by_rank={10: _card_success(output_file="/tmp/rank10.mp4")}
    )

    service = Top10CountdownService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        numbering_voiceover_service=voiceover_service,  # type: ignore[arg-type]
        rank_card_render_service=card_service,  # type: ignore[arg-type]
        production_render_service=_FakeProductionRenderService(  # type: ignore[arg-type]
            result=_final_success()
        ),
    )

    result = service.build(
        scenes=_scenes(),
        video_timeline=VideoTimeline(clips=[], items=[]),
        audio_timeline=AudioTimeline(tracks=[]),
        voice_blueprints=[],
        seo_context=_seo_context(),
        voice_profile_id="voice.neutral_narrator",
        output_file="/tmp/final_countdown.mp4",
        include_numbering_voiceover=False,
    )

    assert result.success is True
    assert voiceover_service.calls == []
    assert card_service.calls[0]["voiceover_file"] is None
    assert card_service.calls[0]["voiceover_duration_seconds"] is None


def test_voiceover_generation_failure_raises_rather_than_degrading() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/bg.png")

    voiceover_service = _FakeNumberingVoiceoverService(
        result_by_rank={10: _voice_failure(rank=10)}
    )

    card_service = _FakeRankCardRenderService(result_by_rank={})

    service = Top10CountdownService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        numbering_voiceover_service=voiceover_service,  # type: ignore[arg-type]
        rank_card_render_service=card_service,  # type: ignore[arg-type]
        production_render_service=_FakeProductionRenderService(  # type: ignore[arg-type]
            result=_final_success()
        ),
    )

    try:
        service.build(
            scenes=_scenes(),
            video_timeline=VideoTimeline(clips=[], items=[]),
            audio_timeline=AudioTimeline(tracks=[]),
            voice_blueprints=[],
            seo_context=_seo_context(),
            voice_profile_id="voice.neutral_narrator",
            output_file="/tmp/final_countdown.mp4",
        )

        raise AssertionError("Expected a ValueError for the failed voiceover.")
    except ValueError as error:
        assert "rank 10" in str(error)

    assert card_service.calls == []


def test_card_render_failure_short_circuits_before_countdown_render_is_called() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/bg.png")

    voiceover_service = _FakeNumberingVoiceoverService(
        result_by_rank={10: _voice_success(rank=10, output_file="/tmp/number10.wav")}
    )

    failed_card = RenderResult(
        success=False,
        output_file=None,
        render_engine="ffmpeg",
        duration_seconds=0,
        status=RenderStatus.FAILED,
        error_message="Simulated card render failure.",
    )

    card_service = _FakeRankCardRenderService(result_by_rank={10: failed_card})

    production_render_service = _FakeProductionRenderService(result=_final_success())

    service = Top10CountdownService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        numbering_voiceover_service=voiceover_service,  # type: ignore[arg-type]
        rank_card_render_service=card_service,  # type: ignore[arg-type]
        production_render_service=production_render_service,  # type: ignore[arg-type]
    )

    result = service.build(
        scenes=_scenes(),
        video_timeline=VideoTimeline(clips=[], items=[]),
        audio_timeline=AudioTimeline(tracks=[]),
        voice_blueprints=[],
        seo_context=_seo_context(),
        voice_profile_id="voice.neutral_narrator",
        output_file="/tmp/final_countdown.mp4",
    )

    assert result.success is False
    assert production_render_service.calls == []


def test_no_ranked_scenes_raises_before_any_generation_call() -> None:
    image_service = _FakeImageGenerationService(image_file="/tmp/bg.png")
    voiceover_service = _FakeNumberingVoiceoverService(result_by_rank={})
    card_service = _FakeRankCardRenderService(result_by_rank={})

    service = Top10CountdownService(
        image_generation_service=image_service,  # type: ignore[arg-type]
        numbering_voiceover_service=voiceover_service,  # type: ignore[arg-type]
        rank_card_render_service=card_service,  # type: ignore[arg-type]
        production_render_service=_FakeProductionRenderService(  # type: ignore[arg-type]
            result=_final_success()
        ),
    )

    unranked_scene = Scene(
        scene_number=1,
        title="Hook",
        narration="Welcome.",
        visual_prompt="A hook shot.",
        estimated_duration_seconds=5,
        status=SceneStatus.READY,
        list_rank=None,
    )

    try:
        service.build(
            scenes=[unranked_scene],
            video_timeline=VideoTimeline(clips=[], items=[]),
            audio_timeline=AudioTimeline(tracks=[]),
            voice_blueprints=[],
            seo_context=_seo_context(),
            voice_profile_id="voice.neutral_narrator",
            output_file="/tmp/final_countdown.mp4",
        )

        raise AssertionError("Expected a ValueError for zero ranked scenes.")
    except ValueError as error:
        assert "list_rank" in str(error)

    assert image_service.calls == []
    assert card_service.calls == []
