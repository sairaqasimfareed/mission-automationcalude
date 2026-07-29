from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class DurationMode(str, Enum):
    """Supported ways to define the requested video duration."""

    EXACT = "exact"
    RANGE = "range"


class DurationConfig(MissionBaseModel):
    """Defines the requested duration for one video project."""

    schema_version: str = "1.0"

    mode: DurationMode

    target_duration_seconds: int | None = None
    minimum_duration_seconds: int | None = None
    maximum_duration_seconds: int | None = None

    tolerance_seconds: int = Field(
        default=10,
        ge=0,
    )

    @model_validator(mode="after")
    def validate_duration(self) -> "DurationConfig":
        if self.mode == DurationMode.EXACT:
            if self.target_duration_seconds is None:
                raise ValueError(
                    "Exact duration mode requires "
                    "target_duration_seconds."
                )

            if self.target_duration_seconds <= 0:
                raise ValueError(
                    "Target duration must be greater than zero."
                )

            if (
                self.minimum_duration_seconds is not None
                or self.maximum_duration_seconds is not None
            ):
                raise ValueError(
                    "Exact duration mode cannot include "
                    "minimum or maximum duration."
                )

        if self.mode == DurationMode.RANGE:
            if (
                self.minimum_duration_seconds is None
                or self.maximum_duration_seconds is None
            ):
                raise ValueError(
                    "Range duration mode requires both "
                    "minimum_duration_seconds and "
                    "maximum_duration_seconds."
                )

            if self.minimum_duration_seconds <= 0:
                raise ValueError(
                    "Minimum duration must be greater than zero."
                )

            if self.maximum_duration_seconds <= 0:
                raise ValueError(
                    "Maximum duration must be greater than zero."
                )

            if (
                self.minimum_duration_seconds
                > self.maximum_duration_seconds
            ):
                raise ValueError(
                    "Minimum duration cannot exceed "
                    "maximum duration."
                )

            if self.target_duration_seconds is not None:
                raise ValueError(
                    "Range duration mode cannot include "
                    "target_duration_seconds."
                )

        return self

    @property
    def preferred_duration_seconds(self) -> int:
        """Return the preferred working duration for planning."""

        if self.mode == DurationMode.EXACT:
            assert self.target_duration_seconds is not None
            return self.target_duration_seconds

        assert self.minimum_duration_seconds is not None
        assert self.maximum_duration_seconds is not None

        return round(
            (
                self.minimum_duration_seconds
                + self.maximum_duration_seconds
            )
            / 2
        )

    def is_within_allowed_duration(
        self,
        actual_duration_seconds: int,
    ) -> bool:
        """Check whether an actual duration satisfies this config."""

        if actual_duration_seconds < 0:
            return False

        if self.mode == DurationMode.EXACT:
            assert self.target_duration_seconds is not None

            lower_bound = (
                self.target_duration_seconds
                - self.tolerance_seconds
            )
            upper_bound = (
                self.target_duration_seconds
                + self.tolerance_seconds
            )

            return (
                lower_bound
                <= actual_duration_seconds
                <= upper_bound
            )

        assert self.minimum_duration_seconds is not None
        assert self.maximum_duration_seconds is not None

        lower_bound = (
            self.minimum_duration_seconds
            - self.tolerance_seconds
        )
        upper_bound = (
            self.maximum_duration_seconds
            + self.tolerance_seconds
        )

        return (
            lower_bound
            <= actual_duration_seconds
            <= upper_bound
        )