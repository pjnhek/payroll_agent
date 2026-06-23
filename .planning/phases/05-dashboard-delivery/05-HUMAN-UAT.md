---
status: partial
phase: 05-dashboard-delivery
source: [05-VERIFICATION.md]
started: 2026-06-23T00:00:00Z
updated: 2026-06-23T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. 3-column honest gate renders in correct left-to-right order
expected: GET /runs/{run_id} shows three columns left→right — raw cleaned inbound email (leftmost) | LLM extracted_data | computed paystubs — with the decision reasons banner above the grid (DASH-02). CSS grid `1fr 1fr 1fr` column order is a visual/browser behaviour automated checks can't fully confirm.
result: [pending]

### 2. Error banner + Re-trigger button are visible and functional
expected: A run in `error` status surfaces an error banner on the run detail page and a working Re-trigger control that idempotently restarts the run (INGEST-05). Requires a live app with a controllable error.
result: [pending]

### 3. Confirmation email subject carries real business name + pay period
expected: Approving a run sends a confirmation whose subject is "Payroll Confirmation — {real business name} — {pay period}" (CR-03 fix), not the blank fallback. Requires a live approval run to inspect the assembled subject.
result: [pending]

### 4. Send Test Email fires two distinct runs on two consecutive clicks
expected: Clicking "Send Test Email" twice creates two distinct runs (fresh uuid4 Message-ID per click) and redirects to two distinct /runs/{run_id} URLs (DASH-05, MEDIUM finding). Requires live DB writes.
result: [pending]

### 5. Eval view renders metrics, chart, and fixture raw bodies
expected: GET /eval renders headline metrics, the per-category breakdown chart (chart.svg), and per-fixture raw bodies (DASH-04/05). SVG loading + CSS rendering require a live HTTP server.
result: [pending]

## Summary

total: 5
passed: 0
issues: 0
pending: 5
skipped: 0
blocked: 0

## Gaps
