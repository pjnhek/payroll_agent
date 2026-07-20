---
status: testing
phase: 21-durability-proofs-ops-view
source: [21-07-SUMMARY.md, 21-11-SUMMARY.md]
started: 2026-07-20T00:00:00Z
updated: 2026-07-20T00:00:00Z
---

## Current Test

number: 1
name: Live alarm baseline and the drain-runs-while-firing proof
expected: |
  The alarm has no mute by design, so a non-zero baseline fires on deploy.
  Every baseline row must be dispositioned before approval, and the drain
  must be shown to run even while the alarm is red.
awaiting: user response

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
result: [pending]

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
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
