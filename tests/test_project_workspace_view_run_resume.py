from __future__ import annotations

from src.desktop.views.project_workspace_view import _BLOCKER_STAGE_TAB


def test_research_plan_blocker_routes_to_content_studio() -> None:
    """
    Regression test (found via external audit): Phase 7's research_plan
    approval gate (ContentIntelligencePipeline.run_research_plan() calls
    approval_gate_service.gate(..., stage="research_plan")) produces a
    ProductionReadinessService Blocker with stage="research_plan".
    Without an entry for it here, _handle_run_resume()'s
    _BLOCKER_STAGE_TAB.get(...) lookup returned None and the "Run/Resume"
    button silently did nothing while a project was blocked on "Approve
    Brief & Start Research."
    """

    assert _BLOCKER_STAGE_TAB.get("research_plan") == "content_studio"


def test_every_content_intelligence_stage_routes_to_content_studio() -> None:
    """
    research_plan should sit alongside every other granular content-
    intelligence stage, all of which route to the same workspace tab -
    this is a mapping-consistency check, not a claim that these stages
    are otherwise related.
    """

    content_intelligence_stages = [
        "content_intelligence",
        "audience_promise",
        "research_plan",
        "research",
        "story_angles",
        "narrative_architecture",
        "hooks",
        "script",
    ]

    for stage in content_intelligence_stages:
        assert _BLOCKER_STAGE_TAB.get(stage) == "content_studio", stage
