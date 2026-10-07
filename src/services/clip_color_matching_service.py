"""Shot-to-shot colour matching: bring the generated clips toward one shared look.

Each generated clip comes back with its own exposure and colour (live, 2026-10-07:
Remedy's bright daylight clip between dark, warm kitchen ones). This measures every
live-action clip's brightness, saturation and warmth, takes the middle of them as the
video's typical look, and gives each clip a mild, bounded correction toward it - kept on
the clip and applied at render when the project has colour matching on.

It nudges, it does not re-grade: no clip moves further than the limits in
`ColorCorrection`, so a clip that is very different ends up closer but not identical.
Graphic scenes (infographics) are left alone - their colours are designed, not shot.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

from src.models.color_correction import (
    MAX_BRIGHTNESS_SHIFT,
    MAX_CHANNEL_GAIN_SHIFT,
    MAX_SATURATION,
    MIN_SATURATION,
    ColorCorrection,
)
from src.models.media_strategy import SceneSourceType
from src.models.video_clip import VideoClip
from src.models.video_job import VideoJob
from src.services.project_look_suggestion_service import measure_frame
from src.services.reference_frame_selection_service import SampledFrame
from src.services.scene_visual_treatment import renders_as_graphic
from src.shared.logger import logger

_FRAMES_PER_CLIP = 3
# How much of the gap to the typical look is closed: 1.0 would force every clip to match
# exactly, which flattens deliberate differences (a night scene is meant to be darker).
_STRENGTH = 0.7
# At least this many measurable clips are needed to say what "typical" is.
_MIN_CLIPS = 3

FrameSampler = Callable[[str, int], list[SampledFrame]]


def _default_sampler(video_path: str, count: int) -> list[SampledFrame]:
    from src.services.reference_frame_selection_service import _read_sample_frames

    return _read_sample_frames(video_path, count)


@dataclass(frozen=True)
class ClipColorStats:
    brightness: float
    saturation: float
    warmth: float


@dataclass(frozen=True)
class ColorMatchingEntry:
    scene_number: int
    clip_sequence_index: int
    correction: ColorCorrection | None
    note: str


@dataclass(frozen=True)
class ColorMatchingReport:
    entries: list[ColorMatchingEntry] = field(default_factory=list)
    measured: int = 0
    skipped_graphic: int = 0
    reason: str = ""

    @property
    def corrected_count(self) -> int:
        return sum(1 for entry in self.entries if entry.correction is not None)

    def text(self) -> str:
        if self.reason:
            return self.reason

        head = (
            f"Measured {self.measured} clip(s); {self.corrected_count} brought closer to "
            "the video's typical look, the rest were already close."
        )

        if self.skipped_graphic:
            head += f" {self.skipped_graphic} graphic scene(s) left alone."

        lines = [
            f"Scene {entry.scene_number}: {entry.note}"
            for entry in self.entries
            if entry.correction is not None
        ]

        return head + ("\n" + "\n".join(lines) if lines else "")


class ClipColorMatchingService:
    def __init__(self, *, frame_sampler: FrameSampler | None = None) -> None:
        self._sample = frame_sampler or _default_sampler

    # ------------------------------------------------------------------ public

    def match(self, job: VideoJob) -> ColorMatchingReport:
        """Measure the clips and store each one's correction on `job.video_clips`
        (None when it already sits with the others). Mutates the job - run it on a copy
        off the GUI thread and bring the corrections back with `apply_to`."""

        eligible, skipped_graphic = self._eligible_clips(job)

        if len(eligible) < _MIN_CLIPS:
            self.clear(job)

            return ColorMatchingReport(
                reason=(
                    f"Colour matching needs at least {_MIN_CLIPS} generated live-action "
                    f"clips to compare; there are {len(eligible)}."
                ),
                skipped_graphic=skipped_graphic,
            )

        stats: dict[tuple[int, int], ClipColorStats] = {}

        for clip in eligible:
            measured = self._measure_clip(clip)

            if measured is not None:
                stats[(clip.scene_number, clip.clip_sequence_index)] = measured

        if len(stats) < _MIN_CLIPS:
            self.clear(job)

            return ColorMatchingReport(
                reason="Fewer than three clips could be read, so nothing was changed.",
                measured=len(stats),
                skipped_graphic=skipped_graphic,
            )

        target = ClipColorStats(
            brightness=median(s.brightness for s in stats.values()),
            saturation=median(s.saturation for s in stats.values()),
            warmth=median(s.warmth for s in stats.values()),
        )
        entries: list[ColorMatchingEntry] = []

        self.clear(job)

        for clip in sorted(
            eligible, key=lambda c: (c.scene_number, c.clip_sequence_index)
        ):
            clip_stats = stats.get((clip.scene_number, clip.clip_sequence_index))

            if clip_stats is None:
                continue

            correction = self.correction_for(clip_stats, target)

            if correction.is_identity:
                continue

            clip.color_correction = correction
            entries.append(
                ColorMatchingEntry(
                    clip.scene_number,
                    clip.clip_sequence_index,
                    correction,
                    describe(correction),
                )
            )

        return ColorMatchingReport(
            entries=entries, measured=len(stats), skipped_graphic=skipped_graphic
        )

    @staticmethod
    def clear(job: VideoJob) -> None:
        for clip in job.video_clips:
            clip.color_correction = None

    @staticmethod
    def apply_to(job: VideoJob, matched: VideoJob) -> None:
        """Bring the corrections measured on a copy back onto the real job."""

        corrections = {
            (clip.scene_number, clip.clip_sequence_index): clip.color_correction
            for clip in matched.video_clips
        }

        for clip in job.video_clips:
            clip.color_correction = corrections.get(
                (clip.scene_number, clip.clip_sequence_index)
            )

    @staticmethod
    def correction_for(
        stats: ClipColorStats, target: ClipColorStats
    ) -> ColorCorrection:
        brightness = _clamp(
            (target.brightness - stats.brightness) / 255.0 * _STRENGTH,
            -MAX_BRIGHTNESS_SHIFT,
            MAX_BRIGHTNESS_SHIFT,
        )
        saturation = (
            _clamp(
                1.0 + (target.saturation / stats.saturation - 1.0) * _STRENGTH,
                MIN_SATURATION,
                MAX_SATURATION,
            )
            if stats.saturation >= 10.0
            else 1.0
        )
        shift = _clamp(
            (target.warmth - stats.warmth) / 255.0 * _STRENGTH * 0.5,
            -MAX_CHANNEL_GAIN_SHIFT,
            MAX_CHANNEL_GAIN_SHIFT,
        )

        return ColorCorrection(
            brightness=round(brightness, 4),
            saturation=round(saturation, 4),
            red_gain=round(1.0 + shift, 4),
            blue_gain=round(1.0 - shift, 4),
        )

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _eligible_clips(job: VideoJob) -> tuple[list[VideoClip], int]:
        bible = job.visual_continuity_bible
        plan = job.cinematic_shot_plan
        scenes = {scene.scene_number: scene for scene in job.scenes}
        eligible: list[VideoClip] = []
        skipped_graphic = 0

        for clip in job.video_clips:
            if (
                clip.source_type != SceneSourceType.AI_GENERATE
                or not clip.local_file
                or not Path(clip.local_file).is_file()
            ):
                continue

            scene = scenes.get(clip.scene_number)

            if scene is not None and renders_as_graphic(
                scene=scene,
                entry=bible.entry_for_scene(scene.scene_number) if bible else None,
                shot=plan.shot_for_scene(scene.scene_number) if plan else None,
            ):
                skipped_graphic += 1
                continue

            eligible.append(clip)

        return eligible, skipped_graphic

    def _measure_clip(self, clip: VideoClip) -> ClipColorStats | None:
        try:
            frames = self._sample(clip.local_file or "", _FRAMES_PER_CLIP)
        except Exception as error:  # noqa: BLE001 - one unreadable clip is not fatal
            logger.warning(
                "Measuring scene %s for colour matching failed: %s",
                clip.scene_number,
                type(error).__name__,
            )

            return None

        measured = [
            m for m in (measure_frame(f.image) for f in frames) if m is not None
        ]

        if not measured:
            return None

        return ClipColorStats(
            brightness=sum(m[0] for m in measured) / len(measured),
            saturation=sum(m[1] for m in measured) / len(measured),
            warmth=sum(m[2] for m in measured) / len(measured),
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def describe(correction: ColorCorrection) -> str:
    """The correction in plain words, e.g. "9% darker, a little less colourful"."""

    parts: list[str] = []
    percent = round(abs(correction.brightness) * 100)

    if percent >= 1:
        parts.append(
            f"{percent}% {'brighter' if correction.brightness > 0 else 'darker'}"
        )

    if correction.saturation < 0.97:
        parts.append("a little less colourful")
    elif correction.saturation > 1.03:
        parts.append("a little more colourful")

    if correction.red_gain - correction.blue_gain > 0.01:
        parts.append("slightly warmer")
    elif correction.blue_gain - correction.red_gain > 0.01:
        parts.append("slightly cooler")

    return ", ".join(parts) or "a very small change"
