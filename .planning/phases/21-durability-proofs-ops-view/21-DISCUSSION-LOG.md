# Phase 21: Durability Proofs & Ops View - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-20
**Phase:** 21-Durability Proofs & Ops View
**Areas discussed:** Proof identity & consolidation, Red-run evidence mechanism, Ops view shape & contents, The swallowing alarm

---

## Todo triage

| Option | Description | Selected |
|--------|-------------|----------|
| None — keep 21 clean | Phase 21 is the milestone's evidence phase; folding UI polish dilutes the proof story and recreates the Phase 20 "secondary items pressure the safety path" dynamic | ✓ |
| Frontend progressive enhancement | Fold only what the ops page naturally needs to work without JS | |
| Eval chart restyle | Possibly already closed by Phase 20's offline SVG using dashboard tokens | |
| Paystub YTD columns | Unrelated payroll-document feature | |

**User's choice:** None — keep 21 clean
**Notes:** All three remain in the backlog. The eval-chart restyle is flagged in CONTEXT.md as likely already satisfied by Phase 20 and worth verifying/closing rather than carrying into v5.

---

## Proof identity & consolidation

### Q1 — How to establish the four canonical proofs

| Option | Description | Selected |
|--------|-------------|----------|
| Promote in place + registry | Audit each existing test against its exact roadmap criterion, strengthen where unmet, tag with its PROOF id, add a registry. DRY; no working proof rewritten | ✓ |
| Fresh canonical file | Four new self-documenting proofs in one dedicated file. Best readability; duplicates 3 passing real-Postgres proofs that could then drift | |
| Map, don't move | A PROOFS.md mapping ids to file::test_name. Cheapest; a prose map rots and a rename silently orphans the requirement | |

**User's choice:** Promote in place + registry
**Notes:** Grounded in a scout finding — 3 of 4 proofs already exist as passing tests, but zero files reference PROOF-01..05 or OPS-01.

### Q2 — What binds a PROOF id to its test, and where the completeness check lives

| Option | Description | Selected |
|--------|-------------|----------|
| Marker arg + CI collect gate | `@pytest.mark.proof("PROOF-01")` plus a `--collect-only` step in concurrency-proof.yml reding the build unless PROOF-01..04 each appear once. Survives renames/moves; sits at the selection layer where the typo gap lives | ✓ |
| Marker arg + in-suite test | Same marker, completeness checked by a test shelling out to pytest. Runs locally too; pytest-inside-pytest is awkward and can mask env differences | |
| Naming convention + grep | Rename tests to `test_proof_01_*` and grep the collect output. No new vocabulary; a rename dropping the prefix silently orphans the requirement | |

**User's choice:** Marker arg + CI collect gate
**Notes:** Targets the gap concurrency-proof.yml documents in its own comment but explicitly does not close.

### Q3 — PROOF-03's crash fidelity

| Option | Description | Selected |
|--------|-------------|----------|
| Injected seam failure, real DB | Real Postgres, gateway double returns provider-accept, settlement forced to fail before commit, second attempt replays. Teeth = byte-identical message_id + exactly one provider call + same Idempotency-Key | ✓ |
| Hard connection kill | Kill the psycopg connection mid-transaction. Higher fidelity; fragile under shared CI Postgres and proves the same invariant | |
| Both — injected + one kill case | Most thorough; doubles surface and the kill case is the likeliest to flake and get quarantined | |

**User's choice:** Injected seam failure, real DB
**Notes:** PROOF-03 was identified as having the thinnest existing coverage — Phase 20 shipped provider-handoff fence races, not this crash boundary.

### Q4 — Making PROOF-04 genuinely concurrent

| Option | Description | Selected |
|--------|-------------|----------|
| Barrier race, no sleeping | Two real OS threads on separate connections under a threading.Barrier; keep expiring leased_until by direct SQL. Matches the established sync-seam-under-Barrier convention from Phase 10's CR-01 | ✓ |
| Real elapsed lease expiry | Low LEASE_SECONDS and real wall-clock expiry. Highest fidelity; adds sleep and reintroduces the nondeterminism the current test designed out | |
| Threads only for the zombie writes | Smaller change; leaves the reclaim half — the one criterion 4 names — still non-racing | |

**User's choice:** Barrier race, no sleeping
**Notes:** Scout finding presented before the question — `test_expired_lease_is_reclaimed` (:2224) and `test_zombie_is_fenced_on_BOTH_complete_and_fail` (:2262) are both single-threaded, expiring the lease with a direct SQL UPDATE and calling `claim_job()` twice from one thread. That is the Phase-10 vacuity pattern this milestone exists to not repeat.

---

## Red-run evidence mechanism

### Q1 — Form of the evidence

| Option | Description | Selected |
|--------|-------------|----------|
| Pasted artifact + target guard | Mutation diff, pasted red, commit SHA, byte-identical-revert — executed live in-phase, never deferred. Plus a CI guard that each mutation target still exists as live code | ✓ |
| Automated mutation harness | CI applies each mutation, asserts red, reverts, asserts green. Never decays; real machinery, and the patches themselves rot | |
| Both | Most thorough; heaviest option in a phase that also has an ops page, and the two can disagree | |

**User's choice:** Pasted artifact + target guard
**Notes:** Framed against the user's own history — a mutation "deferred to the CI gate" ran nowhere, because that gate runs tests, not mutations.

### Q2 — Guaranteeing the mutation lands on live code

| Option | Description | Selected |
|--------|-------------|----------|
| AST target + named assertion | Guard resolves each target as a real AST node (BOUND-01 / 19-12 detector pattern) so a docstring copy can't satisfy it; artifact names the exact assertion expected to fail. Catches both failure modes | ✓ |
| Named assertion only | Cheapest; catches "red for the wrong reason" but leaves target selection a discipline, not a mechanism | |
| AST target only | Prevents the docstring landing; an unrelated red still reads as a successful falsification | |

**User's choice:** AST target + named assertion
**Notes:** Directly addresses the recorded incident where a mutation hit a docstring copy of the SQL string.

### Q3 — Where the evidence lives

| Option | Description | Selected |
|--------|-------------|----------|
| docs/ + README link | `docs/DURABILITY-PROOFS.md`, recruiter-reachable, linked from the recruiter-first README; phase SUMMARY/VERIFICATION cite it rather than duplicate it | ✓ |
| Planning artifact only | 21-PROOFS.md in the phase directory, consistent with Phase 16. The milestone's best story stays invisible | |
| Both | Complete audit trail plus visibility; two places to sync and the condensed one goes stale | |

**User's choice:** docs/ + README link
**Notes:** Primary audience is hiring managers; "here is the mutation that breaks it, here is the red output" is the milestone's most differentiating artifact.

### Q4 — Whether the doc carries the limitations

| Option | Description | Selected |
|--------|-------------|----------|
| Claims + limits, same doc | Each proof states its claim; a companion section states the accepted residuals (Two Generals, best-effort ~30 min, retrigger sends a legitimate second email) | ✓ |
| Proofs only; limits in README | README already carries PUMP-02's best-effort wording; a proofs reader can over-read the claims without the boundary next to them | |
| Claim table only | Most scannable; a table can flatten nuance the residuals need | |

**User's choice:** Claims + limits, same doc
**Notes:** REQUIREMENTS states publishing the limitation honestly "is itself the differentiator."

---

## Ops view shape & contents

### Q1 — Where the ops view lives

| Option | Description | Selected |
|--------|-------------|----------|
| New /ops page + nav item | /runs stays the payroll surface, /ops the transport surface — rendering invariant J-1 in the information architecture | ✓ |
| Queue-health strip on /runs | No new nav; mixes transport state into the payroll surface, undoing the secondary-indicator discipline of Phases 18/19 | |
| JSON endpoint only | Cheapest and machine-readable; fails criterion 6's explicit "on one page" | |

**User's choice:** New /ops page + nav item

### Q2 — Dead-letter list actionability

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only, links to run detail | Retrigger already lives on run detail with its validation and new-generation semantics. One recovery affordance; /ops stays a pure read per D-18 | ✓ |
| Inline retrigger button | Faster during an incident; duplicates Retrigger's affordance and validation, which then drift | |
| Read-only, no links | Simplest; an operator who spots a dead job has to hunt for the run by hand | |

**User's choice:** Read-only, links to run detail

### Q3 — Refresh behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Manual refresh only | Static read with an "as of" stamp. A polling tab holds the Render instance awake, burning the same 750-instance-hour budget the pump cadence was sized against | ✓ |
| Reuse the 2s/120s poller | No new pattern and self-terminating; still 60 requests per visit for data that moves on a 30-minute cadence | |
| Slow poll (e.g. 60s) | Cadence-matched; a third polling cadence in the codebase, and an abandoned tab still holds the instance awake | |

**User's choice:** Manual refresh only

### Q4 — Metric presentation

| Option | Description | Selected |
|--------|-------------|----------|
| Numbers vs. their bounds | Oldest-pending age against documented worst-case recovery latency, attempts against MAX_ATTEMPTS, depth split pending/leased. "Healthy" is a comparison the page performs | ✓ |
| Raw numbers only | Simplest; "41 minutes" means nothing without knowing the cadence — the vibe the requirement kills | |
| Traffic-light status | Most scannable; hides the numbers and a hardcoded threshold becomes a lie when the cadence changes | |

**User's choice:** Numbers vs. their bounds

---

## The swallowing alarm

### Q1 — What the alarm actually detects

| Option | Description | Selected |
|--------|-------------|----------|
| Errors the queue can't account for | Runs in `error` with no corresponding terminal/dead job settlement — work that failed without the transport recording it failed. Silent on legitimate terminal failures | ✓ |
| Literal ratio as written | Faithful to REQUIREMENTS; fires on every correctly-handled terminal failure, training the operator to ignore the milestone's one alarm | |
| Error runs with no job at all | Narrowest and unambiguous; misses the likelier variant where a job ran, reported done, and left the run errored | |

**User's choice:** Errors the queue can't account for
**Notes:** Raised as a requirement defect before the question — Phase 18's D-16 ("an explicit terminal result settles the job as `done` and the run as `error`") makes REQUIREMENTS' literal predicate the normal shape of a correctly-classified terminal failure. Recorded in CONTEXT.md as a documented requirement correction.

### Q2 — Where the alarm fires

| Option | Description | Selected |
|--------|-------------|----------|
| Page banner + cron-checkable | /ops renders the banner AND a health endpoint returns non-200 while the condition holds, wired as a `curl -f` step in pump.yml — the same pattern Phase 17 carried forward for /health/schema | ✓ |
| Page banner only | Meets criterion 6 literally; the swallowing bug is by definition the failure nobody noticed, so a banner alone doesn't change that | |
| Cron-checkable only | Machine-reliable; fails criterion 6's requirement that the alarm be surfaced on the page | |

**User's choice:** Page banner + cron-checkable

### Q3 — Sequencing within pump.yml

| Option | Description | Selected |
|--------|-------------|----------|
| After the drain, always-run | Alarm step last, drain executes regardless. An alarm ahead of the drain turns "something went wrong" into "and now nothing recovers" | ✓ |
| First step, fail fast | Fastest signal; the exact suppression footgun — the run that most needs the pump is the one whose alarm stops it | |
| Its own workflow | Cleanest isolation; a second cron against the same 750-hour budget plus another workflow to keep past the 60-quiet-day auto-disable | |

**User's choice:** After the drain, always-run
**Notes:** This repo has already been bitten once by a `pump.yml` `if:`-guard gap that code review caught.

### Q4 — How the alarm clears

| Option | Description | Selected |
|--------|-------------|----------|
| Clears when the condition clears | Purely derived; no acknowledge state, no mute table, nothing to forget to un-mute | ✓ |
| Operator acknowledgement | Useful for known-and-accepted conditions; new persisted state, and a muted alarm is how a swallowing bug returns unnoticed | |
| Auto-clear after a window | Keeps the cron from staying red; hides a live pathology on a timer, strictly worse than a persistent red | |

**User's choice:** Clears when the condition clears

---

## Claude's Discretion

The user made every presented decision explicitly; no question was answered with "you
decide." Discretion recorded in CONTEXT.md is scoped implementation latitude beneath the
locked decisions:

- Marker spelling/registration and the exact `--collect-only` assertion shape.
- The mechanism forcing PROOF-03's settlement transaction to fail after provider-accept.
- The concrete falsifying mutation per proof (constrained by each roadmap criterion's named
  target and by the AST-target guard).
- The AST-guard implementation for mutation targets.
- SQL composition, repository boundaries, and projection shapes for `/ops` metrics and the
  alarm predicate.
- `/ops` layout, styling, and attempts-distribution rendering.
- Which health route carries the alarm and its exact non-200 status.

## Deferred Ideas

- The 10 dormant `integration`-marked test modules — pre-existing gap, already in the
  ROADMAP backlog, explicitly not Phase 21.
- An automated mutation harness re-proving non-vacuity every CI run — considered and
  rejected here; reasonable future candidate.
- Operator authentication for `/ops` and the dashboard — explicit v4 out-of-scope.
- Per-tenant fairness lanes, priority lanes, adaptive backpressure, circuit breakers, a
  throughput/load chart — v4 out-of-scope.
- The three pending polish todos (frontend progressive enhancement, paystub YTD columns,
  eval-chart restyle) — reviewed, none folded.
