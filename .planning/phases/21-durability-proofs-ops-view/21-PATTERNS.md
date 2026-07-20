# Phase 21: Durability Proofs & Ops View - Pattern Map

**Mapped:** 2026-07-20
**Files analyzed:** 11 (2 new source, 3 modified templates/config, 5 new/modified tests, 1 new doc)
**Analogs found:** 11 / 11 — this is an audit-and-close phase; every new surface has a strong
in-repo analog already identified by RESEARCH.md's Findings 0-9. No "no analog" section needed.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `app/routes/ops.py` (NEW) | route/controller | request-response (read) | `app/routes/dashboard.py` (`landing`, `eval`) + `app/routes/runs.py::runs_list` | exact |
| `app/routes/health.py` (extend, D-14 alarm endpoint) | route/controller | request-response (read) | `app/routes/health.py::health_schema` (same file, sibling route) | exact |
| `app/db/repo/jobs.py` (extend: oldest-pending / attempts-distribution / dead-letter queries) | service/repo | CRUD (read) | `app/db/repo/jobs.py::count_open_jobs`, `::get_run_queue_label` (same file, sibling functions) | exact |
| `app/db/repo/job_settlement.py` (extend: D-13 alarm predicate query) | service/repo | CRUD (read) | `app/db/repo/job_settlement.py::_set_run_error` / settlement writers (same file) | exact |
| `app/templates/ops.html` (NEW) | component/template | request-response (SSR read) | `app/templates/runs_list.html` | exact |
| `app/templates/base.html` (nav edit) | template | request-response | itself (existing nav block) | exact |
| `tests/test_queue_durability.py` (PROOF-01 marker; PROOF-04 threading rewrite) | test | event-driven / concurrency | same file's `test_provider_handoff_blocks_epoch_bump_before_gateway` (Barrier idiom) | exact |
| `tests/test_webhook_dedup_race.py` (PROOF-02 marker) | test | request-response | itself (existing test, add decorator only) | exact |
| `tests/test_send_idempotency.py` (PROOF-03 NEW test) | test | CRUD / fault-injection | same file's `fake_repo`/`seeded_db` idempotency tests | role-match |
| new/extended AST-guard test file (D-06) | test | transform (static analysis) | `tests/test_bound01_private_imports.py`, `tests/test_fake_repo_pairing.py` | exact |
| `tests/test_queue_config.py` (D-02 collect-gate pin extension) | test | transform (config/YAML pin) | same file's `TestD14NoWideningGuard`, `TestQueueproofMarkerRegistered` | exact |
| `.github/workflows/concurrency-proof.yml` (D-02 new step) | config | batch (CI) | itself — existing `queueproof` step (same file) | exact |
| `.github/workflows/pump.yml` (D-14 new step) | config | batch (CI cron) | itself — existing `/health/ready`/`/health/schema` steps (same file) | exact |
| `pyproject.toml` (register `proof` marker) | config | — | itself — existing `markers` list | exact |
| `docs/DURABILITY-PROOFS.md` (NEW) | doc | — | `README.md`'s architecture-diagram link convention | role-match |

## Pattern Assignments

### `app/routes/ops.py` (route, request-response read)

**Analog:** `app/routes/runs.py::runs_list` (`GET /runs`, lines 809-836) — the closest sibling:
also an unauthenticated pure-read GET rendering a Jinja2 template from repo projections.

**Imports pattern** (`app/routes/dashboard.py:1-16`):
```python
"""GET /, /eval, /eval/chart.svg — dashboard views."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from app.db import repo
from app.routes.demo import DEMO_FIXTURES, DEMO_OPERATOR_EMAIL, SEED_BUSINESS_IDS, SEED_CONTACTS
from app.routes.templating import templates

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()
```
`ops.py` should mirror this exactly: `from app.db import repo`, `from app.routes.templating import
templates`, module-level `router = APIRouter()`, module-level logger named
`"payroll_agent.webhook"` (the convention used by both `dashboard.py` and `runs.py`).

**Side-effect-free read convention (Phase 18 D-18)** — copy verbatim, adapted (`app/routes/runs.py:809-836`):
```python
@router.get("/runs")
def runs_list(
    request: Request,
    demo_queue_error: str = Query(default=""),
) -> Response:
    """DASH-01: Read and render the reverse-chronological runs list.

    This unauthenticated GET is deliberately side-effect free. Durable queue workers
    own automatic recovery; operators use explicit mutation routes such as Retrigger.
    """
    try:
        runs = [_safe_run_for_browser(run) for run in repo.load_all_runs()]
    except Exception:
        # DB unavailable (no pool / no connection): render empty list rather than 500.
        # This keeps the dashboard functional during test runs and Render cold-starts
        # before the pool is warmed up.
        logger.debug("load_all_runs unavailable — rendering empty list")
        runs = []
    return templates.TemplateResponse(
        request,
        "runs_list.html",
        {
            "runs": runs,
            "demo_fixtures": DEMO_FIXTURES,
            "in_flight_statuses": list(IN_FLIGHT_STATUSES),
            "demo_queue_error": bool(demo_queue_error),
        },
    )
```
`GET /ops` should follow this shape 1:1: try the repo reads, `except Exception: logger.debug(...);`
fall back to empty/zeroed metrics, then `templates.TemplateResponse(request, "ops.html", {...})`.
State explicitly in the docstring (mirroring D-18's own wording) that `/ops` is side-effect-free,
citing D-18 the same way `runs_list`'s docstring cites its own requirement id.

**Registration in `app/main.py`** (full file, 18 lines):
```python
"""FastAPI entrypoint — thin app assembly only. Routes live in app/routes/*."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.queue import worker
from app.routes import dashboard, demo, health, pump, runs, webhook

app = FastAPI(title="Pyrl", lifespan=worker.lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(demo.router)
app.include_router(pump.router)
```
Add `ops` to the `from app.routes import ...` tuple (alphabetical-ish grouping already loose; put it
near `pump`/`runs`) and one `app.include_router(ops.router)` line — a strict 2-line diff, exactly the
shape RESEARCH.md's Finding 6 describes ("adding a 6th router is a 2-line change").

**Templating seam** (`app/routes/templating.py`, full file) — `ops.html`'s badge rendering (if any
queue-state badges appear) should reuse the existing filters registered here:
```python
templates = Jinja2Templates(directory="app/templates")
...
templates.env.filters["badge_class"] = badge_class_filter
templates.env.filters["badge_label"] = badge_label_filter  # (mirrors badge_class registration)
```
Import `from app.routes.templating import templates` — never construct a second `Jinja2Templates`
instance.

---

### `app/routes/health.py` (D-14's alarm endpoint, extend or add a route)

**Analog:** same file, `health_schema` (lines 51-72) — the disclosure-discipline precedent:

```python
@router.get("/health/schema")
def health_schema() -> JSONResponse:
    """Live schema-parity probe ...
    200 {"status":"in_sync"}                       — live DB matches schema.sql
    503 {"status":"drift","missing":{...}}         — declared-but-missing on live
    503 {"detail":"schema check unavailable"}      — DB unreachable / parse error

    The body carries only schema identifier NAMES — no row data, no connection
    string, no stack trace. Same disclosure rule as /health/ready.
    """
    try:
        with get_connection() as conn:
            diff = diff_against_live(conn)
    except Exception as exc:  # noqa: BLE001 — probe must not leak internals
        logger.error("schema parity probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="schema check unavailable") from exc
    if diff.is_in_sync:
        return JSONResponse({"status": "in_sync"})
    return JSONResponse(
        {"status": "drift", "missing": diff.as_missing_dict()},
        status_code=503,
    )
```
D-14's new alarm route (e.g. `/health/queue`) must follow this exact shape: try the DB read, catch
broadly with `# noqa: BLE001` + `type(exc).__name__`-only logging (never `str(exc)`), 200 when
healthy, non-200 (503, matching the sibling probes) when the alarm condition holds, body carrying
only a `status` field + minimal boolean/count — never a raw run id list, error string, or stack
trace (per RESEARCH.md's Security Domain table).

---

### `app/db/repo/jobs.py` (extend: oldest-pending age / attempts distribution / dead-letter)

**Analog:** same file, `count_open_jobs()` (lines 573-591) and `get_run_queue_label()` (lines
596-624) — copy the `_conn_ctx` + explicit-column convention verbatim:

```python
def count_open_jobs(conn: psycopg.Connection | None = None) -> int:
    """The point-in-time backlog count: rows in `state IN ('pending',
    'leased')`. ...
    This is a plain read, no fencing, no mutation — a
    `SELECT count(*)` behind the same `_conn_ctx` convention every other
    function in this module uses.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')", ()
        ).fetchone()
    return int(row[0]) if row else 0
```

```python
def get_run_queue_label(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> str | None:
    """Return the fixed browser-safe label for a run's open queue work.
    The aggregate deliberately projects no job identifier, counter, timestamp,
    payload, or diagnostic.  ...
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
                SELECT CASE
                         WHEN bool_or(state = 'leased')
                           THEN 'Running'
                         ...
                       END AS queue_label
                  FROM jobs
                 WHERE run_id = %s
                   AND state IN ('pending', 'leased')
                """,
            (str(run_id),),
        ).fetchone()
    ...
```
New functions (e.g. `oldest_pending_age_seconds()`, `attempts_distribution()`, `list_dead_letter_jobs()`)
must use the same `with _conn_ctx(conn) as (c, _owns): ... c.execute(sql, (params,)).fetchone()/
fetchall()` idiom, `%s` placeholders exclusively (never f-string SQL — the universal convention in
this file), and the existing `_JOB_COLS` explicit column list / `get_job`'s dict_row pattern (lines
1-10 of that excerpt above) for any row-shaped return, never `SELECT *`. Dead-letter query is
literally `SELECT ... FROM jobs WHERE state = 'dead'` per RESEARCH.md Finding 6.

**PII-safe bounded projection** — `jobs.last_error` is already scrubbed via `_build_error_detail`
(cited in RESEARCH.md Security Domain); the dead-letter list template context must project only
`run_id`, `kind`, `attempts`, and this already-bounded `last_error` field — never a raw exception
string.

---

### `app/db/repo/job_settlement.py` (D-13 alarm predicate)

**Analog:** same file — `_set_run_error` and the `settle_*`/`reap_*` writer functions are the
source-of-truth facts; RESEARCH.md's Finding 7/Open Question 1 flags that no dedicated settlement
ledger exists, so the predicate must be a correlated query joining `payroll_runs.status='error'`
against `jobs.run_id`/`jobs.state`/`jobs.updated_at` timing — trace `_set_run_error`'s callers before
finalizing the SQL (explicit plan-time task, not guessable from research alone).

---

### `app/templates/ops.html` (NEW) + `app/templates/base.html` (nav)

**Analog:** `app/templates/runs_list.html` — extends `base.html`, same block structure:
```jinja
{% extends "base.html" %}
{% block content %}
...
<h1>Payroll Runs</h1>
```
`ops.html` should extend `base.html` identically and open with `<h1>Ops</h1>` or similar, followed by
D-11's "as of &lt;timestamp&gt;" stamp (no polling script — `runs_list.html`'s per-row poll `<script>`
block at the top is explicitly NOT to be copied; D-11 forbids polling).

**Nav block to extend** (`app/templates/base.html:12-16`):
```html
  <nav>
    <a href="/" class="nav-brand">Pyrl</a>
    <a href="/runs">Runs</a>
    <a href="/eval">Eval</a>
  </nav>
```
Add a fourth `<a href="/ops">Ops</a>` line, producing `Pyrl | Runs | Eval | Ops` per D-09.

**Styling tokens** (`app/static/style.css:1-50`) — reuse the existing design-token `:root` block
(`--space-*`, `--surface`, `--border`, `--accent`, `--danger`, `--radius-*`, `--shadow-*`,
`--font-sans`) rather than introducing new colors/spacing values; the alarm banner should use
`--danger`/`--danger-hover` (already defined) for its warning state.

---

### PROOF-01 / PROOF-02 markers (promote in place, D-01/D-02)

**Analog:** `tests/test_webhook_dedup_race.py:191-193`'s existing per-function marker stacking
pattern:
```python
@pytest.mark.integration
@pytest.mark.queueproof
@pytest.mark.proof("PROOF-02")  # ADD — D-02
def test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run(...):
```
For PROOF-01 (`tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease`), the
module already applies `pytestmark = [pytest.mark.integration, pytest.mark.queueproof]` at module
scope — add `@pytest.mark.proof("PROOF-01")` directly above that one function only (never at module
scope, since exactly one test per PROOF id is required per D-02).

**Marker registration** (`pyproject.toml:41-46`):
```toml
markers = [
    "integration: marks tests as requiring a live database (deselect with -m 'not integration')",
    "live_llm: marks tests as hitting real DeepSeek/Kimi APIs (deselect with -m 'not live_llm')",
    "queueproof: a durability proof for the v4 job queue; MUST execute in CI against a real Postgres",
]
```
Add a fourth line: `"proof: identifies a durability proof by id (@pytest.mark.proof(\"PROOF-0N\")); see D-02",`
— exact same list-append convention.

---

### PROOF-04 threading rewrite (D-04) — the Barrier idiom to copy

**Analog (same file, nearby):** `tests/test_queue_durability.py`'s module docstring rule (lines 5-12,
paraphrased in RESEARCH.md) plus the live worked example
`test_provider_handoff_blocks_epoch_bump_before_gateway` (lines 1997-2070+):
```python
barrier = threading.Barrier(2, timeout=30)
return_to_handler = threading.Event()
barrier_passes: list[str] = []
worker_connection_ids: list[int] = []
retrigger_connection_ids: list[int] = []
worker_errors: list[BaseException] = []
retrigger_errors: list[BaseException] = []

def authorize_then_pause(leased_job):
    with repo.get_connection() as conn:
        with conn.transaction():
            worker_connection_ids.append(id(conn))
            authorization = real_authorize(leased_job, conn=conn)
        barrier.wait()
        barrier_passes.append("worker")
        assert return_to_handler.wait(timeout=30), "retrigger did not release worker"
        return authorization

def run_handler() -> None:
    try:
        assert send_outbound.handle_send_outbound(job).outcome is PipelineOutcome.OK
    except BaseException as exc:  # surface thread failures in the test thread
        worker_errors.append(exc)

def retrigger_after_authorization() -> None:
    try:
        with repo.get_connection() as conn:
            with conn.transaction():
                retrigger_connection_ids.append(id(conn))
            barrier.wait()
            barrier_passes.append("retrigger")
            ...
    except BaseException as exc:
        retrigger_errors.append(exc)
    finally:
        return_to_handler.set()
```
The rewritten `test_expired_lease_is_reclaimed`/`test_zombie_is_fenced_on_BOTH_complete_and_fail`
(current single-threaded incumbents, lines 2224-2299 — full text below) must replace their sequential
`repo.claim_job()` / `complete_job` / `fail_job` calls with two real `threading.Thread` targets
released by a `threading.Barrier(2, timeout=30)`, capturing per-thread connection ids the same way,
while keeping the direct-SQL lease-expiry `UPDATE jobs SET leased_until = now() - interval '1 second'
WHERE id = %s` (no sleeping, no lowered `LEASE_SECONDS`) exactly as today:

```python
def test_expired_lease_is_reclaimed(seeded_db) -> None:
    ...
    first = repo.claim_job()
    ...
    token_a = first.lease_token
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s",
            (str(enqueued_id),),
        )
    second = repo.claim_job()
    ...
```
Per D-04, both `complete_job(token_a)` and `fail_job(token_a, ...)` must be driven from Worker A's own
thread (not the test's main thread) racing genuinely against Worker B's `claim_job()` reclaim thread —
mind the pool budget (`max_size=5`); two threads is well inside it.

---

### PROOF-03 (NEW test, D-03) — injection seam + assertions to copy

**Analog:** the fault-injection/spy idiom already used throughout
`tests/test_queue_durability.py` (`provider_spy` closures, e.g. lines 2038-2041) and
`tests/test_send_idempotency.py`'s existing `message_id`/epoch assertions (e.g. lines 360-437,
531-557).

**Exact injection point** (`app/queue/drain.py:241-255`, VERIFIED live source):
```python
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

**Settlement transaction to force-fail** (`app/db/repo/job_settlement.py:495-529`, VERIFIED):
```python
if result.outcome is PipelineOutcome.OK:
    if not finalize_outbound_provider_handoff(authorization, conn=c):   # <-- or here
        raise RuntimeError("locked delivery success lost its provider handoff")
    _append_delivery_attempt(c, snapshot_id=snapshot_id, attempt_state="sent", ...)
    sent = c.execute("UPDATE email_messages SET send_state = 'sent' ...").fetchone()
```

**The fence that makes "exactly one provider call" true by construction**
(`app/db/repo/outbound_handoffs.py:311-337`, VERIFIED):
```python
if owner_token == job.lease_token:
    return _authorization(...)          # same job/lease re-authorizing: OK
if not owner_expired:
    return ProviderHandoffActive("active_handoff_unexpired", handoff_id)   # BLOCKED
```

**message_id/Idempotency-Key contract** — `message_id` is minted once at RESERVE time
(`reserve_outbound_snapshot`, `ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING`) and passed
unchanged as `idempotency_key` at `app/email/gateway.py:167`
(`resend.Emails.send(send_params, {"idempotency_key": message_id})`). PROOF-03's assertions must read
the persisted `message_id` via `load_outbound_snapshot`/`get_outbound_message_id` before and after the
forced failure + replay and assert byte-identical equality, plus assert the gateway spy's call count
is exactly 1 (or, if both calls legitimately reach the provider, that both carried the identical
`idempotency_key`).

**Sequential (not threaded) structure per Open Question 2** — reuse PROOF-01's lease-expiry-via-
direct-SQL idiom to unblock the handoff fence for the "replay" step, mirroring the
`test_expired_lease_is_reclaimed` shape above but for `SEND_OUTBOUND` jobs.

---

### D-06 AST mutation-target guard (new or extended file)

**Analog 1:** `tests/test_bound01_private_imports.py` — the `ast.walk` + node-type resolution shape,
and its own red-proof pattern:
```python
def test_no_cross_module_private_imports() -> None:
    """The permanent CI gate: scans the LIVE app/, eval/, scripts/ trees and
    asserts zero cross-module private-name references remain, ..."""
    scan_roots = [REPO_ROOT / name for name in SCAN_ROOTS]
    violations = scan_tree_for_violations(scan_roots, REPO_ROOT)
    assert not violations, "BOUND-01 violation(s) found:\n" + "\n".join(violations)


def test_scanner_detects_synthetic_violation(tmp_path: pathlib.Path) -> None:
    """Prove the scanner's own detection logic against synthetic fixtures."""
    ...
```
D-06's guard needs the identical two-test shape: one asserting the real repo is clean (or, for
D-06, that each proof's declared mutation target resolves as a real AST node), and a SEPARATE
`test_..._detects_synthetic_...` test that feeds a synthetic bad source string through the same
detector function and asserts it correctly flags the violation — never only the "passes on real
source" half (Pitfall 2).

**Analog 2:** `tests/test_fake_repo_pairing.py:1-80` — the retired-symbol / paired-facade detector
shape, directly reusable for resolving a named target (e.g. "the `OR (c.state = 'leased' AND ...)`
clause in `claim_job`'s WHERE") as a real AST node rather than a grep match:
```python
def _defined_or_exported_names(source: str) -> set[str]:
    """Return concrete definitions, imports, assignments, and ``__all__`` names."""
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            names.update(
                item.value
                for item in ast.walk(node.value)
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            )
    return names
```

---

### D-02 CI collect-gate (`.github/workflows/concurrency-proof.yml`)

**Analog:** the file's own existing `queueproof` step's guard idiom (lines 145-161, VERIFIED):
```yaml
run: |
  set -o pipefail
  uv run pytest tests/ -m queueproof -v -rs 2>&1 | tee pytest-queueproof.log
  if grep -qE '[0-9]+ skipped' pytest-queueproof.log; then
    echo "A queue durability proof was skipped instead of executed. A skipped proof proves nothing." >&2
    exit 1
  fi
  if ! grep -qE '[0-9]+ passed' pytest-queueproof.log; then
    echo "No queueproof test reported as passed — the marker selection or the live-DB guard is broken." >&2
    exit 1
  fi
```
D-02's NEW step (add, don't touch this one) should mirror this `set -o pipefail` + `tee` + grep-guard
idiom but run `pytest tests/ -m proof --collect-only -q`, parsed for exactly 4 distinct
`PROOF-01`..`PROOF-04` ids, per RESEARCH.md's Code Examples section. **Do not touch the two existing
steps** — `tests/test_queue_config.py::TestD14NoWideningGuard` pins the by-name step byte-identically
(see below) and `TestQueueproofMarkerRegistered` pins the `queueproof:` marker registration string.

**The byte-identical pin to preserve** (`tests/test_queue_config.py:109-149`):
```python
class TestD14NoWideningGuard:
    def test_existing_gate_still_names_its_two_files(self) -> None:
        sql = _WORKFLOW_YML.read_text()
        assert (
            "tests/test_concurrency_proof.py "
            "tests/test_email_epoch_arbiter_integration.py -m integration"
            in sql
        ), (...)

    def test_whole_suite_integration_collection_absent(self) -> None:
        sql = _WORKFLOW_YML.read_text()
        assert "uv run pytest tests/ -m integration" not in sql, (...)


class TestQueueproofMarkerRegistered:
    def test_queueproof_registered_in_pyproject(self) -> None:
        toml_src = _PYPROJECT_TOML.read_text()
        assert "queueproof:" in toml_src, (...)
```
Extend `tests/test_queue_config.py` with a sibling `TestProofMarkerRegistered` class asserting
`"proof:"` is in `pyproject.toml`'s markers list, using the identical `_PYPROJECT_TOML.read_text()`
seam — do not invent a new file-reading helper.

---

### D-14/D-15 pump.yml alarm step

**Analog:** the file's own existing two `always()`-guarded health steps (lines 99-118, VERIFIED):
```yaml
      - name: Ping /health/ready (wakes service + touches Supabase via SELECT)
        if: ${{ always() }}
        run: curl -f --max-time 90 "$RENDER_URL/health/ready"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}

      - name: Check /health/schema (drift → RED)
        if: ${{ always() }}
        run: curl -f --max-time 90 "$RENDER_URL/health/schema"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```
D-14's new step must be appended AFTER these two (last in the file, per D-15's "recovery first,
reporting second"), use the identical `if: ${{ always() }}` + `curl -f --max-time 90
"$RENDER_URL/<new-health-route>"` + `env: RENDER_URL: ${{ secrets.RENDER_URL }}` shape — never gate
the drain step on the alarm.

---

### `docs/DURABILITY-PROOFS.md` (NEW, D-07)

**Analog:** no existing `docs/*.md` narrative file was found (only `docs/architecture.{mmd,png,svg}`
and `docs/superpowers/`); README.md links to `docs/architecture.svg` via a plain relative Markdown
link:
```markdown
thread. See the [detailed architecture diagram](docs/architecture.svg) for the implementation-level
```
Add a comparable `[durability proofs](docs/DURABILITY-PROOFS.md)` link near this existing
architecture-diagram reference in README.md — same relative-path convention, no new linking pattern.
Structure the doc itself per D-07/D-08's stated shape: one section per proof (claim → mutation →
pasted red → byte-identical revert green → exact re-run command), plus a residuals section stating
verbatim the Two-Generals / ~30-min best-effort / at-most-once-per-epoch boundaries from D-08.

## Shared Patterns

### Side-effect-free reads (Phase 18 D-18)
**Source:** `app/routes/runs.py::runs_list` (lines 809-836)
**Apply to:** `app/routes/ops.py` — every query in the route is a pure `SELECT`; no mutation, no
retrigger, no write path. State this explicitly in the route docstring.

### `_conn_ctx` + explicit-column-list DB read convention
**Source:** `app/db/repo/jobs.py::count_open_jobs`, `::get_run_queue_label`, `::get_job`
**Apply to:** every new repo function this phase adds (`jobs.py` metrics, `job_settlement.py`
predicate) — `with _conn_ctx(conn) as (c, _owns): ...`, `%s` placeholders exclusively, explicit
column lists (never `SELECT *`), `dict_row` for row-shaped returns.

### Fake-repo pairing registration (critical, silent-failure trap)
**Source:** `tests/conftest.py`'s `fake_repo` tuple (verified at lines 2560-2661, NOT ~1015 as
CONTEXT.md's stale citation says) and `tests/test_threading.py`'s two `_MiniStore` monkeypatch
tuples (verified at lines ~495-530 and ~596-615, NOT ~346/~427):
```python
@pytest.fixture
def fake_repo(monkeypatch) -> InMemoryRepo:
    store = InMemoryRepo()
    import app.db.repo as repo_mod
    for name in (
        "insert_inbound_email", "find_business_by_sender", "create_run", "load_run",
        ... "get_run_queue_label", ...
    ):
```
```python
# tests/test_threading.py — TWO separate tuples, both driving _MiniStore
for name in (
    "load_run", "load_source_email", "load_roster_for_business",
    "set_status", "claim_status", "record_run_error", "persist_extracted",
    ...
):
    monkey.setattr(repo_mod, name, getattr(store, name), raising=False)
```
**Apply to:** every new `app/db/repo/jobs.py`/`job_settlement.py` function this phase adds that any
hermetic (non-`seeded_db`) test path touches — its name string must be added to all THREE tuples, or
`tests/test_fake_repo_pairing.py`'s own guard (`_assert_durable_recovery_pairs`,
`test_threading_ministore_patch_sets_are_complete`) reds first — treat that red as confirmation, not
failure.

### AST-based static guards (never grep)
**Source:** `tests/test_bound01_private_imports.py::scan_tree_for_violations` +
`tests/test_fake_repo_pairing.py::_defined_or_exported_names`
**Apply to:** D-06's mutation-target guard — resolve every mutation target as a real `ast.walk`
node, never a text/grep match; ship both the "clean on real source" test AND a
`test_..._detects_synthetic_...` red-proof test per detector, per Pitfall 2.

### `threading.Barrier`-driven genuine concurrency, never through an HTTP route
**Source:** `tests/test_queue_durability.py`'s own module docstring + the live
`test_provider_handoff_blocks_epoch_bump_before_gateway` idiom (barrier + named threads + captured
connection ids + `BaseException`-catching thread bodies that surface failures in the test thread)
**Apply to:** PROOF-04's rewrite — drive `claim_job`/`complete_job`/`fail_job` directly from real
`threading.Thread` targets released by a shared `threading.Barrier`, never via `TestClient` hitting
an `async def` route (the Phase-10 CR-01 lesson, restated in this file's own docstring).

### CI guard idiom — `set -o pipefail` + `tee` + grep-on-log
**Source:** `.github/workflows/concurrency-proof.yml`'s two existing steps (lines 93-104, 145-161)
**Apply to:** D-02's new `--collect-only` completeness step in the same file — reuse the exact
`pipefail`/`tee .log`/`grep -qE` idiom rather than inventing a new counting mechanism.

### Minimal-disclosure health-probe body convention
**Source:** `app/routes/health.py` (`/health/live`, `/health/ready`, `/health/schema`) — status +
minimal boolean/count fields only, `type(exc).__name__` in logs, never `str(exc)` or a connection
string.
**Apply to:** D-14's new/extended alarm health route.

## No Analog Found

None — every file this phase touches has a strong, directly-cited in-repo analog (see table above).

## Metadata

**Analog search scope:** `app/routes/`, `app/db/repo/`, `app/templates/`, `app/static/`, `tests/`,
`.github/workflows/`, `pyproject.toml`, `README.md`, `docs/`
**Files scanned (read/grepped this session):** `app/routes/dashboard.py`, `app/routes/runs.py`,
`app/routes/templating.py`, `app/routes/health.py`, `app/routes/pump.py`, `app/main.py`,
`app/db/repo/jobs.py`, `app/templates/base.html`, `app/templates/runs_list.html`,
`app/static/style.css`, `tests/conftest.py`, `tests/test_threading.py`,
`tests/test_fake_repo_pairing.py`, `tests/test_bound01_private_imports.py`,
`tests/test_queue_durability.py`, `tests/test_send_idempotency.py`, `tests/test_queue_config.py`,
`.github/workflows/concurrency-proof.yml`, `.github/workflows/pump.yml`, `pyproject.toml`,
`README.md`
**Pattern extraction date:** 2026-07-20
