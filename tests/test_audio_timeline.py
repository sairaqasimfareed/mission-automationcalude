from src.models.audio_timeline import AudioTimeline
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)

voice = AudioTrack(
    track_type=AudioTrackType.VOICEOVER,
    source_file="voice.wav",
    duration_seconds=60,
    status=AudioTrackStatus.READY,
)

music = AudioTrack(
    track_type=AudioTrackType.BACKGROUND_MUSIC,
    source_file="music.mp3",
    duration_seconds=60,
    volume=0.2,
    status=AudioTrackStatus.READY,
)

effect = AudioTrack(
    track_type=AudioTrackType.SOUND_EFFECT,
    source_file="boom.wav",
    start_time_seconds=18,
    duration_seconds=4,
    status=AudioTrackStatus.READY,
)

timeline = AudioTimeline(
    tracks=[
        voice,
        music,
        effect,
    ]
)

duration = timeline.calculate_duration()

print("Tracks:", len(timeline.tracks))
print("Duration:", duration)
print("Sample Rate:", timeline.sample_rate)
print("Channels:", timeline.channels)

assert len(timeline.tracks) == 3
assert duration == 60

print("Audio Timeline tests completed successfully.")
