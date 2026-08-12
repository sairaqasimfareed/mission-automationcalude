from __future__ import annotations

from src.models.asset_state import SceneAssetState
from src.models.media_strategy import SceneSourceStatus
from src.models.scene import Scene
from src.models.video_clip import VideoClip, VideoClipStatus


class SceneAssetVideoClipBuilderService:
    """
    Bridge resolved SceneAssetState objects into VideoClip objects.

    No pipeline stage previously performed this conversion: the asset
    workflow (SceneAssetWorkflowService/AssetPipelineStage) resolves
    each scene down to a SceneAssetState with a selected, approved
    AssetCandidate, but VideoJob.video_clips - which TimelinePipelineStage
    requires - was never populated from it, for any source type. This
    service is that missing bridge.

    Only scenes whose SceneAssetState.is_ready is true (READY status
    with a selected candidate) produce a clip. Scenes left unresolved
    (skipped, disabled, still waiting) produce no clip, so
    GenreTimelinePipelineService's own "video clips are missing for
    scenes: ..." validation surfaces that gap explicitly rather than
    this service inventing a placeholder.
    """

    def build_clips(
        self,
        *,
        scenes: list[Scene],
        states: list[SceneAssetState],
    ) -> list[VideoClip]:
        duration_by_scene_number = {
            scene.scene_number: scene.estimated_duration_seconds for scene in scenes
        }

        clips: list[VideoClip] = []

        for state in states:
            if not state.is_ready:
                continue

            candidate = state.selected_candidate

            if candidate is None:
                continue

            file_path = candidate.file_path or state.manual_upload_path

            if not file_path:
                continue

            clips.append(
                VideoClip(
                    scene_number=state.scene_number,
                    source_type=(state.selected_source or candidate.source_type),
                    duration_seconds=duration_by_scene_number.get(
                        state.scene_number,
                        int(candidate.duration_seconds),
                    ),
                    provider=candidate.provider,
                    source_url=candidate.source_url,
                    local_file=file_path,
                    license_type=candidate.license_type,
                    resolution=candidate.resolution or "1920x1080",
                    aspect_ratio=candidate.aspect_ratio or "16:9",
                    source_status=SceneSourceStatus.READY,
                    status=VideoClipStatus.READY,
                    metadata=dict(candidate.metadata),
                )
            )

        return clips
