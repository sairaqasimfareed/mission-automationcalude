from __future__ import annotations

from src.agents.originality_agent.agent import OriginalityAgent
from src.agents.scene_planner.agent import ScenePlannerAgent
from src.models.enums import WorkflowStage
from src.models.video_job import VideoJob
from src.services.research_pipeline import ResearchPipeline
from src.services.script_pipeline import ScriptPipeline


class ContentPipeline:
    """Runs the complete core content-generation workflow."""

    def __init__(self) -> None:
        self.research_pipeline = ResearchPipeline()
        self.script_pipeline = ScriptPipeline()
        self.originality_agent = OriginalityAgent()
        self.scene_planner = ScenePlannerAgent()

    def run(self, job: VideoJob) -> VideoJob:
        # Research
        research = self.research_pipeline.run(job.topic)
        job.research = research
        job.current_stage = WorkflowStage.SCRIPT

        # Script generation and Claude-style review
        script = self.script_pipeline.run(research)
        job.script = script
        job.current_stage = WorkflowStage.ORIGINALITY_REVIEW

        # Originality analysis
        originality = self.originality_agent.analyze(script)
        job.originality_review = originality

        # Scene planning
        scenes = self.scene_planner.plan(script)
        job.scenes = scenes

        # Core content is ready for the next quality/policy stage
        job.current_stage = WorkflowStage.QUALITY_CHECK

        return job