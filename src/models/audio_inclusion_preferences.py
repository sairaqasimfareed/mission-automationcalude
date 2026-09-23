from __future__ import annotations

from src.models.audio_track import AudioTrackType
from src.models.base import MissionBaseModel


class AudioInclusionPreferences(MissionBaseModel):
    """
    REQ-10(a): four independent, combinable per-project audio-source
    toggles - deliberately NOT coupled to genre (a POV-style scene can
    occur inside an ordinary genre, e.g. History, not just a dedicated
    Survival genre - see cinematic_touch_requirements memory).

    Design refined 2026-09-21: these are MUX-TIME deselects, not
    pre-generation skips. Voiceover, music, and SFX generation all
    still run unconditionally regardless of these flags - see
    SceneClipSplitPlanningService's own real dependency on
    Scene.real_narration_duration_seconds for why skipping narration
    generation isn't safe. These toggles only decide which already-
    generated AudioTrack entries reach REQ-00 Stage 2's mux - see
    filter_audio_timeline_for_mux().

    include_native_clip_audio defaults to False (opt-in, new
    capability, requires NativeClipAudioExtractionService to have
    actually populated a NATIVE_CLIP track for a scene). The other
    three default to True, matching today's real behavior (every
    generated track type is included) so an existing job's implicit
    preferences never change under it.
    """

    include_native_clip_audio: bool = False
    include_voiceover: bool = True
    include_music: bool = True
    include_sound_effects: bool = True

    def allowed_track_types(self) -> set[AudioTrackType]:
        """Return the AudioTrackType values this preference set allows."""

        allowed: set[AudioTrackType] = set()

        if self.include_native_clip_audio:
            allowed.add(AudioTrackType.NATIVE_CLIP)

        if self.include_voiceover:
            allowed.add(AudioTrackType.VOICEOVER)

        if self.include_music:
            allowed.add(AudioTrackType.BACKGROUND_MUSIC)

        if self.include_sound_effects:
            allowed.add(AudioTrackType.SOUND_EFFECT)

        return allowed
