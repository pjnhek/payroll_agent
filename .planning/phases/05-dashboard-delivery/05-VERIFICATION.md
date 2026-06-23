---
phase: 05-dashboard-delivery
verified: 2026-06-22T00:00:00Z
status: passed
score: 5/5 must-haves verified
human_verification_status: approved   # builder walked the live flow (multi-employee clarify→simulate-reply→approve), 2026-06-23
overrides_applied: 0
post_verification_note: >
  After this verification ran, an extended UAT + 5 code-review rounds landed further fixes
  (paystub redesign, vanilla-JS status poll, simulate-reply demo affordance, reload-on-change,
  Content-Disposition sanitization incl. non-latin-1, approve error-boundary). All 5/5
  observable truths remain verified against the current code; full suite 409 passed / 0 failed.
  The builder manually walked the live dashboard flow and approved the human-verification items
  (see 05-HUMAN-UAT.md, now status: passed) on 2026-06-23.
human_verification:
  - test: "Open /runs in a browser and trigger a run via the Send Test Email button. Confirm (a) the runs list shows the new run with a status badge, (b) clicking View opens the 3-column run detail showing the raw email leftmost, extracted data in the centre, and either paystubs or a clarification banner on the right, and (c) for a run in awaiting_approval both Approve & Send and Reject buttons are present."
    expected: "All three columns render with real content. The raw email column is the LEFTMOST column. The decision reasons appear in the banner above the grid. Approve & Send and Reject controls are visible only when status is awaiting_approval."
    why_human: "CSS grid column ordering (leftmost = raw email) and button visibility are visual/browser behaviours that grep and template inspection cannot confirm end-to-end with a live DB session."
  - test: "Trigger an errored run (e.g. kill the DB connection or force an exception) and confirm the error banner and Re-trigger from Start button appear on the run detail page."
    expected: "Error banner shows error_reason. Re-trigger button is present. Clicking Re-trigger restarts the run and redirects back to the detail page with a non-error status."
    why_human: "Requires a live running app with a real or simulated error condition."
  - test: "Approve a run that was driven through the clarification path (David Reyez fixture). Confirm the confirmation email subject contains the real business name and pay period, and the paystub PDF is generated and attached (not empty, not a placeholder)."
    expected: "Subject: 'Payroll Confirmation — Coastal Cleaning — <pay_period_start> to <pay_period_end>'. PDF attachment is a valid reportlab-generated PDF with the correct employee name and net pay."
    why_human: "Requires a live gateway.send_outbound call and PDF inspection; the stub email gateway records outbound rows but cannot render the PDF or display the subject in a browser."
  - test: "Click Send Test Email twice in rapid succession and confirm two distinct runs appear in /runs (not a duplicate dropped to the same run_id)."
    expected: "Two separate rows in the runs list, each with a distinct run UUID. The second click is NOT silently swallowed."
    why_human: "Requires live DB interaction to observe unique message_id per click."
  - test: "Navigate to /eval and confirm (a) the headline metrics grid shows non-zero Extraction F1 and Decision Accuracy values, (b) the chart.svg image loads (not broken), and (c) at least one fixture row in the drill-in table shows a truncated raw email body rather than a dash."
    expected: "Headline metrics show real numbers (F1 ≈ 99%, Decision Accuracy = 100% per committed summary.json). Chart renders as an SVG image. Per-fixture raw_body column shows truncated email text."
    why_human: "Browser rendering and SVG loading require a live HTTP server; the eval.html template logic is correct but visual rendering cannot be asserted by grep."
---

# Phase 05: Dashboard Delivery Verification Report

**Phase Goal:** A human operator can approve real payrolls through an honest gate — seeing the raw cleaned inbound email beside the LLM's extraction beside the computed paystubs — then a confirmation email with on-demand PDFs sends only after approval, with idempotent sends and a visible error path.
**Verified:** 2026-06-22
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Run detail view shows three columns left-to-right: raw cleaned inbound email (leftmost, mandatory) \| LLM extracted_data \| computed paystubs, plus decision reasons (DASH-02) | VERIFIED | `app/templates/run_detail.html` lines 34–123: `.run-detail-grid` CSS class (3-column `grid-template-columns: 1fr 1fr 1fr` in style.css:178-180); Column 1 = `raw_email.body_text`, Column 2 = `extracted_data.employees`, Column 3 = `paystubs`. Decision banner above grid (lines 5–32). Route at `app/main.py:444` loads all three via `repo.load_run`, `repo.load_inbound_email`, `repo.load_line_items`. |
| 2 | Runs list shows every run with status badge; pending run exposes Approve-and-send + Reject controls; double-approval blocked by atomic CAS (`claim_status`) reused for approve/reject/retrigger (FOUND-04) | VERIFIED | `app/templates/runs_list.html` renders badge with `run.status \| badge_class` and `badge_label` Jinja2 filters. Approve/Reject forms in `run_detail.html:126-135` gated by `run.status == 'awaiting_approval'`. `repo.claim_status` (repo.py:313-338) uses `WHERE id=%s AND status=%s RETURNING id` atomic SQL. `app/main.py:313`, `333`, `369` all route through `claim_status` for approve/reject/retrigger. |
| 3 | On approval, run advances `approved → sent → reconciled`, sending LLM-drafted confirmation email with per-employee paystub PDFs generated in-memory (reportlab, BytesIO — nothing written to disk) (HITL-02, HITL-03) | VERIFIED | `_deliver` in `orchestrator.py:466-569` confirmed: enriches run dict with `business_name` + `pay_period_label` (CR-03 fix, line 488-496); calls `compose_confirmation` (line 517); calls `generate_paystub_pdf` per employee (line 528-534) in `BytesIO` (pdf.py:53, returns `buf.getvalue()`); calls `gateway.send_outbound` with `attachments=pdf_attachments` (line 543-551); `set_status(SENT)` then `set_status(RECONCILED)` (lines 568-569). `pdf.py` contains no `open()` or `.write()` to filesystem. |
| 4 | Outbound sends are idempotent — retrying approval or re-triggering an errored run never double-sends; error status visible on dashboard with re-trigger control (CLAR-04, INGEST-05) | VERIFIED | Purpose-aware guard in `_deliver` (orchestrator.py:499-511): `repo.get_outbound_message_id(run_id, purpose="confirmation")` — only `send_state='sent'` rows match (repo.py:630-656). Same guard in `_clarify` (orchestrator.py:283-291) with `purpose="clarification"`. Schema constraint `uq_email_run_purpose UNIQUE (run_id, purpose)` (schema.sql:156). Error banner in `run_detail.html:6-9`. Re-trigger button for `error`, `approved`, stale in-flight states (`run_detail.html:139-144`). Retrigger route (`main.py:337-416`) uses `claim_status` CAS. |
| 5 | Eval view renders latest summary with headline metrics + per-category chart; Send Test Email button fires fixture through whole pipeline (DASH-05) | VERIFIED | `app/templates/eval.html`: Section 1 = headline metrics grid (`extraction_overall_f1`, decision accuracy, false_process_rate lines 6-23). Section 2 = chart via `<img src="/eval/chart.svg">` (line 30). Section 3 = per-fixture drill-in table with `raw_body` column (lines 34-69). `eval/summary.json` exists with 15 fixtures; `eval/chart.svg` exists. `GET /eval/chart.svg` route at `main.py:507-513`. Send Test Email POSTs to `/demo/send-test` in both `eval.html:80-82` and `runs_list.html:48-50`. Fresh `uuid4` message_id per click (main.py:590). |

**Score: 5/5 truths verified**

---

### Load-Bearing Invariant: Deterministic Decisioning (not guessing on money-moving decisions)

The `_safe_to_learn_alias` function in `app/pipeline/reconcile_names.py:112-147` is fully implemented. It uses a synthetic roster approach (Pydantic `model_copy`) to simulate the post-write state and calls `deterministic_match` — returning `True` only when the token uniquely resolves to the target employee AFTER appending it. The "D. Reyes" trap (David Reyes AND Daniel Reyes both carrying the alias) is correctly handled: the synthetic roster still has two candidates, so `deterministic_match` returns `None` and `_safe_to_learn_alias` returns `False`.

The capture-time collision check in `_clarify` (orchestrator.py:308-351) directly counts `candidate_ids` (NOT `deterministic_match` return value — the R2-HIGH fix), correctly excluding ambiguous tokens at emit time rather than only at write time.

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/main.py` | All DASH/HITL routes + approve/reject/retrigger | VERIFIED | 647 lines; all endpoints present, implemented, not stubs |
| `app/db/repo.py` | `claim_status`, `get_outbound_message_id`, `update_known_alias`, `load_business_name` | VERIFIED | All 4 helpers present with full SQL implementations |
| `app/pipeline/orchestrator.py` | `_deliver`, `_clarify`, `_write_aliases_if_safe`, `resume_pipeline` with alias diff | VERIFIED | All present with full logic, CR-01/02/03 fixes applied |
| `app/pipeline/pdf.py` | `generate_paystub_pdf` — BytesIO only | VERIFIED | reportlab + BytesIO, no filesystem write |
| `app/pipeline/compose_email.py` | `compose_confirmation`, `confirmation_subject` | VERIFIED | Both present; `confirmation_subject` uses `run.get("business_name")` + `run.get("pay_period_label")` |
| `app/pipeline/reconcile_names.py` | `_safe_to_learn_alias` — collision guard | VERIFIED | Implemented at line 112; uses synthetic roster + deterministic_match |
| `app/templates/run_detail.html` | 3-column grid with raw email leftmost | VERIFIED | `.run-detail-grid`, three `<div>` children in correct order |
| `app/templates/runs_list.html` | Status badges + Approve/Reject controls | VERIFIED | Badge filters applied; controls in run_detail.html gated by status |
| `app/templates/eval.html` | Headline metrics + chart + per-fixture drill-in + Send Test button | VERIFIED | All sections present |
| `app/static/style.css` | `.run-detail-grid` 3-column CSS | VERIFIED | `grid-template-columns: 1fr 1fr 1fr` at line 180 |
| `app/db/schema.sql` | `uq_email_run_purpose` constraint; `purpose` + `send_state` columns | VERIFIED | Constraint at line 156; columns at lines 147-151; idempotent ALTER TABLE blocks |
| `tests/test_claim_status.py` | CAS True/False unit tests + SQL shape + integration marker | VERIFIED | 6 test functions including `@pytest.mark.integration` race test |
| `tests/test_alias_write.py` | D. Reyes trap + collision guard tests + idempotency stubs | VERIFIED | 10 test functions including all 3 capture stubs |
| `tests/test_validate.py` | 5 D-05 OT rule test functions | VERIFIED | `test_ot_rule_*` functions at lines 180-300+ |
| `tests/test_cr_regressions.py` | CR-01/CR-02/CR-03 regression tests | VERIFIED | 10 regression tests including TEXT[] ops, `updated_at` in RUN_COLS, business_name enrichment |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `main.py:approve` | `repo.claim_status` | `claim_status(run_id, AWAITING_APPROVAL, APPROVED)` | WIRED | line 313; atomic CAS before calling `_deliver` |
| `main.py:reject` | `repo.claim_status` | `claim_status(run_id, AWAITING_APPROVAL, REJECTED)` | WIRED | line 333 |
| `main.py:retrigger` | `repo.claim_status` | `claim_status` for ERROR/APPROVED/stale states | WIRED | lines 369-404 |
| `approve route` | `orchestrator._deliver` | direct call after claim succeeds | WIRED | main.py:317; `_deliver(run_id, run)` |
| `_deliver` | `repo.load_business_name` | CR-03 enrichment before confirmation helpers | WIRED | orchestrator.py:492 |
| `_deliver` | `pdf.generate_paystub_pdf` | per-employee in-memory PDF | WIRED | orchestrator.py:528 |
| `_deliver` | `gateway.send_outbound` | with `purpose='confirmation'`, `attachments=pdf_attachments` | WIRED | orchestrator.py:543-551 |
| `_deliver` | `repo.get_outbound_message_id` | idempotency guard (`purpose='confirmation'`) | WIRED | orchestrator.py:501 |
| `_clarify` | `repo.get_outbound_message_id` | idempotency guard (`purpose='clarification'`) | WIRED | orchestrator.py:283 |
| `_clarify` | `repo.set_alias_candidates` | single-token, non-colliding capture | WIRED | orchestrator.py:344 |
| `resume_pipeline` | `repo.set_alias_candidates` | pre-vs-post diff binding | WIRED | orchestrator.py:185 |
| `_write_aliases_if_safe` | `_safe_to_learn_alias` | D-01b collision guard before each write | WIRED | orchestrator.py:444 |
| `_write_aliases_if_safe` | `repo.update_known_alias` | idempotent TEXT[] append (CR-01 fix) | WIRED | orchestrator.py:452 |
| `run_detail route` | `repo.load_inbound_email` | raw email for Column 1 | WIRED | main.py:455 |
| `run_detail route` | `repo.load_line_items` | paystubs for Column 3 | WIRED | main.py:456 |
| `eval_view route` | `eval/summary.json` | disk read, per-fixture raw_body enrichment | WIRED | main.py:487-498 |
| `demo_send_test route` | `_run_pipeline` background task | pipeline fired on each click | WIRED | main.py:634 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `run_detail.html:Column1` | `raw_email.body_text` | `repo.load_inbound_email(run_id)` → JOIN `email_messages` on `source_email_id` | Yes — cleaned body persisted at ingest | FLOWING |
| `run_detail.html:Column2` | `run.extracted_data.employees` | `repo.load_run(run_id)` → `payroll_runs.extracted_data` JSONB | Yes — set by `persist_extracted` after LLM extraction | FLOWING |
| `run_detail.html:Column3` | `paystubs` list | `repo.load_line_items(run_id)` → `paystub_line_items` table | Yes — set by `replace_line_items` after calculate stage | FLOWING |
| `eval.html:metrics` | `summary.extraction_overall_f1` etc. | `eval/summary.json` disk read | Yes — 15-fixture eval run, F1=0.987, decision accuracy=1.0 | FLOWING |
| `eval.html:chart` | SVG image | `eval/chart.svg` FileResponse | Yes — committed chart artifact | FLOWING |

---

### Behavioral Spot-Checks

Step 7b: SKIPPED for live pipeline execution (requires live DB + LLM keys). The mocked test suite fully exercises the pipeline at the code level with FakeConnection injection.

The test suite itself is a substantive behavioral check:
- `tests/test_delivery.py`: 11 tests covering approve/reject/retrigger/idempotency paths
- `tests/test_dashboard.py`: 7 tests covering all dashboard routes
- `tests/test_alias_write.py`: 10 tests covering the alias write-side
- `tests/test_cr_regressions.py`: 10 regression tests for all 3 Critical fixes
- Total: **372 passed, 13 skipped (live-LLM/integration), 0 failed**

---

### Probe Execution

No `scripts/*/tests/probe-*.sh` files exist in this project. Step 7c: SKIPPED.

---

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|---------|
| DASH-01 | 05-02, 05-06, 05-07 | Runs list with status badges | SATISFIED | `GET /runs` + `runs_list.html` with badge filters |
| DASH-02 | 05-02, 05-06, 05-07 | Run detail 3-column gate (raw \| extracted \| paystubs + decision reasons) | SATISFIED | `GET /runs/{id}` + `run_detail.html` 3-column grid |
| DASH-03 | 05-02, 05-05, 05-06 | Approve-and-send + Reject controls (pending runs only) | SATISFIED | `run_detail.html:126-135` gated by `status == 'awaiting_approval'` |
| DASH-04 | 05-06 | Eval view with headline metrics + per-category chart + drill-in | SATISFIED | `GET /eval` + `eval.html` with real `summary.json` data |
| DASH-05 | 05-06 | Send Test Email button fires fixture through pipeline | SATISFIED | `POST /demo/send-test` with fresh `uuid4` message_id per click |
| HITL-02 | 05-02, 05-04, 05-05 | Confirmation email on approval with paystub PDFs | SATISFIED | `_deliver` in `orchestrator.py` sends via `gateway.send_outbound` with `attachments` |
| HITL-03 | 05-02, 05-04, 05-05 | PDFs generated in-memory (reportlab, BytesIO — no disk) | SATISFIED | `pdf.py:53` uses `BytesIO`; `generate_paystub_pdf` returns `buf.getvalue()` |
| CLAR-04 | 05-01, 05-05 | Idempotent outbound sends (no duplicate clarification or confirmation) | SATISFIED | Purpose-aware `get_outbound_message_id` guards in `_clarify` and `_deliver`; `uq_email_run_purpose` constraint |
| INGEST-05 | 05-01, 05-03, 05-05 | Error status visible on dashboard; re-triggerable idempotently | SATISFIED | Error banner + Re-trigger button in `run_detail.html`; `claim_status` CAS in retrigger route |
| FOUND-04 | 05-01, 05-03 | Atomic status transitions, SELECT FOR UPDATE prevents double-approval | SATISFIED | `claim_status` CAS SQL `WHERE id=%s AND status=%s RETURNING id`; used at every contended gate |

All 10 phase requirements are SATISFIED.

**Note:** REQUIREMENTS.md still shows these as "Pending" — the traceability table was not updated during phase execution. This is a documentation gap, not an implementation gap. All required behaviors are present in the codebase.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/db/repo.py` | 579 | `message_id = EXCLUDED.message_id` in ON CONFLICT upsert | WARNING (WR-01 deferred) | If a clarification `message_id` was already communicated and a retrigger creates a new one, old In-Reply-To references break thread routing. Only manifests on crash-between-reserved-and-sent scenario. Deferred per 05-REVIEW.md. |
| `app/db/supabase.py` | ~37-51 | `get_pool()` check-then-act without lock | WARNING (WR-02 deferred) | Two concurrent cold requests can create duplicate pools. Only affects cold-start race on free-tier Render. Deferred per 05-REVIEW.md. |
| `app/db/repo.py` | 776 | `SELECT pr.*` in `load_all_runs` | WARNING (WR-03 deferred) | Fetches full JSONB blobs on every runs-list page load. Deferred per 05-REVIEW.md. |
| `app/main.py` | 547 | `safe_name = emp_name.replace(" ", "_")` — no quote/newline sanitisation | WARNING (WR-04 deferred) | Content-Disposition header injectable via employee names containing `"` or `\r\n`. Deferred per 05-REVIEW.md. |
| `app/main.py` | 490-495 | `fixture_path` not containment-checked | WARNING (WR-05 deferred) | Path traversal risk if `eval/summary.json` is crafted. Low risk in demo context. Deferred per 05-REVIEW.md. |
| `app/main.py` | ~76-103 | `needs_clarification` absent from `_BADGE_CLASS`/`_BADGE_LABEL` | INFO (IN-01 deferred) | Status is unreachable in current flow; falls back to title-case. Deferred per 05-REVIEW.md. |
| `app/llm/client.py` | ~146 | Retry prompt echoes raw `ValidationError` including PII | INFO (IN-02 deferred) | PII in LLM provider retry prompt. Deferred per 05-REVIEW.md. |

No `TBD`, `FIXME`, or `XXX` markers found in any phase-modified production file. All deferred items are formally tracked in `.planning/todos/pending/260623-01-phase05-review-warnings.md` per the review resolution note and are NOT phase blockers.

---

### Human Verification Required

#### 1. Three-column layout renders in correct left-to-right order in a browser

**Test:** Open `/runs`, fire a test email, navigate to the run detail page.
**Expected:** The raw cleaned email body appears as the leftmost column, extracted data in the centre, paystubs on the right. Decision banner is visible above the grid.
**Why human:** CSS grid column order and visual layout cannot be asserted by template inspection or grep.

#### 2. Error path — banner and Re-trigger button are visible and functional

**Test:** Force a run to ERROR status (e.g. with a bad DB connection or a seed business whose LLM extraction fails), then navigate to its detail page.
**Expected:** Red error banner shows the `error_reason` string. "Re-trigger from Start" button is present. Clicking it restarts the run.
**Why human:** Requires a live app with a controllable error condition.

#### 3. Confirmation email subject carries real business name and pay period

**Test:** Approve a run through the operator gate and inspect the outbound `email_messages` row (or the gateway stub log).
**Expected:** `subject` = `"Payroll Confirmation — Coastal Cleaning — <date> to <date>"`. NOT the fallback `"Payroll Confirmation — Payroll Run — "`.
**Why human:** The CR-03 fix is wired correctly in code but verifying the assembled subject with real DB data requires a live run.

#### 4. Send Test Email fires two distinct runs on two consecutive clicks

**Test:** Click "Send Test Email" twice in quick succession on `/eval` or `/runs`.
**Expected:** Two distinct run rows appear in `/runs`, each with a unique UUID. No run is silently deduplicated.
**Why human:** Requires live DB writes to observe the uuid4 message_id deduplication logic in action.

#### 5. Eval view renders metrics, chart, and fixture raw bodies

**Test:** Navigate to `/eval` in a browser.
**Expected:** Headline metrics show non-zero F1 (~99%) and Decision Accuracy (100%). Chart SVG loads (not broken image). Fixture drill-in rows show truncated email text in the Raw Input column.
**Why human:** SVG loading and CSS rendering require a live HTTP server.

---

### Gaps Summary

No gaps. All five observable must-have truths are VERIFIED against the codebase. All 10 phase requirements are SATISFIED. The three Criticals from the code review (CR-01 JSONB-on-TEXT[] crash, CR-02 missing `updated_at` in RUN_COLS, CR-03 confirmation subject fallback values) are all fixed in the codebase and covered by dedicated regression tests in `tests/test_cr_regressions.py`. The five Warnings and two Info items from the review are formally deferred and tracked — they are not phase blockers.

The only blocking path to `status: passed` is human-in-the-loop verification of visual/runtime behaviours that cannot be confirmed by static code analysis.

---

_Verified: 2026-06-22_
_Verifier: Claude (gsd-verifier)_
