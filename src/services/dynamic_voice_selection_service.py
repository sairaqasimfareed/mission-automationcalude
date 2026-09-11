from __future__ import annotations

from src.models.voice_directives import VoiceEmotion, VoicePitchStyle
from src.models.voice_profile import VoiceProfile
from src.providers.elevenlabs_voice_search_client import ElevenLabsVoiceSearchClient
from src.services.http.http_provider_executor import HttpProviderExecutionError
from src.services.voice_search_query_builder import build_voice_search_terms


class DynamicVoiceSelectionService:
    """
    Real fix for "don't hardcode a specific voice against a genre, I
    want it to be flexible" (2026-09-11): rather than requiring a
    human to pre-register a voice_id per profile through Voice
    Manager before generation can run, select a real candidate live
    from ElevenLabs' own catalog at resolution time - using the
    profile's own recommended tags plus whatever emotion/pitch_style
    the actual scene directive carries (often LLM-produced, free to
    vary scene-to-scene and project-to-project) rather than a single
    fixed value baked into a genre.

    This makes the same genre profile legitimately resolve to
    different real voices across different projects, or even
    different scenes within one project, as the LLM's own directives
    vary - the whole point being that nothing is hardcoded anywhere
    in this codebase.

    A manual pin registered via VoiceProviderMappingService (Voice
    Manager's Save button) still takes priority over this when one
    exists - VoiceDirectiveResolutionService only calls this service
    when no earlier resolution tier already produced a voice_id, so a
    user who deliberately wants one fixed voice for a profile keeps
    that ability; this service only fills the gap when nothing was
    pinned.

    Caches by (profile_id, emotion, pitch_style) for this instance's
    lifetime, so every scene in one render run that shares the same
    effective style reuses the same real voice_id (consistent
    narration within a project, and no redundant ElevenLabs API calls
    for what is, in effect, an identical query) rather than each scene
    searching independently and risking drift or wasted calls.

    Any real search failure (network error, HTTP error, no candidates
    found) resolves to None rather than raising - this is an optional,
    best-effort resolution tier; a caller with require_real_id=True
    downstream still raises its own clear error if nothing at all
    resolved a voice_id, exactly as before this service existed.
    """

    def __init__(self, *, search_client: ElevenLabsVoiceSearchClient) -> None:
        self._search_client = search_client
        self._cache: dict[tuple[str, str, str], str | None] = {}

    def select_voice_id(
        self,
        *,
        profile: VoiceProfile,
        emotion: VoiceEmotion,
        pitch_style: VoicePitchStyle,
    ) -> str | None:
        cache_key = (profile.profile_id, emotion.value, pitch_style.value)

        if cache_key in self._cache:
            return self._cache[cache_key]

        voice_id = self._select_voice_id_uncached(
            profile=profile,
            emotion=emotion,
            pitch_style=pitch_style,
        )

        self._cache[cache_key] = voice_id

        return voice_id

    def _select_voice_id_uncached(
        self,
        *,
        profile: VoiceProfile,
        emotion: VoiceEmotion,
        pitch_style: VoicePitchStyle,
    ) -> str | None:
        terms = build_voice_search_terms(
            profile,
            emotion=emotion,
            pitch_style=pitch_style,
        )

        if not terms:
            return None

        try:
            results = self._search_client.suggest(terms=terms)
        except (HttpProviderExecutionError, ValueError):
            return None

        if not results:
            return None

        return results[0].voice_id
