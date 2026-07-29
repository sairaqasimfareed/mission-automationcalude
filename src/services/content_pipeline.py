from __future__ import annotations

from src.models.enums import WorkflowStage
from src.models.video_job import VideoJob
from src.services.research_pipeline import ResearchPipeline
from src.services.script_pipeline import ScriptPipeline
from src.agents.originality_agent.agent import OriginalityAgent


class ContentPipeline:
    """
    Runs the complete content generation workflow.
    """

    def __init__(self) -> None:
        self.research_pipeline = ResearchPipeline()
        self.script_pipeline = ScriptPipeline()
        self.originality_agent = OriginalityAgent()

    def run(self, job: VideoJob) -> VideoJob:

        # Research
        research = self.research_pipeline.run(job.topic)
        job.research = research
        job.current_stage = WorkflowStage.SCRIPT

        # Script
        script = self.script_pipeline.run(research)
        job.script = script
        job.current_stage = WorkflowStage.ORIGINALITY_REVIEW

        # Originality
        originality = self.originality_agent.analyze(script)
        job.originality_review = originality
        job.current_stage = WorkflowStage.QUALITY_CHECK

        return job