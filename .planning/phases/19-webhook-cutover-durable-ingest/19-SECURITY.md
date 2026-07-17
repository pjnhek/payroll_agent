---
phase: 19
slug: webhook-cutover-durable-ingest
status: verified
threats_open: 0
asvs_level: 1
block_on: high
register_authored_at_plan_time: true
created: 2026-07-17
---

# Phase 19 — Security

> ASVS L1 verification of the threat registers authored in all twelve Phase 19 plans. Evidence is the implemented source/test surface, plan summaries, canonical verification, and exact-revision GitHub runs at `130c038`.

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Public webhook → authenticated receipt | Untrusted streamed bytes cross size, signature, and minimal-envelope validation before persistence. | Provider envelope, Svix identity |
| Durable event → provider fetch → payroll state | A transport identifier authorizes later retrieval of sensitive email content and deterministic business processing. | Email body, headers, sender, roster-linked data |
| Operator form → payroll authority | User-controlled mappings compete to become the one money-moving generation. | Employee mappings, remember intent |
| Queue row/lease → handler and settlement | Identifier-only persisted work selects a handler; stale workers must not settle another lease or invent payroll authority. | Event/run/reply/resolution UUIDs, bounded outcomes |
| Deployment tooling → live Postgres | Schema and authority migration can irreversibly classify historical money-moving state. | Catalog state, aggregate inventory, writer-fence state |
| Jobs/query flags → browser | Internal queue state and failures are reduced to fixed recruiter-safe presentation. | Fixed labels and booleans only |
| Authenticated pump → retained PII | Scheduled maintenance removes terminal raw envelopes without deleting owed work or audit history. | Retention timestamps, event payloads |

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Evidence | Status |
|-----------|----------|-----------|----------|-------------|---------------------|--------|
| T19-01 | Tampering | operator authority migration | high | mitigate | `scripts/check_operator_resolution_inventory.py`, `scripts/migrate_operator_resolution_authority.py`, and migration tests enforce aggregate preflight, transactional recheck, sole-winner migration, and exact postflight. | closed |
| T19-01A | Tampering | legacy writer during cutover | high | mitigate | `app/db/schema.sql` plus migration/reopen tests install and hold the trigger fence under the required lock through activation. | closed |
| T19-02 | Tampering | schema drift health | high | mitigate | `app/db/schema_introspect.py` and schema tests compare exact catalog tuples, including malformed/multiple CHECK rejection. | closed |
| T19-03 | Information Disclosure | inventory/migration output | medium | mitigate | Inventory/migration tests pin aggregate-only output and reject identifiers, names, mappings, payloads, and raw database errors. | closed |
| T19-04 | Denial of Service | raw-event retention relationship | medium | mitigate | Received-time index, terminal-only bounded purge, open-work exclusions, and `ON DELETE SET NULL` audit preservation are test-pinned. | closed |
| T19-05 | Tampering | competing operator mappings | high | mitigate | `app/db/repo/operator_resume_resolutions.py` locks the run, chooses first committed authority, validates completeness, and preserves later generations as no-ops. | closed |
| T19-06 | Elevation of Privilege | cross-business employee mapping | high | mitigate | Operator-resolution repository/tests validate every employee against the run business roster before authority or alias projection. | closed |
| T19-07 | Repudiation | losing generation audit | medium | mitigate | Immutable resolution generations and generation-specific queue rows preserve superseded submissions. | closed |
| T19-08 | Information Disclosure | bounded submission result | medium | Typed repository/route results expose only authority booleans and UUIDs; focused tests reject mapping and diagnostic leakage. | closed |
| T19-09 | Spoofing | clarification reply sender | high | mitigate | `app/ingest.py`, `app/routes/pipeline_glue.py`, and `app/queue/handlers/resume_reply.py` require same-run ownership and sender/business revalidation before enqueue or resume. | closed |
| T19-10 | Tampering | DATA-02 transaction ordering | high | mitigate | Delayed ingest keeps classification, persistence, and identifier-only downstream enqueue in one caller-owned transaction; rollback/outcome tests pass. | closed |
| T19-11 | Information Disclosure | fetched message and diagnostics | high | mitigate | Bodies and sender data remain outside jobs, handler results, logs, and browser responses; bounded-domain tests pass. | closed |
| T19-12 | Repudiation | two-layer replay | medium | mitigate | `inbound_events` preserves unique Svix identity independently from RFC Message-ID uniqueness in `email_messages`; both replay layers are tested. | closed |
| T19-13 | Tampering | queue vocabulary/context | high | mitigate | `JobKind`, SQL constraints, `Job`, claim hydration, dispatch, and handler equality are exact and drift-tested. | closed |
| T19-14 | Elevation of Privilege | INGEST job context | high | mitigate | Open INGEST work accepts `event_id` only and rejects mixed run/reply/resolution identifiers before SQL and dispatch. | closed |
| T19-15 | Information Disclosure | job boundary | medium | Queue models and handlers retain identifiers and bounded outcomes only; provider envelope/body/sender/mappings are excluded. | closed |
| T19-16 | Elevation of Privilege | transport settlement | high | mitigate | `app/db/repo/job_settlement.py` branches on INGEST before run requirements; fail-if-called tests prove no payroll writer on null-run outcomes. | closed |
| T19-17 | Denial of Service | final-attempt null-run lease | high | mitigate | Final-attempt reaping dead-letters and clears the lease rather than perpetually fencing the job; real-Postgres queueproof coverage passes. | closed |
| T19-18 (19-05) | Tampering | stale worker settlement | high | mitigate | Lease-token and attempt fences protect every ingest settlement and reaper path. | closed |
| T19-19 (19-05) | Information Disclosure | fake/diagnostic boundary | medium | Fake parity and settlement tests retain bounded diagnostic codes and exclude transport PII. | closed |
| T19-W01 | Spoofing | `/webhook/inbound` | high | mitigate | `app/routes/webhook.py` verifies exact bounded bytes before parse/persistence; unsigned fixtures require explicit configuration. | closed |
| T19-W02 | Denial of Service | request body | high | mitigate | Streaming input is capped at 256 KiB before persistence; over-limit tests pass. | closed |
| T19-W03 | Denial of Service | synchronous receipt database work | high | mitigate | Receipt persistence is awaited through `run_in_threadpool`; slow-database responsiveness behavior is test-covered. | closed |
| T19-W04 | Tampering | event/job atomicity | high | mitigate | Inbound event and `ingest:{event_id}` job commit in one transaction before wake and HTTP response; rollback tests pass. | closed |
| T19-W05 | Information Disclosure | response/error boundary | medium | Responses expose fixed status plus stable event UUID; failure responses are fixed and diagnostics-free. | closed |
| T19-18 (19-07) | Tampering | demo transaction | high | mitigate | Both demo paths atomically commit allowlisted email, run, and identifier-only job before waking. | closed |
| T19-19 (19-07) | Denial of Service | duplicate/failed demo enqueue | medium | mitigate | Enqueue failure rolls back and presents one manual retry path without automatic re-enqueue. | closed |
| T19-20 | Information Disclosure | demo failure presentation | medium | mitigate | Routes map fixed query-flag presence to fixed copy; exceptions, identifiers, and body text never render. | closed |
| T19-21 | Repudiation | demo job ownership | low | accept | Stable run-scoped dedup and durable email/run/job audit rows are proportionate for the allowlisted recruiter demo surface. | closed — accepted |
| T19-22 | Spoofing | RESUME_REPLY handler | high | mitigate | Every attempt revalidates same-run ownership and sender/business identity before conversion or orchestration. | closed |
| T19-23 | Tampering | operator resume | high | mitigate | Handler consumes commit-selected authority, validates complete roster ownership, and drains superseded jobs before payroll/alias effects. | closed |
| T19-24 | Information Disclosure | redirect/log boundaries | high | mitigate | Fixed flags and bounded codes exclude senders, mappings, identifiers, and raw diagnostics. | closed |
| T19-25 | Repudiation | superseded submissions | medium | mitigate | Immutable generation plus job history records explicit supersession. | closed |
| T19-27 | Information Disclosure | queue/status projection | high | mitigate | Repository projection exposes fixed labels and open-work booleans only; IDs, attempts, timestamps, payloads, and diagnostics are stripped. | closed |
| T19-28 | Tampering | notice query flags | medium | mitigate | Query values are reduced to boolean presence and never rendered; Jinja autoescape remains active. | closed |
| T19-29 | Denial of Service | polling | medium | mitigate | Browser polling is read-only, fixed at two seconds, capped at 60 attempts, and performs no recovery mutation. | closed |
| T19-30 | Elevation of Privilege | queue state as payroll outcome | high | mitigate | Queue label fields remain separate from `RunStatus`; tests prohibit inference or mutation of payroll status from job state. | closed |
| T19-31 | Information Disclosure | retained inbound envelopes | high | mitigate | Authenticated pump invokes a 30-day, terminal-only, batch-capped raw-event purge. | closed |
| T19-32 | Denial of Service | premature retention | high | mitigate | Purge excludes pending/leased references and retains terminal job audit via nullable event linkage. | closed |
| T19-33 | Repudiation | durability proof | medium | mitigate | Lost-wake proof and GitHub run `29589513220` prove committed receipt plus later drain; unavailable evidence is never reported as a pass. | closed |
| T19-34 | Tampering | live authority/schema | high | mitigate | Migration blocks on ambiguity, migrates sole generations transactionally with `remember=false`, and requires exact schema/authority postflight. | closed |
| T19-35 | Tampering | legacy writer during deployment | high | mitigate | Persistent fence remains closed through preflight, schema, migration, activation, and repeated exact-revision postflight before reopen. | closed |
| T19-36 | Tampering | stale test consumers | high | mitigate | Nine named consumers use explicit durable seams; migrated suites and retired-name scans pass. | closed |
| T19-39 | Elevation of Privilege | inline request execution | high | mitigate | HTTP-boundary tests install fail-if-called execution spies and assert only committed identifier work. | closed |
| T19-40 | Information Disclosure | migrated route tests | medium | mitigate | Bounded response assertions exclude provider bodies, sender data, mappings, diagnostics, and job IDs. | closed |
| T19-37 | Denial of Service | deletion sequencing | high | mitigate | Compatibility deletion followed complete consumer migration and pre/post-deletion expanded suite passes. | closed |
| T19-38 | Repudiation | cutover architecture guard | high | mitigate | Nonempty exact inventory plus synthetic producer and retired-definition mutations prove the guard is non-vacuous. | closed |
| T19-41 | Elevation of Privilege | request-owned payroll execution | high | mitigate | Production request paths contain no background payroll scheduling seam and preserve identifier-only queue producers. | closed |
| T19-42 | Tampering | queued exception semantics | high | mitigate | Explicit `PipelineResult` value seams and drain tests route escaping failures through fenced settlement. | closed |

The plan set reused IDs `T19-18` and `T19-19` in Plans 19-05 and 19-07. This report preserves both authored entries and disambiguates them by source plan.

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-19-01 | T19-21 | The allowlisted recruiter demo already has stable run-scoped dedup and durable email/run/job audit rows; a stronger ownership ledger would add complexity without protecting a production client surface. | Phase 19 plan disposition | 2026-07-17 |

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-17 | 49 | 49 | 0 | Codex inline GSD security audit, ASVS L1 |

## Verification Evidence

- GitHub CI run `29589513261` at `130c038`: hermetic tests, mypy strict, and Ruff passed.
- GitHub concurrency-proof run `29589513220` at the same revision: real-Postgres invariants and queueproof gate passed; exact same-Svix node passed, with 44 passed and 1060 deselected.
- GitHub eval run `29589513190` and deploy-migrate run `29589513283`: passed.
- Canonical Phase 19 verification established all other implementation links and behavioral checks; `19-UAT.md` closes its sole previously unobserved real-Postgres truth with exact run evidence.
- No Phase 19 summary contains an additional `Threat Flags` entry.

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-17
