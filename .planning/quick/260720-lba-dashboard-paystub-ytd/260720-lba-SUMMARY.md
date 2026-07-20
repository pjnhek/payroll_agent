---
quick_id: 260720-lba
status: complete
one-liner: Threaded real YTD into the on-demand paystub download route (GET /runs/{run_id}/pdf/{employee_id}), mirroring the emailed confirmation PDF's YTD wiring in app/pipeline/delivery.py — closing the money-display parity gap. Locked with a hermetic spy-based regression test proven RED→GREEN.
key-files:
  modified:
    - app/routes/runs.py
    - tests/test_dashboard.py
metrics:
  duration: "~15 min"
  completed: 2026-07-20
---

# Quick Task 260720-lba: Dashboard Paystub Download YTD Parity — Summary

## What was done

Closed the paystub-download YTD parity gap described in the plan: the on-demand
dashboard route `paystub_pdf()` (`app/routes/runs.py`, `GET
/runs/{run_id}/pdf/{employee_id}`, HITL-03) called `generate_paystub_pdf(...)` without
the `ytd=` argument, so an operator's manual PDF download silently showed
current-period values as YTD, while the emailed confirmation PDF for the same run
(`app/pipeline/delivery.py:115`) already showed real calendar-year YTD.

**Task 1 — `app/routes/runs.py`:** Extended the existing function-local import to also
pull in `PaystubYtdTotals`, then mirrored `delivery.py`'s wiring exactly: after `item`
and `run` are loaded, call
`repo.load_prior_reconciled_paystub_totals(run["business_id"], [item.employee_id] if
item.employee_id else [], run.get("pay_period_start"))` (no `conn=` — this route is a
plain read outside any transaction), then pass
`ytd=PaystubYtdTotals.from_prior(prior_ytd.get(item.employee_id) if item.employee_id
else None, item)` into the existing `generate_paystub_pdf(...)` call. No second call
added, no signature change, no PDF-layout change, no change to the
Content-Disposition filename sanitization (`re.sub(..., flags=re.ASCII)` left
verbatim).

**Task 2 — `tests/test_dashboard.py`:** Added
`test_paystub_pdf_download_route_threads_ytd_from_prior_reconciled_runs`, following
the file's existing hermetic pattern (direct `monkeypatch.setattr(_repo, ...)` on
`app.db.repo` functions + the module-level `client = TestClient(app,
raise_server_exceptions=False)` — same style as the neighboring
`test_paystub_pdf_content_disposition_sanitized`). The test:
- monkeypatches `load_line_items`, `load_run`, `load_roster_for_business`,
  `load_business_name`, and `load_prior_reconciled_paystub_totals` to seed one
  employee with a current-period `PaystubLineItem` plus non-zero prior reconciled
  totals;
- **spies on `app.pipeline.pdf.generate_paystub_pdf`** (patched at its defining
  module, since the route imports it via a function-local `from
  app.pipeline.pdf import ...` — patching the route's local name would not take
  effect) to capture the `ytd=` kwarg while still delegating to the real
  implementation, so the response body is a real, valid PDF;
- asserts `200`, `content-type: application/pdf`, body starts with `b"%PDF"`;
- asserts the captured `PaystubYtdTotals.gross_pay` / `.net_pay` are **strictly
  greater** than the current line item's own `gross_pay` / `.net_pay` — this can only
  be true if prior reconciled totals were summed in via `PaystubYtdTotals.from_prior`,
  making it a deterministic, glyph-free regression lockout (no rendered-PDF text
  parsing).

## Deviations from Plan

None — plan executed exactly as written. Both tasks matched the plan's described
signatures, line-number anchors, and the delivery.py reference pattern (verified
against `app/pipeline/delivery.py:115-136`) without drift.

## Regression Lockout — RED → GREEN Proof

Per the plan's verification section, the `ytd=` kwarg (and its
`PaystubYtdTotals.from_prior(...)` call) was **temporarily reverted** from
`paystub_pdf()` in `app/routes/runs.py`, the new test alone was re-run, and then the
fix was restored.

**RED (kwarg reverted):**
```
$ uv run pytest -q tests/test_dashboard.py::test_paystub_pdf_download_route_threads_ytd_from_prior_reconciled_runs
...
        assert len(captured_ytd) == 1, "generate_paystub_pdf must be called exactly once"
        ytd = captured_ytd[0]
>       assert ytd is not None, "paystub_pdf must pass a populated ytd= to generate_paystub_pdf"
E       AssertionError: paystub_pdf must pass a populated ytd= to generate_paystub_pdf
E       assert None is not None
tests/test_dashboard.py:1561: AssertionError
1 failed, 1 warning in 0.68s
```

The `ytd=` kwarg was then restored verbatim (confirmed via `git diff` showing zero
residual change against the committed fix) — see GREEN verification below.

## Verification (actual command output, fix restored)

```
$ uv run pytest -q tests/test_dashboard.py
...................................................s....s                [100%]
55 passed, 2 skipped, 1 warning in 0.99s
```

```
$ uv run ruff check app/routes/runs.py tests/test_dashboard.py
All checks passed!
```

```
$ uv run mypy --strict app/routes/runs.py
Success: no issues found in 1 source file
```

**Extra confirmation (not required by the plan, run for scope confidence):**
```
$ uv run pytest -q tests/test_delivery.py
..................
18 passed in 0.33s
```

**Diff scope (`git diff --stat` before commit):**
```
 app/routes/runs.py      |  15 ++++++-
 tests/test_dashboard.py | 107 ++++++++++++++++++++++++++++++++++++++++++++++++
 2 files changed, 121 insertions(+), 1 deletion(-)
```
Confirmed: exactly the two plan-declared files, no schema change, no other route
touched, emailed-PDF path (`app/pipeline/delivery.py`) untouched.

## Commits

- `25e2582` — `fix(260720-lba): thread YTD into on-demand paystub download route`

## Self-Check: PASSED

- FOUND: app/routes/runs.py (edited, exists, ruff+mypy clean)
- FOUND: tests/test_dashboard.py (edited, exists, new test present and passing)
- FOUND: commit 25e2582 in `git log --oneline`
