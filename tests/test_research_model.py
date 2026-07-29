from src.models.research import (
    ResearchResult,
    ResearchSource,
    ResearchStatus,
)


source = ResearchSource(
    title="Example Research Article",
    url="https://example.com/research",
    publisher="Example Publisher",
    notes="Used only for model testing.",
    confidence_score=85,
)


research = ResearchResult(
    topic="Top 10 Hidden Underground Cities",
    research_summary=(
        "A structured research summary for testing the Research Agent."
    ),
    key_facts=[
        "Some underground cities were built for protection.",
        "Several contain tunnels, homes, and storage areas.",
    ],
    interesting_angles=[
        "Why entire communities moved underground.",
        "How these cities survived without modern technology.",
    ],
    potential_hooks=[
        "Beneath ordinary streets lie cities built to disappear."
    ],
    risk_notes=[
        "Historical dates must be verified before script generation."
    ],
    sources=[source],
    fact_confidence_score=85,
    prompt_version="research_prompt_v1.0.0",
    status=ResearchStatus.UNDER_REVIEW,
)

print("Topic:", research.topic)
print("Status:", research.status)
print("Prompt version:", research.prompt_version)
print("Facts:", len(research.key_facts))
print("Sources:", len(research.sources))
print("Confidence:", research.fact_confidence_score)

assert research.topic == "Top 10 Hidden Underground Cities"
assert research.status == ResearchStatus.UNDER_REVIEW
assert research.prompt_version == "research_prompt_v1.0.0"
assert len(research.sources) == 1

print("Research model tests completed successfully.")