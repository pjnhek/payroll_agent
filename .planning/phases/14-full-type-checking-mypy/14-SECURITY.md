---
phase: 14
slug: 14-full-type-checking-mypy
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
threats_found: 21
threats_closed: 21
asvs_level: 1
block_on: high
created: 2026-07-10
---

# Phase 14 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Phase 14 is behavior-neutral strict mypy adoption. All mitigations verified against
> CURRENT source (post review-fix commits 9a2c210, 3305888, 7f59de3, ef732d4, 3aa0539,
> a033764) — not against SUMMARY claims alone.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| CI/dev-machine → PyPI | `uv add --dev mypy` supply chain (14-01) | dev tooling packages |
| Inbound webhook → gateway.py | Untrusted email payload crosses `verify()`/`parse_inbound()`/`_parse_resend_envelope()` | attacker-controlled email content |
| psycopg / JSONB boundary | Raw DB row dicts cross into typed repo returns | run/roster/payroll state |
| LLM JSON boundary | Raw LLM output into Pydantic-validated contracts | extraction/suggestion payloads |
| Money-path computation | calculate.py / decide.py / federal_withholding.py annotation edits | payroll amounts, decisions |
| Operator gate (runs.py) | The single human money-approval gate; CAS claim semantics | approval actions |
| CI workflow file | ci.yml edits affect security posture of every future push | workflow config, action pins |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-14-01 | Tampering | `uv add --dev mypy` supply chain | low | mitigate | mypy dev-group-only (`pyproject.toml:22-29`); Docker excludes dev deps (`Dockerfile:33,37` — `uv sync --frozen --no-dev`); legitimacy audit at `14-RESEARCH.md:91-97` (13-yr-old official python/mypy, Approved) | closed |
| T-14-02 | Tampering | gateway.py Protocol+cast at `resend.EmailsReceiving.get(...)` | medium | mitigate | `_ReceivedEmailLike` Protocol declares exactly `headers`/`message_id`/`text` (`app/email/gateway.py:58-63`); `cast(_ReceivedEmailLike, ...)` at `:162` with ResponseDict rationale comment (`:160-161`); no cast-to-Any; seam survived review-fix ef732d4 intact; full suite incl. test_gateway green (616 passed / 50 skipped, live re-run 2026-07-10) | closed |
| T-14-03 | Repudiation | eval/run_eval.py `--record` import fix | low | accept | Manual/local-only path; regression test present (`tests/test_eval_wiring.py:168`); module-object import landed (`eval/run_eval.py:803`) — see Accepted Risks AR-01 | closed |
| T-14-04 | Tampering | Annotation-only edits to app/db/repo/ | high | mitigate | Full hermetic suite re-run by auditor with live env vars stripped: 616 passed / 50 skipped, matching declared baseline; `uv run mypy` Success 114 files; repo facade unchanged (14-02 SUMMARY measured no reexport errors) | closed |
| T-14-05 | Info Disclosure | `dict[str, Any]` at psycopg/JSONB boundary | low | accept | D-10-sanctioned dynamic edge; e.g. `app/db/repo/runs.py:262` `-> dict[str, Any] \| None` — see Accepted Risks AR-02 | closed |
| T-14-06 | Tampering | calculate.py / decide.py annotation edits | high | mitigate | Whole-phase git diff (4111955..HEAD) traced: calculate.py = typing import + `cast(...)` (runtime no-op) + `dict` → `dict[str, object]` params; decide.py = uuid import + bare `dict`/`set` → typed generics. Zero logic/branch/rounding changes. Money-path tests green in live suite run | closed |
| T-14-07 | Tampering | delivery.py `exc.payroll_roster` D-09 ignore | medium | mitigate | Exactly one `# type: ignore[attr-defined]` in all of app/ (`app/pipeline/delivery.py:232`) with WR-04 reason text; `except Exception as exc:` (`:226`) + `contextlib.suppress(Exception)` (`:231`) structure unchanged; downstream `getattr(exc, "payroll_roster", None)` read intact (`app/routes/runs.py:134`) | closed |
| T-14-08 | Info Disclosure | orchestrator.py LLM-facing signature annotations | low | accept | Annotations change type-checker understanding, not data flow — see Accepted Risks AR-03 | closed |
| T-14-09a | Tampering | gateway.py residual annotation edits (verify/parse/send seams) | medium | mitigate | Phase diff of gateway.py removed lines = signature annotations + typed-literal restructure only; `verify()` svix HMAC seam unchanged (`app/email/gateway.py:85-104`); ef732d4's SendParams rework produces identical send keys/headers/attachments (`:274-297`); test_gateway green in live suite run | closed |
| T-14-09 | Tampering | runs.py operator-gate route annotations | high | mitigate | Operator-gate suite (test_hitl, test_needs_operator, test_claim_status, test_gate, test_retrigger_epoch) included in auditor's live 616-passed run; 14-04 diff annotation-only; no ignore added at the getattr site | closed |
| T-14-10 | Elevation of Privilege | webhook.py reply-routing annotations | low | accept | FIX-5 sender revalidation intact: `reply_sender_ok` defined `app/routes/pipeline_glue.py:57`, called `app/routes/webhook.py:245`; test_reply_redelivery green in live run — see Accepted Risks AR-04 | closed |
| T-14-11 | Tampering | eval/run_eval.py scoring annotation | low | accept | Local dev-time tool; `--check` regression gate passed (14-05 SUMMARY) — see Accepted Risks AR-05 | closed |
| T-14-12 | Tampering | scripts/reset_stuck_runs.py annotation | medium | mitigate | Whole-phase git diff = `from typing import Any` + `_counts(c)` → `_counts(c: Any) -> None`; `sys.argv` parsing (`scripts/reset_stuck_runs.py:32`) byte-for-byte untouched; py_compile passed (14-05); script never executed | closed |
| T-14-13 | Tampering | Test-file annotation edits weakening an assertion | medium | mitigate | Per-commit diff scan of all six 14-06/07/08 commits (6b5135b, f82bbf6, 1f0c979, 78acccf, 8eb54f6, 71c5376): zero removed/modified assertion lines. Three assertion modifications found later in range belong to reviewed post-phase fix commits (see Audit Trail note) and preserve/strengthen semantics | closed |
| T-14-14 | Tampering | conftest.py fixture return-type annotation | medium | mitigate | Fixture implementations annotated (`tests/conftest.py:167` `-> FakeConnection`, `:967` `-> InMemoryRepo`; 7 annotated module-level defs); conftest blast radius covered by auditor's live full-suite run matching baseline exactly | closed |
| T-14-15 | Tampering | test_federal_withholding.py money-path test data | high | mitigate | Whole-phase git diff of the file = 2 added / 1 removed lines: `from typing import Any` + `emp_kwargs: dict` → `dict[str, Any]`. Zero removed lines contain any digit — every IRS worked-example value untouched | closed |
| T-14-16 | Repudiation | Bare `uv run mypy` residual cross-module errors | medium | mitigate | 14-09 owned the combined gate; the one residual fix (`explicit_package_bases = true`, `pyproject.toml:68`) individually documented in 14-09 SUMMARY with rationale; auditor re-ran bare `uv run mypy` → `Success: no issues found in 114 source files` | closed |
| T-14-16b | Tampering | Late annotation fixes touching money-path files | medium | mitigate | 14-09's only change was the pyproject config line (no source files); auditor's live hermetic run matches the declared baseline (616/50) | closed |
| T-14-17 | Tampering | ci.yml typecheck job addition | medium | mitigate | `typecheck` job (`ci.yml:60-76`) uses byte-identical pinned SHAs as lint/test (`actions/checkout@34e114876b0b...`, `astral-sh/setup-uv@d4b2f3b6ecc6...`); final step is bare `run: uv run mypy`; no new third-party Action; lint/test/permissions/concurrency blocks unchanged | closed |
| T-14-18 | Elevation of Privilege | Red-proof branch push to origin | low | accept | Phase-12-accepted push-then-delete pattern; `permissions: contents: read` (`ci.yml:4-5`); branch gone locally (`git branch --list` empty) and on origin (`git ls-remote --heads origin red-proof/mypy-14` empty, verified live); red/green run URLs committed in 14-VERIFICATION.md — see Accepted Risks AR-06 | closed |
| T-14-SC | Tampering | npm/pip/cargo installs | high | mitigate | Only 14-01 added a package (mypy, audited `14-RESEARCH.md:91-97`); across 14-10 and all six review-fix commits, only 11b67ec touched pyproject.toml (1-line mypy setting, no dependency change); uv.lock untouched after 14-01; ci.yml adds no new install source | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-14-03 | `--record` path is manual/local-only, never exercised by hermetic CI or production; regression test (`tests/test_eval_wiring.py:168`) closes the gap forward | Plan 14-01 threat model (planner) | 2026-07-10 |
| AR-02 | T-14-05 | `Any` is the D-10-sanctioned type at genuinely dynamic DB-row/JSONB boundaries; narrowing further requires a schema-typed row mapper, out of this behavior-neutral phase's scope | Plan 14-02 threat model (planner) | 2026-07-10 |
| AR-03 | T-14-08 | Annotations do not change what data flows to the LLM — only the type-checker's model of existing flows | Plan 14-03 threat model (planner) | 2026-07-10 |
| AR-04 | T-14-10 | No branching/comparison code touched in reply routing; FIX-5 sender revalidation verified intact in source and by test_reply_redelivery staying green | Plan 14-04 threat model (planner) | 2026-07-10 |
| AR-05 | T-14-11 | Eval harness is a local dev tool; a behavior slip surfaces as a changed eval chart or failing `--check` gate, not a live money-path bug | Plan 14-05 threat model (planner) | 2026-07-10 |
| AR-06 | T-14-18 | Push-then-delete red-proof pattern already accepted in Phase 12 (D-14); workflow token is read-only (`contents: read`); branch deletion verified live on origin | Plan 14-10 threat model (planner), Phase 12 precedent | 2026-07-10 |

*Accepted risks do not resurface in future audit runs.*

---

## Unregistered Threat Flags

None. 14-06 SUMMARY explicitly declares "Threat flags: None"; no other SUMMARY declares a Threat Flags section, and no new attack surface (endpoints, schema, deps beyond audited mypy, CI actions) was introduced by the phase.

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-10 | 21 | 21 (15 mitigated + 6 accepted) | 0 | gsd-security-auditor (Claude, /gsd-secure-phase) |

**Audit method:** ASVS L1 presence verification against current source at HEAD (a033764), plus live command re-runs:
- `uv run mypy --version` → mypy 2.2.0; bare `uv run mypy` → Success: no issues found in 114 source files
- `uv run ruff check .` → All checks passed
- Hermetic suite with live LLM/DB env vars stripped (`env -u DATABASE_URL -u ALLOW_LIVE_LLM -u ALLOW_DB_RESET -u *_API_KEY uv run pytest -q`) → **616 passed, 50 skipped** — exact baseline match
- Whole-phase git diffs (base 4111955) traced for calculate.py, decide.py, gateway.py, delivery.py, reset_stuck_runs.py, test_federal_withholding.py, and per-commit assertion scans of the six test-typing commits

**Observation (informational, not a finding):** the post-phase code-review fix commits modified three test assertion lines outside the T-14-13-scoped plan commits — one in 7f59de3 (WR-03: `load_run` result narrowed with an added `is not None` assertion before the original equality assert, strengthening) and two in 3aa0539 (WR-05: `"extra_body" not in kwargs` → `kwargs.get("extra_body") is None`; `inst.timeout is None` → `inst.timeout is NOT_GIVEN`), which adapt the assertions to the reviewed branch-collapse refactor with equivalent wire-level semantics. Both commits belong to the cross-AI review round that ended verdict READY; the full suite passes at the current baseline.

**Implementation files modified by this audit:** none (SECURITY.md only).

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-10
