"""The Character-Oriented Video preset (project-level, genre-independent).

A project whose script is `NAME: line` dialogue spoken on camera by characters, lip-synced by the
video provider, needs these settings together:

- the clip's own audio IS the speech: native clip audio on, the ElevenLabs voiceover off at the
  final mix. The voiceover is still generated - its measured length is what sizes each clip - and
  music and sound effects are left as the operator had them;
- the pause after each line is off: characters' lines already run into each other on camera, and a
  silent hold after a line would only be dead air in the clip;
- the video provider is Muse, the one this mode was tested on (lip sync, face, outfit and voice
  continuity with a reference picture). Flow also generated lip-synced speech in an earlier test
  but is not the target.

Applied when the project is created, before any script exists.
"""

from __future__ import annotations

from src.models.audio_inclusion_preferences import AudioInclusionPreferences
from src.models.video_job import VideoJob
from src.models.video_provider import VideoProvider


def apply_character_mode_preset(job: VideoJob) -> VideoJob:
    current = job.audio_inclusion_preferences

    job.character_oriented = True
    job.audio_inclusion_preferences = AudioInclusionPreferences(
        include_native_clip_audio=True,
        include_voiceover=False,
        include_music=current.include_music,
        include_sound_effects=current.include_sound_effects,
    )
    job.scene_hold_seconds = 0.0
    job.video_provider = VideoProvider.MUSE

    return job
