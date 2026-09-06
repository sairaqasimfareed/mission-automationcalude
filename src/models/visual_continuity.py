from __future__ import annotations

from enum import Enum

from pydantic import Field, field_validator

from src.models.base import MissionBaseModel


class CanonicalEntityType(str, Enum):
    """
    Post-Script-Approval Production Plan, Phase 2: which kind of
    recurring visual entity one canonical identity records.

    Deliberately narrower than ContinuityEntryType (TIMELINE/FACT
    entries have no visual state to track) and scoped to PERSON/
    LOCATION only for now - both are already reliably extracted by
    the pre-existing ContinuityBibleExtractionService, reused directly
    here rather than re-extracted. PROP/VEHICLE canonical identity
    resolution is a deliberately deferred, honestly-documented gap
    (see VisualContinuityService) - props/vehicles still appear on
    VisualState.props/vehicles as plain names, just without a
    registered canonical identity behind them yet.
    """

    PERSON = "person"
    LOCATION = "location"


class VisualState(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 2: mutable visual
    state at one point in the story - "wardrobe, condition, location,
    time, weather, lighting, props and vehicles," as distinct from a
    CanonicalEntityIdentity's immutable traits.

    Every field defaults to an explicit "unspecified" placeholder
    (never a silent empty string) so a first clip's incoming_state -
    which has no prior clip to inherit from - is honestly marked
    unknown rather than fabricated.
    """

    wardrobe: str = "unspecified"
    condition: str = "unspecified"
    location: str = "unspecified"
    time_of_day: str = "unspecified"
    weather: str = "unspecified"
    lighting: str = "unspecified"
    props: list[str] = Field(default_factory=list)
    vehicles: list[str] = Field(default_factory=list)


class CanonicalEntityIdentity(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 2: one recurring
    person or location's stable identity, reused across every clip
    that features it - "separate immutable traits from mutable
    state."
    """

    entity_type: CanonicalEntityType
    name: str = Field(min_length=1)
    canonical_description: str = Field(min_length=1)

    # Provider-neutral reference asset IDs (Phase 2: "Attach reference
    # assets through provider-neutral IDs") - opaque strings this
    # model never interprets; whatever asset-store IDs a later phase
    # attaches.
    reference_asset_ids: list[str] = Field(default_factory=list)

    @field_validator("name", "canonical_description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Canonical entity identity text cannot be empty.")

        return cleaned


class ClipContinuityEntry(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 2: one clip's
    continuity contract - "incoming state, shot action, and outgoing
    state." Bound to a Scene by scene_number rather than embedding a
    full Scene reference, matching how ProductionSemanticSegment binds
    to a script segment by number rather than duplicating its content.
    """

    scene_number: int = Field(ge=1)
    incoming_state: VisualState
    shot_action: str = Field(min_length=1)
    outgoing_state: VisualState
    entity_names: list[str] = Field(default_factory=list)

    @field_validator("shot_action")
    @classmethod
    def clean_shot_action(cls, value: str) -> str:
        cleaned = value.strip()

        if not cleaned:
            raise ValueError("Clip continuity shot action cannot be empty.")

        return cleaned


class VisualContinuityBible(MissionBaseModel):
    """
    Post-Script-Approval Production Plan, Phase 2: "the authoritative
    visual state machine across every clip boundary" - bound to the
    exact script lock it was built from, matching the same convention
    Phase 1's ProductionSemanticBrief already established.

    Deliberately lenient at construction (no hard validators) -
    mirroring the pre-existing ContinuityBible/ContinuityValidationService
    split, where extraction and validation are two separate passes.
    VisualContinuityValidationService is what actually checks handoff
    equality and unknown-identity references, producing actionable
    diagnostics rather than a raised exception a caller has to catch.
    """

    script_lock_hash: str = Field(min_length=1)
    identities: list[CanonicalEntityIdentity] = Field(default_factory=list)
    clip_entries: list[ClipContinuityEntry] = Field(default_factory=list)

    @property
    def people(self) -> list[CanonicalEntityIdentity]:
        return [
            identity
            for identity in self.identities
            if identity.entity_type == CanonicalEntityType.PERSON
        ]

    @property
    def locations(self) -> list[CanonicalEntityIdentity]:
        return [
            identity
            for identity in self.identities
            if identity.entity_type == CanonicalEntityType.LOCATION
        ]

    def entry_for_scene(self, scene_number: int) -> ClipContinuityEntry | None:
        for entry in self.clip_entries:
            if entry.scene_number == scene_number:
                return entry

        return None


class ContinuityConflictType(str, Enum):
    """What kind of visual continuity problem one conflict records."""

    HANDOFF_MISMATCH = "handoff_mismatch"
    UNKNOWN_IDENTITY = "unknown_identity"


class VisualContinuityConflict(MissionBaseModel):
    """
    One actionable visual continuity problem - "actionable continuity
    conflict diagnostics," mechanically detected, never a claim about
    which side is "wrong" (the same honest framing
    ContinuityInconsistency already uses for the text-level bible).
    """

    conflict_type: ContinuityConflictType
    scene_number: int = Field(ge=1)
    detail: str = Field(min_length=1)


class VisualContinuityValidationResult(MissionBaseModel):
    """Result of checking one VisualContinuityBible for conflicts."""

    script_lock_hash: str = Field(min_length=1)
    conflicts: list[VisualContinuityConflict] = Field(default_factory=list)

    @property
    def is_consistent(self) -> bool:
        return not self.conflicts
