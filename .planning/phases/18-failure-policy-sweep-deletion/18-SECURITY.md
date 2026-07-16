---
phase: 18
slug: failure-policy-sweep-deletion
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
register_authored_at_plan_time: true
created: 2026-07-16
---

# Phase 18 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Phase 18 replaces swallowed pipeline failures and the legacy dashboard sweep
> with a bounded `PipelineResult`, durable identifier-only resume jobs, fenced
> cross-aggregate settlement, final-attempt lease reaping, and read-only run
> listing. The STRIDE register was authored at plan time across all 14 plans and
> verified retroactively at OWASP ASVS L1 grep depth against the completed phase,
> its summaries, the passed `18-VERIFICATION.md`, and current implementation.

---

## Trust Boundaries

| Source plan | Boundary | Description | Data Crossing |
|-------------|----------|-------------|---------------|
| 18-01 | provider/LLM exception → pipeline result | Untrusted exceptions may contain prompts, responses, email content, provider details, or connection data and must reduce to bounded policy values. | Exception objects and potentially sensitive provider text |
| 18-01 / 18-10 / 18-11 | producer → consumer result graph | Every value-producing orchestration seam must return and consume one exact result; discarded or optional results recreate swallowed failure. | `PipelineResult` outcome, stage, reason, and bounded diagnostic |
| 18-02 / 18-09 | jobs row → resume handler | Typed identifiers select persisted email or operator-resolution context; independent identifiers are inputs, not proof of same-run authority. | Run, email, and operator-resolution UUIDs |
| 18-02 / 18-03 / 18-09 | validated operator POST → immutable resolution generation | A complete money-moving mapping crosses from the request into normalized immutable database rows before identifier-only scheduling. | Submitted names, employee UUIDs, remember choices |
| 18-02 / 18-12 | `schema.sql` expectation → deployed Postgres | An apparently successful deploy may still retain malformed tables, constraints, indexes, or job-kind checks. | Schema/catalog metadata and recovery-authority columns |
| 18-03 | background task → durable queue | A process-local first attempt hands retry authority to durable state without persisting raw exception data. | Run identifier and bounded retry classification |
| 18-03 / 18-04 / 18-13 | leased job/run pair → settlement | A lease token, row locks, and run state jointly authorize retry, terminal, exhaustion, or final-lease settlement. | Job state, run state, lease token, attempt history |
| 18-04 / 18-13 | expired lease → reaper authority | Expiry and the attempt cap authorize transport settlement without a live worker, but not arbitrary business-state overwrite. | Expired job lease and canonical `RunStatus` |
| 18-05 | drain outcome → HTTP accounting | Internal transport outcomes become operator-visible counters and must remain bounded and semantically honest. | Claimed/done/retried/dead/reaped integer counters |
| 18-06 | persisted diagnostics → browser | Database values cross into HTML and JSON and must be reduced before rendering. | Error reason/detail and bounded attempt projection |
| 18-06 | Retrigger action → immutable history | A human recovery action creates fresh work beside terminal records without rewriting dead history. | Run status, reply epoch, dedup key, new job generation |
| 18-07 | unauthenticated GET → durable state | The run-list read previously triggered mutation and scheduling; it must now remain a pure read projection. | Run rows and rendered dashboard state |
| 18-07 / 18-08 | supported reply/operator entry points → resume | Removing the legacy sweep must not subtract sender, consumed-reply, mapping, roster, epoch, or retrigger safeguards. | Inbound email context and deterministic operator mapping |
| 18-08 | repository facade/fakes → callers/tests | Public mutation seams define durable authority; permissive or obsolete fakes can conceal missing production contracts. | Repository methods and stateful fake behavior |
| 18-14 | persisted reply → payroll pipeline | Email content can affect money-moving reconciliation only after exact same-run ownership is proven. | Sender, subject, body, business and run association |
| 18-14 | invalid durable context → logs | Stored identifiers and message content must not escape through rejection diagnostics. | UUIDs, addresses, names, subject, and body |

---

## Threat Register

The original plan files reuse `T-18-12` through `T-18-15` in both Plans 18-03
and 18-04 for different threats. The Source column is therefore part of each
row's identity in this security record; no duplicate ID is silently conflated.

| Threat ID | Source | Category | Component | Severity | Disposition | Mitigation / Evidence | Status |
|-----------|--------|----------|-----------|----------|-------------|-----------------------|--------|
| T-18-01 | 18-01 | Information Disclosure | Pipeline result/classifier | high | mitigate | Frozen bounded enums and classifier in `app/pipeline/result.py`; hostile exception-text non-retention coverage in `tests/test_orchestrator_states.py`. | closed |
| T-18-02 | 18-01 | Tampering | Compatibility adapter | high | mitigate | One named `None` adapter with exact pass-through and invalid-type rejection; active optional-result compatibility was removed by 18-11 and guarded by the call-graph tests. | closed |
| T-18-03 | 18-01 | Denial of Service | Retry classifier | medium | mitigate | Retry is restricted to named extraction connection/timeout/rate-limit/5xx cases; all other stages and unknown failures default terminal. | closed |
| T-18-01-SC | 18-01 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency; `pyproject.toml` and `uv.lock` were not widened for this plan. | closed (accepted) |
| T-18-04 | 18-02 | Tampering | Operator resolution store | high | mitigate | Immutable UUID parent plus typed per-name child rows, strict run scoping, employee FKs, atomic insertion, and exact replay validation in `app/db/repo/operator_resume_resolutions.py`. | closed |
| T-18-05 | 18-02 | Tampering | `JobKind` / schema | high | mitigate | Exact Python/SQL/dispatch kind equality, per-kind identifier constraints, deployed CHECK replacement, and drift tests. | closed |
| T-18-06 | 18-02 | Information Disclosure | Transport schema | high | mitigate | Jobs carry typed identifiers only; there is no arbitrary payload, raw mapping, provider text, or alias-candidate authority. | closed |
| T-18-07 | 18-02 | Injection | Context repository SQL | medium | mitigate | Explicit column lists and parameterized UUID/name/delay/diagnostic inputs in the jobs and resolution repositories. | closed |
| T-18-02-SC | 18-02 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-12 | 18-03 | Tampering | `/resolve` persistence and operator retry | high | mitigate | Route-owned atomic immutable mapping persistence, post-commit identifier-only handoff, resolution-scoped dedup, signature guard, and rollback tests. | closed |
| T-18-13 | 18-03 | Denial of Service | Background retry bridge | high | mitigate | Replay-safe classified failures enqueue bounded delayed work for all entry points; no in-memory retry loop or terminal reclassification. | closed |
| T-18-14 | 18-03 | Tampering | Classified settlement | high | mitigate | Lease-token fence, run CAS, atomic rollback, immutable dead history, and one cross-aggregate settlement owner in `app/db/repo/job_settlement.py`. | closed |
| T-18-15 | 18-03 | Information Disclosure | Diagnostics / override rows | high | mitigate | Diagnostics are bounded codes; complete mappings remain only in typed DB rows and are excluded from jobs, logs, and UI. | closed |
| T-18-03-SC | 18-03 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-12 | 18-04 | Tampering | Drain result mapping | high | mitigate | Exhaustive typed outcome mapping treats clarification as OK and atomically settles retry, terminal, and infrastructure exhaustion. | closed |
| T-18-13 | 18-04 | Denial of Service | Final-attempt lease | high | mitigate | Exact expired-final-attempt predicate runs from the shared drain; 18-13 closed the prior starvation gap for every valid `RunStatus`. | closed |
| T-18-14 | 18-04 | Tampering | Reaper / run state | high | mitigate | `FOR UPDATE SKIP LOCKED`, run lock, disjoint status sets, active-state-only CAS, atomic job/run transaction, and rollback/fence tests. | closed |
| T-18-15 | 18-04 | Repudiation | Final reason | medium | mitigate | Active crash states receive bounded `FinalAttemptLeaseExpired`; prior `jobs.last_error` remains immutable attempt history. | closed |
| T-18-04-SC | 18-04 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-16 | 18-05 | Repudiation | Pump counters | high | mitigate | Reaped final leases count as dead maintenance, not claimed execution; invariant is pinned in `tests/test_pump_route.py`. | closed |
| T-18-17 | 18-05 | Tampering | Claimed arithmetic | medium | mitigate | Separate bounded drained counter preserves the 20-outcome request cap while table-driven tests preserve all legacy counter mappings. | closed |
| T-18-05-SC | 18-05 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-18 | 18-06 | Information Disclosure | Diagnostic rendering | high | mitigate | Strict grammar plus fixed allowlists reduce persisted diagnostics before list, detail, and polling HTML/JSON; hostile raw-text absence tests pass. | closed |
| T-18-19 | 18-06 | Tampering | Retrigger history | high | mitigate | ERROR-to-RECEIVED CAS creates a fresh epoch/dedup generation while preserving terminal job history; immutable-history regression coverage passes. | closed |
| T-18-20 | 18-06 | Spoofing | Retrigger route | medium | accept | Existing demo dashboard mutation route remains unauthenticated. State gating and immutable history limit effects, but identity/authorization is not claimed. See AR-18-01. | closed (accepted) |
| T-18-06-SC | 18-06 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-24 | 18-07 | Tampering | `GET /runs` | high | mitigate | Legacy mutating callers were deleted; exact AST inventory and hostile mutation/enqueue/reply/scheduling spies prove the route is read-only. | closed |
| T-18-25 | 18-07 | Spoofing | Supported resume paths | high | mitigate | Sender, consumed-reply, late-reply, operator-map, roster, epoch, and manual-retrigger safeguards remain covered after sweep deletion. | closed |
| T-18-26 | 18-07 | Repudiation | Hidden compatibility caller | medium | mitigate | Supported entry-point inventory and production-source negative scans prove no hidden sweep caller remains. | closed |
| T-18-07-SC | 18-07 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-21 | 18-08 | Tampering | Duplicate recovery APIs | high | mitigate | Caller-first deletion removed definitions, exports, routes, facade methods, SQL, templates, and raw source references for both legacy sweep APIs. | closed |
| T-18-22 | 18-08 | Tampering | Permissive fakes | high | mitigate | Legacy fake mirrors were removed; strict stateful replacements and positive/negative production-fake pairing remain enforced. | closed |
| T-18-23 | 18-08 | Spoofing | Reply/operator safeguards | high | mitigate | Narrow subtraction preserves sender/consumed checks, immutable operator authority, roster validation, epoch isolation, and Retrigger tests. | closed |
| T-18-08-SC | 18-08 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-08 | 18-09 | Tampering | Operator resume handler | high | mitigate | Exact unresolved-name key set, run scoping, roster membership, bounded invalid-context result, and no `alias_candidates` authority. | closed |
| T-18-09 | 18-09 | Tampering | Resume reclaim | high | mitigate | Reclaimed attempts rewind through the authoritative RECEIVED CAS without advancing `reply_epoch`; explicit-result regressions pass. | closed |
| T-18-10 | 18-09 | Information Disclosure | Handler diagnostics | high | mitigate | Invalid context produces bounded codes and identifier-free logs; hostile token/name/UUID absence tests pass. | closed |
| T-18-11 | 18-09 | Tampering | Fake fallthrough | high | mitigate | Reflection/AST pairing and strict fake methods cover every public persisted-context, resolution, settlement, retry, and reaper seam. | closed |
| T-18-09-SC | 18-09 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-27 | 18-10 | Denial of Service | Producer cutover | high | mitigate | Both orchestration entry points now return bounded results on every path only after consumers were installed; exhaustive producer tests pass. | closed |
| T-18-28 | 18-10 | Tampering | Active caller result handling | high | mitigate | Non-vacuous AST call inventory and RETRYABLE/TERMINAL behavior matrices prove active callers consume results rather than discard them. | closed |
| T-18-29 | 18-10 | Information Disclosure | Classified diagnostics | high | mitigate | Stage/reason-only classification and hostile exception-text absence coverage prevent raw provider/DB details from being retained. | closed |
| T-18-10-SC | 18-10 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-30 | 18-11 | Denial of Service | Compatibility result sink | high | mitigate | `PipelineResult`-only annotations, strict runtime validation, exhaustive behavior tests, and positive AST inventory remove `None`-as-success. | closed |
| T-18-31 | 18-11 | Tampering | Handler/dispatch forwarding | high | mitigate | Dynamic dispatch validates exact results; handlers return bounded values; repo-wide strict mypy and hostile mutation guards pass. | closed |
| T-18-11-SC | 18-11 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-32 | 18-12 | Tampering | Live schema drift | high | mitigate | Exact parent/child/job-column, index, constraint, type, and reference-target catalog inventory with malformed-object negative tests. | closed |
| T-18-33 | 18-12 | Denial of Service | Handler persistence dependency | high | mitigate | Schema-health contract covers every typed persistence object required by resume handlers before deployment is considered healthy. | closed |
| T-18-12-SC | 18-12 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-34 | 18-13 | Denial of Service | Oldest final-attempt lease | high | mitigate | Every canonical run status dead-letters the selected transport row; all-status and second-candidate tests prove starvation-free progress. | closed |
| T-18-35 | 18-13 | Tampering | Run status during reap | high | mitigate | Associated run is locked; disjoint exhaustive status sets CAS only active crash states and preserve completed/human-wait/rejected/error states. | closed |
| T-18-36 | 18-13 | Repudiation | Final lease diagnostics | medium | mitigate | Prior `jobs.last_error` is preserved and only bounded final-expiry detail is written on active-state error transitions. | closed |
| T-18-13-SC | 18-13 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |
| T-18-37 | 18-14 | Tampering | `RESUME_REPLY` ownership | high | mitigate | Canonical non-null persisted row owner must equal `job.run_id` before conversion, reclaim, or orchestration; same-business and cross-business counterexamples pass. | closed |
| T-18-38 | 18-14 | Information Disclosure | Invalid-context logging | high | mitigate | Static event plus bounded reason code only; hostile UUID/body/name/address absence assertions pass. | closed |
| T-18-39 | 18-14 | Repudiation | Skipped handler regressions | high | mitigate | Module-wide DB skip was removed; tests run with `DATABASE_URL` absent or stubbed and require explicit `PipelineOutcome.OK`. | closed |
| T-18-14-SC | 18-14 | Tampering (supply chain) | Package installs | low | accept | Plan added no dependency. | closed (accepted) |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above `workflow.security_block_on` (`high`) count toward `threats_open`.*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party).*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-18-01 | T-18-20 (18-06) | The existing portfolio/demo dashboard has no operator authentication, so an unauthenticated caller who can reach the mutation route could retrigger an eligible ERROR run. Phase 18 did not add a public mutation surface and preserves ERROR-state gating, fresh job generations, and immutable dead history, but those controls do not establish caller identity. This is explicitly accepted rather than misrepresented as mitigated; production deployment requires operator authentication/authorization as separate hardening. | User, `$gsd-secure-phase 18` checkpoint choice 1 | 2026-07-16 |
| AR-18-02 | T-18-01-SC through T-18-14-SC | None of the 14 plans added a package or dependency. The per-plan supply-chain rows are accepted as not-applicable exposure, with `pyproject.toml` plus the committed `uv.lock` remaining the dependency source of truth. | User, `$gsd-secure-phase 18` checkpoint choice 1 | 2026-07-16 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-16 | 57 | 57 | 0 | `$gsd-secure-phase 18` (orchestrator, ASVS L1; user accepted the 15 planned open accept rows) |

Verification method: L1 grep-depth classification against all 14 PLAN/SUMMARY
pairs, current phase-owned source and tests, and the authoritative passed
`18-VERIFICATION.md` (9/9 must-haves, 0 behavior-unverified). Forty-two
`mitigate` rows have implementation/test evidence. Fifteen `accept` rows are
documented above: 14 no-dependency supply-chain rows and the existing
unauthenticated Retrigger risk. No threat remains open at or above the `high`
block threshold, and no lower-severity row remains undocumented.

The reset-enabled live Postgres proof was unavailable during final phase
verification because `DATABASE_URL` and `ALLOW_DB_RESET=1` were absent. Its 17
selected tests were skipped and are not counted as passing evidence; equivalent
state transitions, ordering, rejection, and starvation behavior are covered by
always-run stateful tests, as adjudicated in `18-VERIFICATION.md`.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-16
