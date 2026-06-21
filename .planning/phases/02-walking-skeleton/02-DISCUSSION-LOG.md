# Phase 2: Walking Skeleton - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 2-Walking Skeleton
**Areas discussed:** Background task & error/retry model, Model tiering & live-vs-mock LLM, Reconciliation gate semantics, Demo fixtures & clarify-reply loop (+ README handling)

---

## Background task & error/retry model

### Async execution (INGEST-01)
| Option | Description | Selected |
|--------|-------------|----------|
| FastAPI BackgroundTasks (in-process) | Webhook returns 200 fast, schedules pipeline in-process; accepts sleeping-dyno risk, handled by error+re-trigger | ✓ |
| External queue / worker | Separate worker/queue so a sleeping web dyno can't strand work; more infra/cost | |
| Synchronous in the request | Run pipeline inside the request; violates INGEST-01, risks timeouts | |

**User's choice:** FastAPI BackgroundTasks (in-process)
**Notes:** Roadmap-aligned; fits the free single-service stack.

### Error handling & recovery (INGEST-05)
| Option | Description | Selected |
|--------|-------------|----------|
| Catch → status=error, store reason | Unhandled stage exception → status='error' + reason; re-trigger from start, idempotent | ✓ |
| Catch + auto-retry once, then error | Same but auto-retry whole run once before error | |
| Let it crash (no error state) | No wrapping; violates "nothing silently hangs" | |

**User's choice:** Catch → status=error, store reason
**Notes:** Re-trigger reruns from the start of the run; full mid-pipeline resume deferred to v2.

### Outbound-send idempotency (CLAR-04)
| Option | Description | Selected |
|--------|-------------|----------|
| Per-run sent-state flags + stored Message-IDs | Code checks per-run sent flags before any send; already-sent = skip | ✓ |
| Unique constraint on email_messages | DB UNIQUE makes duplicate send fail at insert; blunter | |
| You decide | Choose cleanest mechanism during planning | |

**User's choice:** Per-run sent-state flags + stored Message-IDs
**Notes:** Makes re-trigger-from-start safe; DB UNIQUE may backstop but isn't primary.

---

## Model tiering & live-vs-mock LLM

### Test strategy (LLM-01/02)
| Option | Description | Selected |
|--------|-------------|----------|
| Mock/recorded by default, live opt-in | Stubbed/recorded responses for CI; env-gated opt-in hits real APIs; mirrors live-DB pattern | ✓ |
| Always live | Every test calls real models; costly, flaky, non-deterministic | |
| Pure mock only | Only stubbed; never exercises real client wiring | |

**User's choice:** Mock/recorded by default, live opt-in
**Notes:** Real-model accuracy is measured in the Phase 4 eval, not the test suite.

### Model tier assignment (LLM-01)
| Option | Description | Selected |
|--------|-------------|----------|
| Per .env.example defaults | extraction=DeepSeek strong; reconcile+decide=Kimi mid; draft=Kimi cheap; gate=no model | ✓ |
| Tune assignments now | Revisit which stage gets which tier | |
| You decide | Use defaults; flag tuning as Phase 4 | |

**User's choice:** Per .env.example defaults
**Notes:** Config-driven; tier tuning is a Phase 4 eval concern.

### Reflective retry on bad JSON (LLM-02)
| Option | Description | Selected |
|--------|-------------|----------|
| Reflective retry: feed error back, then fail-closed | On ValidationError/empty content, retry once with error in prompt; else → status=error | ✓ |
| Plain retry (same prompt) | Retry once, no reflection | |
| You decide | Standard reflective-retry pattern in planning | |

**User's choice:** Reflective retry: feed the error back, then fail-closed
**Notes:** Also covers DeepSeek's empty-content quirk; temperature 0.

---

## Reconciliation gate semantics

### Gate composition (LLM-04/05/07)
| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic first; model only on residuals; code gate is final | 3 ordered layers; final_action is sole branch source; gate hard-blocks even on model 'process' | ✓ |
| Adjust the layering | Run model on all names / let model bypass gate | |

**User's choice:** Deterministic first; model only on residuals; code gate is final
**Notes:** The thesis — gate is code-owned and unconditional at 0.8.

### One-to-one mapping enforcement (LLM-09)
| Option | Description | Selected |
|--------|-------------|----------|
| Enforce all three collision cases in code | two-names→one-employee, duplicate, name→nobody all gate to clarify; each a gate_reason | ✓ |
| Just the no-match case | Only gate when a name resolves to nobody; misses collapse | |
| You decide | Full three-case validation in planning | |

**User's choice:** Enforce all three collision cases in code
**Notes:** Pure code backstop; a name cannot collapse onto another even with a confident model.

### Decision object (LLM-08)
| Option | Description | Selected |
|--------|-------------|----------|
| Pydantic Decision contract → JSONB column on the run | Existing Decision contract persisted as JSONB on payroll_runs; all consumers branch on final_action | ✓ |
| Separate decision columns | Flatten each field into its own column; more schema surface | |
| You decide | JSONB likely; confirm in planning | |

**User's choice:** Pydantic Decision contract → JSONB column on the run
**Notes:** Planner confirms/adds the column to schema.sql; keep status-drift guard green.

---

## Demo fixtures & clarify-reply loop

### Gate-block fixture trigger (DEMO-01)
| Option | Description | Selected |
|--------|-------------|----------|
| Ambiguous name below 0.8 (seeded mismatch case) | Model reconciles David Reyes <0.8, proposes process, gate blocks → clarify | ✓ |
| One-to-one collision (two names → one employee) | LLM-09 collapse; strong second test | |
| Missing required field | Gate blocks on missing_fields; less visual | |

**User's choice:** Ambiguous name below 0.8 (uses seeded mismatch case)
**Notes:** Cleanest on-camera narrative; reuses Phase 1 seed coverage. Collision/missing-field cases kept as additional tests.

### Clarify-reply injection & routing (EMAIL-01, CLAR-02/03)
| Option | Description | Selected |
|--------|-------------|----------|
| Inject via webhook with In-Reply-To = stored outbound Message-ID | Reply POSTed to same webhook; header-chain routing; re-enter at extraction idempotently; late reply logged not resumed | ✓ |
| Direct resume call (bypass webhook) | Test helper calls resume directly; doesn't exercise routing | |
| You decide | Route through webhook in planning | |

**User's choice:** Inject via webhook with In-Reply-To = stored outbound Message-ID
**Notes:** Exercises the real routing path — the P6 landmine fixtures can structurally test now.

### Fixture replay surface (DEMO-01 / DASH-05)
| Option | Description | Selected |
|--------|-------------|----------|
| Replayable via webhook POST now; dashboard button later | Fixtures committed as JSON, POSTed to webhook in P2; "Send test email" button deferred to dashboard phase | ✓ |
| Build a minimal trigger endpoint now | Dedicated replay endpoint, less than full dashboard | |
| You decide | Webhook POST now; thin endpoint only if planning shows worth | |

**User's choice:** Replayable via webhook POST now; dashboard button later
**Notes:** Keeps Phase 2 scope honest (no UI).

---

## Claude's Discretion

- Exact module layout under `app/pipeline/` (stage file names, decide.py/orchestrator.py split).
- Shape of recorded-response fixtures + env-gate flag name for the live-LLM opt-in (mirror the live-DB two-factor pattern).
- Whether a DB UNIQUE constraint backstops the per-run sent-state flags.

## Deferred Ideas

- Full README → hosting/demo phase (only a minimal disclaimer stub in Phase 2).
- Dashboard "Send test email" button (DASH-05) + dashboard UI → dashboard phase.
- Real IRS Pub 15-T federal withholding → Phase 3 (Phase 2 calc is thin, net pre-federal).
- Real email provider + Render/Supabase deploy → hosting phase (with the pull-forward: prove header round-trip + hello-world deploy early).
- Full mid-pipeline resume from arbitrary status → INGEST-05 v2.
- Auto-retry of a whole errored run → not in scope; operator re-triggers.
