from __future__ import annotations

from collections.abc import Callable

from src.models.google_flow_generation import GoogleFlowGenerationState
from src.models.google_flow_generation import is_terminal_state as _flow_is_terminal
from src.models.muse_generation import is_terminal_state as _muse_is_terminal
from src.models.scene import Scene
from src.models.scene_completeness import (
    SceneCompletenessEntry,
    SceneCompletenessReport,
    SceneCompletenessStatus,
)
from src.models.video_job import VideoJob
from src.services.muse_scene_video_generation_service import (
    MuseSceneVideoGenerationService,
)
from src.services.registry.provider_registry import ProviderRegistry
from src.services.scene_completeness_service import SceneCompletenessService
from src.services.scene_video_generation_service import SceneVideoGenerationService


class SceneGenerationDispatchService:
    """
    Per-scene account picker (locked design, generalized to cover both
    Google Flow and Muse - the same explicit-choice-over-auto-routing
    capability, extended once a second EXTERNAL_UI_VIDEO provider
    existed to route to).

    Google Flow and Muse are two fully independent stacks - separate
    ledgers, separate orchestrators, separate scene-video-generation
    services (see this session's own 2026-09-29 architecture
    investigation for why: ExternalUIGenerationProvider's own request/
    attempt types are concretely Flow-typed, not a shared generic
    base, and generalizing that would mean refactoring an already-
    stable subsystem for no functional gain). This service is the one
    new piece that ties them together for the GUI: given a scene, it
    decides which underlying service actually drives that scene's
    generation, based on Scene.preferred_profile_id.

    Scene.preferred_profile_id is None ("Auto") for every scene by
    default - routes to Google Flow, unchanged from every existing
    job's behavior before Muse existed. Setting it to a specific
    profile_id (which already uniquely identifies both provider and
    account, via ProviderRegistry) routes to whichever service that
    profile actually belongs to. An unregistered profile_id raises a
    clear ValueError immediately, here, rather than being silently
    routed to the wrong service and failing there with a confusing
    "not a Google Flow account" (or "not a Muse account") message.
    """

    def __init__(
        self,
        *,
        registry: ProviderRegistry,
        flow_service: SceneVideoGenerationService,
        muse_service: MuseSceneVideoGenerationService,
    ) -> None:
        self._registry = registry
        self._flow_service = flow_service
        self._muse_service = muse_service

    def generate_one(self, job: VideoJob, scene_number: int) -> SceneCompletenessEntry:
        scene = self._find_scene(job, scene_number)

        return self._resolve_service(scene).generate_one(job, scene_number)

    def generate_all(
        self,
        job: VideoJob,
        *,
        forced_profile_id: str | None = None,
        on_scene_complete: Callable[[VideoJob, int], None] | None = None,
    ) -> SceneCompletenessReport:
        """
        Same "skip already-ready scenes" behavior as each underlying
        service's own generate_all() - reimplemented here (rather than
        delegating to either one directly) since a batch run may now
        dispatch different scenes to different services.

        forced_profile_id ("Generate all" with an account chosen in
        its own dropdown, not the per-scene one): applied as a bulk
        write to EVERY scene's own Scene.preferred_profile_id before
        the run starts, rather than as a separate, hidden one-shot
        override - so the dropdown's own choice becomes visibly each
        scene's own persisted preference afterward (accurate, not a
        silent override), and every scene routes through the exact
        same _resolve_service()/generate_one() path a per-scene choice
        would. None (the default) leaves every scene's own existing
        preferred_profile_id untouched.
        """

        if forced_profile_id is not None:
            for scene in job.scenes:
                scene.preferred_profile_id = forced_profile_id

        already_ready = {
            entry.scene_number
            for entry in SceneCompletenessService().check(job).entries
            if entry.status == SceneCompletenessStatus.READY
        }

        for scene in sorted(job.scenes, key=lambda scene: scene.scene_number):
            if scene.scene_number in already_ready:
                continue

            self.generate_one(job, scene.scene_number)

            if on_scene_complete is not None:
                on_scene_complete(job, scene.scene_number)

        return SceneCompletenessService().check(job)

    def retry_scene_after_auth(
        self, job: VideoJob, scene_number: int
    ) -> SceneCompletenessEntry:
        """
        Routes by whichever ledger actually holds the stuck
        AUTH_REQUIRED attempt, not by Scene.preferred_profile_id -
        same reasoning as abandon_stuck_attempt: an operator may have
        changed the dropdown after a scene got stuck on the other
        provider, and resolving by preferred_profile_id alone would
        call the wrong service and fail with a confusing "no attempt
        waiting on authentication" error.
        """

        self._find_scene(job, scene_number)

        flow_stuck_on_auth = any(
            attempt.request.scene_number == scene_number
            and attempt.state == GoogleFlowGenerationState.AUTH_REQUIRED
            for attempt in job.flow_generation_attempts
        )

        if flow_stuck_on_auth:
            return self._flow_service.retry_scene_after_auth(job, scene_number)

        return self._muse_service.retry_scene_after_auth(job, scene_number)

    def abandon_stuck_attempt(
        self,
        job: VideoJob,
        scene_number: int,
        *,
        force: bool = False,
    ) -> None:
        """
        Checks BOTH ledgers for a non-terminal attempt, since a scene's
        stuck attempt may belong to whichever provider it was actually
        submitted through at the time - not necessarily the one
        Scene.preferred_profile_id currently names (an operator may
        have changed the dropdown after a scene got stuck on the
        other provider). Whichever ledger actually has one is the one
        abandoned; raises ValueError if neither does, matching each
        underlying service's own exact error.

        GoogleFlowAttemptCreditSensitiveError/MuseAttemptCreditSensitiveError
        both propagate unchanged (a GUI caller catches either to show
        the same confirm-before-force dialog Google Flow's own
        "Abandon attempt" button already uses).
        """

        flow_stuck = any(
            attempt.request.scene_number == scene_number
            and not _flow_is_terminal(attempt.state)
            for attempt in job.flow_generation_attempts
        )

        if flow_stuck:
            self._flow_service.abandon_stuck_attempt(job, scene_number, force=force)
            return

        muse_stuck = any(
            attempt.request.scene_number == scene_number
            and not _muse_is_terminal(attempt.state)
            for attempt in job.muse_generation_attempts
        )

        if muse_stuck:
            self._muse_service.abandon_stuck_attempt(job, scene_number, force=force)
            return

        raise ValueError(
            f"Scene {scene_number} has no non-terminal attempt to abandon."
        )

    def _resolve_service(
        self, scene: Scene
    ) -> SceneVideoGenerationService | MuseSceneVideoGenerationService:
        if scene.preferred_profile_id is None:
            return self._flow_service

        try:
            profile = self._registry.get(scene.preferred_profile_id)
        except KeyError:
            raise ValueError(
                f"Scene {scene.scene_number}'s preferred account "
                f"'{scene.preferred_profile_id}' is not registered."
            ) from None

        if profile.provider_name == "Muse":
            return self._muse_service

        return self._flow_service

    @staticmethod
    def _find_scene(job: VideoJob, scene_number: int) -> Scene:
        scene = next(
            (s for s in job.scenes if s.scene_number == scene_number),
            None,
        )

        if scene is None:
            raise ValueError(f"Job has no scene numbered {scene_number}.")

        return scene
