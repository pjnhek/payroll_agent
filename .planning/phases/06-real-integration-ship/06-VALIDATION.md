---
phase: 6
slug: real-integration-ship
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-23
---

# Phase 6 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `06-RESEARCH.md` → Validation Architecture + Security Domain.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (dev dep in `pyproject.toml`) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` |
| **Quick run command** | `uv run pytest -q -m "not integration and not live_llm"` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~15–30 seconds (mocked suite); integration adds live-DB time |

**Markers:** `integration` (requires live local DB), `live_llm` (requires real API keys — never run in CI/gates). Resend, Render, and live-DB round-trip behaviors are mocked at the `gateway.py` seam — no `live_resend` marker needed because the real provider is exercised only at the BLOCKING human gate (D-09b), not in the suite.

**No-op-swap invariant:** the existing mocked suite (422 tests as of Phase 5) MUST stay green throughout Phase 6 — it is the guard that wiring Resend behind the gateway did not change pipeline behavior.

**MEDIUM-5 xfail protocol:** Wave-0 gateway tests targeting not-yet-implemented behavior are marked `@pytest.mark.xfail(strict=True, reason="implemented in 06-04")`. This keeps the mocked suite exit code 0 between waves. When 06-04 implements the real gateway, each test becomes XPASS (strict=True → suite exits non-zero); 06-04 removes the xfail markers. The suite must have 0 FAILED and 0 XFAIL after 06-04 completes.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -m "not integration and not live_llm"` (full mocked suite, no live deps) — must exit 0
- **After every plan wave:** Run `uv run pytest -q -m "not live_llm"` (includes integration tests against live local DB)
- **Before `/gsd-verify-work`:** Full suite green (`uv run pytest -q`)
- **Max feedback latency:** ~30 seconds (mocked suite)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner. This map is keyed by requirement/decision + target test file
> so each plan task can cite the row it satisfies. Threat refs map to `06-RESEARCH.md` → Security Domain.
> The three Resend SDK call sites (`resend.Webhooks.verify`, `resend.EmailsReceiving.get`,
> `resend.Emails.send`) are mocked at module level in `tests/test_gateway.py` — no live network.

| Requirement | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| OPS-02 / D-17 | Forged inbound POST (bad/absent `svix-signature`) → `resend.Webhooks.verify` raises `ValueError` → route returns HTTP 400, pipeline NOT entered | Spoofed inbound payroll email (Spoofing) | Signature verify is step zero on `raw_body = await request.body()` for Resend-shaped payloads; reject before any extraction | unit (mock `resend.Webhooks.verify` raising) — xfail(strict=True) in 06-01, xfail removed in 06-04 | `uv run pytest tests/test_gateway.py -k "verify or signature" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-17 / HIGH-2 | Canonical fixture POST (InboundEmail JSON, no svix headers) succeeds without signature verify — fixture/dev path intact | Fixture path regression (Integrity) | parse_inbound dual-path: Resend-envelope → verify+two-step; canonical shape → passthrough, no verify | unit (no xfail — GREEN immediately from 06-01) | `uv run pytest tests/test_gateway.py -k "canonical_fixture" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-17 / BLOCKER-2 | With ALLOW_UNSIGNED_FIXTURES unset/False (prod default), a Resend-envelope payload WITHOUT svix-* headers → route returns 400 — prod default path verified by automated test | Unsigned Resend payload passes in prod (Spoofing) | allow_unsigned_fixtures=False default in Settings (06-02 Task 2); route returns 400 for unsigned Resend-envelope payloads in prod; ALLOW_UNSIGNED_FIXTURES absent from render.yaml value: entries | unit (no xfail — GREEN from 06-04 Task 2) | `uv run pytest tests/test_gateway.py -k "allow_unsigned_fixtures_prod_default" -x -q` AND `grep -q "ALLOW_UNSIGNED_FIXTURES" render.yaml && exit 1 \|\| true` | ❌ W3 | ⬜ pending |
| OPS-02 / D-13 | Duplicate delivery (same RFC `message_id`) → second webhook returns 200 but `decide.py`/pipeline runs exactly ONCE; enqueue ONLY on inserted row (explicit ON CONFLICT DO NOTHING RETURNING id) | Duplicate-delivery false-process (Integrity) | Atomic insert-or-skip; background task enqueued ONLY if row returned (HIGH-4 explicit dedup) | unit (mocked: `test_duplicate_delivery_pipeline_runs_once_unit`, no live DB) + integration (`test_duplicate_delivery_pipeline_runs_once`, `@pytest.mark.integration`) | `uv run pytest tests/test_ingest.py -k "dedup or duplicate" -x -q` (unit runs without integration marker) | ✅ extend (existing dedup via UNIQUE) | ⬜ pending |
| OPS-02 / D-13 | Dedup keys on the RFC `message_id` from the full fetch, NOT the Resend internal `email_id` | Wrong-key dedup miss (Integrity) | Dedup uses the normalized `InboundEmail.message_id` (RFC), set from the fetched headers | unit — xfail(strict=True) in 06-01, xfail removed in 06-04 | `uv run pytest tests/test_gateway.py -k "message_id" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-01a / D-18 | Two-step parse: metadata-only `email.received` webhook → `resend.EmailsReceiving.get(email_id)` fetch → normalized `InboundEmail` (typed `message_id`/`in_reply_to`/`references_header`/`body_text`) | Provider blob leak past seam (Tampering) | `parse_inbound` owns BOTH steps + lowercases `ReceivedEmail.headers` before extracting `in-reply-to`/`references`; no raw provider dict downstream | unit (mock `resend.EmailsReceiving.get`) — xfail(strict=True) in 06-01, xfail removed in 06-04 | `uv run pytest tests/test_gateway.py -k "two_step or parse_inbound" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-14 / D-13c / BLOCKER-3 | Outbound send calls `repo.get_outbound_references_chain(run_id)` to LOAD the prior accumulated References chain from DB rows, appends the new `in_reply_to` token to build the full chain, THEN writes `send_state='reserved'` row BEFORE `resend.Emails.send` call; the flip-to-sent UPDATE uses the SYNTHETIC message_id as WHERE key (not the Resend provider id) | Threading corruption on dropped/dup delivery (Integrity); send-without-record (Repudiation); WHERE-key ambiguity (Integrity) | Durable threading from DB state — FakeConnection pre-populated with prior outbound row; test_send_outbound_reserved_before_sent_ordering asserts accumulated chain + asserts fake_conn.executed[1] WHERE param is the SYNTHETIC message_id not the provider id (BLOCKER-3) | unit (mock `resend.Emails.send` + FakeConnection) — xfail(strict=True) in 06-01, xfail removed in 06-04 | `uv run pytest tests/test_gateway.py -k "threading or references or reserved" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / HIGH-3 | send_outbound on provider exception flips reserved row to send_state='failed' and re-raises; run reaches ERROR and is retriggerable (not stranded in 'reserved') | Stranded runs (Repudiation/Availability) | try/except around resend.Emails.send; on exception call repo.update_email_message_state(message_id, "failed"); re-raise | unit (mock resend.Emails.send raising + FakeConnection) — xfail(strict=True) in 06-01, xfail removed in 06-04 | `uv run pytest tests/test_gateway.py -k "failed_on_exception" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-14 / MEDIUM-7 | An inbound reply whose In-Reply-To/References points at a prior outbound chain resumes the CORRECT run via existing reply-routing code — not just chain-construction, but actual run-match | Routing miss silently opens a new run (Integrity) | test_inbound_reply_routes_to_correct_run: FakeConnection returns run_A for header match; POST canonical reply; assert BackgroundTasks.add_task called with run_A's run_id | unit (FakeConnection + monkeypatched repo.find_awaiting_reply_for_header) — xfail(strict=True) in 06-01, xfail removed in 06-04 | `uv run pytest tests/test_gateway.py -k "reply_routes" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 | No-op-swap invariant: full existing suite stays green after the real gateway lands; fixture path unchanged | Regression hidden by integration (Integrity) | Real provider isolated to `gateway.py`; every caller + fixture path untouched | full suite | `uv run pytest -q` | ✅ existing suite | ⬜ pending |
| OPS-01 / D-20 | Liveness route returns 200 with NO DB hit (Render deploy health check must not fail on a Supabase blip) | DoS via health-check flap (Availability) | Liveness is pure; DB dependency isolated to readiness | unit — xfail(strict=True) in 06-01 (reason: "implemented in 06-02"), xfail removed in 06-02 | `uv run pytest tests/test_dashboard.py -k "live or health" -x -q` | ❌ W0 | ⬜ pending |
| OPS-01 / D-16 / D-20 | Readiness/keep-alive route runs a real `SELECT` and returns 200 when the pool is up | Silent DB-down served as healthy (Availability) | Readiness proves the DB path; the keep-alive cron's target | integration — xfail(strict=True) in 06-01 (reason: "implemented in 06-02"), xfail removed in 06-02 | `uv run pytest tests/test_dashboard.py -k "ready or keepalive" -m integration -x` | ❌ W0 | ⬜ pending |
| OPS-03 | Keep-alive workflow targets the readiness route (runs a `SELECT`) and includes `workflow_dispatch:` for manual re-enable | Stale keep-alive → Supabase pause (Availability) | Cron hits the DB-touching route (warms Render + un-pauses Supabase in one ping); manual re-trigger documented | manual (YAML inspection) | inspect `.github/workflows/keepalive.yml` | ❌ W0 | ⬜ pending |
| OPS-04 / CALC-04/05 | README contains the locked disclaimer verbatim (educational/not-tax-compliant; OBBBA exclusion; Additional Medicare 0.9% over $200k YTD unmodeled) | Misrepresentation as tax-compliant (Repudiation) | Disclaimer prominent near top per D-11; copied verbatim from CLAUDE.md §5 / REQUIREMENTS.md CALC-04/05 | unit (grep/assert) | `uv run pytest tests/test_readme.py -x -q` OR `grep` check | ❌ W0 (optional) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Highest-Risk Units (priority test targets)

1. **Inbound dedup before pipeline (D-13) — THE highest-value fix.** A duplicate at-least-once delivery that re-runs `decide.py` is exactly the false-process the thesis forbids, and it is invisible in the stub world. Test: two webhook deliveries with the same RFC `message_id` → the pipeline/`decide.py` is invoked once; the second is an insert-or-skip no-op. HIGH-4 makes this EXPLICIT in the route: enqueue only if the ON CONFLICT insert returned a row.
2. **Signature reject (D-17).** A forged POST to the public money-themed webhook must be refused at step zero. Test: mock `resend.Webhooks.verify` to raise `ValueError` → assert HTTP 400 and that NO extraction/pipeline code ran. HIGH-2 dual-path: verify only fires for Resend-envelope payloads; canonical fixture POSTs are not verified.
3. **Fixture/dev path survival (HIGH-2).** A canonical InboundEmail JSON POST with no svix headers must succeed throughout Phase 6. test_parse_inbound_canonical_fixture_still_works must be GREEN from 06-01 onward (no xfail; GREEN immediately).
4. **Send-failure routing (HIGH-3).** A provider exception in send_outbound must flip the reserved row to 'failed' and re-raise. Runs must be retriggerable. test_send_outbound_failed_on_provider_exception asserts this.
5. **D-14 reply-routing end-to-end (MEDIUM-7).** Not just chain-construction — an inbound reply with matching In-Reply-To resumes the CORRECT run. test_inbound_reply_routes_to_correct_run asserts the BackgroundTasks.add_task call with the matched run_id.
6. **Durable threading from persisted state (D-14).** Building outbound headers off "the last webhook I saw" lets a dropped/duplicated delivery corrupt threading. Test: with a persisted References chain row, `send_outbound` rebuilds `In-Reply-To`/`References` from the DB row.
7. **No-op-swap invariant.** The 422-test mocked suite green after the gateway swap is the structural proof that the provider wiring touched only `gateway.py`.

---

## Wave 0 Requirements

- [ ] `uv add resend==2.32.2` — adds the only new runtime package (official resendlabs org; self-contained `Webhooks.verify`, no `svix` dep)
- [ ] `tests/test_gateway.py` — all Phase-6-behavior tests marked `@pytest.mark.xfail(strict=True, reason="implemented in 06-04")` EXCEPT `test_parse_inbound_canonical_fixture_still_works` (which must be GREEN immediately with no xfail). Xfail tests: two-step parse, signature-reject, threading/reserved, failed-on-exception, reply-routing-e2e.
- [ ] `tests/test_gateway.py` NEW (no xfail): `test_parse_inbound_canonical_fixture_still_works` — canonical InboundEmail dict passes parse_inbound in the current stub gateway. GREEN from Wave 0.
- [ ] `tests/test_ingest.py` — **EXTEND** with TWO dedup tests: `test_duplicate_delivery_pipeline_runs_once_unit` (mocked, no integration marker, runs in default `uv run pytest -q -m "not integration and not live_llm"`) + `test_duplicate_delivery_pipeline_runs_once` (`@pytest.mark.integration`, live DB). Neither needs xfail.
- [ ] `tests/test_dashboard.py` — **EXTEND** with liveness (xfail reason: "implemented in 06-02") and readiness (xfail, integration) health-route tests
- [ ] `tests/test_readme.py` *(optional)* — assert the locked disclaimer strings are present verbatim in README.md
- [ ] `tests/conftest.py` — extend shared fixtures (mock Resend SDK seams; a received-email fixture with realistic mixed-case headers)

---

## Manual-Only Verifications

> These are the behaviors fixtures structurally cannot test — the BLOCKING human checkpoints (D-09, D-09b)
> and the recording. They retire the ⚠ CONFIRM assumptions (A1, A4, A5, A6) from `06-RESEARCH.md`.

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Thin Render deploy serves dashboard + liveness route, binds `0.0.0.0:$PORT`, reaches Supabase via the pooler, survives a cold-start wake | OPS-01 / D-08 / D-09 | Live Render account creation + secret injection need a human; cold-start is real-infra behavior | Human executes the credentialed deploy from prepared artifacts; confirm the service serves, reaches Supabase, and wakes from spin-down |
| Local pooler pre-check: connect from laptop over 6543 (prepared statements off) and apply `schema.sql` + seed over the 5432 session pooler | OPS-01 / D-08a / D-15 | Isolates the IPv4/pooler/prepared-statement failure class from the container/`$PORT`/cold-start class; needs live Supabase creds | Run the prepared connection + migrate/seed scripts against the fresh project; confirm which port bootstrap needs (⚠ A4) |
| Real email round-trip: send → reply → **three threading headers intact** against the deployed service; LOG_WEBHOOK_DEBUG_IDS flag captures real header key casing for ⚠ A1 | OPS-02 / D-09b / MEDIUM-6 | The one assumption fixtures cannot test — real sender-client header survival (Outlook/Exchange mangle `References`); logging inside parse_inbound (gateway.py) captures header keys before normalization | Human enables LOG_WEBHOOK_DEBUG_IDS=true in Render env, does personal send→reply→approve round-trip; reads WEBHOOK_DEBUG log for header_keys=[...] (⚠ A1); confirms email_id vs rfc_message_id (⚠ A6); confirms outbound provider_id (⚠ A5) |
| Demo-reset re-arms beat 2: clearing learned aliases + run rows makes a second take clarify again | OPS-04 / D-07 / MEDIUM-8 | Cross-run/cross-take state; the learned alias persists to prod and poisons a repeat take | Run `uv run python scripts/demo_reset.py --confirm` (explicit flag required); re-run the shorthand fixture → confirm it clarifies again |
| Architecture diagram renders in GitHub README (Mermaid source + committed SVG **and** PNG — D-11a mandatory; Mermaid-only NOT sufficient) | OPS-04 / D-11a / MEDIUM-LOW-9 | GitHub Mermaid/SVG render fidelity is visual; SVG embedding is inconsistent | View the README on GitHub; confirm the Mermaid block renders AND the committed PNG (docs/architecture.png) displays as a fallback; diagram shows pipeline stages + two pause states + the `decide.py` code gate |
| 60–90s demo recording exists and shows all three beats + the eval closing shot | OPS-04 / D-04 / D-06 | The hero artifact; recorded off the deterministic `/demo/send-test` button | Confirm the recording: (1) clean→approve→deliver, (2) unknown shorthand clarifies + suggestion names the employee, (3) approve→learned→re-run resolves without clarifying, + ~5–10s eval view (`false_process_count=0`) |
| Eval chart served as a committed STATIC asset (not a runtime regen on the ephemeral FS) | OPS-04 / D-21 | Ephemeral FS; a regen would 500 on the dyno | On the deployed service, hit `/eval/chart.svg`; confirm it serves the committed `eval/chart.svg` baked into the image |

---
