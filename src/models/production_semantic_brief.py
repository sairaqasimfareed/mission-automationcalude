from __future__ import annotations

import hashlib
from itertools import pairwise
from uuid import UUID

from pydantic import Field, model_validator

from src.models.base import MissionBaseModel


class ProductionSemanticSegment(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 1: one time-bounded
    slice of production intent - narrative, emotional, pacing, visual,
    voice, music, SFX, editing and transition intent for one span of
    the locked script.

    Deliberately carries short descriptive *intent* strings, not fully
    resolved production directives (camera angles, exact asset IDs,
    ...) - resolving intent into a concrete shot/prompt is Phases 3-4's
    job. This segment is a one-to-one projection of one
    GeneratedScript.segments entry (never invented independently), so
    "every second of the production timeline is owned by a semantic
    segment" holds by construction: GeneratedScript's own validator
    already guarantees its segments are gapless and ordered.
    """

    segment_number: int = Field(ge=1)
    start_seconds: float = Field(ge=0.0)
    end_seconds: float = Field(gt=0.0)

    # This codebase has no separate "section" concept distinct from a
    # story beat (see src/models/story_blueprint.py's StoryBeat) - a
    # documented simplification, not a silently-guessed one:
    # beat_type doubles as the PDF's "section_id" binding, and beat_id
    # is the originating StoryBeat's own id where one could be matched
    # by time range (None when no story_blueprint was supplied, e.g.
    # a Script Intake-originated script that never had a blueprint).
    beat_id: UUID | None = None
    beat_type: str = Field(min_length=1)

    narrative_intent: str = Field(min_length=1)
    emotional_intent: str = Field(min_length=1)
    pacing_intent: str = Field(min_length=1)
    visual_intent: str = Field(min_length=1)
    voice_intent: str = Field(min_length=1)
    music_intent: str = Field(min_length=1)
    sfx_intent: str = Field(min_length=1)
    editing_intent: str = Field(min_length=1)
    transition_intent: str = Field(min_length=1)

    # True exactly when the source ScriptSegment is itself tagged as
    # advancing a tracked curiosity loop (ScriptSegment.
    # related_curiosity_loop) - reusing that existing signal directly
    # rather than re-deriving it from InformationRevealMap's
    # normalized positions a second, potentially-drifting way.
    reveal_protected: bool = False
    related_curiosity_loop: str | None = None

    supporting_claims: list[str] = Field(default_factory=list)


class ProductionSemanticBrief(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 1: the full,
    time-bounded production-intent document for one locked script.

    Bound to the exact script lock it was generated from
    (script_lock_hash) so a later re-lock can be told apart from the
    brief that's still current - the same "downstream artifact
    identifies the exact locked script SHA-256" requirement Phase 0
    introduced for Scene, now applied here too.
    """

    script_lock_hash: str = Field(min_length=1)
    target_duration_seconds: int = Field(gt=0)
    segments: list[ProductionSemanticSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_full_coverage(self) -> ProductionSemanticBrief:
        """
        "Generate semantic segments that cover the full locked
        timeline without overlaps or unowned time" - the plan's own
        named quality gate for coverage, enforced mechanically rather
        than trusted from the source script a second time.
        """

        ordered = sorted(self.segments, key=lambda segment: segment.segment_number)

        if ordered[0].start_seconds != 0.0:
            raise ValueError(
                "Production semantic brief must start at 0 seconds - "
                f"got {ordered[0].start_seconds}."
            )

        for current, following in pairwise(ordered):
            if current.end_seconds != following.start_seconds:
                raise ValueError(
                    "Production semantic brief has a gap or overlap between "
                    f"segment {current.segment_number} (ends "
                    f"{current.end_seconds}) and segment "
                    f"{following.segment_number} (starts "
                    f"{following.start_seconds})."
                )

        return self

    @property
    def content_hash(self) -> str:
        """
        Post-Script-Approval Production Plan, Phase 1: "Persist an
        artifact hash/version for downstream staleness detection" -
        the same sha256-over-stable-fields convention
        GeneratedScript.content_hash/ScriptLock already use, so a
        rebuild from unchanged inputs is recognizably identical.
        """

        payload = "|".join(
            f"{segment.segment_number}:{segment.start_seconds}:"
            f"{segment.end_seconds}:{segment.beat_type}:"
            f"{segment.narrative_intent}:{segment.visual_intent}:"
            f"{segment.voice_intent}:{segment.music_intent}:"
            f"{segment.sfx_intent}:{segment.editing_intent}:"
            f"{segment.transition_intent}"
            for segment in sorted(self.segments, key=lambda s: s.segment_number)
        )

        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
