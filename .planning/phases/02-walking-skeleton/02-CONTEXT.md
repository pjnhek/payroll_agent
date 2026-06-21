# Phase 2: Walking Skeleton - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning

<domain>
## Phase Boundary

The first end-to-end proof: a messy fixture email flows through the four gated judgment stages (extract → reconcile names → validate fields → decide) to a **code-gated** decision, drives the run state machine through both pause points (`awaiting_reply`, `awaiting_approval`), and produces a *thin* computed payroll (gross + FICA, net labeled "pre-federal" — no fabricated federal figure). 19 requirements (INGEST-01..05, EMAIL-01, LLM-01..09, HITL-01, CLAR-01..04, DEMO-01). This is the judgment spine of the whole system; if the gated decision flow works, everything else is plumbing.

**In scope:** webhook ingest + background pipeline, the four pure-function judgment stages, the code gate, the orchestrator state machine through both pauses, the stub email gateway + fixture-reply injection, the clarify→reply→resume loop, a thin gross+FICA calc, on-demand paystub PDFs, and the two canonical demo fixtures.

**Out of scope (later phases):** real IRS Pub 15-T federal withholding (Phase 3), the dashboard UI / "Send test email" button (DASH-05, dashboard phase), the eval (Phase 4), the real email provider + deploy (hosting phase), state withholding, full mid-pipeline resume (only resume-from-start in scope, INGEST-05).

</domain>

<decisions>
## Implementation Decisions

### Background execution & orchestration (Area 1)
- **D-A1-01:** Webhook stores the inbound row, returns 200 fast, and schedules the pipeline via **FastAPI `BackgroundTasks` (in-process)** — roadmap-aligned, zero infra, fits the free single-service stack. The known risk (a Render dyno sleeping mid-run strands a run) is accepted and handled by the error-state + re-trigger path, NOT avoided. No external queue/worker.
- **D-A1-02:** An explicit `orchestrator.py` owns the legal `status` transitions and the two pause points (`awaiting_reply`, `awaiting_approval`) — plain Python state machine, Postgres as checkpoint, NOT LangGraph (locked).
- **D-A1-03:** Error model — the orchestrator wraps each run; any unhandled stage exception sets `status='error'` with the failure reason persisted on the run (surfaces on the dashboard later; "nothing silently hangs"). Re-trigger reruns **from the start of the run**, idempotently (INGEST-05; full mid-pipeline resume deferred to v2). No auto-retry of the whole run (operator re-triggers); the single reflective LLM retry in D-A2-03 is separate and stage-local.
- **D-A1-04:** Outbound-send idempotency (CLAR-04) — primary guard is **per-run sent-state flags + stored outbound Message-IDs** on the run. Before any clarification/confirmation send, code checks the flag; already-sent = skip (no-op). This makes re-trigger-from-start safe. A DB UNIQUE constraint may backstop but is not the primary mechanism.

### Model tiering & LLM test strategy (Area 2)
- **D-A2-01:** Test strategy — **mock/recorded responses by default, live opt-in**. Unit tests run the stages against stubbed/recorded fixture responses (deterministic, free, no network, CI-safe). A separate **env-gated opt-in mode** (mirroring the live-DB tests' two-factor guard) hits the real DeepSeek/Kimi APIs for periodic sanity checks. Real-model *accuracy* is measured in the eval (Phase 4), not the test suite.
- **D-A2-02:** Model tier assignment per existing `.env.example` / PROJECT.md tiering: **extraction = strong (DeepSeek v4-flash); name reconciliation + process/clarify decision = mid (Kimi/moonshot); clarification & confirmation email drafting = cheap (Kimi)**. The code gate calls **no model**. Config-driven (base_url/model/key swapped per tier) so any tier re-points without code change. Tier tuning is a Phase 4 eval concern.
- **D-A2-03:** Structured-output retry (LLM-02) — **reflective retry**: on a Pydantic `ValidationError` (or empty content, a known DeepSeek quirk), retry **once** with the validation error fed back into the prompt ("your last output failed: <error>, return valid JSON matching the schema"). If the retry also fails, the stage raises → run goes to `status='error'` (D-A1-03). Temperature 0 for extraction/decision; JSON mode (`response_format={"type":"json_object"}`) + Pydantic validation. One OpenAI-compatible client wrapper (LLM-01).

### Reconciliation gate semantics — THE CORE VALUE (Area 3)
- **D-A3-01:** Gate composition (LLM-04/05/07) — three layers, strictly ordered: **(1)** deterministic match (exact/case/whitespace/known-alias) resolves clean names with NO model call; **(2)** only residual (failed-deterministic) names go to the LLM, which returns match + confidence + reason and never re-decides a clean deterministic hit; **(3)** `decide.py` computes a code-owned `final_action` that hard-blocks on any name still unresolved or below **0.8** confidence — EVEN IF the model said `process`. `final_action` is the SOLE branch source consumed by the orchestrator, dashboard, and eval; nothing downstream ever branches on `model_action`.
- **D-A3-02:** One-to-one mapping enforcement (LLM-09) — `decide.py` validates the full submitted-name → employee mapping in code and gates to clarification if ANY of: **(a)** two submitted names resolve to the same `employee_id`, **(b)** a submitted name is duplicated, **(c)** a name resolves to no roster employee. Pure code (not model judgment); each collision becomes a `gate_reason`. A name cannot silently collapse onto another even with a confident model.
- **D-A3-03:** Decision object (LLM-08) — persisted as the existing Pydantic **`Decision` contract** (from Phase 1 `app/models/`) stored in a **JSONB column on `payroll_runs`**. Fields: `model_action`, `gate_triggered`, `gate_reasons`, `final_action`, `unresolved_names`, `missing_fields`, `confidence`, `reasons`. One typed object the orchestrator/dashboard/eval all read; they branch only on `final_action`. Planner confirms/adds the JSONB column to `schema.sql` (schema change → keep status-drift guard green).
- **D-A3-04:** 401k override (LLM-03) — extraction may return an optional current-run-only 401k contribution override that applies to THIS run only and never mutates the employee's stored default.

### Demo fixtures & clarify-reply loop (Area 4)
- **D-A4-01:** Two canonical demo fixtures (DEMO-01), committed as JSON: **(1) clean happy path** — runs to operator approval; **(2) gate-block** — an ambiguous submitted name that fails deterministic match and that the model reconciles with confidence **<0.8** (reuse the seeded **David Reyes / name-mismatch** employee), so the model proposes `process` but the code gate blocks → clarify. The sub-0.8-confidence story is the canonical on-camera case ("the model was willing; the code said no"). The one-to-one collision case and the missing-field case are valuable *additional* test cases, not the headline fixture.
- **D-A4-02:** Clarify-reply routing (EMAIL-01, CLAR-02/03) — the fixture reply is POSTed to the **same inbound webhook** with `In-Reply-To`/`References` pointing at the clarification's stored outbound Message-ID. Routing matches on that **header chain** (subject/provider-thread are fallbacks only), finds the run in `awaiting_reply`, and **re-enters at extraction idempotently** (overwrite `extracted_data`, replace line items by run). A header match to an already-sent/reconciled run is logged as a **late reply, not resumed**. This exercises the real routing path (the assumption fixtures can structurally test now and that breaks in P6 with real providers).
- **D-A4-03:** Fixture replay surface — in Phase 2, both fixtures are replayable by **POSTing the committed JSON to the inbound webhook** (script/test/curl) — deterministic, end-to-end, no UI. The "Send test email" dashboard button (DASH-05) that fires the same POST is deferred to the dashboard phase. Phase 2 proves the flow; the dashboard later just adds the on-camera button.

### Internal sequencing (LOCKED — from roadmap build-time guidance)
- **D-A5-01:** Build INSIDE the phase in this order: **(a)** clean happy path end-to-end first (POST fixture → all-clean match → process → thin calc → done — lands the one-third end-to-end proof), then **(b)** the gate-block case, then **(c)** the clarify-reply-resume loop LAST (CLAR-03 re-entrancy is the trickiest sub-piece). The phase exit criteria must name all three behaviors so it can't be called done with resume half-wired.

### README (small Phase 2 scope item)
- **D-A6-01:** Add a **minimal README stub** in Phase 2 carrying only the honesty-critical disclaimers that must exist the moment a paystub renders on screen: the "explicitly educational model" statement and the **"net is pre-federal in this slice (real federal withholding lands in Phase 3)"** note. The full README (setup, architecture, demo, eval chart, all FICA/IRS citations, OBBBA/Additional-Medicare disclaimers) is deferred to the hosting/demo phase — see Deferred Ideas.

### Claude's Discretion
- Exact module layout under `app/pipeline/` (stage file names, the `decide.py`/`orchestrator.py` split) — implementation detail for the planner, consistent with "stages are pure importable functions, data in/data out."
- Precise shape of the recorded-response fixtures and the env-gate flag name for the live-LLM opt-in (mirror the live-DB two-factor pattern).
- Whether a DB UNIQUE constraint backstops the per-run sent-state flags (D-A1-04).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap
- `.planning/REQUIREMENTS.md` — INGEST-01..05, EMAIL-01, LLM-01..09, HITL-01, CLAR-01..04, DEMO-01 (full text + traceability).
- `.planning/ROADMAP.md` §Phase 2 — goal, the 5 success criteria, and the **build-time guidance** (internal sequencing, pull-forward items: threading round-trip, prove Render+Supabase early).
- `.planning/PROJECT.md` — Core Value (the code-gated thesis), the 3-layer decisioning model, model tiering, fixture-first development, Out-of-Scope list.
- `./CLAUDE.md` — locked constraints (JSON mode + Pydantic + one retry, 0.8 threshold, non-reasoning models, stub gateway behind one interface, net "pre-federal", README disclaimers).

### Phase 1 artifacts this phase builds on
- `app/models/contracts.py` — `InboundEmail`, `Extracted`, `ExtractedEmployee`, `Decision`, `PaystubLineItem` (the same types the eval imports; the `Decision` contract is the persisted decision object, D-A3-03).
- `app/models/roster.py` — `Employee`, `Roster`, `NameMatchResult`, `ValidationIssue` (reconciliation I/O shapes; `NameMatchResult.confidence` drives the 0.8 gate).
- `app/models/status.py` — `RunStatus` (the 11-value state machine the orchestrator drives; pauses at `awaiting_reply`, `awaiting_approval`).
- `app/db/schema.sql` — the 6 tables; `payroll_runs` (add the `Decision` JSONB column, D-A3-03), `email_messages` (Message-ID/In-Reply-To/References, UNIQUE(message_id) idempotency), the status drift guard must stay green on any schema change.
- `app/db/seed.py` — seeded businesses/employees incl. the David Reyes name-mismatch case used by the gate-block fixture (D-A4-01).
- `app/config.py` — `Settings` (the per-tier model/base_url/key config consumed by the LLM client, D-A2-02).

### Provider IDs (must confirm before live demo)
- `.env.example` — model-tier env var names (live values now in local `.env`). Model IDs still placeholders to confirm from the DeepSeek/Kimi consoles (see STATE.md Blockers + memory `payroll-agent-provider-ids-unconfirmed`).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **All Phase 1 Pydantic contracts** are the I/O shapes for every stage — the stages are typed pure functions over these. No new contract types should be needed beyond wiring (and possibly small additions for the run/decision persistence).
- **`app/db/supabase.py`** — pooled connection (`get_connection`) + `close_pool()`; the orchestrator and stages use this for all state reads/writes.
- **Seed data** already covers the gate-block demo case (David Reyes), so the fixture reuses real seeded rows rather than inventing a roster.

### Established Patterns
- **Contracts-first / fixture-first** — develop and test the whole pipeline by POSTing JSON; the real email provider is wired last (P6).
- **Two-factor env-gated live tests** (live-DB pattern from Phase 1) — reuse this exact shape for the live-LLM opt-in (D-A2-01).
- **`schema.sql` is the single source of truth** applied via `bootstrap.py`; any column addition (Decision JSONB, sent-state flags) goes there, and the status-drift guard pattern is the model the planner extends if new enums appear.

### Integration Points
- New `app/pipeline/` (stages + `decide.py` + `orchestrator.py`), a new FastAPI webhook entrypoint (`app/web/` or `app/main.py`), and a new stub email gateway (`app/email/`) behind one small interface (`parse_inbound`, `send_outbound`) so the real provider swaps in at P6.
- The webhook → orchestrator → stages → DB write path; the orchestrator owns `RunStatus` transitions.

</code_context>

<specifics>
## Specific Ideas

- Gate-block demo narrative for camera: "the model was willing to process — the code said no." Drive it with the sub-0.8 David Reyes name (D-A4-01).
- Re-use the Phase 1 live-DB two-factor test-gate pattern verbatim for the live-LLM opt-in, so the suite stays green and free by default.
- Net pay must be labeled **"pre-federal"** everywhere it appears (paystub, decision, any output) — no fabricated federal number until Phase 3.

</specifics>

<deferred>
## Deferred Ideas

- **Full README** (setup, architecture, demo GIF, eval chart, FICA/IRS Pub 15-T citations, OBBBA + Additional-Medicare out-of-scope disclaimers) → **hosting/demo phase**. Only the minimal disclaimer stub is in Phase 2 (D-A6-01).
- **Dashboard "Send test email" button** (DASH-05) and the dashboard UI generally → **dashboard phase**. Phase 2 replays fixtures via raw webhook POST (D-A4-03).
- **Real IRS Pub 15-T federal withholding** → **Phase 3**. Phase 2 calc is thin (gross + FICA, net pre-federal).
- **Real email provider + Render/Supabase deploy** → **hosting phase (P6)**. NOTE build-guidance pull-forward: send ONE real email + reply during P1/P2 to confirm In-Reply-To/References headers survive the provider round-trip, and do a hello-world Render+Supabase deploy early — both retire last-phase landmines but are not blocking Phase 2's fixture-first build.
- **Full mid-pipeline resume from arbitrary status** (INGEST-05 v2) → deferred; Phase 2 only does resume-from-start.
- **Auto-retry of a whole errored run** → not in scope; operator re-triggers (D-A1-03).

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 2-Walking Skeleton*
*Context gathered: 2026-06-21*
