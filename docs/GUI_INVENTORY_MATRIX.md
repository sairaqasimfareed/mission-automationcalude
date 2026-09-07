# GUI-0: Live GUI Inventory Matrix

Unified GUI & Release Hardening, Phase GUI-0. Every desktop surface in
this codebase, audited against the current canonical runtime -
reachability, controller/service mapping, keep/refactor/retire
decision, and known gaps. Built from actually reading the code
(`src/desktop/main_window.py`, `src/desktop/views/project_workspace_view.py`,
and every view file), not assumed from the plan document's own generic
language.

## 1. Navigation map (complete, verified)

```
MainWindow toolbar (5 actions)
├── Dashboard              -> DashboardView
├── New Project            -> ProjectFormView
├── Providers              -> ProviderManagerView
├── Google Flow            -> GoogleFlowProviderPanelView
└── Settings               -> SettingsView

Dashboard "open project"    -> ProjectWorkspaceView (the project shell)
  └── 7 workspace tabs (left sidebar)
      ├── Content           -> ContentStudioView
      ├── Clips             -> ClipWorkspaceView
      ├── Audio             -> ProductionAudioView
      ├── Timeline          -> EditingTimelineView
      ├── Render            -> RenderWorkspaceView
      ├── Quality           -> QualityCenterView
      └── Packaging         -> PackagingView
```

**Finding: every single view file in `src/desktop/views/` (13 files,
excluding `__init__.py`) is accounted for in this map, and every one
is reachable from exactly one place.** There is no orphaned, hidden,
unreachable, or duplicate-competing view anywhere in this codebase -
the "misleading duplicate entry points" the plan document warns about
in general terms do not exist here. `recovery_dialog.py`'s
`show_recoverable_error()` is a shared helper (QMessageBox + optional
Retry), not a separate window - used consistently across Content
Studio, Render, Packaging, Quality Center, Clip Workspace, and
Production Audio (`no_blocking_dialogs` in
`tests/test_desktop_app_integration.py` patches all six call sites,
itself independent evidence of consistent reuse rather than six
divergent implementations).

## 2. Per-surface matrix

| Surface | Reachable from | Backing controllers/services (from `MainWindow`/`ProjectWorkspaceView` construction) | Decision | Notes |
|---|---|---|---|---|
| `MainWindow` | App entrypoint (`src/desktop/app.py`) | `services.get_job_store()` | **Keep** | Owns the `QStackedWidget` + toolbar; thin, no business logic |
| `DashboardView` | Toolbar "Dashboard" | `JobStore`, `PipelineCheckpointStorageService` | **Keep** | |
| `ProjectFormView` | Toolbar "New Project" | `JobStore`, `ProviderProfileManagementService` | **Keep** | Already has real per-stage `ApprovalPolicyConfig` mode controls (GUI-3 groundwork already built) |
| `ProviderManagerView` | Toolbar "Providers" | `ProviderProfileManagementService` | **Keep** | Category dropdown excludes `EXTERNAL_UI_VIDEO` on purpose - Google Flow gets its own panel, not a bolted-on field (GF-13) |
| `GoogleFlowProviderPanelView` | Toolbar "Google Flow" | `ProviderProfileManagementService`, `FlowBrowserWorker` | **Keep** | Built this session (GF-13); structurally separate from Provider Manager for a real reason (browser-profile auth, never an API key) |
| `SettingsView` | Toolbar "Settings" | `RuntimeConfigurationLoader` | **Keep** | Currently read-only display of runtime config - no user-editable theme preference lives here yet (GUI-1 gap, see section 4) |
| `ProjectWorkspaceView` | Dashboard "open project" | `JobStore` + every pipeline/service listed in `MainWindow.__init__` | **Keep** | The actual "unified project shell" GUI-2 asks for - already shows project/mode/stage/quality/budget/automation/readiness in one persistent header row (`_refresh_header_row`), rebuilt from `ProductionReadinessService` truth, not GUI-invented state |
| `ContentStudioView` | Workspace tab "Content" | `ContentPipeline`, `ContentIntelligencePipeline`, `ReviewerService`, `TopicCandidateGenerationService`, `FactCheckService` | **Keep** | Largest view (4520 lines) - the sprint 0-7 content-intelligence stack's real GUI, not a stub |
| `ClipWorkspaceView` | Workspace tab "Clips" | `AssetWorkflowService` | **Keep** | |
| `ProductionAudioView` | Workspace tab "Audio" | `MediaGenerationPipeline` | **Keep** | |
| `EditingTimelineView` | Workspace tab "Timeline" | `JobStore` only (reads/writes `VideoTimeline` directly) | **Keep** | |
| `RenderWorkspaceView` | Workspace tab "Render" | `RenderRuntimeFactory`, `AssetWorkflowService` | **Keep** | Runs render on a background `QThread`, not the GUI thread - `_wait_for_render()` in the integration tests exists specifically because of this |
| `QualityCenterView` | Workspace tab "Quality" | reads `VideoJob` fields directly + `content_intelligence_pipeline.approval_gate_service` (via `PackagingView`'s own construction, shared) | **Keep** | Already has readiness/checklist/final-preview/policy-compliance cards - GUI-5's own objective is substantially already met here, not a green-field build |
| `PackagingView` | Workspace tab "Packaging" | `SEOPackageService`, `ThumbnailPackageService`, `FinalExportService`, `ApprovalGateService` | **Keep** | |

No surface was found that warrants **Refactor** or **Retire** at this
pass - a genuinely different outcome than the plan document's generic
language assumed, and worth stating plainly rather than inventing a
retirement candidate to match the template.

## 3. GUI-only transient state (already identified, already justified)

`ContentStudioView` is the one view with meaningful non-persisted
state, and it already documents why each piece is safe:

- `_last_review_by_stage: dict[str, ReviewerResult]` - "a review is a
  read-only critique, never persisted to VideoJob (the Reviewer never
  becomes the author)". Cleared on `set_job()` (switching projects),
  rebuilt fresh each `refresh()` otherwise.
- `_script_segment_editors`, `_script_compare_from/_to`,
  `_last_script_comparison`, `_quality_finding_checkboxes`,
  `_script_intake_editor/_mode_select` - "rebuilt fresh every
  refresh() so a segment's editable text survives redraws only via
  job.generated_script itself (Save/AI-edit actions persist to the
  job before the next refresh)".
- `_selected_ci_stage_index`, `_activity_history_category_filter`,
  `_activity_history_stage_filter` - plain UI selection/filter state,
  correctly never persisted (matches every other list/tab selection
  in the app).

No GUI-only state was found anywhere that represents a decision or
artifact that *should* be persisted but currently isn't - the
"identify GUI-only transient state that must become persisted
projection" requirement turns up nothing to fix here.

## 4. Approval/reviewer surface map

Three real, already-built surfaces, confirmed by reading the code
(not assumed):

1. **`ProjectFormView`** (New/Edit Project) - per-decision-point
   `ApprovalPolicy` controls (`_POLICY_LABELS`: "Auto-continue" /
   "Review if uncertain" / "Always require approval"), building a
   real `ApprovalPolicyConfig` on submit.
2. **`ProjectWorkspaceView`'s header row** - live `Approval: <mode>`,
   `Next approval: <pending decision or "None pending">`, `Readiness:
   <state>` fields, rebuilt from `ProductionReadinessService` on every
   `refresh()` - not a GUI-invented status.
3. **`ContentStudioView._render_review_result()`** - Reviewer findings
   rendered under an explicit "Reviewer feedback:" heading, severity-
   mapped (`blocking` -> red/error, everything else -> amber/warning),
   visually separate from the approval-mode controls above it. This
   already satisfies GUI-3/GUI-5's "Reviewer advice visually separate
   from operator approval and hard blockers" requirement.

## 5. Tests: GUI import/smoke baseline + navigation

Already substantially in place before this pass, with one real gap
found and closed:

- `test_main_window_constructs_and_navigates` - **was** only
  exercising 3 of the 5 toolbar actions (Dashboard/New
  Project/Settings); Providers and Google Flow were reachable in the
  real app but never asserted in this test. **Fixed** the same day
  this matrix was written - now covers all 5.
- `test_workspace_views_refresh_without_crashing_on_a_fresh_project` -
  already iterates all 7 workspace tabs against a freshly created
  project's empty state.
- `test_project_header_row_reflects_summary_and_rebuilds_on_refresh` -
  already covers the unified shell's header projection.
- Every desktop view file has its own dedicated test file (confirmed:
  `test_provider_manager_view.py`, `test_google_flow_provider_panel_view.py`,
  `test_content_studio_content_intelligence_gui.py`, and others already
  existed for the rest before this session).

## 6. Known, real gaps (not invented to match the template)

These are the genuine, evidenced gaps this audit actually found -
GUI-1 through GUI-8 should target these specifically rather than
re-building what already exists:

- **GUI-1 (design system)**: ~~theme is dark-only. No Light/System
  option, no persisted theme preference anywhere in the codebase~~ -
  **addressed, same day**: `ThemeMode` (SYSTEM/LIGHT/DARK), a real
  separately-designed Light palette, `ThemePreferenceStore`
  (`data/desktop_preferences.json`), and an "Appearance" section in
  `SettingsView`. See `PROJECT_PROGRESS.md`'s GUI-1 entry and
  `docs/IMPLEMENTATION_STATE.md`'s GUI-1 row for the full account.
- **GUI-6 (Windows hardening)**: real, evidenced, ongoing need - this
  same session found and fixed three genuine Windows-rendering bugs
  independent of any GUI-0 audit (a missing `QPalette` making
  `QComboBox` dropdown arrows invisible; a headed Playwright browser
  window rendering cut off/wrongly sized; a prior fix for overlapping
  Provider Manager advanced-form rows, see `PROJECT_PROGRESS.md`'s
  `c43ae4c` entry). No systematic accessibility audit (keyboard focus
  order, accessible labels, high-DPI scaling) has been done - these
  were all found reactively, not by a deliberate pass.
- **GUI-8 (full validation)**: strong per-commit quality gates already
  exist (mypy/ruff/black/pytest on every change, confirmed throughout
  this project's history), but no single coherent "click every button,
  check every theme, look for dead buttons" pass across the whole
  desktop app exists as one test/checklist.
- **Pre-existing, unrelated mypy gap**: `tests/test_desktop_app_integration.py`
  has 3 pre-existing mypy findings (lines ~578/643/654 as of this
  writing - `QLayoutItem | None` narrowing, a callback typed `object`
  called directly) that predate this audit and are out of this
  phase's scope to fix, but are noted here so they're not mistaken for
  something this pass missed.

## 7. What this means for the rest of the plan

GUI-2, GUI-3, GUI-4, GUI-5 are **substantially already built** -
their own stated exit gates are largely already met by the surfaces
in section 2. Treating them as green-field phases would mean
rebuilding working, tested code, which contradicts the plan
document's own stated authority boundary ("Reuse existing
windows/components where sound, retire misleading duplicates only
after runtime/compatibility audit"). The real remaining work this
plan should concentrate on:

1. ~~**GUI-1**: build actual Light/System theme support + a persisted
   preference~~ - **done, same day** (see PROJECT_PROGRESS.md).
2. **GUI-6**: a deliberate accessibility/Windows-hardening pass
   (keyboard focus order, accessible labels, high-DPI scaling,
   long-text handling) rather than continuing to find these bugs
   reactively.
3. **GUI-8**: a coherent, documented full-desktop validation pass once
   2 lands.

GUI-0's own exit gate - "Complete GUI matrix with exact keep/refactor/
retire decisions" - is met by this document.
