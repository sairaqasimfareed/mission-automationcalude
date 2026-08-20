from __future__ import annotations

import shutil

import pytest

from src.models.ffmpeg_config import (
    FFmpegCapabilities,
    FFmpegConfig,
    FFmpegVideoCodec,
)
from src.services.ffmpeg_capability_service import FFmpegCapabilityService

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None

requires_ffmpeg = pytest.mark.skipif(
    not _HAS_FFMPEG,
    reason="Real ffmpeg/ffprobe binaries are not on PATH on this machine.",
)


@requires_ffmpeg
def test_detect_finds_real_ffmpeg_and_ffprobe() -> None:
    capabilities = FFmpegCapabilityService().detect(FFmpegConfig())

    assert capabilities.ffmpeg_available is True
    assert capabilities.ffprobe_available is True
    assert capabilities.ready is True
    assert capabilities.ffmpeg_version is not None
    assert capabilities.ffprobe_version is not None


@requires_ffmpeg
def test_detect_populates_encoders_decoders_and_filters() -> None:
    capabilities = FFmpegCapabilityService().detect(FFmpegConfig())

    assert len(capabilities.encoders) > 0
    assert len(capabilities.decoders) > 0
    assert len(capabilities.filters) > 0
    assert capabilities.metadata["encoder_count"] == len(capabilities.encoders)
    assert capabilities.metadata["filter_count"] == len(capabilities.filters)


@requires_ffmpeg
def test_resolve_selects_a_working_video_and_audio_codec() -> None:
    resolved = FFmpegCapabilityService().resolve(FFmpegConfig())

    assert resolved.capabilities.has_encoder(resolved.selected_video_codec)
    assert resolved.capabilities.has_encoder(resolved.selected_audio_codec)


@requires_ffmpeg
def test_resolve_rejects_an_unavailable_requested_video_codec() -> None:
    config = FFmpegConfig(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        video_codec=FFmpegVideoCodec.H264_NVENC,
    )
    capabilities = FFmpegCapabilityService().detect(config)

    if capabilities.has_encoder(str(FFmpegVideoCodec.H264_NVENC.value)):
        pytest.skip("This machine's ffmpeg build actually has h264_nvenc.")

    with pytest.raises(RuntimeError, match="video codec"):
        FFmpegCapabilityService().resolve(config)


def test_detect_reports_unavailable_when_binaries_do_not_exist() -> None:
    config = FFmpegConfig(
        ffmpeg_path="definitely-not-a-real-ffmpeg-binary",
        ffprobe_path="definitely-not-a-real-ffprobe-binary",
    )

    capabilities = FFmpegCapabilityService().detect(config)

    assert capabilities.ffmpeg_available is False
    assert capabilities.ffprobe_available is False
    assert capabilities.ready is False
    assert capabilities.encoders == set()
    assert capabilities.ffmpeg_version is None


def test_resolve_raises_when_ffmpeg_runtime_is_not_ready() -> None:
    config = FFmpegConfig(
        ffmpeg_path="definitely-not-a-real-ffmpeg-binary",
        ffprobe_path="definitely-not-a-real-ffprobe-binary",
    )

    with pytest.raises(RuntimeError, match="not ready"):
        FFmpegCapabilityService().resolve(config)


def _capabilities(**overrides: object) -> FFmpegCapabilities:
    defaults: dict[str, object] = {
        "ffmpeg_available": True,
        "ffprobe_available": True,
        "ffmpeg_path": "/usr/bin/ffmpeg",
        "ffprobe_path": "/usr/bin/ffprobe",
        "encoders": {"libx264", "aac"},
        "hardware_accelerators": set(),
    }
    defaults.update(overrides)

    return FFmpegCapabilities(**defaults)  # type: ignore[arg-type]


def test_has_encoder_is_case_insensitive() -> None:
    capabilities = _capabilities(encoders={"libx264"})

    assert capabilities.has_encoder("LIBX264") is True
    assert capabilities.has_encoder("libx265") is False


def test_has_hardware_accelerator_is_case_insensitive() -> None:
    capabilities = _capabilities(hardware_accelerators={"cuda"})

    assert capabilities.has_hardware_accelerator("CUDA") is True
    assert capabilities.has_hardware_accelerator("vaapi") is False
