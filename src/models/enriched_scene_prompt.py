from __future__ import annotations

from pydantic import Field

from src.models.base import MissionBaseModel
from src.models.google_flow_generation import GoogleFlowReferenceAsset
from src.models.visual_continuity import VisualState


class EnrichedScenePrompt(MissionBaseModel):
    """
    REQ-9 (full compiled prompt screen): every real piece of a scene's
    generation instruction, gathered into one place for a human to
    read and copy - deliberately NOT what gets sent to any provider
    automatically. `ResolvedCinematicPrompt.prompt_text` (the real
    automated-generation prompt) is carried here unchanged as
    `base_prompt_text`; this model only ADDS the real gaps that never
    made it into that string (negative constraints, transitions, full
    continuity state, resolved reference assets, execution settings,
    quality scores), for manual/informational use.
    """

    scene_number: int

    # Phase 5 (multi-clip scene splitting): mirrors
    # ResolvedCinematicPrompt's own field of the same name - default 0
    # means "the only entry for this scene", identical to every entry
    # that existed before a scene could ever need splitting.
    clip_sequence_index: int = Field(default=0, ge=0)

    base_prompt_text: str

    negative_constraints: list[str] = Field(default_factory=list)

    transition_in: str | None = None

    transition_out: str | None = None

    continuity_incoming: VisualState | None = None

    continuity_outgoing: VisualState | None = None

    reference_assets: list[GoogleFlowReferenceAsset] = Field(default_factory=list)

    execution_model_family: str | None = None

    execution_duration_seconds: float | None = None

    execution_aspect_ratio: str | None = None

    execution_resolution: str | None = None

    specificity_score: int | None = None
    continuity_score: int | None = None
    action_score: int | None = None
    camera_score: int | None = None
    lighting_score: int | None = None
    reveal_safety_score: int | None = None

    is_blocked: bool | None = None

    def full_text(self) -> str:
        """
        Render every field into one readable, copyable text block -
        what the "Copy" button in the desktop view actually puts on
        the clipboard.
        """

        lines: list[str] = [
            f"Scene {self.scene_number}",
            "",
            self.base_prompt_text,
        ]

        if self.negative_constraints:
            lines.append("")
            lines.append("Negative constraints:")
            lines.extend(f"- {item}" for item in self.negative_constraints)

        if self.transition_in or self.transition_out:
            lines.append("")
            lines.append(
                f"Transition in: {self.transition_in or 'unspecified'} | "
                f"Transition out: {self.transition_out or 'unspecified'}"
            )

        if self.continuity_incoming is not None or self.continuity_outgoing is not None:
            lines.append("")
            lines.append("Continuity:")

            if self.continuity_incoming is not None:
                lines.append(
                    "  Incoming: " + self._render_visual_state(self.continuity_incoming)
                )

            if self.continuity_outgoing is not None:
                lines.append(
                    "  Outgoing: " + self._render_visual_state(self.continuity_outgoing)
                )

        if self.reference_assets:
            lines.append("")
            lines.append("Reference assets:")
            lines.extend(
                f"- [{asset.role.value}] {asset.source_path}"
                for asset in self.reference_assets
            )

        lines.append("")
        lines.append(
            "Execution settings: "
            f"model_family={self.execution_model_family or 'unset (uses account default)'}, "
            f"duration={self._format_optional_seconds(self.execution_duration_seconds)}, "
            f"aspect_ratio={self.execution_aspect_ratio or 'unset (not pinned)'}, "
            f"resolution={self.execution_resolution or 'unset (not pinned)'}"
        )

        if self.specificity_score is not None:
            lines.append("")
            lines.append(
                "Quality scores: "
                f"specificity={self.specificity_score}, "
                f"continuity={self.continuity_score}, "
                f"action={self.action_score}, "
                f"camera={self.camera_score}, "
                f"lighting={self.lighting_score}, "
                f"reveal_safety={self.reveal_safety_score}"
                + (" (BLOCKED - below quality threshold)" if self.is_blocked else "")
            )
        else:
            lines.append("")
            lines.append("Quality scores: not yet scored.")

        return "\n".join(lines)

    @staticmethod
    def _render_visual_state(state: VisualState) -> str:
        parts = [
            f"location={state.location}",
            f"lighting={state.lighting}",
            f"wardrobe={state.wardrobe}",
            f"condition={state.condition}",
            f"time_of_day={state.time_of_day}",
            f"weather={state.weather}",
        ]

        if state.props:
            parts.append(f"props={', '.join(state.props)}")

        if state.vehicles:
            parts.append(f"vehicles={', '.join(state.vehicles)}")

        return ", ".join(parts)

    @staticmethod
    def _format_optional_seconds(value: float | None) -> str:
        if value is None:
            return "unset"

        return f"{value:.1f}s"
