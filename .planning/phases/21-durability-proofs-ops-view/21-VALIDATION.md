---
phase: 21
slug: durability-proofs-ops-view
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-19
---

# Phase 21 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `21-RESEARCH.md` § Validation Architecture (verified against live source).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (pinned in `pyproject.toml` dev group) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — markers `integration`, `live_llm`, `queueproof`; **`proof` marker is added by this phase** |
| **Quick run command** | `uv run pytest tests/<file>.py -k <test_name> -v` |
| **Full suite command (hermetic)** | `uv run pytest tests/ -m "not integration and not live_llm"` |
| **Full suite command (real Postgres)** | `uv run pytest tests/ -m queueproof -v -rs` — mirrors `concurrency-proof.yml`'s own invocation |
| **Estimated runtime** | Measure at Wave 0 and record here — do not assume. Hermetic suite is the fast path; the `queueproof` suite requires a live Postgres. |

**Environment precondition (BLOCKING for this phase):** live-DB tests self-skip without
`DATABASE_URL`. A skip is not a pass. Every executor working a PROOF task needs its own
throwaway Postgres reachable via `DATABASE_URL` in its working environment — git worktrees
do **not** inherit the repo `.env`, which is precisely how prior phases silently deferred
every live-DB proof. Verify with `-rs` and read the skip report before claiming green.

---

## Sampling Rate

- **After every task commit:** hermetic subset for the changed file —
  `uv run pytest tests/<file>.py -k <name> -v`
- **After every plan wave:** `uv run pytest tests/ -m queueproof -v -rs` against a real
  Postgres, **plus** the full hermetic suite
  `uv run pytest tests/ -m "not integration and not live_llm"`
- **Before `/gsd-verify-work`:** both suites green, and the new `--collect-only`
  completeness check (D-02) run **manually at least once** — it otherwise executes only in
  CI on push/PR, so a local green proves nothing about it.
- **Max feedback latency:** hermetic subset must stay under ~60s; record the measured
  figure at Wave 0.

---

## Per-Task Verification Map

Task IDs do not exist until plans are written. The **requirement-level** map below is
established; the planner and `/gsd-execute-phase` expand it to `{21-NN-NN}` task rows.

| Requirement | Behavior | Test Type | Automated Command | File Exists |
|-------------|----------|-----------|-------------------|-------------|
| PROOF-01 | Worker crash mid-lease → reclaim + attempts increment | integration (real DB) | `uv run pytest tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease -v` | ✅ exists — needs `proof` marker |
| PROOF-02 | Same-Svix redelivery → exactly one event, job, run | integration (real DB) | `uv run pytest tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run -v` | ✅ exists — needs `proof` marker |
| PROOF-03 | Crash between provider-accept and `sent` commit; `message_id` byte-identical, exactly one provider call, same `Idempotency-Key` | integration (real DB) | `uv run pytest tests/test_send_idempotency.py -k proof03 -v` | ❌ W0 — new test |
| PROOF-04 | Genuine concurrent lease reclaim; zombie's late `complete_job` **and** `fail_job` both fenced | integration (real DB, real OS threads under `threading.Barrier`) | `uv run pytest tests/test_queue_durability.py -k proof04 -v` | ⚠️ exists but **single-threaded** — must be rewritten |
| PROOF-05 | Completeness gate: PROOF-01..04 each appear exactly once at the selection layer | CI collection-layer check | `uv run pytest tests/ -m proof --collect-only -q` | ❌ W0 — new CI step + marker registration |
| OPS-01 | `/ops` renders depth, oldest-pending age, attempts distribution, dead-letter list, alarm banner | hermetic route/template test (`fake_repo`) + manual browser UAT | `uv run pytest tests/test_ops_route.py -v` | ❌ W0 — new route, template, test |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Guard non-vacuity obligation (applies to every guard this phase adds)

D-02's collect gate and D-06's AST mutation-target guard are themselves code that can be
silently blind. Each requires **both** halves before it counts as validated:

1. **Red-proof** — a synthetic violation makes the guard fail.
2. **Pinned no-false-positive half** — a conforming case makes it pass.

Reuse the in-repo precedents rather than inventing: `tests/test_bound01_private_imports.py`
and `tests/test_fake_repo_pairing.py` both already carry synthetic-mutation red-proof tests.
Note `git grep -E` silently ignores `\b` — a verification grep has produced false green in
this repo before.

---

## Wave 0 Requirements

- [ ] `pyproject.toml` — register the `proof` marker (mirror the existing `queueproof`
      registration pattern)
- [ ] `tests/test_send_idempotency.py` — new PROOF-03 test (fault injected in the OK-branch
      settlement transaction, after provider-accept)
- [ ] `tests/test_queue_durability.py` — PROOF-04's two incumbents rewritten with genuine OS
      threads under `threading.Barrier`, expiring `leased_until` by direct SQL (no sleep)
- [ ] `.github/workflows/concurrency-proof.yml` — D-02 `--collect-only` completeness step,
      added **without** disturbing the byte-identical shape `tests/test_queue_config.py` pins
- [ ] AST mutation-target guard for D-06 — extend an existing guard file if a natural home
      exists, else new `tests/test_proof_mutation_targets.py`
- [ ] `tests/test_ops_route.py` — hermetic `/ops` route/template test
- [ ] `docs/DURABILITY-PROOFS.md` — evidence document (D-07), linked from README
- [ ] A reachable throwaway Postgres (`DATABASE_URL`) in every executor environment that
      touches a PROOF task

*Framework itself needs no install — pytest, `ast`, `threading`, and psycopg are already
present and exercised in-repo. Zero new dependencies.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Each falsifying mutation produces the **named** expected red | PROOF-01..04 | A mutation is an edit to source, not a test — no gate runs it. **Executed live in-phase, never deferred** (D-05). | Apply the mutation diff → run the proof's command → confirm the *specific named assertion* fails (a red for an unrelated reason is not a falsification) → paste output → revert → confirm byte-identical revert and green. |
| `/ops` visual rendering and numbers-beside-bounds legibility | OPS-01 | Layout/readability judgment (D-12) | Load `/ops`, confirm depth split `pending`/`leased`, oldest-pending age shown against the documented worst-case recovery latency, attempts against `MAX_ATTEMPTS`, and the "as of &lt;timestamp&gt;" stamp. |
| `pump.yml` drain executes **while the alarm is firing** | OPS-01 / D-15 | Requires an actual firing alarm in a workflow run; ordering bug is invisible when the alarm is quiet | Force the alarm condition, run the workflow, confirm the drain step still executed and the alarm step ran last. |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or a Wave 0 dependency
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Live-DB proofs verified **run, not skipped** (`-rs` skip report read)
- [ ] Every added guard has both a red-proof and a pinned no-false-positive half
- [ ] Every falsifying mutation executed in-phase with pasted red + byte-identical revert
- [ ] Feedback latency measured and recorded
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
