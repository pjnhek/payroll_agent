# Phase 21: Durability Proofs & Ops View - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 21 turns v4's durability and exactly-once claims from *passing tests* into
*demonstrated-able-to-fail evidence*, and gives an operator one page where "the queue is
healthy" is a checkable fact rather than a vibe.

Two deliverables:

1. **Four durability proofs** (PROOF-01 kill-worker-mid-run, PROOF-02 same-Svix
   redelivery, PROOF-03 crash between Resend-accept and the local `sent` commit,
   PROOF-04 expired-lease reclaim with the zombie's `mark_failed`/reschedule fenced),
   each carrying an identity, each running in CI against a real Postgres (PROOF-05), and
   each shipping with a live-executed falsifying mutation and its pasted red run.
2. **An ops view** (OPS-01) surfacing queue depth, oldest-pending age, attempts
   distribution, and the dead-letter list, plus the alarm for the swallowing bug.

**This is an audit-and-close phase, not a build-from-scratch phase.** Scouting found that
three of the four proofs already exist as working real-Postgres tests, and that PROOF-05's
premise is stale (see Requirement corrections below). The phase's real work is: give the
proofs identity and traceability, close the falsification half of each roadmap criterion,
and build the one genuinely new surface (`/ops`).

**Out of scope:**

- The **10 dormant `integration`-marked test modules** that never execute in CI. This is a
  pre-existing gap explicitly tracked in the ROADMAP backlog and deliberately not fixed by
  Phase 16's D-14. Collecting them would wake 10 live-DB modules against the shared CI
  Postgres with a destructive module-scope reset (`tests/conftest.py:74-93`). Phase 21 must
  not smuggle this in.
- **Operator authentication** — an explicit v4 out-of-scope exclusion. `/ops` is
  unauthenticated like every other dashboard route; this remains the known/accepted gap.
- **New payroll statuses, new business capabilities, throughput/load charts**, and the
  three pending polish todos (see Reviewed Todos).

**Requirements:** PROOF-01, PROOF-02, PROOF-03, PROOF-04, PROOF-05, OPS-01.

### Requirement corrections discovered during discussion

Downstream agents must plan against these corrections, not the stale text:

- **PROOF-05's premise is stale.** REQUIREMENTS says `concurrency-proof.yml` "hard-codes
  its test files by name," so a durability proof landed outside that line never runs.
  Phase 16's D-14 already added a second, **marker-selected** step (`-m queueproof`) that
  collects any test carrying `@pytest.mark.queueproof` from anywhere under `tests/` with
  zero workflow edits; 63 tests collect there today. PROOF-05 is therefore not "generalize
  the workflow" work. Its remaining substance is the residual gap the workflow documents
  in its own comment and does **not** close: *a typo'd marker on one newly-added test
  while the other queueproof tests still pass — the log still says "N passed" and the new
  proof silently never ran.* D-02 below closes exactly that.
- **OPS-01's alarm predicate is broken as written.** REQUIREMENTS specifies the alarm as
  *"job success ≈100% while `payroll_runs.status='error'` > 0."* Phase 18's **D-16**
  ("An explicit terminal result settles the job as `done` and the run as `error`") makes
  that the **normal, correct** shape of a legitimately-classified terminal failure. The
  literal predicate would fire on every correctly-handled terminal failure. D-11 below
  replaces it with the predicate that actually isolates the pathology.

</domain>

<decisions>
## Implementation Decisions

### Proof identity & consolidation

- **D-01: Promote in place; do not rewrite working proofs.** Three of the four proofs
  already exist as passing real-Postgres tests. Audit each against its **exact** roadmap
  success criterion, strengthen it only where the criterion is unmet, and tag it with its
  PROOF id. No proof gets duplicated into a new canonical file — two copies of a proof
  drift apart silently. Current mapping to audit:
  - PROOF-01 → `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease`
  - PROOF-02 → `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run`
  - PROOF-03 → **no clear existing coverage.** Phase 20 shipped provider-handoff *fence
    races*, not a crash between Resend-accept and the `sent` commit. Treat as new work.
  - PROOF-04 → `tests/test_queue_durability.py::test_expired_lease_is_reclaimed` (:2224)
    and `::test_zombie_is_fenced_on_BOTH_complete_and_fail` (:2262). **Both are
    single-threaded** — they expire the lease with a direct SQL `UPDATE` and call
    `claim_job()` twice from one thread. Criterion 4 demands a *genuinely concurrent
    (real OS thread)* second worker. See D-04.

- **D-02: Identity is a marker argument; the completeness check is a CI collect gate.**
  Each proof carries `@pytest.mark.proof("PROOF-0N")` (alongside its existing
  `queueproof`/`integration` markers). A step in `.github/workflows/concurrency-proof.yml`
  runs a `--collect-only` selection and **reds the build unless each of PROOF-01..04
  appears exactly once**. A marker argument survives a function rename and a file move,
  which a naming convention does not; and the check sits at the *selection* layer, which
  is precisely where the documented typo gap lives (execution-layer "N passed" guards
  cannot see it).

- **D-03: PROOF-03 is an injected-seam failure against a real Postgres, not a hard kill.**
  Real DB; a gateway double returns provider-accept; the settlement transaction is then
  forced to fail before commit; a second attempt replays. **The proof's teeth are the
  assertions, not the crash mechanism:** the persisted `message_id` must be
  **byte-identical** across both attempts, and **exactly one** provider call must have
  been made, carrying the **same `Idempotency-Key`**. (REQUIREMENTS' warning that a fake
  gateway makes this vacuous applies to a version that omits the byte-identical assertion
  — not to the injection technique.) A hard connection kill was rejected: it proves the
  same invariant while being nondeterministic under a shared CI Postgres, and a flaky
  proof is a proof that eventually gets quarantined.

- **D-04: PROOF-04 must genuinely race, under a `threading.Barrier`, without sleeping.**
  Two real OS threads on separate connections, released by a `threading.Barrier`. Keep
  expiring `leased_until` by direct SQL (no wall-clock sleep, no lowered `LEASE_SECONDS`)
  so the test stays deterministic — but worker B's reclaim and worker A's late
  `complete_job` **and** `fail_job`/reschedule must be driven from their own threads and
  genuinely contend. This follows the established convention (races drive the **sync repo
  seam** under a Barrier, never an HTTP route) that Phase 10's CR-01 taught this repo the
  hard way. Mind the connection-pool budget (`max_size=5`); two threads is well inside it.

### Red-run evidence (non-vacuity)

- **D-05: Evidence is a pasted artifact executed live in-phase, guarded against rot.** For
  each proof, record: the exact mutation diff, the pasted **red** pytest output, the commit
  SHA it ran against, confirmation of a **byte-identical revert**, and the exact command to
  re-run it. **Every mutation must be executed during the phase — never deferred to "the CI
  gate."** A deferred falsifying mutation runs *nowhere*: that gate runs tests, not
  mutations. A full automated mutation harness was rejected as over-engineering here (the
  patches themselves rot, and a no-longer-applying patch becomes another gate to get
  right); the anti-rot job is done by D-06's guard instead.

- **D-06: Mutation targets are AST-resolved, and the artifact names the expected failing
  assertion.** A CI guard resolves each mutation target as a **real AST node**, reusing the
  repo's existing AST-guard pattern (BOUND-01; the Phase 19-12 producer/retired-symbol
  detector), so a **docstring or comment copy can never satisfy it** — the exact trap that
  previously made a real blind spot look like a passing proof. Separately, the artifact must
  name the **specific assertion** expected to fail, so a red arising for an unrelated reason
  is visibly not the falsification. Both halves are required: the AST guard catches a
  mis-targeted mutation, the named assertion catches a right-target/wrong-red.

- **D-07: The evidence lives in `docs/DURABILITY-PROOFS.md`, linked from the README.**
  Recruiter-reachable, not buried in `.planning/`. One section per proof: the claim, the
  mutation, the pasted red, the revert-green, and the re-run command. The phase's
  SUMMARY/VERIFICATION artifacts **cite** this doc rather than duplicating it — one source
  of truth. "Here is the mutation that breaks it, here is the red output" is the single most
  differentiating artifact this milestone produces for the primary audience.

- **D-08: The same doc carries what is NOT guaranteed.** Each proof states the exact claim
  it establishes; a companion section states the accepted residuals verbatim in spirit:
  (a) **exactly-once delivery is not achievable** — the Two Generals problem, not a library
  gap; (b) recovery is **best-effort within ~30 minutes** — GitHub Actions cron can be
  delayed and auto-disables after 60 quiet days, with operator retry as the stated fallback;
  (c) **an operator retrigger can legitimately send a second email** by design (it bumps
  `reply_epoch`), which is why the claim is *"at most once per approved run, per epoch"*
  rather than a flat "never twice." Publishing the boundary next to the claim is itself the
  differentiator.

### Ops view (OPS-01)

- **D-09: A new `/ops` page and a fourth nav item** (`Pyrl | Runs | Eval | Ops`). `/runs`
  stays the payroll surface; `/ops` becomes the transport surface. This renders
  **invariant J-1** (jobs = transport state, `payroll_runs.status` = the sole business
  state machine) in the information architecture, not only in the code — and Phases 18/19
  deliberately kept queue state a *secondary* indicator on `/runs`, which a health strip
  there would undo.

- **D-10: The dead-letter list is read-only; each row links to its run detail.** Retrigger
  already lives on run detail with its validation, new-job-generation semantics
  (Phase 18 D-10), and epoch handling. One recovery affordance in the codebase, not two.
  `/ops` stays a pure read, consistent with Phase 18's D-18 (`GET /runs` is a read, not an
  accidental cron). The ops page's job is to make a problem **findable**; run detail's job
  is to act on it.

- **D-11: Manual refresh only, with a visible "as of &lt;timestamp&gt;" stamp.** No polling.
  On Render free, inbound HTTP is exactly what keeps the instance awake — a tab left open on
  a polling ops page would hold the instance up indefinitely, burning the same
  **750-instance-hour/month** budget the 30-minute pump cadence was deliberately sized
  against. The underlying data moves on that cadence anyway.

- **D-12: Every metric renders beside the bound that makes it meaningful.** Oldest-pending
  age against the documented worst-case recovery latency (derived from the 30-minute pump
  cadence, already documented in the README per PUMP-02); attempts distribution against
  `MAX_ATTEMPTS`; depth split `pending` vs. `leased`. "Healthy" becomes a comparison the
  page performs, not arithmetic the operator does from memory. A traffic-light abstraction
  was rejected — a threshold hardcoded today becomes a lie when the cadence changes.

### The swallowing alarm

- **D-13: The alarm detects errors the queue cannot account for.** Fire on runs in `error`
  with **no corresponding terminal/dead job settlement** — an error state no job ever
  claimed responsibility for. That is the actual swallowing bug: work that failed without
  the transport recording that it failed. It uses settlement facts Phase 18 already
  persists, fires on the pathology, and stays **silent on every legitimate terminal
  failure**. This deliberately supersedes REQUIREMENTS' literal ratio predicate (see
  Requirement corrections in `<domain>`), which D-16 made a false-positive generator — and
  an alarm that cries wolf is worse than no alarm, because it trains the operator to ignore
  the one alarm this milestone ships.

- **D-14: The alarm fires in two places — an `/ops` banner and a cron-checkable endpoint.**
  `/ops` renders the banner (criterion 6 requires it on the page), **and** a health endpoint
  returns non-200 while the condition holds, wired as an additional `curl -f` step in
  `.github/workflows/pump.yml`. This is exactly the pattern Phase 17 insisted on carrying
  forward for `/health/schema` — which STATE.md calls the only monitor that catches a manual
  Supabase edit bypassing deploy-migrate. The swallowing bug is by definition *the failure
  nobody noticed*; a banner on a page you'd only visit if already suspicious does not change
  that.

- **D-15: The alarm check runs AFTER the drain and must not be able to suppress it.** In
  `pump.yml`, the alarm step is last and the drain executes regardless of its result. An
  alarm placed ahead of the drain would turn "something went wrong" into "and now nothing
  recovers" — and this repo has already been bitten once by a `pump.yml` `if:`-guard gap
  that code review caught. **Recovery first, reporting second.** Whatever guard mechanism is
  used, it must be verified to actually run the drain when the alarm is firing.

- **D-16: The alarm is purely derived and clears when the condition clears.** No
  acknowledge action, no mute state, no time-boxed auto-clear. Once the unaccounted-for
  error run is retriggered or settled, the query returns empty and the alarm goes quiet on
  its own. Consistent with this milestone's discipline of not inventing state to mirror
  state that already exists — and a muted alarm is precisely how a swallowing bug returns
  unnoticed.

### the agent's Discretion

- The exact marker spelling and registration for `@pytest.mark.proof(...)` in
  `pyproject.toml`, and the exact shape of the `--collect-only` assertion in
  `concurrency-proof.yml`, provided D-02's rename-survival and exactly-once-per-id
  properties hold.
- The mechanism used to force PROOF-03's settlement transaction to fail after
  provider-accept, provided the byte-identical `message_id`, single-provider-call, and
  identical-`Idempotency-Key` assertions are all present and non-vacuous.
- The concrete falsifying mutation chosen per proof, provided it satisfies the roadmap
  criterion's named target (criterion 1: the lease-reclaim clause **or** the
  attempts-increment; criterion 2: dedup keyed on the RFC `Message-ID` alone; criterion 3:
  the pre-Phase-20 send path; criterion 4: the original claim SQL that cannot reclaim a
  `leased` row) and passes D-06's AST-target guard.
- The AST-guard implementation for mutation targets, provided it follows the existing
  BOUND-01 / 19-12 detector precedent and is itself proven non-vacuous.
- SQL composition, repository function boundaries, and projection shapes for the `/ops`
  metrics and the alarm predicate, provided caller-owned-transaction, fencing, PII-safe
  bounded-projection, and fake-repo pairing conventions are preserved.
- The `/ops` page layout, styling, and the attempts-distribution rendering, provided D-12's
  numbers-beside-bounds property holds and the page stays a pure read.
- Which health route carries the alarm (a new `/health/queue` vs. extending an existing
  one) and its exact non-200 status, provided it does not weaken or conflate the existing
  `/health/live`, `/health/ready`, and `/health/schema` contracts that `pump.yml` already
  depends on.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope and requirements

- `.planning/ROADMAP.md` — Phase 21 goal and its six success criteria; the two
  cross-cutting hazards this milestone must not repeat; the backlog entry recording the
  10 dormant integration modules as out of scope.
- `.planning/REQUIREMENTS.md` — PROOF-01..05 and OPS-01 language, each with its explicit
  "vacuous if…" clause. **Read alongside the Requirement corrections in this file's
  `<domain>` section** — PROOF-05's premise and OPS-01's alarm predicate are both stale.
- `.planning/PROJECT.md` — v4 durable-execution narrative and the recruiter-first audience
  priority that motivates D-07.
- `.planning/STATE.md` — Phase 20 closeout, the accumulated v4 decision log, and the
  pump/keepalive absorption constraints that D-14/D-15 extend.

### Approved durable-execution design

- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — authoritative claim
  wording, the proof model, and the honest-limitation posture D-08 publishes.
- `.planning/research/ARCHITECTURE.md` — queue ownership, fencing, lease semantics, and
  the two-layer dedup argument PROOF-02's falsification depends on.
- `.planning/research/SUMMARY.md` — the adversarial corrections and the non-vacuous-proof
  obligations this phase discharges.
- `.planning/research/PITFALLS.md` — durability, PII, and provider failure modes.

### Upstream phase contracts

- `.planning/phases/16-queue-substrate-unblocked-webhook/16-CONTEXT.md` — queue invariants,
  attempts-at-claim, CAS/fencing rules, and **D-14** (the narrow `queueproof` marker gate
  that makes PROOF-05's premise stale).
- `.planning/phases/17-the-pump/17-CONTEXT.md` — shared `drain_once()`, pump accounting,
  the 30-minute cadence and its 750-instance-hour arithmetic, and the keepalive absorption
  (both `/health/schema` and `/health/ready` checks) that D-14/D-15 must preserve.
- `.planning/phases/18-failure-policy-sweep-deletion/18-CONTEXT.md` — **D-16** (terminal
  result ⇒ job `done` + run `error`), which is why OPS-01's literal alarm predicate is
  wrong; **D-18** (`GET /runs` is side-effect-free), the precedent for D-10; and
  **D-09/D-10** (Retrigger's home and new-generation semantics).
- `.planning/phases/19-webhook-cutover-durable-ingest/19-CONTEXT.md` — **D-15/D-17**
  (queue state is secondary presentation, never a payroll status), the two-layer dedup
  argument, the bounded-polling precedent D-11 declines to reuse, and the PII-safe browser
  boundary.
- `.planning/phases/20-exactly-once-send/20-CONTEXT.md` — the frozen-snapshot / reserved
  `message_id` / `Idempotency-Key` contract that PROOF-03 must assert against.

### Existing implementation and proof surface

- `.github/workflows/concurrency-proof.yml` — **read the comments in full.** The by-name
  `integration` step, the marker-selected `queueproof` step, the skip/passed guards, the
  explicit "STATED GAP THIS GUARD DOES NOT CLOSE" comment (the marker typo — D-02's
  target), and the FORBIDDEN whole-suite `-m integration` collection.
- `.github/workflows/pump.yml` — the 30-minute cron, its `curl -f` steps, and the absorbed
  keepalive checks; D-14 adds a step here and D-15 constrains where.
- `tests/test_queue_durability.py` — the existing durability proof surface (~3100 lines,
  37 `queueproof` markers); `:2224` and `:2262` are PROOF-04's single-threaded incumbents;
  `test_retrigger_survives_worker_crash_mid_lease` is PROOF-01's.
- `tests/test_webhook_dedup_race.py` — PROOF-02's incumbent
  (`test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run`).
- `tests/test_send_idempotency.py` — the reserved/frozen-snapshot and provider-handoff
  guards PROOF-03 builds on.
- `tests/test_queue_config.py` — the existing tests that pin `concurrency-proof.yml`'s
  shape byte-identically; D-02's new step must be added without breaking them.
- `tests/conftest.py` — the `seeded_db` fixture and its `ALLOW_DB_RESET` two-factor guard;
  the destructive module-scope reset at `:74-93` is why the 10 dormant modules stay out.
- `app/db/repo/jobs.py` — `count_open_jobs()` (:575) and `get_run_queue_label()` (:596)
  are the existing queue-projection seam `/ops` extends; `claim_job` (:392),
  `complete_job` (:469), `fail_job` (:491) are PROOF-04's fenced write paths.
- `app/db/repo/job_settlement.py` — the fenced cross-aggregate settlement coordinator whose
  facts D-13's alarm predicate queries.
- `app/routes/pump.py` — the drain route and its truthful counts; the alarm endpoint must
  not conflate with it.
- `app/routes/health.py` — `/health/live`, `/health/ready`, `/health/schema`; the pattern
  D-14's endpoint follows and must not disturb.
- `app/routes/dashboard.py`, `app/routes/runs.py`, `app/routes/templating.py`,
  `app/templates/base.html`, `app/templates/runs_list.html` — the route/nav/template
  patterns `/ops` follows.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `.github/workflows/concurrency-proof.yml`'s **marker-selected `queueproof` step** — any
  test carrying `@pytest.mark.queueproof` already runs against a real Postgres in CI with
  zero workflow edits. 63 tests collect there today. This is the vehicle for all four
  proofs; PROOF-05 needs no new gate, only D-02's completeness check.
- `app/db/repo/jobs.py::count_open_jobs()` and `::get_run_queue_label()` — existing queue
  projections; extend this seam rather than inventing a second queue-metrics API.
- `app/db/repo/job_settlement.py` — the fenced settlement coordinator already records
  which job took terminal responsibility for a run; D-13's predicate is a query over facts
  that already exist, not new bookkeeping.
- The repo's **AST-guard precedent** — BOUND-01 and Phase 19-12's producer/retired-symbol
  detector (itself mutation-proven with synthetic producers). D-06's mutation-target guard
  reuses this pattern rather than grep.
- `tests/conftest.py::seeded_db` and the `threading.Barrier` race helpers already used by
  `test_concurrency_proof.py` and `test_genuine_claim_race_exactly_one_winner` — D-04's
  threading follows these, not a new concurrency idiom.
- README's PUMP-02 cadence/750-hour arithmetic — D-12's bounds are already documented
  constants; the page should render them, not restate them.

### Established Patterns

- **INVARIANT J-1** — `jobs` is transport state only; `payroll_runs.status` is the sole
  business state machine. D-09 extends this into the IA; nothing on `/ops` may become a
  payroll status.
- **Races drive the sync repo seam under a `threading.Barrier`, never an HTTP route.** The
  Phase-10 CR-01 lesson: threads fired at an `async def` route serialize and prove nothing.
- **Side-effect-free reads** — Phase 18's D-18 made `GET /runs` a pure read. `/ops` inherits
  this unconditionally.
- **PII-safe bounded browser projections** — templates receive safe projections; raw
  provider/queue/DB diagnostics never cross the boundary. `jobs.last_error` is already
  bounded and safe; dead-letter rows must stay within that boundary.
- **Fake-repo pairing** — every new facade function must be registered in the fake
  repository patch inventories. Note the known trap: adding a `repo.*` method requires its
  **name string** in **three** hard-coded monkeypatch tuples (`conftest.py` ~:1015 and
  **two** in `test_threading.py` ~:346/~:427); `conftest`'s `hasattr` guard makes a miss
  fail **silently**, letting the real function run against a `FakeCursor` and the write
  vanish. Gate any new repo function against this.
- **A guard proves nothing about what it does not scan.** Every guard added in this phase
  (D-02's collect gate, D-06's AST target check) must be red-proofed *and* have its
  no-false-positive half pinned. Note `git grep -E` silently ignores `\b` — verification
  greps have lied here before.
- **Executed, never deferred** — a falsifying mutation postponed to a later gate runs
  nowhere. Worktrees have no `.env`, so DB-heavy work silently defers live-DB proofs;
  executors need their own throwaway Postgres to actually run these.

### Integration Points

- `pyproject.toml` — register the `proof` marker alongside `queueproof`/`integration`.
- `.github/workflows/concurrency-proof.yml` — add D-02's `--collect-only` completeness step
  without disturbing the byte-identical by-name step that `tests/test_queue_config.py` pins.
- `.github/workflows/pump.yml` — add D-14's alarm step, positioned per D-15 (after the
  drain, drain unconditional).
- `tests/test_queue_durability.py`, `tests/test_webhook_dedup_race.py`,
  `tests/test_send_idempotency.py` — where the four proofs are tagged, strengthened, and
  (PROOF-03) added.
- `app/routes/` — a new `ops.py` router registered in `app/main.py`; a new `/health/*`
  alarm endpoint (or extension) in `app/routes/health.py`.
- `app/db/repo/jobs.py` + `app/db/repo/__init__.py` facade + the fake-repo inventories —
  the `/ops` metric and alarm-predicate queries.
- `app/templates/base.html` (nav) and a new `app/templates/ops.html`;
  `app/static/style.css`.
- `docs/DURABILITY-PROOFS.md` (new) + a README link.

</code_context>

<specifics>
## Specific Ideas

- The proofs' identity is a **marker argument**, not a filename or a test name:
  `@pytest.mark.proof("PROOF-01")`. Rename the function, move the file — the id survives.
- PROOF-03's teeth, stated exactly: **the persisted `message_id` is byte-identical across
  both attempts, exactly one provider call was made, and it carried the same
  `Idempotency-Key`.**
- PROOF-04's fix, stated exactly: **no sleeping, real threads.** Keep expiring
  `leased_until` by direct SQL; race the reclaim and the zombie's `complete_job` *and*
  `fail_job` from separate OS threads under a `threading.Barrier`.
- The mutation discipline, stated as a rule: **run it, don't defer it; resolve the target
  as an AST node, not a string; and name the assertion you expect to see fail.**
- `docs/DURABILITY-PROOFS.md`'s shape per proof: *claim → mutation → pasted red →
  byte-identical revert green → exact re-run command.*
- The alarm is not "errors exist." It is **"an error nobody's job claimed responsibility
  for."**
- The pump ordering rule, in one line: **recovery first, reporting second.**
- `/ops` should read as the transport-side mirror of `/runs` — the same operator, a
  different state machine.

</specifics>

<deferred>
## Deferred Ideas

- **The 10 dormant `integration`-marked test modules** (`test_atomic_persist`,
  `test_claim_status`, `test_dashboard`, `test_gateway`, `test_ingest`, `test_persistence`,
  `test_seed_roundtrip`, `test_stuck_run_recovery`, `test_threading`, and the non-queueproof
  tests in `test_webhook_dedup_race`) — a pre-existing gap needing its own dedicated work:
  inventory and classify each, make it reliable under a shared Postgres (or isolate it),
  then bring it into CI. Already tracked in the ROADMAP backlog. **Explicitly not Phase 21.**
- **An automated mutation harness** that re-proves non-vacuity on every CI run — considered
  and rejected for this phase as over-engineering (D-05). A reasonable future candidate if
  the proof set grows or the evidence artifact is observed rotting.
- **Operator authentication** for `/ops` and the rest of the dashboard — an explicit v4
  out-of-scope exclusion; remains the known/accepted gap.
- **Per-tenant fairness lanes, priority lanes, adaptive backpressure, circuit breakers, a
  throughput/load chart** — v4 out-of-scope; schema-shaped for later.

### Reviewed Todos (not folded)

The user reviewed all three pending polish todos and folded **none** — Phase 21 is the
milestone's evidence phase, and folding UI polish into it dilutes the proof story and
recreates the "secondary items pressure the safety path" dynamic Phase 20 hit.

- `.planning/todos/pending/260623-02-frontend-progressive-enhancement.md` — deferred; the
  `/ops` page should simply not require JS (D-11 makes it a static read anyway), which is
  not the same as taking on the progressive-enhancement todo.
- `.planning/todos/pending/260623-03-paystub-ytd-v2.md` — deferred; unrelated
  payroll-document feature.
- `.planning/todos/pending/260623-04-eval-chart-restyle-v2.md` — deferred; **and likely
  already closed** — Phase 20 shipped an offline SVG using dashboard navy/indigo/neutral
  tokens. Worth verifying and closing the todo rather than carrying it into v5.

</deferred>

---

*Phase: 21-Durability Proofs & Ops View*
*Context gathered: 2026-07-20*
