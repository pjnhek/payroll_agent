# Phase 15: Comment Hygiene & Deferred-Polish Triage - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Comments and docstrings across the codebase document constraints and invariants for a future maintainer — no ticket-ID/provenance references anywhere (COMM-01), real module-purpose docstrings replace the deleted repo.py TOC style across the split DB modules (COMM-02), module docstrings state purpose + invariants rather than phase history (COMM-03) — and the two remaining v2 deferred-polish todos are explicitly closed: todo 260623-01 Phase 05 review warnings (POLISH-01) and todo 260623-05 fixture 10's category label (POLISH-02). The milestone ends with zero silently-open loose ends.

Scope decision widens the sweep beyond COMM-01's literal `app/` wording to the whole codebase (per the roadmap goal's "across the codebase" phrasing) — see D-02. Everything outside the sanctioned POLISH fixes is comment/docstring/rename-only: the full test suite passes with no assertion changes, and mypy strict + ruff + BOUND-01 guard stay green at every commit.

Measured surface at discussion time: ~293 ticket-comment lines in `app/*.py` (orchestrator.py 72, clarification.py 28, delivery.py 23, routes/runs.py 22, seed.py 18, …), 47 in `app/db/schema.sql`, 1 in `app/templates/run_detail.html`, 29 in `eval/`, 3 in `scripts/`, 287 across 44 `tests/` files, plus ~29+ test function names embedding ticket IDs.

</domain>

<decisions>
## Implementation Decisions

### Rewrite policy (COMM-01, COMM-03)
- **D-01:** **Keep constraint, drop label.** Every ticket comment is judged on content: if it documents a real constraint/invariant/edge case, it is rewritten as plain maintainer-facing English with the ticket reference removed; pure provenance (who/when/which review/where code migrated from) is deleted entirely. The codebase's unusually rich why-documentation is preserved — only its process vocabulary goes.
- **D-02 (money-path depth):** In money-path files (`calculate.py`, `tax_tables_2026.py`, `decide.py`, `delivery.py`, and money-relevant comments elsewhere), surviving comments keep **full depth — constraint AND failure mode** (e.g. "using the MFJ table for MFS would halve withholding"). The consequence narration is what stops a future "simplification" from reintroducing a mispay; do not trim it.
- **D-03 (provenance beyond ticket IDs):** All project-process references are stripped the same as ticket IDs — phase numbers ("Phase 3"), review rounds ("review round 2", "review fix"), planning-doc citations ("PATTERNS.md", "RESEARCH Security Domain"), split history ("post-split", "migrated from X per D-02"). A comment must stand alone for a maintainer who has never seen `.planning/`. **External authoritative citations stay** (IRS Pub 15-T PDF URL, SSA wage-base URL, provider API docs) — they are sources, not process history.
- **D-04 (docstring shape):** Module docstrings get a 1–2 sentence **purpose statement**; modules with genuine invariants (e.g. `_shared.py`'s "parameterized SQL only, never f-string SQL"; `decide.py`'s "pure code, no LLM, no confidence") add a **short invariants paragraph**. No history, no TOC-style function indexes (COMM-02: the split DB modules get their real module-purpose statements now, per Phase 13 D-04's placeholder handoff).

### Sweep scope (COMM-01 widened)
- **D-05:** The sweep covers the **whole codebase**: `app/*.py`, `app/db/schema.sql`, `app/templates/`, `eval/`, `scripts/`, `tests/`, and maintainer-facing Markdown inside the code tree (e.g. `eval/fixtures/DIVERGENCES.md`) — all under the same D-01 rule. `.planning/`, phase artifacts, README changelog-ish content, and git history remain the provenance record and are untouched.
- **D-06 (test names):** Test function names lose their ticket-ID prefixes — `test_cr01_explicit_zero_overpay_guard...` → `test_explicit_zero_overpay_guard...`. Pure renames, no assertion changes; where the ticket ID is the only meaningful part of a name, invent a descriptive scenario name. The suite passing unchanged (same count) is the neutrality proof.

### Regression guard (new invariant)
- **D-07:** A **pytest guard test** (precedent: `tests/test_bound01_private_imports.py`) scans swept sources for ticket-ID patterns and fails on any hit. It runs inside the existing CI test job — no `ci.yml` change — and doubles as the sweep's completion proof (COMM-01 success criterion becomes executable).
- **D-08 (patterns):** Guard blocks **ticket-shaped patterns only**: `D-<n>`/`D-21-01`-style IDs, `WR-`/`CR-`/`CX-`/`GAP-<n>`, `FIX <n>/<letter>`, `Pitfall #<n>`, `(review fix)`, and capital-P `Phase <n>`. Natural prose ("fix the rounding", "this phase of parsing") must pass. Tune the final regex set against the swept corpus for zero false positives on the final tree.
- **D-09 (guard scope):** Guard scans **exactly what the sweep cleaned** (D-05 file set), excluding `.planning/` and the guard's own pattern table.

### POLISH-01 — todo 260623-01 triage
- **D-10:** **WR-01 (threading after crash+retrigger) is verified by a hermetic regression test**: drive crash → retrigger → outbound send and assert the reply-threading anchor (Message-ID chain) survives the `(run_id, purpose)` upsert. If the test exposes a real break, fix it under the test-first money-path protocol (failing test commit, then minimal fix — never buried in comment commits). Phase 11 reworked this machinery, so verify against current source first; "verified by reading" alone is not acceptable (Phase 10 vacuous-proof lesson).
- **D-11:** **WR-02** (pool singleton): confirm the Phase 8 fix in current source and close — verification note only.
- **D-12:** **Fix cheap+real, disposition the rest** for the remaining items, each first verified against current code (later phases may have incidentally fixed them): WR-04 (Content-Disposition filename sanitization), WR-05 (path-containment check on eval summary/fixture reads), INFO-01 (`needs_clarification` badge-map entry), INFO-02 (scrub ValidationError content from the LLM retry prompt) get small test-first fixes if still present. **WR-03** (runs-list `SELECT pr.*` JSONB over-fetch) is **dispositioned as accepted** — perf-only, invisible at demo scale — with a written rationale in the todo closure. Todo 260623-01 is then closed with an explicit per-item disposition record.

### POLISH-02 — todo 260623-05
- **D-13:** Fixture 10's `fixture_category` becomes **`"typo"`** — matches the established six-category eval taxonomy (exact / stored-alias / first-time-alias / typo / collision / unknown); "Jame Okafor" is a typo of roster "James Okafor". Verify: eval re-run shows per-category chart grouping still reads correctly, and no test asserts `category=="exact"` for fixture 10. Todo 260623-05 closed.

### Claude's Discretion
- Exact guard-test implementation (regex table, file walker, failure message wording) within D-07..D-09.
- Per-comment keep-vs-delete judgment within the D-01 bar; final wording of rewritten comments and docstrings.
- Commit sequencing/granularity — comment-only commits must be cleanly separated from any POLISH behavior-fix commits (D-10/D-12), and the suite + mypy + ruff stay green at every commit.
- Where the POLISH disposition records live (todo closure notes vs phase VERIFICATION.md) — standard GSD artifacts.
- Whether trivially-empty `__init__.py` files need docstrings at all.

### Folded Todos
- **260623-01 — Phase 05 review warnings** (IS POLISH-01): WR-01..05 + INFO-01/02 triage per D-10..D-12.
- **260623-05 — Fixture 10 category-label mismatch** (IS POLISH-02): relabel to `"typo"` per D-13.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements & milestone framing
- `.planning/ROADMAP.md` — Phase 15 goal + success criteria 1–5; note the goal's "across the codebase" wording that D-05 operationalizes.
- `.planning/REQUIREMENTS.md` — COMM-01/02/03, POLISH-01/02 exact wording; "Out of Scope: any behavior change to pipeline/money logic" (POLISH fixes are the sanctioned exception, test-first).

### The two todos this phase closes
- `.planning/todos/pending/260623-01-phase05-review-warnings.md` — full WR-01..05 + INFO-01/02 text (POLISH-01).
- `.planning/todos/pending/260623-05-fixture-category-label-mismatch.md` — fixture 10 label details + the no-eval-impact analysis (POLISH-02).
- `.planning/phases/05-dashboard-delivery/05-REVIEW.md` — original Phase 05 review with full finding detail behind todo 260623-01.

### Prior-phase constraints that bind this phase
- `.planning/phases/13-module-structure-boundaries/13-CONTEXT.md` — D-04 (TOC deleted at split, Phase 15 writes real module statements); final module layout the docstrings describe; the monkeypatch-seam invariants docstrings must keep documenting accurately.
- `.planning/phases/14-full-type-checking-mypy/14-CONTEXT.md` — D-08 (real bugs get separate test-first commits — governs any POLISH fix), D-09 (`# type: ignore[code]` comments carry required reason text: rewrite the reason in plain English, never delete the ignore rationale).

### Files at the center of the sweep (largest ticket-comment counts)
- `app/pipeline/orchestrator.py` (72), `app/pipeline/clarification.py` (28), `app/pipeline/delivery.py` (23), `app/routes/runs.py` (22), `app/db/seed.py` (18), `app/db/schema.sql` (47).
- `tests/test_bound01_private_imports.py` — the guard-test pattern D-07 mirrors.
- `eval/fixtures/10_multi_employee_coastal.json` + `eval/run_eval.py` — POLISH-02 target and the chart grouping to verify.

### Tooling rules
- `CLAUDE.md` §Tooling Rule — uv-only; `uv run pytest -q` / `uv run ruff check` / `uv run mypy` for every verification.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/test_bound01_private_imports.py` — existing source-scanning guard test; the COMM guard (D-07) follows its structure and lives beside it.
- The split DB modules already carry working draft docstrings from Phases 13/14 — COMM-02 is a rewrite-in-place (strip provenance like "post-split", "PATTERNS.md / RESEARCH"), not greenfield writing.
- Eval harness (`uv run` eval + chart) is the ready-made verification for POLISH-02's "grouping unaffected" check.

### Established Patterns
- Comment conventions to preserve: `noqa`/`type: ignore[code]` comments carry mandatory reason text (Phase 12 D-03 / Phase 14 D-09) — rewrite reasons in plain English, never strip the rationale itself.
- Test seams are module-attribute monkeypatches; the sweep must not move code or change any module/function structure except the D-06 test renames.
- Execute-phase hazard (v2/v3 experience): this repo's `.env` has LIVE LLM keys — executors must keep LLM seams stubbed (e.g. `suggest_employees`); never rely on env emptiness.
- CI gates from Phases 12/14 (ruff, pytest, mypy strict) must stay green at every commit — they are the behavior-neutrality proof for a comment-only diff.

### Integration Points
- The new guard test slots into the existing CI `test` job — no `ci.yml` edit (D-07).
- WR-01's regression test drives the retrigger route / `insert_email_message` upsert seam (`app/routes/runs.py` + `app/db/repo/emails.py`) — Phase 11's rework of this path is the first thing to verify.
- Fixture 10 label touches `eval/fixtures/10_multi_employee_coastal.json` and is read by `eval/run_eval.py` grouping/chart code.

</code_context>

<specifics>
## Specific Ideas

- The audience test: a hiring manager reading any file sees comments that explain the system's invariants ("collisions always clarify — resolving here would guess with money") with zero clue the project ever had ticket numbers. `.planning/` and git history keep the full provenance for anyone who wants it.
- The guard test makes COMM-01's success criterion executable — "no ticket refs anywhere" is enforced, not asserted.
- Milestone-closure framing: this is v3's last phase; POLISH dispositions should leave STATE.md's deferred-items table with nothing silently open.

</specifics>

<deferred>
## Deferred Ideas

- **Clean multi-employee PROCESS fixture** (all names resolve → straight-through 2-employee approval demo) — floated in todo 260623-05; a new capability, not polish. Backlog.

### Reviewed Todos (not folded)
- `260623-02` (frontend progressive enhancement), `260623-03` (paystub YTD columns), `260623-04` (eval-chart restyle) — out of v3 per REQUIREMENTS.md Future Requirements; same disposition as Phases 12–14.

</deferred>

---

*Phase: 15-Comment Hygiene & Deferred-Polish Triage*
*Context gathered: 2026-07-10*
