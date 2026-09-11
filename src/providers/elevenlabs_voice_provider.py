from __future__ import annotations

import base64
import json
from pathlib import Path
from uuid import uuid4

from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryLocator,
)
from src.models.elevenlabs_voice_alignment import (
    ElevenLabsVoiceCharacterAlignment,
    ElevenLabsVoiceWithTimestampsResult,
)
from src.models.elevenlabs_voice_request import ElevenLabsVoiceRequest
from src.models.provider_profile import ProviderProfile
from src.models.resolved_voice_blueprint import ResolvedVoiceBlueprint
from src.providers.elevenlabs_pronunciation_dictionary_client import (
    ElevenLabsPronunciationDictionaryClient,
)
from src.providers.voice_provider import VoiceProvider
from src.services.elevenlabs_voice_translation_service import (
    ElevenLabsVoiceTranslationService,
)
from src.services.http.http_provider_executor import (
    HttpProviderExecutionError,
    PreparedHttpRequest,
    Transport,
    default_transport,
)
from src.services.voice_generation_service import VoiceGenerationService
from src.services.voice_pitch_shift_service import VoicePitchShiftService
from src.shared.logger import logger

_DEFAULT_BASE_URL = "https://api.elevenlabs.io"
_DEFAULT_MODEL_ID = "eleven_multilingual_v2"
_DEFAULT_OUTPUT_DIRECTORY = Path("data/voice_output")


class ElevenLabsVoiceProvider(VoiceProvider):
    """
    Real ElevenLabs text-to-speech adapter.

    Calls POST /v1/text-to-speech/{voice_id} with an xi-api-key header
    and a JSON body, expecting a raw audio/mpeg response - the shape
    documented in ElevenLabs' TTS API.

    Partially verified against a real, live ElevenLabs account
    (2026-09-08): a real call with a valid key reached ElevenLabs and
    got back a real HTTP 402 (Payment Required) across every model_id
    tried (eleven_multilingual_v2, eleven_turbo_v2_5,
    eleven_flash_v2_5), not a 401/404 or a malformed-request error -
    the endpoint path, auth header, and request shape are confirmed
    accepted by ElevenLabs. The precise cause (from ElevenLabs' own
    error body, not assumed): "Free users cannot use library voices
    via the API" - an account-plan restriction on that account's Free
    tier specific to shared/library voice ids, unrelated to remaining
    credit balance (the account had 9,900+ credits free at the time).
    Re-verify generate_voice()/generate_from_blueprint() end to end
    once tested against a voice actually owned by the account (a
    cloned/added "My Voices" entry) or a paid plan.
    """

    def __init__(
        self,
        *,
        profile: ProviderProfile,
        api_key: str,
        transport: Transport | None = None,
        output_directory: str | Path = _DEFAULT_OUTPUT_DIRECTORY,
        model_id: str = _DEFAULT_MODEL_ID,
        translation_service: ElevenLabsVoiceTranslationService | None = None,
        pronunciation_dictionary_client: (
            ElevenLabsPronunciationDictionaryClient | None
        ) = None,
        pitch_shift_service: VoicePitchShiftService | None = None,
    ) -> None:
        self._profile = profile
        self._api_key = api_key
        self._transport = transport or default_transport
        self._output_directory = Path(output_directory)
        self._model_id = model_id
        self._base_url = (profile.base_url or _DEFAULT_BASE_URL).rstrip("/")
        # Post-Script-Approval Production Plan, Phase 9.
        self._translation_service = (
            translation_service or ElevenLabsVoiceTranslationService()
        )
        # Voice gap #5 (2026-09-09 audit) - real pronunciation
        # dictionaries. Shares this provider's own api_key/base_url/
        # transport so tests can fake both HTTP calls the same way.
        self._pronunciation_dictionary_client = (
            pronunciation_dictionary_client
            or ElevenLabsPronunciationDictionaryClient(
                api_key=api_key,
                base_url=self._base_url,
                transport=self._transport,
                timeout_seconds=float(profile.timeout_seconds),
            )
        )
        # Voice gap #3 (2026-09-09 audit) - real FFmpeg pitch
        # post-processing. ElevenLabs has no pitch control in its API
        # at all, on any model, so this runs after generation, on the
        # already-downloaded audio file.
        self._pitch_shift_service = pitch_shift_service or VoicePitchShiftService()

    @property
    def provider_name(self) -> str:
        return self._profile.provider_name

    def health_check(self) -> bool:
        return True

    def generate_voice(self, text: str, voice: str) -> str:
        return self._call_text_to_speech(
            voice_id=voice,
            json_body={"text": text, "model_id": self._model_id},
        )

    def generate_from_blueprint(self, blueprint: ResolvedVoiceBlueprint) -> str:
        """
        Post-Script-Approval Production Plan, Phase 9: "The voice
        provider must consume a translated ResolvedVoiceBlueprint
        rather than only raw narration text." Overrides the base
        class's plain-text fallback with a real translation.

        See _build_request_and_json_body() for how the real request is
        assembled (translation, pronunciation dictionaries, request
        stitching) - shared verbatim with
        generate_from_blueprint_with_timestamps() below.
        """

        _request, json_body = self._build_request_and_json_body(blueprint)

        output_file = self._call_text_to_speech(
            voice_id=_request.voice_id,
            json_body=json_body,
        )

        return self._apply_pitch_shift_if_requested(
            output_file,
            blueprint=blueprint,
        )

    def generate_from_blueprint_with_timestamps(
        self, blueprint: ResolvedVoiceBlueprint
    ) -> ElevenLabsVoiceWithTimestampsResult:
        """
        Voice gap #8 (2026-09-09 audit): real character-level timing
        data, via ElevenLabs' real, separate text-to-speech-with-
        timestamps endpoint (POST /v1/text-to-speech/{voice_id}/
        with-timestamps - verified directly against ElevenLabs' own
        current API documentation, not assumed). Never requested
        anywhere in this codebase before now - this is an additive
        method, not a replacement for generate_from_blueprint(), since
        most callers don't need per-character timing and the plain
        endpoint is the simpler, already-proven path for them.

        Builds and sends the exact same real request
        generate_from_blueprint() does (same translation, same
        pronunciation-dictionary/stitching handling, same pitch-shift
        post-processing) - only the endpoint and response shape
        differ, since /with-timestamps returns the audio base64-
        encoded inside a JSON body alongside the alignment data,
        rather than as a raw audio/mpeg response body.
        """

        _request, json_body = self._build_request_and_json_body(blueprint)

        response_data = self._call_text_to_speech_with_timestamps(
            voice_id=_request.voice_id,
            json_body=json_body,
        )

        audio_base64 = response_data.get("audio_base64")

        if not isinstance(audio_base64, str) or not audio_base64:
            raise HttpProviderExecutionError(
                "ElevenLabs text-to-speech-with-timestamps response was "
                "missing audio_base64."
            )

        try:
            audio_bytes = base64.b64decode(audio_base64)
        except (ValueError, TypeError) as error:
            raise HttpProviderExecutionError(
                "ElevenLabs text-to-speech-with-timestamps returned "
                "undecodable audio_base64."
            ) from error

        output_file = self._write_audio_bytes(audio_bytes)

        output_file = self._apply_pitch_shift_if_requested(
            output_file,
            blueprint=blueprint,
        )

        return ElevenLabsVoiceWithTimestampsResult(
            output_file=output_file,
            alignment=self._parse_alignment(response_data.get("alignment")),
            normalized_alignment=self._parse_alignment(
                response_data.get("normalized_alignment")
            ),
        )

    def _build_request_and_json_body(
        self, blueprint: ResolvedVoiceBlueprint
    ) -> tuple[ElevenLabsVoiceRequest, dict[str, object]]:
        """
        Shared request-building logic for both the plain and
        with-timestamps endpoints (voice gap #8, 2026-09-09 audit) -
        extracted so the two real ElevenLabs endpoints this provider
        calls always build their request the exact same way, rather
        than maintaining two copies that could silently drift apart.

        Post-Script-Approval Production Plan, Phase 9: "The voice
        provider must consume a translated ResolvedVoiceBlueprint
        rather than only raw narration text." Every supported
        blueprint property ElevenLabsVoiceTranslationService can map
        becomes part of the request; everything it can't is simply
        absent from `voice_settings` rather than silently lost without
        a trace (see that service's own `unsupported_controls` list,
        carried on the returned request for a caller to log or
        surface).

        Voice gap #5 (2026-09-09 audit): when the blueprint carries
        pronunciation directives, a real ElevenLabs pronunciation
        dictionary is created first (its own, separate API call - a
        TTS request can only reference an already-created dictionary,
        never inline rules), and its locator is passed into
        translate() so the real request actually applies it. Dictionary
        creation failing is deliberately non-fatal to voice generation
        itself - losing a pronunciation nuance is a much smaller
        problem than losing the whole scene's narration over it; the
        real failure reason is appended to `unsupported_controls`
        instead of being silently swallowed.
        """

        # Voice gap #1 (2026-09-09 audit): a real provider must never
        # silently send an internal profile id (e.g.
        # "voice.horror_whisper") to ElevenLabs as if it were a real
        # voice_id - require_real_id=True turns that into a clear,
        # actionable error instead of a confusing rejection from
        # ElevenLabs itself.
        voice_id = VoiceGenerationService.resolve_provider_voice(
            blueprint=blueprint, require_real_id=True
        )

        pronunciation_dictionary_locators: list[
            ElevenLabsPronunciationDictionaryLocator
        ] = []
        pronunciation_dictionary_failure: str | None = None

        if blueprint.pronunciation_directives:
            try:
                locator = self._pronunciation_dictionary_client.create_from_directives(
                    blueprint.pronunciation_directives,
                    name=f"scene-{blueprint.scene_number}-pronunciation",
                )
                pronunciation_dictionary_locators = [locator]
            except (HttpProviderExecutionError, ValueError) as error:
                pronunciation_dictionary_failure = (
                    f"pronunciation dictionary creation failed: {error}"
                )

        request = self._translation_service.translate(
            blueprint,
            voice_id=voice_id,
            model_id=self._model_id,
            pronunciation_dictionary_locators=pronunciation_dictionary_locators,
        )

        if pronunciation_dictionary_failure:
            request.unsupported_controls.append(pronunciation_dictionary_failure)

        json_body: dict[str, object] = {
            "text": request.text,
            "model_id": request.model_id,
            # 2026-09-11 real fix, found live: a bare .model_dump()
            # here included MissionBaseModel's own inherited id/
            # created_at/updated_at fields alongside the real
            # ElevenLabsVoiceSettings ones - id (a UUID) isn't JSON
            # serializable by requests' plain json.dumps() at all, so
            # every real voice generation call failed with a real
            # TypeError, silently flattened by VoiceGenerationService's
            # own broad except-and-fail wrapper into a generic "Voice
            # provider failed during audio generation." with no
            # visible cause. Scoped to exactly the fields
            # ElevenLabsVoiceSettings' own docstring promises are real,
            # documented ElevenLabs parameters - the same include=
            # pattern already used a few lines below for
            # pronunciation_dictionary_locators, just missed here.
            "voice_settings": request.voice_settings.model_dump(
                include={
                    "stability",
                    "similarity_boost",
                    "style",
                    "use_speaker_boost",
                    "speed",
                }
            ),
        }

        if request.pronunciation_dictionary_locators:
            json_body["pronunciation_dictionary_locators"] = [
                locator.model_dump(
                    include={"pronunciation_dictionary_id", "version_id"}
                )
                for locator in request.pronunciation_dictionary_locators
            ]

        # Voice gap #9 (2026-09-09 audit) - real request stitching.
        # Only ever set together with a non-v3 model_id (see
        # ElevenLabsVoiceTranslationService), so no need to guard
        # against sending these alongside eleven_v3.
        if request.previous_text:
            json_body["previous_text"] = request.previous_text

        if request.next_text:
            json_body["next_text"] = request.next_text

        return request, json_body

    @staticmethod
    def _parse_alignment(
        raw_alignment: object,
    ) -> ElevenLabsVoiceCharacterAlignment | None:
        if not isinstance(raw_alignment, dict):
            return None

        return ElevenLabsVoiceCharacterAlignment(
            characters=raw_alignment.get("characters", []),
            character_start_times_seconds=raw_alignment.get(
                "character_start_times_seconds", []
            ),
            character_end_times_seconds=raw_alignment.get(
                "character_end_times_seconds", []
            ),
        )

    def _apply_pitch_shift_if_requested(
        self,
        output_file: str,
        *,
        blueprint: ResolvedVoiceBlueprint,
    ) -> str:
        """
        Voice gap #3 (2026-09-09 audit): apply a real FFmpeg pitch
        shift to the just-generated audio file when the blueprint
        requests one. Deliberately non-fatal, same discipline as
        pronunciation-dictionary creation failures - losing a pitch
        adjustment is a much smaller problem than losing the whole
        scene's narration over it. A failure is logged, not silently
        swallowed, and the unshifted (but otherwise complete) audio is
        still returned.
        """

        if blueprint.pitch_adjustment == 0.0:
            return output_file

        result = self._pitch_shift_service.apply(
            Path(output_file),
            semitones=blueprint.pitch_adjustment,
        )

        if not result.success:
            logger.warning(
                "Voice pitch shift failed for scene %s (%s semitones): %s. "
                "Returning the unshifted audio instead.",
                blueprint.scene_number,
                blueprint.pitch_adjustment,
                result.error_message,
            )
            return output_file

        return result.output_file or output_file

    def _call_text_to_speech(
        self, *, voice_id: str, json_body: dict[str, object]
    ) -> str:
        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body=json_body,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                f"ElevenLabs text-to-speech request failed with HTTP "
                f"{response.status_code}."
            )

        return self._write_audio_bytes(response.content)

    def _call_text_to_speech_with_timestamps(
        self, *, voice_id: str, json_body: dict[str, object]
    ) -> dict[str, object]:
        """
        Voice gap #8 (2026-09-09 audit): the real, separate
        with-timestamps endpoint - same auth/JSON-body shape as the
        plain endpoint, but a different URL and a JSON response
        (audio_base64 + alignment + normalized_alignment) instead of a
        raw audio/mpeg body.
        """

        request = PreparedHttpRequest(
            method="POST",
            url=f"{self._base_url}/v1/text-to-speech/{voice_id}/with-timestamps",
            headers={
                "xi-api-key": self._api_key,
                "Content-Type": "application/json",
            },
            json_body=json_body,
            timeout_seconds=float(self._profile.timeout_seconds),
        )

        response = self._transport(request)

        if response.status_code >= 400:
            raise HttpProviderExecutionError(
                "ElevenLabs text-to-speech-with-timestamps request failed "
                f"with HTTP {response.status_code}."
            )

        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError as error:
            raise HttpProviderExecutionError(
                "ElevenLabs text-to-speech-with-timestamps returned a "
                "non-JSON response."
            ) from error

        if not isinstance(parsed, dict):
            raise HttpProviderExecutionError(
                "ElevenLabs text-to-speech-with-timestamps response was "
                "not a JSON object."
            )

        return parsed

    def _write_audio_bytes(self, audio_bytes: bytes) -> str:
        self._output_directory.mkdir(parents=True, exist_ok=True)
        destination = self._output_directory / f"{uuid4()}.mp3"
        destination.write_bytes(audio_bytes)

        return str(destination.resolve())
