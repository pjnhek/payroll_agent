---
phase: 6
slug: real-integration-ship
status: draft
nyquist_compliant: false
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

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -m "not integration and not live_llm"` (full mocked suite, no live deps)
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
| OPS-02 / D-17 | Forged inbound POST (bad/absent `svix-signature`) → `resend.Webhooks.verify` raises `ValueError` → route returns HTTP 400, pipeline NOT entered | Spoofed inbound payroll email (Spoofing) | Signature verify is step zero on `raw_body = await request.body()`; reject before any extraction | unit (mock `resend.Webhooks.verify` raising) | `uv run pytest tests/test_gateway.py -k "verify or signature" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-13 | Duplicate delivery (same RFC `message_id`) → second webhook returns 200 but `decide.py`/pipeline runs exactly ONCE | Duplicate-delivery false-process (Integrity) | Dedup on `email_messages.uq_message_id` via `ON CONFLICT DO NOTHING` BEFORE pipeline; re-run skipped | unit/integration (insert-or-skip) | `uv run pytest tests/test_ingest.py -k "dedup or duplicate" -x -q` | ✅ extend (existing dedup via UNIQUE) | ⬜ pending |
| OPS-02 / D-13 | Dedup keys on the RFC `message_id` from the full fetch, NOT the Resend internal `email_id` | Wrong-key dedup miss (Integrity) | Dedup uses the normalized `InboundEmail.message_id` (RFC), set from the fetched headers | unit | `uv run pytest tests/test_gateway.py -k "message_id" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-01a / D-18 | Two-step parse: metadata-only `email.received` webhook → `resend.EmailsReceiving.get(email_id)` fetch → normalized `InboundEmail` (typed `message_id`/`in_reply_to`/`references_header`/`body_text`) | Provider blob leak past seam (Tampering) | `parse_inbound` owns BOTH steps + lowercases `ReceivedEmail.headers` before extracting `in-reply-to`/`references`; no raw provider dict downstream | unit (mock `resend.EmailsReceiving.get`) | `uv run pytest tests/test_gateway.py -k "two_step or parse_inbound" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 / D-14 / D-13c | Outbound send rebuilds `In-Reply-To`/`References` from the PERSISTED thread row (not the last webhook); `send_state='reserved'` row written BEFORE the `resend.Emails.send` call, flipped to `sent`/`failed` after | Threading corruption on dropped/dup delivery (Integrity); send-without-record (Repudiation) | Durable threading from DB state; crash-safe intent-before-side-effect | unit (mock `resend.Emails.send` + FakeConnection) | `uv run pytest tests/test_gateway.py -k "threading or references or reserved" -x -q` | ❌ W0 | ⬜ pending |
| OPS-02 | No-op-swap invariant: full existing suite stays green after the real gateway lands; fixture path unchanged | Regression hidden by integration (Integrity) | Real provider isolated to `gateway.py`; every caller + fixture path untouched | full suite | `uv run pytest -q` | ✅ existing suite | ⬜ pending |
| OPS-01 / D-20 | Liveness route returns 200 with NO DB hit (Render deploy health check must not fail on a Supabase blip) | DoS via health-check flap (Availability) | Liveness is pure; DB dependency isolated to readiness | unit | `uv run pytest tests/test_dashboard.py -k "live or health" -x -q` | ❌ W0 | ⬜ pending |
| OPS-01 / D-16 / D-20 | Readiness/keep-alive route runs a real `SELECT` and returns 200 when the pool is up | Silent DB-down served as healthy (Availability) | Readiness proves the DB path; the keep-alive cron's target | integration | `uv run pytest tests/test_dashboard.py -k "ready or keepalive" -m integration -x` | ❌ W0 | ⬜ pending |
| OPS-03 | Keep-alive workflow targets the readiness route (runs a `SELECT`) and includes `workflow_dispatch:` for manual re-enable | Stale keep-alive → Supabase pause (Availability) | Cron hits the DB-touching route (warms Render + un-pauses Supabase in one ping); manual re-trigger documented | manual (YAML inspection) | inspect `.github/workflows/keepalive.yml` | ❌ W0 | ⬜ pending |
| OPS-04 / CALC-04/05 | README contains the locked disclaimer verbatim (educational/not-tax-compliant; OBBBA exclusion; Additional Medicare 0.9% over $200k YTD unmodeled) | Misrepresentation as tax-compliant (Repudiation) | Disclaimer prominent near top per D-11; copied verbatim from CLAUDE.md §5 / REQUIREMENTS.md CALC-04/05 | unit (grep/assert) | `uv run pytest tests/test_readme.py -x -q` OR `grep` check | ❌ W0 (optional) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Highest-Risk Units (priority test targets)

1. **Inbound dedup before pipeline (D-13) — THE highest-value fix.** A duplicate at-least-once delivery that re-runs `decide.py` is exactly the false-process the thesis forbids, and it is invisible in the stub world. Test: two webhook deliveries with the same RFC `message_id` → the pipeline/`decide.py` is invoked once; the second is an insert-or-skip no-op. Must key on the RFC `message_id` from the full fetch, NOT the Resend `email_id`.
2. **Signature reject (D-17).** A forged POST to the public money-themed webhook must be refused at step zero. Test: mock `resend.Webhooks.verify` to raise `ValueError` → assert HTTP 400 and that NO extraction/pipeline code ran. Guard the `Request` raw-body refactor — a Pydantic-typed body would consume the stream and silently break verify.
3. **Durable threading from persisted state (D-14).** Building outbound headers off "the last webhook I saw" lets a dropped/duplicated delivery corrupt threading. Test: with a persisted References chain row, `send_outbound` rebuilds `In-Reply-To`/`References` from the DB row, and the `send_state='reserved'`-before-send ordering holds (intent row exists before the mocked `resend.Emails.send`).
4. **Two-step parse + header normalization (D-01a/D-18).** The single biggest hidden shape difference from the stub. Test: metadata-only webhook + mocked `resend.EmailsReceiving.get` → a fully-populated normalized `InboundEmail`; assert headers are read case-insensitively (⚠ A1 — real sender casing only provable at D-09b).
5. **No-op-swap invariant.** The 422-test mocked suite green after the gateway swap is the structural proof that the provider wiring touched only `gateway.py`.

---

## Wave 0 Requirements

- [ ] `uv add resend==2.32.2` — adds the only new runtime package (official resendlabs org; self-contained `Webhooks.verify`, no `svix` dep)
- [ ] `tests/test_gateway.py` — two-step parse (mock `resend.EmailsReceiving.get`), signature-reject (mock `resend.Webhooks.verify` → `ValueError` → HTTP 400), durable-threading rebuild + `reserved`-before-send ordering, RFC-`message_id`-not-`email_id` dedup key, case-insensitive header normalization
- [ ] `tests/test_ingest.py` — **EXTEND** with explicit duplicate-delivery dedup (pipeline runs once on repeat `message_id`)
- [ ] `tests/test_dashboard.py` — **EXTEND** with liveness (no DB, always 200) and readiness (DB `SELECT`, `integration`) health-route tests
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
| Real email round-trip: send → reply → **three threading headers intact** against the deployed service | OPS-02 / D-09b | The one assumption fixtures cannot test — real sender-client header survival (Outlook/Exchange mangle `References`) | Human does a personal send→reply→approve round-trip on the deployed URL; LOG the raw `email_obj.headers` dict (⚠ A1) and the raw webhook payload (⚠ A6 — is `data.message_id` the RFC Message-ID?); confirm outbound Message-ID is settable/exposed (⚠ A5) |
| Demo-reset re-arms beat 2: clearing learned aliases + run rows makes a second take clarify again | OPS-04 / D-07 | Cross-run/cross-take state; the learned alias persists to prod and poisons a repeat take | Run the reset (purge runs + `uv run python -m app.db.seed` to reset `employees.known_aliases` via `ON CONFLICT DO UPDATE`); re-run the shorthand fixture → confirm it clarifies again |
| Architecture diagram renders in GitHub README (Mermaid source + committed SVG **and** PNG) | OPS-04 / D-11a | GitHub Mermaid/SVG render fidelity is visual; SVG embedding is inconsistent | View the README on GitHub; confirm the Mermaid block renders AND the committed PNG fallback displays; diagram shows pipeline stages + two pause states + the `decide.py` code gate |
| 60–90s demo recording exists and shows all three beats + the eval closing shot | OPS-04 / D-04 / D-06 | The hero artifact; recorded off the deterministic `/demo/send-test` button | Confirm the recording: (1) clean→approve→deliver, (2) unknown shorthand clarifies + suggestion names the employee, (3) approve→learned→re-run resolves without clarifying, + ~5–10s eval view (`false_process_count=0`) |
| Eval chart served as a committed STATIC asset (not a runtime regen on the ephemeral FS) | OPS-04 / D-21 | Ephemeral FS; a regen would 500 on the dyno | On the deployed service, hit `/eval/chart.svg`; confirm it serves the committed `eval/chart.svg` baked into the image |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`tests/test_gateway.py`, health-route tests, `resend` package)
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
