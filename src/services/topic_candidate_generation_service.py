from __future__ import annotations

from src.models.enums import Platform
from src.models.topic_candidate import TopicCandidate
from src.services.llm.labeled_block_parser import extract_labeled_field, split_blocks
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

_SCORE_LABELS = (
    ("AUDIENCE_POTENTIAL", "audience_potential"),
    ("SPECIFICITY", "specificity"),
    ("NOVELTY", "novelty"),
    ("STORY_POTENTIAL", "story_potential"),
    ("RESEARCHABILITY", "researchability"),
    ("PLATFORM_FIT", "platform_fit"),
)

_DRY_RUN_RESPONSE = "\n---\n".join(
    f"TITLE: Dry-run topic candidate {index} for development and testing purposes only.\n"
    "AUDIENCE_POTENTIAL: 70\n"
    "SPECIFICITY: 65\n"
    "NOVELTY: 60\n"
    "STORY_POTENTIAL: 72\n"
    "RESEARCHABILITY: 80\n"
    "PLATFORM_FIT: 68\n"
    "AI_RECOMMENDATION: Dry-run recommendation for development and testing "
    "purposes only."
    for index in range(1, 4)
)


class TopicCandidateGenerationService:
    """
    Generates multiple candidate topics from one seed idea, before any
    audience/research/angle work begins (PDF-2 Phase 5: Topic
    Intelligence Workspace).

    Deliberately takes only a raw seed idea plus genre/platform rather
    than a full EditorialProfile - Topic is the first stage in the
    redesign's own pipeline order, before AudienceProfile/
    ChannelStyleProfile exist for a project, so there is nothing yet
    to compose an EditorialProfile from. Genre/platform are the only
    real signals available this early.
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated topic candidate cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def generate(
        self,
        *,
        seed_idea: str,
        genre_id: str,
        platform: Platform,
        candidate_count: int = 5,
    ) -> list[TopicCandidate]:
        """Generate up to candidate_count distinct, scored topic candidates."""

        if candidate_count < 1:
            raise ValueError("Topic candidate count must be at least 1.")

        normalized_seed_idea = seed_idea.strip()

        if not normalized_seed_idea:
            raise ValueError("Topic candidate seed idea cannot be empty.")

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(
                seed_idea=normalized_seed_idea,
                genre_id=genre_id,
                platform=platform,
                candidate_count=candidate_count,
            ),
            system_prompt=(
                "You are an expert content strategist for long-form video. "
                "Propose distinct, concrete topic candidates for the "
                "supplied seed idea and score each one honestly - do not "
                "inflate scores to make every candidate look strong."
            ),
            prompt_version="topic_candidate_generation_prompt_v1.0.0",
            dry_run_response=_DRY_RUN_RESPONSE,
            metadata={
                "agent": "TopicCandidateGenerationService",
                "workflow": "topic_candidate_generation",
                "seed_idea": normalized_seed_idea,
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

            raise RuntimeError(f"Topic candidate generation failed: {error_message}")

        content = (service_result.result.content or "").strip()

        if not content:
            raise RuntimeError("Topic candidate provider returned empty content.")

        candidates = self._parse_candidates(content)

        if not candidates:
            raise RuntimeError(
                "Topic candidate provider returned no usable candidates."
            )

        return candidates[:candidate_count]

    @staticmethod
    def _build_prompt(
        *,
        seed_idea: str,
        genre_id: str,
        platform: Platform,
        candidate_count: int,
    ) -> str:
        score_lines = "\n".join(
            f"{label}: <0-100 integer>" for label, _ in _SCORE_LABELS
        )

        return (
            f"Seed idea: {seed_idea}\n"
            f"Genre: {genre_id}\n"
            f"Platform: {platform.value}\n\n"
            f"Propose {candidate_count} distinct, concrete topic candidates "
            "for this seed idea. Each candidate should be a specific, "
            "produceable video topic - not a restatement of the seed idea "
            "itself.\n\n"
            "Return each candidate as a block with exactly these labeled "
            "lines, and separate blocks with a line of three or more "
            "dashes:\n"
            "TITLE: <specific topic title>\n"
            f"{score_lines}\n"
            "AI_RECOMMENDATION: <1-2 sentences on why this topic scored "
            "the way it did>"
        )

    @classmethod
    def _parse_candidates(cls, content: str) -> list[TopicCandidate]:
        candidates: list[TopicCandidate] = []

        for block in split_blocks(content):
            title = extract_labeled_field(block, "TITLE")
            recommendation = extract_labeled_field(block, "AI_RECOMMENDATION")

            if not title:
                continue

            scores: dict[str, int] = {}
            scores_complete = True

            for label, field_name in _SCORE_LABELS:
                raw_value = extract_labeled_field(block, label)

                if raw_value is None:
                    scores_complete = False
                    break

                try:
                    parsed_value = int(raw_value.strip())
                except ValueError:
                    scores_complete = False
                    break

                if not 0 <= parsed_value <= 100:
                    scores_complete = False
                    break

                scores[field_name] = parsed_value

            if not scores_complete:
                continue

            candidates.append(
                TopicCandidate(
                    title=title,
                    ai_recommendation=recommendation,
                    audience_potential=scores["audience_potential"],
                    specificity=scores["specificity"],
                    novelty=scores["novelty"],
                    story_potential=scores["story_potential"],
                    researchability=scores["researchability"],
                    platform_fit=scores["platform_fit"],
                )
            )

        return candidates
