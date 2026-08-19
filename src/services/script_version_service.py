from __future__ import annotations

from src.models.editorial_critique import EditorialCritique, QualityDimension
from src.models.generated_script import GeneratedScript
from src.models.script_version import (
    ScriptChangeClass,
    ScriptVersion,
    ScriptVersionHistory,
)

# Which critique findings drove a revision determines its change
# class - this reuses the same QualityDimension vocabulary
# EditorialCritiqueService already scores against, rather than
# inventing a second classification the revision service would have
# to also understand.
_FACTUAL_DIMENSIONS = frozenset(
    {QualityDimension.FACTUAL_CONFIDENCE, QualityDimension.RESEARCH_GROUNDING}
)
_NARRATIVE_DIMENSIONS = frozenset(
    {
        QualityDimension.RETENTION_ARCHITECTURE,
        QualityDimension.EMOTIONAL_PROGRESSION,
        QualityDimension.NARRATIVE_COHERENCE,
        QualityDimension.CHARACTER_DEPTH,
        QualityDimension.PAYOFF_STRENGTH,
        QualityDimension.CONTINUITY,
    }
)


class ScriptVersionService:
    """
    Tracks a script's revision lineage and classifies each revision's
    downstream impact.

    No LLM call: a real STRUCTURAL/TIMING change is detected
    mechanically by comparing the before/after GeneratedScript, and
    ScriptRevisionService is the only path that produces a revision in
    this architecture, so a FACTUAL/NARRATIVE/STYLE_ONLY split can be
    read directly off the EditorialCritique findings that drove it -
    a text diff alone could not honestly tell a stylistic paraphrase
    from a factual correction.
    """

    def start_history(
        self,
        *,
        topic: str,
        script: GeneratedScript,
    ) -> ScriptVersionHistory:
        """Begin a new version history at the script's first draft."""

        normalized_topic = topic.strip()

        if not normalized_topic:
            raise ValueError("Script version history topic cannot be empty.")

        return ScriptVersionHistory(
            topic=normalized_topic,
            versions=[
                ScriptVersion(
                    version_number=1,
                    script=script,
                    change_summary="Initial generated script.",
                )
            ],
        )

    def add_revision(
        self,
        *,
        history: ScriptVersionHistory,
        revised_script: GeneratedScript,
        critique: EditorialCritique,
        change_summary: str | None = None,
    ) -> ScriptVersionHistory:
        """Append one new version, classifying its impact."""

        current = history.current_version

        if current.locked:
            raise ValueError(
                f"Version {current.version_number} is locked - unlock it "
                "before adding a new revision."
            )

        change_class = self._classify_change(
            previous=current.script,
            revised=revised_script,
            critique=critique,
        )

        new_version = ScriptVersion(
            version_number=current.version_number + 1,
            script=revised_script,
            parent_version_number=current.version_number,
            change_class=change_class,
            change_summary=change_summary or self._default_summary(change_class),
        )

        return history.model_copy(update={"versions": [*history.versions, new_version]})

    def lock_version(
        self,
        *,
        history: ScriptVersionHistory,
        version_number: int,
    ) -> ScriptVersionHistory:
        """Lock one version against further revision."""

        return self._set_lock(
            history=history, version_number=version_number, locked=True
        )

    def unlock_version(
        self,
        *,
        history: ScriptVersionHistory,
        version_number: int,
    ) -> ScriptVersionHistory:
        """Unlock one version, allowing revision to resume."""

        return self._set_lock(
            history=history, version_number=version_number, locked=False
        )

    @staticmethod
    def _set_lock(
        *,
        history: ScriptVersionHistory,
        version_number: int,
        locked: bool,
    ) -> ScriptVersionHistory:
        matched = next(
            (
                version
                for version in history.versions
                if version.version_number == version_number
            ),
            None,
        )

        if matched is None:
            raise ValueError(f"No version {version_number} exists in this history.")

        updated_versions = [
            (
                version.model_copy(update={"locked": locked})
                if version.version_number == version_number
                else version
            )
            for version in history.versions
        ]

        return history.model_copy(update={"versions": updated_versions})

    @staticmethod
    def _classify_change(
        *,
        previous: GeneratedScript,
        revised: GeneratedScript,
        critique: EditorialCritique,
    ) -> ScriptChangeClass:
        previous_ordered = sorted(
            previous.segments, key=lambda segment: segment.segment_number
        )
        revised_ordered = sorted(
            revised.segments, key=lambda segment: segment.segment_number
        )

        if len(previous_ordered) != len(revised_ordered) or any(
            earlier.narrative_function != later.narrative_function
            for earlier, later in zip(previous_ordered, revised_ordered, strict=False)
        ):
            return ScriptChangeClass.STRUCTURAL

        if any(
            earlier.start_seconds != later.start_seconds
            or earlier.end_seconds != later.end_seconds
            for earlier, later in zip(previous_ordered, revised_ordered, strict=False)
        ):
            return ScriptChangeClass.TIMING

        finding_dimensions = {finding.dimension for finding in critique.findings}

        if finding_dimensions & _FACTUAL_DIMENSIONS:
            return ScriptChangeClass.FACTUAL

        if finding_dimensions & _NARRATIVE_DIMENSIONS:
            return ScriptChangeClass.NARRATIVE

        return ScriptChangeClass.STYLE_ONLY

    @staticmethod
    def _default_summary(change_class: ScriptChangeClass) -> str:
        return f"Revision addressing {change_class.value} findings."
