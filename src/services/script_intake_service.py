from __future__ import annotations

from src.models.generated_script import GeneratedScript, ScriptSegment
from src.models.script_intake import (
    ScriptIntakeMismatch,
    ScriptIntakeMode,
    ScriptIntakeResult,
)
from src.models.story_blueprint import StoryBeatType
from src.models.video_job import VideoJob
from src.services.llm.labeled_block_parser import extract_labeled_field
from src.services.llm.llm_service import LLMService
from src.shared.llm.models import LLMProvider
from src.shared.llm.request import LLMRequest

# Average spoken narration pace - used only to estimate duration for an
# imported script that has no real timing information of its own yet.
# The same rough figure the industry commonly uses for narration VO.
_WORDS_PER_MINUTE = 150.0

_MIN_SEGMENT_DURATION_SECONDS = 1.0


class ScriptIntakeService:
    """
    Content Studio Redesign, Phase 15: "Allow users to bypass Content
    Production while still entering the same professional downstream
    pipeline." Converts raw pasted/uploaded script text into the same
    canonical GeneratedScript every generated script already uses, so
    everything downstream (versioning, selection edits, quality gate,
    lock) works identically regardless of a script's origin.

    Deliberately builds no fake StoryBlueprint/Research/Hook - an
    imported script has none of those, and this service never invents
    them merely to satisfy some other stage's input requirements
    (spec: "No fake Research/Hook/Beat artifacts are generated merely
    to satisfy dependencies").
    """

    def __init__(
        self,
        *,
        llm_service: LLMService,
        profile_ids: list[str] | None = None,
        estimated_cost_usd: float = 0.0,
    ) -> None:
        if estimated_cost_usd < 0:
            raise ValueError("Estimated script intake cost cannot be negative.")

        self.llm_service = llm_service
        self.profile_ids = profile_ids
        self.estimated_cost_usd = estimated_cost_usd

    def normalize_text_to_script(
        self,
        *,
        raw_text: str,
        topic: str,
        genre_id: str,
        target_duration_seconds: int,
    ) -> GeneratedScript:
        """
        Deterministic, no LLM call: splits on blank-line-separated
        paragraphs, one ScriptSegment per paragraph, timed by an
        estimated speaking pace. narrative_function is SETUP for every
        segment - an imported script has no real beat sheet to draw a
        structural role from, and this service never invents one.
        """

        paragraphs = [
            paragraph.strip()
            for paragraph in raw_text.replace("\r\n", "\n").split("\n\n")
            if paragraph.strip()
        ]

        if not paragraphs:
            raise ValueError("Imported script text is empty.")

        segments: list[ScriptSegment] = []
        cursor_seconds = 0.0

        for index, paragraph in enumerate(paragraphs, start=1):
            word_count = len(paragraph.split())
            duration = max(
                word_count / _WORDS_PER_MINUTE * 60.0, _MIN_SEGMENT_DURATION_SECONDS
            )

            segments.append(
                ScriptSegment(
                    segment_number=index,
                    start_seconds=cursor_seconds,
                    end_seconds=cursor_seconds + duration,
                    narrative_function=StoryBeatType.SETUP,
                    narration=paragraph,
                    tension_level=50,
                )
            )
            cursor_seconds += duration

        return GeneratedScript(
            topic=topic,
            genre_id=genre_id,
            target_duration_seconds=target_duration_seconds,
            segments=segments,
            prompt_version="script_intake_prompt_v1.0.0",
        )

    def analyze_mismatches(
        self, *, script: GeneratedScript, job: VideoJob
    ) -> list[ScriptIntakeMismatch]:
        """
        One LLM call (Primary "analyzes but does not rewrite") flags
        language/genre/audience/platform inconsistencies against the
        project's own settings - never silently corrected, only
        reported.
        """

        request = LLMRequest(
            provider=LLMProvider.OPENAI,
            model="provider-default-model",
            prompt=self._build_prompt(script=script, job=job),
            system_prompt=(
                "You are analyzing an imported script for consistency "
                "with a project's own settings. You are not the "
                "author - never rewrite or correct the script, only "
                "report what you observe."
            ),
            prompt_version="script_intake_analysis_prompt_v1.0.0",
            dry_run_response=(
                f"DETECTED_LANGUAGE: {job.language}\n"
                "LANGUAGE_MATCH: yes\n"
                "GENRE_FIT: yes\n"
                "GENRE_NOTE: none\n"
                "AUDIENCE_FIT: yes\n"
                "AUDIENCE_NOTE: none\n"
                "PLATFORM_FIT: yes\n"
                "PLATFORM_NOTE: none"
            ),
            metadata={
                "agent": "ScriptIntakeService",
                "workflow": "script_intake_analysis",
                "topic": job.topic,
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

            raise RuntimeError(f"Script intake analysis failed: {error_message}")

        content = (service_result.result.content or "").strip()

        return self._parse_mismatches(content, job=job)

    def intake(
        self,
        *,
        job: VideoJob,
        raw_text: str,
        mode: ScriptIntakeMode,
    ) -> ScriptIntakeResult:
        script = self.normalize_text_to_script(
            raw_text=raw_text,
            topic=job.topic,
            genre_id=job.genre_id,
            target_duration_seconds=job.target_duration_seconds,
        )

        mismatches: list[ScriptIntakeMismatch] = []

        # TRUST_MY_SCRIPT deliberately skips the analysis call - the
        # whole point of that mode is "don't second-guess this."
        if mode != ScriptIntakeMode.TRUST_MY_SCRIPT:
            mismatches = self.analyze_mismatches(script=script, job=job)

        estimated_duration = (
            max(segment.end_seconds for segment in script.segments)
            if script.segments
            else 0.0
        )

        result = ScriptIntakeResult(
            mode=mode,
            script=script,
            word_count=script.word_count,
            estimated_duration_seconds=estimated_duration,
            target_duration_seconds=job.target_duration_seconds,
            mismatches=mismatches,
        )

        if result.has_significant_duration_mismatch:
            result = result.model_copy(
                update={
                    "mismatches": [
                        *result.mismatches,
                        ScriptIntakeMismatch(
                            field="duration",
                            expected=f"~{job.target_duration_seconds}s",
                            detected=f"~{estimated_duration:.0f}s",
                            note=(
                                "Estimated narration duration differs "
                                "from the project's target duration by "
                                f"more than 20% "
                                f"({result.duration_mismatch_ratio:.0%})."
                            ),
                        ),
                    ]
                }
            )

        return result

    @staticmethod
    def _build_prompt(*, script: GeneratedScript, job: VideoJob) -> str:
        return (
            f"Project settings - genre: {job.genre_id}, language: "
            f"{job.language}, target audience: {job.target_audience}, "
            f"platform: {job.platform.value}.\n\n"
            f"Imported script narration:\n{script.full_narration}\n\n"
            "Return exactly these labeled fields:\n"
            "DETECTED_LANGUAGE: <the language this script is actually "
            "written in>\n"
            "LANGUAGE_MATCH: <yes or no - does it match the project "
            "language above>\n"
            "GENRE_FIT: <yes or no - does the content fit the "
            "project's genre>\n"
            "GENRE_NOTE: <one short sentence, or 'none' if it fits>\n"
            "AUDIENCE_FIT: <yes or no - does it suit the target "
            "audience>\n"
            "AUDIENCE_NOTE: <one short sentence, or 'none' if it fits>\n"
            "PLATFORM_FIT: <yes or no - is it suitable for the target "
            "platform>\n"
            "PLATFORM_NOTE: <one short sentence, or 'none' if it fits>"
        )

    @staticmethod
    def _parse_mismatches(content: str, *, job: VideoJob) -> list[ScriptIntakeMismatch]:
        mismatches: list[ScriptIntakeMismatch] = []

        detected_language = extract_labeled_field(content, "DETECTED_LANGUAGE")
        language_match = extract_labeled_field(content, "LANGUAGE_MATCH")

        if (
            detected_language
            and language_match
            and language_match.strip().lower() != "yes"
        ):
            mismatches.append(
                ScriptIntakeMismatch(
                    field="language",
                    expected=job.language,
                    detected=detected_language.strip(),
                    note="The imported script's language does not match "
                    "the project's configured language.",
                )
            )

        for field_label, note_label, field_name, expected in (
            ("GENRE_FIT", "GENRE_NOTE", "genre", job.genre_id),
            ("AUDIENCE_FIT", "AUDIENCE_NOTE", "audience", job.target_audience),
            ("PLATFORM_FIT", "PLATFORM_NOTE", "platform", job.platform.value),
        ):
            fit = extract_labeled_field(content, field_label)

            if fit and fit.strip().lower() != "yes":
                note = extract_labeled_field(content, note_label)
                mismatches.append(
                    ScriptIntakeMismatch(
                        field=field_name,
                        expected=expected,
                        detected="mismatch detected",
                        note=(
                            note.strip()
                            if note and note.strip().lower() != "none"
                            else f"The imported script may not fit the "
                            f"project's {field_name}."
                        ),
                    )
                )

        return mismatches
