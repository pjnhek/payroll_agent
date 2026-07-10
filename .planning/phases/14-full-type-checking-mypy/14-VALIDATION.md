---
phase: 14
slug: full-type-checking-mypy
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-10
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (existing suite, ~596 tests) + mypy 2.2.0 (installed this phase) |
| **Config file** | `pyproject.toml` (mypy + pydantic plugin config lands this phase) |
| **Quick run command** | `uv run mypy app/` |
| **Full suite command** | `uv run mypy . && uv run pytest -q` |
| **Estimated runtime** | ~60–120 seconds |

---

## Sampling Rate

- **After every task commit:** Run `uv run mypy app/` (or the directory the task touched)
- **After every plan wave:** Run `uv run mypy . && uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (filled by planner) | — | — | TYPE-01/02/03 | — | N/A | static + unit | `uv run mypy .` / `uv run pytest -q` | ✅ | ⬜ pending |

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

**Approval:** pending
