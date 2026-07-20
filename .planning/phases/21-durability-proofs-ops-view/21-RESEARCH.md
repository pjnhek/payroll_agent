# Phase 21: Durability Proofs & Ops View - Research

**Researched:** 2026-07-20
**Domain:** CI proof engineering (pytest markers, AST-based CI guards, real-Postgres concurrency
tests) + a read-only FastAPI/Jinja2 operator page over existing queue/settlement facts.
**Confidence:** HIGH — this is an audit-and-close phase; nearly every finding below is
`[VERIFIED: live source]` by direct file reads of this repo, not external library research.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01: Promote in place; do not rewrite working proofs.** Current mapping to audit:
  - PROOF-01 → `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease`
  - PROOF-02 → `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run`
  - PROOF-03 → **no clear existing coverage.** Treat as new work.
  - PROOF-04 → `tests/test_queue_durability.py::test_expired_lease_is_reclaimed` (:2224) and
    `::test_zombie_is_fenced_on_BOTH_complete_and_fail` (:2262). **Both are single-threaded.**
- **D-02:** Identity is a marker argument (`@pytest.mark.proof("PROOF-0N")`); the completeness
  check is a CI `--collect-only` gate that reds unless each of PROOF-01..04 appears exactly once.
- **D-03:** PROOF-03 is an injected-seam failure against a real Postgres, not a hard kill. Teeth:
  byte-identical `message_id` across attempts, exactly one provider call, same `Idempotency-Key`.
- **D-04:** PROOF-04 must genuinely race under a `threading.Barrier`, real OS threads, no sleeping.
- **D-05:** Evidence is a pasted artifact executed live in-phase, guarded against rot. Every
  mutation must be executed during the phase — never deferred to "the CI gate."
- **D-06:** Mutation targets are AST-resolved (reusing BOUND-01 / Phase 19-12 pattern), and the
  artifact names the expected failing assertion.
- **D-07:** Evidence lives in `docs/DURABILITY-PROOFS.md`, linked from the README.
- **D-08:** The same doc states what is NOT guaranteed (Two Generals, best-effort ~30min recovery,
  "at most once per approved run, per epoch").
- **D-09:** A new `/ops` page and a fourth nav item (`Pyrl | Runs | Eval | Ops`).
- **D-10:** The dead-letter list is read-only; each row links to its run detail.
- **D-11:** Manual refresh only, with a visible "as of &lt;timestamp&gt;" stamp. No polling.
- **D-12:** Every metric renders beside the bound that makes it meaningful (oldest-pending age vs.
  30-min pump cadence; attempts vs. `MAX_ATTEMPTS`; depth split pending vs. leased).
- **D-13:** The alarm detects errors the queue cannot account for — runs in `error` with no
  corresponding terminal/dead job settlement.
- **D-14:** The alarm fires in two places — `/ops` banner + a cron-checkable health endpoint wired
  into `pump.yml`'s `curl -f`.
- **D-15:** The alarm check runs AFTER the drain and must not be able to suppress it.
- **D-16:** The alarm is purely derived; no acknowledge/mute/auto-clear state.

### Claude's Discretion

- Exact marker spelling/registration for `@pytest.mark.proof(...)` in `pyproject.toml`, and the
  exact `--collect-only` assertion shape, provided D-02's properties hold.
- The mechanism to force PROOF-03's settlement transaction to fail after provider-accept.
- The concrete falsifying mutation per proof, provided it satisfies the named target and passes
  D-06's AST-target guard.
- The AST-guard implementation for mutation targets, following BOUND-01/19-12 precedent.
- SQL composition, repo function boundaries, projection shapes for `/ops` metrics + alarm
  predicate, preserving caller-owned-transaction, fencing, PII-safe projection, fake-repo pairing.
- `/ops` page layout/styling/attempts-distribution rendering.
- Which health route carries the alarm (new `/health/queue` vs. extending an existing one).

### Deferred Ideas (OUT OF SCOPE)

- The 10 dormant `integration`-marked test modules (ROADMAP backlog item, not Phase 21).
- An automated mutation harness (rejected as over-engineering for this phase).
- Operator authentication for `/ops` (explicit v4 out-of-scope exclusion).
- Per-tenant fairness, priority lanes, adaptive backpressure, circuit breakers, a throughput chart.
- All three pending polish todos (frontend progressive enhancement, paystub YTD, eval-chart
  restyle) — reviewed and explicitly NOT folded into Phase 21.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PROOF-01 | Kill worker mid-run → run completes on next drain; reclaim path + attempts asserted | Incumbent test verified complete and non-vacuous (see Finding 1). Only needs `@pytest.mark.proof("PROOF-01")` + evidence doc entry. |
| PROOF-02 | Redeliver same Svix event → exactly one job/run/email; dedup not keyed on post-fetch data | Incumbent test verified complete (see Finding 2). Only needs marker + evidence doc entry. |
| PROOF-03 | Crash between Resend-accept and `sent` commit → no second email, byte-identical `message_id` | **No incumbent — new test.** Exact injection seam identified (Finding 4): `app/queue/drain.py:247`, `app/db/repo/job_settlement.py::settle_outbound_delivery_job` OK-branch, `finalize_outbound_provider_handoff`. |
| PROOF-04 | Expired lease reclaimed by genuine 2nd OS thread; zombie's `mark_failed`/reschedule fenced too | Incumbent tests exist but ARE single-threaded as CONTEXT.md claims (Finding 3) — must be rewritten under `threading.Barrier`, following `test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released`'s existing barrier idiom in the same file. |
| PROOF-05 | Every proof registered in `concurrency-proof.yml`, runs in CI against real Postgres, none silently skipped | CONTEXT.md's correction confirmed verbatim in live workflow comments (Finding 5) — the residual gap is a same-file typo/rename that the "N passed" log guard cannot catch; D-02's `--collect-only` completeness step closes exactly this. |
| OPS-01 | `/ops` view: queue depth, oldest-pending age, attempts distribution, dead-letter list, swallowing-bug alarm | New router/template; data seam identified (Finding 6/7) — extend `app/db/repo/jobs.py` + query `job_settlement.py`'s facts for the alarm. |
</phase_requirements>

## Summary

Phase 21 is almost entirely an **audit-and-instrument** phase, not new-feature engineering. Live
verification confirms CONTEXT.md's every factual claim: three of four proofs already exist as
working real-Postgres tests (PROOF-01, PROOF-02 fully sound; PROOF-04 present but genuinely
single-threaded); PROOF-05's "hard-coded file list" premise is stale (a marker-selected
`-m queueproof` step already exists and 63 tests already collect there, with a documented residual
gap this phase's D-02 closes); and OPS-01's literal alarm predicate is a false-positive generator
that D-13's "unaccounted-for error" predicate correctly replaces. PROOF-03 is genuinely new work,
and its exact injection seam is now identified down to the line: the settlement transaction that
must be force-failed lives at `app/db/repo/job_settlement.py::settle_outbound_delivery_job` (the
`PipelineOutcome.OK` branch, lines 495-529), invoked from `app/queue/drain.py:247` **outside any
try/except**, so an exception raised there propagates straight out of `drain_once()` — exactly
modeling a worker dying between Resend-accept and the local `sent` commit. Crucially, the
`outbound_provider_handoffs` "one active handoff" fence (`app/db/repo/outbound_handoffs.py`)
already structurally prevents a second provider call while the first handoff's
`owner_leased_until` has not expired, which is the mechanism that will make "exactly one provider
call" true by construction rather than by luck.

Two strong, directly reusable AST-guard precedents exist for D-06 (mutation-target resolution):
`tests/test_bound01_private_imports.py` (walks `app/`, `eval/`, `scripts/` with `ast.parse`,
resolves both `ImportFrom` and attribute-access forms, has a synthetic-fixture red-proof) and
`tests/test_fake_repo_pairing.py` / `tests/test_background_task_cutover.py` (walk source for
retired-symbol definitions/exports, with `_defined_or_exported_names`-style AST introspection and
synthetic-mutation red-proof tests). The fake-repo three-tuple hazard CONTEXT.md warns about is
real but its **exact line numbers have drifted** — see Finding 8. `tests/test_fake_repo_pairing.py`
already exists and is itself the mechanized guard against this exact class of miss (including a
test that asserts there are exactly two monkeypatch tuples in `test_threading.py`) — this phase's
new `/ops` repo functions must be added to `tests/conftest.py`'s `fake_repo` tuple (currently
~96 names, lines 2566-2661) or `test_fake_repo_pairing.py`'s own guard will red.

**Primary recommendation:** Treat this phase as five small, independent promotions/additions
(PROOF-01 marker+doc, PROOF-02 marker+doc, PROOF-04 threading rewrite+marker+doc, PROOF-03 new
test+marker+doc, PROOF-05 collect-gate) plus one net-new read-only page (`/ops` + alarm endpoint),
landing D-02's collect-gate and D-06's AST guard early since every proof's evidence doc entry
depends on both existing and being provably non-vacuous.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Proof identity (marker) | Test/CI | — | Pure pytest metadata; no runtime code path. |
| Proof completeness gate | CI (GitHub Actions) | Test collection | `--collect-only` selection layer, per D-02. |
| Mutation-target AST guard | Test/CI | — | Static analysis over `app/` source, mirrors BOUND-01. |
| PROOF-03 injection seam | API/Backend (queue tier) | Database | `app/queue/drain.py` + `app/db/repo/job_settlement.py`; the fault is injected at the repo-transaction boundary, not the HTTP layer. |
| PROOF-04 concurrency | API/Backend (repo tier) | Database | Real OS threads driving `app.db.repo.claim_job`/`complete_job`/`fail_job` directly — never through an HTTP route (Phase-10 CR-01 lesson). |
| `/ops` metrics | API/Backend (new route + repo query) | Database | `app/routes/ops.py` (new) queries `app/db/repo/jobs.py` + `job_settlement.py`; template renders a browser-safe projection. |
| Dead-letter list | API/Backend | Frontend Server (SSR template) | Read-only projection of `jobs WHERE state='dead'`, linked to `/runs/{id}`. |
| Swallowing alarm | API/Backend (health route) | CDN/cron (GitHub Actions) | Derived query in Postgres; surfaced via both `/ops` (SSR) and a `curl -f`-checkable health endpoint consumed by `pump.yml`. |

## Standard Stack

### Core

No new runtime or dev dependencies. Every primitive this phase needs is already installed and in
production use in this repo:

| Library | Version (installed) | Purpose | Why Standard (for this phase) |
|---------|---------|---------|--------------|
| pytest | (pinned in `pyproject.toml` dev group) | `@pytest.mark.proof(...)`, `--collect-only` gate | Already the test runner; custom marker registration is a one-line `pyproject.toml` addition, same pattern as the existing `queueproof`/`integration`/`live_llm` markers `[VERIFIED: pyproject.toml:40-46]`. |
| `ast` (stdlib) | 3.12 | Mutation-target resolution, retired-symbol detection | Already used by `tests/test_bound01_private_imports.py`, `tests/test_fake_repo_pairing.py`, `tests/test_background_task_cutover.py` `[VERIFIED: live source]`. No new tooling. |
| psycopg3 | pinned | PROOF-03/04 real-Postgres transactions | Already the sole DB driver; same `_conn_ctx`/`conn.transaction()` convention every repo function uses. |
| threading (stdlib) | 3.12 | PROOF-04's genuine 2-thread race | `threading.Barrier` idiom already used in this exact file (`test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released`) and in `tests/test_concurrency_proof.py`. |
| FastAPI + Jinja2 | pinned | `/ops` route + template | Same pattern as `app/routes/dashboard.py` + `app/templates/*.html` — no new route-registration mechanism needed. |
| PyYAML | pinned (used by `tests/test_queue_config.py`) | Any new workflow-YAML-shape pin test | Already a test dependency; reuse rather than hand-parsing YAML text. |

### Supporting

Nothing new. `resend` (already pinned) is the provider client PROOF-03's fake/spy gateway double
mimics — no new mocking library needed; the existing tests in this repo spy via `monkeypatch` on
`gateway.send_reserved_outbound_snapshot`/`resend.Emails.send` directly.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| A pytest marker argument for proof identity (D-02) | A naming convention (`test_PROOF_01_...`) | Rejected in CONTEXT.md: doesn't survive rename/file-move, and can't carry an argument for the completeness check to key off. |
| Injected-seam failure for PROOF-03 (D-03) | A hard connection kill (`conn.close()` mid-transaction) | Rejected in CONTEXT.md: nondeterministic under shared CI Postgres, risks flake-driven quarantine. |
| A full automated mutation-testing harness (e.g. `mutmut`, `cosmic-ray`) | The AST-guard + pasted-red-run pattern (D-05/D-06) | Rejected in CONTEXT.md as over-engineering for 4-5 proofs; the patches themselves rot and a harness becomes its own gate to maintain. |

**Installation:** None required — zero new dependencies for this phase.

**Version verification:** N/A — no new packages. Existing pins (`pytest`, `psycopg[binary,pool]`,
`fastapi`, `jinja2`, `pyyaml`) are unchanged by this phase.

## Package Legitimacy Audit

**Not applicable — this phase installs zero new external packages.** Every tool used (pytest, ast,
threading, psycopg, FastAPI, Jinja2, PyYAML) is already an existing pinned dependency exercised
elsewhere in this codebase, per Finding 0 below. No `package-legitimacy check` run needed.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────── CI (concurrency-proof.yml) ───────────────────────────┐
│                                                                                     │
│  pytest --collect-only -m proof            pytest tests/ -m queueproof -v         │
│  (D-02 completeness gate: each of              │                                  │
│   PROOF-01..04 appears exactly once)           ▼                                  │
│         │                              ┌──────────────────────────────┐          │
│         │                              │ real Postgres (service       │          │
│         └─────────────────────────────▶│ container, ephemeral)        │          │
│                                         └──────────────┬───────────────┘          │
│                                                         │                          │
│  PROOF-01: retrigger → enqueue → claim_job (thread A)  │                          │
│            → simulate crash mid-lease → expire lease   │                          │
│            → drain_once() reclaims → run reaches       │                          │
│            COMPUTED, attempts=2                        │                          │
│                                                         │                          │
│  PROOF-02: 2 threads POST /webhook/inbound (same       │                          │
│            svix-id) → ON CONFLICT DO NOTHING on        │                          │
│            inbound_events → exactly 1 event/job/run    │                          │
│                                                         │                          │
│  PROOF-03 (NEW): handle_send_outbound → gateway spy    │                          │
│            returns OK (provider "accepted") →           │                          │
│            settle_outbound_delivery_job's OK-branch    │                          │
│            transaction force-failed (injected fault)   │                          │
│            → propagates out of drain_once() uncaught   │                          │
│            → reservation stays 'reserved', handoff     │                          │
│            stays active, job stays 'leased'             │                          │
│            → 2nd attempt (same lease/job) blocked by   │                          │
│            the one-active-handoff fence until it        │                          │
│            expires → assert 1 provider call, same       │                          │
│            message_id/Idempotency-Key                   │                          │
│                                                         │                          │
│  PROOF-04: thread A claims job → thread B expires      │                          │
│            lease (direct SQL) → Barrier-released        │                          │
│            threads A (late complete_job AND fail_job)  │                          │
│            and B (reclaim) race genuinely on real OS    │                          │
│            threads/connections                          │                          │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────── pump.yml (30-min cron) ───────────────────────┐
│  curl /internal/pump (drain, unconditional)                          │
│     │                                                                 │
│     ▼ (always(), after drain — D-15)                                 │
│  curl /health/ready  →  curl /health/schema  →  curl <NEW alarm>     │
│                                                   endpoint (D-14)      │
└────────────────────────────────────────────────────────────────────┘

┌──────────────────────────── /ops (D-09) ─────────────────────────────┐
│  Operator (unauthenticated, D-09/known gap) GET /ops (manual refresh) │
│     │                                                                  │
│     ▼                                                                  │
│  app/routes/ops.py (NEW)                                              │
│     ├─ repo.count_open_jobs()               (existing, jobs.py:575)   │
│     ├─ NEW: oldest-pending age query          (jobs.available_at)     │
│     ├─ NEW: attempts distribution query       (jobs.attempts/max)     │
│     ├─ NEW: dead-letter list query            (jobs WHERE state='dead')│
│     └─ NEW: swallowing-bug alarm query        (job_settlement facts)  │
│     │                                                                  │
│     ▼                                                                  │
│  app/templates/ops.html (NEW) — read-only, "as of <ts>" stamp,        │
│  each metric beside its bound (D-12), dead-letter rows link to        │
│  /runs/{id} (D-10)                                                    │
└────────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
app/
├── routes/
│   ├── ops.py              # NEW — GET /ops (SSR read); registered in app/main.py
│   ├── health.py            # extend OR add new route for D-14's alarm endpoint
│   └── pump.py               # unchanged — pump.yml gains a step, not this route
├── db/repo/
│   ├── jobs.py                # extend: oldest-pending / attempts-distribution / dead-letter queries
│   └── job_settlement.py       # extend: swallowing-bug alarm predicate query (D-13)
├── templates/
│   ├── base.html                # add 4th nav item "Ops" (D-09)
│   └── ops.html                 # NEW
tests/
├── test_queue_durability.py       # PROOF-01 marker; PROOF-04 threading rewrite + marker
├── test_webhook_dedup_race.py     # PROOF-02 marker
├── test_send_idempotency.py       # PROOF-03 NEW test + marker
├── test_queue_config.py            # extend: D-02's collect-gate byte-identical pin (mirrors
│                                     existing TestD14NoWideningGuard pattern)
└── test_[ast_guard_name].py         # NEW or extend existing AST-guard file for D-06
.github/workflows/
├── concurrency-proof.yml            # add D-02's --collect-only completeness step
└── pump.yml                          # add D-14's alarm curl step (after drain, per D-15)
docs/
└── DURABILITY-PROOFS.md              # NEW — D-07's evidence doc, linked from README
```

### Pattern 1: Module-level `pytestmark` vs. per-function marker

**What:** `tests/test_queue_durability.py` applies `pytestmark = [pytest.mark.integration,
pytest.mark.queueproof]` at module scope (line 128) — every test in that file already carries
`queueproof`/`integration`. `tests/test_webhook_dedup_race.py` and `tests/test_send_idempotency.py`
instead decorate individual functions with `@pytest.mark.integration` / `@pytest.mark.queueproof`
directly above each test.

**When to use:** D-02's new `@pytest.mark.proof("PROOF-0N")` marker MUST be applied **per-function**
on the exact incumbent test (never at module scope) since exactly one test per PROOF id is
required. `test_retrigger_survives_worker_crash_mid_lease` and the two PROOF-04 tests currently
have NO per-function marker decorator (they inherit `queueproof` from the module-level `pytestmark`
list) — the new `@pytest.mark.proof(...)` decorator must be added directly above each, additive to
whatever markers already apply.

**Example:**
```python
# Source: tests/test_webhook_dedup_race.py:191-193 (existing pattern to extend)
@pytest.mark.integration
@pytest.mark.queueproof
@pytest.mark.proof("PROOF-02")  # ADD — D-02
def test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run(...):
```

### Pattern 2: AST-based mutation-target / retired-symbol guard (D-06 precedent)

**What:** Two live, mutation-proven AST scanners already exist in this repo and are the direct
precedent D-06 should reuse rather than reinvent:

1. `tests/test_bound01_private_imports.py` — walks `app/`, `eval/`, `scripts/` with `ast.parse`,
   resolves both `ast.ImportFrom` and `ast.Attribute` private-name access back to a first-party
   module path, and proves itself with `test_scanner_detects_synthetic_violation` (a synthetic
   fixture string parsed and asserted to trip the detector).
2. `tests/test_background_task_cutover.py` / `tests/test_fake_repo_pairing.py` — walk source text
   + `ast.walk` for `FunctionDef`/`ClassDef`/`Import`/`Assign`/`__all__` names, detecting retired
   symbol reintroduction; each has a `test_..._detects_synthetic_...` proof test that constructs a
   literal string of "bad" source and asserts the detector's helper function (not the full pytest
   test) reports the expected violation — the exact shape D-06's own red-proof-of-the-guard should
   take.

**When to use:** D-06's mutation-target guard should resolve a proof's declared mutation target
(e.g., "the `OR (c.state = 'leased' AND ...)` clause in `claim_job`'s WHERE", stated in the
existing FALSIFYING MUTATIONS docstring block at `tests/test_queue_durability.py:72-90`) as a real
AST node in the named source file — so a docstring/comment copy of that clause elsewhere can never
satisfy the check. Reuse `ast.walk` + node-type/line matching, not `grep`.

**Example:**
```python
# Source: tests/test_fake_repo_pairing.py:55-75 (the reusable node-walking shape)
def _defined_or_exported_names(source: str) -> set[str]:
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        # ... Import/ImportFrom/__all__ handling
    return names
```

### Pattern 3: Real-thread concurrency proof, never through an HTTP route

**What:** Every genuine race in this repo is driven at the **sync repo seam**
(`app.db.repo.claim_job`/`complete_job`/`fail_job`), never through `TestClient` hitting an
`async def` route — because a shared `TestClient` funnels every thread through one ASGI portal, and
N threads posting to a route with no `await` before the DB work execute strictly one at a time
(the Phase-10 CR-01 lesson, restated verbatim in `tests/test_queue_durability.py`'s module
docstring, lines 5-12).

**When to use:** PROOF-04's rewrite. The two incumbent tests
(`test_expired_lease_is_reclaimed`, `test_zombie_is_fenced_on_BOTH_complete_and_fail`) currently
call `repo.claim_job()` twice sequentially **from one thread**, with the lease expired by a direct
SQL `UPDATE` in between — proving the reclaim SQL predicate but not genuine concurrency. The file
already has the exact idiom needed nearby:
`test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released` (lines
~1997-2216) drives two named threads (`worker`, `retrigger`) released by a coordination mechanism,
captures per-thread connection ids, and asserts both threads actually touched different
connections (`worker_connection_ids[0] != retrigger_connection_ids[0]`) — the same
"prove-they-were-actually-concurrent" assertion PROOF-04 needs, adapted to `threading.Barrier`.

**Example:**
```python
# Source: tests/test_queue_durability.py's own docstring (lines 5-12) — the rule, not code
# "Every test below calls app.db.repo.claim_job / complete_job / fail_job / release_leases
#  directly, from genuinely parallel OS threads released simultaneously by a
#  threading.Barrier."
```

### Anti-Patterns to Avoid

- **Hard-killing a connection to prove a crash (PROOF-03):** Explicitly rejected by D-03 — same
  invariant, but nondeterministic under a shared CI Postgres and risks eventual quarantine.
- **Deferring a falsifying mutation to "the CI gate":** The CI gate runs *tests*, not mutations. A
  mutation applied and reverted only in a worktree that never had `.env`/`DATABASE_URL` "passes"
  by never running at all — this exact failure mode has bitten this repo before (see Known repo
  hazards below). Every mutation in this phase's evidence doc must be executed live, in-session,
  against a real Postgres, with the red output pasted before the revert.
- **Widening `concurrency-proof.yml`'s by-name step to whole-suite `-m integration`:** Explicitly
  FORBIDDEN by the workflow's own comment and pinned byte-identically by
  `tests/test_queue_config.py::TestD14NoWideningGuard`. Do not touch that step; only ADD a new step
  for D-02's completeness gate.
- **Adding a new `app/db/repo/*` function without registering it in the fake-repo tuples:** The
  `if hasattr(store, name)` guard in `tests/conftest.py`'s `fake_repo` fixture makes a miss
  *silent* — the real DB-backed function runs against a `FakeCursor` and the write vanishes. Any
  new `/ops`-supporting repo function used by a hermetic test path must be added to the tuple at
  `tests/conftest.py:2566-2661`, or `test_fake_repo_pairing.py`'s own guard test will red first
  (which is the intended outcome — treat that red as confirmation the new function needs pairing).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Mutation-target resolution (D-06) | A new grep-based or regex-based "does the mutation exist" checker | The `ast.parse`/`ast.walk` pattern already proven in `test_bound01_private_imports.py` and `test_fake_repo_pairing.py` | `git grep -E` has already produced a false-clean result in this repo (documented hazard — `\b` is silently ignored); an AST walk cannot be fooled by a docstring/comment copy the way a text search can. |
| Proof completeness gate (D-02) | A hand-rolled counting script outside pytest | `pytest --collect-only -m proof -q` piped through a count/uniqueness check, mirroring the existing `grep -qE '[0-9]+ (skipped|passed)'` guard idiom already in `concurrency-proof.yml` | The workflow already has a proven idiom for "parse pytest's own output and red on the wrong shape" (lines 93-104, 150-161) — extend it, don't invent a second mechanism. |
| Genuine-concurrency proof harness (PROOF-04) | A new threading/barrier helper module | The `threading.Barrier` + named-thread + connection-id-capture idiom already present in the SAME file (`test_provider_handoff_race_control_observes_stale_gateway_when_fence_is_released`) | Zero new abstraction; the file already has the exact pattern this phase needs, one screen away from the tests being rewritten. |
| Queue health metrics (OPS-01) | A metrics/observability library (Prometheus client, StatsD, etc.) | Plain SQL `SELECT` queries in `app/db/repo/jobs.py`, same convention as `count_open_jobs()`/`get_run_queue_label()` | Explicitly out of scope per REQUIREMENTS.md ("Autoscaling, distributed tracing, a metrics stack... It would scale between 2 and 2"). A handful of read-only queries over a 5-connection-budget Postgres needs no metrics stack. |

**Key insight:** Every "don't hand-roll" item in this phase already has a live, working precedent
in the same repo — this phase is disciplined reuse, not new-pattern invention. The main planning
risk is NOT choosing the wrong tool; it is failing to notice an existing pattern one file away and
duplicating it slightly differently.

## Common Pitfalls

### Pitfall 1: A deferred mutation runs nowhere

**What goes wrong:** A falsifying mutation applied in a git worktree (created by a parallel
executor) has no `.env`/`DATABASE_URL`, so the live-DB test silently skips (`_SKIP_LIVE_DB` /
module-level `if not os.environ.get("DATABASE_URL"): pytest.skip(...)` guards exist throughout
these test files) — the mutation "ran," the test "passed" (by skipping), and the evidence doc gets
a fabricated-looking green/red pair that never actually executed.

**Why it happens:** This repo's own memory records this exact failure: "a falsifying mutation
'deferred to the CI gate' runs NOWHERE: that gate runs tests, not mutations" — and it has already
cost a prior phase 6 of 9 deferred mutations.

**How to avoid:** Every mutation in this phase must be applied and run in a session/executor with a
real `DATABASE_URL` (e.g. `ALLOW_DB_RESET=1 DATABASE_URL=postgresql://... uv run pytest
tests/test_queue_durability.py::test_name -v`) — not scheduled for "whenever CI runs next." Give
each executor its own throwaway Postgres if running in parallel worktrees.

**Warning signs:** `pytest -rs` output showing `SKIPPED` instead of `PASSED`/`FAILED` for the
targeted test; the evidence doc's "red run" paste shows a skip reason instead of an `AssertionError`
or `psycopg` exception.

### Pitfall 2: A guard that never scans what it claims to scan

**What goes wrong:** A CI guard (D-02's collect-gate, D-06's AST guard) is written, passes today,
but never actually exercises its failure path — so it looks like protection while providing none.

**Why it happens:** This repo has shipped this class of bug 4 separate times in one prior phase
(guard-scope-is-invisible-from-green). `git grep -E` silently ignores `\b` — a verification grep
has already lied in this repo once.

**How to avoid:** Every new guard in this phase (D-02's completeness step, D-06's AST guard) needs
BOTH halves proven: a synthetic-mutation test that proves the guard reds on the exact failure it
claims to catch (mirror `test_scanner_detects_synthetic_violation` /
`test_cutover_guard_detects_process_local_producer_mutation` /
`test_durable_recovery_pairing_guard_detects_one_unpaired_facade_method` — three live examples of
this exact "prove the detector, not just its output" pattern), AND a no-false-positive pin against
the current, unmutated repo state.

**Warning signs:** A guard test file with only a "the guard passes on real source" assertion and no
"the guard reds on a synthetic bad case" assertion.

### Pitfall 3: PROOF-03's fake gateway making the proof vacuous

**What goes wrong:** REQUIREMENTS.md explicitly warns: "Vacuous if it passes against a fake gateway
while SEND-01 is unfixed." A test that spies/fakes the Resend call without asserting the
byte-identical `message_id` (or without asserting exactly one call was made with the same
`Idempotency-Key`) would pass even against the pre-SEND-01 bug this phase's proof exists to catch.

**Why it happens:** SEND-01/SEND-02/SEND-03 are already shipped (Phase 20), so a naive "does it
send successfully" test cannot distinguish "the fix works" from "the fix was never load-bearing for
this scenario."

**How to avoid:** D-03's assertions are the whole proof — assert `message_id` (read via
`load_outbound_snapshot`/`get_outbound_message_id` or equivalent) is identical before and after the
forced settlement failure and any subsequent retry attempt; assert the gateway double's call count
is exactly 1 (or, if the retry legitimately reaches the provider seam, that both calls carried the
identical `idempotency_key` argument — verified live at `app/email/gateway.py:167`,
`resend.Emails.send(send_params, {"idempotency_key": message_id})`, where `message_id` is the
snapshot's frozen field, not freshly minted).

**Warning signs:** A test that only asserts `response.status_code == 200` or "no exception raised"
on the retry, without inspecting the persisted `message_id` or the spy's call arguments.

### Pitfall 4: The alarm firing on every legitimate terminal failure (the stale OPS-01 predicate)

**What goes wrong:** Implementing REQUIREMENTS.md's literal text — "job success ≈100% while
`status='error' > 0`" — as written would fire on every correctly-handled terminal failure, because
Phase 18's D-16 makes "job `done` + run `error`" the **normal, correct** shape of a terminal
failure the queue *did* account for.

**Why it happens:** REQUIREMENTS.md predates Phase 18's D-16 decision; CONTEXT.md's D-13 correction
supersedes it, but a planner working only from REQUIREMENTS.md text (not CONTEXT.md) would
reintroduce the false-positive predicate.

**How to avoid:** Implement D-13's actual predicate: runs in `error` status with **no**
corresponding terminal/dead job settlement — i.e., an error state no job ever took responsibility
for. This is a query over facts `app/db/repo/job_settlement.py` already persists (the module that
records which job took terminal responsibility for a run), not new bookkeeping. Verify against live
D-16 settlement code before finalizing the exact JOIN/anti-join shape (the settlement facts live in
`job_settlement.py`, not in `payroll_runs` alone).

**Warning signs:** An alarm query written directly against `payroll_runs.status = 'error'` with no
join/anti-join into `jobs`/settlement facts.

### Pitfall 5: The pump ordering hazard — alarm suppressing the drain

**What goes wrong:** If the new D-14 alarm step is placed BEFORE the drain step in `pump.yml`, or
uses an `if:` guard that could short-circuit later steps, a firing alarm could prevent recovery from
running at all — "something went wrong" becomes "and now nothing recovers."

**Why it happens:** This repo has already been bitten once by a `pump.yml` `if:`-guard gap that code
review caught (documented in canonical refs). The existing `pump.yml` already uses `if: ${{ always()
}}` on its two health-check steps specifically so an earlier RED step cannot suppress them
`[VERIFIED: .github/workflows/pump.yml:99-102, 116-118]`.

**How to avoid:** Add D-14's alarm step LAST, and give it the same `if: ${{ always() }}` the existing
health steps use, so it runs regardless of the drain step's outcome — never gating the drain itself
on the alarm.

**Warning signs:** A new step in `pump.yml` positioned before "Drain due jobs via the authenticated
pump," or a drain step that gained a new `if:` condition referencing the alarm.

## Code Examples

### The exact PROOF-03 injection point

```python
# Source: app/queue/drain.py:241-255 (VERIFIED live source)
# The success branch calls settlement OUTSIDE any try/except — an exception raised
# inside repo.settle_outbound_delivery_job here propagates straight out of
# drain_once(), uncaught. This is the crash-simulation seam.
else:
    if job.kind is JobKind.SEND_OUTBOUND:
        settled = repo.settle_outbound_delivery_job(job, result)   # <-- inject fault here
    else:
        settled = repo.settle_pipeline_job(
            job, result, backoff_seconds=backoff_seconds(job.attempts),
        )
    outcome = _map_settlement_outcome(settled)
    lease_settled = _lease_is_settled(job_kind=job.kind, outcome=settled)
```

```python
# Source: app/db/repo/job_settlement.py:495-529 (VERIFIED live source)
# The OK branch — ALL of these writes are inside ONE transaction opened by
# settle_outbound_delivery_job's own `with _conn_ctx(conn) as (c, owns), c.transaction()`.
# Any exception here rolls back everything: the reservation stays 'reserved', the
# email_messages row stays un-sent, the job stays 'leased', and (critically) the
# outbound_provider_handoffs row stays active/un-released.
if result.outcome is PipelineOutcome.OK:
    if not finalize_outbound_provider_handoff(authorization, conn=c):   # <-- or here
        raise RuntimeError("locked delivery success lost its provider handoff")
    _append_delivery_attempt(c, snapshot_id=snapshot_id, attempt_state="sent", ...)
    sent = c.execute("UPDATE email_messages SET send_state = 'sent' ...").fetchone()
    ...
```

```python
# Source: app/db/repo/outbound_handoffs.py:311-337 (VERIFIED live source)
# The "one active handoff" fence — this is WHY exactly one provider call is
# structurally enforceable: a second authorize attempt for the same run, while the
# first handoff's owner_leased_until has not expired, is REFUSED before it ever
# reaches gateway.send_reserved_outbound_snapshot.
if owner_token == job.lease_token:
    return _authorization(...)          # same job/lease re-authorizing: OK
if not owner_expired:
    return ProviderHandoffActive("active_handoff_unexpired", handoff_id)   # BLOCKED
```

### The existing marker + collect-gate idiom to extend for D-02

```yaml
# Source: .github/workflows/concurrency-proof.yml:150-161 (VERIFIED live source)
# The existing guard idiom D-02's new step should mirror: parse pytest's own log
# output for a specific pattern, red the build if absent.
run: |
  set -o pipefail
  uv run pytest tests/ -m queueproof -v -rs 2>&1 | tee pytest-queueproof.log
  if grep -qE '[0-9]+ skipped' pytest-queueproof.log; then
    echo "A queue durability proof was skipped instead of executed." >&2
    exit 1
  fi
  if ! grep -qE '[0-9]+ passed' pytest-queueproof.log; then
    echo "No queueproof test reported as passed." >&2
    exit 1
  fi
# D-02's NEW step should instead assert, via --collect-only, that each of
# PROOF-01..04 (the marker ARGUMENT, not the marker name) appears exactly once —
# e.g. `pytest tests/ -m proof --collect-only -q` parsed for 4 distinct IDs.
```

## State of the Art

| Old Approach (pre-Phase-21) | Current/Target Approach | When Changed | Impact |
|--------------------------|--------------------------|---------------|--------|
| Proofs identified by filename/test-name convention | `@pytest.mark.proof("PROOF-0N")` marker argument | This phase (D-02) | Survives rename/file-move; enables a `--collect-only` completeness assertion. |
| `concurrency-proof.yml`'s single by-name step (pre-Phase-16) | Marker-selected `-m queueproof` step, zero-edit for new proofs | Phase 16 (D-14, already shipped) | PROOF-05's REQUIREMENTS-stated premise ("hard-codes test files by name") is stale; this phase's real PROOF-05 work is the narrower completeness gate, not workflow generalization. |
| REQUIREMENTS.md's literal OPS-01 alarm predicate (`success ≈100% while error>0`) | D-13's "error with no corresponding terminal/dead job settlement" predicate | Phase 18 (D-16) made the literal predicate wrong; this phase (D-13) supersedes it | Prevents a false-positive-generating alarm that would train the operator to ignore it. |
| PROOF-04's single-threaded lease-expiry simulation | Genuine 2-thread `threading.Barrier` race, following the existing provider-handoff-race idiom in the same file | This phase (D-04) | Closes the exact vacuous-proof class this repo has already shipped once (Phase 10, v2). |

**Deprecated/outdated:** REQUIREMENTS.md's PROOF-05 and OPS-01 literal text — both are explicitly
flagged stale by CONTEXT.md and must not be implemented as literally written; plan against the
corrections in `<domain>`/D-13, not the checklist text.

## Runtime State Inventory

Not applicable — this phase is not a rename/refactor/migration phase. No renamed strings, no
data-migration concerns.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | PROOF-03's exact concrete injection technique (which specific line inside the OK-branch to monkeypatch/fault-inject) is left to the executor's discretion per CONTEXT.md; this research identifies the *seam* (the transaction boundary) but not the final chosen fault-injection call. | Code Examples / Finding 4 | Low — CONTEXT.md explicitly delegates this to Claude's discretion; the seam identification itself is verified against live source, so the risk is only in *which* function within that already-confirmed transaction gets the injected fault. |
| A2 | The exact SQL shape for D-13's "no corresponding terminal/dead job settlement" alarm predicate (the precise JOIN/anti-join against `job_settlement.py`'s facts) has not been fully designed — only the source tables/functions have been located. | Pitfall 4 / Standard Stack | Medium — an imprecise predicate could reintroduce a narrower false-positive/false-negative; the planner must design this query against `job_settlement.py`'s live settlement-outcome writes, not assume a shape. |
| A3 | Which health route carries D-14's alarm (`/health/queue` new vs. extending `/health/schema` or `/health/ready`) is undetermined — left to Claude's discretion per CONTEXT.md, constrained only to not weaken the 3 existing health contracts. | Architecture Patterns | Low — explicitly a discretion item; existing 3 routes were read and their contracts documented (Finding 6) so the constraint is verifiable either way. |

**None of these assumptions concern package identity, external service behavior, or anything
requiring user reconfirmation before planning** — all three are implementation-shape decisions
CONTEXT.md already delegates to the planner/executor.

## Open Questions

1. **What is the precise anti-join shape for D-13's alarm?**
   - What we know: `app/db/repo/job_settlement.py` has `SettlementOutcome` (DONE, RETRIED, LOST_LEASE,
     INVALID_CONTEXT, etc.) and dedicated functions (`settle_pipeline_job`, `settle_background_terminal`,
     `settle_infrastructure_failure`, `reap_expired_final_attempt`) that write terminal outcomes; the
     `error` run status is set via `_set_run_error` (job_settlement.py:616) and elsewhere.
   - What's unclear: whether "no corresponding terminal/dead job settlement" is best expressed as
     "no `jobs` row for this `run_id` reached `state IN ('done','dead')` at/after the run's
     `error`-transition timestamp" or via a more structured settlement-log table. No settlement
     *log* table was found in this pass — the settlement functions write directly to `jobs` and
     `payroll_runs`, so the predicate likely has to correlate `payroll_runs.status='error'` timing
     against `jobs.run_id`/`jobs.state`/`jobs.updated_at`, not a dedicated ledger.
   - Recommendation: the planner should trace `_set_run_error`'s callers and `jobs.updated_at`
     timing precisely before finalizing SQL — this is squarely a plan-time task, not something to
     guess in research.

2. **Does PROOF-03's "second attempt" need a genuinely separate worker/thread, or can it be driven
   sequentially in the test body (mirroring PROOF-01/02's sequential-claim style)?**
   - What we know: D-03 does not mandate `threading.Barrier` for PROOF-03 (unlike D-04's explicit
     mandate for PROOF-04); the crash being modeled is a single worker dying, and "a second attempt
     replays" — this reads as sequential (attempt 1 fails/crashes, attempt 2 happens later), not
     concurrent.
   - What's unclear: whether "later" means a second `handle_send_outbound`/`drain_once()` call in
     the same test process (simplest), or whether the one-active-handoff fence's `owner_expired`
     check requires simulating elapsed time (`owner_leased_until` derived from the job's own lease,
     which is `lease_seconds=900` — the test would need to either expire that lease via direct SQL,
     mirroring PROOF-01's `UPDATE jobs SET leased_until = now() - interval '1 second'` idiom, or
     structure the assertion around the handoff staying ACTIVE and the second attempt being
     structurally REFUSED rather than replaying).
   - Recommendation: plan PROOF-03 as sequential (not threaded), reusing PROOF-01's lease-expiry-via-
     direct-SQL idiom to unblock the handoff fence for the "replay" step, and consider asserting
     BOTH shapes are true: (a) while the handoff is still active/unexpired, a second send attempt is
     refused (zero provider calls), and (b) once the handoff naturally expires and a genuine retry
     proceeds, the replayed `message_id`/`Idempotency-Key` are byte-identical to the first attempt.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Local/CI Postgres 16 (ephemeral service container) | PROOF-01..04, PROOF-05's CI gate | ✓ (CI-provisioned) | postgres:16 (per `concurrency-proof.yml`) | For local dev execution of live-DB mutations, a throwaway local Postgres via the same `bootstrap()` call CI uses — `uv run python -m app.db.bootstrap` against a local `DATABASE_URL`. |
| `DATABASE_URL` + `ALLOW_DB_RESET=1` env vars | All live-DB proof tests (two-factor guard) | ✓ in CI; **must be set explicitly in any local/worktree execution** | — | None — this is the exact hazard Pitfall 1 documents; there is no automatic fallback, only discipline. |
| `uv` (Python env/deps) | Running any test locally | Project-standard; assumed present per CLAUDE.md | pinned via `.python-version` (3.12) | None needed — mandated tooling. |

**Missing dependencies with no fallback:** None identified as blocking — all required infrastructure
already exists in this repo's CI and is reproducible locally via `uv run python -m app.db.bootstrap`.

**Missing dependencies with fallback:** None applicable.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (pinned in `pyproject.toml` dev group) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (markers: `integration`, `live_llm`, `queueproof`; `proof` marker to be added this phase) |
| Quick run command | `uv run pytest tests/test_queue_durability.py -k <test_name> -v` (hermetic subset; live-DB tests self-skip without `DATABASE_URL`) |
| Full suite command | `uv run pytest tests/ -m queueproof -v -rs` (mirrors `concurrency-proof.yml`'s own invocation) against a real Postgres |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROOF-01 | Worker crash mid-lease → reclaim + attempts increment | integration (real DB) | `uv run pytest tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease -v` | ✅ (needs marker added) |
| PROOF-02 | Same-Svix redelivery → exactly one event/job/run | integration (real DB) | `uv run pytest tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run -v` | ✅ (needs marker added) |
| PROOF-03 | Crash between provider-accept and `sent` commit | integration (real DB) | `uv run pytest tests/test_send_idempotency.py::test_<new_name> -v` | ❌ Wave 0 — new test |
| PROOF-04 | Genuine concurrent lease reclaim + double-fence | integration (real DB, real threads) | `uv run pytest tests/test_queue_durability.py::test_<rewritten_name> -v` | ⚠️ exists but must be rewritten (currently single-threaded) |
| PROOF-05 | Completeness gate: every PROOF id registered, none silently skipped | CI collection-layer check | `uv run pytest tests/ -m proof --collect-only -q` (new) | ❌ Wave 0 — new CI step + supporting pyproject.toml marker registration |
| OPS-01 | `/ops` renders queue depth/age/attempts/dead-letter + alarm | route/template test (hermetic, `fake_repo`) + manual browser UAT | `uv run pytest tests/test_ops_route.py -v` (new file) | ❌ Wave 0 — new route, template, and test file |

### Sampling Rate

- **Per task commit:** hermetic subset relevant to the changed file (`uv run pytest tests/<file>.py -k <name> -v`)
- **Per wave merge:** `uv run pytest tests/ -m queueproof -v -rs` against a real local/CI Postgres, plus full hermetic suite `uv run pytest tests/ -m "not integration and not live_llm"`
- **Phase gate:** Full suite green before `/gsd-verify-work` — including the new `--collect-only`
  completeness step run manually once (it only executes automatically in CI on push/PR).

### Wave 0 Gaps

- [ ] `tests/test_send_idempotency.py` — new PROOF-03 test (crash-between-accept-and-commit)
- [ ] `tests/test_queue_durability.py` — PROOF-04's two incumbent tests rewritten under
      `threading.Barrier` with genuine OS threads
- [ ] `pyproject.toml` — register the `proof` marker (mirrors existing `queueproof` registration
      pattern at line 45)
- [ ] `.github/workflows/concurrency-proof.yml` — new `--collect-only` completeness step (D-02)
- [ ] A new or extended AST-guard test file for D-06's mutation-target resolution (reuse
      `tests/test_bound01_private_imports.py`'s or `tests/test_fake_repo_pairing.py`'s scanning
      pattern rather than a new file, if a natural home exists — otherwise a new
      `tests/test_proof_mutation_targets.py`)
- [ ] `tests/test_ops_route.py` (or similar) — new hermetic route/template test for `/ops`
- [ ] `docs/DURABILITY-PROOFS.md` — new evidence document (D-07)

*(Framework itself needs no install — pytest, ast, threading, psycopg are already present.)*

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | `/ops` is explicitly unauthenticated by design (D-09; known/accepted v4 out-of-scope gap, same as `/runs` and `/eval`). No new auth surface introduced. |
| V3 Session Management | No | No session state introduced by this phase. |
| V4 Access Control | Partially — noted, not enforced | `/ops` inherits the existing dashboard's no-auth posture. The alarm health endpoint (D-14) is a GET with no secret — same posture as `/health/live`/`/health/ready`/`/health/schema`, which are all unauthenticated by design (contrast with `/internal/pump`, which IS bearer-token gated per `app/routes/pump.py:60-74`). Document this consciously rather than silently matching by accident. |
| V5 Input Validation | Minimal | `/ops` is a pure GET with no query params expected to affect the SQL beyond perhaps a future `?refresh` no-op; no user-controlled input reaches SQL. If any filter/query param is added, it must be parameterized exactly like every existing repo function (`%s` placeholders, never string interpolation — verified as universal convention in `jobs.py`/`job_settlement.py`). |
| V6 Cryptography | No | No crypto surface touched. `resend.Emails.send`'s `idempotency_key` is an existing opaque UUID-derived string, not a new secret. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via any new `/ops` filter param | Tampering | Parameterized `%s` placeholders exclusively — same convention as every existing repo function; never f-string SQL. |
| PII leakage on the dead-letter list | Information Disclosure | `jobs.last_error` is already documented as bounded/scrubbed via `_build_error_detail` (`app/db/repo/jobs.py:509-515`, same scrub helper `record_run_error` uses) — the dead-letter list must render only this already-bounded field plus `run_id`/`kind`/`attempts`, never a raw exception string or provider payload. Follow the existing PII-safe bounded-projection convention (`get_run_queue_label` deliberately projects no job identifier/counter/timestamp/payload/diagnostic beyond a fixed label — mirror that discipline for `/ops`). |
| Unauthenticated alarm/health endpoint used as a DoS amplification or information probe | Denial of Service / Information Disclosure | Existing health routes (`/health/live`, `/health/ready`, `/health/schema`) are already unauthenticated and return only status/schema-identifier-name bodies, never connection strings or stack traces (`app/routes/health.py:38-40, 59-60`) — D-14's new/extended endpoint must follow the identical disclosure discipline (status + minimal boolean/count fields only). |
| Cron secret leakage via `pump.yml` | Information Disclosure | Already mitigated — `PUMP_TOKEN` is a GitHub Actions secret, compared with `hmac.compare_digest` (constant-time) in `app/routes/pump.py:67-74`; D-14's new curl step should follow the same secret-handling pattern if it needs a token (health endpoints currently do not require one). |

## Findings (live-code verification detail)

**Finding 0 — Zero new dependencies confirmed.** `grep` across `pyproject.toml`'s dependency
groups plus the AST-guard/threading/pytest tooling this phase needs are all already present and
exercised elsewhere in the repo. `[VERIFIED: pyproject.toml, live test files]`

**Finding 1 — PROOF-01's incumbent is complete and non-vacuous.**
`tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease` (line 2779) is
explicitly labeled "Proof 2 — the phase's headline claim" in its own section header, drives a real
retrigger through `TestClient`, stops mid-lease by calling `repo.claim_job()`/`drain.drain_once()`
directly on the test thread (never starting a real worker thread, so it never needs the
`live_worker` fixture), stubs only the orchestrator (never the DB), and asserts BOTH the reclaim
path fired AND `attempts` incremented — exactly what REQUIREMENTS.md's "vacuous if" clause warns
against. Its own docstring documents two already-executed falsifying mutations with pasted-red
evidence referenced in a prior plan's SUMMARY. `[VERIFIED: tests/test_queue_durability.py:2779-2822]`

**Finding 2 — PROOF-02's incumbent is complete.**
`tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run`
(line 193) drives 2 real threads through `TestClient.post("/webhook/inbound", ...)` with the
identical `svix-id` header, asserts exactly one `inbound_events` row, exactly one `jobs` row, then
drives the ingest handler and asserts exactly one `email_messages` row and one `payroll_runs` row.
The dedup key (`svix-id`/`event_key`) is available pre-fetch (from headers, not from the Resend
`EmailsReceiving.get` call), satisfying REQUIREMENTS.md's "vacuous if dedup is keyed on something
available only post-fetch" warning. `[VERIFIED: tests/test_webhook_dedup_race.py:191-311]`

**Finding 3 — PROOF-04's incumbents are confirmed single-threaded.**
Both `test_expired_lease_is_reclaimed` (line 2224) and
`test_zombie_is_fenced_on_BOTH_complete_and_fail` (line 2262) call `repo.claim_job()` sequentially
twice from the SAME test-body thread, expiring the lease via a direct SQL `UPDATE ... leased_until
= now() - interval '1 second'` in between — CONTEXT.md's claim is exactly correct.
`[VERIFIED: tests/test_queue_durability.py:2224-2299]`

**Finding 4 — PROOF-03's injection seam located precisely.** See Code Examples above. The
settlement transaction (`app/db/repo/job_settlement.py::settle_outbound_delivery_job`, OK-branch,
lines 495-529) is called from `app/queue/drain.py:247` outside any try/except in `drain_once()`'s
success path — an exception there propagates uncaught. The `outbound_provider_handoffs` table's
"one active handoff" fence (`app/db/repo/outbound_handoffs.py:311-337`) structurally blocks a
second provider call while the first handoff's lease-derived `owner_leased_until` remains
unexpired, which is the mechanism that can make "exactly one provider call" true by construction.
`message_id` is minted once at RESERVE time (`reserve_outbound_snapshot`, `ON CONFLICT (run_id,
purpose, round, epoch) DO NOTHING`) and is the same value passed as `idempotency_key` to
`resend.Emails.send` (`app/email/gateway.py:167`). `[VERIFIED: live source, all three files]`

**Finding 5 — PROOF-05's stale premise and residual gap confirmed verbatim.**
`.github/workflows/concurrency-proof.yml`'s own comments (lines 60-161) state exactly what
CONTEXT.md claims: a marker-selected `-m queueproof` step already runs any test anywhere under
`tests/` carrying `@pytest.mark.queueproof` with zero workflow edits, and the workflow's own
comment names the residual gap verbatim: *"STATED GAP THIS GUARD DOES NOT CLOSE: it cannot detect a
typo'd marker on ONE newly-added test while the OTHER queueproof tests still pass — the log still
says 'N passed' and the new proof silently never ran."* `tests/test_queue_config.py` already pins
the byte-identical by-name step (`TestD14NoWideningGuard`) and separately asserts `queueproof` is
registered in `pyproject.toml`'s markers list — D-02's new `proof` marker needs the identical
registration-check treatment. `[VERIFIED: .github/workflows/concurrency-proof.yml, tests/test_queue_config.py]`

**Finding 6 — `/ops` data-layer seam confirmed.** `app/db/repo/jobs.py::count_open_jobs()` (line
575) and `::get_run_queue_label()` (line 596) exist exactly as CONTEXT.md describes and follow a
consistent, extensible convention (`_conn_ctx`, explicit column list `_JOB_COLS` including
`attempts`, `max_attempts`, `available_at`, `created_at`, `state`, `run_id`, `last_error` — all
fields OPS-01's metrics need). `fail_job` already transitions a job to `state='dead'` once
`attempts >= max_attempts` (line 520) — the dead-letter query is `SELECT ... FROM jobs WHERE
state = 'dead'`. `app/routes/health.py` has exactly 3 routes (`/health/live`, `/health/ready`,
`/health/schema`) with a consistent minimal-disclosure body convention; `app/routes/pump.py` is the
pattern for a new authenticated-or-not sync route. `app/main.py` registers 5 routers today — adding
a 6th (`ops`) is a 2-line change. `[VERIFIED: live source, all files named]`

**Finding 7 — `job_settlement.py`'s settlement facts identified, exact predicate shape open.**
`app/db/repo/job_settlement.py` (1136 lines) contains `SettlementOutcome`, `_set_run_error`,
and multiple `settle_*`/`reap_*` functions that are the "facts D-13's predicate must query" — but
no dedicated settlement-log/ledger table was found; the facts live as direct writes to `jobs` and
`payroll_runs`. The exact anti-join SQL for D-13's alarm needs plan-time design (see Open Question
1). `[VERIFIED: app/db/repo/job_settlement.py structure; NOT fully traced — see Open Question 1]`

**Finding 8 — the fake-repo pairing hazard is real, but CONTEXT.md's cited line numbers have
drifted; a dedicated guard test already exists.** `tests/conftest.py`'s `fake_repo` tuple is at
lines 2566-2661 (not ~1015), currently listing ~96 method names with the exact `if hasattr(store,
name)` silent-miss hazard CONTEXT.md describes. `tests/test_threading.py` has exactly 2 (not the
literal "~346/~427") monkeypatch name tuples, at lines 513-526 and 596-609, both driving
`_MiniStore`. Critically, **`tests/test_fake_repo_pairing.py` (327 lines) already exists and is
itself the mechanized guard against exactly this class of miss** — including
`test_threading_ministore_patch_sets_are_complete`, which asserts there are exactly 2 registered
tuples in `test_threading.py` and that every `_MiniStore` public method shadowing a real
`app.db.repo` name appears in both. Any new `/ops`-supporting repo function this phase adds does
NOT need a brand-new guard invented — it needs to be added to the existing tuple(s), and the
existing guard test will catch a miss automatically. `[VERIFIED: tests/conftest.py:2560-2668,
tests/test_threading.py:495-628, tests/test_fake_repo_pairing.py full read]`

**Finding 9 — `pump.yml`'s step order and disclosure discipline confirmed for D-14/D-15.** The
drain step (no `if:`) runs first; both health steps carry `if: ${{ always() }}` specifically so an
earlier RED cannot suppress them, and every curl uses `-f` to fail loudly. D-14's new alarm step
should be appended last with the same `if: ${{ always() }}`, per D-15's "recovery first, reporting
second" rule and the drain's own comment block explaining exactly this ordering philosophy already
for the existing two health checks. `[VERIFIED: .github/workflows/pump.yml full read]`

## Sources

### Primary (HIGH confidence — direct file reads of this repository, 2026-07-20)

- `.planning/phases/21-durability-proofs-ops-view/21-CONTEXT.md` — locked decisions, canonical refs
- `.planning/REQUIREMENTS.md` — PROOF-01..05, OPS-01 literal text + accepted-residual-risk section
- `.planning/STATE.md` — v4 decision log, deferred items, session continuity
- `.github/workflows/concurrency-proof.yml` — full read
- `.github/workflows/pump.yml` — full read
- `tests/test_queue_config.py` — full read
- `tests/test_queue_durability.py` — module docstring, lines 1997-2400, 2760-2900 (targeted reads)
- `tests/test_webhook_dedup_race.py` — lines 180-311
- `tests/test_send_idempotency.py` — lines 1-60, 520-650, 1360-1530
- `tests/test_fake_repo_pairing.py` — full read
- `tests/test_bound01_private_imports.py` — lines 280-374
- `tests/test_background_task_cutover.py` — targeted grep (function/class inventory)
- `tests/conftest.py` — lines 1000-1030, 2540-2668
- `tests/test_threading.py` — lines 335-360, 415-435, 495-628
- `app/db/repo/jobs.py` — full structural read (lines 1-73, 469-625)
- `app/db/repo/job_settlement.py` — function inventory + lines 280-559
- `app/db/repo/outbound_handoffs.py` — lines 1-120, 227-502
- `app/email/gateway.py` — full read
- `app/queue/handlers/send_outbound.py` — full read
- `app/queue/drain.py` — lines 180-260
- `app/routes/health.py` — full read
- `app/routes/pump.py` — full read
- `app/routes/dashboard.py` — full read
- `app/templates/base.html` — full read
- `app/main.py` — full read
- `app/models/job.py`, `app/models/status.py` — targeted reads
- `pyproject.toml` — `[tool.pytest.ini_options]` section
- `render.yaml` — env var key grep
- `README.md` — pump-cadence section grep
- `.planning/config.json` — workflow toggles (nyquist_validation, security_enforcement both enabled/default)

### Secondary (MEDIUM confidence)

None — no external documentation was needed for this phase; every claim was verifiable directly
against this repository's own source.

### Tertiary (LOW confidence)

None.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; every tool already pinned and exercised in-repo.
- Architecture: HIGH — every seam (drain.py, job_settlement.py, outbound_handoffs.py, jobs.py,
  health.py, pump.py) was read directly, not inferred.
- Pitfalls: HIGH — every pitfall is either a documented prior incident in this repo's own memory/
  STATE.md or a directly observed live-code hazard (e.g. the `hasattr` silent-miss guard).
- OPS-01's alarm predicate exact SQL: MEDIUM — the source facts and tables are located, but the
  precise anti-join query design is left as an explicit Open Question for plan-time.

**Research date:** 2026-07-20
**Valid until:** This phase's research is tied to this repository's exact current source (commit
`925a4b2` and prior); it does not expire on a calendar basis but on the next source change to any
of the files listed under Sources — re-verify line numbers before planning if significant time has
passed or intervening commits touched `app/queue/`, `app/db/repo/`, or `tests/test_queue_*.py`.
