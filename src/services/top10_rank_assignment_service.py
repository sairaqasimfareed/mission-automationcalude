from __future__ import annotations

from src.models.scene import Scene
from src.models.top10_rank_assignment import (
    TopTenRankAssignment,
    TopTenRankAssignmentResult,
)
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_DRY_RUN_RESPONSE = "\n---\n".join(
    (
        "RANK: 10\n"
        "SCENES: 2\n"
        "RATIONALE: Dry-run rationale for the tenth-place item.",
        "RANK: 9\n"
        "SCENES: 3\n"
        "RATIONALE: Dry-run rationale for the ninth-place item.",
    )
)


class TopTenRankAssignmentService:
    """
    Assign countdown ranks (10 down to 1) to a top10 job's already-
    generated scenes, from their real narration.

    One batched LLM call for the whole video, matching the cost
    discipline SceneSoundDesignService already established - not one
    call per scene.

    Deliberately runs AFTER normal script/scene generation completes,
    not threaded through StoryBeat/ScriptSegment like tension_level -
    scene boundaries (a generic function of narration duration and
    sentence density) are not guaranteed to align 1:1 with list-item
    boundaries, so rank has to be assigned from the real, already-
    written narration text, not decided structurally beforehand.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated rank assignment cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def assign(
        self,
        *,
        scenes: list[Scene],
    ) -> TopTenRankAssignmentResult:
        """Assign ranks 10 down to 1 across the supplied scenes."""

        if not scenes:
            raise ValueError("Rank assignment requires at least one scene.")

        ordered_scenes = sorted(scenes, key=lambda scene: scene.scene_number)

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(scenes=ordered_scenes),
            system_prompt=(
                "You are a video editor preparing a top-10 countdown "
                "video for on-screen rank cards. Read each scene's "
                "actual narration and determine which scenes belong to "
                "which list item - grounded in what the narration "
                "actually says, never guessed from scene position "
                "alone."
            ),
            prompt_version="top10_rank_assignment_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "TopTenRankAssignmentService",
                "workflow": "top10_rank_assignment",
                "scene_count": len(ordered_scenes),
            },
        )

        service_result = self.llm_service.generate(
            request,
            estimated_cost_usd=self.estimated_cost_usd,
            profile_ids=self.profile_ids,
        )

        if not service_result.is_success:
            error_message = (
                service_result.result.error_message
                or "All configured LLM providers failed."
            )

            raise RuntimeError(f"Rank assignment failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Rank assignment provider returned empty content.")

        valid_scene_numbers = {scene.scene_number for scene in ordered_scenes}

        assignments, warnings = self._parse_assignments(
            content,
            valid_scene_numbers=valid_scene_numbers,
        )

        return TopTenRankAssignmentResult(
            assignments=assignments,
            warnings=warnings,
            provider=service_result.result.provider,
            model=service_result.result.model,
        )

    @staticmethod
    def _build_prompt(*, scenes: list[Scene]) -> str:
        scene_lines = "\n".join(
            f"SCENE {scene.scene_number} "
            f"({scene.estimated_duration_seconds}s): {scene.narration}"
            for scene in scenes
        )

        return (
            "This video counts down a top-10 list, from rank #10 "
            "(shown first) down to rank #1 (the climax, shown last). "
            "Some of the scenes below are the video's opening hook or "
            "intro, before the countdown itself begins - do not assign "
            "those a rank. Group the remaining scenes into exactly the "
            "10 list items, in the order they appear. A single list "
            "item's narration may span more than one consecutive "
            "scene if it needs the extra time - group all such scenes "
            "under the same rank.\n\n"
            f"Scenes:\n{scene_lines}\n\n"
            "Return one block per rank, in descending order (10 down "
            "to 1), separated by a line of three or more dashes.\n\n"
            "Rank block:\n"
            "RANK: <10 down to 1>\n"
            "SCENES: <comma-separated scene numbers belonging to this "
            "rank, e.g. 3,4>\n"
            "RATIONALE: <the specific narration detail that identifies "
            "this as its own list item>"
        )

    @classmethod
    def _parse_assignments(
        cls,
        content: str,
        *,
        valid_scene_numbers: set[int],
    ) -> tuple[list[TopTenRankAssignment], list[str]]:
        assignments: list[TopTenRankAssignment] = []
        warnings: list[str] = []
        seen_ranks: set[int] = set()
        seen_scene_numbers: set[int] = set()

        for block in split_blocks(content):
            assignment = cls._parse_one_block(
                block,
                valid_scene_numbers=valid_scene_numbers,
                seen_ranks=seen_ranks,
                seen_scene_numbers=seen_scene_numbers,
                warnings=warnings,
            )

            if assignment is not None:
                assignments.append(assignment)
                seen_ranks.add(assignment.rank)
                seen_scene_numbers.update(assignment.scene_numbers)

        return assignments, warnings

    @staticmethod
    def _parse_one_block(
        block: str,
        *,
        valid_scene_numbers: set[int],
        seen_ranks: set[int],
        seen_scene_numbers: set[int],
        warnings: list[str],
    ) -> TopTenRankAssignment | None:
        rank_raw = extract_labeled_field(block, "RANK")
        scenes_raw = extract_labeled_field(block, "SCENES")
        rationale = extract_labeled_field(block, "RATIONALE")

        if not rank_raw or not rank_raw.strip().isdigit():
            warnings.append("Skipped a rank block with a missing/invalid RANK.")

            return None

        rank = int(rank_raw.strip())

        if rank < 1 or rank > 10:
            warnings.append(f"Skipped a rank block with an out-of-range RANK: {rank}.")

            return None

        if rank in seen_ranks:
            warnings.append(f"Skipped a duplicate assignment for rank {rank}.")

            return None

        if not scenes_raw or not rationale:
            warnings.append(f"Skipped rank {rank}: missing SCENES or RATIONALE.")

            return None

        scene_numbers: list[int] = []

        for raw_number in scenes_raw.split(","):
            cleaned = raw_number.strip()

            if not cleaned.isdigit():
                continue

            scene_number = int(cleaned)

            if scene_number not in valid_scene_numbers:
                warnings.append(
                    f"Rank {rank} referenced unknown scene {scene_number} - skipped."
                )

                continue

            if scene_number in seen_scene_numbers or scene_number in scene_numbers:
                warnings.append(
                    f"Rank {rank} referenced scene {scene_number}, already "
                    "assigned to another rank - skipped."
                )

                continue

            scene_numbers.append(scene_number)

        if not scene_numbers:
            warnings.append(f"Skipped rank {rank}: no valid scene numbers remained.")

            return None

        return TopTenRankAssignment(
            rank=rank,
            scene_numbers=scene_numbers,
            rationale=rationale,
        )
