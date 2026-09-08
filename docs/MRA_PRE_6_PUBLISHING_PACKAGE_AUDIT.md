# MRA-PRE-6: Publishing/Package Audit

Pre-Installer Master Audit, Phase 6. Objective: verify the final,
publish-ready package (video + SEO metadata + thumbnail + manifest)
is assembled, validated, and tracked correctly - re-verification of
work substantially already built during SEO-1 through SEO-9's own
work, not a from-scratch pass (per `docs/IMPLEMENTATION_STATE.md`'s
own working note for this phase). Every finding below follows the
evidence format defined in `docs/MRA_PRE_0_BASELINE.md` section 9
(claim under test / method / evidence / verdict / HEAD).

**Note on source material**: as with MRA-PRE-4/5, this phase's exact
PDF wording could not be re-quoted verbatim in this segment. Executed
against the phase's already-recorded working title.

**HEAD at phase start**: `24edff7e45934f88ebbdbd091349ca251badba9f`.

**Confirmed first**: there is no real, automated "publish to a
platform" integration anywhere in this codebase (`grep -rln
"youtube.*upload\|YouTubeUpload\|publish_to" src/` - zero matches).
"Publishing" here means producing a complete, validated,
ready-to-hand-off package for a person to publish manually - this
phase audits that package, not an upload mechanism that doesn't exist.

## Findings

### MRA-PRE-6-001: Final export validation is thorough and correctly gates approval

**Claim under test**: `FinalExportValidationService` genuinely checks
everything a publish-ready package needs, and a failing check actually
blocks the package from being marked ready.
**Method**: read `FinalExportValidationService.validate()` and
`FinalExportService.build()` in full.
**Evidence**: seven independent checks run: video file existence,
positive duration, real ffprobe-based technical readability/audio-
stream-presence/resolution-match (reusing `MediaTechnicalValidation
Service`, already QC-proven in an earlier phase), manifest existence,
thumbnail/SEO review-readiness (soft warnings), and a hard
"upstream freshness" gate comparing `script_lock_hash` across the
package's own provenance, the SEO package, and the thumbnail artifact
- explicitly documented as *"fail closed if upstream production
authority is missing/stale... a package must never be handed off for
publishing built against a script that is no longer canonical."*
`FinalExportService.build()` only marks the package `APPROVED` when
validation finds zero hard errors, else `UNDER_REVIEW` - and the
Packaging view's own QC summary re-runs this exact same validation
fresh on every render rather than showing a stale snapshot from build
time.
**Verdict**: CONFIRMED - already thorough, correctly gates status, and
independently re-verified live rather than cached.

### MRA-PRE-6-002: Final export provenance correctly uses Script Lock, not the legacy field

**Claim under test**: whether `_build_provenance()` (the function that
snapshots what a render was built from) has the same "only checks
`job.script`" gap MRA-PRE-3 already found and fixed for SEO context
building.
**Method**: read `FinalExportService._build_provenance()` in full.
**Evidence**: reads `job.script_lock` directly (`script_lock_hash`,
`script_version_number`) - works identically for both the legacy and
current pipeline, since `ScriptLock` itself is the shared artifact
both eventually produce. No `job.script`-only assumption anywhere in
this function.
**Verdict**: CONFIRMED clean - no equivalent bug here.

### MRA-PRE-6-003: `WorkflowStage.UPLOADED` was a real, defined terminal stage with no path to ever reach it

**Claim under test**: once a project's final export is approved and
(manually, externally) actually published, the project's own state
reflects that - the loop closes.
**Method**: `WorkflowStage` enum inspection found a defined
`UPLOADED = "uploaded"` value beyond `READY_FOR_UPLOAD`. Searched
every writer of `job.current_stage`/`job.status` across the whole
codebase (`grep -rn "\.current_stage = \|\.status = JobStatus\."
src/`) and every GUI reference to `UPLOADED` specifically.
**Evidence**: `job.current_stage` is written in exactly 3 places -
`content_studio_view.py`/`content_pipeline.py` (content-production
stage transitions) and `render_orchestrator_service.py` (which sets
`READY_FOR_UPLOAD` on render success) - and **nowhere** does anything
ever write `WorkflowStage.UPLOADED`. No GUI control anywhere
references `UPLOADED` either. Since there is no real automated publish
integration (confirmed above), the only way this terminal state could
ever be reached is a person manually marking it - and no such action
existed. A project's dashboard/list view (which displays
`job.current_stage.value` directly, per `dashboard_view.py` and
`project_workspace_view.py`) would show `ready_for_upload` forever,
even for a project a person had actually gone and published
externally days or months earlier - with no way to record that fact
in the app at all.
**Verdict**: GAP FOUND (severity: **minor** - cosmetic/tracking only,
does not block or corrupt anything; the package itself was already
correctly validated and approved by finding 001) - **fixed same day**.
Added a "Mark as published" action to the Packaging view's final
export card, shown once `final_export.status == "approved"`, that
sets `job.current_stage = WorkflowStage.UPLOADED` and records an
activity-history event (matching the existing `stage="final_export"`
convention already used elsewhere in this file). A no-op if the export
is not yet approved (matching every other status-gated action already
in this view). Proven via 3 new tests, one of which was verified to
genuinely fail without the fix (reverted the assignment, confirmed
`job.current_stage` stayed `READY_FOR_UPLOAD` instead of flipping to
`UPLOADED`).

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | Final export validation thoroughness/gating | CONFIRMED |
| 002 | Final export provenance uses Script Lock correctly | CONFIRMED |
| 003 | `WorkflowStage.UPLOADED` unreachable | GAP FOUND (minor) - **fixed same day**, teeth-verified |

## Validation

- `black`, `ruff check`, `mypy` on `packaging_view.py` and
  `tests/test_packaging_view_gui.py`: clean.
- Teeth-check on `test_mark_as_uploaded_sets_the_terminal_workflow_
  stage`: reverted the `job.current_stage = WorkflowStage.UPLOADED`
  assignment, confirmed the test correctly failed
  (`ready_for_upload` != `uploaded`); restored, `git diff --stat`
  confirmed only the intended change remained.
- Full `tests/test_packaging_view_gui.py` (25 cases, including the 3
  new ones): all passed.

## Acceptance gate

The publish-ready package's own assembly, validation, and hard
approval gating are confirmed thorough and correct - already proven
sound by SEO-1 through SEO-9's own earlier work, and this phase found
no regression. One real, minor, previously-invisible tracking gap
(an entire defined enum value with zero code path to reach it) was
found and fixed same day, closing the loop between "package approved"
and "a person actually published it," with a teeth-verified test. Met.
