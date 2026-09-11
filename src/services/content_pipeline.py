from __future__ import annotations

from src.agents.originality_agent.agent import (
    OriginalityAgent,
)
from src.agents.scene_planner.agent import (
    ScenePlannerAgent,
)
from src.models.enums import WorkflowStage
from src.models.video_job import VideoJob
from src.services.llm.llm_service import LLMService
from src.services.research_pipeline import (
    ResearchPipeline,
)
from src.services.script_pipeline import (
    ScriptPipeline,
)


class ContentPipeline:
    """Runs the complete core content-generation workflow."""

    def __init__(
        self,
        *,
        llm_service: LLMService,
        research_pipeline: ResearchPipeline | None = None,
        script_pipeline: ScriptPipeline | None = None,
        originality_agent: OriginalityAgent | None = None,
        scene_planner: ScenePlannerAgent | None = None,
        research_profile_ids: list[str] | None = None,
        research_estimated_cost_usd: float = 0.0,
    ) -> None:
        self.research_pipeline = research_pipeline or ResearchPipeline(
            llm_service=llm_service,
            profile_ids=research_profile_ids,
            estimated_cost_usd=(research_estimated_cost_usd),
        )

        self.script_pipeline = script_pipeline or ScriptPipeline(
            llm_service=llm_service,
            profile_ids=research_profile_ids,
            estimated_cost_usd=research_estimated_cost_usd,
        )

        self.originality_agent = originality_agent or OriginalityAgent()

        self.scene_planner = scene_planner or ScenePlannerAgent()

    def run(
        self,
        job: VideoJob,
    ) -> VideoJob:
        """Run research, script, originality and scene planning."""

        research = self.research_pipeline.run(job.topic)

        job.research = research
        job.current_stage = WorkflowStage.SCRIPT

        # 2026-09-11 real fix, found live: job.target_duration_seconds
        # already existed and was correctly populated at job-creation
        # time, but nothing in this basic pipeline ever read it - a
        # real 40-second test request produced a real 1578-second
        # script. Always passed (not conditional) since every VideoJob
        # has a real value here (default 600s), so script generation
        # is now duration-aware unconditionally rather than only for
        # callers that remember to ask.
        script = self.script_pipeline.run(
            research,
            target_duration_seconds=job.target_duration_seconds,
        )

        job.script = script
        job.current_stage = WorkflowStage.ORIGINALITY_REVIEW

        originality = self.originality_agent.analyze(script)

        job.originality_review = originality

        scenes = self.scene_planner.plan(script, genre_id=job.genre_id)

        job.scenes = scenes
        job.current_stage = WorkflowStage.QUALITY_CHECK

        return job
