# MRA-PRE-7: GUI and Operator Workflow Audit

Pre-Installer Master Audit, Phase 7. Objective: verify operator-facing
GUI state is complete and correctly surfaces what an operator needs to
know - overlaps heavily with GUI-0/1/6/8's own earlier work (per
`docs/IMPLEMENTATION_STATE.md`'s own working note for this phase), so
this pass targets the two concrete, already-diagnosed gaps MRA-PRE-2
explicitly carried forward, rather than re-doing GUI-0/1/6/8 from
scratch. Every finding below follows the evidence format defined in
`docs/MRA_PRE_0_BASELINE.md` section 9 (claim under test / method /
evidence / verdict / HEAD).

**Note on source material**: as with MRA-PRE-4/5/6, this phase's exact
PDF wording could not be re-quoted verbatim in this segment.

**HEAD at phase start**: `cb156c2cad1772643ccf11c849b588ad627cb1c6`.

## Findings

### MRA-PRE-7-001: `job.stale_artifacts` already has real GUI surfacing - MRA-PRE-2's claim was stale

**Claim under test**: MRA-PRE-2 recorded *"neither Google Flow
generation-attempt state... nor `job.stale_artifacts`... has any GUI
surfacing anywhere."*
**Method**: traced `job.stale_artifacts` forward from
`InvalidationService` through every consumer, rather than trusting the
earlier phase's own claim at face value.
**Evidence**: `ProductionReadinessService._staleness_blockers()`
already converts every `StaleArtifact` record into a real `Blocker`
(`code=BlockerCode.ARTIFACT_STALE`, `message=f"'{record.artifact}' is
stale: {record.reason}"`), and `QualityCenterView._build_readiness_
card()` genuinely renders `blocker.message` via a real `status_label`
widget in the "Production readiness" card - confirmed by reading the
rendering code directly, not merely that a service method exists.
This was already true at MRA-PRE-2's own HEAD (`0a08297`), predating
this phase entirely.
**Verdict**: RISK (a stale, incorrect claim in a prior phase's own
finding, corrected here) - **not a real gap**. No code changed; this
finding exists to correct the record, matching this audit's own
established discipline (see MRA-PRE-4-004 for the same kind of
correction applied to a different stale claim).

### MRA-PRE-7-002: Google Flow generation attempt state had genuinely zero GUI surfacing

**Claim under test**: the other half of MRA-PRE-2's claim - whether an
operator can see when a Google Flow generation attempt has reached a
state that needs their attention (an expired session, an unrecognized
page layout, a required confirmation, an uncertain submission, or a
failed post-download quality check).
**Method**: `grep -rln "flow_generation_attempts\|
GoogleFlowGenerationState\|SUBMISSION_UNCERTAIN" src/desktop/` across
the whole desktop GUI layer.
**Evidence**: the only match was a code comment referencing the
concept, not an actual reader of `job.flow_generation_attempts`
anywhere. `ProductionReadinessService` (the "single centralized
answer" every GUI readiness indicator is meant to consume, per its own
docstring) had no method covering this field at all. An attempt
reconciled to `SUBMISSION_UNCERTAIN` by MRA-PRE-2's own restart-
reconciliation fix earlier this session would sit invisible to an
operator indefinitely - genuinely reproduced this half of the original
claim, unlike finding 001.
**Verdict**: GAP FOUND (severity: **moderate** - an operator has no
way to notice a stuck generation attempt without opening the raw job
JSON) - **fixed same day**. Added `_google_flow_attempt_blockers()` to
`ProductionReadinessService`, reusing the exact same `Blocker`/
`ProductionReadinessReport` vocabulary `_staleness_blockers()` already
proved reaches the GUI (finding 001) rather than inventing a second,
parallel surface - zero new GUI code was needed, only a new blocker-
producing method plus one new `BlockerCode` value
(`GOOGLE_FLOW_ATTEMPT_NEEDS_ATTENTION`). Flags an attempt whose state
is one of `SUBMISSION_UNCERTAIN`/`AUTH_REQUIRED`/`HUMAN_ACTION_
REQUIRED`/`UI_CHANGED`/`QC_FAILED` (`GoogleFlowGenerationState`'s own
module docstring names these "interrupt states" plus `QC_FAILED`),
each with a concrete, state-specific recovery action (e.g.
`SUBMISSION_UNCERTAIN`'s message explicitly warns against a duplicate
paid generation). Deliberately excludes plain `FAILED` - an expected,
regeneration-ready terminal state per `GoogleFlowGenerationAttempt`'s
own docstring, not something to sit and stare at. Proven via 3 new
tests: 2 at the service layer (one confirmed to genuinely fail without
the fix), 1 through the real `QualityCenterView` widget tree
end-to-end.

## Summary

| # | Area | Verdict |
|---|---|---|
| 001 | `stale_artifacts` GUI surfacing | RISK (stale prior claim) - corrected, no code change, not a real gap |
| 002 | Google Flow attempt state GUI surfacing | GAP FOUND (moderate) - **fixed same day**, teeth-verified through the real GUI |

## Explicitly not covered in this pass

This phase's broader working note also named "long content" and
"disabled/loading/error states" (not in GUI-6's own scoped slices) as
remaining gaps. Neither was investigated in this pass - the two items
above were the concrete, already-diagnosed carry-forwards from
MRA-PRE-2, and covering "long content"/"disabled/loading/error states"
properly would require its own exploratory sweep across every
workspace view, not a same-segment extension of this phase. Recorded
in `docs/REMAINING_GAPS.md` as open, not silently dropped.

## Validation

- `black`, `ruff check`, `mypy` on `production_readiness_service.py`
  and `models/blocker.py`: clean.
- Teeth-check on `test_a_stuck_google_flow_attempt_produces_a_blocker`:
  temporarily removed the new blocker method's wiring in `evaluate()`,
  confirmed the test correctly failed (`0 == 1`); restored, `git diff
  --stat` confirmed only the intended change remained.
- Full `tests/test_production_readiness_service.py` (19 cases,
  including the 2 new ones): all passed.
- Full `tests/test_quality_center_readiness_gui.py` (3 cases,
  including the new one proving the fix reaches the real widget
  tree): all passed.

## Acceptance gate

Both concrete, already-diagnosed carry-forwards from MRA-PRE-2 were
resolved: one was found to already be working (a stale prior claim,
corrected) and one was a real, confirmed gap, fixed and teeth-verified
through the actual GUI, not just the service layer. The broader "long
content"/"disabled/loading/error states" scope named for this phase
remains open, honestly disclosed rather than claimed covered. Met for
the concrete scope this pass targeted; the broader GUI sweep is
recorded as future work.
