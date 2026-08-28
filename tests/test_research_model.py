from __future__ import annotations

from src.models.research import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
    SourceStatus,
)
from src.models.research_evidence import (
    ContradictionStatus,
    EvidenceRecord,
    EvidenceSupportType,
    ManualResearchEdit,
    ResearchFact,
)


def _source(*, status: SourceStatus = SourceStatus.ACCEPTED) -> ResearchSource:
    return ResearchSource(
        title="Example Research Article",
        url="https://example.com/research",
        publisher="Example Publisher",
        notes="Used only for model testing.",
        confidence_score=85,
        status=status,
    )


def _research(*, sources: list[ResearchSource] | None = None) -> ResearchResult:
    return ResearchResult(
        topic="Top 10 Hidden Underground Cities",
        research_summary="A structured research summary for testing the Research Agent.",
        key_facts=[
            "Some underground cities were built for protection.",
            "Several contain tunnels, homes, and storage areas.",
        ],
        interesting_angles=[
            "Why entire communities moved underground.",
            "How these cities survived without modern technology.",
        ],
        potential_hooks=["Beneath ordinary streets lie cities built to disappear."],
        risk_notes=["Historical dates must be verified before script generation."],
        sources=sources if sources is not None else [_source()],
        fact_confidence_score=85,
        prompt_version="research_prompt_v1.0.0",
        status=ResearchStatus.UNDER_REVIEW,
    )


def test_research_result_stores_every_field() -> None:
    research = _research()

    assert research.topic == "Top 10 Hidden Underground Cities"
    assert research.status == ResearchStatus.UNDER_REVIEW
    assert research.prompt_version == "research_prompt_v1.0.0"
    assert len(research.key_facts) == 2
    assert len(research.sources) == 1
    assert research.fact_confidence_score == 85


def test_research_source_defaults() -> None:
    source = ResearchSource(title="A source")

    assert source.url is None
    assert source.confidence_score == 0


def test_research_source_phase_8_fields_default() -> None:
    source = _source()

    assert source.date is None
    assert source.retrieved_at is None
    assert source.status == SourceStatus.ACCEPTED


def test_research_source_status_can_be_rejected() -> None:
    source = _source(status=SourceStatus.REJECTED)

    assert source.status == SourceStatus.REJECTED


def test_research_result_phase_8_fields_default_to_empty() -> None:
    research = _research()

    assert research.structured_facts == []
    assert research.research_gaps == []
    assert research.manual_edits == []


def test_research_fact_is_supported_reflects_evidence() -> None:
    source = _source()
    unsupported = ResearchFact(text="An unverified claim.")
    supported = ResearchFact(
        text="A verified claim.",
        evidence=[
            EvidenceRecord(
                source_id=source.id,
                confidence=80,
                support_type=EvidenceSupportType.DIRECT,
            )
        ],
    )

    assert unsupported.is_supported is False
    assert supported.is_supported is True


def test_evidence_record_defaults_to_no_contradiction() -> None:
    source = _source()
    record = EvidenceRecord(
        source_id=source.id, confidence=50, support_type=EvidenceSupportType.INFERRED
    )

    assert record.contradiction_status == ContradictionStatus.NONE


def test_manual_research_edit_defaults_to_unverified() -> None:
    edit = ManualResearchEdit(text="A manually added note.")

    assert edit.is_verified is False
    assert edit.verification_notes is None


def test_backward_compatible_round_trip_without_phase_8_fields() -> None:
    """
    A ResearchResult/ResearchSource JSON saved before Phase 8 has none
    of the new keys at all - Pydantic's defaults must absorb that
    silently rather than raising.
    """

    research = _research()
    raw = research.model_dump_json()

    reloaded = ResearchResult.model_validate_json(raw)

    assert reloaded.structured_facts == []
    assert reloaded.research_gaps == []
    assert reloaded.manual_edits == []
    assert reloaded.sources[0].status == SourceStatus.ACCEPTED
