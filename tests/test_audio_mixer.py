from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.render_result import RenderStatus
from src.services.audio_mixer import AudioMixer

timeline = AudioTimeline(
    tracks=[
        AudioTrack(
            track_type=AudioTrackType.VOICEOVER,
            source_file="outputs/audio/voiceover.wav",
            duration_seconds=60,
            volume=1.0,
            status=AudioTrackStatus.READY,
        ),
        AudioTrack(
            track_type=AudioTrackType.BACKGROUND_MUSIC,
            source_file="assets/music/mystery_theme.mp3",
            duration_seconds=60,
            volume=0.2,
            fade_in_seconds=2.0,
            fade_out_seconds=3.0,
            loop_enabled=True,
            duck_under_voice=True,
            status=AudioTrackStatus.READY,
        ),
        AudioTrack(
            track_type=AudioTrackType.SOUND_EFFECT,
            source_file="assets/sfx/underground_rumble.wav",
            start_time_seconds=5.0,
            duration_seconds=4.0,
            volume=0.7,
            status=AudioTrackStatus.READY,
        ),
    ]
)

mixer = AudioMixer()
result = mixer.mix(timeline)

print("Success:", result.success)
print("Status:", result.status)
print("Engine:", result.render_engine)
print("Duration:", result.duration_seconds)
print("Output:", result.output_file)
print("Warnings:", result.warnings)

assert result.success is True
assert result.status == RenderStatus.COMPLETED
assert result.output_file == "outputs/audio/final_mix.wav"
assert result.duration_seconds == 60

print("Audio Mixer tests completed successfully.")
