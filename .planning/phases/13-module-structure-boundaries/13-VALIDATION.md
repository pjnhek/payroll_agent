---
phase: 13
slug: module-structure-boundaries
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-09
updated: 2026-07-09
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv) |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest -q -x` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~60 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -x`
- **After every plan wave:** Run `uv run pytest -q` (collected-test count must equal the baseline captured at plan start via `uv run pytest --collect-only -q` — 663 at planning time; use the live captured value, not a hardcoded number)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 13-01-01 | 01 | 1 | STRUCT-02 | T-13-xx (repo split) | facade patches still intercept intra-package calls | suite | `uv run pytest -q` | ✅ | ⬜ pending |
| 13-01-02 | 01 | 1 | STRUCT-02, STRUCT-04 | — | test retargets only import paths, zero assertion changes | suite | `uv run pytest -q` (count parity vs captured baseline) | ✅ | ⬜ pending |
| 13-02-01 | 02 | 2 | STRUCT-03, BOUND-01 | T-13-05..08 | verbatim moves; PII-safe logging preserved; module-object seams | suite | `uv run pytest -q` | ✅ | ⬜ pending |
| 13-02-02 | 02 | 2 | STRUCT-03, STRUCT-04 | — | full census retarget (13 test files) with zero assertion changes | suite | `uv run pytest -q` (count parity vs captured baseline) | ✅ | ⬜ pending |
| 13-03-01 | 03 | 3 | STRUCT-01 | webhook transaction boundary (inbound → pipeline_glue.finish_reply_resume, never route_reply) | Phase 9 dedup/race guarantee unchanged | suite | `uv run pytest -q` | ✅ | ⬜ pending |
| 13-03-02 | 03 | 3 | STRUCT-01, STRUCT-04 | — | route parity + test retargets only import paths | suite | `uv run pytest -q` (count parity vs captured baseline) | ✅ | ⬜ pending |
| 13-04-01 | 04 | 4 | BOUND-01, STRUCT-04 | AST guard scope (ImportFrom + module._private attribute access) | zero cross-module private imports repo-wide | unit + suite | `uv run pytest -q tests/test_bound01_private_imports.py && uv run pytest -q && uv run ruff check .` | ✅ (created by task) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements — the 663-test suite is the behavior-neutrality oracle for every split, and the BOUND-01 AST guard test is created by task 13-04-01 (including its `tmp_path`-based synthetic-fixture unit test). No pre-execution test stubs required.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| _none_ | | | |

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task verified)
- [x] Wave 0 covers all MISSING references (none)
- [x] No watch-mode flags
- [x] Feedback latency < 90s (single full-suite run ~60s)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-09
