from __future__ import annotations

import time
from typing import Any

from src.models.asset_state import (
    AssetUserDecision,
    SceneAssetState,
)
from src.models.scene import Scene
from src.pipeline.base_stage import BasePipelineStage
from src.pipeline.pipeline_stage import (
    PipelineStageName,
    PipelineStageStatus,
)
from src.pipeline.stage_context import StageContext
from src.pipeline.stage_result import StageResult
from src.services.scene_asset_video_clip_builder_service import (
    SceneAssetVideoClipBuilderService,
)
from src.services.scene_asset_workflow_service import (
    SceneAssetWorkflowService,
)


class AssetPipelineStage(BasePipelineStage):
    """
    Pipeline adapter for SceneAssetWorkflowService.

    Fresh execution:
    - starts the existing visual-asset workflow for every planned scene;
    - stores resulting SceneAssetState objects on VideoJob.

    Resume execution:
    - preserves existing VideoJob.scene_asset_states;
    - consumes asset decisions from StageContext.user_input;
    - delegates decisions to SceneAssetWorkflowService.apply_decision();
    - never recreates asset decision/manual-upload business logic.

    Expected user-input structure:

        {
            "asset_decisions": [
                {
                    "scene_number": 1,
                    "decision": "manual_upload",
                    "selected_candidate_index": None,
                    "manual_upload_path": "...",
                    "project_id": "...",
                    "apply_to_remaining_scenes": False,
                }
            ]
        }

    asset_decisions may contain decisions for one or more scenes.

    Once every scene's SceneAssetState reaches a resolved, non-waiting
    state, resolved scenes are bridged into VideoJob.video_clips via
    SceneAssetVideoClipBuilderService - TimelinePipelineStage requires
    video_clips, and nothing else in the pipeline ever populated it.
    """

    USER_INPUT_KEY = "asset_decisions"

    def __init__(
        self,
        *,
        asset_workflow_service: SceneAssetWorkflowService,
        video_clip_builder_service: (
            SceneAssetVideoClipBuilderService | None
        ) = None,
    ) -> None:
        self._asset_workflow_service = (
            asset_workflow_service
        )

        self._video_clip_builder_service = (
            video_clip_builder_service
            or SceneAssetVideoClipBuilderService()
        )

    @property
    def stage_name(
        self,
    ) -> PipelineStageName:
        """Return the pipeline identifier."""

        return (
            PipelineStageName
            .ASSET_SELECTION
        )

    def execute(
        self,
        context: StageContext,
    ) -> StageResult:
        """
        Execute fresh or resumed asset-selection workflow.

        Existing asset states are authoritative during resumed execution.
        A resumed stage must not restart local/manual/stock discovery and
        accidentally discard an earlier user-visible workflow state.
        """

        started_at = (
            time.perf_counter()
        )

        scenes = sorted(
            context.job.scenes,
            key=lambda value: (
                value.scene_number
            ),
        )

        if not scenes:
            return self._failed_result(
                started_at=started_at,
                error_message=(
                    "Asset stage requires "
                    "planned scenes."
                ),
            )

        existing_states = (
            context.job
            .scene_asset_states
        )

        decisions = (
            self._consume_decisions(
                context
            )
        )

        if existing_states:
            states = (
                self._resume_states(
                    scenes=scenes,
                    states=existing_states,
                    decisions=decisions,
                )
            )
        else:
            if decisions:
                return self._failed_result(
                    started_at=started_at,
                    error_message=(
                        "Asset decisions cannot be "
                        "applied because no persisted "
                        "scene asset states are available."
                    ),
                )

            states = (
                self._start_states(
                    scenes
                )
            )

        context.job.scene_asset_states = (
            states
        )

        warnings = (
            self._collect_warnings(
                states
            )
        )

        errors = (
            self._collect_errors(
                states
            )
        )

        metadata = (
            self._build_metadata(
                states
            )
        )

        if errors:
            return StageResult(
                stage=self.stage_name,
                status=(
                    PipelineStageStatus
                    .FAILED
                ),
                duration_seconds=(
                    time.perf_counter()
                    - started_at
                ),
                progress_percent=100,
                warnings=warnings,
                errors=errors,
                metadata=metadata,
            )

        if self._requires_user_input(
            states
        ):
            return StageResult(
                stage=self.stage_name,
                status=(
                    PipelineStageStatus
                    .WAITING_FOR_USER
                ),
                duration_seconds=(
                    time.perf_counter()
                    - started_at
                ),
                progress_percent=100,
                warnings=warnings,
                errors=[],
                metadata=metadata,
            )

        context.job.video_clips = (
            self._video_clip_builder_service.build_clips(
                scenes=scenes,
                states=states,
            )
        )

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus
                .COMPLETED
            ),
            duration_seconds=(
                time.perf_counter()
                - started_at
            ),
            progress_percent=100,
            warnings=warnings,
            errors=[],
            metadata=metadata,
        )

    def _start_states(
        self,
        scenes: list[Scene],
    ) -> list[SceneAssetState]:
        """
        Start asset workflow for a fresh execution.

        This preserves the historical AssetPipelineStage behavior.
        """

        states: list[
            SceneAssetState
        ] = []

        for scene in scenes:
            state = (
                self._asset_workflow_service
                .start(
                    scene
                )
            )

            states.append(
                state
            )

        return states

    def _resume_states(
        self,
        *,
        scenes: list[Scene],
        states: list[SceneAssetState],
        decisions: list[dict[str, Any]],
    ) -> list[SceneAssetState]:
        """
        Resume persisted scene workflow states.

        Existing states are matched to scenes by scene_number.
        Only scenes with supplied user decisions are mutated.
        """

        scene_by_number = {
            scene.scene_number: scene
            for scene in scenes
        }

        state_by_number: dict[
            int,
            SceneAssetState,
        ] = {}

        for state in states:
            if (
                state.scene_number
                in state_by_number
            ):
                raise ValueError(
                    "Duplicate persisted asset state "
                    "for scene "
                    f"{state.scene_number}."
                )

            state_by_number[
                state.scene_number
            ] = state

        expected_scene_numbers = set(
            scene_by_number
        )

        persisted_scene_numbers = set(
            state_by_number
        )

        unknown_states = sorted(
            persisted_scene_numbers
            - expected_scene_numbers
        )

        if unknown_states:
            raise ValueError(
                "Persisted asset state references "
                "unknown scene number(s): "
                + ", ".join(
                    str(value)
                    for value in unknown_states
                )
                + "."
            )

        missing_states = sorted(
            expected_scene_numbers
            - persisted_scene_numbers
        )

        if missing_states:
            raise ValueError(
                "Persisted asset state is missing "
                "scene number(s): "
                + ", ".join(
                    str(value)
                    for value in missing_states
                )
                + "."
            )

        decisions_by_scene = (
            self._index_decisions(
                decisions=decisions,
                scene_numbers=(
                    expected_scene_numbers
                ),
            )
        )

        updated_states: list[
            SceneAssetState
        ] = []

        for scene_number in sorted(
            expected_scene_numbers
        ):
            scene = (
                scene_by_number[
                    scene_number
                ]
            )

            state = (
                state_by_number[
                    scene_number
                ]
            )

            decision_payload = (
                decisions_by_scene.get(
                    scene_number
                )
            )

            if decision_payload is not None:
                state = (
                    self._apply_decision(
                        scene=scene,
                        state=state,
                        payload=(
                            decision_payload
                        ),
                    )
                )

            updated_states.append(
                state
            )

        return updated_states

    def _apply_decision(
        self,
        *,
        scene: Scene,
        state: SceneAssetState,
        payload: dict[str, Any],
    ) -> SceneAssetState:
        """
        Validate one normalized user decision and delegate it.

        SceneAssetWorkflowService remains the sole owner of asset
        workflow transitions.
        """

        raw_decision = (
            payload.get(
                "decision"
            )
        )

        if not isinstance(
            raw_decision,
            str,
        ):
            raise ValueError(
                "Asset decision requires a "
                "string 'decision' value."
            )

        try:
            decision = (
                AssetUserDecision(
                    raw_decision.strip()
                )
            )
        except ValueError as error:
            raise ValueError(
                "Unsupported asset decision "
                f"for scene "
                f"{scene.scene_number}: "
                f"{raw_decision}."
            ) from error

        selected_candidate_index = (
            self._optional_int(
                payload=payload,
                key=(
                    "selected_candidate_index"
                ),
            )
        )

        manual_upload_path = (
            self._optional_string(
                payload=payload,
                key="manual_upload_path",
            )
        )

        project_id = (
            self._optional_string(
                payload=payload,
                key="project_id",
            )
        )

        apply_to_remaining_scenes = (
            self._optional_bool(
                payload=payload,
                key=(
                    "apply_to_remaining_scenes"
                ),
                default=False,
            )
        )

        return (
            self._asset_workflow_service
            .apply_decision(
                scene=scene,
                state=state,
                decision=decision,
                selected_candidate_index=(
                    selected_candidate_index
                ),
                manual_upload_path=(
                    manual_upload_path
                ),
                project_id=project_id,
                apply_to_remaining_scenes=(
                    apply_to_remaining_scenes
                ),
            )
        )

    @classmethod
    def _consume_decisions(
        cls,
        context: StageContext,
    ) -> list[dict[str, Any]]:
        """
        Claim and validate asset-stage user input.

        Asset decisions are one-shot execution commands. Once claimed by
        this stage, they are removed from StageContext so an automatic
        retry or downstream stage cannot accidentally apply the same
        decision again.

        Domain-specific validation remains owned by this adapter and the
        existing SceneAssetWorkflowService.
        """

        raw_decisions = (
            context.consume_user_input(
                cls.USER_INPUT_KEY
            )
        )

        if raw_decisions is None:
            return []

        if not isinstance(
            raw_decisions,
            list,
        ):
            raise ValueError(
                "'asset_decisions' user input "
                "must be a list."
            )

        decisions: list[
            dict[str, Any]
        ] = []

        for index, raw_decision in enumerate(
            raw_decisions
        ):
            if not isinstance(
                raw_decision,
                dict,
            ):
                raise ValueError(
                    "Asset decision at index "
                    f"{index} must be an object."
                )

            normalized: dict[
                str,
                Any,
            ] = {}

            for key, value in (
                raw_decision.items()
            ):
                if not isinstance(
                    key,
                    str,
                ):
                    raise ValueError(
                        "Asset decision keys "
                        "must be strings."
                    )

                normalized[
                    key
                ] = value

            decisions.append(
                normalized
            )

        return decisions
    @classmethod
    def _index_decisions(
        cls,
        *,
        decisions: list[
            dict[str, Any]
        ],
        scene_numbers: set[int],
    ) -> dict[
        int,
        dict[str, Any],
    ]:
        """Index decisions by scene number and reject stale input."""

        indexed: dict[
            int,
            dict[str, Any],
        ] = {}

        for payload in decisions:
            scene_number = (
                cls._required_scene_number(
                    payload
                )
            )

            if (
                scene_number
                not in scene_numbers
            ):
                raise ValueError(
                    "Asset decision references "
                    "unknown scene number "
                    f"{scene_number}."
                )

            if (
                scene_number
                in indexed
            ):
                raise ValueError(
                    "Multiple asset decisions "
                    "were supplied for scene "
                    f"{scene_number}."
                )

            indexed[
                scene_number
            ] = payload

        return indexed

    @staticmethod
    def _required_scene_number(
        payload: dict[
            str,
            Any,
        ],
    ) -> int:
        """Return one validated decision scene number."""

        value = payload.get(
            "scene_number"
        )

        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                int,
            )
            or value < 1
        ):
            raise ValueError(
                "Asset decision requires a "
                "positive integer "
                "'scene_number'."
            )

        return value

    @staticmethod
    def _optional_int(
        *,
        payload: dict[
            str,
            Any,
        ],
        key: str,
    ) -> int | None:
        """Read an optional integer decision field."""

        value = payload.get(
            key
        )

        if value is None:
            return None

        if (
            isinstance(value, bool)
            or not isinstance(
                value,
                int,
            )
        ):
            raise ValueError(
                f"Asset decision field "
                f"'{key}' must be an integer "
                "or null."
            )

        return value

    @staticmethod
    def _optional_string(
        *,
        payload: dict[
            str,
            Any,
        ],
        key: str,
    ) -> str | None:
        """Read an optional string decision field."""

        value = payload.get(
            key
        )

        if value is None:
            return None

        if not isinstance(
            value,
            str,
        ):
            raise ValueError(
                f"Asset decision field "
                f"'{key}' must be a string "
                "or null."
            )

        cleaned = (
            value.strip()
        )

        return (
            cleaned
            or None
        )

    @staticmethod
    def _optional_bool(
        *,
        payload: dict[
            str,
            Any,
        ],
        key: str,
        default: bool,
    ) -> bool:
        """Read an optional boolean decision field."""

        value = payload.get(
            key,
            default,
        )

        if not isinstance(
            value,
            bool,
        ):
            raise ValueError(
                f"Asset decision field "
                f"'{key}' must be boolean."
            )

        return value

    @staticmethod
    def _requires_user_input(
        states: list[
            SceneAssetState
        ],
    ) -> bool:
        """
        Return whether one or more scene workflows require input.

        SceneAssetState already owns this domain decision, so the
        pipeline adapter delegates to that property instead of
        duplicating its status list.
        """

        return any(
            state.requires_user_decision
            for state in states
        )

    @staticmethod
    def _collect_warnings(
        states: list[
            SceneAssetState
        ],
    ) -> list[str]:
        """Collect unique warnings from all scene asset states."""

        warnings: list[str] = []

        for state in states:
            for warning in (
                state.warnings
            ):
                cleaned = (
                    warning.strip()
                )

                if (
                    cleaned
                    and cleaned
                    not in warnings
                ):
                    warnings.append(
                        cleaned
                    )

        return warnings

    @staticmethod
    def _collect_errors(
        states: list[
            SceneAssetState
        ],
    ) -> list[str]:
        """Collect unique errors from all scene asset states."""

        errors: list[str] = []

        for state in states:
            for error in (
                state.errors
            ):
                cleaned = (
                    error.strip()
                )

                if (
                    cleaned
                    and cleaned
                    not in errors
                ):
                    errors.append(
                        cleaned
                    )

        return errors

    @staticmethod
    def _build_metadata(
        states: list[
            SceneAssetState
        ],
    ) -> dict[str, object]:
        """Build stable asset-stage diagnostic metadata."""

        status_counts: dict[
            str,
            int,
        ] = {}

        waiting_scene_numbers: list[
            int
        ] = []

        for state in states:
            status = (
                state.status.value
            )

            status_counts[
                status
            ] = (
                status_counts.get(
                    status,
                    0,
                )
                + 1
            )

            if (
                state.requires_user_decision
            ):
                waiting_scene_numbers.append(
                    state.scene_number
                )

        return {
            "scene_count": len(
                states
            ),
            "status_counts": (
                status_counts
            ),
            "waiting_for_user": bool(
                waiting_scene_numbers
            ),
            "waiting_scene_numbers": (
                waiting_scene_numbers
            ),
        }

    def _failed_result(
        self,
        *,
        started_at: float,
        error_message: str,
    ) -> StageResult:
        """Create a normalized asset-stage precondition failure."""

        return StageResult(
            stage=self.stage_name,
            status=(
                PipelineStageStatus
                .FAILED
            ),
            duration_seconds=(
                time.perf_counter()
                - started_at
            ),
            progress_percent=100,
            errors=[
                error_message,
            ],
            metadata={
                "scene_count": 0,
                "waiting_for_user": False,
                "waiting_scene_numbers": [],
            },
        )