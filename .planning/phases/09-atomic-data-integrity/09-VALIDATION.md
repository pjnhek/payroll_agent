---
phase: 9
slug: atomic-data-integrity
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-03
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv) |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest -q -m "not integration"` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30 seconds (offline); integration tests require live DB |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -m "not integration"`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| (filled by planner) | | | DATA-01/02/03 | | | | | | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Live-DB-gated (`@pytest.mark.integration`) test scaffolding for atomicity (SC1) and dedup race (SC2) — follows the existing `tests/test_claim_status.py` pattern
- [ ] Crash-injection fixture (forced exception between writes) for transaction-boundary tests

*FakeConnection (offline double) cannot prove atomicity — only SQL shape; SC1/SC2 require integration-marked tests per RESEARCH.md.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (filled by planner if any) | | | |

*Default: all phase behaviors have automated verification (offline + integration-gated).*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 60s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
