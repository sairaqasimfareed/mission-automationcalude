from __future__ import annotations

from src.models.audio_timeline import (
    AudioTimeline,
)
from src.models.audio_track import (
    AudioTrack,
    AudioTrackStatus,
    AudioTrackType,
)
from src.models.voice_generation import (
    VoiceGenerationFailure,
    VoiceGenerationFailureReason,
    VoiceGenerationResult,
    VoiceGenerationStatus,
)
from src.models.voice_timeline_validation import (
    VoiceTimelineValidationCode,
)
from src.services.voice_timeline_service import (
    VoiceTimelineService,
)


def build_success_result(
    *,
    scene_number: int,
    start_time_seconds: float,
    duration_seconds: float,
    file_name: str,
) -> VoiceGenerationResult:
    track = AudioTrack(
        track_type=AudioTrackType.VOICEOVER,
        source_file=(
            "outputs/audio/"
            f"{file_name}"
        ),
        start_time_seconds=(
            start_time_seconds
        ),
        duration_seconds=duration_seconds,
        provider="Dummy Voice",
        license_type="generated",
        status=AudioTrackStatus.READY,
        metadata={
            "scene_number": scene_number,
            "voice_profile_id": (
                "voice.neutral_narrator"
            ),
        },
    )

    return VoiceGenerationResult(
        success=True,
        scene_number=scene_number,
        status=(
            VoiceGenerationStatus.COMPLETED
        ),
        provider="Dummy Voice",
        output_file=track.source_file,
        audio_track=track,
        attempts=1,
    )


service = VoiceTimelineService()

timeline = AudioTimeline()

scene_1_result = build_success_result(
    scene_number=1,
    start_time_seconds=0.0,
    duration_seconds=4.0,
    file_name="scene_001.wav",
)

scene_2_result = build_success_result(
    scene_number=2,
    start_time_seconds=4.0,
    duration_seconds=5.0,
    file_name="scene_002.wav",
)


attached_scene_1 = service.attach_result(
    timeline,
    result=scene_1_result,
)

assert (
    attached_scene_1.track_type
    == AudioTrackType.VOICEOVER
)

assert (
    attached_scene_1.metadata[
        "scene_number"
    ]
    == 1
)

assert (
    attached_scene_1.metadata[
        "timeline_attached"
    ]
    is True
)

assert len(timeline.tracks) == 1

assert (
    timeline.calculate_duration()
    == 4.0
)


attached_scene_2 = service.attach_result(
    timeline,
    result=scene_2_result,
)

assert len(timeline.tracks) == 2

assert (
    timeline.calculate_duration()
    == 9.0
)

assert (
    service.voice_scene_numbers(
        timeline
    )
    == [
        1,
        2,
    ]
)


valid_result = service.validate(
    timeline,
    expected_scene_numbers=[
        1,
        2,
    ],
    require_gap_free=True,
)

print(
    "Voice timeline valid:",
    valid_result.is_valid,
)

print(
    "Voice tracks:",
    valid_result.voice_track_count,
)

print(
    "Duration:",
    valid_result.total_duration_seconds,
)

assert valid_result.is_valid is True
assert valid_result.errors == []
assert valid_result.voice_track_count == 2
assert valid_result.unique_scene_count == 2
assert valid_result.gap_duration_seconds == 0.0
assert (
    valid_result.overlap_duration_seconds
    == 0.0
)


try:
    service.attach_result(
        timeline,
        result=scene_1_result,
    )
except ValueError:
    print(
        "Duplicate voice scene "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Duplicate voice scenes should fail."
    )


replacement_result = build_success_result(
    scene_number=2,
    start_time_seconds=4.0,
    duration_seconds=6.0,
    file_name="scene_002_replacement.wav",
)

replacement_track = service.replace_result(
    timeline,
    result=replacement_result,
)

assert (
    replacement_track.source_file
    == (
        "outputs/audio/"
        "scene_002_replacement.wav"
    )
)

assert len(timeline.tracks) == 2

assert (
    service.get_scene_voice(
        timeline,
        scene_number=2,
    ).duration_seconds
    == 6.0
)

assert (
    timeline.calculate_duration()
    == 10.0
)


removed_track = service.remove_scene_voice(
    timeline,
    scene_number=2,
)

assert (
    removed_track.metadata[
        "scene_number"
    ]
    == 2
)

assert len(timeline.tracks) == 1

assert (
    service.missing_voice_scenes(
        timeline,
        expected_scene_numbers=[
            1,
            2,
        ],
    )
    == [
        2,
    ]
)


missing_result = service.validate(
    timeline,
    expected_scene_numbers=[
        1,
        2,
    ],
)

assert missing_result.is_valid is False

assert (
    missing_result.missing_scene_numbers
    == [
        2,
    ]
)

assert any(
    issue.code
    == VoiceTimelineValidationCode
    .MISSING_EXPECTED_SCENE
    for issue in missing_result.errors
)


multi_timeline = AudioTimeline()

multi_results = [
    build_success_result(
        scene_number=3,
        start_time_seconds=7.0,
        duration_seconds=3.0,
        file_name="scene_003.wav",
    ),
    build_success_result(
        scene_number=1,
        start_time_seconds=0.0,
        duration_seconds=4.0,
        file_name="scene_001.wav",
    ),
    build_success_result(
        scene_number=2,
        start_time_seconds=4.0,
        duration_seconds=3.0,
        file_name="scene_002.wav",
    ),
]

attached_many = service.attach_many(
    multi_timeline,
    results=multi_results,
)

assert len(attached_many) == 3

assert [
    track.metadata["scene_number"]
    for track in service.voice_tracks(
        multi_timeline
    )
] == [
    1,
    2,
    3,
]

multi_validation = service.validate(
    multi_timeline,
    expected_scene_numbers=[
        1,
        2,
        3,
    ],
    require_gap_free=True,
)

assert multi_validation.is_valid is True
assert (
    multi_timeline.calculate_duration()
    == 10.0
)


gap_timeline = AudioTimeline()

service.attach_many(
    gap_timeline,
    results=[
        build_success_result(
            scene_number=1,
            start_time_seconds=0.0,
            duration_seconds=4.0,
            file_name="gap_001.wav",
        ),
        build_success_result(
            scene_number=2,
            start_time_seconds=6.0,
            duration_seconds=3.0,
            file_name="gap_002.wav",
        ),
    ],
)

gap_warning_result = service.validate(
    gap_timeline,
)

assert gap_warning_result.is_valid is True

assert (
    gap_warning_result
    .gap_duration_seconds
    == 2.0
)

assert any(
    issue.code
    == VoiceTimelineValidationCode.VOICE_GAP
    for issue in gap_warning_result.warnings
)


gap_error_result = service.validate(
    gap_timeline,
    require_gap_free=True,
)

assert gap_error_result.is_valid is False

assert any(
    issue.code
    == VoiceTimelineValidationCode.VOICE_GAP
    for issue in gap_error_result.errors
)


overlap_timeline = AudioTimeline()

service.attach_many(
    overlap_timeline,
    results=[
        build_success_result(
            scene_number=1,
            start_time_seconds=0.0,
            duration_seconds=5.0,
            file_name="overlap_001.wav",
        ),
        build_success_result(
            scene_number=2,
            start_time_seconds=4.0,
            duration_seconds=3.0,
            file_name="overlap_002.wav",
        ),
    ],
)

overlap_result = service.validate(
    overlap_timeline,
)

assert overlap_result.is_valid is False

assert (
    overlap_result
    .overlap_duration_seconds
    == 1.0
)

assert any(
    issue.code
    == VoiceTimelineValidationCode
    .VOICE_OVERLAP
    for issue in overlap_result.errors
)


allowed_overlap_result = (
    service.validate(
        overlap_timeline,
        allow_voice_overlap=True,
    )
)

assert allowed_overlap_result.is_valid is True

assert any(
    issue.code
    == VoiceTimelineValidationCode
    .VOICE_OVERLAP
    for issue in (
        allowed_overlap_result.warnings
    )
)


failed_generation_result = (
    VoiceGenerationResult(
        success=False,
        scene_number=10,
        status=(
            VoiceGenerationStatus.FAILED
        ),
        attempts=1,
        failure=VoiceGenerationFailure(
            reason=(
                VoiceGenerationFailureReason
                .PROVIDER_ERROR
            ),
            message=(
                "Simulated voice generation failure."
            ),
            provider="Dummy Voice",
        ),
    )
)

try:
    service.attach_result(
        AudioTimeline(),
        result=failed_generation_result,
    )
except ValueError:
    print(
        "Failed voice generation result "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Failed generation results "
        "should not be attached."
    )


mismatched_track = AudioTrack(
    track_type=AudioTrackType.VOICEOVER,
    source_file=(
        "outputs/audio/mismatch.wav"
    ),
    duration_seconds=4.0,
    status=AudioTrackStatus.READY,
    metadata={
        "scene_number": 99,
    },
)

mismatched_result = (
    VoiceGenerationResult(
        success=True,
        scene_number=11,
        status=(
            VoiceGenerationStatus.COMPLETED
        ),
        provider="Dummy Voice",
        output_file=(
            "outputs/audio/mismatch.wav"
        ),
        audio_track=mismatched_track,
        attempts=1,
    )
)

try:
    service.attach_result(
        AudioTimeline(),
        result=mismatched_result,
    )
except ValueError:
    print(
        "Mismatched voice scene metadata "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Mismatched scene metadata "
        "should fail."
    )


empty_timeline_result = service.validate(
    AudioTimeline()
)

assert empty_timeline_result.is_valid is False

assert any(
    issue.code
    == VoiceTimelineValidationCode
    .NO_VOICE_TRACKS
    for issue in empty_timeline_result.errors
)


print(
    "Voice Timeline Service tests "
    "completed successfully."
)