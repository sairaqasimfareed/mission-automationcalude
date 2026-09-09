from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from src.models.elevenlabs_pronunciation_dictionary import (
    ElevenLabsPronunciationDictionaryLocator,
)
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
        class's plain-text fallback with a real translation - every
        supported blueprint property ElevenLabsVoiceTranslationService
        can map becomes part of the request; everything it can't is
        simply absent from `voice_settings` rather than silently lost
        without a trace (see that service's own `unsupported_controls`
        list, carried on the returned request for a caller to log or
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
            "voice_settings": request.voice_settings.model_dump(),
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

        return self._call_text_to_speech(
            voice_id=request.voice_id,
            json_body=json_body,
        )

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

        self._output_directory.mkdir(parents=True, exist_ok=True)
        destination = self._output_directory / f"{uuid4()}.mp3"
        destination.write_bytes(response.content)

        return str(destination.resolve())
