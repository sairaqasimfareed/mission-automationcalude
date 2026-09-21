from __future__ import annotations

from collections.abc import Callable

from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.models.voice_directives import SceneVoiceDirectives, VoiceProviderPreferences
from src.providers.voice_provider import VoiceProvider
from src.services.narration_condensation_service import (
    NarrationCondensationService,
)
from src.services.voice_directive_resolution_service import (
    VoiceDirectiveResolutionService,
)
from src.services.voice_directive_validation_service import (
    VoiceDirectiveValidationService,
)
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_profile_registry_service import VoiceProfileRegistryService

_registry = VoiceProfileRegistryService.with_default_profiles()

_validation_service = VoiceDirectiveValidationService(voice_profile_registry=_registry)

_resolution_service = VoiceDirectiveResolutionService(
    voice_profile_registry=_registry,
    validation_service=_validation_service,
)


class _SequencedProvider(VoiceProvider):
    """
    Returns a distinct fake output path per call, so a per-call
    ffprobe stub can report a different (fake) real duration each
    time - standing in for a retry's real regenerated file actually
    being shorter than the original.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.requested_speeds: list[float] = []

    @property
    def provider_name(self) -> str:
        return "Dummy Voice"

    def health_check(self) -> bool:
        return True

    def generate_voice(self, text: str, voice: str) -> str:
        assert text
        assert voice

        self.calls += 1

        return f"outputs/audio/generated_scene_{self.calls}.wav"

    def generate_from_blueprint(self, blueprint: ResolvedVoiceBlueprint) -> str:
        self.requested_speeds.append(blueprint.speed)

        return self.generate_voice(blueprint.narration_text, "dummy-horror-voice")


class _FixedCondensationService(NarrationCondensationService):
    """Real subclass (not a duck-typed fake) so it satisfies
    VoiceGenerationService's narration_condensation_service type
    exactly - returns a fixed condensed narration without any real
    LLM call, and records whether/how it was invoked."""

    def __init__(self, *, condensed_text: str | None) -> None:
        self._condensed_text = condensed_text
        self.calls: list[tuple[str, float]] = []

    def condense(
        self,
        *,
        narration_text: str,
        available_seconds: float,
    ) -> str | None:
        self.calls.append((narration_text, available_seconds))

        return self._condensed_text


def _sequenced_ffprobe_runner(durations: list[float]) -> Callable[[list[str]], str]:
    remaining = iter(durations)

    def _runner(command: list[str]) -> str:
        return f"{next(remaining)}\n"

    return _runner


def _blueprint(
    *,
    scene_duration_seconds: float | None = 6.0,
    speed: float = 1.0,
    narration_text: str = ("The ancient doorway slowly opened into complete darkness."),
) -> ResolvedVoiceBlueprint:
    directives = SceneVoiceDirectives(
        scene_number=1,
        voice_profile_id="voice.horror_whisper",
        provider_preferences=VoiceProviderPreferences(
            preferred_provider="Dummy Voice",
            preferred_voice_id="dummy-horror-voice",
            preferred_output_format="wav",
        ),
    )

    blueprint = _resolution_service.resolve(
        directives,
        narration_text=narration_text,
        scene_duration_seconds=scene_duration_seconds,
    )

    blueprint.speed = speed

    return blueprint


def test_overshoot_triggers_a_speed_corrected_retry_that_fits() -> None:
    """
    First generation overshoots (8.3s into a 6.0s slot); the retry,
    at a corrected speed, comes back at 5.8s - fits, so no trim is
    needed at all and the real (not clamped) duration is used.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=1.0)

    provider = _SequencedProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 5.8]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 2
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.8
    assert blueprint.estimated_speech_duration_seconds == 5.8
    assert blueprint.speed == provider.requested_speeds[-1]
    assert provider.requested_speeds[-1] > 1.0
    assert not any("trimmed to fit" in warning for warning in result.warnings)
    assert any("automatically regenerated" in warning for warning in result.warnings)


def test_overshoot_retry_still_short_falls_back_to_trim() -> None:
    """
    Even after a corrected-speed retry (7.0s), the narration still
    overshoots its 6.0s slot - the text is trimmed and, since this is
    a single-sentence narration with no sentence boundary to drop at,
    one final real regeneration is attempted for that trimmed text
    (5.7s), which fits and is used in place of the original file.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=1.0)

    provider = _SequencedProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.0, 5.7]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 3
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.7
    assert result.audio_track.source_file == "outputs/audio/generated_scene_3.wav"
    assert blueprint.estimated_speech_duration_seconds == 5.7
    assert any(
        "even after an automatic speed correction attempt" in warning
        for warning in result.warnings
    )


def test_small_overshoot_skips_retry_and_trims_directly() -> None:
    """
    An overshoot below the minimum-worth-retrying threshold (here
    0.1s, under the 0.3s floor) never spends a second real provider
    call for speed correction - but the hard-clamp step still
    attempts one real regeneration of the trimmed text (5.9s), which
    fits and is used instead of a blunt time-clamp of the original.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=1.0)

    provider = _SequencedProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([6.1, 5.9]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 2
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.9
    assert result.audio_track.source_file == "outputs/audio/generated_scene_2.wav"
    assert not any(
        "automatically regenerated" in warning for warning in result.warnings
    )
    assert any(
        "trimmed to fit" in warning and "speed correction" not in warning
        for warning in result.warnings
    )


def test_speed_already_at_maximum_skips_retry() -> None:
    """
    A blueprint already at the maximum valid speed has no real room
    left to correct - the speed-correction retry is skipped, and the
    hard-clamp step's one final regeneration of the trimmed text
    (5.6s) is used in place of a blunt time-clamp of the original.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=2.0)

    provider = _SequencedProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 5.6]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 2
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.6


def test_retry_provider_failure_falls_back_to_trimming_the_original() -> None:
    """
    A retry is a best-effort improvement, never a hard requirement -
    if the second provider call itself fails, generation still
    succeeds using the original file, trimmed exactly as before.
    """

    class _FailsOnRetryProvider(_SequencedProvider):
        def generate_from_blueprint(self, blueprint: ResolvedVoiceBlueprint) -> str:
            if self.calls >= 1:
                raise RuntimeError("Simulated provider failure on retry.")

            return super().generate_from_blueprint(blueprint)

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=1.0)

    provider = _FailsOnRetryProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 6.0
    assert any("trimmed to fit" in warning for warning in result.warnings)


def test_condensation_is_tried_after_speed_correction_and_fits() -> None:
    """
    Speed correction alone (7.0s) still overshoots the 6.0s slot;
    condensation is then tried and its regenerated audio (5.5s) fits,
    so sentence-drop never runs at all - no content is deleted.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=1.0)

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(condensed_text="Condensed text.")

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.0, 5.5]),
        narration_condensation_service=condensation_service,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 3
    assert condensation_service.calls == [
        (
            "The ancient doorway slowly opened into complete darkness.",
            6.0,
        )
    ]
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.5
    assert blueprint.narration_text == "Condensed text."
    assert not any("dropped" in warning for warning in result.warnings)
    assert any("condensed to fewer words" in warning for warning in result.warnings)


def test_condensation_still_overshoots_falls_through_to_sentence_drop() -> None:
    """
    Condensation is attempted and produces a usable, shorter result
    (6.8s) that still overshoots the 6.0s slot - sentence-drop then
    runs on the now-shorter condensed text, not the original.
    """

    blueprint = _blueprint(scene_duration_seconds=6.0, speed=1.0)

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(
        condensed_text="Still too long sentence. Second sentence here."
    )

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.0, 6.8, 5.0]),
        narration_condensation_service=condensation_service,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.0
    assert any("condensed to fewer words" in warning for warning in result.warnings)
    assert any("dropped" in warning for warning in result.warnings)


def test_condensation_not_configured_reproduces_prior_sentence_drop_behavior() -> None:
    """No narration_condensation_service (the default, None) skips
    straight to the existing sentence-drop fallback, unchanged."""

    blueprint = _blueprint(
        scene_duration_seconds=6.0,
        speed=1.0,
        narration_text=(
            "The ancient doorway slowly opened into complete darkness. "
            "Something waited on the other side."
        ),
    )

    provider = _SequencedProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.0, 5.0]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.0
    assert not any("condensed to fewer words" in warning for warning in result.warnings)
    assert any("dropped" in warning for warning in result.warnings)


def test_condensation_failure_falls_through_to_sentence_drop() -> None:
    """A condensation attempt that returns None (provider failure or
    empty response) is silently skipped, falling through to the
    existing sentence-drop fallback exactly as if it were never
    configured."""

    blueprint = _blueprint(
        scene_duration_seconds=6.0,
        speed=1.0,
        narration_text=(
            "The ancient doorway slowly opened into complete darkness. "
            "Something waited on the other side."
        ),
    )

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(condensed_text=None)

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.0, 5.0]),
        narration_condensation_service=condensation_service,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert condensation_service.calls
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 5.0
    assert not any("condensed to fewer words" in warning for warning in result.warnings)
    assert any("dropped" in warning for warning in result.warnings)


def test_small_overshoot_after_condensation_skips_destructive_sentence_drop() -> None:
    """
    Real-world finding, 2026-09-19: a condensed narration that still
    overshoots by only 0.23s (well under
    _MINIMUM_OVERSHOOT_TO_SENTENCE_DROP_SECONDS = 0.5) used to trigger
    sentence-drop anyway, deleting nearly the whole line to save a
    fraction of a second. Sentence-drop must not even be attempted
    here - the hard clamp alone (silent, inaudible) is strictly
    better than destroying content for this small a gain.
    """

    blueprint = _blueprint(
        scene_duration_seconds=6.0,
        speed=1.0,
        narration_text=(
            "The ancient doorway slowly opened into complete darkness. "
            "Something waited on the other side."
        ),
    )

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(
        condensed_text="A shorter condensed line here."
    )

    service = VoiceGenerationService(
        providers=[provider],
        # 8.3 initial, 7.0 speed-retry (still over), 6.23 condensed
        # (only 0.23s over the 6.0s slot - below the drop threshold,
        # so sentence-drop is skipped), then 4.9 for the hard clamp's
        # one final regeneration of the further text-trimmed result.
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.0, 6.23, 4.9]),
        narration_condensation_service=condensation_service,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 4
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 4.9
    assert result.audio_track.source_file == "outputs/audio/generated_scene_4.wav"
    assert not any("dropped" in warning for warning in result.warnings)
    assert any("condensed to fewer words" in warning for warning in result.warnings)
    assert any(
        "even after condensing the narration" in warning for warning in result.warnings
    )


def test_hard_clamp_regenerates_audio_for_the_trimmed_text_when_it_fits() -> None:
    """
    Real-world finding, 2026-09-19: confirmed on two real full renders
    - a scene that reaches the hard clamp can have its real AUDIO cut
    off mid-word (the clamp used to just atrim the old, longer file at
    the slot boundary, with no idea where a word ended), and/or its
    subtitle text still not match whatever the clamped audio actually
    contains (a text-only estimate, extrapolated from an averaged
    pace, does not always land where the blunt cut did). One real
    regeneration for the already-trimmed text closes both gaps at
    once: nothing is cut mid-word (the provider is asked for exactly
    this text), and the subtitle and the audio are now built from the
    identical string.

    Uses a 5-sentence narration so sentence-drop's own bounded effort
    (_MAXIMUM_SENTENCE_DROP_ATTEMPTS = 3) still leaves 2 sentences
    behind whose own just-measured pace, extrapolated, exceeds the
    clamped slot - the exact shape needed to exercise the new trim's
    own multi-sentence reduction before the final regeneration.
    """

    blueprint = _blueprint(
        scene_duration_seconds=6.5,
        speed=1.0,
        narration_text=(
            "Alpha happened first. Beta happened next. Gamma happened then. "
            "Delta happened later. Epsilon happened last."
        ),
    )

    provider = _SequencedProvider()

    # No condensation configured. Sequence: initial (8.3), speed-retry
    # (7.2, still 0.7s over the 6.5s slot - above the drop threshold),
    # then 3 sentence-drop attempts (dropping 1, 2, then 3 trailing
    # sentences, 8.0/7.5/7.0) - none fit 6.5s, so the best (most-
    # dropped, 2 sentences left, measured 7.0s) is used, followed by
    # one final real regeneration of the text-trimmed result (3.4s -
    # a genuine, complete recitation that fits comfortably).
    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 7.2, 8.0, 7.5, 7.0, 3.4]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 6
    assert result.audio_track is not None

    # Sentence-drop's own best effort left 2 sentences (6 words,
    # measured 7.0s - a real ~1.17s/word pace) still over the 6.5s
    # slot. Extrapolating that same real pace to just the first
    # sentence (3 words) gives ~3.5s, which fits - the new final trim
    # must reduce the text down to it before regenerating.
    assert blueprint.narration_text == "Alpha happened first."

    # The final audio is the fresh regeneration's own real duration
    # (3.4s), not a blunt clamp to the 6.5s slot - it fits on its own.
    assert result.audio_track.duration_seconds == 3.4
    assert result.audio_track.source_file == "outputs/audio/generated_scene_6.wav"
    assert any("dropped" in warning for warning in result.warnings)


def test_hard_clamp_regeneration_that_still_overshoots_is_clamped_but_kept() -> None:
    """
    The final regeneration is for already-trimmed text, so it usually
    fits - but if it still overshoots (rare), the fresh, complete
    recitation of the short text is still strictly better than the
    original, longer file: it is used (and clamped to the slot) in
    place of the original, not discarded in its favor.
    """

    blueprint = _blueprint(
        scene_duration_seconds=6.0,
        speed=2.0,  # Already at the maximum valid speed - retry is skipped.
        narration_text=(
            "One single long sentence with no real boundary to drop at right now."
        ),
    )

    provider = _SequencedProvider()

    # initial (8.3, over the 6.0s slot) - speed retry skipped (already
    # maxed) - single sentence so sentence-drop is skipped too - the
    # hard-clamp text trim then triggers one final regeneration, which
    # itself still measures a hair over the slot (6.4s).
    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3, 6.4]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 2
    assert result.audio_track is not None

    # Clamped to the slot duration, but using the fresh, shorter file.
    assert result.audio_track.duration_seconds == 6.0
    assert result.audio_track.source_file == "outputs/audio/generated_scene_2.wav"
    assert blueprint.narration_text != (
        "One single long sentence with no real boundary to drop at right now."
    )


def test_hard_clamp_falls_back_to_the_original_audio_when_regeneration_fails() -> None:
    """
    The final regeneration is a best-effort improvement, never a hard
    requirement - if that last real provider call itself fails, the
    original (longer) file is still clamped exactly as before, and
    the narration text is still trimmed for subtitle bookkeeping even
    though no new audio backs it.
    """

    class _FailsOnSecondCallProvider(_SequencedProvider):
        def generate_from_blueprint(self, blueprint: ResolvedVoiceBlueprint) -> str:
            if self.calls >= 1:
                self.calls += 1

                raise RuntimeError("Simulated provider failure on final retry.")

            return super().generate_from_blueprint(blueprint)

    blueprint = _blueprint(
        scene_duration_seconds=6.0,
        speed=2.0,  # Already at the maximum valid speed - retry is skipped.
        narration_text=(
            "One single long sentence with no real boundary to drop at right now."
        ),
    )

    provider = _FailsOnSecondCallProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 6.0
    assert result.audio_track.source_file == "outputs/audio/generated_scene_1.wav"
    assert blueprint.narration_text != (
        "One single long sentence with no real boundary to drop at right now."
    )
    assert any("trimmed to fit" in warning for warning in result.warnings)


def test_none_available_seconds_disables_the_whole_overshoot_cascade() -> None:
    """
    Real-world finding, 2026-09-20: available_scene_duration_seconds
    is None by default now (see ProjectRenderRuntimeFactory) - video
    clip duration follows voice's own real result instead of the
    other way around, so there is normally no ceiling for real
    narration to overshoot at all. None of speed-correction,
    condensation, sentence-drop, or the final hard-clamp trim should
    ever fire - the real, full-length narration is used exactly as
    measured, however long it naturally runs (well under the sanity
    ceiling here).
    """

    blueprint = _blueprint(scene_duration_seconds=None, speed=1.0)

    assert blueprint.available_scene_duration_seconds is None

    provider = _SequencedProvider()

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([8.3]),
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 1
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 8.3
    assert blueprint.narration_text == (
        "The ancient doorway slowly opened into complete darkness."
    )
    assert result.warnings == []


def test_sanity_ceiling_condenses_implausibly_long_narration_with_no_slot() -> None:
    """
    With no real scene-slot ceiling (available_seconds is None), a
    scene whose narration is implausibly long for one sentence - the
    signature of script-planning merging multiple sentences into one
    scene - should still get condensed, targeting the sanity ceiling
    instead of a (nonexistent) scene slot. Speed-correction, sentence-
    drop, and the hard-clamp trim must still never fire (they stay
    gated on a real ceiling being set).
    """

    blueprint = _blueprint(scene_duration_seconds=None, speed=1.0)

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(
        condensed_text="A much shorter condensed line."
    )

    service = VoiceGenerationService(
        providers=[provider],
        # Initial real measurement (50.0s) exceeds the 45.0s default
        # sanity ceiling - condensation is attempted and its own
        # result (30.0s) comfortably fits under it.
        ffprobe_runner=_sequenced_ffprobe_runner([50.0, 30.0]),
        narration_condensation_service=condensation_service,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 2
    assert condensation_service.calls == [
        (
            "The ancient doorway slowly opened into complete darkness.",
            VoiceGenerationService._MAXIMUM_SANE_NARRATION_SECONDS,
        )
    ]
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 30.0
    assert blueprint.narration_text == "A much shorter condensed line."
    assert any(
        "likely two or more sentences merged into one scene" in warning
        for warning in result.warnings
    )
    assert not any("dropped" in warning for warning in result.warnings)
    assert not any("trimmed to fit" in warning for warning in result.warnings)


def test_sanity_ceiling_is_configurable_via_constructor() -> None:
    """A caller can override the default 45.0s sanity ceiling."""

    blueprint = _blueprint(scene_duration_seconds=None, speed=1.0)

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(
        condensed_text="A much shorter condensed line."
    )

    service = VoiceGenerationService(
        providers=[provider],
        # 12.0s is well under the default 45.0s ceiling but exceeds
        # this test's own, much tighter, configured 10.0s ceiling.
        ffprobe_runner=_sequenced_ffprobe_runner([12.0, 8.0]),
        narration_condensation_service=condensation_service,
        maximum_sane_narration_seconds=10.0,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert condensation_service.calls == [
        (
            "The ancient doorway slowly opened into complete darkness.",
            10.0,
        )
    ]
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 8.0


def test_narration_well_under_the_sanity_ceiling_is_never_condensed() -> None:
    """The common case: no real ceiling, and narration nowhere near
    implausible for one sentence - condensation must not fire."""

    blueprint = _blueprint(scene_duration_seconds=None, speed=1.0)

    provider = _SequencedProvider()

    condensation_service = _FixedCondensationService(
        condensed_text="Should not be used."
    )

    service = VoiceGenerationService(
        providers=[provider],
        ffprobe_runner=_sequenced_ffprobe_runner([7.5]),
        narration_condensation_service=condensation_service,
    )

    result = service.generate(blueprint, start_time_seconds=0.0)

    assert result.success is True
    assert provider.calls == 1
    assert condensation_service.calls == []
    assert result.audio_track is not None
    assert result.audio_track.duration_seconds == 7.5


class TestTrimTextToEstimatedDuration:
    def test_returns_text_unchanged_when_it_already_fits(self) -> None:
        text = "A short line."

        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=10.0, measured_duration_seconds=3.0
        )

        assert trimmed == text

    def test_drops_trailing_sentences_until_the_estimate_fits(self) -> None:
        text = (
            "First sentence has several words in it. "
            "Second sentence also has quite a few words. "
            "Third short one."
        )

        # 18 words total measured at 9.0s (0.5s/word). Dropping to
        # just the first sentence (7 words, ~3.5s) is the first kept
        # set that fits a 4.0s budget - sentences are dropped from
        # the end, same convention as sentence-drop's own retry.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=4.0, measured_duration_seconds=9.0
        )

        assert trimmed == "First sentence has several words in it."

    def test_falls_through_to_word_level_trim_when_even_the_first_sentence_overshoots(
        self,
    ) -> None:
        """
        Real-world finding, 2026-09-19: confirmed on a real render -
        NarrationCondensationService's rewrite often merges what were
        two sentences into one, so even "keep just the first
        sentence" can still be a single, still-overshooting sentence
        with no boundary left to drop at. Unlike the real audio (a
        mid-word cut sounds broken), a subtitle ending mid-sentence
        is fine to read - this is a text-only trim of what has
        already been decided for the audio, so dropping trailing
        words here is safe and necessary to stay consistent with
        what is actually left to play.
        """

        text = "This first sentence alone already runs long. Second one."

        # 7 words in sentence 1, measured at 9.0s total / 9 words =
        # 1.0s/word. A 3.0s budget keeps only the first 3 words.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=3.0, measured_duration_seconds=9.0
        )

        assert trimmed == "This first sentence"

    def test_single_sentence_that_already_fits_is_returned_unchanged(self) -> None:
        text = "One single sentence with no real boundary to drop at."

        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=10.0, measured_duration_seconds=5.0
        )

        assert trimmed == text

    def test_single_sentence_that_overshoots_gets_word_trimmed(self) -> None:
        text = "One single sentence with no real boundary to drop at."

        # 10 words measured at 5.0s (0.5s/word) - a 2.0s budget keeps
        # only the first 4 words.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=2.0, measured_duration_seconds=5.0
        )

        assert trimmed == "One single sentence with"

    def test_slower_real_measured_pace_forces_more_trimming(self) -> None:
        """
        Same text and available_seconds, different REAL measured
        pace for this exact utterance - a slower real pace must trim
        more than a faster one would, since the trim is extrapolated
        from what this scene's own narration actually measured, not
        a generic rate.
        """

        text = "First sentence here. Second sentence here too."

        trimmed_slow_pace = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=4.0, measured_duration_seconds=7.0
        )
        trimmed_fast_pace = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=4.0, measured_duration_seconds=3.5
        )

        assert trimmed_slow_pace == "First sentence here."
        assert trimmed_fast_pace == text

    def test_zero_measured_duration_returns_text_unchanged(self) -> None:
        text = "First sentence here. Second sentence here too."

        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=1.0, measured_duration_seconds=0.0
        )

        assert trimmed == text

    def test_drops_trailing_clause_before_falling_to_a_word_count_cut(self) -> None:
        """
        Real-world finding, 2026-09-19: confirmed on a real full
        render - a pure word-count cut of a still-overshooting single
        sentence can land mid-clause and produce a nonsensical
        dangling fragment (observed directly: "...wheat prices
        collapsed and subsidies", with no verb; "Minister Pearce to",
        with no object) - and since this text also becomes the real,
        final regeneration request, that fragment gets spoken aloud,
        not just displayed. Dropping a trailing clause (comma/
        semicolon boundary) first, before ever falling to a blind
        word cut, keeps whatever remains a complete thought.
        """

        text = "The report showed clear results, and the team celebrated quietly."

        # 10 words total measured at 10.0s (1.0s/word). A 5.0s budget
        # exactly fits the first clause alone (5 words) once the
        # trailing clause is dropped - the trailing comma is stripped
        # since this is now deliberately where the text ends.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=5.0, measured_duration_seconds=10.0
        )

        assert trimmed == "The report showed clear results"

    def test_falls_through_to_word_level_trim_of_just_the_first_clause(self) -> None:
        """
        Even the single remaining clause's own estimate can still
        overshoot - the word-level fallback then trims within just
        that clause, not the whole original (multi-clause) sentence.
        """

        text = "The report showed clear results, and the team celebrated quietly."

        # Same 1.0s/word pace as above, but a tighter 3.0s budget -
        # even the first clause alone (5 words, ~5.0s) still
        # overshoots, so only its own first 3 words are kept.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=3.0, measured_duration_seconds=10.0
        )

        assert trimmed == "The report showed"

    def test_comma_with_no_following_space_is_never_treated_as_a_clause_boundary(
        self,
    ) -> None:
        """
        A comma inside a number ("20,000") has no whitespace right
        after it - must never be mistaken for a clause boundary and
        split mid-number, unlike a real clause-separating comma
        ("results, and the team").
        """

        text = (
            "The soldiers found 20,000 emus near the border and radioed "
            "for backup immediately today."
        )

        # 14 words total measured at 14.0s (1.0s/word). No real
        # clause boundary exists before the 5-word budget is reached,
        # so this falls straight to a word-count cut of the whole
        # sentence - "20,000" must survive intact within it.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=5.0, measured_duration_seconds=14.0
        )

        assert trimmed == "The soldiers found 20,000 emus"

    def test_drops_trailing_clause_at_a_semicolon_boundary(self) -> None:
        """Mirrors the real scene 3 shape from the same render - a
        semicolon-joined compound sentence with an internal, non-
        clause-boundary comma inside a number ("20,000") that must be
        preserved, while the real (whitespace-following) commas and
        the semicolon are respected as real clause boundaries."""

        text = "By 1932, 20,000 emus invaded crops; Minister Pearce sent soldiers."

        # 10 words total measured at 10.0s (1.0s/word). A 6.0s budget
        # fits the first two clauses combined (6 words) once the
        # trailing clause is dropped - the semicolon is stripped as
        # the new trailing punctuation, the internal comma is kept.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=6.0, measured_duration_seconds=10.0
        )

        assert trimmed == "By 1932, 20,000 emus invaded crops"

    def test_drops_trailing_clause_joined_by_a_bare_conjunction_with_no_comma(
        self,
    ) -> None:
        """
        Real-world finding, 2026-09-19: confirmed on a real full
        render - the comma/semicolon-only clause split (above) is not
        enough on its own. NarrationCondensationService's rewrite
        sometimes joins two clauses with a bare "and" and no comma at
        all, so a still-overshooting cut fell all the way through to
        a raw word-count trim and landed mid-clause anyway ("...wheat
        prices collapsed and subsidies", with no verb - the exact
        reported symptom, reproduced here). "and"/"but"/"or" must be
        treated as clause boundaries even with no comma present.
        """

        text = (
            "Veteran farmer Jack Reid faced ruin as wheat prices "
            "collapsed and subsidies went unpaid."
        )

        # 14 words total measured at 14.0s (1.0s/word). A 10.0s budget
        # fits everything up to (not including) "and subsidies went
        # unpaid" (10 words) once that trailing, comma-less clause is
        # dropped - not a raw word-count cut into the middle of it.
        trimmed = VoiceGenerationService._trim_text_to_estimated_duration(
            text, available_seconds=10.0, measured_duration_seconds=14.0
        )

        assert (
            trimmed == "Veteran farmer Jack Reid faced ruin as wheat prices collapsed"
        )
