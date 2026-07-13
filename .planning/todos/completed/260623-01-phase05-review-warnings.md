---
id: 260623-01
created: 2026-06-23
source: 05-REVIEW.md
resolves_phase: 15
priority: medium
---

# Phase 05 code-review: deferred Warnings + Info

The 3 Criticals (CR-01/02/03) were fixed during Phase 05 execution. These lower-severity
findings were deferred — candidates for a 05.1 gap phase or standalone fixes. Full detail
in `.planning/phases/05-dashboard-delivery/05-REVIEW.md`.

## Warnings
- **WR-01** — Reply-threading broken after crash+retrigger: the outbound `insert_email_message`
  upsert on `(run_id, purpose)` overwrites `message_id`, so a resumed/retriggered run can lose
  the original thread anchor. Verify the threading round-trip survives retrigger.
- **WR-02** — Thread-unsafe pool singleton in `app/db/supabase.py` (module-level `ConnectionPool`
  init not guarded). Low risk on a single-worker demo, but document or guard.
- **WR-03** — `load_all_runs` uses `SELECT pr.*`, fetching full `extracted_data`/`decision`/
  `reconciliation` JSONB blobs on every runs-list page load. Project to the columns the list needs.
- **WR-04** — `Content-Disposition` header for the paystub PDF is injectable via an employee name
  containing `"` or newline. Sanitize/quote the filename.
- **WR-05** — Missing path-containment check on `eval/summary.json` (and fixture) path reads.
  Confirm no traversal surface even though paths are currently committed/static.

## Info
- **INFO-01** — `needs_clarification` status missing from the dashboard badge maps (inconsistent;
  currently dead but should be added for completeness).
- **INFO-02** — The LLM retry prompt echoes raw `ValidationError` content (which can include model
  output) back to the provider. Scrub before re-sending.

---

## Resolution (Phase 15)

Every item below was **spot-verified against live source before being recorded** — no item is
marked closed on the strength of a prior document alone. Four of the seven turned out to be
already fixed or obsolete; three needed real work.

| Item | Disposition | Evidence in live source |
|------|-------------|-------------------------|
| **WR-01** | **Fixed & proven (Phase 15, plan 15-01)** — by TWO proofs, not one | see below |
| **WR-02** | **Fixed (Phase 8), verified** | `app/db/supabase.py:35` `_pool_lock = threading.Lock()`; double-checked locking at `:54` |
| **WR-03** | **Fixed (Phase 8), verified** — recorded as *fixed*, not the anticipated "accepted" | `app/db/repo/demo.py:162` `load_all_runs` selects an EXPLICIT scalar column list; no `pr.*`. `employee_count` is `jsonb_typeof`-guarded so one corrupt row cannot 500 the runs list |
| **WR-04** | **Fixed (Phase 5 execution), verified** | `app/routes/runs.py:668` sanitizes the filename to a safe charset *before* it reaches the header (`:680`); regression test `tests/test_dashboard.py:454` asserts no CR/LF can reach `Content-Disposition` |
| **WR-05** | **Fixed (Phase 15, plan 15-11)** | `app/routes/dashboard.py:121-128` — `EVAL_FIXTURES_DIR.resolve()` + `fixture_file.is_relative_to(fixtures_root)`. The eval paths were hoisted to module-level constants first, which is what made the containment testable without a `chdir` (a `chdir` would have broken the shared relative Jinja searchpath) |
| **INFO-01** | **Obsolete — no action** | The status was removed: `needs_clarification` does not appear in `app/models/status.py`, and `tests/test_status_drift.py:193` enforces its absence file-wide. Adding a badge for a status that cannot occur would re-introduce dead code |
| **INFO-02** | **Fixed (Phase 15, plan 15-11)** | `app/llm/client.py:121` `_scrubbed_validation_summary()` formats `exc.errors(include_url=False, include_input=False)` — the retry prompt (`:207`) now carries *where* validation failed and *what* the schema wanted, never the model's own echoed output |

### WR-01 — closed by two proofs, because one was not enough

The original finding's premise was **stale**: Phase 11 had already rewritten the upsert to
arbitrate on `(run_id, purpose, round, epoch)`, so a retrigger *appends a new row* rather than
overwriting the thread anchor. But "the code looks right" is not a proof, and the two available
proof surfaces each cover only half the claim — so both were built:

1. **`tests/test_retrigger_threading.py`** (hermetic) — drives the real
   `POST /runs/{run_id}/retrigger` route and the real pipeline, with a **one-shot failure
   injection at a post-send persistence step** to manufacture a genuine crash. It does not merely
   seed an ERROR row and call it a crash. It was **green on the first run**: no production fix was
   needed, confirming the Phase 11 rewrite had genuinely closed the hole. Its claims are narrowed
   to the seam it actually executes (route / pipeline / gateway) — the `fake_repo` fixture patches
   `insert_email_message` onto the `app.db.repo` package, so no test taking that fixture can reach
   the real SQL, and pretending otherwise would have been a lie.
2. **`tests/test_email_epoch_arbiter_integration.py`** (real Postgres) — drives the production
   upsert against a live database and proves the four-column arbiter **appends rather than
   clobbers** across a real `reply_epoch` bump. This is the half the hermetic test structurally
   cannot see.

The second proof also exposed a problem the finding never mentioned: **a new integration test
would not have run in CI at all.** The test job sets no `DATABASE_URL`, so every
`@pytest.mark.integration` test self-skips there, and `concurrency-proof.yml` — the only job with
a Postgres — hard-coded a single test file. Plan 15-01 therefore wired the new module into that
workflow *and* added an execution guard, so the proof cannot silently downgrade to a no-op while
CI stays green. Residual limitation, stated rather than hidden: that workflow runs on
push-to-master and manual dispatch, not on pull requests.

### One thing deliberately left alone

`app/routes/templating.py:21,37` still carry a dead `"computing"` badge-map entry. It is harmless
(both maps are read through `.get()` with defaults) and removing it is a behavior edit outside this
phase's three sanctioned fixes. Noted here so it is a recorded choice rather than an oversight.
