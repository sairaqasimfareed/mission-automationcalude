from __future__ import annotations

import json

import pytest

from src.models.artifact_lifecycle import (
    ArtifactLifecycleStatus,
    ArtifactProvenance,
    ArtifactType,
    ArtifactVersionRecord,
)
from src.models.video_job import VideoJob
from src.services.artifact_lifecycle_service import (
    ArtifactDependencyGraphService,
    ArtifactLifecycleService,
)


def _record(
    *,
    artifact_id: str = "hook-1",
    project_id: str = "project-1",
    artifact_type: ArtifactType = ArtifactType.HOOK,
    version_number: int = 1,
    status: ArtifactLifecycleStatus = ArtifactLifecycleStatus.DRAFT,
    content: str = "content",
    input_version_ids: list[str] | None = None,
) -> ArtifactVersionRecord:
    record = ArtifactVersionRecord(
        artifact_id=artifact_id,
        project_id=project_id,
        artifact_type=artifact_type,
        version_number=version_number,
        content_hash=ArtifactVersionRecord.compute_content_hash(content),
        input_version_ids=input_version_ids or [],
    )
    record.status = status

    return record


# --- ArtifactVersionRecord / hash immutability ---------------------------


def test_compute_content_hash_is_stable_for_identical_content() -> None:
    first = ArtifactVersionRecord.compute_content_hash("hello world")
    second = ArtifactVersionRecord.compute_content_hash("hello world")

    assert first == second


def test_compute_content_hash_differs_for_different_content() -> None:
    first = ArtifactVersionRecord.compute_content_hash("hello world")
    second = ArtifactVersionRecord.compute_content_hash("hello there")

    assert first != second


def test_two_versions_of_identical_content_share_the_same_hash() -> None:
    service = ArtifactLifecycleService()
    ledger: list[ArtifactVersionRecord] = []

    v1 = service.create_version(
        ledger,
        artifact_id="hook-1",
        project_id="project-1",
        artifact_type=ArtifactType.HOOK,
        content="Did you know...",
    )
    ledger.append(v1)

    v2 = service.create_version(
        ledger,
        artifact_id="hook-1",
        project_id="project-1",
        artifact_type=ArtifactType.HOOK,
        content="Did you know...",
    )

    assert v1.content_hash == v2.content_hash
    assert v1.id != v2.id


# --- create_version / version numbering -----------------------------------


def test_create_version_starts_at_one() -> None:
    service = ArtifactLifecycleService()

    record = service.create_version(
        [],
        artifact_id="hook-1",
        project_id="project-1",
        artifact_type=ArtifactType.HOOK,
        content="v1",
    )

    assert record.version_number == 1


def test_create_version_increments_from_the_ledger() -> None:
    service = ArtifactLifecycleService()
    v1 = _record(version_number=1)
    v2 = _record(version_number=2)

    record = service.create_version(
        [v1, v2],
        artifact_id="hook-1",
        project_id="project-1",
        artifact_type=ArtifactType.HOOK,
        content="v3",
    )

    assert record.version_number == 3


def test_create_version_numbering_is_independent_per_artifact_id() -> None:
    service = ArtifactLifecycleService()
    other_artifact = _record(artifact_id="script-1", version_number=5)

    record = service.create_version(
        [other_artifact],
        artifact_id="hook-1",
        project_id="project-1",
        artifact_type=ArtifactType.HOOK,
        content="v1",
    )

    assert record.version_number == 1


def test_create_version_records_input_lineage_and_provenance() -> None:
    service = ArtifactLifecycleService()

    record = service.create_version(
        [],
        artifact_id="script-1",
        project_id="project-1",
        artifact_type=ArtifactType.SCRIPT,
        content="script text",
        input_version_ids=["hook-version-id", "research-version-id"],
        provenance=ArtifactProvenance(provider_name="openai", model_name="gpt"),
    )

    assert record.input_version_ids == ["hook-version-id", "research-version-id"]
    assert record.provenance.provider_name == "openai"


# --- state machine ----------------------------------------------------------


def test_draft_can_only_move_to_generating() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.DRAFT)

    result = service.transition(record, ArtifactLifecycleStatus.GENERATING)

    assert result.status == ArtifactLifecycleStatus.GENERATING


def test_draft_cannot_move_directly_to_approved() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.DRAFT)

    with pytest.raises(ValueError, match="draft"):
        service.transition(record, ArtifactLifecycleStatus.APPROVED)


def test_generating_can_fall_back_to_draft_on_failure() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.GENERATING)

    result = service.transition(record, ArtifactLifecycleStatus.DRAFT)

    assert result.status == ArtifactLifecycleStatus.DRAFT


def test_generated_can_go_straight_to_approved_without_review() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.GENERATED)

    result = service.approve(record)

    assert result.status == ArtifactLifecycleStatus.APPROVED


def test_under_review_can_require_revision() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.UNDER_REVIEW)

    result = service.transition(record, ArtifactLifecycleStatus.REVISION_REQUIRED)

    assert result.status == ArtifactLifecycleStatus.REVISION_REQUIRED


def test_revision_required_cannot_go_back_to_generating() -> None:
    """
    A version stuck at REVISION_REQUIRED never becomes APPROVED itself -
    "Ask Primary to Revise" always creates a *new* artifact version
    (create_version()) rather than resurrecting this one, matching the
    redesign's "revisions never mutate approved/reviewed history" rule.
    """

    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.REVISION_REQUIRED)

    with pytest.raises(ValueError):
        service.transition(record, ArtifactLifecycleStatus.GENERATING)


def test_superseded_and_invalidated_are_terminal() -> None:
    service = ArtifactLifecycleService()

    for terminal_status in (
        ArtifactLifecycleStatus.SUPERSEDED,
        ArtifactLifecycleStatus.INVALIDATED,
    ):
        record = _record(status=terminal_status)

        for target in ArtifactLifecycleStatus:
            with pytest.raises(ValueError):
                service.transition(record, target)


def test_transition_never_mutates_the_original_record() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.DRAFT)

    service.transition(record, ArtifactLifecycleStatus.GENERATING)

    assert record.status == ArtifactLifecycleStatus.DRAFT


def test_transition_never_changes_the_content_hash() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.GENERATED)

    result = service.approve(record)

    assert result.content_hash == record.content_hash


def test_invalidation_reason_is_recorded_on_transition() -> None:
    service = ArtifactLifecycleService()
    record = _record(status=ArtifactLifecycleStatus.APPROVED)

    result = service.transition(
        record,
        ArtifactLifecycleStatus.INVALIDATED,
        invalidation_reason="Upstream research was revised.",
    )

    assert result.invalidation_reason == "Upstream research was revised."


# --- dependency graph / downstream impact -----------------------------------


def test_compute_downstream_impact_finds_a_direct_dependent() -> None:
    upstream = _record(artifact_id="research-1", artifact_type=ArtifactType.RESEARCH)
    downstream = _record(
        artifact_id="hook-1",
        artifact_type=ArtifactType.HOOK,
        input_version_ids=[str(upstream.id)],
    )
    ledger = [upstream, downstream]

    impact = ArtifactDependencyGraphService.compute_downstream_impact(
        ledger, str(upstream.id)
    )

    assert impact == [downstream]


def test_compute_downstream_impact_is_transitive() -> None:
    research = _record(artifact_id="research-1", artifact_type=ArtifactType.RESEARCH)
    hook = _record(
        artifact_id="hook-1",
        artifact_type=ArtifactType.HOOK,
        input_version_ids=[str(research.id)],
    )
    script = _record(
        artifact_id="script-1",
        artifact_type=ArtifactType.SCRIPT,
        input_version_ids=[str(hook.id)],
    )
    ledger = [research, hook, script]

    impact = ArtifactDependencyGraphService.compute_downstream_impact(
        ledger, str(research.id)
    )

    assert {record.artifact_id for record in impact} == {"hook-1", "script-1"}


def test_compute_downstream_impact_handles_branching_dependencies() -> None:
    """
    One upstream version feeding two different downstream artifact
    types, both of which feed a third - the exact branching case the
    redesign plan calls out as a required test.
    """

    research = _record(artifact_id="research-1", artifact_type=ArtifactType.RESEARCH)
    hook = _record(
        artifact_id="hook-1",
        artifact_type=ArtifactType.HOOK,
        input_version_ids=[str(research.id)],
    )
    story = _record(
        artifact_id="story-1",
        artifact_type=ArtifactType.STORY_ARCHITECTURE,
        input_version_ids=[str(research.id)],
    )
    script = _record(
        artifact_id="script-1",
        artifact_type=ArtifactType.SCRIPT,
        input_version_ids=[str(hook.id), str(story.id)],
    )
    ledger = [research, hook, story, script]

    impact = ArtifactDependencyGraphService.compute_downstream_impact(
        ledger, str(research.id)
    )

    assert {record.artifact_id for record in impact} == {
        "hook-1",
        "story-1",
        "script-1",
    }
    # script only appears once even though it is reachable via both
    # hook and story.
    assert len(impact) == 3


def test_compute_downstream_impact_returns_empty_for_a_leaf_version() -> None:
    leaf = _record()

    impact = ArtifactDependencyGraphService.compute_downstream_impact(
        [leaf], str(leaf.id)
    )

    assert impact == []


def test_invalidate_dependents_marks_only_downstream_versions() -> None:
    research = _record(
        artifact_id="research-1",
        artifact_type=ArtifactType.RESEARCH,
        status=ArtifactLifecycleStatus.APPROVED,
    )
    hook = _record(
        artifact_id="hook-1",
        artifact_type=ArtifactType.HOOK,
        status=ArtifactLifecycleStatus.APPROVED,
        input_version_ids=[str(research.id)],
    )
    unrelated = _record(
        artifact_id="topic-1",
        artifact_type=ArtifactType.TOPIC,
        status=ArtifactLifecycleStatus.APPROVED,
    )
    ledger = [research, hook, unrelated]

    updated = ArtifactDependencyGraphService().invalidate_dependents(
        ledger, str(research.id), reason="Research was revised."
    )

    by_artifact_id = {record.artifact_id: record for record in updated}

    assert by_artifact_id["research-1"].status == ArtifactLifecycleStatus.APPROVED
    assert by_artifact_id["hook-1"].status == ArtifactLifecycleStatus.INVALIDATED
    assert by_artifact_id["hook-1"].invalidation_reason == "Research was revised."
    assert by_artifact_id["topic-1"].status == ArtifactLifecycleStatus.APPROVED


def test_invalidate_dependents_preserves_history_rather_than_deleting() -> None:
    research = _record(artifact_id="research-1")
    hook = _record(
        artifact_id="hook-1",
        status=ArtifactLifecycleStatus.APPROVED,
        input_version_ids=[str(research.id)],
    )
    ledger = [research, hook]

    updated = ArtifactDependencyGraphService().invalidate_dependents(
        ledger, str(research.id), reason="test"
    )

    assert len(updated) == len(ledger)
    assert {record.id for record in updated} == {record.id for record in ledger}


def test_invalidate_dependents_does_not_double_invalidate_a_terminal_record() -> None:
    research = _record(artifact_id="research-1")
    already_superseded = _record(
        artifact_id="hook-1",
        status=ArtifactLifecycleStatus.SUPERSEDED,
        input_version_ids=[str(research.id)],
    )
    ledger = [research, already_superseded]

    updated = ArtifactDependencyGraphService().invalidate_dependents(
        ledger, str(research.id), reason="test"
    )

    hook_after = next(r for r in updated if r.artifact_id == "hook-1")
    assert hook_after.status == ArtifactLifecycleStatus.SUPERSEDED
    assert hook_after.invalidation_reason is None


@pytest.mark.parametrize(
    "status",
    [
        ArtifactLifecycleStatus.DRAFT,
        ArtifactLifecycleStatus.GENERATING,
        ArtifactLifecycleStatus.GENERATED,
        ArtifactLifecycleStatus.UNDER_REVIEW,
        ArtifactLifecycleStatus.REVISION_REQUIRED,
        ArtifactLifecycleStatus.APPROVED,
    ],
)
def test_invalidate_dependents_works_regardless_of_the_dependents_own_status(
    status: ArtifactLifecycleStatus,
) -> None:
    """
    Regression test (found via external audit): invalidate_dependents()
    unconditionally calls transition(..., INVALIDATED) on every
    non-terminal downstream record - before this fix, ALLOWED_TRANSITIONS
    only permitted ->INVALIDATED from APPROVED/REVISION_REQUIRED, so a
    dependent still in DRAFT/GENERATING/GENERATED/UNDER_REVIEW raised
    ValueError. Every dependent status short of the two terminal ones
    must now invalidate cleanly.
    """
    research = _record(
        artifact_id="research-1", status=ArtifactLifecycleStatus.APPROVED
    )
    dependent = _record(
        artifact_id="hook-1",
        status=status,
        input_version_ids=[str(research.id)],
    )
    ledger = [research, dependent]

    updated = ArtifactDependencyGraphService().invalidate_dependents(
        ledger, str(research.id), reason="Research was revised."
    )

    dependent_after = next(r for r in updated if r.artifact_id == "hook-1")
    assert dependent_after.status == ArtifactLifecycleStatus.INVALIDATED


def test_invalidate_dependents_is_a_noop_when_nothing_depends_on_it() -> None:
    leaf = _record()

    updated = ArtifactDependencyGraphService().invalidate_dependents(
        [leaf], str(leaf.id), reason="test"
    )

    assert updated == [leaf]


# --- backward compatibility -------------------------------------------------


def test_old_video_job_json_without_artifact_versions_loads_with_an_empty_ledger() -> (
    None
):
    """
    A project file saved before this field existed has no
    "artifact_versions" key at all - Pydantic's default_factory must
    absorb that silently, the same proven pattern every other
    VideoJob field addition this session has relied on (no migration
    code, ever).
    """

    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    old_shape = json.loads(job.model_dump_json())
    del old_shape["artifact_versions"]

    reloaded = VideoJob.model_validate(old_shape)

    assert reloaded.artifact_versions == []


def test_video_job_round_trips_a_populated_artifact_ledger() -> None:
    service = ArtifactLifecycleService()
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="test niche",
        topic="Test topic",
    )
    job.artifact_versions = [
        service.create_version(
            [],
            artifact_id="hook-1",
            project_id=str(job.id),
            artifact_type=ArtifactType.HOOK,
            content="Did you know...",
        )
    ]

    reloaded = VideoJob.model_validate_json(job.model_dump_json())

    assert len(reloaded.artifact_versions) == 1
    assert reloaded.artifact_versions[0].artifact_id == "hook-1"
    assert (
        reloaded.artifact_versions[0].content_hash
        == job.artifact_versions[0].content_hash
    )
