---
phase: 13-module-structure-boundaries
verified: 2026-07-10T03:15:00Z
status: passed
score: 5/5 must-haves verified (BOUND-01 gap closed post-verification — see resolution note in gap below)
overrides_applied: 0
gaps:
  - truth: "BOUND-01's regression-guard artifact (tests/test_bound01_private_imports.py) correctly flags any cross-module private-name reference, including the module._private attribute-access form via BOTH import binding styles used in this codebase (`import X as Y` and `from pkg import Y`)"
    status: resolved
    resolution: >
      Human decision 2026-07-10: fix now (option a). WR-01 fixed in commit 3363ca3
      (facade exemption probes root parents, not scan roots) and WR-02 fixed in commit
      96680cd (attribute scan tracks ImportFrom-bound modules). Fixer re-ran the live
      probes from this verification pass: the facade pattern is no longer flagged, the
      ImportFrom-bound `runs._scrub` probe now fails the gate, the scripts' legitimate
      `repo._conn_ctx` facade accesses stay green, and the live tree passes clean.
      Full suite 615 passed / 50 skipped, ruff clean. See 13-REVIEW-FIX.md.
    reason: >
      The substantive BOUND-01 renames (_norm, _HOURS_FIELDS, _is_paid, _safe_to_learn_alias
      and all Phase 13 promotions) are genuinely done and verified directly against source —
      zero cross-module private-name violations exist in the live app/eval/scripts tree today
      (confirmed with an independently-corrected scanner). However the DELIVERED enforcement
      artifact that is supposed to make this durable has two empirically-reproduced blind spots,
      both independently confirmed against live code in this verification pass (not just
      trusting 13-REVIEW.md's claims):
      (1) WR-01 — the attribute-access facade-boundary exemption (`_is_package_import_target`)
      is dead code: it checks `scan_root / rel_path / "__init__.py"` where `scan_root` is
      already `app/`/`eval/`/`scripts/` (not their parent), so it probes a path like
      `app/app/db/repo/__init__.py` that can never exist. Reproduced live: a probe file doing
      `import app.db.repo as repo_mod; repo_mod._TERMINAL_STATUSES` — the exact pattern the
      facade's own docstring documents as legitimate — is flagged as a violation by the current
      guard.
      (2) WR-02 — the attribute-access scanner only tracks module bindings from `ast.Import`
      nodes, never `ast.ImportFrom`. Any `from module import X` followed by `X._private(...)`
      is invisible to the guard, in ANY module, for ANY target — proven both with a synthetic
      cross-package probe (`from app.pipeline import clarification; clarification._x()` —
      zero violations reported) and against REAL, LIVE production code already in the scan
      roots: `scripts/reset_stuck_runs.py:34`, `scripts/show_confirmation_subject.py:16`, and
      `scripts/demo_reset.py:139/168/188` all bind `repo`/`_repo` via `from app.db import repo`
      (module-level or function-body) and then call `repo._conn_ctx(...)` — none of these
      four real call sites are seen by the scanner at all (not even evaluated against the
      exemption logic).
      Net effect: the guard's "fails the build if one is found" must-have (13-04-PLAN.md
      frontmatter) is not true for the codebase's dominant import-binding idiom
      (`from app.X import Y`), which is also the exact idiom this very phase's own plans
      mandated ("module-object imports... from app.pipeline import alias_learning") as the
      norm going forward. A future regression using this idiom (e.g. `from app.routes import
      demo; demo._some_new_private_helper()`) would pass CI silently.
    artifacts:
      - path: "tests/test_bound01_private_imports.py"
        issue: "_is_package_import_target (line ~171-178) computes a facade-exemption check against the wrong base path (scan root instead of scan root's parent), making the exemption unreachable; _scan_attribute_violations (line ~181-225) builds bound_modules from ast.Import only, never ast.ImportFrom, so the codebase's dominant `from module import X` binding style is entirely outside the attribute-access scan's visibility"
    missing:
      - "Fix _is_package_import_target to probe root_parent (REPO_ROOT) rather than the scan root itself, so the declared facade exemption actually reaches its intended branch"
      - "Extend bound_modules construction in _scan_attribute_violations to also record ast.ImportFrom bindings (module-level and function-body) whose resolved target is a first-party module/package under app/eval/scripts, applying the same (now-fixed) facade exemption uniformly"
      - "Add a synthetic-fixture regression case pinning both fixes (an ImportFrom-bound private-attribute access that must be flagged, and a package-import-via-ImportFrom-or-Import case that must be exempted) so this exact blind spot cannot silently regress again"
deferred: []
human_verification:
  - test: "Decide whether the BOUND-01 guard gaps (WR-01 dead-code exemption, WR-02 ImportFrom-attribute blind spot) block phase closure or are accepted as a tracked follow-up before Phase 14 begins"
    expected: "Either: (a) a quick gap-closure plan patches tests/test_bound01_private_imports.py per the REVIEW.md fixes and re-verifies, or (b) the developer explicitly accepts the current guard as good-enough for now (it does correctly catch the two violation shapes it was designed around in the synthetic fixture, and the LIVE tree has zero actual violations today under a corrected scanner) and this is tracked as a documented, deliberate risk before Phase 14/15 land more code that could exploit the blind spot"
    why_human: "This is a judgment call about risk tolerance for a CI-enforcement artifact, not a money-path bug — the underlying substantive requirement (no private cross-module imports in the live codebase) is independently verified TRUE right now; the gap is entirely about the guard's ability to catch a FUTURE regression using an import idiom this phase itself established as the norm. Whether that risk is acceptable to defer is a project-priority decision, not a fact this verifier can resolve unilaterally under the escalation-gate pattern."
---

# Phase 13: Module Structure & Boundaries Verification Report

**Phase Goal:** The three largest files in the codebase (app/main.py ~1,822 lines, app/db/repo.py ~1,765 lines / 55 functions, app/pipeline/orchestrator.py ~1,845 lines) are decomposed into right-sized, per-concern modules that read as intentional architecture rather than accretion, with no behavior change anywhere and no private cross-module imports left over.
**Verified:** 2026-07-10T03:15:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `app/main.py` is thin app assembly with routers split by concern (STRUCT-01) | VERIFIED | `wc -l app/main.py` = 16 lines; contains only `FastAPI()`, static mount, 5 `app.include_router(...)` calls; `grep -n "def \|async def " app/main.py` returns zero matches; `TestClient(app).get('/health/live')` returns 200 (spot-checked live in this pass) |
| 2 | `app/db/repo.py` is split into per-aggregate modules behind a stable import surface (STRUCT-02) | VERIFIED | `app/db/repo.py` no longer exists; `app/db/repo/` package has 6 files (`__init__.py`, `_shared.py`, `runs.py`, `pipeline_state.py`, `emails.py`, `roster.py`, `demo.py`); both `from app.db import repo` and `import app.db.repo as repo_mod` resolve identical objects and the full live attribute surface (`_scrub`, `_conn_ctx`, `get_connection`, `_TERMINAL_STATUSES`, `_ACCENT_CLASS_MAP`, `_pad_references`) — spot-checked live in this pass |
| 3 | Alias-learning helpers are carved out of `orchestrator.py` into their own module (STRUCT-03) | VERIFIED | `app/pipeline/alias_learning.py` exists (222 lines) exporting `normalize_candidate`, `bind_evidence_for_token`, `write_aliases_if_safe`, `safe_to_learn_alias`; `orchestrator.py` trimmed from 1,845 to 1,029 lines, importing `alias_learning`/`clarification` as module objects |
| 4 | Every split is behavior-neutral — full suite passes throughout, import-path-only changes (STRUCT-04) | VERIFIED | `uv run pytest -q` → 615 passed, 50 skipped (665 collected = 612 pre-split baseline + 2 new guard tests); `uv run ruff check .` → zero violations; independently re-run in this verification pass, not taken from SUMMARY claims |
| 5 | No private cross-module imports remain, enforced by a working AST guard (BOUND-01) | **PARTIAL** | The substantive renames are done and the live tree has zero actual cross-module private-name violations (independently re-verified with a corrected scanner in this pass). BUT the delivered guard (`tests/test_bound01_private_imports.py`) has two proven blind spots (dead-code facade exemption; `ImportFrom`-bound attribute access entirely invisible) that mean it would not catch a real future regression using this codebase's dominant import idiom — see Gaps below |

**Score:** 4/5 truths fully verified, 1 partially verified (substance true, enforcement mechanism incomplete)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/main.py` | thin app assembly | VERIFIED | 16 lines, no route handlers |
| `app/routes/{webhook,runs,dashboard,demo,health,pipeline_glue,templating}.py` | 5 routers + 2 shared modules | VERIFIED | All 8 files exist; `TestClient` smoke test passes; `route_reply` called only from `runs.py::simulate_reply`, never from `webhook.py::inbound` (grep-confirmed live) |
| `app/db/repo/__init__.py` + 5 aggregate modules + `_shared.py` | package facade replacing flat repo.py | VERIFIED | 6 files exist; facade re-exports full live attribute surface; `grep -c "^def " app/db/repo/__init__.py` = 0 |
| `app/pipeline/{alias_learning,clarification,delivery}.py` | carved-out orchestrator modules | VERIFIED | All 3 exist; `orchestrator.py` calls them via module-object imports (`alias_learning.fn`, `clarification.fn`); `delivery.deliver` called from `app/routes/runs.py::approve` |
| `tests/test_bound01_private_imports.py` | AST-walking BOUND-01 regression guard | ⚠️ **PARTIAL** — exists, passes both its own tests, but its live-tree scan has two proven blind spots (dead facade exemption for attribute access; `ImportFrom`-bound attribute access entirely unscanned) that were independently reproduced against the live repo in this verification pass, not merely cited from 13-REVIEW.md |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `app/routes/webhook.py::inbound` | `app/routes/pipeline_glue.py::finish_reply_resume` | module-object import | VERIFIED | `grep -n "finish_reply_resume" app/routes/webhook.py` hits; `grep -n "route_reply" app/routes/webhook.py` returns zero |
| `app/routes/runs.py::approve` | `app/pipeline/delivery.py::deliver` | module-object import | VERIFIED | `from app.pipeline import delivery` present in `runs.py`; call site confirmed |
| `app/db/repo/_shared.py::_conn_ctx` | `app/db/repo/__init__.py::get_connection` | call-time package self-import | VERIFIED (per SUMMARY + facade surface spot-check); not independently re-driven via monkeypatch in this pass but facade attribute presence confirmed live |
| `app/pipeline/orchestrator.py::resume_pipeline/_run_stages` | `alias_learning`/`clarification` modules | module-object import | VERIFIED | Both modules importable; orchestrator trimmed to expected KEEP list |
| `tests/test_bound01_private_imports.py` | live `app/`, `eval/`, `scripts/` trees | `ast.walk` static scan | ⚠️ PARTIAL | Scan executes and passes today (zero violations found), but is proven — via direct probe execution in this verification pass — to miss a whole class of live, real code patterns (`from app.db import repo; repo._conn_ctx(...)` in 3 `scripts/*.py` files) and to have dead exemption logic for the attribute-access form it does check |

### Data-Flow Trace (Level 4)

Not applicable in the conventional sense (no UI/dynamic-data rendering artifacts in this phase) — the equivalent check here is the guard's actual detection behavior against live source, which was traced and reproduced directly (see Behavioral Spot-Checks / Probe Execution below) rather than trusted from the review document.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green | `uv run pytest -q` | 615 passed, 50 skipped | ✓ PASS |
| Ruff clean | `uv run ruff check .` | "All checks passed!" | ✓ PASS |
| App boots + health route | `TestClient(app).get('/health/live')` | 200 | ✓ PASS |
| Repo facade full attribute surface | direct import + hasattr checks | all present | ✓ PASS |
| BOUND-01 named violations gone from live code | `grep -rn "_norm\b\|_HOURS_FIELDS\b\|_is_paid\b\|_safe_to_learn_alias\b" app/ eval/ scripts/` | only `calculate.py`'s own unrelated `_HOURS_FIELDS` + docstring/comment mentions remain | ✓ PASS |
| BOUND-01 guard facade-exemption reachability (WR-01 reproduction) | probe file `import app.db.repo as repo_mod; repo_mod._TERMINAL_STATUSES` under `app/` scanned with the live guard | flagged as a violation (should have been exempt per the facade pattern the guard's own docstring documents as legitimate) | ✗ FAIL (confirms WR-01) |
| BOUND-01 guard ImportFrom-binding blind spot (WR-02 reproduction) | probe file `from app.db import repo; repo._scrub('x')` under `app/`, scanned with the live guard | zero violations reported (should have been evaluated, even if ultimately exempt) | ✗ FAIL (confirms WR-02) |
| BOUND-01 guard blind spot against a genuine non-facade violation | probe file `from app.pipeline import clarification; clarification._some_private_helper()` under `app/`, scanned with the live guard | zero violations reported — a genuine, non-exempt cross-module private access is invisible | ✗ FAIL (confirms the blind spot is general, not facade-specific) |
| Corrected scanner (fixing both WR-01/WR-02) against the live tree | custom script tracking `ast.ImportFrom` bindings too, with the exemption check fixed | 0 violations found | ✓ PASS (confirms the SUBSTANTIVE BOUND-01 goal — zero actual violations today — is true; only the guard's durability is in question) |

### Probe Execution

No `scripts/*/tests/probe-*.sh` convention exists in this project; the "probes" for this phase are the ad-hoc verification scripts run directly against `tests/test_bound01_private_imports.py`'s own detection functions (see Behavioral Spot-Checks above), executed in this verifier's own process, not sourced from SUMMARY.md narration.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| STRUCT-01 | 13-03 | main.py split into APIRouter modules by concern, thin assembly | ✓ SATISFIED | 16-line main.py, 5 routers, TestClient smoke test |
| STRUCT-02 | 13-01 | repo.py split into per-aggregate modules with stable import surface | ✓ SATISFIED | package + facade verified live |
| STRUCT-03 | 13-02 | alias-learning helpers carved into own module | ✓ SATISFIED | `alias_learning.py` verified |
| STRUCT-04 | 13-01/02/03/04 | every split behavior-neutral, full suite passes | ✓ SATISFIED | 615 passed / 50 skipped, ruff clean, independently re-run |
| BOUND-01 | 13-02/03/04 | private cross-module imports promoted; no function-body private imports remain | ⚠️ PARTIALLY SATISFIED | Substantive renames done and verified (no live violations); the guard meant to enforce this durably has two proven detection gaps (WR-01, WR-02), independently reproduced in this verification pass |

No orphaned requirements found — `.planning/REQUIREMENTS.md`'s Phase 13 mapping (STRUCT-01..04, BOUND-01) matches exactly what the four plans' frontmatter `requirements:` fields declare collectively.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `tests/test_bound01_private_imports.py` | ~171-178 | `_is_package_import_target` probes the wrong base path, making the facade exemption unreachable | ⚠️ Warning | Guard would false-positive on any future legitimate `import <package> as X; X._private` pattern outside the currently-hardcoded `app.db.repo` ImportFrom-only carve-out |
| `tests/test_bound01_private_imports.py` | ~181-225 | `bound_modules` only tracks `ast.Import`, never `ast.ImportFrom` | ⚠️ Warning | Guard is blind to the codebase's dominant `from module import X` binding idiom for the attribute-access check — a real class of future regression would pass CI silently |
| `app/routes/runs.py` / `app/routes/pipeline_glue.py` | runs.py:786-797, pipeline_glue.py:126-131 | Inverted outcome logging on `simulate_reply`'s demo-only diagnostic path (pre-existing bug, moved verbatim, not introduced by Phase 13) | ℹ️ Info | Diagnostics-only, no behavior/security impact; carried forward from `356fc41`, not a Phase 13 regression |
| `tests/test_bound01_private_imports.py` docstring | ~44-46 | Docstring claims facade re-exports `_nulltx`; it does not | ℹ️ Info | Cosmetic |
| various | — | Stale docstring cross-references to pre-split file locations (`app/main.py`'s old approve() route, `_row_to_inbound`) | ℹ️ Info | Cosmetic, does not affect behavior |

Advisory/style-only items from 13-REVIEW.md (IN-02 redundant `import uuid as _uuid`, IN-03 redundant exception tuple) are not re-litigated here per the task's instruction — they don't bear on goal achievement.

### Human Verification Required

#### 1. BOUND-01 guard gap disposition

**Test:** Review the two independently-reproduced guard blind spots (WR-01: dead facade exemption; WR-02: `ImportFrom`-bound attribute access entirely unscanned) and decide whether to (a) execute a small gap-closure plan fixing `tests/test_bound01_private_imports.py` per the fixes already prescribed in `13-REVIEW.md`, or (b) explicitly accept the current guard as sufficient for now and proceed to Phase 14.
**Expected:** A decision recorded (either a follow-up gap plan, or an explicit override added to this VERIFICATION.md's frontmatter accepting the current guard state).
**Why human:** This is a risk-tolerance / prioritization judgment about a CI-enforcement artifact's completeness, not a fact this verifier can resolve — the underlying substantive requirement (zero private cross-module imports in the live codebase right now) is independently confirmed TRUE, so nothing is currently broken in production code. The exposure is entirely forward-looking (a future regression using the codebase's now-standard `from module import X` idiom would not be caught).

### Gaps Summary

Phase 13's three god-file decompositions (main.py, repo.py, orchestrator.py) are genuinely, verifiably complete: every claimed artifact exists, every claimed module-object-import wiring is real, the full test suite is green at the exact pre-split baseline plus the two new guard tests, ruff is clean, and a live `TestClient` smoke test confirms the app still boots and serves. STRUCT-01 through STRUCT-04 are all independently verified true against the codebase, not merely asserted by SUMMARY.md.

BOUND-01 is more nuanced: the four originally-named violations (`_norm`, `_HOURS_FIELDS`, `_is_paid`, `_safe_to_learn_alias`) are genuinely promoted and gone from live code, and an independently-corrected version of the scanner confirms zero actual cross-module private-name violations exist in `app/`, `eval/`, `scripts/` today. But the specific enforcement artifact this phase built to make that fact durable — `tests/test_bound01_private_imports.py` — has two proven, reproduced detection gaps that mean it cannot be trusted to catch a real regression of the exact kind BOUND-01 exists to prevent, using the exact import idiom this very phase established as this codebase's new norm. This was flagged as a WARNING (not a blocker) by the code review, and this verification independently reproduced both gaps against live code (not scoped-down synthetic fixtures) to confirm they are real rather than theoretical. Per the escalation-gate pattern, this is surfaced to the developer for a decision rather than silently passed or silently blocked.

---

_Verified: 2026-07-10T03:15:00Z_
_Verifier: Claude (gsd-verifier)_
