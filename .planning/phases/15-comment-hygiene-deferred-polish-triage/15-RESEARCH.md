# Phase 15: Comment Hygiene & Deferred-Polish Triage - Research

**Researched:** 2026-07-10
**Domain:** Internal codebase cleanup (comment/docstring sweep, guard test, deferred-todo triage)
**Confidence:** HIGH (codebase-inventory research; every claim below verified by grep/read against the working tree at commit 0f276d1)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Rewrite policy (COMM-01, COMM-03)**
- **D-01:** **Keep constraint, drop label.** Every ticket comment is judged on content: if it documents a real constraint/invariant/edge case, it is rewritten as plain maintainer-facing English with the ticket reference removed; pure provenance (who/when/which review/where code migrated from) is deleted entirely. The codebase's unusually rich why-documentation is preserved — only its process vocabulary goes.
- **D-02 (money-path depth):** In money-path files (`calculate.py`, `tax_tables_2026.py`, `decide.py`, `delivery.py`, and money-relevant comments elsewhere), surviving comments keep **full depth — constraint AND failure mode** (e.g. "using the MFJ table for MFS would halve withholding"). The consequence narration is what stops a future "simplification" from reintroducing a mispay; do not trim it.
- **D-03 (provenance beyond ticket IDs):** All project-process references are stripped the same as ticket IDs — phase numbers ("Phase 3"), review rounds ("review round 2", "review fix"), planning-doc citations ("PATTERNS.md", "RESEARCH Security Domain"), split history ("post-split", "migrated from X per D-02"). A comment must stand alone for a maintainer who has never seen `.planning/`. **External authoritative citations stay** (IRS Pub 15-T PDF URL, SSA wage-base URL, provider API docs) — they are sources, not process history.
- **D-04 (docstring shape):** Module docstrings get a 1–2 sentence **purpose statement**; modules with genuine invariants (e.g. `_shared.py`'s "parameterized SQL only, never f-string SQL"; `decide.py`'s "pure code, no LLM, no confidence") add a **short invariants paragraph**. No history, no TOC-style function indexes (COMM-02: the split DB modules get their real module-purpose statements now, per Phase 13 D-04's placeholder handoff).

**Sweep scope (COMM-01 widened)**
- **D-05:** The sweep covers the **whole codebase**: `app/*.py`, `app/db/schema.sql`, `app/templates/`, `eval/`, `scripts/`, `tests/`, and maintainer-facing Markdown inside the code tree (e.g. `eval/fixtures/DIVERGENCES.md`) — all under the same D-01 rule. `.planning/`, phase artifacts, README changelog-ish content, and git history remain the provenance record and are untouched.
- **D-06 (test names):** Test function names lose their ticket-ID prefixes — `test_cr01_explicit_zero_overpay_guard...` → `test_explicit_zero_overpay_guard...`. Pure renames, no assertion changes; where the ticket ID is the only meaningful part of a name, invent a descriptive scenario name. The suite passing unchanged (same count) is the neutrality proof.

**Regression guard (new invariant)**
- **D-07:** A **pytest guard test** (precedent: `tests/test_bound01_private_imports.py`) scans swept sources for ticket-ID patterns and fails on any hit. It runs inside the existing CI test job — no `ci.yml` change — and doubles as the sweep's completion proof (COMM-01 success criterion becomes executable).
- **D-08 (patterns):** Guard blocks **ticket-shaped patterns only**: `D-<n>`/`D-21-01`-style IDs, `WR-`/`CR-`/`CX-`/`GAP-<n>`, `FIX <n>/<letter>`, `Pitfall #<n>`, `(review fix)`, and capital-P `Phase <n>`. Natural prose ("fix the rounding", "this phase of parsing") must pass. Tune the final regex set against the swept corpus for zero false positives on the final tree.
- **D-09 (guard scope):** Guard scans **exactly what the sweep cleaned** (D-05 file set), excluding `.planning/` and the guard's own pattern table.

**POLISH-01 — todo 260623-01 triage**
- **D-10:** **WR-01 (threading after crash+retrigger) is verified by a hermetic regression test**: drive crash → retrigger → outbound send and assert the reply-threading anchor (Message-ID chain) survives the `(run_id, purpose)` upsert. If the test exposes a real break, fix it under the test-first money-path protocol (failing test commit, then minimal fix — never buried in comment commits). Phase 11 reworked this machinery, so verify against current source first; "verified by reading" alone is not acceptable (Phase 10 vacuous-proof lesson).
- **D-11:** **WR-02** (pool singleton): confirm the Phase 8 fix in current source and close — verification note only.
- **D-12:** **Fix cheap+real, disposition the rest** for the remaining items, each first verified against current code (later phases may have incidentally fixed them): WR-04 (Content-Disposition filename sanitization), WR-05 (path-containment check on eval summary/fixture reads), INFO-01 (`needs_clarification` badge-map entry), INFO-02 (scrub ValidationError content from the LLM retry prompt) get small test-first fixes if still present. **WR-03** (runs-list `SELECT pr.*` JSONB over-fetch) is **dispositioned as accepted** — perf-only, invisible at demo scale — with a written rationale in the todo closure. Todo 260623-01 is then closed with an explicit per-item disposition record.

**POLISH-02 — todo 260623-05**
- **D-13:** Fixture 10's `fixture_category` becomes **`"typo"`** — matches the established six-category eval taxonomy (exact / stored-alias / first-time-alias / typo / collision / unknown); "Jame Okafor" is a typo of roster "James Okafor". Verify: eval re-run shows per-category chart grouping still reads correctly, and no test asserts `category=="exact"` for fixture 10. Todo 260623-05 closed.

### Claude's Discretion
- Exact guard-test implementation (regex table, file walker, failure message wording) within D-07..D-09.
- Per-comment keep-vs-delete judgment within the D-01 bar; final wording of rewritten comments and docstrings.
- Commit sequencing/granularity — comment-only commits must be cleanly separated from any POLISH behavior-fix commits (D-10/D-12), and the suite + mypy + ruff stay green at every commit.
- Where the POLISH disposition records live (todo closure notes vs phase VERIFICATION.md) — standard GSD artifacts.
- Whether trivially-empty `__init__.py` files need docstrings at all.

### Deferred Ideas (OUT OF SCOPE)
- **Clean multi-employee PROCESS fixture** (all names resolve → straight-through 2-employee approval demo) — floated in todo 260623-05; a new capability, not polish. Backlog.
- Reviewed todos not folded: `260623-02` (frontend progressive enhancement), `260623-03` (paystub YTD columns), `260623-04` (eval-chart restyle) — out of v3 per REQUIREMENTS.md Future Requirements.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| COMM-01 | Ticket-ID/provenance comments stripped across `app/` (widened to whole codebase per D-05), constraints preserved as plain comments | §Ticket-Comment Inventory (exact per-file counts + pattern list + non-comment hit locations); §Guard Test Design (executable success criterion) |
| COMM-02 | repo.py 76-line function-index docstring style replaced with short module-purpose statements across split DB modules | §Module Docstring Survey — TOC already deleted at split; current draft docstrings quoted with the exact provenance strings to strip |
| COMM-03 | Module docstrings state purpose and invariants, not phase history | §Module Docstring Survey — per-module invariants worth keeping identified |
| POLISH-01 | Todo 260623-01 resolved/dispositioned (WR-01 verified, WR-02 confirmed closed) | §POLISH-01 Current-State Verification — every item (WR-01..05, INFO-01/02) checked against live source with file:line evidence |
| POLISH-02 | Fixture 10 `fixture_category` corrected; eval chart grouping verified unaffected | §POLISH-02 — grouping code points, hermetic regeneration flow, `--check` gate interaction, no test couples to the label |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **uv-only tooling:** every verification command is `uv run pytest -q` / `uv run ruff check` / `uv run mypy` — never pip/venv/`.venv/bin/python`. No `requirements.txt`.
- **No behavior change to pipeline/money logic** (REQUIREMENTS.md Out of Scope) — the POLISH fixes (D-10/D-12) are the sanctioned, test-first exception.
- **GSD workflow enforcement:** work proceeds through `/gsd-execute-phase`; no direct edits outside it.
- **Live-key hazard:** this repo's `.env` has LIVE LLM keys — executors must keep LLM seams stubbed (`suggest_employees` etc.); never rely on env emptiness (memory: execute-phase integration hazards).
- **Comment conventions that survive the sweep:** `noqa`/`type: ignore[code]` comments carry mandatory reason text (Phase 12 D-03 / Phase 14 D-09) — rewrite the reason in plain English, never delete the rationale or the code qualifier.

## Summary

This is a codebase-inventory phase, not a web-research phase. Three workstreams: (1) a whole-codebase provenance-comment sweep (~682 matching lines under `app/`+`eval/`+`scripts/` with the broad pattern set, ~1,096 in `tests/`, 46 in `schema.sql`, plus 1 CSS + 2 template + 3 DIVERGENCES.md hits), rewritten under D-01's keep-constraint-drop-label rule; (2) a new pytest guard test making COMM-01 executable, modeled on `tests/test_bound01_private_imports.py`; (3) closing two v2 todos — of whose seven sub-items **four are already fixed or obsolete in current source** (WR-02, WR-03, WR-04, INFO-01) and only three need action (WR-01 hermetic regression test, WR-05 path-containment check, INFO-02 retry-prompt scrub), plus the fixture-10 relabel with a mechanical hermetic eval regeneration.

The highest-risk item is WR-01: Phase 11 rewrote the upsert machinery the original finding targeted (`insert_email_message` now arbitrates on `(run_id, purpose, round, epoch)` — a retrigger *inserts a new row* instead of mutating history), so the finding's premise may be stale, but D-10 requires proof by hermetic test, not by reading. The second-highest risk is guard-test false positives: ticket-shaped strings live not only in comments but in **runtime string literals** (test failure messages like `"FIX C: bare assert..."`, `run_eval.py`'s argparse description `"Payroll Agent eval scorer -- Phase 4"`) — the sweep must rewrite those too or the guard will fail on its own corpus.

**Primary recommendation:** Plan the sweep file-by-file in descending hit-count order with the guard test written FIRST (red) so the sweep drives it green; run the three POLISH code fixes as separate test-first plans before or parallel to comment-only plans, never interleaved in the same commit.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Comment/docstring sweep | Source tree (all tiers' files) | — | Text-only edits; no runtime behavior change permitted |
| COMM guard test | CI / test suite | — | Pytest source-scanner beside `test_bound01_private_imports.py`; runs in existing CI test job (D-07, no ci.yml edit) |
| WR-01 regression test | Test suite (hermetic) | API/backend seams | Drives `POST /runs/{run_id}/retrigger` (app/routes/runs.py:266) + repo email seams via `fake_repo`/`mock_llm` fixtures |
| WR-05 / INFO-02 fixes | API/backend | — | `app/routes/dashboard.py` path containment; `app/llm/client.py` prompt scrub |
| Fixture-10 relabel | Eval tooling | Dashboard (display only) | `eval/fixtures/*.json` + regenerated `summary.json`/`chart.svg`; `eval.html:54` renders the category badge |

## Standard Stack

No new libraries. This phase uses only tooling already in the repo:

### Core
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| pytest | dev dep (uv.lock) | Guard test + WR-01 regression test + suite-green proof | Existing test framework; guard precedent already lives in `tests/` [VERIFIED: repo] |
| ruff | dev dep, `select = ["E","F","I","B","UP","SIM"]`, line-length 100 | Green-at-every-commit gate | Committed config in pyproject.toml; **no docstring (D) or commented-code (ERA) rules selected**, so ruff imposes nothing on comment content — only E501 line length applies to rewritten comments [VERIFIED: pyproject.toml:46-59] |
| mypy | strict, `files = ["app","eval","scripts","tests"]` | Green-at-every-commit gate | Comment-only edits are invisible to mypy EXCEPT `# type: ignore[code]` placement — moving/deleting one breaks strict mode (`warn_unused_ignores`) [VERIFIED: pyproject.toml:61-77] |
| matplotlib | dev dep | `run_eval.py --chart` regeneration for POLISH-02 | Already used by the chart writer [VERIFIED: eval/run_eval.py:988] |

**Installation:** none — `uv sync` as-is.

## Package Legitimacy Audit

Not applicable — this phase installs no external packages. All work uses the existing locked dependency set.

## Ticket-Comment Inventory (COMM-01/D-05 sweep surface)

Measured against the working tree with pattern set `D-[0-9]|WR-[0-9]|CR-[0-9]|CX-[0-9]|GAP-[0-9]|FIX[ -][0-9A-Z]|Pitfall|review fix|Phase [0-9]|R2-[0-9]|PATTERNS\.md` (broader than CONTEXT.md's ~293 estimate because it includes `Phase <n>`, planning-doc citations, and R2 rounds — all in scope per D-03). [VERIFIED: grep, 2026-07-10]

### app/, eval/, scripts/ — 682 matching lines, per file (descending)

| File | Hits | File | Hits |
|------|------|------|------|
| app/pipeline/orchestrator.py | 110 | app/routes/webhook.py | 16 |
| app/pipeline/clarification.py | 46 | app/pipeline/compose_email.py | 15 |
| app/routes/runs.py | 42 | app/pipeline/reconcile_names.py | 14 |
| eval/run_eval.py | 40 | app/pipeline/decide.py | 12 |
| app/db/repo/runs.py | 39 | eval/judge.py | 11 |
| app/db/repo/emails.py | 34 | app/pipeline/suggest.py | 10 |
| app/models/contracts.py | 32 | app/db/bootstrap.py | 9 |
| app/pipeline/delivery.py | 31 | app/llm/client.py | 8 |
| app/pipeline/calculate.py | 31 | app/pipeline/extract.py, app/llm/prompts/extract.py | 7 each |
| app/db/repo/pipeline_state.py | 25 | app/routes/demo.py | 6 |
| app/db/seed.py | 24 | app/routes/health.py | 5 |
| app/routes/pipeline_glue.py | 21 | app/models/status.py, app/email/clean.py, app/db/supabase.py | 4 each |
| app/pipeline/validate.py | 21 | scripts/* (3 files) | 8 total |
| app/pipeline/alias_learning.py | 21 | app/config.py, tax_tables_2026.py, federal_withholding.py, dashboard.py, templating.py, llm/prompts/clarify.py | 3 each |
| app/models/roster.py | 21 | remaining (repo/demo.py, pdf.py, _shared.py, routes/__init__.py, prompts/suggest.py, prompts/__init__.py) | ≤2 each |
| app/email/gateway.py | 18 | | |

### tests/ — 1,096 matching lines across 51 files

Top: test_resume_pipeline.py (115), test_alias_write.py (66), conftest.py (60), test_persistence.py (49), test_gateway.py (45), test_cr_regressions.py (45), test_federal_withholding.py (42), test_models_contracts.py (41), test_threading.py (38), test_validate.py (37). Full list obtainable with the same grep. [VERIFIED: grep]

### Non-Python surfaces (in D-05 scope)

| Surface | Hits | Detail |
|---------|------|--------|
| `app/db/schema.sql` | 46 | `--` comments citing D-8-09, WR-08, D-02/D-03, D-A3-05/D-21-06, Phase 11 (D-11-01)… [VERIFIED: grep] |
| `app/templates/run_detail.html` | 2 | Line 108 "(demo only — Phase 6 uses real inbound webhook)" (user-visible label text!) and line 176 Jinja comment "D-7.5-08: provenance badge macro" [VERIFIED: grep] |
| `app/static/style.css` | 1 | Line 289 `/* needs_operator (D-11-06): … */` — **not in CONTEXT.md's measured surface; add to sweep** [VERIFIED: grep] |
| `eval/fixtures/DIVERGENCES.md` | 3 | "(D-06)" metric citations — maintainer-facing markdown in the code tree, in scope per D-05 [VERIFIED: read] |

### Ticket-shaped strings that are NOT comments (must be rewritten before the guard can pass)

These will trip a text-scanning guard and are part of the sweep:

- `tests/test_calculate.py:348-350` — assertion **message string** `"FIX C: bare assert must not remain in calculate.py source…"` [VERIFIED: read]
- `eval/run_eval.py:1083` — argparse description **runtime string** `"Payroll Agent eval scorer -- Phase 4"` [VERIFIED: read]
- Many test failure-message strings across `tests/` embed WR-/CR-/D- IDs (e.g. `test_status_drift.py:200-201`, `test_clarify.py:362`).
- `# noqa: BLE001 — D-13b defensive isolation` style comments (e.g. app/pipeline/delivery.py:~93): keep `noqa: BLE001` + a plain-English reason, drop `D-13b` (Phase 12 D-03 convention).
- `# type: ignore[attr-defined]  # private re-export binding, see comment above` (tests/test_eval_wiring.py:148) and the WR-04-rationale ignore in delivery (Phase 14 D-09): rewrite reasons, never delete.

### Test function names embedding ticket IDs (D-06)

**32 test functions** match `test_.*(cr\d|wr\d|cx\d|fix\d|d\d+_|gap\d|r2)` [VERIFIED: grep]. Concentrations: `tests/test_cr_regressions.py` (13: cr01/cr02/cr03/clar207 prefixes), `tests/test_resume_pipeline.py` (6: cr01/cr02), `tests/test_cr01_classify_union.py` (3), plus singletons in test_atomic_persist (`test_deliver_finalize_crash_preserves_wr04_payroll_roster_attribute`), test_compose_email_field_regression (`test_field_regression_line_d7509_wording`, `test_d7509_wording_present_even_when_llm_draft_nonempty`), test_reply_redelivery (2 × `fix5`), test_retrigger_epoch, test_multiround_context_edge, test_round2 names in test_atomic_persist. **Two test FILE names also embed IDs** (`test_cr_regressions.py`, `test_cr01_classify_union.py`, `test_bound01_private_imports.py`) — D-06 speaks only to function names; renaming files is Claude's-discretion territory but note `test_bound01_private_imports.py` guards requirement BOUND-01, a REQUIREMENTS.md ID, not a review-ticket ID (BOUND-01 is arguably a requirement name like CLAR-01/DASH-01 that appear in docstrings throughout). **The planner must decide whether requirement IDs (CALC-03, CLAR-04, DASH-01, BOUND-01, COMM-01) count as "ticket-shaped"** — D-08's pattern list does NOT include them, so the guard should not block them; recommend leaving requirement-ID references out of the guard but sweeping the prose around them per D-01 judgment. [VERIFIED: grep + D-08 pattern list]

### CI test-name coupling check (rename safety)

Workflows reference test **files**, not function names: `deploy-migrate.yml` runs `tests/test_schema_introspect.py`, `concurrency-proof.yml` runs `tests/test_concurrency_proof.py -m integration`. No `-k` name filters anywhere. Function renames are CI-safe; if test files are renamed, these two workflow references must be checked (neither file is on the rename list). [VERIFIED: .github/workflows grep]

## Module Docstring Survey (COMM-02/COMM-03)

The Phase 13 TOC deletion already happened — **no 76-line function index survives**; COMM-02 is a rewrite-in-place of draft docstrings. Current state of the split DB modules [VERIFIED: read]:

| Module | Current docstring | What to strip / keep |
|--------|-------------------|---------------------|
| `app/db/repo/_shared.py` | Purpose + SQL discipline | Strip "(PATTERNS.md / RESEARCH Security Domain)"; KEEP the invariant "%s / named placeholders ONLY, NEVER f-string SQL" (D-04 names this as a genuine invariant). `_conn_ctx`'s function docstring explains the package-attribute monkeypatch seam — keep the seam explanation (it's a real constraint), strip nothing else needed |
| `app/db/repo/runs.py` | One-line purpose (clean) | Module docstring fine; the `RUN_COLS` block comment cites CR-02/OPS2-01/CR-01 (phase-8 review) — rewrite as "a column missing from this constant is invisible to every load_run caller" constraint, drop IDs |
| `app/db/repo/emails.py` | One-line purpose (clean) | `insert_email_message` docstring is dense with D-11-01/D-13c/GAP-2/Pitfall #1 — KEEP the arbiter/constraint-drift invariant and the epoch rationale (money-path adjacent, D-02 depth), drop IDs |
| `app/db/repo/roster.py` | One-line purpose (clean) | Minor: "(no SELECT * — extra=forbid)" comments fine as-is |
| `app/db/repo/pipeline_state.py` | Purpose (clean) | `persist_extracted` docstring says "(review fix)" — strip |
| `app/db/repo/demo.py` | Purpose (clean) | `load_all_runs` docstring cites D-8-07/OPS2-02/T-8-07/review fix #2/T-8-12 — KEEP the explicit-column and jsonb_typeof-guard rationale (it explains why a bare COALESCE errors), drop IDs |
| `app/db/repo/__init__.py` | Facade re-export surface + monkeypatch-seam caveat | KEEP the seam invariant (facade-level patch does not intercept same-module internal calls — tests depend on this being documented accurately, per 13-CONTEXT); strip "post-split" |

Other notable module docstrings: `app/db/supabase.py` (D-04 gotcha + WR-02 + 08-RESEARCH.md citations around genuinely load-bearing prepare_threshold/Supavisor and double-checked-locking rationale — keep substance, strip IDs and the "08-RESEARCH.md Open Question 1" citation); `app/routes/templating.py` ("(D-08)" in line 1); `app/routes/dashboard.py` ("(D-06)", "R2-MEDIUM fix", "D-21"); `eval/run_eval.py` header (clean purpose, but body has ~40 ID hits and "D-13 exact label wording" / "D-12" chart annotations).

## POLISH-01 Current-State Verification (todo 260623-01, per D-10..D-12)

Every item verified against live source this session. **Four of seven items need no code change.**

| Item | Current state | Evidence | Disposition per CONTEXT |
|------|--------------|----------|------------------------|
| **WR-01** threading after crash+retrigger | **Machinery reworked by Phase 11 — original premise likely stale, but must be proven by test (D-10).** The upsert arbiter is now `(run_id, purpose, round, epoch)`; a retrigger bumps `reply_epoch` so the fresh send **INSERTs a new row** instead of mutating the historical one — the exact overwrite WR-01 feared is structurally prevented for the retrigger case; an in-round retry (same epoch) still upserts `message_id = EXCLUDED.message_id` in place by design | app/db/repo/emails.py:57-96 (arbiter + DO UPDATE), retrigger route app/routes/runs.py:266, durable References chain rebuilt from DB via `get_outbound_references_chain` (app/email/gateway.py:240-250), confirmation threads on `inbound.message_id` (app/pipeline/delivery.py, in_reply_to/references at the send call) | Write the hermetic regression test anyway: crash → `POST /runs/{id}/retrigger` → outbound send; assert the outbound's In-Reply-To/References anchor to the client's inbound Message-ID survives. Existing partial coverage: `test_retrigger_epoch.py::test_retrigger_sends_fresh_clarification_despite_stale_round0_sent_row`, `test_threading.py` header-chain tests — **none asserts the post-retrigger outbound threading headers end-to-end**, so the new test is not redundant |
| **WR-02** pool singleton | **FIXED (Phase 8) — verify+close.** Double-checked locking with `_pool_lock = threading.Lock()`, outer check + inner re-check under lock | app/db/supabase.py:27-66 (comments even cite WR-02) | D-11: verification note only. Sweep will strip the WR-02 labels from these very comments while keeping the DCL rationale |
| **WR-03** `SELECT pr.*` over-fetch | **ALREADY FIXED (Phase 8, D-8-07/OPS2-02) — the CONTEXT's "disposition as accepted" is stale.** `load_all_runs` selects an explicit scalar column list + two SQL-computed aliases (`summary_gate_reason`, `employee_count` with jsonb_typeof guard); no JSONB blob reaches the list view | app/db/repo/demo.py:140-172 | Disposition record should say "fixed in Phase 8, verified in current source" rather than "accepted" — stronger closure than D-12 anticipated, consistent with D-12's own "verify against current code first" instruction |
| **WR-04** Content-Disposition injection | **ALREADY FIXED.** `safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"` with a full latin-1 rationale; security regression test exists | app/routes/runs.py:673-685; tests/test_dashboard.py:381-423 (asserts no CRLF reaches the header) | Verify+close. Sweep strips "CR-01 (REVIEW-2/3)" labels, keeps the re.ASCII failure-mode narration (money-path-adjacent depth per D-02) |
| **WR-05** path containment on eval reads | **STILL PRESENT — small fix needed.** `eval_view` builds `fixtures_dir / fixture["fixture_path"]` from summary.json content with **no containment check**; `summary.json`/`chart.svg` reads are static relative paths (safe). Attack surface requires a tampered committed summary.json (low), but D-12 says fix cheap+real | app/routes/dashboard.py:112-122 | Test-first fix: resolve and check `.is_relative_to(fixtures_dir.resolve())` before reading; render the missing-file fallback otherwise |
| **INFO-01** `needs_clarification` badge entry | **OBSOLETE — the status does not exist.** `needs_clarification` is absent from `RunStatus` (app/models/status.py) and `tests/test_status_drift.py::test_needs_clarification_absent_file_wide` **enforces its absence** in schema.sql. Both badge maps `.get()` with safe defaults, so any unknown status renders gracefully. Adding the entry would contradict the drift guard's intent | app/routes/templating.py:19-58; app/models/status.py:17-34; tests/test_status_drift.py:192-201 | Disposition: N/A/obsolete — the finding predates the status's removal. (Side observation: `_BADGE_CLASS`/`_BADGE_LABEL` contain a `"computing"` entry that matches no RunStatus member — dead entry; removing it is optional polish, flag for planner discretion since it's behavior-neutral either way given the `.get()` defaults) |
| **INFO-02** ValidationError echoed to provider | **STILL PRESENT — small fix needed.** Retry prompt is `f"Your last output failed validation: {exc}. "` — a Pydantic ValidationError's str includes the offending input values (model output echoed back verbatim) | app/llm/client.py:185 | Test-first fix: send a scrubbed summary (e.g. error count + field locations + expected types, no input values), or `exc.errors(include_input=False, include_url=False)` — pydantic v2 supports `include_input=False` [ASSUMED — verify the pydantic 2.13 `errors()` signature during planning]. Keep the one-retry contract untouched |

## POLISH-02 — Fixture 10 relabel (todo 260623-05, D-13)

**Fixture facts** [VERIFIED: read]:
- `eval/fixtures/10_multi_employee_coastal.json` has `"fixture_category": "exact"`, body submits "Maria Chen" (exact) + "Jame Okafor" (typo of "James Okafor"), expected `final_action` = clarification. Relabel to `"typo"` per D-13.
- `"typo"` is an existing category (fixture 05), so the relabel merges fixture 10 into an existing group — no new chart bucket.
- Full fixture_category population (12 values, richer than the six-name taxonomy): exact, stored-alias, collision, unknown, typo, first-time-alias, missing-hours, vague-hours, buried-reply, zero-hours-hourly, nfc-normalizer-parity, field-drop-clarify. The "six-category taxonomy" in D-13 refers to the per-NAME reconciliation taxonomy (`per_category_reconciliation` has exactly those six); fixture_category is a wider fixture-level label. `"typo"` is valid in both framings.

**Code that consumes fixture_category** [VERIFIED: grep+read]:
- `eval/run_eval.py:474` — copied into the per-fixture record.
- `eval/run_eval.py:494` (`_aggregate`, extraction grouping) and `:583` (decision grouping) — `cat = r["fixture_category"]`. **Relabeling moves fixture 10 from the "exact" group to the "typo" group in `per_category_extraction` AND `per_category_decision`.**
- `per_category_reconciliation` groups by per-NAME category (six buckets), NOT fixture_category — unaffected by the relabel.
- `app/templates/eval.html:54` — renders the category as a badge in the dashboard drill-in table (display-only).
- **No test references fixture 10 or asserts its category** — `grep "10_multi\|multi_employee_coastal" tests/` returns nothing; `fixture_category` appears in no test. The D-13 verify item "no test asserts category=='exact' for fixture 10" is confirmed satisfied. [VERIFIED: grep]

**The `--check` gate interaction (the one sequencing constraint):**
- CI (`eval.yml`) runs `uv run python eval/run_eval.py --check` on push, **hermetically** — extraction comes from committed `*_extraction.json` caches, no LLM, no DB (`ALLOW_LIVE_LLM` intentionally unset). [VERIFIED: .github/workflows/eval.yml:28-32]
- `_assert_regression` compares "ALL scored metrics" of fresh vs committed summary.json — since per-category aggregates change with the relabel, **`--check` fails until summary.json is regenerated and committed in the same change**.
- Regeneration flow (fully hermetic, no live keys): edit the fixture → `uv run python eval/run_eval.py` (rewrites summary.json from caches) → `uv run python eval/run_eval.py --chart` (rewrites chart.svg; matplotlib dev dep) → `uv run python eval/run_eval.py --check` (green) → commit fixture + summary.json + chart.svg together. [VERIFIED: run_eval.py main() flow, lines 1081-1169]
- Note: `eval/fixtures/DIVERGENCES.md` documents that fixture 10's extraction cache deliberately contains a phantom employee ("John Smith") to exercise the precision metric — the relabel does not touch the cache; extraction scores are unchanged, only their grouping bucket moves. The chart's typo group will absorb fixture 10's sub-1.0 extraction scores — "grouping still reads correctly" means the typo bar reflects n=2 with fixture 10's scores included, which is the honest reading.

## Guard Test Design (D-07..D-09) — implementation facts

- **Precedent:** `tests/test_bound01_private_imports.py` (576 lines) — module-docstring spec, `SCAN_ROOTS = ["app", "eval", "scripts"]`, `REPO_ROOT` from `__file__`, one live-tree test + one synthetic self-proof test against `tmp_path`. The COMM guard should mirror: pattern table constant, file walker over the D-05 set, live-tree scan test, synthetic-corpus self-test. [VERIFIED: read]
- **Scan set (D-05/D-09):** `app/**/*.py`, `app/db/schema.sql`, `app/templates/*.html`, `app/static/*.css` (see style.css hit), `eval/**/*.py`, `eval/fixtures/*.md`, `scripts/*.py`, `tests/**/*.py` — excluding the guard's own file (or just its pattern table). BOUND-01's scanner excludes `tests/` (D-14 there); **the COMM guard must INCLUDE `tests/`** since D-05 sweeps it — a scan-scope difference from the precedent worth calling out in the plan.
- **False-positive corpus to tune against (D-08):**
  - `Phase <n>` capital-P in runtime strings (`run_eval.py:1083` argparse) — must be swept, not exempted.
  - Requirement IDs (`CALC-03`, `CLAR-04`, `DASH-01`, `BOUND-01`, `COMM-01`, `EMAIL-01`, `LLM-05`, `UAT #3/#4`, `T-8-07`-style task IDs, `OPS2-01`, `D-A3-05`) — D-08's blocklist covers only `D-<n>`, `WR-`, `CR-`, `CX-`, `GAP-<n>`, `FIX <n>/<letter>`, `Pitfall #<n>`, `(review fix)`, `Phase <n>`. `D-A3-05`, `D-7.5-08`, `D-9-08`, `D-11-01`, `D-13b/c`, `D-21-01` all match a well-written `D-` pattern (e.g. `\bD-[0-9A-Za-z.]+`). Requirement IDs and `T-`/`OPS`/`NEW-1`/`Codex HIGH-2`/`finding #1`/`R2-MEDIUM` mentions do NOT match D-08's list — the sweep should still rewrite them under D-01/D-03 (they are process provenance), but the guard won't enforce them. Planner choice: either widen the guard patterns (risk: false positives) or accept guard-enforces-subset + sweep-covers-all. Recommend the latter to honor D-08's "ticket-shaped patterns only, zero false positives."
  - Legit prose that must pass: "fix the rounding", "this phase of parsing", "phases" lowercase, `round` variables, "fixture" ids like `f0000010`.
  - `# noqa`/`# type: ignore[...]` comment codes themselves (e.g. `BLE001`, `attr-defined`) must never match.
- **schema.sql comment safety:** `app/db/schema_introspect.py` strips `--` line comments before parsing (`_strip_line_comments`, lines 37-38, applied at 135) — **comment-only edits to schema.sql cannot affect the schema-parity check or deploy-migrate CI**. [VERIFIED: read]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Comment-pattern enforcement | pre-commit hook / ci.yml step / ruff plugin | Plain pytest guard test beside test_bound01 (D-07 locks this) | Rides the existing CI test job; self-documenting; the precedent's synthetic self-test pattern proves the scanner works |
| ValidationError scrubbing (INFO-02) | Custom regex over `str(exc)` | Pydantic v2 `exc.errors(include_input=False, include_url=False)` then format loc/type only [ASSUMED — confirm kwargs exist in pydantic 2.13] | Structured API is version-stable vs string-format scraping |
| Path containment (WR-05) | String prefix checks on paths | `Path.resolve()` + `Path.is_relative_to()` (stdlib, py≥3.9) | Handles `..`, symlinks, case; one-liner |

## Runtime State Inventory (refactor-phase requirement)

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — comments/docstrings/test names exist only in source files; no DB rows, Mem0/vector stores, or JSONB payloads contain ticket IDs (Decision/Extracted schemas are `extra="forbid"` contracts with no comment fields) | none |
| Live service config | None affected — Render/Resend/Supabase config carries no ticket IDs. schema.sql comment edits are parity-safe (introspection strips `--` comments; verified schema_introspect.py:37,135). deploy-migrate CI re-applies schema idempotently — comment-only DDL diffs are harmless | none |
| OS-registered state | None — no cron/systemd/Task Scheduler; GitHub Actions workflows reference test FILES not function names (verified: deploy-migrate.yml, concurrency-proof.yml) | none (re-verify if any test FILE is renamed) |
| Secrets/env vars | None — no env var or SOPS key embeds a ticket ID; `.env.example` untouched by scope | none |
| Build artifacts | None — no compiled artifacts embed comments; `chart.svg`/`summary.json` are committed eval artifacts that MUST be regenerated for POLISH-02 (they embed per-category groupings, not comments) | regenerate summary.json + chart.svg with the fixture relabel |

## Common Pitfalls

### Pitfall 1: Guard fails on runtime strings the sweep missed
**What goes wrong:** The guard scans file text, so ticket IDs inside assertion messages (`test_calculate.py:348 "FIX C: …"`), argparse descriptions (`run_eval.py:1083 "Phase 4"`), and user-visible template text (`run_detail.html:108 "Phase 6"`) fail it even after all comments are clean.
**How to avoid:** Inventory-driven sweep (this doc's grep is the checklist); run the guard locally per file batch.
**Warning signs:** Guard red on files whose comments look clean.

### Pitfall 2: Comment rewrite trips E501 or strict mypy
**What goes wrong:** Rewritten comments exceeding line-length 100 fail ruff E501; deleting a `# type: ignore[code]` line (or the comment carrying it) fails `warn_unused_ignores`/strict; moving a `# noqa` off its line re-fires the lint it suppressed.
**How to avoid:** `uv run ruff check && uv run mypy && uv run pytest -q` at every commit (locked in CONTEXT); treat noqa/ignore comments as "rewrite reason text in place, never relocate."

### Pitfall 3: Test renames that collide or change collection count
**What goes wrong:** Stripping prefixes can produce duplicate test names within a module (silent shadowing — pytest collects only the last definition, count drops) — e.g. multiple `test_cr01_*` in test_resume_pipeline.py could collapse if renamed carelessly.
**How to avoid:** D-06's neutrality proof IS the check: assert identical collected-test count before/after (`uv run pytest -q --collect-only | tail -1`). Give each rename a distinct scenario name.

### Pitfall 4: POLISH-02 committed piecemeal breaks the eval CI gate
**What goes wrong:** Committing the fixture relabel without regenerated summary.json (or vice versa) turns `eval.yml --check` red on push, since per-category aggregates are compared.
**How to avoid:** One atomic commit: fixture + summary.json + chart.svg, with `--check` run locally first. All hermetic — no live keys needed.

### Pitfall 5: WR-01 test that proves nothing (Phase 10 lesson)
**What goes wrong:** A "regression test" that stubs the very seam under test (the upsert / epoch stamp) passes vacuously; likewise driving only the route without asserting the outbound headers.
**How to avoid:** Drive the real seams the way tests/test_retrigger_epoch.py does (fake_repo + mock_llm from conftest.py, capture gateway outbound calls) and assert the actual In-Reply-To/References values on the post-retrigger send; also keep LLM seams stubbed because `.env` has live keys (stub `suggest_employees`, per project memory).

### Pitfall 6: Judgment drift on "constraint vs provenance" at scale
**What goes wrong:** ~1,800 matching lines across ~100 files; different executors applying D-01 inconsistently (one deletes a load-bearing arbiter-drift warning, another keeps ticket IDs "because the comment was useful").
**How to avoid:** Plans should restate the D-01/D-02/D-03 rubric verbatim per plan, name the money-path files where FULL depth is mandatory (calculate.py, tax_tables_2026.py, decide.py, delivery.py, emails.py's arbiter block, validate.py's pay-type rule), and route all files through the guard.

## Code Examples

### Guard-test skeleton (mirrors the BOUND-01 precedent)
```python
# Pattern source: tests/test_bound01_private_imports.py (this repo)
import pathlib, re

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
SCAN_GLOBS = [
    "app/**/*.py", "app/db/schema.sql", "app/templates/*.html", "app/static/*.css",
    "eval/**/*.py", "eval/fixtures/*.md", "scripts/*.py", "tests/**/*.py",
]
# D-08 blocklist — ticket-shaped only; tune against the final tree for zero FPs.
TICKET_PATTERNS = [
    re.compile(r"\bD-\d[\w.\-]*"),          # D-21-01, D-7.5-08, D-11-13, D-13b
    re.compile(r"\b(?:WR|CR|CX|GAP|R2)-\d+\b"),
    re.compile(r"\bFIX[ -][0-9A-Z]\b"),
    re.compile(r"Pitfall #\d+"),
    re.compile(r"\(review fix\)"),
    re.compile(r"\bPhase \d"),               # capital P only (D-08)
]

def test_no_ticket_provenance_in_swept_sources():
    hits = []
    for glob in SCAN_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if path.resolve() == pathlib.Path(__file__).resolve():
                continue  # D-09: the guard's own pattern table is exempt
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                for pat in TICKET_PATTERNS:
                    if pat.search(line):
                        hits.append(f"{path.relative_to(REPO_ROOT)}:{lineno}: {line.strip()}")
    assert not hits, "ticket-provenance references found:\n" + "\n".join(hits)
```
(Plus a synthetic `tmp_path` self-test proving each pattern fires and each legit-prose case passes, per the precedent.)

### POLISH-02 regeneration commands (all hermetic)
```bash
# after editing eval/fixtures/10_multi_employee_coastal.json fixture_category -> "typo"
uv run python eval/run_eval.py            # rewrites eval/summary.json from committed caches
uv run python eval/run_eval.py --chart    # rewrites eval/chart.svg
uv run python eval/run_eval.py --check    # must exit 0 before committing
```

### WR-05 containment fix shape
```python
# app/routes/dashboard.py eval_view — before read_text()
fixture_file = (fixtures_dir / fixture["fixture_path"]).resolve()
if not fixture_file.is_relative_to(fixtures_dir.resolve()):
    fixture["raw_body"] = "‹fixture file missing›"   # same fallback as the not-exists branch
    continue
```

## State of the Art

Not applicable in the usual sense (no external ecosystem). The relevant "current state" facts are internal and verified above: Phase 11's epoch arbiter supersedes WR-01's premise; Phase 8 already fixed WR-02 and WR-03; a Phase-5-execution fix already covered WR-04; the `needs_clarification` status was removed (INFO-01 obsolete). Only WR-01(test), WR-05, INFO-02, and the fixture relabel produce new code/data changes.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pydantic 2.13 `ValidationError.errors()` accepts `include_input=False, include_url=False` for the INFO-02 scrub | Don't Hand-Roll / POLISH-01 | Low — fall back to formatting only `loc`/`type` from `exc.errors()` dicts, which exists in all v2 releases. Verify with `uv run python -c "..."` during planning |
| A2 | `_assert_regression` compares per-category aggregates (its docstring says "ALL scored metrics"; I verified confusion-matrix + overall comparisons directly, per-category blocks were below the read window) | POLISH-02 | None in practice — the safe plan (regenerate summary.json atomically with the relabel) is correct whether or not per-category is compared |

## Open Questions (RESOLVED)

All four resolved during planning — owning plan noted per question.

1. **Do requirement IDs (CALC-03, DASH-01, BOUND-01…) and secondary provenance (`T-8-07`, `Codex HIGH-2`, `finding #1`, `R2-MEDIUM`, `OPS2-01`, `NEW-1`) get guard-enforced or only sweep-rewritten?**
   - RESOLVED → plan 15-10 Task 1: the guard enforces exactly the D-08 subset (secondary shapes appended only if a full-tree run shows zero false positives); the sweep plans handle the rest editorially, and requirement IDs never match.
   - What we know: D-08 enumerates the blocklist and demands zero false positives; D-01/D-03 demand sweeping ALL process references. Requirement IDs arguably aren't "process history" — they map to REQUIREMENTS.md which lives in `.planning/` (invisible to the future maintainer per the audience test), yet they are the codebase's requirement-traceability convention.
   - Recommendation: guard enforces exactly D-08's list (append `R2-\d`, `\bOPS2?-\d`, `T-\d+-\d+` only if the final corpus shows zero FPs); the sweep rewrites everything under D-01 judgment, including requirement-ID prose where it reads as provenance ("CLAR-04 purpose-aware idempotency guard (finding #1)" → keep the purpose-aware idempotency explanation, drop the labels). Planner should make this call explicit per D-08's "tune the final regex set."
2. **Test file renames (`test_cr_regressions.py`, `test_cr01_classify_union.py`)** — D-06 covers function names only. Renaming the files is cleaner (their names ARE ticket provenance) but touches nothing CI references. Claude's-discretion; recommend renaming both (e.g. `test_alias_and_run_column_regressions.py`, `test_reply_classify_union.py`) with `git mv` in the same commit as their function renames.
   - RESOLVED → plan 15-06 Task 1: both files renamed via `git mv` to the recommended names, with collect-count identity enforced against a pre-rename baseline.
3. **Dead `"computing"` badge-map entry** (templating.py) — not any RunStatus member. Removing it is a one-line behavior-neutral cleanup adjacent to INFO-01's disposition; include or leave, planner's call.
   - RESOLVED → plan 15-09 sweep rubric: deliberately left in place (behavior edits beyond 15-01's three sanctioned fixes are out of phase scope); plan 15-10 Task 2 documents the call in the disposition record.
4. **`run_detail.html:108` user-visible text "(demo only — Phase 6 uses real inbound webhook)"** — this is rendered UI copy, not a comment; the sweep should rewrite it ("demo only — production uses the real inbound webhook") since it faces the hiring-manager audience directly.
   - RESOLVED → plan 15-09 Task 2: caption rewritten to "(demo only — production uses the real inbound webhook)", with a pre-check for any test pinning the old wording.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv + Python 3.12 | everything | ✓ (project-managed, .python-version) | 3.12 | — |
| pytest / ruff / mypy | per-commit gates | ✓ (dev deps in uv.lock) | locked | — |
| matplotlib | `run_eval.py --chart` | ✓ (dev dep; chart.svg exists in repo) | locked | — |
| Live LLM keys | NOT needed — eval `--check`/default runs are hermetic via `*_extraction.json` caches | n/a (present in .env — hazard, keep seams stubbed) | — | — |
| Live DATABASE_URL | NOT needed — only `--db` flag and integration-marked tests use it | n/a | — | hermetic suite runs with `-m 'not integration'` default posture |

**Missing dependencies with no fallback:** none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (uv dev dep), markers: `integration`, `live_llm` (deselected by default hermetic posture) |
| Config file | `pyproject.toml` (markers at lines 42-43) |
| Quick run command | `uv run pytest -q -x tests/<file>` |
| Full suite command | `uv run pytest -q` (~616 tests green as of Phase 14 close) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| COMM-01 | No ticket-shaped patterns in swept sources | static-scan guard | `uv run pytest -q tests/test_comment_provenance_guard.py` (name TBD) | ❌ Wave 0 (D-07) |
| COMM-01/02/03 neutrality | Suite unchanged (same count), ruff+mypy green | full gates | `uv run pytest -q && uv run ruff check && uv run mypy` | ✅ existing |
| D-06 renames | Collection count identical pre/post | collect-only diff | `uv run pytest -q --collect-only \| tail -1` | ✅ (procedure, not file) |
| POLISH-01 WR-01 | Threading anchor survives crash→retrigger→send | hermetic regression (fake_repo + mock_llm) | `uv run pytest -q tests/test_threading.py -k retrigger` (or new file) | ❌ Wave 0 (D-10) |
| POLISH-01 WR-05 | Traversal path in summary.json fixture_path is refused | unit (route + tmp summary) | `uv run pytest -q tests/test_dashboard.py -k containment` | ❌ Wave 0 |
| POLISH-01 INFO-02 | Retry prompt carries no raw input values | unit (fake client capture) | `uv run pytest -q tests/test_llm_client.py -k retry` | ❌ Wave 0 (extend existing test_llm_client.py) |
| POLISH-02 | Relabel + regenerated artifacts pass regression gate | eval gate | `uv run python eval/run_eval.py --check` | ✅ existing (eval.yml runs it on push) |

### Sampling Rate
- **Per task commit:** `uv run pytest -q <touched test files> && uv run ruff check && uv run mypy` (mypy is cheap enough repo-wide; comment edits rarely affect it but ignore-comment edits do)
- **Per wave merge:** `uv run pytest -q` full suite + `uv run python eval/run_eval.py --check`
- **Phase gate:** full suite + ruff + mypy + eval --check + new guard test green before `/gsd-verify-work`

### Wave 0 Gaps
- [ ] `tests/test_comment_provenance_guard.py` (or similar) — COMM-01 guard, D-07..D-09
- [ ] WR-01 hermetic crash→retrigger→send threading regression test
- [ ] WR-05 path-containment test (extend tests/test_dashboard.py)
- [ ] INFO-02 retry-prompt-scrub test (extend tests/test_llm_client.py)
- [ ] Framework install: none needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no (demo posture, WR-3 known/accepted per REQUIREMENTS.md Out of Scope) | — |
| V4 Access Control | no new surface | — |
| V5 Input Validation | yes | WR-05: `Path.resolve()` + `is_relative_to()` containment on summary.json-derived fixture paths |
| V6 Cryptography | no | — |
| V13 API / V14 Config | yes (header injection) | WR-04 Content-Disposition sanitizer — already fixed + regression-tested (tests/test_dashboard.py:381-423); verify-only |

### Known Threat Patterns for this phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Path traversal via `fixture_path` in summary.json (WR-05) | Information Disclosure | Containment check before read; fall back to the existing missing-file placeholder |
| Model-output echo to provider in retry prompt (INFO-02) | Information Disclosure | Scrubbed structured error summary instead of `f"{exc}"` |
| Header injection via employee name in Content-Disposition (WR-04) | Tampering | Already mitigated: `re.sub(r"[^\w.\-]","_",name,flags=re.ASCII)`; keep the failure-mode comment at full depth (D-02) |
| Comment sweep silently altering behavior | Tampering (self-inflicted) | Text-only diffs proven by unchanged test count + green CI gates at every commit; POLISH fixes isolated in test-first commits |

## Sources

### Primary (HIGH confidence — direct codebase verification this session)
- Working tree at commit 0f276d1 — grep/read of: app/db/repo/* (docstrings), app/db/supabase.py (WR-02 fix), app/db/repo/demo.py:140-172 (WR-03 fixed), app/routes/runs.py:266,673-685 (retrigger route, WR-04 fix), app/routes/dashboard.py:100-135 (WR-05 gap), app/llm/client.py:150-190 (INFO-02 present), app/routes/templating.py:19-58 + app/models/status.py (INFO-01 obsolete), app/db/repo/emails.py:16-140 (epoch arbiter), app/email/gateway.py:240-280 (durable References chain), app/pipeline/delivery.py:30-110, eval/run_eval.py:474/494/583/655-700/1081-1169 (grouping, --check, main flow), eval/summary.json + all 18 fixture categories, eval/fixtures/DIVERGENCES.md, tests/test_bound01_private_imports.py, tests/test_status_drift.py, tests/test_dashboard.py:381-423, .github/workflows/{ci,eval,deploy-migrate,concurrency-proof}.yml, pyproject.toml (ruff/mypy config), app/db/schema_introspect.py:37,135
- `.planning/phases/15-comment-hygiene-deferred-polish-triage/15-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/todos/pending/260623-01…md`, `.planning/todos/pending/260623-05…md` (05-REVIEW.md confirmed present at `.planning/phases/05-dashboard-delivery/05-REVIEW.md`)

### Secondary (MEDIUM confidence)
- Grep-derived counts (682 app/eval/scripts lines, 1,096 tests lines, 32 ticket-named test functions) — exact numbers depend on the final regex set; treat as sizing, re-derive per plan.

### Tertiary (LOW confidence)
- A2 (per-category comparison inside `_assert_regression`) and A1 (pydantic `include_input` kwarg) — see Assumptions Log.

## Metadata

**Confidence breakdown:**
- Sweep inventory: HIGH — grep-verified per file this session
- POLISH-01 per-item state: HIGH — every item read in live source with line numbers
- POLISH-02 mechanics: HIGH — grouping code, CI gate, and hermetic flow all read directly; one LOW assumption (A2) that doesn't change the plan
- Guard design: HIGH on precedent/scope; MEDIUM on the final regex set (D-08 explicitly defers tuning to the swept corpus)

**Research date:** 2026-07-10
**Valid until:** phase execution (internal inventory — invalidated by any commit touching the swept files, so re-run the greps at plan time)
