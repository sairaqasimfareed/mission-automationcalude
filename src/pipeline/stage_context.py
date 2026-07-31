from __future__ import annotations

from typing import Any

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.video_job import VideoJob
from src.pipeline.pipeline_state import PipelineState


class StageContext(MissionBaseModel):
    """
    Shared execution context passed to every pipeline stage.

    User input is execution-scoped and stage-owned. A stage may inspect
    input without mutating it through get_user_input(), or claim an
    input key exactly once through consume_user_input().

    Consuming a key removes it from the shared execution context so the
    same payload cannot accidentally leak into downstream stages or be
    reapplied during an automatic retry.
    """

    job: VideoJob
    pipeline_state: PipelineState

    dry_run: bool = True

    services: dict[str, Any] = Field(
        default_factory=dict
    )

    temporary_data: dict[str, Any] = Field(
        default_factory=dict
    )

    user_input: dict[str, Any] = Field(
        default_factory=dict
    )

    def add_service(
        self,
        name: str,
        service: Any,
    ) -> None:
        """Register one execution-scoped service."""

        self.services[name] = service

    def get_service(
        self,
        name: str,
    ) -> Any:
        """Return a registered execution-scoped service."""

        if name not in self.services:
            raise KeyError(
                "Service is not available in "
                f"stage context: {name}"
            )

        return self.services[name]

    def has_user_input(
        self,
        key: str,
    ) -> bool:
        """
        Return whether an unconsumed user-input key is available.

        This method never mutates the context.
        """

        return key in self.user_input

    def get_user_input(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Read user input without consuming it.

        Stage implementations should normally prefer
        consume_user_input() when the payload represents a command,
        decision, approval, retry request, or other one-shot action.
        """

        return self.user_input.get(
            key,
            default,
        )

    def consume_user_input(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Claim one user-input value and remove it from the context.

        Consumption is intentionally generic. StageContext does not
        interpret asset decisions or any other domain-specific payload.

        Once consumed, the same key is unavailable to later stages and
        automatic retries unless a caller starts a new execution with
        new user input.
        """

        return self.user_input.pop(
            key,
            default,
        )