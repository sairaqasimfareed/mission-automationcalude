from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.browser.flow_profile_paths import profile_directory
from src.desktop.job_store import JobStore
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationState,
    GoogleFlowReferenceAsset,
)
from src.models.provider_profile import ProviderCategory
from src.models.video_job import VideoJob
from src.services.google_flow_account_router_service import (
    NoEligibleGoogleFlowAccountError,
)
from src.services.google_flow_generation_orchestrator_service import (
    GoogleFlowGenerationOrchestratorService,
)
from src.services.registry.provider_registry import ProviderRegistry

# GF-14, section 21: "This is NOT a Google Flow API. It is an OPTIONAL
# LOCAL MISSION AUTOMATION REST GATEWAY into the SAME canonical Google
# Flow orchestration... HTTP handlers must NOT contain: Playwright
# selectors, browser navigation logic, Flow confirmation logic,
# routing algorithms, budget algorithms, QC algorithms, download
# implementation, duplicate generation ledger logic. They call the
# SAME canonical services used in-process."
#
# Every route handler in this file does exactly that and nothing
# more: parse the request, call GoogleFlowGenerationOrchestratorService
# (which itself already owns the ledger/routing/budget calls) or
# ProviderRegistry directly - the identical instances a caller would
# use in-process, e.g. from the desktop GUI - then serialize the
# result. GF-35's own "API/in-process parity" rule holds structurally,
# not by convention, because there is no second implementation to
# drift from the first.
#
# Localhost-first by construction: the server binds to 127.0.0.1
# unless a caller explicitly asks for a different host - "if future
# deployment exposes it beyond localhost: explicit configuration,
# authentication, appropriate transport security" (GF-34) is a
# decision left to that future caller, not defaulted here.
#
# project_id is not part of the documents' own literal path contract
# (which assumes a single implicit project); this codebase's own
# JobStore is keyed by VideoJob.id, and this gateway can serve more
# than one project, so every route takes project_id as an explicit
# query parameter rather than guessing which job an attempt_id
# belongs to.


class GoogleFlowGatewayError(RuntimeError):
    """A request-level error with an associated HTTP status code."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


_CREATE_PATH = re.compile(r"^/v1/video-generations$")
_STATUS_PATH = re.compile(r"^/v1/video-generations/(?P<attempt_id>[^/]+)$")
_RESULT_PATH = re.compile(r"^/v1/video-generations/(?P<attempt_id>[^/]+)/result$")
_RETRY_PATH = re.compile(r"^/v1/video-generations/(?P<attempt_id>[^/]+)/retry$")
_OPEN_LOGIN_PATH = re.compile(r"^/v1/profiles/(?P<profile_id>[^/]+)/open-login$")
_PROVIDER_HEALTH_PATH = re.compile(r"^/v1/provider-health$")


class GoogleFlowLocalGateway:
    """
    An optional, localhost-first HTTP facade over the same canonical
    Google Flow orchestrator/ledger/registry a desktop caller already
    uses in-process. Long-running work (an actual generation) happens
    inside `GoogleFlowGenerationOrchestratorService.submit_new_attempt()`,
    which already returns as soon as the attempt reaches GENERATING
    (GF-4) rather than blocking for full completion - so this gateway
    satisfies "do not hold the HTTP connection open for full
    generation" by construction, not by adding its own async worker
    queue on top.
    """

    def __init__(
        self,
        *,
        job_store: JobStore,
        orchestrator: GoogleFlowGenerationOrchestratorService,
        provider_registry: ProviderRegistry,
        browser_worker: FlowBrowserWorker | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        self._job_store = job_store
        self._orchestrator = orchestrator
        self._provider_registry = provider_registry
        self._browser_worker = browser_worker
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise RuntimeError("The gateway has not been started yet.")

        host, port = self._server.server_address[:2]

        return f"http://{host!s}:{port}"

    def start(self) -> None:
        if self._server is not None:
            return

        gateway = self
        handler_class = _make_handler_class(gateway)

        self._server = ThreadingHTTPServer((self._host, self._port), handler_class)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="google-flow-local-gateway",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return

        self._server.shutdown()
        self._server.server_close()

        if self._thread is not None:
            self._thread.join(timeout=5.0)

        self._server = None
        self._thread = None

    # --- route implementations, called by the handler below ---

    def handle_create(
        self, project_id: UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        job = self._get_job(project_id)

        try:
            reference_assets = [
                GoogleFlowReferenceAsset(**entry)
                for entry in payload.get("reference_assets", [])
            ]
            execution_settings = GoogleFlowExecutionSettings(
                **payload.get("execution_settings", {})
            )

            attempt = self._orchestrator.submit_new_attempt(
                job,
                scene_number=int(payload["scene_number"]),
                prompt=str(payload["prompt"]),
                prompt_version=str(payload["prompt_version"]),
                idempotency_key=str(payload["idempotency_key"]),
                execution_settings=execution_settings,
                reference_assets=reference_assets,
                negative_constraints=payload.get("negative_constraints"),
                locked_script_hash=payload.get("locked_script_hash"),
                estimated_cost_usd=float(payload.get("estimated_cost_usd", 0.0)),
            )
        except KeyError as error:
            raise GoogleFlowGatewayError(
                400, f"Missing required field: {error}"
            ) from error
        except NoEligibleGoogleFlowAccountError as error:
            raise GoogleFlowGatewayError(503, _sanitize(str(error))) from error
        except ValueError as error:
            raise GoogleFlowGatewayError(409, _sanitize(str(error))) from error

        self._job_store.add(job)

        return _attempt_status_payload(attempt)

    def handle_status(self, project_id: UUID, attempt_id: UUID) -> dict[str, Any]:
        job = self._get_job(project_id)
        attempt = self._get_attempt(job, attempt_id)

        return _attempt_status_payload(attempt)

    def handle_result(self, project_id: UUID, attempt_id: UUID) -> dict[str, Any]:
        job = self._get_job(project_id)
        attempt = self._get_attempt(job, attempt_id)

        if attempt.state != GoogleFlowGenerationState.READY:
            return {
                "attempt_id": str(attempt.id),
                "ready": False,
                "state": attempt.state.value,
            }

        return {
            "attempt_id": str(attempt.id),
            "ready": True,
            "state": attempt.state.value,
            "checksum": attempt.checksum,
            # The canonical media path, not any browser/session detail
            # - matches the same result an in-process caller would see
            # on job.flow_generation_attempts.
            "downloaded_file": attempt.downloaded_file,
        }

    def handle_retry(self, project_id: UUID, attempt_id: UUID) -> dict[str, Any]:
        """
        A deliberate retry: a brand-new attempt through the exact same
        canonical gates (routing/budget/idempotency), never a replay
        of an HTTP or browser click against the existing attempt -
        GF-33's own "It must NOT simply repeat an HTTP/browser click."
        """

        job = self._get_job(project_id)
        previous = self._get_attempt(job, attempt_id)

        try:
            attempt = self._orchestrator.submit_new_attempt(
                job,
                scene_number=previous.request.scene_number,
                prompt=previous.request.prompt,
                prompt_version=previous.request.prompt_version,
                idempotency_key=f"{previous.request.idempotency_key}-retry-{previous.attempt_number + 1}",
                execution_settings=previous.request.execution_settings,
                reference_assets=previous.request.reference_assets,
                negative_constraints=previous.request.negative_constraints,
                locked_script_hash=previous.request.locked_script_hash,
                estimated_cost_usd=previous.request.estimated_cost_usd,
            )
        except NoEligibleGoogleFlowAccountError as error:
            raise GoogleFlowGatewayError(503, _sanitize(str(error))) from error
        except ValueError as error:
            raise GoogleFlowGatewayError(409, _sanitize(str(error))) from error

        self._job_store.add(job)

        return _attempt_status_payload(attempt)

    def handle_open_login(self, profile_id: str) -> dict[str, Any]:
        """
        Delegates to the SAME safe browser-profile login capability
        the desktop Providers UI would use (GF-31/GF-32's own "do not
        duplicate browser startup logic inside the HTTP route") -
        never types a password, never returns any browser/session
        detail.
        """

        if self._browser_worker is None:
            raise GoogleFlowGatewayError(
                503, "No browser worker is configured for this gateway."
            )

        if not self._provider_registry.contains(profile_id):
            raise GoogleFlowGatewayError(404, "Unknown Google Flow profile.")

        profile = self._provider_registry.get(profile_id)

        if profile.category != ProviderCategory.EXTERNAL_UI_VIDEO:
            raise GoogleFlowGatewayError(
                400, "That profile is not a Google Flow account."
            )

        self._browser_worker.open_persistent_context(
            profile_id, profile_directory(profile_id), headless=False
        ).result(timeout=30.0)

        return {"profile_id": profile_id, "opened": True}

    def handle_provider_health(self) -> dict[str, Any]:
        profiles = self._provider_registry.list_by_category(
            ProviderCategory.EXTERNAL_UI_VIDEO
        )

        return {
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "display_name": profile.display_name,
                    "enabled": profile.enabled,
                    "health_status": profile.health_status.value,
                    "usable": profile.usable,
                    "priority": profile.priority,
                }
                for profile in profiles
            ]
        }

    def _get_job(self, project_id: UUID) -> VideoJob:
        job = self._job_store.get(project_id)

        if job is None:
            raise GoogleFlowGatewayError(404, "Unknown project_id.")

        return job

    @staticmethod
    def _get_attempt(job: VideoJob, attempt_id: UUID) -> GoogleFlowGenerationAttempt:
        for attempt in job.flow_generation_attempts:
            if attempt.id == attempt_id:
                return attempt

        raise GoogleFlowGatewayError(404, "Unknown attempt_id for this project.")


def _attempt_status_payload(attempt: GoogleFlowGenerationAttempt) -> dict[str, Any]:
    """
    Safe, sanitized status projection - never a raw browser/session
    secret, never a raw Playwright exception (GF-34's own
    "Never return: cookies, tokens, browser storage, passwords,
    session secrets, raw Playwright errors").
    """

    return {
        "attempt_id": str(attempt.id),
        "scene_number": attempt.request.scene_number,
        "attempt_number": attempt.attempt_number,
        "state": attempt.state.value,
        "profile_id": attempt.profile_id,
        "blocker": (
            {
                "code": attempt.failure.code.value,
                "message": attempt.failure.message,
                "recoverable": attempt.failure.recoverable,
            }
            if attempt.failure is not None
            else None
        ),
    }


def _sanitize(message: str) -> str:
    """
    A defensive last line, on top of every failure code above already
    being a clean, pre-written message with no raw exception text or
    secret interpolated into it.
    """

    return message


def _make_handler_class(
    gateway: GoogleFlowLocalGateway,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            # Suppress BaseHTTPRequestHandler's default stderr access
            # log - structured application events belong in this
            # codebase's own logger, not raw HTTP access lines.
            return

        def do_GET(self) -> None:  # noqa: N802
            self._dispatch(self._handle_get)

        def do_POST(self) -> None:  # noqa: N802
            self._dispatch(self._handle_post)

        def _dispatch(self, handler: Callable[[], dict[str, Any]]) -> None:
            try:
                body = handler()
                self._respond(200, body)
            except GoogleFlowGatewayError as error:
                self._respond(error.status_code, {"error": str(error)})
            except Exception:  # noqa: BLE001
                # Never leak a raw internal exception (GF-34) - a
                # generic 500 is the honest response to something this
                # route genuinely did not anticipate.
                self._respond(500, {"error": "Internal gateway error."})

        def _handle_get(self) -> dict[str, Any]:
            path, query = _split_path_and_query(self.path)

            # _RESULT_PATH is checked first even though _STATUS_PATH's
            # own anchoring already can't match a "/result" suffix
            # (`[^/]+` never spans the extra "/") - kept explicit
            # rather than relying on that non-overlap silently.
            if match := _RESULT_PATH.match(path):
                return gateway.handle_result(
                    _require_uuid(query, "project_id"),
                    _parse_uuid(match.group("attempt_id"), "attempt_id"),
                )

            if match := _STATUS_PATH.match(path):
                return gateway.handle_status(
                    _require_uuid(query, "project_id"),
                    _parse_uuid(match.group("attempt_id"), "attempt_id"),
                )

            if _PROVIDER_HEALTH_PATH.match(path):
                return gateway.handle_provider_health()

            raise GoogleFlowGatewayError(404, "Unknown route.")

        def _handle_post(self) -> dict[str, Any]:
            path, query = _split_path_and_query(self.path)

            if _CREATE_PATH.match(path):
                return gateway.handle_create(
                    _require_uuid(query, "project_id"), self._read_json_body()
                )

            if match := _RETRY_PATH.match(path):
                return gateway.handle_retry(
                    _require_uuid(query, "project_id"),
                    _parse_uuid(match.group("attempt_id"), "attempt_id"),
                )

            if match := _OPEN_LOGIN_PATH.match(path):
                return gateway.handle_open_login(match.group("profile_id"))

            raise GoogleFlowGatewayError(404, "Unknown route.")

        def _read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")

            if length == 0:
                return {}

            raw = self.rfile.read(length)

            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as error:
                raise GoogleFlowGatewayError(
                    400, "Request body is not valid JSON."
                ) from error

            if not isinstance(parsed, dict):
                raise GoogleFlowGatewayError(400, "Request body must be a JSON object.")

            return parsed

        def _respond(self, status_code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload).encode("utf-8")

            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def _split_path_and_query(raw_path: str) -> tuple[str, dict[str, str]]:
    from urllib.parse import parse_qs, urlsplit

    split = urlsplit(raw_path)
    query = {key: values[0] for key, values in parse_qs(split.query).items()}

    return split.path, query


def _require_uuid(query: dict[str, str], key: str) -> UUID:
    if key not in query:
        raise GoogleFlowGatewayError(400, f"Missing required query parameter: {key}")

    return _parse_uuid(query[key], key)


def _parse_uuid(raw: str, field_name: str) -> UUID:
    try:
        return UUID(raw)
    except ValueError as error:
        raise GoogleFlowGatewayError(400, f"Invalid {field_name}.") from error
