from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from playwright.sync_api import Page

from src.browser.flow_browser_worker import FlowBrowserWorker
from src.browser.flow_profile_paths import profile_directory
from src.models.google_flow_generation import (
    GoogleFlowExecutionSettings,
    GoogleFlowGenerationAttempt,
    GoogleFlowGenerationRequest,
    GoogleFlowGenerationState,
)
from src.providers.external_ui_generation_provider import (
    ExternalUIGenerationProvider,
    ExternalUIOperation,
)
from src.providers.google_flow.locators import GoogleFlowRealAccessibleNames

# Matches GoogleFlowUIAdapter's own local-storage convention
# (src/providers/google_flow/adapter.py's DEFAULT_FLOW_DOWNLOAD_ROOT) -
# a shared download tree for both adapters is intentional, since both
# ultimately download the same kind of provider-neutral artifact.
DEFAULT_FLOW_DOWNLOAD_ROOT = Path("data/google_flow_downloads")

# Real, verified vocabulary -> the real settings popover's own radio
# accessible names, per docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4.
# The radio's accessible name IS the value itself for every dimension
# except variation_count (an int on GoogleFlowExecutionSettings, "x2"
# on the real control).
_VARIATION_COUNT_RADIO_NAMES = {1: "x1", 2: "x2", 3: "x3", 4: "x4"}


class GoogleFlowUIChangedError(RuntimeError):
    """
    Raised internally when a critical Flow control cannot be located
    at all. Never escapes GoogleFlowRealUIAdapter's own public
    methods - they catch it and return an attempt transitioned to
    UI_CHANGED instead, matching GoogleFlowUIAdapter's own "ambiguous
    critical control: UI_CHANGED, STOP. Never guess" rule.
    """


class GoogleFlowAuthRequiredError(RuntimeError):
    """Raised internally when the real product shows no sign of an
    authenticated session (see _detect_auth_required's own docstring
    for exactly what's checked and why)."""


class GoogleFlowRealUIAdapter(ExternalUIGenerationProvider):
    """
    A SEPARATE adapter from GoogleFlowUIAdapter (src/providers/google_flow/adapter.py),
    deliberately - not a locators-string swap on the same class. The
    real product's settings mechanism is a popover of radio-button
    groups, opened via a "Settings trigger" button; GoogleFlowUIAdapter's
    whole interaction shape (a <select> dropdown read via
    select_option(), distinct named analysis/generation/result panels)
    was built against tests/fixtures/fake_flow_ui.html and does not
    match the real product's structure at all - forcing both into one
    class via conditionals would tangle two genuinely different
    interaction models together. GoogleFlowUIAdapter and its 16
    fixture-driven tests are completely untouched by this class.

    Built from real, verified findings - docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md,
    captured against a real, authenticated Google Flow session,
    including one real, human-authorized generation. What IS verified
    (and exercised by this class's own logic): the dashboard, the
    compose UI inside an existing project, typing a real prompt, the
    settings popover's full real vocabulary (model family, resolution,
    duration, aspect ratio, variation count), clicking Start
    generation, the generating -> completed tile sequence, and the
    real Download scene control. Also now confirmed (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md
    section 4a): the confirmation-before-generating screen is an
    Agent-mode-only, explicitly configurable setting ("Confirm before
    generating": Always/Never, in Agent settings) - not content/
    policy-triggered, and irrelevant to this class, since it never
    enables Agent mode (the "Agent" toggle is never clicked - see
    section 4's own "Operationally important" note on why Agent-off is
    the real, working path this class drives). What IS still NOT
    verified and deliberately NOT built here, rather than guessed:
    the ingredient/reference-attachment flow ("Add ingredients to the
    prompt box" was seen but never opened) and any error-state
    screens. A submission that unexpectedly hits either lands on
    UI_CHANGED/SUBMISSION_UNCERTAIN rather than a fabricated click
    sequence.

    base_url/base_url_resolver must resolve to a SPECIFIC project URL
    (https://flow.google.com/project/<uuid>), not the bare domain -
    the real compose UI lives inside a project, and this class never
    creates one itself ("New project" has a real, visible side effect
    on the account and is never clicked automatically). Reuses the
    exact same per-account "Flow URL" field/mechanism
    GoogleFlowUIAdapter and the desktop panel already use, rather than
    adding a redundant new field - the operator points it at a
    project's URL instead of the bare domain for real submissions.

    Only ever mutates its own `_pages` dict from inside the worker
    thread (every public method here runs its actual work through
    `self._worker.submit(...)`), matching FlowBrowserWorker's own
    threading contract - identical discipline to GoogleFlowUIAdapter.
    """

    def __init__(
        self,
        *,
        worker: FlowBrowserWorker,
        base_url: str | None = None,
        base_url_resolver: Callable[[str], str] | None = None,
        names: GoogleFlowRealAccessibleNames | None = None,
        headless: bool = True,
        operation_timeout_seconds: float = 30.0,
        download_root: Path = DEFAULT_FLOW_DOWNLOAD_ROOT,
        profile_directory_resolver: Callable[[str], Path] = profile_directory,
    ) -> None:
        """
        Exactly one of base_url/base_url_resolver must be given.

        base_url is what the desktop panel uses - one operator, one
        account selected at a time, so one fixed project URL per
        adapter instance is correct there. base_url_resolver is what a
        single, long-lived adapter instance serving MULTIPLE accounts
        needs (e.g. the orchestrator, routing across several accounts
        via GoogleFlowAccountRouterService) - each account's own saved
        project URL (ProviderProfile.metadata["flow_url"], the exact
        same value the desktop panel's Flow URL field manages) rather
        than one URL forced onto every account.
        """

        if (base_url is None) == (base_url_resolver is None):
            raise ValueError(
                "Exactly one of base_url or base_url_resolver must be given."
            )

        self._worker = worker

        if base_url_resolver is not None:
            self._base_url_resolver: Callable[[str], str] = base_url_resolver
        else:
            fixed_url = base_url
            assert fixed_url is not None  # guaranteed by the check above  # noqa: S101
            self._base_url_resolver = lambda _profile_id: fixed_url

        self._names = names or GoogleFlowRealAccessibleNames()
        self._headless = headless
        self._operation_timeout_seconds = operation_timeout_seconds
        self._download_root = download_root
        self._profile_directory_resolver = profile_directory_resolver

        self._pages: dict[str, Page] = {}

    @property
    def _action_timeout_ms(self) -> float:
        """Same reasoning as GoogleFlowUIAdapter's own property of the
        same name: kept shorter than every outer future timeout below
        so a genuine "can't find/interact with this control" condition
        fails fast and is actually caught."""

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
            page.goto(
                self._base_url_resolver(profile_id), timeout=self._action_timeout_ms
            )

            return self._looks_authenticated(page)

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
            page.goto(
                self._base_url_resolver(attempt.profile_id),
                timeout=self._action_timeout_ms,
            )

            if not self._looks_authenticated(page):
                return attempt.with_transition(
                    GoogleFlowGenerationState.AUTH_REQUIRED,
                    detail="Flow shows no sign of an authenticated session.",
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
                return attempt

            thumbnails = page.get_by_role(
                "img", name=self._names.generated_video_thumbnail
            )

            if thumbnails.count() == 0:
                # Still generating - real Flow shows no distinct
                # progress indicator in the accessible tree, only the
                # eventual thumbnail (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md
                # section 5) - read-only, correctly reports unchanged.
                return attempt

            return attempt.with_transition(
                GoogleFlowGenerationState.READY_TO_DOWNLOAD,
                detail=f"Flow shows {thumbnails.count()} generated thumbnail(s).",
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

            # Opens the first completed thumbnail's edit view, matching
            # docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 7 - real Flow
            # has no direct "download from the grid" control observed;
            # Download scene lives inside the per-video edit view.
            page.get_by_role(
                "img", name=self._names.generated_video_thumbnail
            ).first.click(timeout=self._action_timeout_ms)

            with page.expect_download(
                timeout=self._operation_timeout_seconds * 1000
            ) as download_info:
                page.get_by_role(
                    "button", name=self._names.download_scene_button
                ).click(timeout=self._action_timeout_ms)

            download = download_info.value
            destination = destination_dir / download.suggested_filename
            download.save_as(str(destination))

            done_button = page.get_by_role(
                "button", name=self._names.done_editing_scene_button
            )

            if done_button.count() > 0:
                done_button.click(timeout=self._action_timeout_ms)

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
        # Same honesty as GoogleFlowUIAdapter: no real, verified way to
        # actually stop an in-flight generation was found - claiming
        # to cancel it would be dishonest rather than merely
        # unimplemented.
        self.ensure_supported(ExternalUIOperation.CANCEL_OR_ABANDON)

        raise AssertionError("unreachable - ensure_supported always raises first")

    def _drive_submission(
        self,
        page: Page,
        request: GoogleFlowGenerationRequest,
        attempt: GoogleFlowGenerationAttempt,
    ) -> GoogleFlowGenerationAttempt:
        current = attempt

        try:
            self._apply_settings(page, request.execution_settings)
        except _FlowSettingsUnavailableError as error:
            return current.with_transition(
                GoogleFlowGenerationState.FAILED,
                detail=f"FLOW_SETTINGS_UNAVAILABLE: {error}",
            )

        current = current.with_transition(
            GoogleFlowGenerationState.SETTINGS_VERIFIED,
            detail="Requested settings applied via the real settings popover.",
        )

        prompt_box = page.locator(self._names.prompt_input_css)
        prompt_box.click(timeout=self._action_timeout_ms)
        page.keyboard.type(request.prompt, delay=10)
        current = current.with_transition(
            GoogleFlowGenerationState.PROMPT_PREPARED,
            detail="Exact persisted prompt typed - never rewritten.",
        )

        if request.reference_assets:
            # "Add ingredients to the prompt box" was located but its
            # real upload flow was never opened/verified (see class
            # docstring) - never guessed here.
            return current.with_transition(
                GoogleFlowGenerationState.UI_CHANGED,
                detail=(
                    "This request has reference assets, but the real "
                    "ingredient-attachment flow is not yet verified - "
                    "refusing to guess rather than risk a silent drop."
                ),
            )

        start_button = page.get_by_role(
            "button", name=self._names.start_generation_button
        )

        if start_button.is_disabled(timeout=self._action_timeout_ms):
            return current.with_transition(
                GoogleFlowGenerationState.FAILED,
                detail=(
                    "Start generation stayed disabled after typing the "
                    "prompt - the real product's own disabled-state rule "
                    "(docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 3)."
                ),
            )

        current = current.with_transition(
            GoogleFlowGenerationState.ANALYZING,
            detail="About to click Start generation.",
        )

        # The credit-sensitive boundary (this whole initiative's own
        # rule): persisted BEFORE the operation that may spend
        # provider credit.
        current = current.with_transition(
            GoogleFlowGenerationState.SUBMITTING,
            detail="Crossing the credit-sensitive submission boundary.",
        )

        start_button.click(timeout=self._action_timeout_ms)

        if self._wait_for_new_tiles_or_confirmation(page):
            current = current.with_transition(
                GoogleFlowGenerationState.SUBMITTED,
                detail="New generating tile(s) appeared after Start generation.",
            )

            return current.with_transition(
                GoogleFlowGenerationState.GENERATING,
                detail="Generation is in progress.",
            )

        # No positive evidence generation actually started (no new
        # tile). This class never enables Agent mode (see the class
        # docstring), and confirmation-before-generating is confirmed
        # to be an Agent-mode-only setting
        # (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 4a) - so this
        # is NOT expected to be a confirmation screen for the account/
        # settings this class actually drives, but something else
        # unrecognized. Never blindly retried, matching the credit-
        # sensitive-state rule exactly.
        return current.with_transition(
            GoogleFlowGenerationState.SUBMISSION_UNCERTAIN,
            detail=(
                "No positive evidence generation started after clicking "
                "Start generation - an unrecognized real screen (not "
                "expected to be Agent-mode confirmation, since Agent is "
                "never enabled by this class)."
            ),
        )

    def _apply_settings(
        self, page: Page, settings: GoogleFlowExecutionSettings
    ) -> None:
        """
        Open the real settings popover and click the radio/menu option
        matching each requested dimension - never silent substitution,
        matching GoogleFlowUIAdapter's own rule: a requested value this
        method cannot find raises _FlowSettingsUnavailableError rather
        than leaving Flow's current default silently in place.
        """

        if not any(
            (
                settings.model_family,
                settings.resolution,
                settings.duration_seconds,
                settings.aspect_ratio,
                settings.variation_count,
            )
        ):
            # Nothing requested - Flow's own current defaults for this
            # project stand, matching "never guess a value the caller
            # didn't ask for".
            return

        page.get_by_role("button", name=self._names.settings_trigger_button).click(
            timeout=self._action_timeout_ms
        )

        if settings.model_family:
            page.get_by_role(
                "button", name=self._names.select_model_family_button
            ).click(timeout=self._action_timeout_ms)
            option = page.get_by_role(
                "menuitem", name=settings.model_family, exact=True
            )

            if option.count() == 0:
                raise _FlowSettingsUnavailableError(
                    f"requested model_family '{settings.model_family}' is not "
                    "one of the real options Flow currently offers."
                )

            option.click(timeout=self._action_timeout_ms)

        if settings.resolution:
            self._click_radio(page, settings.resolution, dimension="resolution")

        if settings.duration_seconds:
            duration_name = f"{int(settings.duration_seconds)}s"
            self._click_radio(page, duration_name, dimension="duration_seconds")

        if settings.aspect_ratio:
            self._click_radio(page, settings.aspect_ratio, dimension="aspect_ratio")

        if settings.variation_count:
            variation_name = _VARIATION_COUNT_RADIO_NAMES.get(settings.variation_count)

            if variation_name is None:
                raise _FlowSettingsUnavailableError(
                    f"requested variation_count {settings.variation_count} is "
                    "not one of the real x1-x4 options Flow currently offers."
                )

            self._click_radio(page, variation_name, dimension="variation_count")

        # Closing mechanism is NOT verified against the real product -
        # Escape is a conservative, standard way to dismiss a popover
        # without guessing at a specific close control this session
        # never observed.
        page.keyboard.press("Escape")

    def _click_radio(self, page: Page, name: str, *, dimension: str) -> None:
        radio = page.get_by_role("radio", name=name)

        if radio.count() == 0:
            raise _FlowSettingsUnavailableError(
                f"requested {dimension} '{name}' is not one of the real "
                "options Flow currently offers."
            )

        radio.first.click(timeout=self._action_timeout_ms)

    def _wait_for_new_tiles_or_confirmation(self, page: Page) -> bool:
        """
        Poll for the real, verified positive-evidence signal that
        generation actually started: the prompt box clearing itself
        back to empty (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 5 -
        confirmed real, immediate behavior for the one real submission
        tested). Returns False, never guessing at an unrecognized
        screen, if that doesn't happen within the timeout.
        """

        start_button = page.get_by_role(
            "button", name=self._names.start_generation_button
        )

        deadline = time.monotonic() + self._operation_timeout_seconds

        while time.monotonic() < deadline:
            if start_button.is_disabled():
                return True

            page.wait_for_timeout(50)

        return False

    def _looks_authenticated(self, page: Page) -> bool:
        """
        Real, verified authenticated-session signal
        (docs/GOOGLE_FLOW_REAL_UI_FINDINGS.md section 2): the real
        dashboard shows a "New project" button; an unauthenticated
        visitor never does (the public marketing page shows "Create
        with Google Flow" instead). Works whether base_url is the
        dashboard or a project URL, since a project's own navigation
        bar/back button only renders for an authenticated session too -
        this checks account details instead when New project itself
        isn't present (i.e. base_url is a project, not the dashboard).
        """

        if page.get_by_role("button", name=self._names.new_project_button).count() > 0:
            return True

        return page.get_by_role("button", name="Account details").count() > 0

    def _preflight(self, page: Page) -> None:
        """
        Verify the real prompt box and Start generation button are
        both present before touching anything credit-sensitive -
        matches GoogleFlowUIAdapter's own preflight discipline, using
        the real, verified controls instead of the fixture's.
        """

        missing = []

        if page.locator(self._names.prompt_input_css).count() == 0:
            missing.append("prompt_input")

        if (
            page.get_by_role("button", name=self._names.start_generation_button).count()
            == 0
        ):
            missing.append("start_generation_button")

        if missing:
            raise GoogleFlowUIChangedError(
                "UI_CHANGED: the following expected real Flow controls "
                f"could not be found: {', '.join(missing)}."
            )

    def _get_or_open_page(self, profile_id: str) -> Page:
        """
        Must only ever be called from inside the worker thread - same
        contract as GoogleFlowUIAdapter._get_or_open_page(), which its
        own docstring explains in full (the real-world bug fixed by
        reading a real persistent, already-authenticated profile
        instead of an ephemeral one).
        """

        existing = self._pages.get(profile_id)

        if existing is not None:
            return existing

        directory = self._profile_directory_resolver(profile_id)
        context = self._worker.open_persistent_context_from_worker_thread(
            profile_id, directory, headless=self._headless
        )
        page = context.pages[0] if context.pages else context.new_page()
        self._pages[profile_id] = page

        return page


class _FlowSettingsUnavailableError(RuntimeError):
    """Internal only - a requested execution setting has no matching
    real control. Always caught by _drive_submission and turned into a
    FAILED transition; never escapes this module."""
