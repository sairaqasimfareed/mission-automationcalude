from __future__ import annotations

from src.models.editorial_profile import EditorialProfile
from src.models.retention_audit import (
    RetentionAuditReport,
    RetentionFinding,
    RetentionIssueType,
)
from src.models.story_blueprint import StoryBeat, StoryBeatType, StoryBlueprint

# A gap between reveal-type beats larger than this multiple of the
# genre's expected average reveal spacing is flagged - two, not one,
# so ordinary variation in beat length is never mistaken for a real
# retention problem.
_MAX_GAP_MULTIPLE = 2.0

_REVEAL_BEAT_TYPES = frozenset(
    {
        StoryBeatType.REVEAL,
        StoryBeatType.MAJOR_REVELATION,
        StoryBeatType.PAYOFF,
    }
)


class RetentionAuditService:
    """
    Rule-based audit of one StoryBlueprint's reveal spacing and
    tension variation against its genre's retention policy, run
    before script generation so a structurally thin blueprint is
    caught before prose is written on top of it. No LLM call - every
    check here is a mechanical comparison of beat positions and counts
    against GenreContentIntelligenceProfile fields already set in
    Sprint A1.
    """

    def audit(
        self,
        *,
        topic: str,
        blueprint: StoryBlueprint,
        editorial_profile: EditorialProfile,
    ) -> RetentionAuditReport:
        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Retention audit topic cannot be empty.")

        content_intelligence = editorial_profile.content_intelligence
        ordered_beats = sorted(blueprint.beats, key=lambda beat: beat.start_seconds)
        reveal_beats = [
            beat for beat in ordered_beats if beat.beat_type in _REVEAL_BEAT_TYPES
        ]

        expected_minimum_reveal_count = max(
            1,
            round(
                content_intelligence.reveal_density_per_minute
                * blueprint.target_duration_seconds
                / 60
            ),
        )

        findings: list[RetentionFinding] = []

        if len(reveal_beats) < expected_minimum_reveal_count:
            findings.append(
                RetentionFinding(
                    issue_type=RetentionIssueType.INSUFFICIENT_REVEAL_DENSITY,
                    description=(
                        f"Blueprint has {len(reveal_beats)} reveal-type beat(s) "
                        f"but this genre expects at least "
                        f"{expected_minimum_reveal_count} for a "
                        f"{blueprint.target_duration_seconds}s video."
                    ),
                )
            )

        findings.extend(
            self._gap_findings(
                ordered_beats=ordered_beats,
                reveal_beats=reveal_beats,
                target_duration_seconds=blueprint.target_duration_seconds,
                reveal_density_per_minute=content_intelligence.reveal_density_per_minute,
            )
        )

        if not blueprint.has_tension_variation:
            findings.append(
                RetentionFinding(
                    issue_type=RetentionIssueType.LOW_TENSION_VARIATION,
                    description=(
                        "Tension level barely varies across this blueprint's "
                        "beats - risks feeling flat regardless of genre."
                    ),
                )
            )

        return RetentionAuditReport(
            topic=normalized_topic,
            genre_id=editorial_profile.genre_id,
            reveal_count=len(reveal_beats),
            expected_minimum_reveal_count=expected_minimum_reveal_count,
            findings=findings,
        )

    @staticmethod
    def _gap_findings(
        *,
        ordered_beats: list[StoryBeat],
        reveal_beats: list[StoryBeat],
        target_duration_seconds: int,
        reveal_density_per_minute: float,
    ) -> list[RetentionFinding]:
        if not ordered_beats:
            return []

        max_allowed_gap_seconds = (60.0 / reveal_density_per_minute) * _MAX_GAP_MULTIPLE

        checkpoints = (
            [0.0]
            + [beat.start_seconds for beat in reveal_beats]
            + [float(target_duration_seconds)]
        )

        findings: list[RetentionFinding] = []

        for gap_start, gap_end in zip(checkpoints, checkpoints[1:], strict=False):
            gap_seconds = gap_end - gap_start

            if gap_seconds > max_allowed_gap_seconds:
                findings.append(
                    RetentionFinding(
                        issue_type=RetentionIssueType.REVEAL_GAP_TOO_LONG,
                        description=(
                            f"{gap_seconds:.0f}s pass with no reveal-type beat "
                            f"starting at {gap_start:.0f}s - this genre's "
                            f"reveal density implies gaps no longer than "
                            f"~{max_allowed_gap_seconds:.0f}s."
                        ),
                        position_seconds=gap_start,
                    )
                )

        return findings
