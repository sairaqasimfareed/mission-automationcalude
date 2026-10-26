"""
Audio-tab audio realignment, 2026-10-03: the Audio tab places voice end to end
(no video exists yet) and reads sound-effect/music positions off the video
timeline's nominal starts, ignoring crossfade shrinkage. On a real 18-scene
project the voice ended up 11s behind the picture (Muse) or 9s ahead (Flow) by
the last scene. The render now moves those tracks onto the real scene starts.
"""

from __future__ import annotations

import pytest

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackStatus, AudioTrackType
from src.models.media_strategy import SceneSourceStatus, SceneSourceType
from src.models.render_result import SceneRenderTiming
from src.models.scene import Scene
from src.models.sound_design_plan import MusicMoodSegment, SoundDesignPlan
from src.models.video_clip import VideoClip, VideoClipStatus
from src.models.video_timeline import VideoTimeline
from src.services.audio_realignment_service import (
    BASIS_NOMINAL,
    BASIS_REAL,
    BASIS_SEQUENTIAL,
    POSITION_BASIS_KEY,
    mark_position_basis,
    realign_audio_to_scene_timings,
)
from src.services.editing_directive_resolution_service import (
    EditingDirectiveResolutionService,
)
from src.services.effect_registry_service import EffectRegistryService
from src.services.genre_directive_generation_service import (
    GenreDirectiveGenerationService,
)
from src.services.genre_profile_registry_service import GenreProfileRegistryService
from src.services.genre_timeline_pipeline_service import GenreTimelinePipelineService
from src.services.production_render_service import ProductionRenderService

_REGISTRY = GenreProfileRegistryService.with_default_profiles()


def _track(
    track_type: AudioTrackType,
    start: float,
    duration: float,
    *,
    scene_number: int | None = None,
    basis: str | None = None,
    **metadata: object,
) -> AudioTrack:
    track = AudioTrack(
        track_type=track_type,
        source_file="a.mp3",
        start_time_seconds=start,
        duration_seconds=duration,
        status=AudioTrackStatus.READY,
        metadata={
            **({} if scene_number is None else {"scene_number": scene_number}),
            **metadata,
        },
    )

    if basis is not None:
        mark_position_basis(track, basis)

    return track


def _timings(*pairs: tuple[int, float, float]) -> list[SceneRenderTiming]:
    return [
        SceneRenderTiming(scene_number=n, start_seconds=s, end_seconds=e)
        for n, s, e in pairs
    ]


def _video(*spans: tuple[int, float, float]) -> VideoTimeline:
    """A real VideoTimeline whose items start at the nominal (uncorrected) spans."""

    scenes = [
        Scene(
            scene_number=n,
            title=f"S{n}",
            narration=f"N{n}.",
            visual_prompt=f"V{n}.",
            # The script's own estimate (never below 4s), as in a real project -
            # NOT the clip length: the editing rules compare transitions to this.
            estimated_duration_seconds=max(4, int(round(e - s))),
        )
        for n, s, e in spans
    ]
    clips = [
        VideoClip(
            scene_number=n,
            source_type=SceneSourceType.MANUAL_UPLOAD,
            duration_seconds=max(1, int(round(e - s))),
            prompt=f"s{n}",
            provider="Manual Upload",
            local_file=f"clips/{n}.mp4",
            source_status=SceneSourceStatus.READY,
            status=VideoClipStatus.READY,
        )
        for n, s, e in spans
    ]
    result = GenreTimelinePipelineService(
        genre_directive_service=GenreDirectiveGenerationService(
            genre_registry=_REGISTRY
        ),
        directive_resolution_service=EditingDirectiveResolutionService(
            effect_registry=EffectRegistryService.with_default_presets()
        ),
    ).build(scenes=scenes, clips=clips, genre_id="genre.medical")

    return result.timeline


class TestVoice:
    def _three_scenes(self) -> tuple[AudioTimeline, VideoTimeline]:
        timeline = AudioTimeline(
            tracks=[
                _track(
                    AudioTrackType.VOICEOVER,
                    0.0,
                    8.0,
                    scene_number=1,
                    basis=BASIS_SEQUENTIAL,
                ),
                _track(
                    AudioTrackType.VOICEOVER,
                    8.0,
                    4.0,
                    scene_number=2,
                    basis=BASIS_SEQUENTIAL,
                ),
                _track(
                    AudioTrackType.VOICEOVER,
                    12.0,
                    6.0,
                    scene_number=3,
                    basis=BASIS_SEQUENTIAL,
                ),
            ]
        )

        return timeline, _video((1, 0, 8), (2, 8, 12), (3, 12, 18))

    def test_flagged_voice_moves_onto_each_scenes_real_start(self) -> None:
        timeline, video = self._three_scenes()

        moved = realign_audio_to_scene_timings(
            timeline,
            video_timeline=video,
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 11.4), (3, 10.8, 16.8)),
        )

        assert moved == 2  # scene 1 already sat at its real start
        assert [t.start_time_seconds for t in timeline.tracks] == [0.0, 7.4, 10.8]
        assert all(
            t.metadata[POSITION_BASIS_KEY] == BASIS_REAL for t in timeline.tracks
        )

    def test_it_is_idempotent(self) -> None:
        timeline, video = self._three_scenes()
        timings = _timings((1, 0.0, 8.0), (2, 7.4, 11.4), (3, 10.8, 16.8))

        realign_audio_to_scene_timings(
            timeline, video_timeline=video, scene_timings=timings
        )
        again = realign_audio_to_scene_timings(
            timeline, video_timeline=video, scene_timings=timings
        )

        assert again == 0
        assert [t.start_time_seconds for t in timeline.tracks] == [0.0, 7.4, 10.8]

    def test_voice_flagged_real_follows_a_scene_that_moved(self) -> None:
        """A position that was real for an earlier render's clips goes stale when a clip changes."""

        timeline = AudioTimeline(
            tracks=[
                _track(
                    AudioTrackType.VOICEOVER, 0.0, 8.0, scene_number=1, basis=BASIS_REAL
                ),
                _track(
                    AudioTrackType.VOICEOVER, 7.4, 4.0, scene_number=2, basis=BASIS_REAL
                ),
            ]
        )

        moved = realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 12)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 99.0, 103.0)),
        )

        assert moved == 1
        assert timeline.tracks[1].start_time_seconds == 99.0

    def test_an_unflagged_end_to_end_voiceover_is_treated_as_the_audio_tabs(
        self,
    ) -> None:
        """A voiceover generated before the flag existed (exactly end to end)."""

        timeline = AudioTimeline(
            tracks=[
                _track(AudioTrackType.VOICEOVER, 0.0, 8.0, scene_number=1),
                _track(AudioTrackType.VOICEOVER, 8.0, 4.0, scene_number=2),
            ]
        )

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 12)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 11.4)),
        )

        assert timeline.tracks[1].start_time_seconds == 7.4

    def test_an_unflagged_voiceover_with_gaps_also_goes_to_the_real_starts(
        self,
    ) -> None:
        """The voice of a scene always starts where its scene starts."""

        timeline = AudioTimeline(
            tracks=[
                _track(AudioTrackType.VOICEOVER, 0.0, 8.0, scene_number=1),
                _track(AudioTrackType.VOICEOVER, 7.4, 4.0, scene_number=2),
            ]
        )

        moved = realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 12)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 50.0, 54.0)),
        )

        assert moved == 1
        assert timeline.tracks[1].start_time_seconds == 50.0

    def test_a_scene_missing_from_the_timings_is_left_alone(self) -> None:
        timeline, video = self._three_scenes()

        realign_audio_to_scene_timings(
            timeline, video_timeline=video, scene_timings=_timings((1, 0.0, 8.0))
        )

        assert [t.start_time_seconds for t in timeline.tracks] == [0.0, 8.0, 12.0]
        assert timeline.tracks[1].metadata[POSITION_BASIS_KEY] == BASIS_SEQUENTIAL

    def test_no_timings_changes_nothing(self) -> None:
        timeline, video = self._three_scenes()

        assert (
            realign_audio_to_scene_timings(
                timeline, video_timeline=video, scene_timings=[]
            )
            == 0
        )
        assert timeline.tracks[2].start_time_seconds == 12.0


class TestSoundEffects:
    def test_the_offset_inside_the_scene_is_kept(self) -> None:
        video = _video((1, 0, 8), (2, 8, 14))
        sfx = _track(
            AudioTrackType.SOUND_EFFECT, 10.0, 2.0, scene_number=2, basis=BASIS_NOMINAL
        )  # 2s into scene 2 (nominal start 8.0)
        timeline = AudioTimeline(tracks=[sfx])

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=video,
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 13.4)),
        )

        assert sfx.start_time_seconds == pytest.approx(9.4)  # real start 7.4 + 2.0

    def test_the_offset_is_clamped_to_the_real_scene_length(self) -> None:
        video = _video((1, 0, 8), (2, 8, 14))
        sfx = _track(
            AudioTrackType.SOUND_EFFECT, 14.0, 1.0, scene_number=2, basis=BASIS_NOMINAL
        )  # at the nominal END of scene 2
        timeline = AudioTimeline(tracks=[sfx])

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=video,
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 13.4)),
        )

        assert sfx.start_time_seconds == pytest.approx(13.4)

    def test_an_unflagged_effect_is_not_guessed_at(self) -> None:
        sfx = _track(AudioTrackType.SOUND_EFFECT, 10.0, 2.0, scene_number=2)
        timeline = AudioTimeline(tracks=[sfx])

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 14)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 13.4)),
        )

        assert sfx.start_time_seconds == 10.0


class TestMusic:
    def _plan_and_track(self) -> tuple[SoundDesignPlan, AudioTrack]:
        segment = MusicMoodSegment(
            start_scene_number=2,
            end_scene_number=3,
            mood_description="warm piano",
            rationale="r",
        )
        track = _track(
            AudioTrackType.BACKGROUND_MUSIC,
            8.0,
            10.0,
            basis=BASIS_NOMINAL,
            sound_design_segment_id=str(segment.id),
        )

        return SoundDesignPlan(sfx_cues=[], music_segments=[segment]), track

    def test_a_segment_spans_its_scenes_real_range(self) -> None:
        plan, track = self._plan_and_track()
        timeline = AudioTimeline(tracks=[track])

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 12), (3, 12, 18)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 11.4), (3, 10.8, 16.8)),
            sound_design_plan=plan,
        )

        assert track.start_time_seconds == pytest.approx(7.4)
        assert track.duration_seconds == pytest.approx(16.8 - 7.4)

    def test_without_the_plan_a_segment_track_is_left_alone(self) -> None:
        _plan, track = self._plan_and_track()
        timeline = AudioTimeline(tracks=[track])

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 12), (3, 12, 18)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 7.4, 11.4), (3, 10.8, 16.8)),
        )

        assert track.start_time_seconds == 8.0


def test_voice_lands_exactly_on_the_real_scene_starts_for_a_realistic_project() -> None:
    """
    The measured case: 18 scenes, Muse-style exact-narration clips, 0.6s
    crossfades. Before this fix the last scene's voice was 11s late; it must
    land on the same real starts the render itself computes.
    """

    narration = [
        7.66, 1.07, 7.66, 7.76, 1.76, 7.38, 1.39, 4.32, 6.92,
        2.37, 5.99, 6.87, 3.3, 2.46, 4.97, 8.36, 2.65, 2.69,
    ]  # fmt: skip

    start = 0.0
    tracks = []

    for number, seconds in enumerate(narration, start=1):
        tracks.append(
            _track(
                AudioTrackType.VOICEOVER,
                start,
                seconds,
                scene_number=number,
                basis=BASIS_SEQUENTIAL,
            )
        )
        start += seconds

    clip_spans = []
    nominal = 0.0

    for number, seconds in enumerate(narration, start=1):
        length = float(max(1, round(seconds)))
        clip_spans.append((number, nominal, nominal + length))
        nominal += length

    video = _video(*clip_spans)
    real = ProductionRenderService._compute_real_scene_timings(
        video_timeline=video,
        transition_duration_seconds=_REGISTRY.resolve(
            "genre.medical"
        ).profile.editing.default_transition_duration_seconds,
    )
    timeline = AudioTimeline(tracks=tracks)

    before = max(
        abs(t.start_time_seconds - r.start_seconds)
        for t, r in zip(tracks, real, strict=True)
    )

    realign_audio_to_scene_timings(timeline, video_timeline=video, scene_timings=real)

    for track, timing in zip(tracks, real, strict=True):
        assert track.start_time_seconds == pytest.approx(timing.start_seconds)

    assert before > 5.0  # it really was badly out before


class TestClipsChangedSinceTheLastRender:
    """Live, 2026-10-20: clips regenerated, cut and held after a render moved every later scene, but the
    voice kept the positions of that render - up to 16 s ahead of the picture."""

    def test_voice_and_its_sound_effect_follow_the_scene(self) -> None:
        voice_1 = _track(
            AudioTrackType.VOICEOVER, 0.0, 10.3, scene_number=1, basis=BASIS_REAL
        )
        voice_2 = _track(
            AudioTrackType.VOICEOVER, 6.3, 8.9, scene_number=2, basis=BASIS_REAL
        )
        sfx_2 = _track(
            AudioTrackType.SOUND_EFFECT, 7.3, 1.0, scene_number=2, basis=BASIS_REAL
        )  # 1 s into scene 2, which used to start at 6.3
        timeline = AudioTimeline(tracks=[voice_1, voice_2, sfx_2])

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 13), (2, 13, 23)),
            scene_timings=_timings((1, 0.0, 13.0), (2, 11.6, 21.6)),
        )

        assert voice_2.start_time_seconds == pytest.approx(11.6)
        assert sfx_2.start_time_seconds == pytest.approx(12.6)

    def test_a_second_pass_with_the_same_timings_changes_nothing(self) -> None:
        voice = _track(
            AudioTrackType.VOICEOVER, 6.3, 8.9, scene_number=2, basis=BASIS_REAL
        )
        sfx = _track(
            AudioTrackType.SOUND_EFFECT, 7.3, 1.0, scene_number=2, basis=BASIS_REAL
        )
        timeline = AudioTimeline(tracks=[voice, sfx])
        timings = _timings((1, 0.0, 13.0), (2, 11.6, 21.6))
        video = _video((1, 0, 13), (2, 13, 23))

        realign_audio_to_scene_timings(
            timeline, video_timeline=video, scene_timings=timings
        )
        second = realign_audio_to_scene_timings(
            timeline, video_timeline=video, scene_timings=timings
        )

        assert second == 0
        assert sfx.start_time_seconds == pytest.approx(12.6)


class TestEffectsFollowThePlan:
    """Live, 2026-10-20: the stamp meant for the visual-only scene 9 stayed at 57.4 s, under scene 8's voice."""

    def _plan(self, **cue_fields: object):  # type: ignore[no-untyped-def]
        from src.models.editing_directives import DirectiveTimingMode
        from src.models.sound_design_plan import SoundEffectCueDirective

        cue = SoundEffectCueDirective(
            scene_number=2,
            generation_prompt="A heavy rubber stamp striking paper.",
            rationale="a stamp on paper",
            timing_mode=DirectiveTimingMode.ABSOLUTE_SECONDS,
            **cue_fields,  # type: ignore[arg-type]
        )

        return cue, SoundDesignPlan(sfx_cues=[cue], music_segments=[])

    def test_an_effect_at_a_percentage_lands_that_far_into_the_scenes_real_span(
        self,
    ) -> None:
        cue, plan = self._plan(relative_position_percent=40.0)
        sfx = _track(
            AudioTrackType.SOUND_EFFECT,
            57.4,
            2.0,
            scene_number=2,
            basis=BASIS_REAL,
            sound_design_cue_id=str(cue.id),
        )

        realign_audio_to_scene_timings(
            AudioTimeline(tracks=[sfx]),
            video_timeline=_video((1, 0, 8), (2, 8, 18)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 61.7, 66.7)),
            sound_design_plan=plan,
        )

        assert sfx.start_time_seconds == pytest.approx(61.7 + 0.4 * 5.0)

    def test_a_scene_start_effect_goes_to_the_start_of_the_scene(self) -> None:
        from src.models.editing_directives import DirectiveTimingMode

        cue, plan = self._plan()
        cue.timing_mode = DirectiveTimingMode.SCENE_START
        sfx = _track(
            AudioTrackType.SOUND_EFFECT,
            16.9,
            0.5,
            scene_number=2,
            basis=BASIS_REAL,
            sound_design_cue_id=str(cue.id),
        )

        realign_audio_to_scene_timings(
            AudioTimeline(tracks=[sfx]),
            video_timeline=_video((1, 0, 8), (2, 8, 18)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 20.9, 27.9)),
            sound_design_plan=plan,
        )

        # the crossfade into a scene takes 0.7 s, so the effect starts once it is over
        assert sfx.start_time_seconds == pytest.approx(20.9 + 0.7)


class TestMinimumGapBetweenLines:
    """Live, 2026-10-25 (Radium): the silence between two lines was anything from 0.5 s to 4.5 s,
    because every clip is rounded to 4/6/8/10 s and the next picture starts at the crossfade.
    """

    def _voices(self) -> AudioTimeline:
        return AudioTimeline(
            tracks=[
                _track(AudioTrackType.VOICEOVER, 0.0, 6.0, scene_number=1),
                _track(AudioTrackType.VOICEOVER, 0.0, 8.0, scene_number=2),
                _track(AudioTrackType.VOICEOVER, 0.0, 3.0, scene_number=3),
            ]
        )

    def _starts(self, timeline: AudioTimeline) -> list[float]:
        return [round(t.start_time_seconds, 2) for t in timeline.tracks]

    def test_without_a_gap_every_voice_stays_on_its_scene_start(self) -> None:
        timeline = self._voices()

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 18), (3, 18, 24)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 6.3, 16.3), (3, 15.6, 22.6)),
        )

        assert self._starts(timeline) == [0.0, 6.3, 15.6]

    def test_a_voice_that_would_start_too_soon_after_the_last_line_is_started_a_little_later(
        self,
    ) -> None:
        timeline = self._voices()

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 18), (3, 18, 24)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 6.3, 16.3), (3, 15.6, 22.6)),
            minimum_voice_gap_seconds=1.0,
        )

        # line 1 ends at 6.0, line 2 would start at 6.3 -> 7.0 would be needed, but a voice is
        # never delayed by more than half a second
        assert self._starts(timeline)[:2] == [0.0, 6.8]
        # line 2 ends at 14.8; line 3 starts at 15.6, which is already 0.8 later -> 15.8 (a 1.0 gap)
        assert self._starts(timeline)[2] == 15.8

    def test_a_voice_is_never_pushed_past_the_end_of_its_own_scene(self) -> None:
        timeline = AudioTimeline(
            tracks=[
                _track(AudioTrackType.VOICEOVER, 0.0, 6.0, scene_number=1),
                _track(AudioTrackType.VOICEOVER, 0.0, 9.8, scene_number=2),
            ]
        )

        realign_audio_to_scene_timings(
            timeline,
            video_timeline=_video((1, 0, 8), (2, 8, 18)),
            scene_timings=_timings((1, 0.0, 8.0), (2, 6.3, 16.3)),
            minimum_voice_gap_seconds=1.0,
        )

        # the scene has only 10 s and the line is 9.8 s: at most 0.2 s of delay fits
        assert self._starts(timeline)[1] == 6.5

    def test_running_it_twice_changes_nothing(self) -> None:
        timeline = self._voices()
        kwargs = {
            "video_timeline": _video((1, 0, 8), (2, 8, 18), (3, 18, 24)),
            "scene_timings": _timings((1, 0.0, 8.0), (2, 6.3, 16.3), (3, 15.6, 22.6)),
            "minimum_voice_gap_seconds": 1.0,
        }

        realign_audio_to_scene_timings(timeline, **kwargs)
        first = self._starts(timeline)

        assert realign_audio_to_scene_timings(timeline, **kwargs) == 0
        assert self._starts(timeline) == first


def test_the_render_never_asks_for_more_than_half_a_second_between_lines() -> None:
    from src.pipeline.render_stage import _MAXIMUM_VOICE_GAP_SECONDS

    assert _MAXIMUM_VOICE_GAP_SECONDS == 0.5
