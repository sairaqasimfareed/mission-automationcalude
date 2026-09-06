from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel


class MediaTechnicalValidationResult(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 8: "Run technical
    checks first: readability, duration, dimensions/aspect ratio and
    basic media validity" - applicable to any acquired clip (manual
    upload or stock footage in this codebase's actual acquisition
    paths; Google Flow's own download step is out of scope per this
    implementation's standing exclusion), not only a Flow-generated
    one.

    `issues` is always machine- *and* human-readable text - "every
    rejection has machine- and human-readable cause" - rather than a
    bare error code.
    """

    is_readable: bool
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    has_video_stream: bool = False
    has_audio_stream: bool = False

    issues: list[str] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.is_readable and not self.issues
