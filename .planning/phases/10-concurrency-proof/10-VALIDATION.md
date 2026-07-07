---
phase: 10
slug: concurrency-proof
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-07
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `10-RESEARCH.md` § Validation Architecture (Dimension-8 map).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (dev group, `pyproject.toml` `[dependency-groups].dev`) |
| **Config file** | `pyproject.toml` (markers: `integration`) + `tests/conftest.py` (fixtures + two-factor live-DB guard) |
| **Quick run command** | `uv run pytest -m 'not integration'` (hermetic, DB-free — the capstone is EXCLUDED here by design, D-10-04) |
| **Full suite command** | `uv run pytest` (includes integration when `DATABASE_URL` + `ALLOW_DB_RESET=1` present) |
| **Proof-only command** | `DATABASE_URL=... ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true uv run pytest tests/test_concurrency_proof.py -m integration` |
| **Estimated runtime** | ~5–15 seconds (proof module against local/ephemeral Postgres; hermetic suite unaffected) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -m 'not integration'` (fast, DB-free — the capstone is skipped locally).
- **After every plan wave / phase gate:** the `concurrency-proof.yml` CI job runs the proof against the ephemeral Postgres — green = standing evidence; red = caught regression.
- **Before `/gsd-verify-work`:** Full suite green + the CI proof job green.
- **Max feedback latency:** ~15 seconds (local hermetic) / one CI run (integration proof).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| Surface A | proof | 1 | OPS2-03 | — | No duplicate run per `message_id` (`insert_inbound_email` ON CONFLICT) | integration | `uv run pytest tests/test_concurrency_proof.py -m integration -k dedup` | ❌ W0 | ⬜ pending |
| Surface B | proof | 1 | OPS2-03 | — | No double-approval (`claim_status` CAS via HTTP `/approve`, exactly one `_deliver`) | integration | `uv run pytest tests/test_concurrency_proof.py -m integration -k approval` | ❌ W0 | ⬜ pending |
| Surface C | proof | 1 | OPS2-03 | — | No lost update AND no half-written state (N distinct runs, each atomic) | integration | `uv run pytest tests/test_concurrency_proof.py -m integration -k distinct_runs` | ❌ W0 | ⬜ pending |
| CI job | proof | 1 | OPS2-03 | — | Proof runs (not skipped) against ephemeral Postgres on every push | integration | GitHub Actions `concurrency-proof.yml` green | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### The Four Invariants → Concrete Asserted Conditions

| Invariant | Surface | Concrete asserted condition |
|-----------|---------|------------------------------|
| No duplicate run per `message_id` | A | `len({r["run_id"] for r in results if r.get("run_id")}) == 1` AND exactly one `_run_pipeline` call AND `count(payroll_runs WHERE source_email_id=...) == 1` |
| No double-approval | B | `len(deliver_calls) == 1` (exactly one `_deliver` fired above the CAS) AND run status reaches `approved` exactly once |
| No lost update | C | N distinct `message_id`s → `count(payroll_runs) == N`; every distinct ingest produced exactly one run (none dropped) |
| No half-written state | C | every run row exists WITH its source email row (ingest txn atomicity, D-9-09); each run has non-null `source_email_id` + a matching `email_messages` row (fault-injection half-write proof stays in `test_atomic_persist.py` per D-10-01) |

---

## Wave 0 Requirements

- [ ] `tests/test_concurrency_proof.py` — NEW capstone module covering OPS2-03 (all four invariants across three surfaces).
- [ ] `.github/workflows/concurrency-proof.yml` — NEW CI job with `services: postgres:16` + `pg_isready` health check, runs the proof with `-m integration`.
- [ ] (No framework install gap — pytest + the two-factor guard + `integration` marker + seeded-DB fixture already exist in `tests/conftest.py`.)

---

## Manual-Only Verifications

*All phase behaviors have automated verification.* The proof is self-asserting; the CI job makes it standing evidence. No manual step is required for OPS2-03 beyond reading the green CI badge.

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (the two net-new files)
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s (hermetic) / one CI run (proof)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
