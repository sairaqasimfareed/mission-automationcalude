"""Candidate project looks, so the operator picks one instead of writing it.

Two sources, both free and instant (no Claude call): ready-made looks for the
project's genre, and one measured from the clips already generated - how bright,
how saturated and how warm the footage the operator actually has is, written as
words.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.models.media_strategy import SceneSourceType
from src.models.suggestions import LookSuggestion
from src.models.video_job import VideoJob
from src.services.reference_frame_selection_service import SampledFrame
from src.shared.logger import logger

# (label, lighting, colour palette, camera feel) - two per genre. Short phrases: they
# are repeated word for word in every prompt.
_GENRE_LOOKS: dict[str, list[tuple[str, str, str, str]]] = {
    "genre.default": [
        (
            "Natural daylight",
            "soft natural daylight, even and slightly diffused",
            "natural colours, gentle contrast",
            "steady documentary camera, shallow depth of field",
        ),
        (
            "Warm and cinematic",
            "warm, soft key light with gentle shadows",
            "warm amber and neutral tones, slightly muted",
            "smooth cinematic camera, shallow depth of field",
        ),
    ],
    "genre.medical": [
        (
            "Clean and clinical",
            "bright, soft, even light, no harsh shadows",
            "clean whites and soft blues, natural skin tones",
            "steady, calm camera, shallow depth of field",
        ),
        (
            "Warm home care",
            "warm, soft household lamp light",
            "warm amber and cream tones, slightly muted",
            "gentle, steady camera, close and reassuring",
        ),
    ],
    "genre.documentary": [
        (
            "Overcast realism",
            "overcast soft daylight, no harsh shadows",
            "muted, desaturated documentary colours",
            "handheld documentary realism, shallow depth of field",
        ),
        (
            "Golden hour",
            "low golden-hour sunlight, long soft shadows",
            "warm natural colours, rich but not oversaturated",
            "steady camera with slow, observational movement",
        ),
    ],
    "genre.history": [
        (
            "Archive warmth",
            "soft, low, warm light like an old photograph",
            "sepia-leaning warm browns, faded highlights",
            "slow, steady camera, still and composed",
        ),
        (
            "Candle and stone",
            "dim candle or window light, deep shadows",
            "earthy browns and muted golds",
            "slow push-ins, painterly framing",
        ),
    ],
    "genre.horror": [
        (
            "Cold dread",
            "low, dim, directional light with deep shadows",
            "desaturated cold blues and greys",
            "slow, creeping camera, handheld unease",
        ),
        (
            "Sickly night",
            "single weak light source in a dark room",
            "murky greens and near-black shadows",
            "static, watchful framing with slow zooms",
        ),
    ],
    "genre.mystery": [
        (
            "Noir shadows",
            "low-key light with strong contrast and long shadows",
            "dark blues and warm amber highlights",
            "slow, deliberate camera, wide and moody",
        ),
        (
            "Foggy dusk",
            "dim blue-hour light with soft fog",
            "cool, muted blues and greys",
            "slow tracking shots, shallow depth of field",
        ),
    ],
    "genre.travel": [
        (
            "Sunlit and vivid",
            "bright natural sunlight, clear skies",
            "vivid, saturated natural colours",
            "smooth gimbal movement, wide and open",
        ),
        (
            "Golden hour journey",
            "warm golden-hour light",
            "warm golden and teal tones",
            "flowing camera, wide landscapes with depth",
        ),
    ],
    "genre.top10": [
        (
            "Bold and bright",
            "bright, punchy, even light",
            "vivid, high-contrast colours",
            "dynamic camera with clean, centred framing",
        ),
        (
            "Clean studio",
            "clean studio lighting, soft shadows",
            "crisp, saturated colours on a neutral ground",
            "steady camera, tight clean compositions",
        ),
    ],
    "genre.storytelling": [
        (
            "Warm and intimate",
            "warm, soft practical light, gentle shadows",
            "warm amber and soft neutrals",
            "close, human-level camera, shallow depth of field",
        ),
        (
            "Dusk drama",
            "low dusk light with soft contrast",
            "muted warm tones with cool shadows",
            "slow, emotional camera, close framing",
        ),
    ],
    "genre.reaction": [
        (
            "Bright and casual",
            "bright, even indoor light",
            "natural, slightly saturated colours",
            "handheld, close and energetic",
        ),
        (
            "Screen glow",
            "soft room light with a cool screen glow",
            "cool blues with warm skin tones",
            "steady close-up framing",
        ),
    ],
    "genre.survival": [
        (
            "Harsh daylight",
            "hard natural daylight, strong shadows",
            "gritty, desaturated earth tones",
            "handheld, close and urgent",
        ),
        (
            "Dusk and fire",
            "low dusk light with warm firelight",
            "dark earthy tones with orange highlights",
            "handheld, tense, close to the subject",
        ),
    ],
    "genre.comedy": [
        (
            "Bright and playful",
            "bright, even, cheerful light",
            "colourful, saturated, friendly colours",
            "lively camera with quick, playful framing",
        ),
        (
            "Sitcom warm",
            "warm, flat indoor light with no deep shadows",
            "warm, slightly saturated colours",
            "steady, wide, clearly framed shots",
        ),
    ],
}

_FRAMES_PER_CLIP = 3
_MAX_CLIPS = 12

FrameSampler = Callable[[str, int], list[SampledFrame]]


def _default_sampler(video_path: str, count: int) -> list[SampledFrame]:
    from src.services.reference_frame_selection_service import _read_sample_frames

    return _read_sample_frames(video_path, count)


class ProjectLookSuggestionService:
    """Builds candidate looks for a project. Never mutates the job's chosen look."""

    def __init__(self, *, frame_sampler: FrameSampler | None = None) -> None:
        self._sample = frame_sampler or _default_sampler

    def genre_suggestions(self, job: VideoJob) -> list[LookSuggestion]:
        looks = _GENRE_LOOKS.get(job.genre_id) or _GENRE_LOOKS["genre.default"]

        return [
            LookSuggestion(
                label=label,
                lighting=lighting,
                color_palette=palette,
                camera_feel=camera,
                source="genre",
            )
            for label, lighting, palette, camera in looks
        ]

    def clips_suggestion(self, job: VideoJob) -> LookSuggestion | None:
        """One look measured from the generated clips, or None when there are no
        usable clips (or the machine cannot read video)."""

        clips = [
            clip
            for clip in job.video_clips
            if clip.source_type == SceneSourceType.AI_GENERATE
            and clip.local_file
            and Path(clip.local_file).is_file()
        ][:_MAX_CLIPS]

        brightness: list[float] = []
        saturation: list[float] = []
        warmth: list[float] = []

        for clip in clips:
            try:
                frames = self._sample(clip.local_file or "", _FRAMES_PER_CLIP)
            except (
                Exception
            ) as error:  # noqa: BLE001 - one unreadable clip is not fatal
                logger.warning(
                    "Measuring a clip for a look suggestion failed: %s",
                    type(error).__name__,
                )
                continue

            for frame in frames:
                measured = measure_frame(frame.image)

                if measured is not None:
                    brightness.append(measured[0])
                    saturation.append(measured[1])
                    warmth.append(measured[2])

        if not brightness:
            return None

        return _describe(
            sum(brightness) / len(brightness),
            sum(saturation) / len(saturation),
            sum(warmth) / len(warmth),
            camera=_camera_feel_for(job.genre_id),
            clip_count=len(clips),
        )

    def suggest(self, job: VideoJob) -> list[LookSuggestion]:
        """New candidates only: the genre looks and the clips look, minus any the
        operator already saw (accepted or discarded) or that are still pending."""

        seen = {suggestion.key for suggestion in job.look_suggestions}
        candidates = self.genre_suggestions(job)
        measured = self.clips_suggestion(job)

        if measured is not None:
            candidates.insert(0, measured)

        return [c for c in candidates if c.key not in seen]


def _camera_feel_for(genre_id: str) -> str:
    looks = _GENRE_LOOKS.get(genre_id) or _GENRE_LOOKS["genre.default"]

    return looks[0][3]


def measure_frame(image: Any) -> tuple[float, float, float] | None:
    """(brightness 0-255, saturation 0-255, warmth = red minus blue) of one frame."""

    try:
        import cv2

        small = cv2.resize(image, (64, 64))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        blue, _green, red = (float(small[:, :, i].mean()) for i in range(3))

        return float(hsv[:, :, 2].mean()), float(hsv[:, :, 1].mean()), red - blue
    except Exception:  # noqa: BLE001 - an unreadable frame is skipped
        return None


def _describe(
    brightness: float,
    saturation: float,
    warmth: float,
    *,
    camera: str,
    clip_count: int,
) -> LookSuggestion:
    if brightness < 80:
        light = "dim, low-key"
    elif brightness < 140:
        light = "soft, moderate"
    else:
        light = "bright, airy"

    if warmth > 12:
        tone, tint = "warm", "warm amber"
    elif warmth < -12:
        tone, tint = "cool", "cool blue"
    else:
        tone, tint = "neutral", "neutral"

    if saturation < 70:
        colour = "muted"
    elif saturation < 120:
        colour = "natural"
    else:
        colour = "vivid"

    return LookSuggestion(
        label=f"From your clips ({clip_count})",
        lighting=f"{light}, {tone} light",
        color_palette=f"{colour} {tint} tones",
        camera_feel=camera,
        source="clips",
    )
