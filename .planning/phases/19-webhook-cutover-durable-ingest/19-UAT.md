---
status: testing
phase: 19-webhook-cutover-durable-ingest
source: [19-VERIFICATION.md]
started: 2026-07-17T05:57:53Z
updated: 2026-07-17T05:57:53Z
---

## Current Test

number: 1
name: Concurrent same-Svix real-Postgres deduplication
expected: |
  Two concurrent deliveries of the same Svix event ID produce exactly one
  durable inbound event, one INGEST job, and one payroll run after delayed
  ingest. The responses are one accepted receipt and one duplicate receipt
  carrying the same stable event ID.
awaiting: user response

## Tests

### 1. Concurrent same-Svix real-Postgres deduplication

expected: Run `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` against an isolated seeded Postgres database, or wire an isolated equivalent into the DB-backed CI gate, and observe exactly one event, one INGEST job, and one payroll run with no skipped test.
result: pending

## Summary

total: 1
passed: 0
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
