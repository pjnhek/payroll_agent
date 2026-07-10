---
phase: 14
slug: full-type-checking-mypy
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-10
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing suite; Phase 13 verified full-suite reference: 615 passed / 50 skipped — capture the live baseline in-session, never pin) + mypy 2.2.0 (installed this phase) |
| **Config file** | `pyproject.toml` (mypy + pydantic plugin config lands this phase) |
| **Quick run command** | `uv run mypy app/` |
| **Full suite command** | `uv run mypy && uv run pytest -q` (bare mypy — scope from pyproject.toml `files=`, per D-06 parity) |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run mypy app/` (or the directory the task touched)
- **After every plan wave:** Run `uv run mypy && uv run pytest -q` (bare mypy per D-06)
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01 T1-T3 | 14-01 | 1 | TYPE-01/02 | T-14-01/02/03 | mypy config authored; D-08 bug fixed test-first; gateway Protocol+cast (targeted attr-defined assertion); federal_withholding.py annotation fix | static + unit | `uv run mypy --version`, `uv run pytest tests/test_eval_wiring.py tests/test_gateway.py -q` | ✅ | ⬜ pending |
| 14-02 T1-T3 | 14-02 | 2 | TYPE-01 | T-14-04/05 | app/config.py, app/models/, app/llm/, then app/db/ (incl. repo/) mypy-clean — import-graph task order | static + unit | `uv run mypy app/__init__.py app/config.py app/models/ app/llm/ app/db/`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-03 T1-T3 | 14-03 | 3 | TYPE-01 | T-14-06/07/08/09a | app/pipeline/ + app/email/ (gateway residuals) mypy-clean, one D-09 ignore | static + unit | `uv run mypy app/pipeline/ app/email/`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-04 T1-T3 | 14-04 | 4 | TYPE-01 | T-14-09/10 | app/routes/ + app/main.py mypy-clean | static + unit | `uv run mypy app/routes/ app/main.py`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-05 T1-T2 | 14-05 | 4 | TYPE-02 | T-14-11/12 | eval/, scripts/ mypy-clean; scripts proven executable via py_compile only (no DB-touching script runs) | static + unit | `uv run mypy eval/ scripts/`, `uv run python -m py_compile scripts/*.py`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-06 T1-T2 | 14-06 | 5 | TYPE-02 | T-14-13 | tests/ group 1 (19 files + tests/__init__.py) mypy-clean; dynamic baseline + assert-diff proof | static + unit | `uv run mypy <group1 files>`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-07 T1-T2 | 14-07 | 5 | TYPE-02 | T-14-14 | tests/ group 2 (18 files incl. conftest.py) mypy-clean; fixture implementations checked (no cross-file inference claim) | static + unit | `uv run mypy <group2 files>`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-08 T1-T2 | 14-08 | 5 | TYPE-02 | T-14-15 | tests/ group 3 (18 files) mypy-clean; strict file ownership (no out-of-scope fixes) | static + unit | `uv run mypy <group3 files>`, `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-09 T1 | 14-09 | 6 | TYPE-01/02 | T-14-16/16b | full-repo integration gate: bare `uv run mypy` exits 0; residual fixes documented, solo wave | static + unit | `uv run mypy` (bare, D-06 parity), `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 14-10 T1-T4 | 14-10 | 7 | TYPE-03 | T-14-17/18/SC | typecheck CI job wired, red-proofed with exact single-cause snippet; VERIFICATION.md committed post-checkpoint | integration (CI red-proof) | `gh run view` on master + red-proof branch; `git ls-remote --heads origin red-proof/mypy-14` empty | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements — pytest suite is live; mypy itself is the new verification tool and its installation is a phase task, not a Wave 0 stub.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| CI blocking mypy job actually fails a bad push | TYPE-03 | CI behavior only observable on a real push | Push a branch with a deliberate type error (or verify job wiring mirrors the Phase 12 lint job exactly); confirm the workflow run fails on the mypy step |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** replanned 2026-07-10 (Codex cross-AI review incorporated) — 10 plans across 7 waves (14-01..14-10); waves follow mypy's import traversal; dedicated integration gate (14-09) precedes CI wiring (14-10); all TYPE-01/02/03 requirements covered; full sign-off pending execution.
