from __future__ import annotations

from src.agents.scene_planner.agent import ScenePlannerAgent
from src.agents.veo_generator.agent import VeoGeneratorAgent
from src.models.render_result import RenderResult
from src.models.script import Script
from src.models.video_timeline import VideoTimeline
from src.services.render_service import RenderService


class RenderPipeline:
    """
    Complete dry-run render pipeline.

    Approved Script
            │
            ▼
      Scene Planner
            │
            ▼
      Veo Generator
            │
            ▼
      Video Timeline
            │
            ▼
      Render Service
            │
            ▼
      Final Render Result
    """

    def __init__(self) -> None:
        self.scene_planner = ScenePlannerAgent()
        self.veo_generator = VeoGeneratorAgent()
        self.render_service = RenderService()

    def run(self, script: Script) -> RenderResult:

        scenes = self.scene_planner.plan(script)

        clips = []

        for scene in scenes:
            clips.append(self.veo_generator.generate(scene))

        timeline = VideoTimeline(
            clips=clips,
        )

        timeline.calculate_duration()

        return self.render_service.render(timeline)
