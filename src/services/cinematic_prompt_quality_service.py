from __future__ import annotations

from src.models.cinematic_prompt import CinematicPromptPackage
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_SCORE_LABELS = (
    "SPECIFICITY",
    "CONTINUITY",
    "ACTION",
    "CAMERA",
    "LIGHTING",
    "REVEAL_SAFETY",
)
_REQUIRED_LABELS = ("SCENE", *_SCORE_LABELS)

_DRY_RUN_RESPONSE = "\n---\n".join(
    [
        "SCENE: 1\n" + "\n".join(f"{label}: 70" for label in _SCORE_LABELS),
    ]
)


class CinematicPromptQualityService:
    """
    Post-Script-Approval Production Plan, Phase 4: "Score specificity,
    continuity, action, camera, lighting and reveal safety. Block/
    regenerate low-quality prompts before spending generation budget."

    A separate, genuinely evaluative pass from
    CinematicPromptCompilationService - one batched LLM call scores
    every already-compiled prompt in the package, the same "writing
    and evaluation are separate passes" discipline every other
    evaluator in this engine (HookEvaluationService,
    StoryAngleEvaluationService, ...) already follows. Returns a new
    CinematicPromptPackage with scores attached rather than mutating
    the one it was given, matching this codebase's model-immutability-
    by-convention elsewhere.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError(
                "Estimated cinematic prompt quality cost cannot be negative."
            )

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def evaluate(self, package: CinematicPromptPackage) -> CinematicPromptPackage:
        if not package.prompts:
            raise ValueError(
                "Cinematic prompt quality evaluation requires at least one prompt."
            )

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(package),
            system_prompt=(
                "You are a generation-quality reviewer scoring cinematic "
                "prompts before they are sent to a video generation "
                "provider - each dimension 0-100, honestly, so a weak "
                "prompt can be caught before spending generation budget "
                "on it."
            ),
            prompt_version="cinematic_prompt_quality_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "CinematicPromptQualityService",
                "workflow": "cinematic_prompt_quality",
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

            raise RuntimeError(
                f"Cinematic prompt quality evaluation failed: {error_message}"
            )

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError(
                "Cinematic prompt quality evaluation provider returned empty content."
            )

        scores_by_scene = self._parse_scores(content)

        scored_prompts = []
        for prompt in package.prompts:
            scores = scores_by_scene.get(prompt.scene_number)
            updated = prompt.model_copy(
                update=(
                    {
                        "specificity_score": scores[0],
                        "continuity_score": scores[1],
                        "action_score": scores[2],
                        "camera_score": scores[3],
                        "lighting_score": scores[4],
                        "reveal_safety_score": scores[5],
                    }
                    if scores is not None
                    else {}
                )
            )
            scored_prompts.append(updated)

        return CinematicPromptPackage(
            script_lock_hash=package.script_lock_hash, prompts=scored_prompts
        )

    @staticmethod
    def _build_prompt(package: CinematicPromptPackage) -> str:
        prompt_lines = "\n".join(
            f"SCENE {prompt.scene_number}: {prompt.prompt_text}"
            for prompt in sorted(package.prompts, key=lambda p: p.scene_number)
        )

        return (
            f"Cinematic prompts to score:\n{prompt_lines}\n\n"
            "For each scene, return one block separated by a line of "
            "three or more dashes, with exactly these labeled lines:\n"
            "SCENE: <the scene number>\n"
            "SPECIFICITY: <0-100, how visually specific/unambiguous "
            "the prompt is>\n"
            "CONTINUITY: <0-100, how well it respects the stated "
            "continuity state>\n"
            "ACTION: <0-100, how clear the action progression is>\n"
            "CAMERA: <0-100, how usable the camera/lens instruction is>\n"
            "LIGHTING: <0-100, how clear the lighting instruction is>\n"
            "REVEAL_SAFETY: <0-100, how well it avoids spoiling "
            "protected reveals>"
        )

    @staticmethod
    def _parse_scores(content: str) -> dict[int, tuple[int, int, int, int, int, int]]:
        scores_by_scene: dict[int, tuple[int, int, int, int, int, int]] = {}

        for block in split_blocks(content):
            fields = {
                label: extract_labeled_field(block, label) for label in _REQUIRED_LABELS
            }

            if any(fields[label] is None for label in _REQUIRED_LABELS):
                continue

            try:
                scene_number = int((fields["SCENE"] or "").strip())
                parsed_scores = tuple(
                    max(0, min(100, int((fields[label] or "0").strip())))
                    for label in _SCORE_LABELS
                )
            except ValueError:
                continue

            if scene_number < 1:
                continue

            scores_by_scene[scene_number] = parsed_scores  # type: ignore[assignment]

        return scores_by_scene
