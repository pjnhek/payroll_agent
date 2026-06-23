---
phase: 6
reviewers: [codex]
reviewed_at: 2026-06-23
plans_reviewed: [06-01-PLAN.md, 06-02-PLAN.md, 06-03-PLAN.md, 06-04-PLAN.md, 06-05-PLAN.md, 06-06-PLAN.md, 06-07-PLAN.md]
codex_cli_version: codex-cli 0.135.0
overall_risk: HIGH (as written)
---

# Cross-AI Plan Review — Phase 6

> Requested: Codex review of the 7 Phase-6 plans (post plan-checker pass, post one revision iteration).
> Codex was given PROJECT.md context, the ROADMAP Phase-6 section, OPS-01..04, the full CONTEXT.md
> (locked D-01..D-21), and all 7 PLAN.md files, with instructions to be adversarial about the
> thesis-critical correctness points.

## Codex Review

**Summary**

The plan set is directionally strong and covers the Phase 6 goal: deploy on Render/Supabase, wire Resend behind the email seam, add keep-alive, and produce README/demo artifacts. Codex would NOT approve it as-is. The sequencing and human gates are good, but there are several high-risk implementation holes that could either break the public deploy or, worse, make the real email path fail silently around dedup/threading.

**Strengths**

- Good dependency order: thin deploy before provider wiring, then real round-trip, then README/demo.
- Human checkpoints are correctly marked `autonomous:false` for Supabase/Render and real email verification.
- The plan correctly elevates D-13 inbound dedup, D-17 signature verification, and D-14 durable threading as thesis-critical.
- `/health/live` vs `/health/ready` split is the right Render/Supabase design.
- Demo strategy is pragmatic: prove live email once, record thesis beats through the deterministic dashboard path.
- README plan has the right audience split and includes the required tax disclaimers.

**Concerns**

- **HIGH — 06-04 may break the fixture path.** Replacing `parse_inbound` with Resend-only two-step parsing conflicts with "fixture path unchanged" and "developable by POSTing JSON fixtures." The route also verifies every `/webhook/inbound` request, so local unsigned JSON fixtures likely start failing unless an explicit fixture/dev path remains.
- **HIGH — 06-02 Docker runtime likely will not start.** The runtime stage copies `/app` and sets `.venv/bin` on `PATH`, but the CMD uses `uv run ...` without copying the `uv` binary into the runtime image. Either copy uv into runtime or run `uvicorn` directly from the venv (`.venv/bin/uvicorn`).
- **HIGH — 06-04 outbound threading depends on an unconfirmed Resend ID shape (A5).** The plan stores `resend.Emails.send()["id"]` as `email_messages.message_id` before A5 is confirmed. If that ID is Resend-internal rather than the actual RFC `Message-ID`, reply routing via `In-Reply-To` can break.
- **HIGH — 06-04 D-14 threading test is too narrow.** Testing that `send_outbound` builds a References header is not enough. There should also be an automated reply-routing test proving an inbound reply whose `In-Reply-To`/`References` points at the outbound chain resumes the correct run.
- **HIGH — 06-04 does not specify send-failure handling.** Plan writes `send_state='reserved'` before `resend.Emails.send`, then flips to `sent`, but does not require `failed` on provider exception. Can leave runs stuck in `reserved` instead of ERROR/retriggerable.
- **HIGH — D-13 dedup depends on current repo behavior that is not fully specified.** The plan says "rest of route unchanged" after parsing, but D-13 requires duplicate short-circuit BEFORE any pipeline task. The plan should explicitly require atomic insert-or-skip plus "enqueue background task only if inserted."
- **MEDIUM — 06-01 intentionally failing tests conflict with no-op-swap/CI stability.** Adding RED tests to the normal suite means `uv run pytest -q -m "not integration and not live_llm"` fails until 06-04. Use `xfail(strict=True)` or isolate RED checks so the branch is not in a globally failing state.
- **MEDIUM — 06-05 temporary raw logging is unsafe and incomplete.** Asks the human to log raw payload/body in Render logs, but after `parse_inbound` the raw provider headers are already discarded, so A1 is not actually captured. Log only header keys/IDs inside `gateway.py` behind a temporary env flag.
- **MEDIUM — 06-06 README PNG requirement is internally inconsistent.** Must-haves require committed `docs/architecture.png`, but the task allows accepting Mermaid-only. D-11a requires BOTH Mermaid source and exported PNG/SVG fallback.
- **MEDIUM — 06-06 demo reset may not fully reset dependent tables.** Deleting only `email_messages` and `payroll_runs` may fail or leave residue if line items/paystubs/alias audit rows reference runs. The reset should inspect FK order or use a deliberate `TRUNCATE ... CASCADE` for demo-owned tables.
- **LOW — 06-02 `.env.example` misses `RESEND_FROM_ADDR`.** (See note below — the revision routed this field to `app/config.py` + `render.yaml`; the `.env.example` line is worth adding for dev parity.)
- **LOW — 06-06 new docs files missing from frontmatter.** `docs/architecture.mmd` and `docs/architecture.png` should be listed in `files_modified`.

**Suggestions**

- Preserve dual inbound parsing: canonical fixture `InboundEmail` dicts should still parse locally, while Resend webhook payloads use the two-step fetch.
- Add explicit duplicate behavior in 06-04: `insert_inbound_email(... ON CONFLICT DO NOTHING RETURNING id)` and enqueue only on returned row.
- Store provider send ID separately if possible. If schema cannot change, do not assume it is an RFC Message-ID; prove reply routing works through `References`.
- Add tests for real reply matching using both `In-Reply-To` and `References` token chains.
- Fix Docker CMD/runtime: copy uv into runtime OR use `.venv/bin/uvicorn`.
- Add `try/except` around `resend.Emails.send` that marks the outbound row `failed` and raises into the existing ERROR/retry handling.
- Replace 06-05 manual debug edits with a committed, removable `LOG_WEBHOOK_DEBUG_IDS=true`-style switch that logs IDs/header keys only.
- Make `scripts/demo_reset.py` require an explicit mode; do not make destructive reset the default no-arg behavior.

**Risk Assessment**

**Overall: HIGH as written.** Right architecture and sequencing, but the Docker runtime issue can fail deployment outright, and the gateway changes risk breaking the fixture path and reply threading. After fixing fixture compatibility, outbound Message-ID/threading proof, send-failure handling, and the Docker CMD, this drops to **MEDIUM/LOW** for a portfolio-grade free-stack ship.

---

## Orchestrator Triage (Claude Code)

Cross-checking Codex's findings against the *revised* plans (Codex reviewed a snapshot; some details it flags were already partially addressed, and two references are off — there is no plan "06-13", and the `RESEND_FROM_ADDR` field was moved to `config.py`+`render.yaml` in the revision, so `.env.example` parity is a LOW nicety, not the AttributeError gap the plan-checker already closed).

**Findings I judge REAL and worth a revision pass (the GSD path is `/gsd-plan-phase 6 --reviews`):**

1. **HIGH — Docker runtime `uv run` without the uv binary (06-02).** Strongest finding. If the runtime stage doesn't carry the `uv` binary, `CMD uv run uvicorn ...` fails at container start → the Render deploy 502s. Fix: either `COPY --from=ghcr.io/astral-sh/uv ... /bin/` into the runtime stage too, or change CMD to `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}` (no uv needed at runtime — cleaner, smaller). **Verify the current 06-02 CMD/runtime-stage wording before fixing.**
2. **HIGH — Fixture path vs. signature verify (06-04).** Genuine. If `verify()` runs on every `/webhook/inbound` POST and `parse_inbound` becomes Resend-only, the existing fixture/dev path (POST a JSON `InboundEmail`) breaks — directly violating "fixture path unchanged" (OPS-02) and the no-op-swap invariant. Fix: keep a dev/fixture branch (shape-detect Resend webhook vs. canonical `InboundEmail` dict; skip verify when a dev flag is set or the payload is the canonical shape). **This is the most important correctness/scope finding.**
3. **HIGH — Send-failure handling (06-04).** Real gap. `reserved`→`sent` without a `reserved`→`failed` on exception strands runs in `reserved`. Fix: `try/except` around `resend.Emails.send` flips to `failed` and raises into the existing ERROR path (mirrors the Phase-5 D-13b delivery error boundary).
4. **HIGH — Dedup short-circuit must be explicit (06-04).** D-13's whole value is "duplicate does NOT re-run the pipeline." "Rest of route unchanged" is too loose. Fix: make it explicit — `ON CONFLICT DO NOTHING RETURNING id`, enqueue the background pipeline task ONLY if a row was inserted.
5. **MEDIUM — RED tests poison the mocked suite (06-01).** Adding failing tests to the default suite means the no-op-swap gate (`pytest -m "not integration and not live_llm"` green) is red from Wave 1 → Wave 3. Fix: mark the not-yet-implemented tests `@pytest.mark.xfail(strict=True)` so they flip to a real failure (XPASS) exactly when the feature lands, keeping the suite green in between.
6. **MEDIUM — A1 logging is in the wrong layer (06-05).** Correct: `parse_inbound` discards raw headers, so logging "after parse" can't capture real sender casing. Fix: log header keys/IDs INSIDE `gateway.py` behind a temporary `LOG_WEBHOOK_DEBUG_IDS` env flag (no PII — keys/IDs only).
7. **MEDIUM — D-14 needs an end-to-end reply-routing test, not just chain-construction.** Worth adding: an automated test that an inbound reply with `In-Reply-To`/`References` pointing at the outbound chain resumes the correct run (the existing reply-routing code exists from prior phases; assert it still matches).
8. **MEDIUM — demo-reset FK safety + non-default destructive mode (06-06).** Real: deleting only two tables may FK-fail or orphan rows; and a no-arg destructive default is foot-gun. Fix: explicit `--confirm`/mode flag; reset via FK-ordered deletes or `TRUNCATE ... CASCADE` on demo-owned tables (or just re-run seed, which the research already preferred).
9. **MEDIUM/LOW — 06-06 PNG must-have consistency + docs files in `files_modified`.** Tighten: D-11a requires BOTH Mermaid source AND a committed PNG (no Mermaid-only escape hatch); add `docs/architecture.mmd` + `docs/architecture.png` to frontmatter.

**Findings I judge already-addressed or off-target (no action):**
- `.env.example` missing `RESEND_FROM_ADDR` (LOW): the revision put the field in `config.py` (with a default) + `render.yaml`; the AttributeError gap is closed. Adding the `.env.example` line is a nicety, fold into #9 if revising 06-02.
- "06-13" — no such plan; Codex meant 06-04's D-13 dedup task (covered by #4).

---

## Consensus Summary

Single external reviewer (Codex), so "consensus" = Codex + orchestrator triage agreement.

### Agreed Strengths
- Locked dependency ordering (thin deploy → provider → round-trip → demo) is correct.
- Human gates (`autonomous:false`) are placed correctly.
- The thesis-critical trio (D-13 dedup, D-17 verify, D-14 threading) is correctly elevated.
- Health-route split + pragmatic demo strategy are sound.

### Agreed Concerns (highest priority → revise before execute)
1. Docker runtime won't start (`uv run` with no uv binary) — **deploy-blocking**.
2. Signature verify breaks the fixture/dev path — **violates no-op-swap + OPS-02 "fixture path unchanged"**.
3. Send-failure doesn't flip `reserved`→`failed` — **strands runs**.
4. Dedup short-circuit not explicit — **weakens the highest-value fix**.
5. RED tests poison the mocked suite between waves — use `xfail(strict=True)`.
6. A1 logging in the wrong layer; D-14 reply-routing not E2E-tested; demo-reset FK safety.

### Divergent Views
None (single reviewer). Two Codex references were stale/mistaken (`.env.example` field already relocated; "06-13" is 06-04's dedup task) — noted, not actioned as-is.

### Recommended next step
`/gsd-plan-phase 6 --reviews` — replan incorporating this feedback. The fixture-path fix (#2) and the Docker CMD fix (#1) are the two that would otherwise surface only at the live human deploy gate, which is the most expensive place to discover them.
