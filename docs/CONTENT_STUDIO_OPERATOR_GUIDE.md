# Content Studio Operator Guide

Content Studio Redesign, Phase 19: "Final documentation for both
internal-content and imported-script workflows." A practical, task-
oriented guide for running a project end to end - not a repeat of
`docs/IMPLEMENTATION_STATE.md` (what's built and why) or
`docs/SYSTEM_TRACEABILITY_MATRIX.md` (model → service → GUI → tests
per capability). Read those for architecture; read this to actually
run a project.

## Two ways to start a project

Every project reaches the same destination - a locked, production-
ready script (`VideoJob.script_lock`) - by one of two paths. Both are
first-class; neither is a fallback for the other.

### Path A: Internal Content Production

Let Content Studio write the script from a topic. This is the
`ContentIntelligencePipeline` path, and it is what "Run automation" /
"Resume automation" on the Content Intelligence card drives:

1. **Audience Promise** - who this is for and what it promises them.
2. **Research Plan → Research** - a brief, then retrieval and fact
   integrity (Evidence Ledger, source accept/reject, fact-check).
3. **Story Angles** - candidate framings, scored; select or combine.
4. **Narrative Architecture** - the beat sheet / blueprint, plus a
   rule-based Retention Audit before any prose is written.
5. **Hooks** - candidate hooks generated and scored; select or write
   your own.
6. **Writing Directives** - system/genre/project/user directives
   resolved into one coherent set the script generator obeys.
7. **Script** - written, then compressed.
8. **Continuity Bible, Editorial Critique, Quality Gate** - advisory
   extraction, independent critique, and a pass/needs-revision/
   needs-review verdict. One bounded automatic revision pass runs if
   the first verdict is fixable; a human decides beyond that.
9. **Packaging Hypothesis, Scene Planning** - a thin packaging
   direction, then genre-aware scenes derived from the finished
   script.
10. **Script Lock** - once the quality gate is `APPROVED_FOR_PRODUCTION`
    (and no blocking continuity-critical ambiguities are open), the
    script locks automatically under `full_auto()`, or waits for
    "Approve & lock script" under the other two approval postures.

### Path B: Import Approved Script (Script Intake)

Already have an approved script from outside Content Studio? Paste it
or upload a `.txt` file on the Script panel's import section, pick an
intake mode, and import:

- **Trust My Script** - accepted as-is, no analysis.
- **Validate For Production** - one pass checking language/genre/
  audience/platform consistency against the project's own settings.
- **Full Quality Check** - same validation today; does not yet run
  the full editorial critique pipeline (see Known Gaps below).

An imported script deliberately has **no** research, story angle,
hook, or blueprint - Content Studio does not fabricate any of those
to satisfy a stage that doesn't apply. From here, the script can still
be edited (selection-scoped AI edits, typed edits, versioned/restored)
and locked exactly like an internally-produced one - locking infers
`ScriptProvenance.EXTERNAL` automatically, so this is a real, complete
second path to the same Script Lock, not a partial one.

## Choosing an approval posture

Set on `VideoJob.approval_policy` (project settings), one engine
underneath all three:

| Preset | Behavior |
|---|---|
| `full_auto()` | Every stage auto-continues; automation runs straight through to Script Lock in one call. |
| `review_critical_stages()` | Pauses at the stages judged high-impact (story angle, final script, ...); auto-continues elsewhere. |
| `manual_editorial()` | Pauses at every gated decision point for an explicit human action. |

"Run automation" / "Resume automation" on the Content Intelligence
card always calls the same `run_all()` - a paused project resumes
exactly where it left off (already-completed stages are never
regenerated); nothing about resuming requires knowing which posture
produced the pause.

## Checking where a project stands

- **Production journey strip** (top of the workspace) - an 8-checkpoint
  glance: Audience → Research → Angle → Story → Hook → Script →
  Quality → Script Lock.
- **Automation status** (Content Intelligence card) - completed-stage
  count, and while paused, the exact blocked stage/decision/summary.
- **Activity History** (its own card) - the full chronological,
  filterable ledger of every stage's generation, approval, revision,
  restore, and lock/unlock event, not only the gated ones. Filter by
  category or stage to find one specific event in a long project.

## Editing and recovering a script

- **Selection edits** - highlight text in a segment, pick an action
  (Rewrite/Shorten/Expand/More Suspenseful/More Natural/Improve
  Transition/Custom), or type directly and "Save typed edit."
- **Versions** - every edit (AI-assisted, typed, revision-driven,
  restored) is its own version with a reason. Compare any two
  versions segment-by-segment, or **Restore** an earlier one as a new
  version - nothing is ever destroyed, so a restore is itself
  undoable by restoring again.
- **Locking** - "Approve & lock script" refuses over unresolved
  blocking quality findings or continuity-critical ambiguities unless
  given an explicit override reason. **Unlocking** shows the real list
  of dependent production assets (scenes, clips, timelines, render
  results) that go stale, not a generic warning.

## Legacy pipeline

The original `ContentPipeline` (Research → Script → Originality
Review → Scenes, one card each, no genre-awareness, no critique) is
still present and fully functional - kept for existing projects, not
removed. A new project sees a plain notice pointing to Content
Intelligence instead; the notice disappears once a project has
clearly committed to one path or the other. Nothing about the legacy
cards is disabled - an in-progress legacy project is never stranded.

## Known gaps (see `docs/REMAINING_GAPS.md`/`IMPLEMENTATION_STATE.md` for the full list)

- Full Quality Check intake mode does not yet auto-trigger the full
  editorial critique (blocked on that service's `research` parameter
  becoming optional, so it doesn't fabricate a fake `ResearchResult`).
- No fourth "Automatic Reviewer" approval posture yet.
- No document-format script import beyond plain `.txt` (paste/upload
  both go through the same text path).
- No rollback-to-any-past-project-state recovery beyond script-version
  Restore; no activity-log export.
