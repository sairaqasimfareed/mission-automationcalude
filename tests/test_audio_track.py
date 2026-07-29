from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)


voice_track = AudioTrack(
    track_type=AudioTrackType.VOICEOVER,
    source_file="outputs/audio/voiceover.wav",
    duration_seconds=60.0,
    volume=1.0,
    provider="ElevenLabs",
    status=AudioTrackStatus.READY,
)

music_track = AudioTrack(
    track_type=AudioTrackType.BACKGROUND_MUSIC,
    source_file="assets/music/mystery_theme.mp3",
    duration_seconds=60.0,
    volume=0.2,
    fade_in_seconds=2.0,
    fade_out_seconds=3.0,
    loop_enabled=True,
    duck_under_voice=True,
    license_type="royalty_free",
    status=AudioTrackStatus.READY,
)

sfx_track = AudioTrack(
    track_type=AudioTrackType.SOUND_EFFECT,
    source_file="assets/sfx/underground_rumble.wav",
    start_time_seconds=5.0,
    duration_seconds=4.0,
    volume=0.7,
    status=AudioTrackStatus.READY,
)

print("Voice:", voice_track.track_type, voice_track.volume)
print("Music:", music_track.track_type, music_track.volume)
print("SFX:", sfx_track.track_type, sfx_track.start_time_seconds)

assert voice_track.status == AudioTrackStatus.READY
assert music_track.duck_under_voice is True
assert sfx_track.start_time_seconds == 5.0

print("Audio Track tests completed successfully.")