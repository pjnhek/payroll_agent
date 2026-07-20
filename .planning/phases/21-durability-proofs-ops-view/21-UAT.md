---
status: complete
phase: 21-durability-proofs-ops-view
source: [21-07-SUMMARY.md, 21-11-SUMMARY.md]
started: 2026-07-20T00:00:00Z
updated: 2026-07-20T19:55:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live alarm baseline + drain-runs-while-firing (from 21-07)
expected: |
  a) Query repo.list_unaccounted_error_runs() against the live database.
     Record the count and run ids, and disposition each row as retriggered /
     terminally settled / intentionally retained.
  b) Trigger pump.yml via workflow_dispatch with at least one unaccounted
     error run present. Confirm from the real Actions log that the drain
     executed, the alarm step ran last and red, and the drain was NOT
     skipped or short-circuited.
  Code-side is already verified: drain at pump.yml:62 carries no `if:`
  guard; alarm sits last at :129.
result: pass
verified: |
  Prerequisite discovered during UAT: master was 94 commits ahead of
  origin/master — Phase 21 was entirely unpushed, so /ops and /health/queue
  404'd and the deployed pump.yml had no alarm step. Pushed origin/master
  b50d982..eeb1c78; deploy-migrate CI green (live schema applied cleanly);
  Render redeployed (/ops + /health/queue → 200).
  a) list_unaccounted_error_runs() vs LIVE Supabase → 0 rows. State clean:
     payroll_runs = 23 awaiting_approval / 6 needs_operator / 2 approved /
     1 reconciled / 1 awaiting_reply, ZERO error; jobs = 25, all done (0 dead,
     0 pending, 0 due). Empty baseline — nothing to disposition.
     /health/queue on deployed service = {"status":"ok"} 200.
  b) Dispatched pump.yml (run 29773910333, green). 7 steps in order: drain
     (step 3, curl /internal/pump, no `if:`), health/ready, health/schema,
     alarm (step 6, LAST, curl /health/queue → {"status":"ok"}). Recovery-first
     ordering proven live: drain ran before the alarm and was not gated by it.
  Caveat (operator-accepted): the written premise "a non-zero baseline fires
  on deploy" is FALSE against reality — baseline is clean, so the alarm ran
  GREEN, not RED. The literal "alarm red while drain runs" variant would
  require inserting an unaccounted error run into PRODUCTION; the RED path is
  instead covered by hermetic tests (TestAlarmStepOrdering + the live-firing
  predicate test test_ops_alarm_predicate.py, 8/8). Passed on clean baseline
  per operator judgment.

### 2. /ops legibility and the published evidence (from 21-11)
expected: |
  a) Load /ops on the deployed service. Each of the four panels reads as a
     comparison, not a bare number (depth split pending/leased; oldest-due
     age vs pump cadence; attempts vs max; dead-letter attempts vs max).
  b) The "as of <timestamp>" stamp is present and does not move if the page
     is left open for a minute.
  c) Nav reads `Pyrl | Runs | Eval | Ops`; /ops carries no button, form, or
     dismiss control — every route to action goes via a run-detail link.
  d) Clicking a dead-letter or alarm row lands on that run's detail page
     where Retrigger lives.
  e) With JavaScript disabled, /ops still renders fully.
  f) docs/DURABILITY-PROOFS.md is reachable from the README; one proof
     section is re-runnable from what is written; the "What is not
     guaranteed" section says what you would want said.
result: pass
verified: |
  Verified against the LIVE deployed service (https://payroll-agent.onrender.com/ops),
  fetched via curl (JavaScript-free by construction — proves (e)):
  a) Four panels present, each framed as a comparison: Queue depth (Pending
     vs Leased, two figures), Oldest due-pending age ("Bound: recovery within
     the pump's 30-minute cadence"), Attempts distribution ("Bound: dead-letters
     after 5 attempts"), Dead letter. (Clean baseline → attempts/dead-letter
     show empty states; the "N of 5" rows are unpopulated but the bound text
     renders.)
  b) As-of stamp present + static: "As of 2026-07-20 19:54:05 UTC. This view
     refreshes only when reloaded…" — server-rendered, no JS updates it.
  c) Nav reads exactly Pyrl | Runs | Eval | Ops; grep for
     button/form/dismiss/Retrigger/Approve/Reject on the live page → 0 matches.
  d) Dead-letter and alarm rows link to /runs/{id} (template-verified; no live
     rows to click on the clean baseline).
  e) Full 1987-byte page rendered from a plain curl (no JS).
  f) README:37 links docs/DURABILITY-PROOFS.md; doc has PROOF-01..05 +
     "What is not guaranteed" + "The operational counterpart". Re-runnability
     demonstrated end-to-end: ran the doc's own PROOF-01 command verbatim
     against a throwaway local Postgres → 1 passed; applied the doc's exact
     diff → RED at `assert claimed.attempts == 1` (AssertionError: assert 0 == 1,
     matching the pasted red); reverted byte-identical (empty git diff --stat);
     green again. Every line matched the doc's pasted output.
  Subjective legibility ("reads as a comparison" / "reads as evidence"):
  operator confirmed "everything else seems to be good"; (f) additionally
  demonstrated concretely above.

## Summary

total: 2
passed: 2
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none — both checkpoints passed]
