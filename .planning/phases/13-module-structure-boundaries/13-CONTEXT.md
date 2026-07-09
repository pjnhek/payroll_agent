# Phase 13: Module Structure & Boundaries - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

The three god-files — `app/main.py` (1,857 lines), `app/db/repo.py` (1,734 lines / ~55 functions), `app/pipeline/orchestrator.py` (1,843 lines) — are decomposed into right-sized, per-concern modules with **zero behavior change**: the full test suite passes after every split with no assertion changes (import-path / patch-target updates only). Cross-module `_private` imports are promoted to deliberate public names (BOUND-01). Requirements: STRUCT-01, STRUCT-02, STRUCT-03, STRUCT-04, BOUND-01.

Locked v3 ordering applies: comments are rewritten in Phase 15 *after* files land in final locations — this phase moves code **verbatim** (no comment editing, no signature changes, no refactoring-while-moving), except where a decision below explicitly says otherwise (TOC deletion, BOUND-01 renames).

</domain>

<decisions>
## Implementation Decisions

### repo.py split (STRUCT-02)
- **D-01:** `repo.py` becomes the package `app/db/repo/` whose `__init__.py` re-exports the full public API — the ~30 call sites doing `from app.db import repo` / `import app.db.repo` and the 14 `monkeypatch.setattr(repo, "fn", ...)` test seams keep working **unchanged**. No temporary facade, no direct-migration churn.
- **D-02:** Right-size to ~5 aggregate modules (not the roadmap's literal three): `runs.py` (lifecycle + status CAS + sweep + error recording with its `_scrub` helpers), `pipeline_state.py` (persist/load extracted/decision/line-items/clarify-round JSONB context), `emails.py` (email_messages + threading/header lookups), `roster.py`, `demo.py` (demo binding + dashboard list queries). Target 200–450 lines each; planner draws exact lines by function affinity, keeping each aggregate's public↔public calls within one module.
- **D-03:** Shared plumbing `_conn_ctx`/`_nulltx` moves to one internal module (e.g. `app/db/repo/_shared.py`); submodules import siblings directly. Facade patching stays safe because no public function calls another public function across aggregates today — **planner must verify this invariant when drawing module lines** so `monkeypatch.setattr(repo, ...)` seams stay intact.
- **D-04:** The hand-maintained 76-line function-index docstring is **deleted at split time** (it would be factually wrong post-split); each new module gets a one-line placeholder docstring. Phase 15 (COMM-02) writes the real module-purpose statements.

### main.py → routers (STRUCT-01)
- **D-05:** Route modules live in `app/routes/`: `webhook.py`, `runs.py`, `dashboard.py`, `demo.py`, `health.py`.
- **D-06:** Grouping is by URL prefix, not read/write: `routes/runs.py` owns **everything under `/runs*`** — list, detail, status poll, approve, reject, resolve, retrigger, paystub PDF, simulate-reply — so the whole operator-gate flow reads in one file. `routes/dashboard.py` owns landing (`/`) + `/eval` + `/eval/chart.svg`. `routes/demo.py` owns `/demo/*` (bind, compose, send-test).
- **D-07:** The shared HTTP→orchestrator bridge (`_run_pipeline`, `_resume_pipeline`, `_route_reply`, `_reply_sender_ok`, `_row_to_inbound`, `_finish_reply_resume`, `_operator_resume`) lands in `app/routes/pipeline_glue.py` with **public names** (feeds BOUND-01). `webhook.py` and `runs.py` import it; tests patch this one obvious seam.
- **D-08:** Final `main.py` is assembly only (~100 lines): create app, register routers, wire startup/shutdown. Jinja templates object + badge filters → `app/routes/templating.py` (routers import it — avoids routers importing `app.main` and circular imports). `_build_alias_rationale_notes` → `routes/runs.py` beside its only caller.

### orchestrator.py split (STRUCT-03)
- **D-09:** Moderate depth — three carve-outs, four concerns total: `app/pipeline/alias_learning.py` (required), `app/pipeline/clarification.py` (`_clarify`, `_combined_context_email`, `_render_asked_summary`, `_defer_field_regression_clarification`), `app/pipeline/delivery.py` (`_deliver`). The core state machine (`run_pipeline`, `_run`, `resume_pipeline`, `_run_stages`, `_compute_line_items`, `backfill_extracted`) **stays** in `orchestrator.py` at ~800–900 lines. The ~600-line resume machinery is deliberately NOT extracted (too coupled to `_run_stages`; money-path risk).
- **D-10:** `alias_learning.py` is the **single home for the learning rule set**: it absorbs `_normalize_candidate`, `_bind_evidence_for_token`, `_write_aliases_if_safe` from orchestrator PLUS `_safe_to_learn_alias` (the misname guard) moves over from `reconcile_names.py`, importing reconcile_names' promoted-public normalize helper. This resolves that name's BOUND-01 violation by relocation.
- **D-11:** Import discipline for every moved function: **module-object imports** — callers do `from app.pipeline import delivery` then `delivery.deliver(...)` — so each function has ONE canonical patch seam on its owning module and every caller resolves through it at call time. Test migration = mechanical retarget of patch paths (57 orchestrator imports across the suite; counts as "import-path updates only" under STRUCT-04).

### BOUND-01 promotion
- **D-12:** Promotion = **rename in place** (`_is_paid` → `is_paid`, `_HOURS_FIELDS` → `HOURS_FIELDS`, `_safe_to_learn_alias` → `safe_to_learn_alias`, `_deliver` → `deliver`), all references updated in the same commit. No `public = _private` alias shims.
- **D-13:** Naming policy: drop-underscore is the default; genuinely cryptic names get a real public name — specifically `_norm` → `normalize_name` (or planner's equally descriptive choice). No semantic changes; rename-only commits.
- **D-14:** Scope = **runtime code only** (`app/`, `eval/`, `scripts/`). Full violation inventory to fix: `orchestrator` ← `reconcile_names._safe_to_learn_alias`, `validate._HOURS_FIELDS`/`._is_paid`, function-body `reconcile_names._norm` (×2, orchestrator lines ~138/~1341); `app/main.py:784` function-body ← `orchestrator._deliver`; `eval/run_eval.py:39` ← `_norm`. Tests may keep importing same-module privates to unit-test internals (~22 files) — promoting internals like `calculate._money` purely for test access would weaken the real APIs. (`import uuid as _uuid` and `import x as _x` local aliases of public names are NOT violations.)
- **D-15:** Add an **automated regression guard** to the existing CI gates so cross-module private imports can't quietly return: ruff's private-import rule (PLC2701) if it works cleanly with the pinned ruff (it's a preview rule), else a small AST-walking test scoped to `app/`, `eval/`, `scripts/`. Mechanism is planner's discretion; the boundary must be enforced, not aspirational.

### Claude's Discretion
- Exact function-to-module assignment inside the ~5 repo aggregate modules (bounded by D-02/D-03 invariants).
- Final public names for promoted helpers beyond the examples in D-12/D-13.
- BOUND-01 guard mechanism (ruff rule vs AST test) per D-15.
- Commit sequencing/granularity — as long as each commit is behavior-neutral, the suite passes at every commit (STRUCT-04), and file moves use `git mv` where practical so history follows.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements & milestone framing
- `.planning/ROADMAP.md` — Phase 13 goal + success criteria 1–5; v3 dependency chain (Phase 12 CI protects these refactors; Phases 14/15 depend on the post-split file locations).
- `.planning/REQUIREMENTS.md` — STRUCT-01..04 and BOUND-01 exact wording; "Out of Scope: any behavior change to pipeline/money logic".

### Prior-phase constraints that bind this phase
- `.planning/phases/12-ci-quality-gates/12-CONTEXT.md` — the CI gates (ruff ruleset E/F/I/B/UP/SIM, line length 100, lint+test on every push, all branches) every split commit must keep green; Phase 14 will extend the same `ci.yml`.

### The three files being split (read before planning, not just grep)
- `app/main.py` — section banners already match the 5 router concerns; shared kickoff/reply helpers at lines ~578–760, HITL routes ~769–1083, `_build_alias_rationale_notes` ~1090.
- `app/db/repo.py` — existing section banners (ingest/lookup, status machine, error+scrub, persistence, email_messages, demo/dashboard, roster); the 76-line TOC docstring (D-04).
- `app/pipeline/orchestrator.py` — alias helpers (~80–175, ~1503–1590), clarify cluster (~937–1090, ~1229–1500), `_deliver` (~1592–1800), `_compute_line_items` (~1801+).

### Tooling rules
- `CLAUDE.md` §Tooling Rule — uv-only; `uv run pytest -q` / `uv run ruff check` for every verification.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `main.py`'s `# ---` section banners already partition routes by the roadmap's 5 concerns — the router split is largely cut-along-the-dotted-lines.
- `repo.py`'s section banners similarly pre-figure the aggregate modules; the intra-repo call graph is clean (only same-aggregate public→public calls: `record_run_error`/`set_clarification_round`/`set_pre_clarify_extracted` → `set_status`, `update_email_message_sent` → `update_email_message_state`, `create_run` → `get_record_only_flag`).
- `app/pipeline/__init__.py` is 6 lines, `app/db/__init__.py` empty — no existing package-level exports to collide with the new facade.

### Established Patterns
- Test seams are module-attribute patches: `monkeypatch.setattr(repo, "fn", ...)` (14×) and orchestrator attribute stubs across 57 imports — D-01/D-11 exist specifically to preserve/retarget these mechanically.
- Both import styles are in use (`from app.db import repo` and `import app.db.repo as repo_mod`) — the package facade satisfies both.
- Execute-phase hazard (from v2 experience): this repo's `.env` has LIVE LLM keys — executor tests must keep stubbing LLM seams (`suggest_employees`, draft calls); never rely on env emptiness.

### Integration Points
- `app/main.py:784` lazy-imports `orchestrator._deliver` inside the retrigger route → becomes a top-level `from app.pipeline import delivery` in `routes/runs.py` (no cycle: routes → pipeline is one-directional).
- `eval/run_eval.py:39` imports `_norm` → retargets to the promoted `normalize_name`.
- Phase 14 (mypy) and Phase 15 (comments) operate on the post-split file layout — module names chosen here are final.

</code_context>

<specifics>
## Specific Ideas

- The audience test for "right-sized": a hiring manager opening `app/routes/runs.py` should see the entire operator-gate flow in one file, and `main.py` should read as textbook app assembly.
- "Behavior-neutral" is defined operationally: the suite passes at every commit with only import-path / patch-target updates — any assertion change means the split leaked behavior.

</specifics>

<deferred>
## Deferred Ideas

- **`ruff format --check` one-time reformat** — Phase 12 noted the cheapest moment is *before* the Phase 13 file moves; it was NOT folded in here (still explicitly out of v3 scope). If ever adopted, do it as its own commit, never mixed with moves.

### Reviewed Todos (not folded)
- All 5 keyword-matched pending todos were already dispositioned in Phase 12's context: `260623-01` (Phase 05 review warnings) and `260623-05` (fixture_category label) → Phase 15 (POLISH-01/02); `260623-02/03/04` (frontend enhancement, paystub YTD, eval-chart restyle) → out of v3 per REQUIREMENTS backlog. Keyword match with Phase 13 is a false positive — none folded.

</deferred>

---

*Phase: 13-Module Structure & Boundaries*
*Context gathered: 2026-07-09*
