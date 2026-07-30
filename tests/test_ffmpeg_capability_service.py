from __future__ import annotations

from src.models.ffmpeg_config import (
    FFmpegAudioCodec,
    FFmpegConfig,
    FFmpegHardwareAcceleration,
    FFmpegPixelFormat,
    FFmpegVideoCodec,
)
from src.services.ffmpeg_capability_service import (
    FFmpegCapabilityService,
)


service = FFmpegCapabilityService()

config = FFmpegConfig()

capabilities = service.detect(
    config
)

print(
    "FFmpeg available:",
    capabilities.ffmpeg_available,
)

print(
    "ffprobe available:",
    capabilities.ffprobe_available,
)

print(
    "FFmpeg version:",
    capabilities.ffmpeg_version,
)

print(
    "Encoder count:",
    len(
        capabilities.encoders
    ),
)

print(
    "Filter count:",
    len(
        capabilities.filters
    ),
)

print(
    "Hardware acceleration:",
    sorted(
        capabilities.hardware_accelerators
    ),
)

assert capabilities.ffmpeg_available is True
assert capabilities.ffprobe_available is True
assert capabilities.ready is True

assert capabilities.ffmpeg_path
assert capabilities.ffprobe_path

assert capabilities.ffmpeg_version
assert capabilities.ffprobe_version

assert capabilities.has_encoder(
    "libx264"
)

assert capabilities.has_encoder(
    "aac"
)

assert capabilities.has_filter(
    "scale"
)

assert capabilities.has_filter(
    "overlay"
)

assert capabilities.has_filter(
    "xfade"
)

assert capabilities.has_filter(
    "zoompan"
)

assert capabilities.has_filter(
    "amix"
)

assert capabilities.has_filter(
    "sidechaincompress"
)


resolved = service.resolve(
    config
)

print(
    "Selected video codec:",
    resolved.selected_video_codec,
)

print(
    "Selected audio codec:",
    resolved.selected_audio_codec,
)

print(
    "Selected hardware acceleration:",
    resolved.selected_hardware_acceleration,
)

assert (
    resolved.selected_audio_codec
    == FFmpegAudioCodec.AAC.value
)

assert (
    resolved.selected_video_codec
    in {
        FFmpegVideoCodec.H264_NVENC.value,
        FFmpegVideoCodec.LIBX264.value,
    }
)

assert resolved.capabilities.ready is True


cpu_config = FFmpegConfig(
    video_codec=(
        FFmpegVideoCodec.LIBX264
    ),
    audio_codec=(
        FFmpegAudioCodec.AAC
    ),
    hardware_acceleration=(
        FFmpegHardwareAcceleration.NONE
    ),
    pixel_format=(
        FFmpegPixelFormat.YUV420P
    ),
    crf=20,
    preset="medium",
)

cpu_resolved = service.resolve(
    cpu_config
)

assert (
    cpu_resolved.selected_video_codec
    == "libx264"
)

assert (
    cpu_resolved
    .selected_hardware_acceleration
    is None
)


try:
    FFmpegConfig(
        video_codec=(
            FFmpegVideoCodec.H264_NVENC
        ),
        hardware_acceleration=(
            FFmpegHardwareAcceleration.NONE
        ),
    )
except ValueError:
    print(
        "Invalid NVENC configuration "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "NVENC with disabled hardware "
        "acceleration should fail."
    )


missing_binary_config = FFmpegConfig(
    ffmpeg_path=(
        "definitely_missing_ffmpeg_binary"
    ),
    ffprobe_path=(
        "definitely_missing_ffprobe_binary"
    ),
)

missing_capabilities = service.detect(
    missing_binary_config
)

assert (
    missing_capabilities.ffmpeg_available
    is False
)

assert (
    missing_capabilities.ffprobe_available
    is False
)

assert missing_capabilities.ready is False


try:
    service.resolve(
        missing_binary_config
    )
except RuntimeError:
    print(
        "Missing FFmpeg runtime "
        "successfully blocked."
    )
else:
    raise AssertionError(
        "Missing FFmpeg runtime should fail."
    )


serialized = (
    capabilities.model_dump_json()
)

restored = (
    capabilities.__class__
    .model_validate_json(
        serialized
    )
)

assert restored == capabilities


print(
    "FFmpeg Capability Service tests "
    "completed successfully."
)