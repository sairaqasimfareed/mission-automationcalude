from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel


class FFmpegHardwareAcceleration(str, Enum):
    """Supported FFmpeg hardware-acceleration preferences."""

    AUTO = "auto"
    NONE = "none"
    CUDA = "cuda"
    D3D11VA = "d3d11va"
    D3D12VA = "d3d12va"
    DXVA2 = "dxva2"
    QSV = "qsv"
    VULKAN = "vulkan"
    OPENCL = "opencl"


class FFmpegVideoCodec(str, Enum):
    """Supported video codec preferences."""

    AUTO = "auto"
    LIBX264 = "libx264"
    LIBX265 = "libx265"
    H264_NVENC = "h264_nvenc"
    HEVC_NVENC = "hevc_nvenc"


class FFmpegAudioCodec(str, Enum):
    """Supported audio codec preferences."""

    AAC = "aac"
    LIBOPUS = "libopus"


class FFmpegPixelFormat(str, Enum):
    """Supported output pixel formats."""

    YUV420P = "yuv420p"
    YUV422P = "yuv422p"
    YUV444P = "yuv444p"


class FFmpegContainer(str, Enum):
    """Supported final media containers."""

    MP4 = "mp4"
    MKV = "mkv"
    MOV = "mov"


class FFmpegConfig(MissionBaseModel):
    """Provider-independent FFmpeg renderer configuration."""

    schema_version: str = "1.0"

    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"

    video_codec: FFmpegVideoCodec = (
        FFmpegVideoCodec.AUTO
    )

    audio_codec: FFmpegAudioCodec = (
        FFmpegAudioCodec.AAC
    )

    hardware_acceleration: FFmpegHardwareAcceleration = (
        FFmpegHardwareAcceleration.AUTO
    )

    pixel_format: FFmpegPixelFormat = (
        FFmpegPixelFormat.YUV420P
    )

    container: FFmpegContainer = (
        FFmpegContainer.MP4
    )

    crf: int = Field(
        default=20,
        ge=0,
        le=51,
    )

    preset: str = "medium"

    audio_bitrate: str = "192k"

    threads: int | None = Field(
        default=None,
        ge=1,
    )

    timeout_seconds: float = Field(
        default=3600.0,
        gt=0.0,
    )

    overwrite_output: bool = True

    extra_global_args: list[str] = Field(
        default_factory=list,
    )

    extra_video_args: list[str] = Field(
        default_factory=list,
    )

    extra_audio_args: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "ffmpeg_path",
        "ffprobe_path",
        "preset",
        "audio_bitrate",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "FFmpeg configuration text "
                "cannot be empty."
            )

        return cleaned

    @field_validator(
        "extra_global_args",
        "extra_video_args",
        "extra_audio_args",
    )
    @classmethod
    def clean_argument_list(
        cls,
        values: list[str],
    ) -> list[str]:
        cleaned: list[str] = []

        for value in values:
            normalized = value.strip()

            if normalized:
                cleaned.append(
                    normalized
                )

        return cleaned

    @model_validator(mode="after")
    def validate_codec_configuration(
        self,
    ) -> FFmpegConfig:
        if (
            self.video_codec
            in {
                FFmpegVideoCodec.H264_NVENC,
                FFmpegVideoCodec.HEVC_NVENC,
            }
            and self.hardware_acceleration
            == FFmpegHardwareAcceleration.NONE
        ):
            raise ValueError(
                "NVENC video codecs cannot be used "
                "with hardware acceleration disabled."
            )

        return self


class FFmpegCapabilities(MissionBaseModel):
    """Capabilities detected from the local FFmpeg installation."""

    schema_version: str = "1.0"

    ffmpeg_available: bool = False
    ffprobe_available: bool = False

    ffmpeg_path: str | None = None
    ffprobe_path: str | None = None

    ffmpeg_version: str | None = None
    ffprobe_version: str | None = None

    encoders: set[str] = Field(
        default_factory=set,
    )

    decoders: set[str] = Field(
        default_factory=set,
    )

    filters: set[str] = Field(
        default_factory=set,
    )

    hardware_accelerators: set[str] = Field(
        default_factory=set,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @property
    def ready(self) -> bool:
        """Return whether both required binaries are available."""

        return (
            self.ffmpeg_available
            and self.ffprobe_available
        )

    def has_encoder(
        self,
        name: str,
    ) -> bool:
        """Return whether one encoder is available."""

        return (
            name.strip().lower()
            in self.encoders
        )

    def has_filter(
        self,
        name: str,
    ) -> bool:
        """Return whether one filter is available."""

        return (
            name.strip().lower()
            in self.filters
        )

    def has_hardware_accelerator(
        self,
        name: str,
    ) -> bool:
        """Return whether one hardware accelerator exists."""

        return (
            name.strip().lower()
            in self.hardware_accelerators
        )


class FFmpegResolvedConfig(MissionBaseModel):
    """Concrete FFmpeg settings selected for one machine."""

    config: FFmpegConfig

    capabilities: FFmpegCapabilities

    selected_video_codec: str

    selected_audio_codec: str

    selected_hardware_acceleration: str | None = None

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @model_validator(mode="after")
    def validate_resolved_configuration(
        self,
    ) -> FFmpegResolvedConfig:
        if not self.capabilities.ready:
            raise ValueError(
                "Resolved FFmpeg configuration requires "
                "available FFmpeg and ffprobe binaries."
            )

        if not self.capabilities.has_encoder(
            self.selected_video_codec
        ):
            raise ValueError(
                "Selected video codec is not available: "
                f"{self.selected_video_codec}."
            )

        if not self.capabilities.has_encoder(
            self.selected_audio_codec
        ):
            raise ValueError(
                "Selected audio codec is not available: "
                f"{self.selected_audio_codec}."
            )

        return self