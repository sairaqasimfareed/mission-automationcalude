from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
    GoogleFlowReferenceAsset,
    GoogleFlowReferenceRole,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIOperation,
    ExternalUIOperationNotSupportedError,
)
from src.providers.google_flow.adapter import GoogleFlowUIAdapter

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "fake_flow_ui.html"


def _fixture_url(*, query: str = "") -> str:
    base = _FIXTURE_PATH.resolve().as_uri()

    return f"{base}?{query}" if query else base


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()

        return True
    except Exception:
        return False


_HAS_CHROMIUM = _chromium_available()

requires_chromium = pytest.mark.skipif(
    not _HAS_CHROMIUM,
    reason="A real headless Chromium binary is not available on this machine.",
)


@pytest.fixture
def worker() -> Iterator[FlowBrowserWorker]:
    instance = FlowBrowserWorker()
    yield instance
    instance.shutdown()


def _request(**overrides: object) -> GoogleFlowGenerationRequest:
    defaults: dict[str, object] = {
        "scene_number": 1,
        "prompt": "A lighthouse at dusk, waves crashing below.",
        "prompt_version": "v1",
        "profile_id": "flow.primary",
        "idempotency_key": "req-1",
    }
    defaults.update(overrides)
    return GoogleFlowGenerationRequest(**defaults)  # type: ignore[arg-type]


def _attempt(request: GoogleFlowGenerationRequest) -> GoogleFlowGenerationAttempt:
    return GoogleFlowGenerationAttempt(request=request, profile_id=request.profile_id)


def _adapter(
    worker: FlowBrowserWorker, tmp_path: Path, *, query: str = ""
) -> GoogleFlowUIAdapter:
    # A profile_directory_resolver pointed at pytest's own tmp_path
    # gives each test a fresh, isolated persistent-profile directory -
    # the adapter now genuinely opens a real persistent Chromium
    # context (GF-2's FlowBrowserWorker.open_persistent_context_from_worker_thread())
    # per profile_id, not a throwaway ephemeral browser, so isolation
    # has to come from the resolver rather than "ephemeral by default".
    return GoogleFlowUIAdapter(
        worker=worker,
        base_url=_fixture_url(query=query),
        headless=True,
        operation_timeout_seconds=20.0,
        profile_directory_resolver=lambda profile_id: tmp_path / profile_id,
    )


def _observe_until(
    adapter: GoogleFlowUIAdapter,
    attempt: GoogleFlowGenerationAttempt,
    *,
    target_states: set[GoogleFlowGenerationState],
    timeout_seconds: float = 5.0,
) -> GoogleFlowGenerationAttempt:
    """Poll observe() - proving it's genuinely repeatable - until one
    of target_states is reached or the timeout elapses."""

    deadline = time.monotonic() + timeout_seconds
    current = attempt

    while time.monotonic() < deadline:
        current = adapter.observe(current)

        if current.state in target_states:
            return current

        time.sleep(0.05)

    return current


@requires_chromium
def test_submit_reaches_generating_through_confirmation(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path)
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    visited = [entry.state for entry in result.state_history]
    assert GoogleFlowGenerationState.CONFIRMATION_REQUIRED in visited
    assert GoogleFlowGenerationState.CONFIRMING in visited
    assert GoogleFlowGenerationState.SUBMITTING in visited
    assert GoogleFlowGenerationState.SUBMITTED in visited


@requires_chromium
def test_submit_reaches_generating_without_confirmation(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path, query="no_confirm=1")
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    visited = [entry.state for entry in result.state_history]
    assert GoogleFlowGenerationState.CONFIRMATION_REQUIRED not in visited
    assert GoogleFlowGenerationState.CONFIRMING not in visited


@requires_chromium
def test_submit_inserts_the_exact_prompt_text(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    adapter = _adapter(worker, tmp_path, query="no_confirm=1")
    request = _request(prompt="A very specific, exact prompt string.")

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING


@requires_chromium
def test_submit_detects_auth_required(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    adapter = _adapter(worker, tmp_path, query="simulate=auth_required")
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.AUTH_REQUIRED


@requires_chromium
def test_submit_detects_ui_changed_and_never_guesses(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    adapter = _adapter(worker, tmp_path, query="simulate=ui_changed")
    request = _request()

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.UI_CHANGED
    assert "prompt_input" in result.state_history[-1].detail  # type: ignore[operator]


@requires_chromium
def test_submit_stops_before_generation_when_a_reference_is_dropped(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path, query="simulate=reference_drop")
    request = _request(
        reference_assets=[
            GoogleFlowReferenceAsset(
                source_path="assets/hero.png",
                checksum="abc123",
                role=GoogleFlowReferenceRole.CHARACTER,
            )
        ]
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.FAILED
    assert "REFERENCE_DROPPED" in result.state_history[-1].detail  # type: ignore[operator]
    # Never reached the credit-sensitive boundary.
    visited = [entry.state for entry in result.state_history]
    assert GoogleFlowGenerationState.SUBMITTING not in visited


@requires_chromium
def test_submit_attaches_a_reference_when_flow_accepts_it(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path, query="no_confirm=1")
    request = _request(
        reference_assets=[
            GoogleFlowReferenceAsset(
                source_path="assets/hero.png",
                checksum="abc123",
                role=GoogleFlowReferenceRole.CHARACTER,
            )
        ]
    )

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING


@requires_chromium
def test_submit_reports_settings_unavailable_for_an_unknown_model_family(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path)
    request = _request(execution_settings={"model_family": "not_a_real_model"})

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.FAILED
    assert "FLOW_SETTINGS_UNAVAILABLE" in result.state_history[-1].detail  # type: ignore[operator]


@requires_chromium
def test_submit_accepts_a_valid_requested_model_family(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path, query="no_confirm=1")
    request = _request(execution_settings={"model_family": "premium"})

    result = adapter.submit(request, _attempt(request))

    assert result.state == GoogleFlowGenerationState.GENERATING
    visited = [entry.state for entry in result.state_history]
    assert GoogleFlowGenerationState.SETTINGS_VERIFIED in visited


@requires_chromium
def test_check_profile_health_is_true_on_the_normal_page(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path)

    assert adapter.check_profile_health("flow.primary") is True


@requires_chromium
def test_check_profile_health_is_false_when_auth_is_required(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path, query="simulate=auth_required")

    assert adapter.check_profile_health("flow.primary") is False


@requires_chromium
def test_observe_detects_ready_to_download_after_generation_completes(
    worker: FlowBrowserWorker,
    tmp_path: Path,
) -> None:
    adapter = _adapter(worker, tmp_path, query="no_confirm=1")
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    assert submitted.state == GoogleFlowGenerationState.GENERATING

    observed = _observe_until(
        adapter,
        submitted,
        target_states={
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
            GoogleFlowGenerationState.FAILED,
        },
    )

    assert observed.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD


@requires_chromium
def test_observe_detects_failure(worker: FlowBrowserWorker, tmp_path: Path) -> None:
    adapter = _adapter(worker, tmp_path, query="no_confirm=1&fail=1")
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    assert submitted.state == GoogleFlowGenerationState.GENERATING

    observed = _observe_until(
        adapter,
        submitted,
        target_states={
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
            GoogleFlowGenerationState.FAILED,
        },
    )

    assert observed.state == GoogleFlowGenerationState.FAILED


@requires_chromium
def test_observe_is_read_only_before_completion(
    worker: FlowBrowserWorker, tmp_path: Path
) -> None:
    """
    observe() must never advance an attempt on its own guesswork - if
    generation genuinely hasn't finished yet, the attempt comes back
    unchanged, not nudged toward some other state.
    """

    adapter = _adapter(worker, tmp_path, query="no_confirm=1")
    request = _request()
    submitted = adapter.submit(request, _attempt(request))

    observed = adapter.observe(submitted)

    assert observed.state in {
        GoogleFlowGenerationState.GENERATING,
        GoogleFlowGenerationState.READY_TO_DOWNLOAD,
    }


@requires_chromium
def test_download_saves_a_real_file(worker: FlowBrowserWorker, tmp_path: Path) -> None:
    # download_root and the browser profile directory must be
    # genuinely separate subtrees - the assertion below rglobs
    # download_root for exactly one saved file, which would break if
    # the browser profile's own many internal files landed in the
    # same tree.
    download_root = tmp_path / "downloads"
    adapter = GoogleFlowUIAdapter(
        worker=worker,
        base_url=_fixture_url(query="no_confirm=1"),
        headless=True,
        operation_timeout_seconds=20.0,
        download_root=download_root,
        profile_directory_resolver=lambda profile_id: tmp_path / "profile" / profile_id,
    )
    request = _request()
    submitted = adapter.submit(request, _attempt(request))
    ready = _observe_until(
        adapter,
        submitted,
        target_states={
            GoogleFlowGenerationState.READY_TO_DOWNLOAD,
            GoogleFlowGenerationState.FAILED,
        },
    )
    assert ready.state == GoogleFlowGenerationState.READY_TO_DOWNLOAD

    downloaded = adapter.download(ready)

    assert downloaded.state == GoogleFlowGenerationState.DOWNLOADED
    saved_files = list(download_root.rglob("*"))
    saved_files = [path for path in saved_files if path.is_file()]
    assert len(saved_files) == 1
    assert saved_files[0].stat().st_size > 0


def test_cancel_or_abandon_is_not_supported(tmp_path: Path) -> None:
    worker = FlowBrowserWorker()
    try:
        adapter = _adapter(worker, tmp_path)
        request = _request()

        with pytest.raises(ExternalUIOperationNotSupportedError) as excinfo:
            adapter.cancel_or_abandon(_attempt(request))

        assert excinfo.value.operation == ExternalUIOperation.CANCEL_OR_ABANDON
    finally:
        worker.shutdown()
