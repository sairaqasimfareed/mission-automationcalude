from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.resolved_voice_blueprint import (
    ResolvedVoiceBlueprint,
    VoiceBlueprintResolutionStatus,
)
from src.models.voice_generation import (
    VoiceGenerationFailure,
    VoiceGenerationFailureReason,
    VoiceGenerationJob,
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.providers.voice_provider import VoiceProvider
from src.services.narration_condensation_service import (
    NarrationCondensationService,
)

_PROBE_COMMAND_TIMEOUT_SECONDS = 30.0


def _run_ffprobe(command: list[str]) -> str:
    """Real ffprobe invocation - the default `ffprobe_runner` implementation."""

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_PROBE_COMMAND_TIMEOUT_SECONDS,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "ffprobe command failed: "
            + " ".join(command)
            + (f"\n{completed.stderr.strip()}" if completed.stderr else "")
        )

    return completed.stdout


class VoiceGenerationService:
    """
    Generate narration audio from resolved voice blueprints.

    The service is provider-independent. Real ElevenLabs,
    OpenAI, Google, or Azure adapters can implement the existing
    VoiceProvider interface.
    """

    SUPPORTED_OUTPUT_FORMATS = {
        ".mp3",
        ".wav",
        ".aac",
        ".ogg",
        ".flac",
    }

    # Real-world finding, 2026-09-17: confirmed against a real render
    # that real TTS narration frequently overshoots its planned video
    # slot (11 of 18 scenes on one real job), and the only existing
    # response was a hard atrim mid-sentence - audible, and the exact
    # cause of the "patchy desync" a user can hear even when voice and
    # video are otherwise perfectly aligned everywhere else, since the
    # trimmed audio no longer matches what the subtitles (built from
    # the same narration text) still say. Retrying once at a
    # corrected, faster speed closes most of that gap without ever
    # cutting a sentence short - see run_job and
    # _attempt_speed_corrected_regeneration.

    # Real-world finding, 2026-09-18: the first version of this retry
    # aimed for whatever speed would fully close a scene's overshoot,
    # capped only at the blueprint's own generic maximum (2.0) - on a
    # real render this asked for speeds up to 1.54x. ElevenLabs' own
    # documentation gives 0.7-1.2 as its real, enforced range (values
    # outside are "not supported" and silently clamped by
    # ElevenLabsVoiceTranslationService's own _MAX_PROVIDER_SPEED), so
    # every request above 1.2 was already being reduced before it
    # reached the API - but real listening confirmed even values near
    # that 1.2 edge came back with skipped/garbled words and an
    # audibly rushed pace, exactly the "extreme values may affect
    # quality" warning in ElevenLabs' own docs (natural conversation
    # sits at 0.9-1.1). A clean trim is a worse-sounding defect than a
    # slightly early cutoff was assumed to be when this feature was
    # designed - it turned out to be the other way around: garbled
    # words mid-sentence read as broken, where a trim just ends a
    # touch early. Capping the retry's own target well short of
    # ElevenLabs' real edge keeps every regenerated scene inside the
    # range that actually sounds natural, at the cost of leaning on
    # the trim fallback more often for large overshoots - a real,
    # deliberate trade-off, not an oversight.
    _MAXIMUM_RETRY_SPEED = 1.15

    # Below this, a trim is inaudible and not worth a second real
    # provider call.
    _MINIMUM_OVERSHOOT_TO_RETRY_SECONDS = 0.3

    # Below this, the corrected speed is indistinguishable from the
    # blueprint's current one - not worth a second real provider call
    # either.
    _MINIMUM_SPEED_CORRECTION_DELTA = 0.02

    # Real-world finding, 2026-09-18: a speed-corrected retry that
    # still overshoots was, until now, handed straight to the
    # trim-to-fit fallback below - which cuts from the *end* of the
    # audio, at whatever timestamp its available_seconds boundary
    # happens to fall. Confirmed on a real render: two different
    # scenes' trims each landed exactly on the sentence's own final
    # word ("...Lewis guns." / "...stayed painfully low.") and
    # deleted it outright - not an abrupt-sounding-but-complete
    # ending, an actually missing word, which is worse. A narration's
    # own sentence boundaries are the only safe place to shorten it
    # without doing that: dropping whole trailing sentences (see
    # _split_into_sentences / _attempt_sentence_trimmed_regeneration)
    # keeps every real, spoken word part of a complete sentence, at
    # the cost of the video's narration covering less of the scene's
    # own content when a scene's narration is too long to say even at
    # a safe, natural speed. Bounded to a handful of real provider
    # calls (never more sentences than the narration actually has) so
    # a long, many-sentence narration cannot turn one overshoot into
    # an unbounded retry loop.
    _MAXIMUM_SENTENCE_DROP_ATTEMPTS = 3

    # Real-world finding, 2026-09-19: confirmed on a real render -
    # scene 4's narration ("On November second, soldiers spotted
    # fifty emus near Campion.") was condensed to 3.63s against a
    # 3.40s slot, a 0.23s remaining overshoot - genuinely inaudible
    # if just hard-clamped. But sentence-drop had no floor of its
    # own (unlike the speed-correction retry above, which already
    # skips itself below _MINIMUM_OVERSHOOT_TO_RETRY_SECONDS), so it
    # fired anyway, dropped nearly the whole condensed narration, and
    # left a 0.67s scrap - deleting real content to save a fraction
    # of a second nobody would have noticed missing. Below this
    # threshold, a hard-clamped trim is strictly better than
    # sentence-drop's content loss - the same "a trim just ends a
    # touch early" reasoning _MAXIMUM_RETRY_SPEED's own comment
    # already applies to speed correction, extended to this
    # strictly-more-destructive fallback. Deliberately higher than
    # _MINIMUM_OVERSHOOT_TO_RETRY_SECONDS (0.3s) - a free speed retry
    # is worth attempting for a smaller gain than a fallback that
    # deletes real, spoken content is.
    _MINIMUM_OVERSHOOT_TO_SENTENCE_DROP_SECONDS = 0.5

    # Real-world finding, 2026-09-20: available_scene_duration_seconds
    # is no longer a hard per-scene ceiling for the default case (see
    # ProjectRenderRuntimeFactory, which now passes None) - video clip
    # duration follows voice's own real, measured result instead of
    # the other way around, so there is normally no slot for real
    # narration to overshoot at all. This constant is NOT a scene- or
    # video-length limit - a long-form video simply has more scenes,
    # not longer ones. It exists only to catch one specific anomaly:
    # script-planning accidentally merging multiple sentences into one
    # scene, producing a single "scene" whose narration is implausibly
    # long for one sentence. When available_scene_duration_seconds is
    # None, this constant (not the scene's own, absent, ceiling) is
    # what the condensation attempt below targets - a real, but rare,
    # safety net, not a routine limit. The speed-correction retry and
    # sentence-drop/text-trim tail intentionally stay gated on
    # available_scene_duration_seconds being set, so they remain
    # unreachable in the default flow even when this fires.
    _MAXIMUM_SANE_NARRATION_SECONDS = 45.0

    _SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")

    # Deliberately requires whitespace right after the comma/semicolon
    # (same lookbehind shape as _SENTENCE_BOUNDARY_PATTERN) so a comma
    # with no following space - "20,000" - is never treated as a
    # clause boundary and split mid-number.
    #
    # Real-world finding, 2026-09-19: a comma/semicolon boundary alone
    # is not enough - confirmed on a real render where
    # NarrationCondensationService's own rewrite joined two clauses
    # with a bare coordinating conjunction and no comma at all
    # ("...wheat prices collapsed and subsidies went unpaid."), so a
    # still-overshooting cut still landed mid-clause ("...collapsed
    # and subsidies") with no punctuation boundary anywhere to fall
    # back to. "and"/"but"/"or" are deliberately the only three
    # included - the ones that reliably join two independent clauses
    # in narration-style text - unlike "so"/"yet"/"for", which are
    # common as plain adverbs/prepositions ("so many", "for years")
    # and would risk splitting mid-phrase rather than at a real clause
    # boundary.
    _CLAUSE_BOUNDARY_PATTERN = re.compile(r"(?<=[,;])\s+|\s+(?=(?:and|but|or)\b)")

    def __init__(
        self,
        *,
        providers: list[VoiceProvider],
        ffprobe_path: str = "ffprobe",
        ffprobe_runner: Callable[[list[str]], str] | None = None,
        narration_condensation_service: NarrationCondensationService | None = None,
        maximum_sane_narration_seconds: float | None = None,
    ) -> None:
        self.providers = providers
        self.ffprobe_path = ffprobe_path
        self._ffprobe_runner = ffprobe_runner or _run_ffprobe
        # Optional: without it, an overshoot that survives speed
        # correction goes straight to the existing sentence-drop
        # fallback, reproducing this class's exact prior behavior.
        self._narration_condensation_service = narration_condensation_service
        # Configurable override for _MAXIMUM_SANE_NARRATION_SECONDS -
        # see that constant's own comment for what it is and, just as
        # importantly, what it is not (not a scene- or video-length
        # limit).
        self._maximum_sane_narration_seconds = (
            maximum_sane_narration_seconds
            if maximum_sane_narration_seconds is not None
            else self._MAXIMUM_SANE_NARRATION_SECONDS
        )

    def generate(
        self,
        blueprint: ResolvedVoiceBlueprint,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        """Generate one voiceover and return an audio track."""

        job = VoiceGenerationJob(
            scene_number=blueprint.scene_number,
            blueprint=blueprint,
            status=VoiceGenerationStatus.PENDING,
            metadata={
                "requested_profile_id": (blueprint.profile.requested_profile_id),
                "resolved_profile_id": (blueprint.profile.resolved_profile_id),
            },
        )

        return self.run_job(
            job,
            start_time_seconds=start_time_seconds,
            provider_name=provider_name,
        )

    def run_job(
        self,
        job: VoiceGenerationJob,
        *,
        start_time_seconds: float = 0.0,
        provider_name: str | None = None,
    ) -> VoiceGenerationResult:
        """Execute one voice generation job."""

        if start_time_seconds < 0:
            raise ValueError("Voice track start time cannot be negative.")

        blueprint = job.blueprint

        if not blueprint.is_generation_ready:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.BLUEPRINT_NOT_READY),
                message=("Voice blueprint is not ready " "for generation."),
                recoverable=False,
            )

        preferred_provider = provider_name or (
            blueprint.provider_preferences.preferred_provider
        )

        provider = self._select_provider(
            preferred_provider=(preferred_provider),
        )

        if provider is None:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.NO_PROVIDER_AVAILABLE),
                message=("No compatible voice provider " "is available."),
            )

        job.selected_provider = provider.provider_name

        try:
            provider_healthy = provider.health_check()
        except Exception as exc:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.PROVIDER_UNHEALTHY),
                message=("Voice provider health check failed."),
                provider=provider.provider_name,
                metadata={
                    "exception_type": (type(exc).__name__),
                    "exception_message": str(exc),
                },
            )

        if not provider_healthy:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.PROVIDER_UNHEALTHY),
                message=("Selected voice provider is unhealthy."),
                provider=provider.provider_name,
            )

        job.status = VoiceGenerationStatus.GENERATING
        job.attempts += 1

        try:
            # Post-Script-Approval Production Plan, Phase 9: "The
            # voice provider must consume a translated
            # ResolvedVoiceBlueprint rather than only raw narration
            # text." Every provider supports this call - it's the
            # base class's own generate_voice()/resolve_provider_voice()
            # fallback for a provider with no richer translation
            # (DryRunVoiceProvider), and a real translation for one
            # that has it (ElevenLabsVoiceProvider) - so this call
            # site never needs to know which kind it has.
            output_file = provider.generate_from_blueprint(blueprint)
        except Exception as exc:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.PROVIDER_ERROR),
                message=("Voice provider failed during " "audio generation."),
                provider=provider.provider_name,
                metadata={
                    "exception_type": (type(exc).__name__),
                    "exception_message": str(exc),
                },
            )

        cleaned_output_file = (
            output_file.strip() if isinstance(output_file, str) else ""
        )

        if not cleaned_output_file:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.EMPTY_OUTPUT_PATH),
                message=("Voice provider returned an empty " "output file path."),
                provider=provider.provider_name,
            )

        normalized_output_file = Path(cleaned_output_file).as_posix()

        output_suffix = Path(normalized_output_file).suffix.lower()

        if output_suffix not in self.SUPPORTED_OUTPUT_FORMATS:
            return self._fail(
                job=job,
                reason=(VoiceGenerationFailureReason.UNSUPPORTED_OUTPUT_FORMAT),
                message=("Voice provider returned an " "unsupported audio format."),
                provider=provider.provider_name,
                metadata={
                    "output_file": (normalized_output_file),
                    "output_suffix": output_suffix,
                },
            )

        # Real-world finding: this always used the pre-generation
        # ESTIMATE, never the real generated file's own duration -
        # every later scene's voice start_time_seconds is computed by
        # accumulating this value (see the caller's loop), and
        # subtitle timing keys off this same estimate, so any real
        # difference between estimated and actual TTS speech length
        # compounds across every remaining scene, drifting voice,
        # subtitles, and the real audio further out of sync as the
        # video goes on. Measuring the real file directly removes the
        # estimate from the loop entirely; a measurement failure
        # (ffprobe unavailable, unreadable file) falls back to the
        # old estimate-based behavior with a warning, never hard-
        # failing voice generation over it.
        measured_duration_seconds = self._detect_duration_seconds(
            Path(normalized_output_file)
        )

        if measured_duration_seconds is not None and measured_duration_seconds > 0.0:
            resolved_duration_seconds = measured_duration_seconds

            # Real-world finding: real TTS pacing does not always match
            # the pre-generation word-count estimate closely enough to
            # fit the scene's own video slot (confirmed on a real
            # render: one scene planned for 6s of video came back as
            # 8.3s of real narration) - MasterEditPlanService's own
            # audio-vs-video duration check then refuses to render at
            # all, correctly, since nothing downstream previously
            # constrained playback to duration_seconds (see
            # FilterGraphBuilderService._build_audio_chains' new atrim
            # step, which is what actually makes this clamp take real
            # effect rather than just relabeling a track that still
            # plays its full length). Clamping here - not deeper in
            # the pipeline - is what keeps this scene-local: no other
            # scene's timing, and nothing about the video, ever moves.
            available_seconds = blueprint.available_scene_duration_seconds

            retry_attempted = False

            if (
                available_seconds is not None
                and resolved_duration_seconds > available_seconds
            ):
                retry_result = self._attempt_speed_corrected_regeneration(
                    provider=provider,
                    blueprint=blueprint,
                    resolved_duration_seconds=resolved_duration_seconds,
                    available_seconds=available_seconds,
                )

                if retry_result is not None:
                    retry_attempted = True

                    (
                        retry_output_file,
                        retry_duration_seconds,
                        requested_speed,
                    ) = retry_result

                    normalized_output_file = retry_output_file

                    resolved_duration_seconds = retry_duration_seconds

                    blueprint.speed = requested_speed

                    job.metadata["speed_corrected_retry"] = True

                    job.warnings.append(
                        f"Real narration for scene {blueprint.scene_number} "
                        "originally ran longer than its "
                        f"{available_seconds:.2f}s video slot; automatically "
                        f"regenerated at {requested_speed:.2f}x speed "
                        f"(now {resolved_duration_seconds:.2f}s) instead of "
                        "cutting it short."
                    )

            # Real-world finding, 2026-09-18: see
            # NarrationCondensationService's own module docstring -
            # dropping trailing sentences removes real story content
            # (a confirmed, repeated user complaint). Tried after
            # speed-correction (free, no content risk) and before the
            # sentence-drop fallback below (which does lose content),
            # so a genuine overshoot gets a chance at a rewrite that
            # preserves every fact before anything is deleted
            # outright. Optional (self._narration_condensation_service
            # can be None) - reproduces this method's exact prior
            # behavior when not configured.
            #
            # Real-world finding, 2026-09-20: when there is no real
            # scene-slot ceiling (available_seconds is None, the new
            # default - see ProjectRenderRuntimeFactory), this step
            # still runs, but targets _maximum_sane_narration_seconds
            # instead - a much higher, rarely-hit anomaly threshold
            # (see that constant's own comment), not a routine limit.
            # When a real scene-slot ceiling IS set, behavior is
            # unchanged from before.
            condensed = False

            condensation_ceiling = (
                available_seconds
                if available_seconds is not None
                else self._maximum_sane_narration_seconds
            )

            if (
                self._narration_condensation_service is not None
                and resolved_duration_seconds > condensation_ceiling
            ):
                condense_retry = self._attempt_condensed_regeneration(
                    provider=provider,
                    blueprint=blueprint,
                    available_seconds=condensation_ceiling,
                )

                if condense_retry is not None:
                    condensed = True

                    (
                        condensed_output_file,
                        condensed_duration_seconds,
                        condensed_narration_text,
                    ) = condense_retry

                    normalized_output_file = condensed_output_file

                    resolved_duration_seconds = condensed_duration_seconds

                    blueprint.narration_text = condensed_narration_text

                    job.metadata["narration_condensed_retry"] = True

                    now_fits = resolved_duration_seconds <= condensation_ceiling

                    slot_description = (
                        f"its {available_seconds:.2f}s video slot"
                        if available_seconds is not None
                        else "a plausible length for one sentence "
                        f"({condensation_ceiling:.2f}s) - likely two or more "
                        "sentences merged into one scene"
                    )

                    after_retry_description = (
                        " after a speed correction" if retry_attempted else ""
                    )

                    job.warnings.append(
                        f"Real narration for scene {blueprint.scene_number} "
                        f"ran longer than {slot_description}"
                        f"{after_retry_description}; automatically condensed "
                        "to fewer words (preserving all information) instead of "
                        f"dropping any sentence (now "
                        f"{resolved_duration_seconds:.2f}s"
                        f"{'' if now_fits else ', still trimmed to fit'})."
                    )

            sentences_dropped = False

            if (
                available_seconds is not None
                and resolved_duration_seconds > available_seconds
                and (resolved_duration_seconds - available_seconds)
                >= self._MINIMUM_OVERSHOOT_TO_SENTENCE_DROP_SECONDS
            ):
                sentence_retry = self._attempt_sentence_trimmed_regeneration(
                    provider=provider,
                    blueprint=blueprint,
                    available_seconds=available_seconds,
                )

                if sentence_retry is not None:
                    sentences_dropped = True

                    (
                        sentence_output_file,
                        sentence_duration_seconds,
                        shortened_narration_text,
                    ) = sentence_retry

                    normalized_output_file = sentence_output_file

                    resolved_duration_seconds = sentence_duration_seconds

                    blueprint.narration_text = shortened_narration_text

                    job.metadata["sentence_dropped_retry"] = True

                    now_fits = resolved_duration_seconds <= available_seconds

                    job.warnings.append(
                        f"Real narration for scene {blueprint.scene_number} "
                        "still ran longer than its "
                        f"{available_seconds:.2f}s video slot after a speed "
                        "correction; the narration's own trailing sentence(s) "
                        "were dropped instead of cutting a word short "
                        f"(now {resolved_duration_seconds:.2f}s"
                        f"{'' if now_fits else ', still trimmed to fit'})."
                    )

            if (
                available_seconds is not None
                and resolved_duration_seconds > available_seconds
            ):
                overshoot = resolved_duration_seconds - available_seconds

                if sentences_dropped:
                    still_overshoots_after_retry = (
                        " even after dropping trailing sentences"
                    )
                elif condensed:
                    still_overshoots_after_retry = (
                        " even after condensing the narration"
                    )
                elif retry_attempted:
                    still_overshoots_after_retry = (
                        " even after an automatic speed correction attempt"
                    )
                else:
                    still_overshoots_after_retry = ""

                job.warnings.append(
                    f"Real narration for scene {blueprint.scene_number} "
                    f"({resolved_duration_seconds:.2f}s) ran "
                    f"{overshoot:.2f}s longer than its {available_seconds:.2f}s "
                    f"video slot{still_overshoots_after_retry}; trimmed to "
                    "fit. Consider shortening this scene's narration if the "
                    "trim is noticeable."
                )

                # Real-world finding, 2026-09-19: this hard clamp only
                # ever trimmed the real AUDIO FILE's own reported
                # duration via a blunt, time-based atrim at render
                # time - it has no idea where a word boundary falls,
                # so the real audio can be sliced mid-word (confirmed
                # directly: a user report of audio "skipping words" /
                # sounding incomplete on a scene whose clamped
                # duration landed on the exact slot boundary, the
                # signature of a time-cut rather than a natural
                # measurement). Separately, the text-only trim this
                # comment used to describe (still computed below, as
                # target_text) only estimates how many words fit from
                # an AVERAGED pace - real speech is not evenly paced,
                # so that estimate can land on either side of what the
                # blunt audio cut actually captured, which is exactly
                # the other half of the same user report ("audio says
                # more than its subtitle"). One real regeneration for
                # target_text - a complete, natural recitation of
                # exactly the text this scene will actually use -
                # replaces both symptoms at their real source: no
                # mid-word cut (nothing needs cutting - the provider
                # is asked for precisely this text) and no estimate
                # mismatch (subtitle and audio are now built from the
                # identical string). Only falls back to the blunt
                # clamp if this real call fails outright.
                target_text = self._trim_text_to_estimated_duration(
                    blueprint.narration_text,
                    available_seconds=available_seconds,
                    measured_duration_seconds=resolved_duration_seconds,
                )

                final_regeneration = None

                if target_text != blueprint.narration_text:
                    final_retry_blueprint = blueprint.model_copy(
                        update={"narration_text": target_text}
                    )

                    final_regeneration = self._generate_and_measure(
                        provider=provider,
                        blueprint=final_retry_blueprint,
                    )

                if final_regeneration is not None:
                    (
                        final_output_file,
                        final_measured_duration,
                    ) = final_regeneration

                    normalized_output_file = final_output_file
                    blueprint.narration_text = target_text

                    if final_measured_duration <= available_seconds:
                        resolved_duration_seconds = final_measured_duration
                    else:
                        # The regenerated recitation of the already-
                        # shortened text still overran the slot -
                        # rare, but still strictly better to clamp a
                        # clean, complete take of the SHORT text than
                        # the original long one.
                        resolved_duration_seconds = available_seconds
                else:
                    blueprint.narration_text = target_text
                    resolved_duration_seconds = available_seconds

            # Subtitle timing (SubtitleExecutionService.build_scene_subtitles)
            # reads this same blueprint's estimated_speech_duration_seconds
            # directly, not the audio track - updating it here in place is
            # what actually closes the loop for subtitle sync, since this
            # is the exact same blueprint object the render pipeline later
            # hands to the subtitle stage. "Estimated" now means "the best
            # known duration" - a real measurement (clamped to the scene's
            # real available slot when it overshoots) after generation,
            # the pre-generation guess only until then.
            blueprint.estimated_speech_duration_seconds = resolved_duration_seconds
        else:
            resolved_duration_seconds = blueprint.estimated_speech_duration_seconds

            job.warnings.append(
                "Could not measure the real generated audio duration; "
                "used the pre-generation estimate instead, which can "
                "drift voice/subtitle timing out of sync with the "
                "actual audio."
            )

        audio_track = AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file=normalized_output_file,
            start_time_seconds=(start_time_seconds),
            duration_seconds=resolved_duration_seconds,
            volume=self._gain_db_to_linear(blueprint.volume_gain_db),
            fade_in_seconds=(blueprint.pause_before_seconds),
            fade_out_seconds=(blueprint.pause_after_seconds),
            loop_enabled=False,
            duck_under_voice=False,
            provider=provider.provider_name,
            license_type="generated",
            status=AudioTrackStatus.READY,
            metadata={
                "scene_number": (blueprint.scene_number),
                "voice_profile_id": (blueprint.profile.resolved_profile_id),
                "requested_voice_profile_id": (blueprint.profile.requested_profile_id),
                "language": blueprint.language,
                "language_code": (blueprint.language_code),
                "emotion": (blueprint.emotion.value),
                "pace": blueprint.pace.value,
                "energy": blueprint.energy.value,
                "speed": blueprint.speed,
                "pitch_adjustment": (blueprint.pitch_adjustment),
                "stability": (blueprint.stability),
                "similarity_boost": (blueprint.similarity_boost),
                "style_strength": (blueprint.style_strength),
                "speaker_boost": (blueprint.speaker_boost),
                "explicit_instruction_count": (blueprint.explicit_instruction_count),
                "measured_duration_seconds": measured_duration_seconds,
            },
        )

        job.status = VoiceGenerationStatus.COMPLETED
        job.output_file = normalized_output_file
        job.failure = None

        blueprint.output_file = normalized_output_file

        blueprint.status = VoiceBlueprintResolutionStatus.GENERATED

        return VoiceGenerationResult(
            success=True,
            scene_number=job.scene_number,
            status=(VoiceGenerationStatus.COMPLETED),
            provider=provider.provider_name,
            output_file=normalized_output_file,
            audio_track=audio_track,
            attempts=job.attempts,
            warnings=list(
                dict.fromkeys(
                    [
                        *job.warnings,
                        *blueprint.warnings,
                    ]
                )
            ),
            metadata={
                **job.metadata,
                "blueprint_status": (blueprint.status.value),
                "estimated_duration_seconds": (
                    blueprint.estimated_speech_duration_seconds
                ),
            },
        )

    def generate_many(
        self,
        blueprints: list[ResolvedVoiceBlueprint],
        *,
        provider_name: str | None = None,
        sequential_placement: bool = True,
    ) -> list[VoiceGenerationResult]:
        """Generate voiceovers for multiple scenes."""

        scene_numbers = [blueprint.scene_number for blueprint in blueprints]

        if len(scene_numbers) != len(set(scene_numbers)):
            raise ValueError(
                "Duplicate voice blueprint scene numbers "
                "cannot be generated together."
            )

        results: list[VoiceGenerationResult] = []

        current_start_time = 0.0

        for blueprint in sorted(
            blueprints,
            key=lambda item: item.scene_number,
        ):
            start_time = current_start_time if sequential_placement else 0.0

            result = self.generate(
                blueprint,
                start_time_seconds=start_time,
                provider_name=provider_name,
            )

            results.append(result)

            if (
                sequential_placement
                and result.success
                and result.audio_track is not None
            ):
                current_start_time = (
                    result.audio_track.start_time_seconds
                    + result.audio_track.duration_seconds
                )

        return results

    def available_providers(
        self,
        *,
        healthy_only: bool = False,
    ) -> list[str]:
        """Return registered provider names."""

        names: list[str] = []

        for provider in self.providers:
            if healthy_only:
                try:
                    if not provider.health_check():
                        continue
                except Exception:
                    continue

            if provider.provider_name not in names:
                names.append(provider.provider_name)

        return sorted(
            names,
            key=str.lower,
        )

    def _select_provider(
        self,
        *,
        preferred_provider: str | None,
    ) -> VoiceProvider | None:
        """Select a requested or first healthy provider."""

        if preferred_provider is not None:
            normalized_preference = preferred_provider.strip().lower()

            for provider in self.providers:
                if provider.provider_name.strip().lower() == normalized_preference:
                    return provider

            return None

        for provider in self.providers:
            try:
                if provider.health_check():
                    return provider
            except Exception:
                continue

        return None

    @staticmethod
    def resolve_provider_voice(
        *,
        blueprint: ResolvedVoiceBlueprint,
        require_real_id: bool = False,
    ) -> str:
        """
        Resolve the voice identifier sent to a provider.

        Public (Post-Script-Approval Production Plan, Phase 9): also
        reused by VoiceProvider.generate_from_blueprint()'s default
        implementation, so both this service's own call site and
        every provider's fallback resolve a voice ID exactly the same
        way rather than maintaining two copies that could drift apart.

        require_real_id=False (the default, used by every existing
        caller and by DryRunVoiceProvider) preserves this method's
        original, permissive behavior exactly - falling back to
        `blueprint.profile.resolved_profile_id` (an internal profile
        id, e.g. "voice.horror_whisper") when nothing real is
        configured, which is harmless for a dry-run provider that
        never actually calls a real API with it.

        require_real_id=True is voice gap #1's (2026-09-09 audit)
        other real fix: a REAL provider (ElevenLabsVoiceProvider passes
        this) must never silently send that internal profile id to a
        real API as if it were a real voice_id - ElevenLabs would just
        reject it with a confusing error. Raising a clear, actionable
        ValueError here instead turns that into an honest, specific
        failure the caller's own exception handling already surfaces
        cleanly (see VoiceGenerationService.generate()'s broad
        except-and-fail wrapper around provider calls).
        """

        preferred_voice_id = blueprint.provider_preferences.preferred_voice_id

        if preferred_voice_id:
            return preferred_voice_id

        mapping_voice_id = blueprint.selected_provider_mapping.get("voice_id")

        if (
            isinstance(
                mapping_voice_id,
                str,
            )
            and mapping_voice_id.strip()
        ):
            return mapping_voice_id.strip()

        if require_real_id:
            raise ValueError(
                "No real provider voice_id is configured for voice "
                f"profile '{blueprint.profile.resolved_profile_id}'. "
                "Register one via VoiceProviderMappingService.set_voice_id() "
                "once a matching voice exists in the target account "
                '(e.g. added to ElevenLabs\' own "My Voices").'
            )

        return blueprint.profile.resolved_profile_id

    @staticmethod
    def _gain_db_to_linear(
        gain_db: float,
    ) -> float:
        """Convert decibel gain to linear volume."""

        linear_volume = 10 ** (gain_db / 20.0)

        return max(
            0.0,
            min(
                linear_volume,
                4.0,
            ),
        )

    def _attempt_speed_corrected_regeneration(
        self,
        *,
        provider: VoiceProvider,
        blueprint: ResolvedVoiceBlueprint,
        resolved_duration_seconds: float,
        available_seconds: float,
    ) -> tuple[str, float, float] | None:
        """
        Retry generation once at a faster speed when real narration
        overshoots its scene's video slot, so the trim fallback in
        run_job only ever has to absorb whatever this single bounded
        correction could not close.

        Returns (output_file, measured_duration_seconds,
        requested_speed) when a retry was attempted and produced a
        usable file - even if it still overshoots afterward, since a
        smaller trim is still strictly better than the original,
        larger one. Returns None when no retry was attempted at all
        (the overshoot is too small to be worth a second real
        provider call, or the blueprint's speed already has no real
        room left to correct within its own valid range) or when the
        retry itself failed to produce a usable file - run_job then
        falls back to trimming the original file exactly as before.
        """

        overshoot_seconds = resolved_duration_seconds - available_seconds

        if overshoot_seconds < self._MINIMUM_OVERSHOOT_TO_RETRY_SECONDS:
            return None

        # A TTS provider's own real narration pace does not scale
        # perfectly linearly with a requested speed multiplier
        # (pauses and breaths do not shrink at the same rate as
        # spoken words), so this is only a starting point, not a
        # guarantee - the real result is always measured afterward,
        # never trusted, which is what makes an imprecise estimate
        # safe to use here.
        required_multiplier = resolved_duration_seconds / available_seconds

        corrected_speed = min(
            self._MAXIMUM_RETRY_SPEED,
            blueprint.speed * required_multiplier,
        )

        if corrected_speed - blueprint.speed < self._MINIMUM_SPEED_CORRECTION_DELTA:
            return None

        retry_blueprint = blueprint.model_copy(update={"speed": corrected_speed})

        generated = self._generate_and_measure(
            provider=provider,
            blueprint=retry_blueprint,
        )

        if generated is None:
            return None

        normalized_retry_output_file, retry_measured_duration = generated

        return (
            normalized_retry_output_file,
            retry_measured_duration,
            corrected_speed,
        )

    def _attempt_condensed_regeneration(
        self,
        *,
        provider: VoiceProvider,
        blueprint: ResolvedVoiceBlueprint,
        available_seconds: float,
    ) -> tuple[str, float, str] | None:
        """
        Retry generation with the narration rewritten to fewer words
        (via self._narration_condensation_service), targeting
        available_seconds, when a speed-corrected retry still
        overshoots its scene's video slot - see
        NarrationCondensationService's own module docstring for why
        this exists as a real, content-preserving alternative to the
        sentence-drop fallback below.

        Returns (output_file, measured_duration_seconds,
        narration_text) for the condensed rewrite - even if it still
        overshoots afterward, since a smaller remaining overshoot is
        strictly better than the original for whatever fallback runs
        next. Returns None when condensation was not configured, the
        rewrite provider call failed, or the condensed narration
        still failed to produce a usable audio file - run_job then
        falls through to the sentence-drop fallback exactly as if
        this had never been attempted.
        """

        if self._narration_condensation_service is None:
            return None

        condensed_text = self._narration_condensation_service.condense(
            narration_text=blueprint.narration_text,
            available_seconds=available_seconds,
        )

        if condensed_text is None or not condensed_text.strip():
            return None

        retry_blueprint = blueprint.model_copy(
            update={"narration_text": condensed_text}
        )

        generated = self._generate_and_measure(
            provider=provider,
            blueprint=retry_blueprint,
        )

        if generated is None:
            return None

        normalized_output_file, measured_duration = generated

        return (normalized_output_file, measured_duration, condensed_text)

    def _attempt_sentence_trimmed_regeneration(
        self,
        *,
        provider: VoiceProvider,
        blueprint: ResolvedVoiceBlueprint,
        available_seconds: float,
    ) -> tuple[str, float, str] | None:
        """
        Retry generation with the narration's own trailing sentences
        dropped, one at a time, when a speed-corrected retry still
        overshoots its scene's video slot - see this class's own
        real-world-finding comment above _MAXIMUM_SENTENCE_DROP_ATTEMPTS
        for why a blind end-trim is not an acceptable fallback for a
        large overshoot (it can, and on a real render did, delete a
        sentence's own final word rather than just ending early).

        Returns (output_file, measured_duration_seconds,
        narration_text) for the *shortest* dropped version that
        actually fits, stopping as soon as one is found so the
        narration loses as little real content as possible. If none
        of the attempted versions fit, returns the best (least-
        dropped, smallest remaining overshoot) usable result instead
        of None, so run_job's existing hard-trim fallback still has
        less work left to do than it would on the original, un-
        shortened audio. Returns None only when no sentence could be
        dropped at all (a single-sentence narration) or every attempt
        failed to produce a usable file - run_job then falls back to
        trimming whatever result it already had.
        """

        sentences = self._split_into_sentences(blueprint.narration_text)

        if len(sentences) <= 1:
            return None

        best_result: tuple[str, float, str] | None = None

        max_drop_count = min(
            len(sentences) - 1,
            self._MAXIMUM_SENTENCE_DROP_ATTEMPTS,
        )

        for drop_count in range(1, max_drop_count + 1):
            shortened_text = " ".join(sentences[: len(sentences) - drop_count])

            retry_blueprint = blueprint.model_copy(
                update={"narration_text": shortened_text}
            )

            generated = self._generate_and_measure(
                provider=provider,
                blueprint=retry_blueprint,
            )

            if generated is None:
                continue

            normalized_output_file, measured_duration = generated

            best_result = (normalized_output_file, measured_duration, shortened_text)

            if measured_duration <= available_seconds:
                return best_result

        return best_result

    def _generate_and_measure(
        self,
        *,
        provider: VoiceProvider,
        blueprint: ResolvedVoiceBlueprint,
    ) -> tuple[str, float] | None:
        """
        Real-generate one blueprint and return its own measured real
        duration, or None on any failure along the way (provider
        error, empty/unsupported output, unmeasurable file) - the
        shared plumbing both overshoot-correction retries build on.
        """

        try:
            output_file = provider.generate_from_blueprint(blueprint)
        except Exception:
            return None

        cleaned_output_file = (
            output_file.strip() if isinstance(output_file, str) else ""
        )

        if not cleaned_output_file:
            return None

        normalized_output_file = Path(cleaned_output_file).as_posix()

        if (
            Path(normalized_output_file).suffix.lower()
            not in self.SUPPORTED_OUTPUT_FORMATS
        ):
            return None

        measured_duration = self._detect_duration_seconds(Path(normalized_output_file))

        if measured_duration is None or measured_duration <= 0.0:
            return None

        return normalized_output_file, measured_duration

    @classmethod
    def _split_into_sentences(cls, text: str) -> list[str]:
        """Split narration text into its own real sentences, by punctuation."""

        return [
            sentence.strip()
            for sentence in cls._SENTENCE_BOUNDARY_PATTERN.split(text.strip())
            if sentence.strip()
        ]

    @classmethod
    def _split_into_clauses(cls, text: str) -> list[str]:
        """Split one sentence into its own clauses, by comma/semicolon
        - one level finer than _split_into_sentences, for the single-
        sentence case _trim_text_to_estimated_duration's own fallback
        stage handles."""

        return [
            clause.strip()
            for clause in cls._CLAUSE_BOUNDARY_PATTERN.split(text.strip())
            if clause.strip()
        ]

    @classmethod
    def _trim_text_to_estimated_duration(
        cls,
        text: str,
        *,
        available_seconds: float,
        measured_duration_seconds: float,
    ) -> str:
        """
        No provider call - a cheap, arithmetic-only text trim so this
        blueprint's narration_text (what subtitle building reads,
        never the audio - already generated and already decided by
        the time this runs) never claims more speech than is left to
        play. Three stages:

        1. Drop trailing sentences until the estimate fits, same
           sentence-boundary safety _attempt_sentence_trimmed_regeneration
           already uses for the real audio.
        2. If even the single remaining sentence's own estimate still
           overshoots, drop trailing CLAUSES (split on comma/semicolon)
           the same way - a real render confirmed a pure word-count
           cut here can land mid-clause and produce a nonsensical
           dangling fragment ("...wheat prices collapsed and
           subsidies", with no verb; "Minister Pearce to", with no
           object) - since this text also becomes the real, final
           regeneration request downstream (the hard-clamp step that
           calls this method), that fragment does not just look wrong
           as a subtitle, it gets spoken aloud verbatim. Ending at a
           clause boundary instead keeps whatever remains a complete
           thought.
        3. Only if even the single remaining clause's own estimate
           still overshoots, drop trailing WORDS too - unlike the
           audio (where a mid-word cut sounds broken), text ending
           mid-clause is still far better than the alternative of
           leaving the full, still-overshooting clause attached, which
           would recreate the exact bug this trim exists to close.

        Deliberately extrapolates from this exact scene's own real,
        just-measured pace (measured_duration_seconds over this same
        text's own word count) rather than a generic WORDS_PER_SECOND
        constant - real TTS pacing for one specific utterance can run
        slower than that generic rate (confirmed the real cause of
        the render this fix targets: a condensed rewrite whose own
        generic-rate estimate already looked like it fit, while its
        real measured pace did not), so a generic-rate estimate here
        would silently miss exactly the case that needs catching.

        Real-world finding, 2026-09-19: confirmed on a real render -
        NarrationCondensationService's own rewrite frequently merges
        what were two sentences into one (no internal '.!?'), so
        "keep at least one sentence" alone still left an entire,
        still-overshooting sentence attached to the blueprint with no
        further recourse - stage 2 exists specifically for that case.
        """

        sentences = cls._split_into_sentences(text)

        if not sentences:
            return text

        total_words = sum(len(sentence.split()) for sentence in sentences)

        if total_words <= 0 or measured_duration_seconds <= 0.0:
            return text

        seconds_per_word = measured_duration_seconds / total_words

        kept_sentences = sentences[:1]

        for drop_count in range(len(sentences)):
            kept = sentences[: len(sentences) - drop_count]

            kept_words = sum(len(sentence.split()) for sentence in kept)

            if kept_words * seconds_per_word <= available_seconds:
                return " ".join(kept)

            kept_sentences = kept

        # Even just the first sentence alone still overshoots by
        # estimate - try dropping trailing CLAUSES within it before
        # falling all the way to a blind word-count cut, so whatever
        # remains still reads as a complete thought.
        target_text = kept_sentences[0]

        clauses = cls._split_into_clauses(target_text)

        if len(clauses) > 1:
            kept_clauses = clauses[:1]

            for drop_count in range(len(clauses)):
                kept = clauses[: len(clauses) - drop_count]

                kept_words = sum(len(clause.split()) for clause in kept)

                if kept_words * seconds_per_word <= available_seconds:
                    return " ".join(kept).rstrip(",;").rstrip()

                kept_clauses = kept

            target_text = kept_clauses[0]

        # Even just the first clause alone still overshoots by
        # estimate - fall through to a word-level trim of it, text
        # only (the real audio is already decided by this point).
        words = target_text.split()

        max_words = max(int(available_seconds / seconds_per_word), 1)

        if max_words >= len(words):
            return target_text.rstrip(",;").rstrip()

        return " ".join(words[:max_words]).rstrip(",;").rstrip()

    def _detect_duration_seconds(
        self,
        file_path: Path,
    ) -> float | None:
        """Return the real, measured duration of a generated audio file."""

        try:
            raw_output = self._ffprobe_runner(
                [
                    self.ffprobe_path,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(file_path),
                ]
            )
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return None

        cleaned = raw_output.strip()

        if not cleaned:
            return None

        try:
            return float(cleaned.splitlines()[0].strip())
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _fail(
        *,
        job: VoiceGenerationJob,
        reason: VoiceGenerationFailureReason,
        message: str,
        provider: str | None = None,
        recoverable: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> VoiceGenerationResult:
        """Return a normalized failed generation result."""

        failure = VoiceGenerationFailure(
            reason=reason,
            message=message,
            provider=provider,
            recoverable=recoverable,
            metadata=metadata or {},
        )

        job.status = VoiceGenerationStatus.FAILED
        job.failure = failure

        return VoiceGenerationResult(
            success=False,
            scene_number=job.scene_number,
            status=VoiceGenerationStatus.FAILED,
            provider=provider,
            attempts=job.attempts,
            failure=failure,
            warnings=list(job.warnings),
            metadata=dict(job.metadata),
        )
