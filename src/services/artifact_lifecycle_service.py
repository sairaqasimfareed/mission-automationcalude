from __future__ import annotations

from datetime import UTC, datetime

from src.models.artifact_lifecycle import (
    ArtifactLifecycleStatus,
    ArtifactProvenance,
    ArtifactType,
    ArtifactVersionRecord,
)

_TERMINAL_STATUSES = frozenset(
    {ArtifactLifecycleStatus.SUPERSEDED, ArtifactLifecycleStatus.INVALIDATED}
)


class ArtifactLifecycleService:
    """
    The one canonical state machine every artifact type shares
    (Content Studio Redesign, Phase 1). Operates on a plain
    `list[ArtifactVersionRecord]` ledger - the same append-only,
    never-delete convention `VideoJob.content_decisions`/
    `.stale_artifacts` already use elsewhere in this codebase - rather
    than owning its own storage, so it can sit on `VideoJob` as one
    more field without a new persistence mechanism.

    Deliberately does not touch any of the ~40 existing per-artifact
    status enums (ScriptStatus, ResearchStatus, ...) - those keep
    governing their own models exactly as before. This is a second,
    parallel ledger new artifact types register into as each
    workspace is migrated onto the canonical engine (see
    docs/CONTENT_STUDIO_REDESIGN_BASELINE.md), not a replacement for
    what already exists.
    """

    ALLOWED_TRANSITIONS: dict[
        ArtifactLifecycleStatus, frozenset[ArtifactLifecycleStatus]
    ] = {
        ArtifactLifecycleStatus.DRAFT: frozenset({ArtifactLifecycleStatus.GENERATING}),
        ArtifactLifecycleStatus.GENERATING: frozenset(
            {ArtifactLifecycleStatus.GENERATED, ArtifactLifecycleStatus.DRAFT}
        ),
        ArtifactLifecycleStatus.GENERATED: frozenset(
            {
                ArtifactLifecycleStatus.UNDER_REVIEW,
                ArtifactLifecycleStatus.APPROVED,
                ArtifactLifecycleStatus.REVISION_REQUIRED,
            }
        ),
        ArtifactLifecycleStatus.UNDER_REVIEW: frozenset(
            {
                ArtifactLifecycleStatus.APPROVED,
                ArtifactLifecycleStatus.REVISION_REQUIRED,
            }
        ),
        # REVISION_REQUIRED never transitions back to GENERATING for the
        # *same* version - "Ask Primary to Revise" always creates a new
        # artifact version (create_version(), with this version's id in
        # the new version's input_version_ids) rather than mutating this
        # one's history. The only forward moves for a version stuck here
        # are becoming superseded by that new version, or being
        # invalidated outright.
        ArtifactLifecycleStatus.REVISION_REQUIRED: frozenset(
            {ArtifactLifecycleStatus.SUPERSEDED, ArtifactLifecycleStatus.INVALIDATED}
        ),
        ArtifactLifecycleStatus.APPROVED: frozenset(
            {ArtifactLifecycleStatus.SUPERSEDED, ArtifactLifecycleStatus.INVALIDATED}
        ),
        ArtifactLifecycleStatus.SUPERSEDED: frozenset(),
        ArtifactLifecycleStatus.INVALIDATED: frozenset(),
    }

    def create_version(
        self,
        ledger: list[ArtifactVersionRecord],
        *,
        artifact_id: str,
        project_id: str,
        artifact_type: ArtifactType,
        content: str,
        input_version_ids: list[str] | None = None,
        provenance: ArtifactProvenance | None = None,
    ) -> ArtifactVersionRecord:
        """
        Create the next version for one logical artifact.

        version_number is derived from the ledger itself (highest
        existing version for this artifact_id, plus one) rather than
        tracked separately - the ledger is the single source of truth
        for how many versions exist.
        """

        existing = [record for record in ledger if record.artifact_id == artifact_id]
        next_version_number = (
            max((record.version_number for record in existing), default=0) + 1
        )

        return ArtifactVersionRecord(
            artifact_id=artifact_id,
            project_id=project_id,
            artifact_type=artifact_type,
            version_number=next_version_number,
            content_hash=ArtifactVersionRecord.compute_content_hash(content),
            input_version_ids=list(input_version_ids or []),
            provenance=provenance or ArtifactProvenance(),
        )

    def transition(
        self,
        record: ArtifactVersionRecord,
        new_status: ArtifactLifecycleStatus,
        *,
        invalidation_reason: str | None = None,
    ) -> ArtifactVersionRecord:
        """
        Return a new record reflecting one legal state transition.

        Never mutates `record` in place - callers hold a ledger list
        and are expected to replace the old record with the returned
        one (matching `id`, so it's the same logical entry advancing
        through its lifecycle, not a new version).
        """

        allowed = self.ALLOWED_TRANSITIONS.get(record.status, frozenset())

        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition artifact from {record.status.value} to "
                f"{new_status.value}."
            )

        update: dict[str, object] = {
            "status": new_status,
            "updated_at": datetime.now(UTC),
        }

        if invalidation_reason is not None:
            update["invalidation_reason"] = invalidation_reason

        return record.model_copy(update=update)

    def approve(self, record: ArtifactVersionRecord) -> ArtifactVersionRecord:
        return self.transition(record, ArtifactLifecycleStatus.APPROVED)


class ArtifactDependencyGraphService:
    """
    Read-only traversal over one project's artifact ledger, treating
    every record's `input_version_ids` as edges pointing backward to
    its upstream inputs. Walking those edges *forward* from a given
    version answers "what actually depends on this" - the impact
    calculation the redesign plan requires before Unapprove ever
    touches anything.
    """

    @staticmethod
    def compute_downstream_impact(
        ledger: list[ArtifactVersionRecord], version_id: str
    ) -> list[ArtifactVersionRecord]:
        """
        Return every version transitively depending on version_id,
        via breadth-first traversal so branching dependencies (one
        version feeding two different downstream artifact types, both
        of which feed a third) are all found, not just the first
        chain discovered.
        """

        impacted: list[ArtifactVersionRecord] = []
        visited: set[str] = {version_id}
        frontier: set[str] = {version_id}

        while frontier:
            next_frontier: set[str] = set()

            for record in ledger:
                record_id = str(record.id)

                if record_id in visited:
                    continue

                if any(input_id in frontier for input_id in record.input_version_ids):
                    impacted.append(record)
                    next_frontier.add(record_id)
                    visited.add(record_id)

            frontier = next_frontier

        return impacted

    def invalidate_dependents(
        self,
        ledger: list[ArtifactVersionRecord],
        version_id: str,
        *,
        reason: str,
    ) -> list[ArtifactVersionRecord]:
        """
        Return a new ledger with every non-terminal version downstream
        of version_id marked INVALIDATED, and every other record
        unchanged. Already SUPERSEDED/INVALIDATED dependents are left
        exactly as they are - invalidation is idempotent, not a second
        reason stacked onto an already-terminal record.

        Non-destructive by construction: this returns replacement
        records via ArtifactLifecycleService.transition(), it never
        removes anything from the ledger.
        """

        impacted_ids = {
            str(record.id)
            for record in self.compute_downstream_impact(ledger, version_id)
            if record.status not in _TERMINAL_STATUSES
        }

        if not impacted_ids:
            return list(ledger)

        lifecycle_service = ArtifactLifecycleService()
        updated: list[ArtifactVersionRecord] = []

        for record in ledger:
            if str(record.id) in impacted_ids:
                updated.append(
                    lifecycle_service.transition(
                        record,
                        ArtifactLifecycleStatus.INVALIDATED,
                        invalidation_reason=reason,
                    )
                )
            else:
                updated.append(record)

        return updated
