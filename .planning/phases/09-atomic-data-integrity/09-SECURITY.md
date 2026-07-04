---
phase: 9
slug: atomic-data-integrity
status: verified
threats_open: 0
asvs_level: 1
created: 2026-07-04
---

# Phase 9 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register origin: plan-time (`<threat_model>` blocks in all 6 PLAN.md files). Audit verified all
> `mitigate` dispositions against current HEAD (post gap-closure `09-06` and review-fix commits
> `8eb937e`/`a676c52`/`a6d4e2e`) — including mitigations relocated or strengthened by later commits.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Resend (external) → `POST /webhook/inbound` | Untrusted network input; dedup/ingest transaction guarantees exactly-once run creation under duplicate/racing delivery | Raw client email (payroll hours, names — PII) |
| Unauthenticated `GET /runs` → sweep UPDATE | Sweep runs on every dashboard load (matches route's existing auth posture); blast radius bounded by hardcoded scope list | Run status transitions only |
| Background task (extract/decide) → persist transaction | LLM output is Pydantic-validated before the transaction boundary; Phase 9 changed WHEN validated data commits, not what is trusted | Extracted payroll data |
| `_deliver`/`_clarify` finalize transactions ↔ provider send | Sends are irreversible; no DB transaction ever spans a provider call (D-9-01); at-least-once windows resolve to recoverable, diagnosable states | Outbound email + send state |
| App → DeepSeek/Kimi (external LLM providers) | Bounded timeouts + `max_retries=0` cap how long a hung provider can stall a run (resilience boundary; output validated post-hoc) | Email text (PII) → provider |
| Operator (dashboard) → `POST /runs/{run_id}/retrigger` | Human recovery path for swept/stranded runs; exercised via HTTP in tests | Status CAS |
| Clarification reply (client text) → resume extraction context | Known accepted gap: earlier-round corrections can drop from later rounds' context (T-09-21, deferred MONEY finding) | Client-supplied corrections |
| Test double → `app.db.repo.get_connection` | `FakeConnection.transaction()` is a documented no-op; genuine rollback proof lives in two-factor-guarded live-DB integration tests | n/a (test seam) |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-09-01 | Tampering (TOCTOU) | `sweep_stranded_runs` | mitigate | Single CAS `UPDATE … WHERE status = ANY(%s) AND updated_at < … RETURNING id` (`app/db/repo.py:484-499`); sanctioned-writer doc at `:462`; SQL-shape test `tests/test_stuck_run_recovery.py:39` | closed |
| T-09-02 | DoS (over-broad sweep) | `sweep_stranded_runs` scope | mitigate | `_STRANDED_SCOPE_STATUSES = ["received","extracting","computed"]` hardcoded in module (`app/db/repo.py:456`, used `:496`); scope-pin test `tests/test_stuck_run_recovery.py:68` + live parked-status test `:332` | closed |
| T-09-05 | Tampering (partial write) | `_run_stages` persist txn | mitigate | One `conn.transaction()` wraps all persist writes, status last (`app/pipeline/orchestrator.py:949-958`); fault-injection test `tests/test_atomic_persist.py:170` + call-order pin `:234` | closed |
| T-09-06 | Repudiation (DB claims "no email sent") | `_deliver`/`_clarify` finalize txns | mitigate | No txn spans a send: `_clarify` txn opens after `send_outbound` (`orchestrator.py:1160` → `:1175-1178`); `_deliver` finalize `:1427` after send `:1408-1416`; reserved-row pre-send marker `:1406-1407` | closed |
| T-09-07 | Tampering (alias failure rolls back delivery) | `_deliver` alias try/except | mitigate | Strengthened into SAVEPOINT form (see T-09.06-02): try/except `orchestrator.py:1449-1457` inside finalize txn wrapping only `_write_aliases_if_safe`; test `tests/test_atomic_persist.py:726` | closed |
| T-09-09 | Tampering (duplicate financial run) | `inbound()` dedup+create_run | mitigate | `uq_message_id` UNIQUE (`db/schema.sql:218`) + `ON CONFLICT DO NOTHING` (`app/db/repo.py:180`) in ONE txn (`app/main.py:370-452`); real-thread race test `tests/test_webhook_dedup_race.py:29` | closed |
| T-09-10 | DoS (orphaned email row) | `inbound()` ingest txn | mitigate | Dedup + reply-classification + routing + create_run in one txn (`app/main.py:370-452`); scheduling strictly post-commit (`:453-454`); WR-03 reply-linking landed inside the same txn (strengthens) | closed |
| T-09-11 | Repudiation (stuck run invisible) | `runs_list()` sweep hook | mitigate | Sweep on every dashboard load (`app/main.py:1073-1076`); `StrandedRunSwept` sentinel + pre-update status (`app/db/repo.py:487-498`); tests `tests/test_stuck_run_recovery.py:180`, `:212` | closed |
| T-09-13 | DoS (hung LLM defeats sweep) | `call_structured` client | mitigate | `OpenAI(…, timeout=_STRUCTURED_TIMEOUT_S, max_retries=0)` (`app/llm/client.py:139-144`, 45s at `:73`); ceiling ×2 app attempts; test `tests/test_llm_client.py:311` | closed |
| T-09-15 | Info Disclosure (PII-scrub bypass) | `_deliver` finalize vs WR-04 wrapper | mitigate | Finalize txn (`orchestrator.py:1427-1463`) INSIDE the try whose except attaches `exc.payroll_roster` (`:1357`, `:1464-1471`); test `tests/test_atomic_persist.py:856` | closed |
| T-09-16 | Tampering (resume write ahead of unprotected send) | `_defer_field_regression_clarification` Step-3 | mitigate | Step-3 `set_clarified_fields` in own single-statement txn before `_clarify` (`orchestrator.py:807-809` → `:826`); tests `tests/test_atomic_persist.py:401`, `:468` | closed |
| T-09-17 | Tampering (reply creates second run) | `inbound()` reply-classification ordering | mitigate | Reply-classification reads inside ingest txn strictly before any `create_run` (`app/main.py:395-438`); test `tests/test_webhook.py:126` | closed |
| T-09-19 | Repudiation (retry-over-sent skips alias learning) | `_deliver` already-sent guard | mitigate | Guard attempts `_write_aliases_if_safe` before SENT/RECONCILED (`orchestrator.py:1311-1337`); exactly-once test `tests/test_atomic_persist.py:887` | closed |
| T-09-20 | DoS (`call_text` unbounded) | `call_text` client (all callers) | mitigate | Unconditional `max_retries=0` (`app/llm/client.py:237`); `compose_clarification` passes `timeout_s=_CLARIFICATION_TIMEOUT_S` (30.0) (`app/pipeline/compose_email.py:178-179`, `:38`); tests `tests/test_llm_client.py:370`, `:387` | closed |
| T-09.06-01 | Tampering (Round-2 provenance crash window) | `resume_pipeline` clarified_fields write | mitigate | Write commits in own txn strictly before `_run_stages` (`orchestrator.py:633-637`; relocated from planned ~604 by later edits, intent intact); tests `tests/test_atomic_persist.py:541`, `:656` | closed |
| T-09.06-02 | Repudiation (DB-level alias failure poisons finalize) | `_deliver` finalize SAVEPOINT | mitigate | Nested `conn.transaction()` SAVEPOINT (`orchestrator.py:1450`) inside try/except `:1449-1457` with rationale `:1436-1448`; genuine-DB-level fault-injection test `tests/test_atomic_persist.py:759` | closed |
| T-09-03 | Repudiation (untraceable sweep) | sweep `error_detail` | accept | Sentinel + pre-update status only, no PII in string (`app/db/repo.py:487-498`) | closed |
| T-09-04 | Tampering (test-double drift) | `conftest.py` fake_repo | accept | `FakeTransaction` documented no-op (`tests/conftest.py:104-112`); real proof in `@pytest.mark.integration` group | closed |
| T-09-08 | Info Disclosure (live-DB tests) | `test_atomic_persist.py` integration tests | accept | Two-factor guard `DATABASE_URL` + `ALLOW_DB_RESET=1` (`tests/test_atomic_persist.py:38-43`); 11 skips confirmed offline | closed |
| T-09-12 | DoS (sweep threshold tension) | `STALE_THRESHOLD_SECONDS` | accept | 15-min threshold with rationale tied to 09-04's tightened LLM ceilings (`app/main.py:93-101`); Phase 10 venue (09-CONTEXT.md:49) | closed |
| T-09-14 | Tampering (zombie `set_status` overwrites ERROR) | D-9-13 accepted tension | accept | 09-CONTEXT.md:49/:128; independently re-found as CX-02 (09-REVIEWS.md:144-148) — acceptance documentation covers the CX-02 shape; Phase 10 concurrency work is the designated venue | closed |
| T-09-18 | Repudiation (retrigger loses reply context) | `retrigger()` dispatch | accept | Explicit code comment (`app/main.py:717-732`) + 09-CONTEXT.md Deferred Ideas (`:120`) | closed |
| T-09-21 | Tampering (multi-round context loss — MONEY class) | `resume_pipeline` combined extraction | accept | Known-edge fixture `tests/test_multiround_context_edge.py:180` + 09-CONTEXT.md:150 deferred finding; independently re-found as CX-01 (09-REVIEWS.md cross-AI code review), validating CRITICAL-class priority for a future MONEY phase | closed |
| T-09.06-03 | DoS (test resource exhaustion) | 09-06 live-DB tests | accept | `@pytest.mark.integration` + two-factor guard (`tests/test_atomic_persist.py:38-43`, `:725`, `:758`) | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-09-01 | T-09-03 | Sweep error_detail carries only a sentinel + pre-update status — no PII surface exists to mitigate | plan-time threat model (09-01) | 2026-07-04 |
| AR-09-02 | T-09-04 | FakeConnection no-op transaction is documented; genuine rollback proof deferred to live-DB integration tests per project convention | plan-time threat model (09-01) | 2026-07-04 |
| AR-09-03 | T-09-08 | Live-DB tests two-factor skip-guarded; no secrets logged | plan-time threat model (09-02) | 2026-07-04 |
| AR-09-04 | T-09-12 | Sweep-threshold vs in-flight-task tension documented; LLM ceilings tightened in 09-04; Phase 10 is the venue for further hardening evidence | plan-time threat model (09-03), 09-CONTEXT.md | 2026-07-04 |
| AR-09-05 | T-09-14 | Zombie-worker `set_status` overwrite (= CX-02 in cross-AI review) accepted per D-9-13; fencing design belongs to Phase 10 concurrency proof | plan-time threat model (09-04), 09-CONTEXT.md | 2026-07-04 |
| AR-09-06 | T-09-18 | Retrigger restarts from original inbound email by design ("never auto-restart" philosophy); operator retains visibility | plan-time threat model (09-03) | 2026-07-04 |
| AR-09-07 | T-09-21 | Multi-round context loss (= CX-01) is a MONEY-class correctness gap out of Phase 9 scope — proven by known-edge fixture, tracked for a future MONEY phase | plan-time threat model (09-05), 09-CONTEXT.md | 2026-07-04 |
| AR-09-08 | T-09.06-03 | Live-DB fault-injection tests guarded identically to the existing convention | plan-time threat model (09-06) | 2026-07-04 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-04 | 24 | 24 | 0 | gsd-security-auditor (register: plan-time; verified at HEAD `a6d4e2e` lineage; pinning tests: 36 passed, 11 expected live-DB skips) |

**Audit notes:**
- Post-plan drift verified: WR-03 reply-linking sits inside the ingest transaction (strengthens T-09-10/T-09-17); CX-03 suppress-detection guard touches no verified transaction boundary; T-09-07's planned bare try/except now exists in its stronger SAVEPOINT form (T-09.06-02).
- Process observation (informational): `09-01-SUMMARY.md` and `09-02-SUMMARY.md` omit the `## Threat Flags` section entirely; their surfaces are fully covered by their own plans' threat models, so no unmapped surface results.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-04
