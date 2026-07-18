---
phase: 20
slug: exactly-once-send
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-18
---

# Phase 20 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Browser POST → review/retrigger routes | Operator input selects an explicit bounded action; it must not bypass review or supersede active provider authority. | Route/form data; payroll state |
| Producer → durable queue | Approval and clarification producers may schedule identifier-only work after persistence commits. | Run/email/snapshot identifiers |
| Queue lease/snapshot/run → provider handoff | A worker requires an exact current lease, immutable snapshot, purpose/status, and epoch before a provider call. | Frozen email/PDF bytes; authorization metadata |
| Gateway → Resend | The provider receives frozen content with a Message-ID-derived idempotency key and a fixed replay deadline. | Email envelope/body/PDF; idempotency key |
| Provider result → settlement/review | Result handling can mutate a job, ledger, and review state only through the matching exact owner. | Bounded result categories; job/attempt state |
| Retrigger/reply epoch → active handoff | An epoch-changing action must reject while a provider handoff remains unresolved. | Reply generation and handoff metadata |
| Tests/CI → durability claim | Real-Postgres proofs and guarded database reset controls prevent a missing or unsafe test from being treated as evidence. | Test credentials; disposable database state |

---

## Threat Register

All 104 threats were parsed from the 27 executed Phase-20 plan threat models. “CLOSED” means the planned mitigation is present in implementation/test evidence and is corroborated by the phase verification report.

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-20-01-01 | Tampering | Retry-supplied content overwrites the original logical email | high | mitigate | Plan 20-01 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-01-02 | Information disclosure | Attachment content leaks through transport rows or review queries | high | mitigate | Plan 20-01 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-01-03 | Information disclosure | Attempt diagnostics retain provider payload or exception text | medium | mitigate | Plan 20-01 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-02-01 | Tampering | A route or malformed job injects mutable mail content into the queue | high | mitigate | Plan 20-02 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-02-02 | Denial of service | A send kind exists before its consumer and is silently stranded | high | mitigate | Plan 20-02 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-02-03 | Elevation of privilege | A wrong run/email pairing causes cross-run provider action | high | mitigate | Plan 20-02 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-03-01 | Tampering | Same key is sent with drifted payload and loses provider deduplication | high | mitigate | Plan 20-03 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-03-02 | Repudiation | Expired idempotency key permits an automatic duplicate email | high | mitigate | Plan 20-03 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-03-03 | Tampering | Payload mismatch triggers automatic fresh key creation | high | mitigate | Plan 20-03 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-04-01 | Tampering | Approval-time crash loses content or causes a later rebuilt payload | high | mitigate | Plan 20-04 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-04-02 | Tampering | HTTP approval races a worker or direct provider path | high | mitigate | Plan 20-04 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-04-03 | Denial of service | Safe retry changes payroll business state to error | high | mitigate | Plan 20-04 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-05-01 | Denial of service | A dispatch entry imports a missing handler or receives unowned context | high | mitigate | Plan 20-05 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-05-02 | Tampering | Handler bypasses exact-token settlement | high | mitigate | Plan 20-05 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-05-03 | Tampering | Handler recomposes or regenerates provider content | high | mitigate | Plan 20-05 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-06-01 | Elevation of privilege | Form tampering creates a duplicate without conscious operator authorization | high | mitigate | Plan 20-06 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-06-02 | Information disclosure | Provider diagnostics or payload bytes are rendered in the browser | high | mitigate | Plan 20-06 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-06-03 | Tampering | Retry-now races active work or invokes provider directly | high | mitigate | Plan 20-06 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-07-01 | Tampering | Re-rendered paystub changes an idempotent provider payload | high | mitigate | Plan 20-07 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-07-02 | Tampering | Incomplete YTD data misrepresents payroll history | high | mitigate | Plan 20-07 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-07-03 | Information disclosure | Historical YTD data leaks across employees | high | mitigate | Plan 20-07 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-08-01 | Tampering | Visual refactor alters reported evaluation truth | high | mitigate | Plan 20-08 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-08-02 | Tampering | Eval polish crosses into delivery persistence or frozen snapshots | high | mitigate | Plan 20-08 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-08-03 | Information disclosure | SVG exposes fixture-level sensitive text | medium | mitigate | Plan 20-08 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-09-01 | Tampering | Reclaimed zombie lease records a second attempt or reopens review | high | mitigate | Plan 20-09 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-09-02 | Tampering | Generic retry rewinds approved payroll state | high | mitigate | Plan 20-09 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-09-03 | Repudiation | Stale provider key is retried after retention safety margin | high | mitigate | Plan 20-09 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-10-01 | Denial of service | Producer creates a job before a safe consumer can settle it | high | mitigate | Plan 20-10 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-10-02 | Tampering | Repeated clarification draft changes a provider payload/key | high | mitigate | Plan 20-10 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-10-03 | Elevation of privilege | Scheduled send writes a confirmed alias | high | mitigate | Plan 20-10 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-11-01 | Tampering | Shared delivery settlement sends a clarification through confirmation review | high | mitigate | Plan 20-11 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-11-02 | Elevation of privilege | Delivery replay confirms an alias without a human reply decision | high | mitigate | Plan 20-11 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-11-03 | Tampering | A stale worker changes clarification state after lease reclaim | high | mitigate | Plan 20-11 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-12-01 | Tampering | A forgotten producer sends mutable caller content around the snapshot | high | mitigate | Plan 20-12 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-12-02 | Tampering | A compatibility import turns into a silent provider fallback | high | mitigate | Plan 20-12 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-12-03 | Tampering | Clarification migration loses thread/round or writes alias state | high | mitigate | Plan 20-12 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-13-01 | Tampering | A claimed job settles a different outbound snapshot | high | mitigate | Plan 20-13 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-13-02 | Repudiation | Timeout/5xx ambiguity is replayed after the safe category or time boundary | high | mitigate | Plan 20-13 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-13-03 | Tampering | Final lease expiry bypasses review and generic recovery creates a duplicate | high | mitigate | Plan 20-13 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-13-04 | Denial of service | Retry-now and worker settlement deadlock while holding opposite locks | high | mitigate | Plan 20-13 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-14-01 | Tampering | A stale clarification header resumes the wrong epoch | high | mitigate | Plan 20-14 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-14-02 | Information disclosure | Review callers receive payroll/client body content unnecessarily | high | mitigate | Plan 20-14 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-14-03 | Tampering | Compatibility code mutates inbound or arbitrary email state | high | mitigate | Plan 20-14 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-15-01 | Tampering | A fake accepts a malformed send job that production rejects | high | mitigate | Plan 20-15 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-15-02 | Repudiation | Fake review evidence reports zero attempts and hides duplicate risk | high | mitigate | Plan 20-15 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-15-03 | Tampering | Fake tests replay an unsafe retryable delivery reason | high | mitigate | Plan 20-15 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-15-04 | Tampering | Fake tests authorize stale replies or generic clarification recovery | high | mitigate | Plan 20-15 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-15-05 | Information disclosure | Fake projection exposes frozen body text to broad callers | high | mitigate | Plan 20-15 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-16-01 | Tampering | Ambiguous clarification is mistaken for a name-resolution problem | high | mitigate | Plan 20-16 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-16-02 | Tampering | Clarification retry creates a second logical question or fresh content | high | mitigate | Plan 20-16 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-16-03 | Elevation of privilege | Operator form silently confirms an alias or sends a second email | high | mitigate | Plan 20-16 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-16-04 | Information disclosure | Frozen question or provider diagnostics leak through the browser | high | mitigate | Plan 20-16 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-17-01 | Tampering | `get_outbound_message_id` | high | mitigate | Plan 20-17 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-17-02 | Denial of service | confirmation delivery proof branch | medium | mitigate | Plan 20-17 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-17-SC | Tampering | uv package installation | high | mitigate | Plan 20-17 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-18-01 | Tampering | `send_outbound.py` handler | critical | mitigate | Plan 20-18 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-18-02 | Tampering | `settle_outbound_delivery_job` | critical | mitigate | Plan 20-18 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-18-03 | Denial of service | `reap_expired_final_attempt` | high | mitigate | Plan 20-18 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-18-SC | Tampering | uv package installation | high | mitigate | Plan 20-18 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-19-01 | Tampering | invalid-context settlement | critical | mitigate | Plan 20-19 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-19-02 | Denial of service | `drain_once` token bookkeeping | high | mitigate | Plan 20-19 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-19-03 | Repudiation | LOST_LEASE versus INVALID_CONTEXT reporting | medium | mitigate | Plan 20-19 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-19-SC | Tampering | uv package installation | high | mitigate | Plan 20-19 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-20-01 | Elevation of privilege | confirmation review POST routes | critical | mitigate | Plan 20-20 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-20-02 | Tampering | advance_existing_send_job_due_now | high | mitigate | Plan 20-20 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-20-03 | Repudiation | fake repository parity | medium | mitigate | Plan 20-20 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-20-04 | Denial of service | bare mypy quality gate | medium | mitigate | Plan 20-20 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-20-SC | Tampering | uv package installation | high | mitigate | Plan 20-20 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-21-01 | Tampering | provider authorization | critical | mitigate | Plan 20-21 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-21-02 | Tampering | clear_reply_context | critical | mitigate | Plan 20-21 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-21-03 | Denial of service | lock protocol | high | mitigate | Plan 20-21 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-21-04 | Information disclosure | handoff diagnostics | high | mitigate | Plan 20-21 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-21-SC | Tampering | uv package installation | high | mitigate | Plan 20-21 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-22-01 | Tampering | handler authority | critical | mitigate | Plan 20-22 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-22-02 | Tampering | Resend provider entry | critical | mitigate | Plan 20-22 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-22-03 | Denial of service | synchronous SDK transport | high | mitigate | Plan 20-22 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-22-04 | Information disclosure | timeout/expiry diagnostics | medium | mitigate | Plan 20-22 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-22-SC | Tampering | uv package installation | high | mitigate | Plan 20-22 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-23-01 | Tampering | provider/epoch race | critical | mitigate | Plan 20-23 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-23-02 | Repudiation | queueproof evidence | high | mitigate | Plan 20-23 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-23-03 | Denial of service | test cleanup | medium | mitigate | Plan 20-23 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-23-04 | Information disclosure | test logs | medium | mitigate | Plan 20-23 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-23-SC | Tampering | uv package installation | high | mitigate | Plan 20-23 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-24-01 | Tampering | delivery settlement | critical | mitigate | Plan 20-24 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-24-02 | Tampering | reaper/reclaim | critical | mitigate | Plan 20-24 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-24-03 | Repudiation | delivery review | high | mitigate | Plan 20-24 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-24-04 | Information disclosure | fake diagnostics | medium | mitigate | Plan 20-24 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-24-SC | Tampering | uv package installation | high | mitigate | Plan 20-24 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-25-01 | Elevation of privilege | generic retrigger | critical | mitigate | Plan 20-25 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-25-02 | Tampering | review resolution | critical | mitigate | Plan 20-25 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-25-03 | Repudiation | authorization acknowledgement | high | mitigate | Plan 20-25 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-25-04 | Information disclosure | route responses | medium | mitigate | Plan 20-25 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-25-SC | Tampering | uv package installation | high | mitigate | Plan 20-25 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-26-01 | Tampering | handler result normalization | critical | mitigate | Plan 20-26 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-26-02 | Tampering | no-handoff settlement | critical | mitigate | Plan 20-26 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-26-03 | Repudiation | delivery evidence | high | mitigate | Plan 20-26 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-26-04 | Information disclosure | browser/review diagnostics | medium | mitigate | Plan 20-26 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-26-SC | Tampering | uv package installation | high | mitigate | Plan 20-26 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-27-01 | Tampering | schema vocabulary drift | critical | mitigate | Plan 20-27 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-27-02 | Repudiation | delivery-review evidence | critical | mitigate | Plan 20-27 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-27-03 | Tampering | provider boundary | critical | mitigate | Plan 20-27 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-27-04 | Denial of service | database reset | high | mitigate | Plan 20-27 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-27-05 | Repudiation | queueproof evidence | high | mitigate | Plan 20-27 mitigation; implemented and verified in the phase report. | CLOSED |
| T-20-27-SC | Tampering | uv package installation | high | mitigate | Plan 20-27 mitigation; implemented and verified in the phase report. | CLOSED |

*Status: closed · open · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit 2026-07-18

| Metric | Count |
|--------|-------|
| Threats found | 104 |
| Closed | 104 |
| Open | 0 |

Evidence used: every Phase-20 PLAN threat model (27/27), every completed SUMMARY (27/27, with no additional threat flags), the passing Phase-20 verification report (4/4 roadmap truths), source-level boundary checks, and `uv run pytest -q tests/test_send_idempotency.py tests/test_gateway.py tests/test_phase20_fake_parity.py` (`126 passed, 6 skipped`).

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-18 | 104 | 104 | 0 | Codex (L1 inline audit) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-18

