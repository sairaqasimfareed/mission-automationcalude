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

    Real-world finding, 2026-09-14: this used to record every clip's
    duration_seconds as the SCENE's own planned estimate
    (Scene.estimated_duration_seconds), falling back to the
    candidate's real duration only when a scene number couldn't be
    found at all - which never happens, since `scenes` is always the
    full list. Confirmed directly against a real Google Flow
    generation: a scene planned at 18s whose actual clamped clip was
    really only 8s still recorded duration_seconds=18 here, so
    TimelineBuilderService (`end_time = current_time +
    clip.duration_seconds`) laid the clip into an 18s timeline slot
    for an 8s file. It also silently defeated
    DurationMismatchPolicyService, whose own docstring assumes this
    field already holds the clip's real duration by the time it runs -
    with planned and "actual" forced equal here, it could never detect
    a mismatch at all. Now prefers the candidate's own real duration
    (set from real probed/technically-validated data at every
    construction site - ManualUploadService, LocalAssetSearchService,
    stock search, and SceneAssetWorkflowService's own AI-generate
    path) whenever it's known (> 0), falling back to the scene's
    planned estimate only when no real duration was ever recorded
    (the field's own documented 0.0 default for "not yet known").
    """

    def build_clips(
        self,
        *,
        scenes: list[Scene],
        states: list[SceneAssetState],
    ) -> list[VideoClip]:
        planned_duration_by_scene_number = {
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

            duration_seconds = (
                round(candidate.duration_seconds)
                if candidate.duration_seconds > 0
                else planned_duration_by_scene_number.get(state.scene_number, 0)
            )

            clips.append(
                VideoClip(
                    scene_number=state.scene_number,
                    scene_id=state.scene_id,
                    source_type=(state.selected_source or candidate.source_type),
                    duration_seconds=duration_seconds,
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
