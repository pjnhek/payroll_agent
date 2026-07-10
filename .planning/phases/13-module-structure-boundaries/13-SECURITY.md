---
phase: 13
slug: module-structure-boundaries
status: verified
threats_open: 0
asvs_level: 1
created: 2026-07-09
---

# Phase 13 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| Repo facade and aggregate modules | The package split must retain PII scrubbing, parameterized SQL, and valid monkeypatch seams. | Payroll data, roster names, email text |
| Pipeline module split | Alias learning, clarification, delivery, and deterministic decisioning cross new module-object boundaries. | Alias candidates, decisions, payroll data |
| Inbound webhook and reply resume | Signed/unsigned webhook handling, transactional reply classification, and sender revalidation protect untrusted email input. | Raw webhook body, sender identity, message headers |
| Demo routes | One module owns the fixture and business allowlist constants used by demo routes. | Fixture keys, seeded business identities |
| CI module-boundary gate | AST scanning prevents cross-module private-name dependencies that could bypass a patched seam. | Source imports and module attributes |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| 13-01/T-13-01 | Tampering | PII scrub call chain | mitigate | `runs.py` co-locates `_scrub`, `_build_error_detail`, and `record_run_error`; the regression patches the owning module. Evidence: `app/db/repo/runs.py:496-535,538-609`; `tests/test_persistence.py:333-363`. | closed |
| 13-01/T-13-02 | Tampering | Repo facade surface | mitigate | Facade imports and exports the complete live surface, including connection and private compatibility seams. Evidence: `app/db/repo/__init__.py:12-75,77-135`; `tests/test_gateway.py:313-332`. | closed |
| 13-01/T-13-03 | Tampering | Same-module monkeypatch seam | mitigate | Interception tests patch `app.db.repo.runs`, the actual globals used by `record_run_error`. Evidence: `app/db/repo/runs.py:584-609`; `tests/test_gateway.py:221-248`; `tests/test_persistence.py:333-346`. | closed |
| 13-01/T-13-04 | Repudiation | Repo package initialization | mitigate | `_conn_ctx` imports the facade only at call time; `pipeline_state` uses direct `_shared` plumbing rather than a `runs` facade import. Evidence: `app/db/repo/_shared.py:13-34`; `app/db/repo/pipeline_state.py:1-13`. | closed |
| 13-01/T-13-05 | Tampering | SQL injection and whole-repo SQL scans | mitigate | Package-wide dynamic source enumeration preserves the f-string-SQL sweep; the clarification-column test uses the same package-wide approach. Evidence: `tests/test_gateway.py:283-310`; `tests/test_clarify.py:466-485`. | closed |
| 13-01/T-13-06 | Repudiation | Invented cross-aggregate calls | mitigate | `create_run` directly writes `record_only`; the two pipeline-state writers only update their own columns and have no `runs` import. Evidence: `app/db/repo/runs.py:208-243`; `app/db/repo/pipeline_state.py:152-172,260-271`. | closed |
| 13-02/T-13-05 | Tampering | Module-object monkeypatch seams | mitigate | Cross-module pipeline callers use owning module objects (`alias_learning`, `clarification`) and qualified calls. Evidence: `app/pipeline/orchestrator.py:52-61,386-401,451-451,746-746,979-979`; `app/pipeline/delivery.py:18,89,212`. | closed |
| 13-02/T-13-06 | Tampering | Delivery PII error attachment | mitigate | `deliver` attaches the already-loaded roster to the original exception and re-raises; tests cover post-load attachment and pre-load absence. Evidence: `app/pipeline/delivery.py:225-232`; `tests/test_delivery.py:485-550`. | closed |
| 13-02/T-13-07 | Information Disclosure | Alias-learning collision guard | mitigate | A synthetic roster is matched deterministically after candidate insertion; only the intended unique employee may be learned. Evidence: `app/pipeline/alias_learning.py:98-133`; `tests/test_alias_write.py:129-238`. | closed |
| 13-02/T-13-08 | Repudiation | Suggestion-versus-decision firewall | mitigate | The structural regression verifies `decide` precedes `clarification.clarify`, excludes suggestions from the decision call, and prohibits `decide` in `clarification.py`. Evidence: `tests/test_clarify.py:412-450`; `app/pipeline/clarification.py:216-223`. | closed |
| 13-02/T-13-09 | Repudiation | Deferred clarification `Extracted` import | mitigate | `Extracted` is imported at module level and used to validate persisted extracted data before clarification. Evidence: `app/pipeline/clarification.py:16-20,114-121`. | closed |
| 13-02/T-13-10 | Repudiation | Retargeted AST transaction tests | mitigate | AST tests explicitly target the qualified `clarification.clarify` call and co-located `defer_field_regression_clarification`/`clarify` pair. Evidence: `tests/test_atomic_persist.py:232-302,424-492`; `tests/test_clarify_rounds.py:279-413`. | closed |
| 13-02/T-13-11 | Repudiation | Approve-to-delivery integration | mitigate | `approve` invokes `delivery.deliver` within its failure boundary and forwards the attached roster to scrubbed error persistence. Evidence: `app/routes/runs.py:89-131`; `tests/test_hitl.py:164-204`. | closed |
| 13-03/T-13-09 | Tampering | Relocated approve/delivery call | mitigate | The sole approval handler imports the delivery module and calls its public `deliver` function. Evidence: `app/routes/runs.py:20-25,89-131`; `app/main.py:1-16`. | closed |
| 13-03/T-13-10 | Tampering | Webhook Svix verification | mitigate | The inbound route verifies signed raw bytes before parsing and rejects unsigned production requests. Evidence: `app/routes/webhook.py:53-81`; `tests/test_gateway.py:1434-1523`. | closed |
| 13-03/T-13-11 | Tampering | Transactional reply resume | mitigate | The real inbound route calls `finish_reply_resume` after in-transaction classification, while the transaction-less `route_reply` remains confined to the simulated reply path. Evidence: `app/routes/webhook.py:107-115,268-275`; `app/routes/pipeline_glue.py:81-131,134-173`; `app/routes/runs.py:682-790`; `tests/test_webhook.py:121-199`. | closed |
| 13-03/T-13-12 | Spoofing | Reply sender revalidation | mitigate | The first resume, redelivery, and stranded-reply paths all require the shared sender check before scheduling. Evidence: `app/routes/pipeline_glue.py:56-78,98-127`; `app/routes/webhook.py:216-258`; `app/routes/runs.py:462-484`; `tests/test_reply_redelivery.py:346-420`. | closed |
| 13-03/T-13-13 | Repudiation | Demo allowlist constants | mitigate | `demo.py` is the single definition site; other routers import its public constants, and the form default resolves locally. Evidence: `app/routes/demo.py:33-85,210-230`; `app/routes/dashboard.py:15,49-59,130`; `app/routes/runs.py:23-25,497-501`. | closed |
| 13-03/T-13-14 | Tampering | Dead `raising=False` pipeline patches | mitigate | All three affected demo tests patch the live `pipeline_glue.run_pipeline_bg` attribute with default `raising=True`. Evidence: `tests/test_demo_landing.py:810-816,880-884,940-944`. | closed |
| 13-04/T-13-13 | Tampering | Cross-module private-import CI gate | mitigate | The permanent test scans `app`, `eval`, and `scripts` for absolute/relative `ImportFrom` and module-private attribute access. Evidence: `tests/test_bound01_private_imports.py:1-35,155-176,234-367`. | closed |
| 13-04/T-13-14 | Repudiation | Scanner positive and negative coverage | mitigate | A committed synthetic fixture asserts all violation forms and legitimate exemptions, including a level-2 relative import. Evidence: `tests/test_bound01_private_imports.py:370-576`. | closed |
| 13-04/T-13-15 | Repudiation | Narrow facade exemption | mitigate | The exemption is scoped to `app.db.repo`; attribute access exempts packages, not arbitrary submodules, and synthetic cases prove the distinction. Evidence: `tests/test_bound01_private_imports.py:47-74,314-326,429-569`. | closed |
| 13-04/T-13-16 | Repudiation | Relative-import resolver parity | mitigate | Absolute and resolved-relative imports converge on the same `_is_private` check; the synthetic level-2 relative import must be flagged. Evidence: `tests/test_bound01_private_imports.py:100-127,155-176,515-519`. | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

No accepted risks.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-09 | 23 | 23 | 0 | gsd-security-auditor |

### Verification note

- Static implementation and committed-test evidence was inspected for every plan-qualified register item.
- No `## Threat Flags` section is present in the four Phase 13 summaries.
- The mitigation-specific `uv run pytest` invocation could not execute because `uv` is not installed on this runtime's `PATH`; no runtime-pass claim is made by this audit.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-09
