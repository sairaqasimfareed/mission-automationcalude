from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator, model_validator

from src.models.base import MissionBaseModel
from src.models.ffmpeg_input import FFmpegInputPlan


class FFmpegCommandPlan(MissionBaseModel):
    """Complete deterministic FFmpeg command specification."""

    schema_version: str = "1.0"

    executable: str

    input_plan: FFmpegInputPlan

    filter_complex: str

    video_output_label: str

    audio_output_label: str

    output_file: str

    arguments: list[str] = Field(
        default_factory=list,
    )

    warnings: list[str] = Field(
        default_factory=list,
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )

    @field_validator(
        "executable",
        "filter_complex",
        "video_output_label",
        "audio_output_label",
        "output_file",
    )
    @classmethod
    def clean_required_text(
        cls,
        value: str,
    ) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError(
                "FFmpeg command text "
                "cannot be empty."
            )

        return cleaned

    @field_validator(
        "video_output_label",
        "audio_output_label",
    )
    @classmethod
    def clean_output_label(
        cls,
        value: str,
    ) -> str:
        return (
            value.strip()
            .strip("[]")
        )

    @field_validator("arguments")
    @classmethod
    def clean_arguments(
        cls,
        values: list[str],
    ) -> list[str]:
        return [
            value
            for value in values
            if value != ""
        ]

    @model_validator(mode="after")
    def validate_command(
        self,
    ) -> FFmpegCommandPlan:
        if not self.arguments:
            raise ValueError(
                "FFmpeg command requires arguments."
            )

        return self

    @property
    def command(self) -> list[str]:
        """Return executable followed by command arguments."""

        return [
            self.executable,
            *self.arguments,
        ]

    @property
    def command_preview(self) -> str:
        """Return human-readable command preview."""

        return " ".join(
            self._quote_argument(
                value
            )
            for value in self.command
        )

    @staticmethod
    def _quote_argument(
        value: str,
    ) -> str:
        if (
            " " not in value
            and "\t" not in value
            and '"' not in value
        ):
            return value

        escaped = value.replace(
            '"',
            '\\"',
        )

        return (
            f'"{escaped}"'
        )