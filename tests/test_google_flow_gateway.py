from __future__ import annotations

import json
from collections.abc import Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from src.api.google_flow_gateway import GoogleFlowLocalGateway
from src.desktop.job_store import InMemoryJobStore
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.models.provider_profile import (
    ProviderCategory,
    ProviderHealthStatus,
    ProviderProfile,
)
from src.models.video_job import VideoJob
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.services.google_flow_account_router_service import (
    GoogleFlowAccountRouterService,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowGenerationOrchestratorService,
)
from src.services.registry.provider_registry import ProviderRegistry


class FakeAdvancingProvider(ExternalUIGenerationProvider):
    """Same fast, deterministic fake used by the orchestrator's own
    unit tests - the gateway's job is HTTP plumbing, not re-proving
    the adapter or the orchestrator's own internal logic."""

    @property
    def provider_name(self) -> str:
        return "Fake Flow"

    def health_check(self) -> bool:
        return True

    @property
    def supported_operations(self) -> frozenset[ExternalUIOperation]:
        return frozenset(
            {
                ExternalUIOperation.SUBMIT,
                ExternalUIOperation.OBSERVE,
                ExternalUIOperation.DOWNLOAD,
            }
        )

    def check_profile_health(self, profile_id: str) -> bool:
        return True

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        current = attempt
        for state in (
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            GoogleFlowGenerationState.PROMPT_PREPARED,
            GoogleFlowGenerationState.ANALYZING,
            GoogleFlowGenerationState.SUBMITTING,
            GoogleFlowGenerationState.SUBMITTED,
            GoogleFlowGenerationState.GENERATING,
        ):
            current = current.with_transition(state)
        return current

    def observe(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        return attempt

    def download(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        return attempt

    def cancel_or_abandon(
        self, attempt: GoogleFlowGenerationAttempt
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)
        raise AssertionError("unreachable")


def _flow_profile(profile_id: str = "flow.primary") -> ProviderProfile:
    return ProviderProfile(
        profile_id=profile_id,
        display_name=profile_id,
        provider_name="Google Flow",
        category=ProviderCategory.EXTERNAL_UI_VIDEO,
        enabled=True,
        health_status=ProviderHealthStatus.HEALTHY,
        browser_profile_reference=f"flow_profiles/{profile_id}",
    )


@pytest.fixture
def gateway() -> Iterator[tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob]]:
    job_store = InMemoryJobStore()
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )
    job_store.add(job)

    registry = ProviderRegistry(profiles=[_flow_profile()])
    router = GoogleFlowAccountRouterService(registry)
    # A high per-account ceiling means these HTTP-level tests exercise
    # the ledger's own scene-level in-flight guard (already unit-
    # tested in isolation in test_google_flow_generation_orchestrator_service.py)
    # rather than the router's separate account-level ceiling - the
    # gateway's own job here is proving HTTP requests reach the real
    # canonical guards at all, not re-proving which specific guard
    # fires first under a default ceiling.
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=FakeAdvancingProvider(),
        account_router=router,
        max_in_flight_per_account=10,
    )

    instance = GoogleFlowLocalGateway(
        job_store=job_store,
        orchestrator=orchestrator,
        provider_registry=registry,
    )
    instance.start()

    yield instance, job_store, job

    instance.stop()


def _post(base_url: str, path: str, payload: dict[str, object]) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(  # noqa: S310
        f"{base_url}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def _get(base_url: str, path: str) -> tuple[int, dict]:
    request = Request(f"{base_url}{path}", method="GET")  # noqa: S310
    try:
        with urlopen(request, timeout=10) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_gateway_binds_to_localhost_by_default(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway

    assert instance.base_url.startswith("http://127.0.0.1:")


def test_create_generation_returns_a_planned_then_generating_attempt(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, job_store, job = gateway

    status, payload = _post(
        instance.base_url,
        f"/v1/video-generations?project_id={job.id}",
        {
            "scene_number": 1,
            "prompt": "A lighthouse at dusk.",
            "prompt_version": "v1",
            "idempotency_key": "req-1",
        },
    )

    assert status == 200
    assert payload["state"] == "generating"
    assert "attempt_id" in payload

    # Persisted through the SAME job_store the desktop GUI would use -
    # GF-35's own API/in-process parity requirement.
    reloaded = job_store.get(job.id)
    assert reloaded is not None
    assert len(reloaded.flow_generation_attempts) == 1


def test_create_generation_requires_project_id(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway

    status, payload = _post(
        instance.base_url,
        "/v1/video-generations",
        {
            "scene_number": 1,
            "prompt": "A lighthouse at dusk.",
            "prompt_version": "v1",
            "idempotency_key": "req-1",
        },
    )

    assert status == 400
    assert "project_id" in payload["error"]


def test_create_generation_rejects_an_unknown_project(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway

    status, payload = _post(
        instance.base_url,
        f"/v1/video-generations?project_id={uuid4()}",
        {
            "scene_number": 1,
            "prompt": "A lighthouse at dusk.",
            "prompt_version": "v1",
            "idempotency_key": "req-1",
        },
    )

    assert status == 404


def test_create_generation_rejects_missing_fields(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, job = gateway

    status, payload = _post(
        instance.base_url,
        f"/v1/video-generations?project_id={job.id}",
        {"scene_number": 1},
    )

    assert status == 400
    assert "Missing required field" in payload["error"]


def test_status_endpoint_reflects_the_created_attempt(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, job = gateway

    _, created = _post(
        instance.base_url,
        f"/v1/video-generations?project_id={job.id}",
        {
            "scene_number": 1,
            "prompt": "A lighthouse at dusk.",
            "prompt_version": "v1",
            "idempotency_key": "req-1",
        },
    )

    status, payload = _get(
        instance.base_url,
        f"/v1/video-generations/{created['attempt_id']}?project_id={job.id}",
    )

    assert status == 200
    assert payload["attempt_id"] == created["attempt_id"]
    assert payload["state"] == "generating"


def test_status_endpoint_rejects_an_unknown_attempt(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, job = gateway

    status, _ = _get(
        instance.base_url,
        f"/v1/video-generations/{uuid4()}?project_id={job.id}",
    )

    assert status == 404


def test_result_endpoint_reports_not_ready_before_completion(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, job = gateway

    _, created = _post(
        instance.base_url,
        f"/v1/video-generations?project_id={job.id}",
        {
            "scene_number": 1,
            "prompt": "A lighthouse at dusk.",
            "prompt_version": "v1",
            "idempotency_key": "req-1",
        },
    )

    status, payload = _get(
        instance.base_url,
        f"/v1/video-generations/{created['attempt_id']}/result?project_id={job.id}",
    )

    assert status == 200
    assert payload["ready"] is False


def test_retry_creates_a_new_attempt_through_the_same_gates(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, job_store, job = gateway

    _, created = _post(
        instance.base_url,
        f"/v1/video-generations?project_id={job.id}",
        {
            "scene_number": 1,
            "prompt": "A lighthouse at dusk.",
            "prompt_version": "v1",
            "idempotency_key": "req-1",
        },
    )

    # The first attempt is still in-flight (GENERATING) - retry must
    # go through the SAME canonical ledger guard as any other caller,
    # never a bare re-click, so it's correctly refused right now.
    status, payload = _post(
        instance.base_url,
        f"/v1/video-generations/{created['attempt_id']}/retry?project_id={job.id}",
        {},
    )

    assert status == 409


def test_provider_health_lists_configured_flow_accounts(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway

    status, payload = _get(instance.base_url, "/v1/provider-health")

    assert status == 200
    assert payload["profiles"][0]["profile_id"] == "flow.primary"
    assert payload["profiles"][0]["usable"] is True
    # Never a raw secret/browser-profile-reference leaked.
    assert "browser_profile_reference" not in payload["profiles"][0]
    assert "secret_reference" not in payload["profiles"][0]


def test_open_login_without_a_browser_worker_returns_service_unavailable(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway

    status, _ = _post(instance.base_url, "/v1/profiles/flow.primary/open-login", {})

    assert status == 503


def test_unknown_route_returns_404(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway

    status, _ = _get(instance.base_url, "/v1/not-a-real-route")

    assert status == 404


def test_start_is_idempotent(
    gateway: tuple[GoogleFlowLocalGateway, InMemoryJobStore, VideoJob],
) -> None:
    instance, _, _ = gateway
    original_url = instance.base_url

    instance.start()

    assert instance.base_url == original_url


def test_base_url_raises_before_start() -> None:
    job_store = InMemoryJobStore()
    registry = ProviderRegistry(profiles=[_flow_profile()])
    router = GoogleFlowAccountRouterService(registry)
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=FakeAdvancingProvider(), account_router=router
    )
    instance = GoogleFlowLocalGateway(
        job_store=job_store, orchestrator=orchestrator, provider_registry=registry
    )

    with pytest.raises(RuntimeError, match="not been started"):
        _ = instance.base_url
