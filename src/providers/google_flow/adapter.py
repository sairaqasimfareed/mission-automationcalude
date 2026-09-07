from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.models.google_flow_generation import (
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.providers.google_flow.locators import GoogleFlowLocators

# GF-4's own default local storage convention (matches
# DEFAULT_MANUAL_UPLOAD_STORAGE_ROOT/DEFAULT_STOCK_STORAGE_ROOT and
# GF-2's DEFAULT_FLOW_PROFILES_ROOT).
DEFAULT_FLOW_DOWNLOAD_ROOT = Path("data/google_flow_downloads")

_CRITICAL_PREFLIGHT_LOCATOR_ATTRS = (
    "prompt_input",
    "model_family_select",
    "generate_button",
    "reference_drop_zone",
    "analysis_panel",
    "generation_panel",
    "result_panel",
)


class GoogleFlowUIChangedError(RuntimeError):
    """
    Raised internally when a critical Flow control cannot be located
    at all. Never escapes GoogleFlowUIAdapter's own public methods -
    they catch it and return an attempt transitioned to UI_CHANGED
    instead, per GF-4's "ambiguous critical control: UI_CHANGED, STOP.
    Never guess."
    """


class GoogleFlowUIAdapter(ExternalUIGenerationProvider):
    """
    The concrete Google Flow adapter.

    IMPORTANT: this adapter has only ever been exercised against
    tests/fixtures/fake_flow_ui.html (GF-16's local fake-Flow test
    harness), driven through GoogleFlowLocators' own default
    selectors - not against the real Google Flow product, which
    nobody building this has inspected. What is genuinely proven here
    is the adapter's *logic*: preflight before any credit-sensitive
    action, settings verification (never silent substitution), exact
    prompt insertion, reference-attachment verification, the analyze
    -> confirmation-required-or-optional -> submit state sequence, the
    credit-sensitive SUBMITTING/SUBMITTED boundary (persisted via
    with_transition each step), UI_CHANGED/AUTH_REQUIRED detection,
    and a basic observe/download cycle. Before any real-account use,
    GoogleFlowLocators must be re-pointed at Google Flow's real,
    verified selectors (GF-17's own real-account certification).

    Only ever mutates its own `_pages` dict from inside the worker
    thread (every public method here runs its actual work through
    `self._worker.submit(...)`), matching FlowBrowserWorker's own
    threading contract.
    """

    def __init__(
        self,
        *,
        worker: FlowBrowserWorker,
        base_url: str,
        locators: GoogleFlowLocators | None = None,
        headless: bool = True,
        operation_timeout_seconds: float = 30.0,
        download_root: Path = DEFAULT_FLOW_DOWNLOAD_ROOT,
    ) -> None:
        self._worker = worker
        self._base_url = base_url
        self._locators = locators or GoogleFlowLocators()
        self._headless = headless
        self._operation_timeout_seconds = operation_timeout_seconds
        self._download_root = download_root

        self._pages: dict[str, Page] = {}

    @property
    def _action_timeout_ms(self) -> float:
        """
        Explicit per-action timeout, in milliseconds, passed to every
        individual Playwright call.

        Without an explicit timeout, Playwright falls back to its own
        default (also 30s) for every actionability wait (click/fill/
        select_option all block until the target element is visible,
        stable, and receives events) - which can collide almost
        exactly with an outer `Future.result(timeout=...)` deadline
        and produce a bare, undiagnostic concurrent.futures.TimeoutError
        instead of a proper, catchable Playwright error. Kept shorter
        than every outer future timeout in this file (all of which
        multiply operation_timeout_seconds) so a genuine "can't find
        or interact with this control" condition fails fast and is
        actually caught, rather than racing an unrelated outer
        deadline.
        """

        return self._operation_timeout_seconds * 1000

    @property
    def provider_name(self) -> str:
        return "Google Flow"

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
        def _run() -> bool:
            page = self._get_or_open_page(profile_id)
            page.goto(self._base_url, timeout=self._action_timeout_ms)

            # Playwright's is_visible() on a locator matching zero
            # elements simply returns False - no error - so this
            # reads correctly whether the banner element exists at
            # all or exists but is hidden.
            return not page.locator(self._locators.auth_required_banner).is_visible()

        # A launch-a-fresh-browser-then-navigate path (the common case
        # for a brand new profile's first health check) needs more
        # headroom than a single Playwright action - matches submit()'s
        # own 3x multiplier rather than the bare operation_timeout_seconds
        # a first version of this method used, which under real system
        # load could fire before browser launch + navigation finished.
        return self._worker.submit(_run).result(
            timeout=self._operation_timeout_seconds * 3
        )

    def submit(
        self,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.SUBMIT)

        def _run() -> GoogleFlowGenerationAttempt:
            page = self._get_or_open_page(attempt.profile_id)
            page.goto(self._base_url, timeout=self._action_timeout_ms)

            if page.locator(self._locators.auth_required_banner).is_visible():
                return attempt.with_transition(
                    GoogleFlowGenerationState.AUTH_REQUIRED,
                    detail="Flow reported an expired or missing authentication session.",
                )

            try:
                self._preflight(page)
            except GoogleFlowUIChangedError as error:
                return attempt.with_transition(
                    GoogleFlowGenerationState.UI_CHANGED,
                    detail=str(error),
                )

            return self._drive_submission(page, request, attempt)

        return self._worker.submit(_run).result(
            timeout=self._operation_timeout_seconds * 3
        )

    def observe(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.OBSERVE)

        def _run() -> GoogleFlowGenerationAttempt:
            page = self._pages.get(attempt.profile_id)

            if page is None:
                return attempt.with_transition(
                    GoogleFlowGenerationState.UI_CHANGED,
                    detail=(
                        "No open Flow page exists for this attempt's profile - "
                        "cannot observe."
                    ),
                )

            if attempt.state not in {
                GoogleFlowGenerationState.SUBMITTED,
                GoogleFlowGenerationState.GENERATING,
            }:
                # Nothing new to report from a state observation
                # doesn't apply to - read-only, so returning the
                # attempt unchanged is correct, not an error.
                return attempt

            result_panel = page.locator(self._locators.result_panel)

            if not result_panel.is_visible():
                return attempt

            status_text = (
                page.locator(self._locators.result_status).text_content() or ""
            ).strip()

            if page.locator(self._locators.download_link).is_visible():
                return attempt.with_transition(
                    GoogleFlowGenerationState.READY_TO_DOWNLOAD,
                    detail=f"Flow reports: {status_text}",
                )

            return attempt.with_transition(
                GoogleFlowGenerationState.FAILED,
                detail=f"Flow reports: {status_text}",
            )

        return self._worker.submit(_run).result(timeout=self._operation_timeout_seconds)

    def download(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        self.ensure_supported(ExternalUIOperation.DOWNLOAD)

        def _run() -> GoogleFlowGenerationAttempt:
            page = self._pages.get(attempt.profile_id)

            if page is None:
                raise RuntimeError(
                    "No open Flow page exists for this attempt's profile."
                )

            destination_dir = self._download_root / attempt.profile_id / str(attempt.id)
            destination_dir.mkdir(parents=True, exist_ok=True)

            with page.expect_download(
                timeout=self._operation_timeout_seconds * 1000
            ) as download_info:
                page.locator(self._locators.download_link).click(
                    timeout=self._action_timeout_ms
                )

            download = download_info.value
            destination = destination_dir / download.suggested_filename
            download.save_as(str(destination))

            return attempt.with_transition(
                GoogleFlowGenerationState.DOWNLOADED,
                detail=f"Saved to {destination}.",
            )

        return self._worker.submit(_run).result(
            timeout=self._operation_timeout_seconds * 2
        )

    def cancel_or_abandon(
        self,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        # Not declared in supported_operations - this always raises
        # ExternalUIOperationNotSupportedError. Google Flow gives this
        # adapter no verified way to actually stop an in-flight,
        # already-submitted generation; claiming to cancel it would be
        # dishonest rather than merely unimplemented.
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)

        raise AssertionError("unreachable - ensure_supported always raises first")

    def _drive_submission(
        self,
        page: Page,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        current = attempt

        settings = request.execution_settings

        if settings.model_family:
            try:
                page.locator(self._locators.model_family_select).select_option(
                    settings.model_family,
                    timeout=self._action_timeout_ms,
                )
            except PlaywrightError:
                return current.with_transition(
                    GoogleFlowGenerationState.FAILED,
                    detail=(
                        "FLOW_SETTINGS_UNAVAILABLE: requested model_family "
                        f"'{settings.model_family}' is not an option Flow "
                        "currently offers."
                    ),
                )

            selected = page.locator(self._locators.model_family_select).input_value(
                timeout=self._action_timeout_ms
            )

            if selected != settings.model_family:
                return current.with_transition(
                    GoogleFlowGenerationState.FAILED,
                    detail=(
                        "FLOW_SETTINGS_MISMATCH: requested "
                        f"'{settings.model_family}', Flow shows '{selected}'."
                    ),
                )

        current = current.with_transition(
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            detail="Visible Flow settings verified against the requested settings.",
        )

        page.locator(self._locators.prompt_input).fill(
            request.prompt, timeout=self._action_timeout_ms
        )
        current = current.with_transition(
            GoogleFlowGenerationState.PROMPT_PREPARED,
            detail="Exact persisted prompt inserted - never rewritten.",
        )

        if request.reference_assets:
            page.locator(self._locators.reference_drop_zone).click(
                timeout=self._action_timeout_ms
            )

            if not page.locator(self._locators.reference_attached_label).is_visible():
                return current.with_transition(
                    GoogleFlowGenerationState.FAILED,
                    detail=(
                        "REFERENCE_DROPPED: a required reference did not "
                        "visibly attach - stopped before generation."
                    ),
                )

        page.locator(self._locators.generate_button).click(
            timeout=self._action_timeout_ms
        )
        current = current.with_transition(
            GoogleFlowGenerationState.ANALYZING,
            detail="Generate clicked; awaiting Flow's analysis/confirmation state.",
        )

        confirmation_seen = self._wait_for_analysis_outcome(page)

        if confirmation_seen:
            current = current.with_transition(
                GoogleFlowGenerationState.CONFIRMATION_REQUIRED,
                detail="Flow is asking for explicit confirmation before generation.",
            )
            current = current.with_transition(
                GoogleFlowGenerationState.CONFIRMING,
                detail="Confirming this exact, already-resolved request.",
            )
            page.locator(self._locators.confirm_button).click(
                timeout=self._action_timeout_ms
            )

        # The credit-sensitive boundary (GF-1's own rule): persisted
        # BEFORE the operation that may spend provider credit.
        current = current.with_transition(
            GoogleFlowGenerationState.SUBMITTING,
            detail="Crossing the credit-sensitive submission boundary.",
        )

        try:
            page.locator(self._locators.generation_panel).wait_for(
                state="visible",
                timeout=self._action_timeout_ms,
            )
        except PlaywrightTimeoutError:
            return current.with_transition(
                GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
                detail=(
                    "No positive evidence generation actually started after "
                    "the submit boundary - never blindly retried."
                ),
            )

        current = current.with_transition(
            GoogleFlowGenerationState.SUBMITTED,
            detail="Positive evidence generation started.",
        )

        return current.with_transition(
            GoogleFlowGenerationState.GENERATING,
            detail="Generation is in progress.",
        )

    def _wait_for_analysis_outcome(self, page: Page) -> bool:
        """
        Wait for either the confirmation control to appear
        (confirmation-required path) or generation to start directly
        (confirmation-optional path, GF-20). Returns whether
        confirmation was seen.
        """

        confirm_button = page.locator(self._locators.confirm_button)
        generation_panel = page.locator(self._locators.generation_panel)

        deadline = time.monotonic() + self._operation_timeout_seconds

        while time.monotonic() < deadline:
            if confirm_button.is_visible():
                return True

            if generation_panel.is_visible():
                return False

            page.wait_for_timeout(50)

        return False

    def _preflight(self, page: Page) -> None:
        """
        GF-4's own rule: verify every critical control is present
        before touching anything credit-sensitive. Presence
        (`count() > 0`), not visibility - several of these are
        legitimately hidden until a later step of the flow.
        """

        missing = [
            attr
            for attr in _CRITICAL_PREFLIGHT_LOCATOR_ATTRS
            if page.locator(getattr(self._locators, attr)).count() == 0
        ]

        if missing:
            raise GoogleFlowUIChangedError(
                "UI_CHANGED: the following expected Flow controls could not "
                f"be found: {', '.join(missing)}."
            )

    def _get_or_open_page(self, profile_id: str) -> Page:
        """
        Must only ever be called from inside the worker thread (every
        caller here is itself a callable already running via
        self._worker.submit(...)).
        """

        existing = self._pages.get(profile_id)

        if existing is not None:
            return existing

        # A minimal, ephemeral (non-persistent) browser for now -
        # GF-2's persistent-profile FlowBrowserWorker.open_persistent_context()
        # is the real production path; wiring this adapter to use a
        # profile's real persistent context, not a throwaway one, is
        # a real, disclosed gap left for the phase that wires this
        # adapter into the actual account router/ledger orchestrator.
        # launch_ephemeral_browser() is called directly, not through
        # self._worker.submit() again - this method is already running
        # on the worker thread, and a second submit() from inside a
        # still-running submitted callable would deadlock the single-
        # worker pool.
        browser = self._worker.launch_ephemeral_browser(headless=self._headless)
        page = browser.new_page()
        self._pages[profile_id] = page

        return page
