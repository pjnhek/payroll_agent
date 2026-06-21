# Phase 2 (Walking Skeleton) — Overnight Autonomous Run Report

**Run date:** 2026-06-21 (overnight)
**Scope authorized:** Plan → 3-round Codex review → execute → live smoke-test → code-review loop, full-auto, stop on hard blocker.
**Outcome:** ✅ Everything buildable is built, reviewed, and green. **One item waits for you: the live hero-fixture run (D-A4-01a).**

---

## TL;DR

- **Phase 2 is fully implemented** — all 19 requirements Complete, **168 tests passing** (12 env-gated integration/live tests skip by design).
- The **code-gated thesis works**: the LLM can say `process`, but `decide.py` blocks a sub-0.8-confidence name (and empty extractions, and one-to-one collisions). Verified in code (`orchestrator` never reads `model_action`) and by tests.
- **Cross-AI plan review (Codex/gpt-5.5) ran 3 rounds** and caught real contract/safety bugs before any code was written.
- **Code review ran 2 rounds** on the built code, found **2 Critical + 6 Warning** real bugs, fixed them all with regression tests, and re-reviewed CLEAN.
- **Live providers are reachable** — creds + model IDs resolve (one caveat below).
- **Phase is intentionally NOT marked complete** — the live hero run is a human gate.

---

## What's waiting for you (the one human gate)

**The live hero-fixture run — D-A4-01a.** The mocked suite proves the *gate* (given a sub-0.8 input, code blocks). Only a live run against real DeepSeek/Kimi proves the *demo* ("the model was willing; the code said no"). This needs your eyes because two failure modes are invisible to tests:
- the real model might self-clarify (gate never fires → weaker story), or
- return confidence ≥0.8 (a mismatch sails through on camera).

**To do it:**
1. Confirm the exact DeepSeek/Kimi non-reasoning model IDs + the DeepSeek non-thinking request param from the consoles, pin in `.env`. (Smoke-test below suggests the current values already work — but the empty-content caveat is worth a look.)
2. Run: `ALLOW_LIVE_LLM=1 .venv/bin/python -m pytest tests/test_live_llm.py::test_hero_fixture_live -m live_llm -x`
3. Expected: real model matches `David Reyez → David Reyes`, returns `process` at sub-0.8 → gate fires → `final_action == request_clarification`.
4. If it self-clarifies or returns ≥0.8: tune the submitted-name variant and/or the reconcile prompt, repeat. This is a judgment loop, not pass/fail.
5. For the recording, capture the exact good run (hosted APIs aren't bit-deterministic even at temp 0).

When it genuinely produces *model-says-process AND gate-blocks*, the phase can be verified/closed (`/gsd-verify-work 2` then mark complete).

---

## Live provider smoke-test (post-build)

All three tiers resolve and respond (HTTP 200, creds valid, model IDs real):

| Tier | Model | Base | Result |
|------|-------|------|--------|
| EXTRACTION | `deepseek-v4-flash` | api.deepseek.com | ✅ 200 — **returned empty content** |
| DECISION | `moonshot-v1-8k` | api.moonshot.ai/v1 | ✅ `ok` |
| DRAFT | `moonshot-v1-8k` | api.moonshot.ai/v1 | ✅ `ok` |

**Caveat to check:** DeepSeek (extraction tier) returned empty content on a trivial prompt. This is a *known DeepSeek quirk* the code already handles (reflective-retry covers empty content), but it's the tier most sensitive to the non-thinking-mode parameter being wired right. Worth confirming the non-thinking toggle is correct before the hero run — extraction field accuracy is one of your three headline eval metrics (Phase 4).

This substantially de-risks the old "provider IDs unconfirmed" blocker — the IDs in `.env` work.

---

## What got built (4 plans, 4 waves, sequential)

| Wave | Plan | Built | Tests after |
|------|------|-------|-------------|
| 1 | 02-01 substrate | LLM client (per-tier, JSON mode, 1 reflective retry, DeepSeek non-thinking), stub email gateway, full DB repo surface, `reconciliation`+`error_reason` columns, `live_llm` marker | 89 |
| 2 | 02-02 clean path | webhook+BackgroundTasks, 4 pure judgment stages, **the code gate (`decide.py`)**, thin gross+FICA (net pre-federal), orchestrator state machine, crude approve/reject (HITL-01) | 129 |
| 3 | 02-03 gate-block | layer-2 LLM reconcile (`NameReconciliationResponse` wrapper), one-to-one mapping (LLM-09), clarify draft+send, **David Reyez hero fixture** | 145 |
| 4 | 02-04 resume loop | header-chain reply routing, sender revalidation (anti-spoof), idempotent+lossless resume, late-reply observability, reply injection | 159 |
| — | code-review fixes | 2 Critical + 6 Warning bugs fixed with regression tests | **168** |

The four judgment stages are pure (no DB) so Phase 4's eval can reuse the exact production functions.

---

## Cross-AI plan review — Codex/gpt-5.5 (3 rounds, converged)

Ran *before* any code, on the plans:
- **Round 1:** 12 findings — contract mismatches (`non_numeric` unreachable through the typed path; `PaystubLineItem` is `extra="forbid"` so "pre-federal" can't be a field; Message-ID storage anchor conflict), plus **two genuine correctness/safety bugs**: partial-reply resume losing original hours, and reply-sender spoofing bypassing access control. All applied.
- **Round 2:** 1 HIGH — `Extracted.run_id` contradiction (stages claimed "no run_id" but the contract requires it). Resolved: `run_id` is code-owned plumbing; the LLM returns an `ExtractionPayload` without it. Applied.
- **Round 3:** CLEAN — READY FOR EXECUTION.

This is the cross-AI review paying off: a different, capable model caught real bugs the internal checker missed.

## Code review — on the built code (2 rounds, converged)

- **Round 1:** 2 Critical + 6 Warning, all verified real (I checked each against the source):
  - **CR-01:** empty-extraction (`employees: []`) bypassed the gate → a junk/prompt-injected email + model `process` could reach approval as an empty payroll. **Fixed** (gate now fails closed on zero employees).
  - **CR-02:** resume could clobber an approved run via a status race → discarding human approval. **Fixed** (status precondition guards the mutation; webhook pre-flip removed).
  - 6 Warnings: silent employee-drop, unanchored Message-ID match, draft-API-error handling, terminal-status clobber, dead param, misleading rounding comment.
- **Round 2:** CLEAN — all 8 resolved with tests, no regressions.

---

## Judgment calls made (so you can override if you disagree)

1. **`use_worktrees=false` for the run** — the 4 plans are a strict linear chain (1/wave), so worktree isolation buys no parallelism and adds merge fragility. Ran sequentially on the main tree. Config restored afterward (no persistent change).
2. **Skipped the 5 Info code-review findings** — style/footgun notes, not bugs. Deferred.
3. **WR-06 rounding:** the fixer corrected a misleading comment but did NOT change monetary rounding (kept `ROUND_HALF_UP`, the standard payroll convention). Changing it would silently alter every paystub — a human call, not an unattended edit.
4. **CR-02 residual race:** the fix is a status-precondition, not a row-locked (`SELECT … FOR UPDATE`) check — `repo.py` has no locked-load helper in Phase 2. Full atomicity is deferred to Phase 5 idempotency work (where CLAR-04/INGEST-05 live). WR-04 is the defense-in-depth backstop.

---

## Carried-forward / open

- **Provider model IDs + DeepSeek non-thinking param** — smoke-test says they work, but confirm the non-thinking toggle before the hero run (empty-content caveat above). Legacy `deepseek-chat`/`deepseek-reasoner` retire 2026/07/24 — never alias.
- **Phase not closed** — pending the live hero run. After it passes: `/gsd-verify-work 2`, then the phase can be marked complete and you're clear for Phase 3 (Harden the Calc — real Pub 15-T federal withholding).

---

## Artifacts (all committed)

- Plans: `02-0{1..4}-PLAN.md` · Context/Research/AI-SPEC/Patterns/Validation
- `02-REVIEWS.md` (3-round Codex plan review) · `02-REVIEW.md` + `02-REVIEW-R2.md` (2-round code review)
- `02-0{1..4}-SUMMARY.md` (per-plan execution summaries)
- 25 source files under `app/` (~2900 LOC) + test suite (168 passing)
