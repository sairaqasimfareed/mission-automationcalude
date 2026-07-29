from __future__ import annotations

from pydantic import model_validator

from src.models.base import MissionBaseModel
from src.models.specification_enums import (
    AspectRatio,
    FrameRate,
    QualityMode,
    VideoResolution,
)


class VideoSettings(MissionBaseModel):
    """Defines the technical output settings for one video project."""

    schema_version: str = "1.0"

    resolution: VideoResolution = VideoResolution.FULL_HD
    aspect_ratio: AspectRatio = AspectRatio.LANDSCAPE
    frame_rate: FrameRate = FrameRate.FPS_30
    quality_mode: QualityMode = QualityMode.PREMIUM

    hdr_enabled: bool = False
    captions_enabled: bool = True

    @model_validator(mode="after")
    def validate_video_settings(self) -> "VideoSettings":
        if (
            self.aspect_ratio == AspectRatio.PORTRAIT
            and self.resolution == VideoResolution.QHD
        ):
            raise ValueError(
                "QHD preset is landscape-oriented and cannot be used "
                "directly with portrait aspect ratio."
            )

        if (
            self.aspect_ratio == AspectRatio.PORTRAIT
            and self.resolution == VideoResolution.UHD_4K
        ):
            raise ValueError(
                "4K landscape preset cannot be used directly with "
                "portrait aspect ratio."
            )

        if (
            self.quality_mode == QualityMode.DRAFT
            and self.hdr_enabled
        ):
            raise ValueError(
                "HDR cannot be enabled in Draft quality mode."
            )

        return self

    @property
    def width(self) -> int:
        return int(self.resolution.value.split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.value.split("x")[1])

    @property
    def frames_per_second(self) -> int:
        return self.frame_rate.value