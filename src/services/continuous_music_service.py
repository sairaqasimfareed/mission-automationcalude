"""One continuous music track for the whole video.

Music used to be one short piece per planned mood (an ElevenLabs sound-generation clip of
18 s at most, looped to fill each scene range) joined with 1 s fades: seven separate
pieces for a 1:24 video, one of which faded to near-silence before its slot ended (live,
2026-10-07, Remedy). ElevenLabs' music composition endpoint makes one instrumental track of
up to 10 minutes from a description, so the planned moods become one description of how a
single piece should move, and the video gets one track.
"""

from __future__ import annotations

from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import AudioTrack, AudioTrackType
from src.models.resolved_editing_blueprint import (
    ResolvedMusicInstruction,
    ResolvedPresetReference,
)
from src.models.sound_design_plan import MusicMoodSegment, SoundDesignItemStatus
from src.models.video_job import VideoJob
from src.models.video_timeline import VideoTimeline
from src.services.music_generation_service import MusicGenerationService

# A mood's own words are cut to this many characters in the description, so seven or
# eight moods stay far inside the composition prompt limit.
_MOOD_CHARACTERS = 140
_MAX_PROMPT_CHARACTERS = 1800
# ElevenLabs composes 3 s to 10 min.
MIN_CONTINUOUS_SECONDS = 3.0
MAX_CONTINUOUS_SECONDS = 600.0

_FRAME = (
    "Instrumental background music for a narrated video: one continuous piece that "
    "flows without abrupt changes or stops, quiet and unobtrusive so a speaking voice "
    "stays clear on top, with no vocals."
)


def _clock(seconds: float) -> str:
    whole = int(round(seconds))

    return f"{whole // 60}:{whole % 60:02d}"


class ContinuousMusicService:
    """Builds the one description, asks for one track, and attaches it to the job."""

    def __init__(self, *, music_generation_service: MusicGenerationService) -> None:
        self._music = music_generation_service

    # ----------------------------------------------------------------- planning

    @staticmethod
    def total_seconds(
        timeline: VideoTimeline, transition_seconds: float = 0.0
    ) -> float:
        """The video's length: the timeline's, less the overlap each crossfade eats."""

        items = len(timeline.items)
        overlap = max(0, items - 1) * transition_seconds

        return max(0.0, timeline.calculate_duration() - overlap)

    @staticmethod
    def prompt_for(job: VideoJob, *, style_hint: str = "") -> str:
        """How the single piece should move: the genre's style, then each planned mood
        in order with the time it covers."""

        timeline = job.video_timeline
        plan = job.sound_design_plan
        parts = [_FRAME]

        if style_hint.strip():
            parts.append(f"Style: {' '.join(style_hint.split())[:200]}.")

        if plan is not None and plan.music_segments and timeline is not None:
            items = {item.scene_number: item for item in timeline.items}
            moves: list[str] = []

            for segment in sorted(
                plan.music_segments, key=lambda s: s.start_scene_number
            ):
                start = items.get(segment.start_scene_number)
                end = items.get(segment.end_scene_number)

                if start is None or end is None:
                    continue

                mood = " ".join(segment.mood_description.split())[:_MOOD_CHARACTERS]
                moves.append(
                    f"{_clock(start.start_time_seconds)}-{_clock(end.end_time_seconds)} "
                    f"{mood}"
                )

            if moves:
                parts.append(
                    "Over the video it moves gently through these moods, in order, "
                    "blending from one into the next: " + "; ".join(moves) + "."
                )

        parts.append("It ends gently.")

        return " ".join(parts)[:_MAX_PROMPT_CHARACTERS]

    # --------------------------------------------------------------- generating

    def generate(
        self,
        job: VideoJob,
        *,
        style_hint: str = "",
        provider_name: str | None = None,
        transition_seconds: float = 0.0,
    ) -> AudioTrack:
        """Compose the track. Raises RuntimeError with the reason when it cannot."""

        timeline = job.video_timeline

        if timeline is None:
            raise RuntimeError(
                "Music generation requires a built video timeline - run Timeline first."
            )

        seconds = self.total_seconds(timeline, transition_seconds)

        if not MIN_CONTINUOUS_SECONDS <= seconds <= MAX_CONTINUOUS_SECONDS:
            raise RuntimeError(
                "One continuous track can be 3 seconds to 10 minutes long; this video "
                f"is {seconds:.0f} seconds. Use separate pieces instead."
            )

        prompt = self.prompt_for(job, style_hint=style_hint)
        instruction = ResolvedMusicInstruction(
            preset=ResolvedPresetReference(
                directive_path="sound_design.continuous_music",
                requested_preset_id="content_aware.continuous",
                resolved_preset_id="content_aware.continuous",
                found_exact_match=False,
                implementation={"library_query": prompt, "loop": False},
            ),
            volume_percent=25.0,
            fade_in_seconds=1.0,
            fade_out_seconds=2.0,
            duck_under_voice=True,
            enabled=True,
        )
        result = self._music.generate(
            instruction,
            duration_seconds=seconds,
            provider_name=provider_name,
            composed=True,
        )

        if not result.success or result.audio_track is None:
            message = (
                result.failure.message
                if result.failure is not None
                else "Music generation failed without failure details."
            )

            raise RuntimeError(f"Continuous music generation failed: {message}")

        return result.audio_track.model_copy(
            update={
                "start_time_seconds": 0.0,
                "metadata": {**result.audio_track.metadata, "continuous": True},
            }
        )

    @staticmethod
    def attach(job: VideoJob, track: AudioTrack) -> None:
        """Make `track` the video's only background music and mark every planned mood
        as covered by it."""

        audio_timeline = job.audio_timeline or AudioTimeline()
        audio_timeline.tracks = [
            existing
            for existing in audio_timeline.tracks
            if existing.track_type != AudioTrackType.BACKGROUND_MUSIC
        ]
        audio_timeline.tracks.append(track)
        job.audio_timeline = audio_timeline

        if job.sound_design_plan is not None:
            segments: list[MusicMoodSegment] = job.sound_design_plan.music_segments

            for segment in segments:
                segment.status = SoundDesignItemStatus.GENERATED
                segment.audio_track_id = str(track.id)
