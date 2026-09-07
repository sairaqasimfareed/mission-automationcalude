from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from src.api.google_flow_gateway import GoogleFlowLocalGateway
from src.browser.flow_profile_lock import FlowProfileLock
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

# Google Flow External UI Automation, GF-15: "Never persist/log/export:
# Google passwords, MFA values, CAPTCHA answers, cookies, tokens,
# browser storage. Persistent browser profiles remain local and
# outside project exports. No CAPTCHA/MFA bypass. No private
# unofficial Google API dependency. Sanitize diagnostics."
#
# These tests turn a one-time manual grep audit into a durable,
# automated regression guard - a future change that accidentally
# introduces logging, a new persisted field, or a leaked key is caught
# here rather than relying on nobody ever forgetting to re-check.

_GOOGLE_FLOW_SOURCE_FILES = [
    Path("src/models/google_flow_generation.py"),
    Path("src/providers/external_ui_generation_provider.py"),
    Path("src/providers/google_flow/adapter.py"),
    Path("src/providers/google_flow/real_adapter.py"),
    Path("src/providers/google_flow/locators.py"),
    Path("src/browser/flow_profile_paths.py"),
    Path("src/browser/flow_profile_lock.py"),
    Path("src/browser/flow_browser_worker.py"),
    Path("src/browser/manual_signin_bootstrap.py"),
    Path("src/desktop/views/google_flow_provider_panel_view.py"),
    Path("src/services/google_flow_generation_ledger_service.py"),
    Path("src/services/google_flow_account_router_service.py"),
    Path("src/services/google_flow_generation_orchestrator_service.py"),
    Path("src/api/google_flow_gateway.py"),
]

_FORBIDDEN_JSON_KEYS = {
    "password",
    "cookie",
    "cookies",
    "token",
    "tokens",
    "session_secret",
    "auth_token",
    "browser_profile_reference",
    "secret_reference",
}


def test_every_google_flow_source_file_exists() -> None:
    """
    A guard against the file list above silently going stale (e.g. a
    file renamed) and the source-scanning tests below quietly scanning
    nothing.
    """

    for relative_path in _GOOGLE_FLOW_SOURCE_FILES:
        assert relative_path.is_file(), f"Expected file not found: {relative_path}"


def test_no_google_flow_source_file_logs_or_prints() -> None:
    """
    Structured application events belong in this codebase's own
    logger, never a bare print()/logging call that could accidentally
    interpolate page content, a Playwright exception, or profile
    metadata into a log stream this module doesn't control.
    """

    pattern = re.compile(r"\bprint\s*\(|\blogger\.|(?<!\.)\blogging\.")

    for relative_path in _GOOGLE_FLOW_SOURCE_FILES:
        content = relative_path.read_text(encoding="utf-8")

        assert not pattern.search(content), (
            f"{relative_path} contains a print()/logger/logging call - "
            "review it for accidental secret/session leakage."
        )


def test_no_google_flow_source_file_mentions_credentials() -> None:
    """
    Every real match here must be a comment/docstring explicitly
    disclaiming credential handling (GF-15's own security boundary),
    never actual code that stores, transmits, or logs one. A line
    containing one of these words with no surrounding "never"/"no"/
    "not"/"nothing" language is flagged for manual review rather than
    silently passed.
    """

    suspicious_pattern = re.compile(r"\b(password|cookie|mfa|captcha)\b", re.IGNORECASE)
    disclaiming_pattern = re.compile(
        r"\b(never|no|not|nothing|none|without)\b", re.IGNORECASE
    )
    # A comment/docstring disclaiming credential handling routinely
    # spans several physical lines (e.g. a wrapped sentence) - a
    # sliding window, not an exact same-line match, is what actually
    # reflects "is this line part of a disclaiming passage."
    window = 3

    for relative_path in _GOOGLE_FLOW_SOURCE_FILES:
        lines = relative_path.read_text(encoding="utf-8").splitlines()

        for line_number, line in enumerate(lines, start=1):
            if not suspicious_pattern.search(line):
                continue

            window_start = max(0, line_number - 1 - window)
            window_end = min(len(lines), line_number + window)
            surrounding = "\n".join(lines[window_start:window_end])

            if not disclaiming_pattern.search(surrounding):
                raise AssertionError(
                    f"{relative_path}:{line_number} mentions a credential-"
                    f"related term with no disclaiming language nearby: "
                    f"{line.strip()!r}"
                )


def test_provider_profile_credential_fields_are_references_not_secrets() -> None:
    """
    ProviderProfile.secret_reference/browser_profile_reference are
    named, and documented, as references (e.g. a keychain lookup key
    or a local directory path) - never a field meant to hold an actual
    password/token value.
    """

    fields = ProviderProfile.model_fields

    assert "secret_reference" in fields
    assert "browser_profile_reference" in fields
    assert "password" not in fields
    assert "secret" not in fields
    assert "token" not in fields
    assert "cookie" not in fields


def test_flow_profile_lock_file_contains_only_safe_fields(tmp_path: Path) -> None:
    profile_dir = tmp_path / "flow.primary"
    lock = FlowProfileLock(profile_dir)
    lock.acquire()

    payload = json.loads(lock.lock_path.read_text(encoding="utf-8"))

    assert set(payload.keys()) == {"owner_pid", "acquired_at"}

    lock.release()


# --- Gateway response sweep ---


class _FakeAdvancingProvider(ExternalUIGenerationProvider):
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


def _find_forbidden_keys(payload: object, *, path: str = "$") -> list[str]:
    found: list[str] = []

    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in _FORBIDDEN_JSON_KEYS:
                found.append(f"{path}.{key}")
            found.extend(_find_forbidden_keys(value, path=f"{path}.{key}"))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found.extend(_find_forbidden_keys(item, path=f"{path}[{index}]"))

    return found


def test_gateway_responses_never_contain_forbidden_keys() -> None:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    job_store = InMemoryJobStore()
    job = VideoJob(
        project_name="Test Project",
        channel_name="Test Channel",
        niche="testing",
        topic="A test topic",
    )
    job_store.add(job)

    registry = ProviderRegistry(
        profiles=[
            ProviderProfile(
                profile_id="flow.primary",
                display_name="flow.primary",
                provider_name="Google Flow",
                category=ProviderCategory.EXTERNAL_UI_VIDEO,
                enabled=True,
                health_status=ProviderHealthStatus.HEALTHY,
                browser_profile_reference="flow_profiles/flow.primary",
            )
        ]
    )
    router = GoogleFlowAccountRouterService(registry)
    orchestrator = GoogleFlowGenerationOrchestratorService(
        provider=_FakeAdvancingProvider(),
        account_router=router,
    )
    gateway = GoogleFlowLocalGateway(
        job_store=job_store, orchestrator=orchestrator, provider_registry=registry
    )
    gateway.start()

    def _request(
        method: str, path: str, body: dict[str, object] | None = None
    ) -> dict[str, object]:
        data = json.dumps(body or {}).encode("utf-8") if method == "POST" else None
        request = Request(  # noqa: S310
            f"{gateway.base_url}{path}", data=data, method=method
        )
        try:
            with urlopen(request, timeout=10) as response:  # noqa: S310
                result: dict[str, object] = json.loads(response.read())
                return result
        except HTTPError as error:
            result = json.loads(error.read())
            return result

    try:
        created = _request(
            "POST",
            f"/v1/video-generations?project_id={job.id}",
            {
                "scene_number": 1,
                "prompt": "A lighthouse at dusk.",
                "prompt_version": "v1",
                "idempotency_key": "req-1",
            },
        )
        attempt_id = created["attempt_id"]

        responses = [
            created,
            _request("GET", f"/v1/video-generations/{attempt_id}?project_id={job.id}"),
            _request(
                "GET",
                f"/v1/video-generations/{attempt_id}/result?project_id={job.id}",
            ),
            _request("GET", "/v1/provider-health"),
            _request("POST", "/v1/profiles/flow.primary/open-login"),
        ]

        for response in responses:
            leaked = _find_forbidden_keys(response)
            assert leaked == [], f"Forbidden key(s) found in response: {leaked}"
    finally:
        gateway.stop()


@pytest.mark.parametrize(
    "forbidden_key",
    sorted(_FORBIDDEN_JSON_KEYS - {"browser_profile_reference", "secret_reference"}),
)
def test_forbidden_key_detector_actually_detects(forbidden_key: str) -> None:
    """A sanity check on the detector itself - proving a genuinely
    forbidden key IS caught, so the sweep above isn't silently
    checking nothing."""

    assert _find_forbidden_keys({forbidden_key: "x"}) == [f"$.{forbidden_key}"]
