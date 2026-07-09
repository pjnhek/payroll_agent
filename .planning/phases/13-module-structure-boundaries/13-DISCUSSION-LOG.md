# Phase 13: Module Structure & Boundaries - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 13-Module Structure & Boundaries
**Areas discussed:** repo.py import surface, Router decomposition shape, Orchestrator split depth, BOUND-01 promotion mechanics

---

## repo.py import surface

### Q1 — How should the split repo.py present itself to callers?

| Option | Description | Selected |
|--------|-------------|----------|
| Package facade | repo.py becomes package app/db/repo/ with per-aggregate submodules; __init__.py re-exports the public API; callers + 14 monkeypatch seams unchanged | ✓ |
| Direct migration, no facade | New flat modules; every caller/test updated; ~50+ files touched | |
| Temporary facade, then remove | Facade for split commits, then migrate callers and delete it | |

### Q2 — How strictly follow the roadmap's three aggregates?

| Option | Description | Selected |
|--------|-------------|----------|
| Right-size, ~5 modules | runs.py, pipeline_state.py, emails.py, roster.py, demo.py; error-scrub helpers with record_run_error; 200–450 lines each | ✓ |
| Exactly three (runs/emails/roster) | Literal roadmap reading; runs.py stays ~1,000 lines | |
| You decide at plan time | Planner picks boundaries, capped at ~500 lines/module | |

### Q3 — Shared plumbing and internal-call wiring?

| Option | Description | Selected |
|--------|-------------|----------|
| Private core + direct imports | _conn_ctx/_nulltx in one internal module; siblings import directly; planner verifies no cross-aggregate public call | ✓ |
| Everything through the facade | Guarantees patch interception, costs circular-import risk | |
| Duplicate the plumbing per module | Copies ~20 lines into each module; violates DRY | |

### Q4 — The 76-line function-index docstring during the split?

| Option | Description | Selected |
|--------|-------------|----------|
| Drop it at split time | Delete index; one-line placeholder docstrings; Phase 15 writes real ones | ✓ |
| Split the index per module | Keeps hand-maintained style until Phase 15 | |
| Write final docstrings now | Does COMM-02 early; violates locked v3 ordering | |

---

## Router decomposition shape

### Q1 — Where do the five APIRouter modules live?

| Option | Description | Selected |
|--------|-------------|----------|
| app/routes/ | Short, conventional, mirrors existing per-concern packages | ✓ |
| app/routers/ | FastAPI-docs-literal naming | |
| app/web/ | 'Web adapter' framing (routes + templates + filters) | |

### Q2 — /runs pages vs HITL POST actions grouping?

| Option | Description | Selected |
|--------|-------------|----------|
| All /runs* together | routes/runs.py owns list, detail, status, approve, reject, resolve, retrigger, PDF, simulate-reply; dashboard.py owns landing + /eval | ✓ |
| Pages vs actions | GET pages in dashboard.py, POST actions in runs.py | |
| You decide | Planner groups by measured coupling | |

### Q3 — Where do the shared pipeline-kickoff/reply-routing helpers land?

| Option | Description | Selected |
|--------|-------------|----------|
| app/routes/pipeline_glue.py | One shared HTTP→orchestrator bridge module, public names, one patch seam | ✓ |
| app/pipeline/entrypoints.py | Pipeline-side API; but helpers do HTTP-ish work | |
| Duplicate into each router | ~200 lines duplicated; listed for completeness | |

### Q4 — How thin must final main.py be?

| Option | Description | Selected |
|--------|-------------|----------|
| Assembly only, ~100 lines | Templates/filters → app/routes/templating.py; _build_alias_rationale_notes → routes/runs.py | ✓ |
| Assembly + templating stays | Routers import from app.main; circular-import risk | |
| You decide | Bounded by: no handlers in main.py, no cycles | |

---

## Orchestrator split depth

### Q1 — How deep beyond the required alias carve-out?

| Option | Description | Selected |
|--------|-------------|----------|
| Moderate: 4 concerns | alias_learning.py + clarification.py + delivery.py carved; core state machine stays ~800–900 lines | ✓ |
| Minimum: alias carve-out only | Least money-path risk; leaves a 1,600-line orchestrator | |
| Full: also split resume machinery | Extracts ~600-line resume_pipeline; highest churn in trickiest code | |

### Q2 — What does alias_learning.py own?

| Option | Description | Selected |
|--------|-------------|----------|
| One home for learning | Absorbs the three orchestrator helpers PLUS _safe_to_learn_alias from reconcile_names | ✓ |
| Orchestrator helpers only | _safe_to_learn_alias promoted in place; rule set stays split | |
| You decide | Planner traces shared state/normalization | |

### Q3 — Import discipline for moved functions?

| Option | Description | Selected |
|--------|-------------|----------|
| Module-object imports | `from app.pipeline import delivery` + `delivery.deliver(...)`; one canonical patch seam | ✓ |
| Direct name imports | Each importer holds its own binding; classic mock-target bug risk | |
| You decide | Per call site, based on current stubbing | |

---

## BOUND-01 promotion mechanics

### Q1 — How are private names promoted?

| Option | Description | Selected |
|--------|-------------|----------|
| Rename in place | _is_paid → is_paid etc., all references in same commit; no shims | ✓ |
| Public alias, keep private impl | `is_paid = _is_paid`; two names for one thing | |

### Q2 — Does BOUND-01 extend to test files?

| Option | Description | Selected |
|--------|-------------|----------|
| Runtime code only | app/, eval/, scripts/ (incl. eval/run_eval.py _norm); tests keep same-module private imports | ✓ |
| Full sweep including tests | Promotes ~8 genuinely-internal helpers for test access | |
| Tests via public seams | Rework tests; violates 'import-path updates only' | |

### Q3 — Naming policy for promoted names?

| Option | Description | Selected |
|--------|-------------|----------|
| Descriptive where cryptic | Drop underscore by default; _norm → normalize_name | ✓ |
| Minimal: drop underscore only | Ships 'norm' as public API | |
| You decide per name | Planner proposes; rename-only commits | |

### Q4 — Automated regression guard?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, guard it | ruff PLC2701 if clean with pinned ruff, else small AST-walking test; wired into existing CI | ✓ |
| No, review-only | Zero tooling cost; invariant regresses silently | |

---

## Claude's Discretion

- Exact function-to-module assignment inside the ~5 repo aggregate modules (bounded by the no-cross-aggregate-public-call invariant).
- Final public names for promoted helpers beyond the agreed examples.
- BOUND-01 guard mechanism (ruff PLC2701 vs AST test).
- Commit sequencing/granularity — behavior-neutral at every commit, `git mv` where practical.

## Deferred Ideas

- `ruff format --check` one-time reformat (Phase 12 deferred idea; cheapest before the moves but still explicitly out of v3 scope).
- The 5 keyword-matched pending todos were confirmed already-dispositioned (Phase 15 / out of v3) — not folded.
