---
phase: quick
plan: "260720-lba"
type: execute
wave: 1
depends_on: []
files_modified:
  - app/routes/runs.py
  - tests/test_dashboard.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "GET /runs/{run_id}/pdf/{employee_id} generates the on-demand paystub PDF with ytd= populated from the employee's prior reconciled runs — parity with the emailed confirmation PDF (app/pipeline/delivery.py)"
    - "A new hermetic regression test in tests/test_dashboard.py proves the downloaded PDF reflects real YTD (YTD > current-period) when a strictly-prior reconciled run exists for that employee, and would fail if ytd= is dropped from the route"
    - "uv run pytest -q tests/test_dashboard.py passes; ruff clean on the two touched files; mypy --strict clean on app/routes/runs.py"
  artifacts:
    - path: "app/routes/runs.py"
      provides: "paystub_pdf() threads YTD into generate_paystub_pdf via load_prior_reconciled_paystub_totals + PaystubYtdTotals.from_prior"
      contains: "PaystubYtdTotals"
    - path: "tests/test_dashboard.py"
      provides: "Regression test locking the download-route YTD parity"
      contains: "pdf"
  key_links:
    - from: "app/routes/runs.py paystub_pdf"
      to: "app.db.repo.load_prior_reconciled_paystub_totals"
      via: "read for [item.employee_id] at run.pay_period_start"
      pattern: "load_prior_reconciled_paystub_totals"
    - from: "app/routes/runs.py paystub_pdf"
      to: "app.pipeline.pdf.PaystubYtdTotals.from_prior"
      via: "ytd= kwarg into generate_paystub_pdf"
      pattern: "PaystubYtdTotals.from_prior"
---

<objective>
Close the paystub-download YTD parity gap. The on-demand dashboard route
`paystub_pdf()` (`app/routes/runs.py`, `GET /runs/{run_id}/pdf/{employee_id}`, HITL-03)
calls `generate_paystub_pdf(...)` WITHOUT the `ytd=` argument, so an operator's manual
PDF download silently shows current-period values as YTD — while the emailed confirmation
PDF for the same run (`app/pipeline/delivery.py:115`) already shows real calendar-year YTD.
Thread YTD into the download route by mirroring the delivery.py pattern exactly, and lock
it with a hermetic regression test.

Scope fence: no schema change, no PDF-layout change, no change to
`generate_paystub_pdf`'s signature (its `ytd=` kwarg already exists, defaults to None).
Do NOT touch the emailed-PDF path (already correct) or the Content-Disposition filename
sanitization (`re.sub(..., flags=re.ASCII)` — leave verbatim).
</objective>

<context>
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Thread YTD into the on-demand paystub download route</name>
  <files>app/routes/runs.py</files>
  <action>
In `paystub_pdf()` (the `@router.get("/runs/{run_id}/pdf/{employee_id}")` route):

1. Extend the existing local import to also import `PaystubYtdTotals`:
   `from app.pipeline.pdf import generate_paystub_pdf, PaystubYtdTotals`
   (Keep it a function-local import, matching the current code. Alphabetize if the
   file's ruff/isort config expects it: `PaystubYtdTotals, generate_paystub_pdf`.)

2. After `run` and the matched line-item `item` are loaded (the route already fetches
   `item` via `next((p for p in paystubs if str(p.employee_id) == str(employee_id)), None)`
   and `run = repo.load_run(run_id)`), load prior reconciled totals for this one employee,
   mirroring `app/pipeline/delivery.py:115`:

   ```python
   prior_ytd = repo.load_prior_reconciled_paystub_totals(
       run["business_id"],
       [item.employee_id] if item.employee_id else [],
       run.get("pay_period_start"),
   )
   ```
   (No `conn=` — this route is a plain read, no transaction context. The helper returns
   `{}` when `pay_period_start` is None or the id list is empty, so both edge cases are
   already safe.)

3. Pass `ytd=` into the EXISTING `generate_paystub_pdf(...)` call (do not add a second
   call — add the one kwarg):

   ```python
   ytd=PaystubYtdTotals.from_prior(
       prior_ytd.get(item.employee_id) if item.employee_id else None,
       item,
   ),
   ```

Signatures for reference (do not modify them):
- `repo.load_prior_reconciled_paystub_totals(business_id, employee_ids: list[uuid.UUID], pay_period_start: date | None, conn=None) -> dict[uuid.UUID, dict[str, Decimal]]` (`app/db/repo/demo.py:144`, exported via `app.db.repo`)
- `PaystubYtdTotals.from_prior(prior: Mapping[str, Decimal] | None, item: PaystubLineItem) -> PaystubYtdTotals` (`app/pipeline/pdf.py:125`)
  </action>
  <verify>uv run ruff check app/routes/runs.py && uv run mypy --strict app/routes/runs.py</verify>
  <done>paystub_pdf passes a populated ytd= to generate_paystub_pdf; ruff + mypy --strict clean on app/routes/runs.py.</done>
</task>

<task type="auto">
  <name>Task 2: Hermetic regression test locking the download-route YTD parity</name>
  <files>tests/test_dashboard.py</files>
  <action>
Add a regression test to `tests/test_dashboard.py` following the existing hermetic
patterns in that file (the `fake_repo` fixture + module-level `client = TestClient(app,
raise_server_exceptions=False)`; no real DB).

The fake repo already provides `load_prior_reconciled_paystub_totals` (`tests/conftest.py:681`,
registered in the monkeypatch tuple at `tests/conftest.py:2831`). Arrange the fake so that
for the target run + employee:
  - a paystub line-item exists (current-period values), AND
  - `load_prior_reconciled_paystub_totals` returns non-zero PRIOR totals for that
    `employee_id` (i.e. at least one strictly-prior reconciled run's worth of gross/FICA/
    net). Inspect the conftest fake's shape at :681 and drive it the way existing tests do
    (a setter/seed helper if one exists, else monkeypatch the fake's return for this test).

Then:
  - `GET /runs/{run_id}/pdf/{employee_id}` → assert 200 and `content-type: application/pdf`
    and the body starts with `b"%PDF"`.
  - Prove `ytd=` was threaded through. Prefer a robust assertion that does NOT depend on
    parsing rendered PDF glyphs: e.g. monkeypatch/spy `app.routes.runs.generate_paystub_pdf`
    (or the symbol as imported in the route) to capture the `ytd` kwarg it was called with,
    and assert the captured `PaystubYtdTotals` has YTD figures STRICTLY GREATER than the
    current line-item's own figures (gross_pay / net_pay), which can only happen if prior
    totals were summed in via `from_prior`. This fails if the route drops `ytd=` (regression
    lockout). If a spy is impractical, fall back to asserting the rendered PDF text contains
    the YTD column total — but the spy approach is preferred (deterministic, glyph-free).

Keep the test hermetic and self-contained; do not require DATABASE_URL or network.
  </action>
  <verify>uv run pytest -q tests/test_dashboard.py && uv run ruff check tests/test_dashboard.py</verify>
  <done>New test passes; it fails if ytd= is removed from paystub_pdf; ruff clean on tests/test_dashboard.py.</done>
</task>

</tasks>

<verification>
Full gate (run after both tasks):
- `uv run pytest -q tests/test_dashboard.py` — green (incl. the new test)
- `uv run ruff check app/routes/runs.py tests/test_dashboard.py` — clean
- `uv run mypy --strict app/routes/runs.py` — clean
Sanity: temporarily reverting the `ytd=` kwarg in paystub_pdf should turn the new test RED
(mention this in the SUMMARY; do not leave it reverted).
</verification>
