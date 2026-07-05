# Phase 11: Clarification Round Machine & Alias Learning - Pattern Map

**Mapped:** 2026-07-05
**Files analyzed:** 15 (10 modified, 5 new test modules)
**Analogs found:** 15 / 15 (every file has an in-repo copy target; this phase invents no new pattern classes)

**Character of this phase:** pure internal redesign — every new mechanism has a proven in-repo primitive (RESEARCH "Don't Hand-Roll"). Most "analogs" are *other seams inside the same file*. The failure mode is inventing a parallel primitive, not missing one.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `app/db/schema.sql` (M) | config/migration | batch DDL | its own DO-blocks (`:141-171`, `:267-278`) | exact |
| `app/db/repo.py` (M) | repository | CRUD | its own fns: `get_outbound_message_id` (`:1054`), `claim_status` (`:422`), `link_email_to_run` (`:199`), `load_thread_messages` (`:1257`), `sweep_stranded_runs` (`:459`) | exact |
| `app/models/status.py` (M) | model (enum) | — | itself (add one member) | exact |
| `app/pipeline/orchestrator.py` (M) | service/workflow | event-driven pipeline | its own seams: `_clarify` guard + 3 finalize paths, `_combined_context_email` (`:837`), bind STEP C/D (`:667-734`), `_write_aliases_if_safe` (`:1181`) | exact |
| `app/pipeline/extract.py` (M) | service (LLM seam) | request-response | itself + `app/llm/prompts/` build_messages idiom | exact |
| `app/main.py` (M) | controller (routes) | request-response | its own routes: `approve`/`reject` (`:642-698`), `retrigger` (`:701-809`), webhook duplicate branch (`:456-465`), `runs_list` sweep hook (`:1073-1076`), badge maps (`:185-226`) | exact |
| `app/templates/run_detail.html` (M) | component (Jinja2) | request-response | its own blocks: awaiting_reply banner+form (`:71-84`), approve/reject forms (`:293-303`), provenance badge macro (`:147-159`) | exact |
| `tests/conftest.py` (M) | test infra | — | its own `InMemoryRepo` method style (`:253-350`, esp. `link_email_to_run` mirror `:288-297`) | exact |
| `tests/test_multiround_context_edge.py` (M) | test | — | its own sibling CX-03 test (`:322+`, asserts DESIRED behavior + paid VALUES) | exact |
| `tests/test_alias_write.py` (M) | test | — | itself (`:720+` binding tests — update shape, un-fake resolution per D-11-17) | exact |
| `tests/test_clarify_rounds.py` (NEW) | test | — | `tests/test_atomic_persist.py` (crash-injection `:170`, AST source-order guard `:234-298`) | role-match |
| `tests/test_needs_operator.py` (NEW) | test | — | `tests/test_stuck_run_recovery.py` scope pins (`:68-93`) + `tests/test_status_drift.py` drift guard + `tests/test_dashboard.py` route tests | role-match |
| `tests/test_combined_context.py` (NEW) | test (pure fn) | — | `tests/test_multiround_context_edge.py` (hermetic, unguarded module, module-docstring warning `:1-12`) | role-match |
| `tests/test_alias_full_loop.py` (NEW) | test (hermetic integration) | — | `tests/test_multiround_context_edge.py` (drives REAL `resume_pipeline` with `fake_repo` + `mock_llm`, asserts persisted line-item values `:295-313`) | exact-for-style |
| `tests/test_reply_redelivery.py` (NEW) | test (webhook) | — | `tests/test_ingest.py` (TestClient + fake_repo fixture `:65-75`, duplicate-delivery tests `:133`, `:256`) | exact-for-style |

## Pattern Assignments

### `app/db/schema.sql` — new columns, widened constraint, `needs_operator` in status CHECK

**Analog: idempotent column add** (`schema.sql:109-115`):
```sql
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS alias_candidates  JSONB;  -- D-04 (Plan 05-03)
ALTER TABLE payroll_runs ADD COLUMN IF NOT EXISTS clarified_fields      JSONB;  -- D-13 MONEY-03
```
Copy for: `payroll_runs.clarification_round INT NOT NULL DEFAULT 0`, `email_messages.round INT NOT NULL DEFAULT 0` (NOT NULL — Pitfall #2: nullable round disables confirmation dedup), `email_messages.consumed_round INT` (nullable = unconsumed).

**Analog: column-anchored CHECK drop + atomic re-ADD in one DO-block** (`schema.sql:141-171` — the WR-06-hardened pattern; conkey match, never name-substring):
```sql
DO $$
DECLARE
    _con RECORD;
BEGIN
    FOR _con IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.contype = 'c'
          AND c.conrelid = 'payroll_runs'::regclass
          AND (SELECT array_agg(a.attname::text)
               FROM pg_attribute a
               WHERE a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
              ) = ARRAY['status']
    LOOP
        EXECUTE 'ALTER TABLE payroll_runs DROP CONSTRAINT ' || quote_ident(_con.conname);
    END LOOP;
    ALTER TABLE payroll_runs ADD CONSTRAINT payroll_runs_status_check
        CHECK (status IN ( 'received', ... 'error' ));
END;
$$;
```
Copy for the `needs_operator` addition — AND edit the inline CREATE TABLE CHECK (`:68-80`) in the same change. The drift guard (`tests/test_status_drift.py:63-98`) parses BOTH spots; miss one and CI fails (that is the desired forcing function).

**Analog: named-constraint guard for UNIQUE add** (`schema.sql:267-278`):
```sql
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_email_run_purpose'
          AND conrelid = 'email_messages'::regclass
    ) THEN
        ALTER TABLE email_messages
            ADD CONSTRAINT uq_email_run_purpose UNIQUE (run_id, purpose);
    END IF;
END;
$$;
```
Copy for widening to `UNIQUE(run_id, purpose, round)` — combine with a conditional DROP of the old name in ONE DO-block (a failed ADD rolls back the DROP, per the D-7.5-03a comment at `:126-129`). RESEARCH "Code Examples" §1 already sketches the exact block. Backfill formulas (clarification_round from sent-row count; round=0) belong in the same checkpoint window (RESEARCH Open Question #3, Pitfall #1/A2 sequencing).

---

### `app/db/repo.py` — round lookup, consumed marker, consumed-replies query, clear-context, stranded-unconsumed query, `insert_email_message` round param

**Analog: purpose-scoped guard lookup** (`repo.py:1054-1080`) — copy shape for `get_outbound_for_round(run_id, purpose, round)` (must return the row's **round**, not just message_id — Pitfall #3):
```python
def get_outbound_message_id(run_id: uuid.UUID, purpose: str, conn=None) -> str | None:
    if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
        raise ValueError(...)
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT message_id FROM email_messages
            WHERE run_id = %s AND direction = 'outbound'
              AND purpose = %s AND send_state = 'sent'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id), purpose),
        ).fetchone()
    return row[0] if row else None
```
Note the invalid-purpose guard (T-05-09b) and the `send_state='sent'` proof-of-delivery filter — keep both in the round-aware variant.

**Analog: single-row write with caller-joinable transaction** (`repo.py:199-223`, `link_email_to_run`) — copy for `mark_reply_consumed`, `clear_reply_context`, `set_clarification_round`:
```python
def link_email_to_run(email_id: uuid.UUID, run_id: uuid.UUID, conn=None) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE email_messages SET run_id = %s WHERE id = %s",
                (str(run_id), str(email_id)),
            )
```
The `_conn_ctx(conn) as (c, owns)` + `c.transaction() if owns else _nulltx()` idiom is THE repo convention — every new write fn uses it so it can join `_clarify`'s finalize transaction via `conn=`.

**Analog: CAS writer** (`repo.py:422-447`) — do NOT build new fencing; reuse:
```python
row = c.execute(
    "UPDATE payroll_runs SET status = %s, updated_at = now() "
    "WHERE id = %s AND status = %s RETURNING id",
    (RunStatus(new).value, str(run_id), RunStatus(expected).value),
).fetchone()
return row is not None
```
D-12: `set_status`/`claim_status` are the only sanctioned status writers (plus the documented `sweep_stranded_runs` third). Escalation to `needs_operator` uses `set_status`; operator resume uses `claim_status(NEEDS_OPERATOR, EXTRACTING)`.

**Analog: multi-row dict query** (`repo.py:1257-1278`, `load_thread_messages`) — copy for `load_consumed_replies(run_id)` (filter `direction='inbound' AND consumed_round IS NOT NULL`, `ORDER BY consumed_round ASC`) and `find_stranded_unconsumed_replies`:
```python
sql = (
    "SELECT direction, purpose, subject, body_text, message_id,"
    " from_addr, to_addr, created_at"
    " FROM email_messages"
    " WHERE run_id = %s"
    " ORDER BY created_at ASC"
)
with _conn_ctx(conn) as (c, _owns):
    with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(run_id), str(run_id)))
        return cur.fetchall() or []
```

**Analog: the ON CONFLICT coupling to change in lockstep** (`repo.py:990-1007`) — Pitfall #1, the arbiter MUST match the new constraint in the same plan step:
```python
ON CONFLICT (run_id, purpose) DO UPDATE      -- becomes ON CONFLICT (run_id, purpose, round)
    SET send_state = EXCLUDED.send_state,
        message_id = EXCLUDED.message_id, ...
```
Add a `round: int = 0` kwarg to `insert_email_message`; `gateway.send_outbound` routes through it and must pass round too. Per-round retry still upserts; a new round is a new row (D-11-01).

**Analog: pinned scope constant** (`repo.py:450-456`) — copy the comment discipline for `MAX_CLARIFICATION_ROUNDS`:
```python
# Stranded-run scope (D-9-12): EXACTLY these three in-flight statuses are eligible
# ... This list is pinned by an explicit unit test ...
_STRANDED_SCOPE_STATUSES: list[str] = ["received", "extracting", "computed"]
```
The cap constant lives at module level with documented derivation (D-11-07, STALE_THRESHOLD style — see `main.py:100-101`).

---

### `app/models/status.py` — `NEEDS_OPERATOR`

One-line member append to the existing StrEnum (`status.py:17-26`); update the "Ten-state" docstring. The drift guard forces the two schema.sql mirrors.

---

### `app/pipeline/orchestrator.py` — round guard, cap/escape, suggestion persist, accumulation, bind rewrite

**Analog: the guard being re-keyed** (`orchestrator.py:1022-1037`) — current WR-05 shape, keep the structure, change the key to (purpose, round):
```python
existing_clari = repo.get_outbound_message_id(run_id, purpose=purpose)
if existing_clari is not None:
    logger.info("clarification already sent for run %s (purpose=%r) — skipping duplicate send ...", run_id, purpose)
    # D-9-06: both writes commit as one transaction, status-advance last (D-9-02).
    with repo.get_connection() as conn:
        with conn.transaction():
            repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
            repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)
    return
```
The early-return path must ALSO advance the round to `found_row.round + 1` (Pitfall #3 — derive from the found sent row, never blind `+1`; the same derived write goes in all THREE finalize paths).

**Analog: finalize transaction shape — all three exit paths** (`orchestrator.py:1175-1178`; twins at `:1033-1037` and `:1154-1158`):
```python
# D-9-06/D-9-01: gateway.send_outbound (the provider call) has ALREADY returned
# above — this transaction opens strictly AFTER it, status-advance last (D-9-02).
with repo.get_connection() as conn:
    with conn.transaction():
        repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
        repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)  # CLAR-01 pause
```
Round increment (`repo.set_clarification_round(run_id, sent_row_round + 1, conn=conn)`) slots in BEFORE the `set_status` line in each of the three blocks. Never put an LLM/provider call inside (D-9-01).

**Analog: cap-check placement** — top of `_clarify`, before guard/draft/send (RESEARCH Pattern 2; covers both call sites `:980` and `:826` with one check):
```python
if repo.get_clarification_round(run_id) >= MAX_CLARIFICATION_ROUNDS:
    with repo.get_connection() as conn:
        with conn.transaction():
            repo.set_status(run_id, RunStatus.NEEDS_OPERATOR, conn=conn)  # status-advance-LAST
    logger.info("run %s escalated to needs_operator after %d rounds (D-11-07)", run_id, MAX_CLARIFICATION_ROUNDS)
    return
```

**Analog: suggestion computation to persist** (`orchestrator.py:1110-1115` + `suggest.py:60-72`):
```python
suggestions = suggest_employees(decision.unresolved_names, roster, **suggest_kwargs)
# suggest_employees returns {submitted_name: suggested_FULL_NAME} — a NAME, not an id.
```
Pitfall #5: at the persist site, map full_name → employee id via the already-loaded roster (`full_name` UNIQUE per business); not-found → `suggested: null`. Persist via the existing `repo.set_alias_candidates` write (`:1091` shows the call shape) with the D-11-14 nested value `{token: {"suggested": id, "bound": None}}`. Keep `suggest_employees` itself unchanged (compose still needs names). Follow its PII discipline: log counts/types, never tokens+names together (`suggest.py:82-89`).

**Analog: combined context — the function being rewritten** (`orchestrator.py:837-850`):
```python
def _combined_context_email(reply: InboundEmail, original_body: str) -> InboundEmail:
    combined_body = (
        "ORIGINAL PAYROLL EMAIL:\n"
        f"{original_body}\n\n"
        "CLARIFICATION REPLY FROM CLIENT:\n"
        f"{reply.body_text}"
    )
    return reply.model_copy(update={"body_text": combined_body})
```
Keep the pure-function + `model_copy(update=...)` shape; extend signature to `(reply, original_body, *, asked_summary_lines, prior_replies)` per RESEARCH Pattern 3. The asked-summary renders from persisted decision facts (`decision.unresolved_names` + `clarified_fields` entries currently `"asked"`), NEVER the LLM-drafted body (D-11-10). String-for-string testable.

**Analog: the bind logic being replaced** (`orchestrator.py:667-734` — NEW-2 pre-vs-post diff; deprecated wholesale by D-11-15 but its post-reconciliation load + set-diff mechanics are reused verbatim):
```python
post_run_data = repo.load_run(run_id)
_post_reconciliation = (post_run_data.get("reconciliation") or []) if post_run_data else []
_post_resolved_ids: set[str] = set()
for _m in _post_reconciliation:
    if isinstance(_m, dict) and _m.get("matched_employee_id") is not None:
        _post_resolved_ids.add(str(_m["matched_employee_id"]))
_newly_resolved_ids = _post_resolved_ids - _pre_resolved_ids
```
New condition (RESEARCH Pattern 4): bind iff `suggested_id in _newly_resolved_ids` AND token gone from unresolved submitted names. Keep the both-branches `logger.info` skip-reason style (`:712-734`) — every non-bind logs why (misname guard narrative).

**Analog: `_write_aliases_if_safe`** (`orchestrator.py:1181-1260`) — structure stays verbatim; only the skip condition changes:
```python
for token, employee_id_str in alias_candidates.items():
    if employee_id_str is None:          # OLD skip → NEW: cand.get("bound") is None
        continue
    ...
    if not _safe_to_learn_alias(token, target_employee, current_roster):   # D-01b collision re-check: KEEP
        continue
    written = repo.update_known_alias(employee_id, token, conn=conn)
    if written:
        # BATCH-SAFE roster refresh after each accepted write: KEEP
        current_roster = repo.load_roster_for_business(run["business_id"], conn=conn)
```
Pitfall #6: live rows carry the old flat shape — one-shot migrate at the checkpoint or a normalize-on-read helper shared by bind + write (pick ONE, test both shapes). This fn swallows exceptions by design at its call site (D-13b) — an AttributeError here dies silently, so shape handling must be explicit.

**Analog: resume CAS claim + consume point** (`orchestrator.py:263-269`):
```python
claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
if not claimed:
    logger.info("resume aborted: run %s claim failed — late/duplicate reply dropped (CR-02, D-12)", run_id)
    return
```
`mark_reply_consumed(...)` goes immediately after a successful claim (D-11-02). Do NOT touch `is_round_2 = bool(clarified)` (`:346`) — it is classify state, not round state (Pitfall #12).

---

### `app/pipeline/extract.py` — absent-if-unaddressed prompt instruction

**Analog: the prompt seam** (`extract.py:46-49`):
```python
messages = extract_prompt.build_messages(email, roster)
payload: ExtractionPayload = llm.call_structured("extraction", messages, ExtractionPayload)
```
The instruction lands in `app/llm/prompts/extract.py`'s `build_messages` (or a resume-context variant) — policy only; the deterministic backstop is the `decide` gate re-asking (Pitfall #9: test the backstop, not the LLM). Preserve extract()'s purity contract (no DB I/O; run_id stamped by code, FIX A).

---

### `app/main.py` — WR-04 re-schedule, D-11-05 hook, retrigger clear, badge maps, resolve route

**Analog: post-commit duplicate branch** (`main.py:453-465`) — the WR-04 re-schedule extends exactly this branch, strictly post-commit (Pitfall #11):
```python
# ── Transaction committed. Everything below is post-commit response shaping
# + background task scheduling — never inside the `with` block above. ──────
if outcome == "duplicate":
    logger.info("duplicate inbound message_id=%s — no second run", email.message_id)
    return JSONResponse(status_code=200, content={"status": "duplicate", ...})
```
When the parsed email carries reply headers: load the PERSISTED row by message_id (it has run_id via WR-03, cleaned body, consumed_round); if `consumed_round IS NULL` and run is `awaiting_reply` → `background_tasks.add_task(_resume_pipeline, run_id, persisted_as_inbound)`. Never rebuild from the redelivered request body.

**Analog: background scheduling shape** (`main.py:549-554`):
```python
reply_for_resume = email.model_copy(update={"body_text": cleaned})
background_tasks.add_task(_resume_pipeline, run_id, reply_for_resume)
return JSONResponse(status_code=200, content={"status": "resumed", "run_id": str(run_id)})
```

**Analog: runs-list recovery hook** (`main.py:1073-1076`) — D-11-05 adds a sibling call beside it, same swallow-on-failure style:
```python
try:
    repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)
except Exception:
    logger.debug("sweep_stranded_runs unavailable — skipping this page load")
```

**Analog: operator action route — the resolve/resume form POST copies `approve`** (`main.py:642-687`):
```python
@app.post("/runs/{run_id}/approve")
def approve(run_id: uuid.UUID, background_tasks: BackgroundTasks) -> RedirectResponse:
    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if claimed:
        try:
            run = repo.load_run(run_id)
            _deliver(run_id, run)
        except Exception as exc:  # noqa: BLE001 — D-13b error boundary
            logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)  # PII-safe: type only
            repo.record_run_error(run_id, type(exc).__name__, detail_exc=exc, stage="delivery", ...)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```
Resolve route: validate form fields (every posted employee_id ∈ the run's business roster — server-side, RESEARCH Security V4; reject the whole POST on any invalid id), apply the mapping deterministically, THEN `claim_status(NEEDS_OPERATOR, EXTRACTING)`, then `background_tasks.add_task(...)`, always 303. Form params need `python-multipart` (already a dep — see `simulate-reply` route for the `Form(...)` idiom).

**Analog: retrigger clear-at-seam** (`main.py:751-808`) — D-11-04's clear goes AFTER a winning claim in BOTH branches (ERROR/APPROVED CAS at `:751-755` and stale in-flight CAS at `:796-798`), before `background_tasks.add_task(_run_pipeline, run_id)` at `:807-808` (Pitfall #8). Honor the docstring at `:766-776`: scope lists deliberately diverge — do NOT add `needs_operator` to `stale_statuses`.

**Analog: badge maps** (`main.py:185-212`) — add `"needs_operator"` to BOTH dicts (own attention-color class per D-11-06); do NOT add to `IN_FLIGHT_STATUSES` (`:111-113`) — it is a settled gate state (Pitfall #4 item 6):
```python
_BADGE_CLASS: dict[str, str] = {"received": "neutral", ..., "awaiting_approval": "pending", "error": "bad"}
_BADGE_LABEL: dict[str, str] = {..., "awaiting_approval": "Needs Approval", ...}
```

---

### `app/templates/run_detail.html` — needs_operator banner + resolve form

**Analog: status-gated banner with embedded form** (`run_detail.html:71-84`) — the resolve form copies this block wholesale:
```html
{% elif run.status == 'awaiting_reply' %}
<div class="banner banner-awaiting banner-mb">
  <strong>Awaiting client reply</strong> — A clarification email has been sent. ...
  <div class="banner-divider">
    <form method="post" action="/runs/{{ run.id }}/simulate-reply" class="composer">
      <textarea name="reply_body" rows="3" class="sim-reply-textarea">...</textarea>
      <div class="form-inline" style="margin-bottom: 0;">
        <button type="submit" class="btn-approve">Simulate client reply</button>
        <span class="form-help">...</span>
      </div>
    </form>
  </div>
</div>
```

**Analog: operator action forms** (`run_detail.html:293-303`) — Resume/Reject pair for `needs_operator` mirrors:
```html
{% if run.status == 'awaiting_approval' %}
<div class="inline-actions">
  <form method="post" action="/runs/{{ run.id }}/approve">
    <button type="submit" class="btn-approve">Approve &amp; Send</button>
  </form>
  <form method="post" action="/runs/{{ run.id }}/reject"
        onsubmit="return confirm('Reject this payroll run? This cannot be undone.')">
    <button type="submit" class="btn-reject">Reject</button>
  </form>
</div>
{% endif %}
```
Per-name dropdown rows: `<select name="...">` over roster employees with the suggestion pre-selected + a `"remember this alias"` checkbox default-checked (D-11-16). Badge styling idiom: the provenance macro (`:147-159`) shows the inline-badge convention. Do NOT add `needs_operator` to the retrigger-form status list (`:306`).

---

### `tests/conftest.py` — InMemoryRepo mirrors (prerequisite for every new hermetic module, Pitfall #7)

**Analog: faithful mirror method with rationale docstring** (`conftest.py:288-297`):
```python
def link_email_to_run(self, email_id, run_id, conn=None):
    """Mirror repo.link_email_to_run (WR-03 phase-9 review fix). ..."""
    row = self.email_by_id.get(str(email_id))
    if row is not None:
        row["run_id"] = run_id
```
Every new repo fn (`get_clarification_round`, `get_outbound_for_round`, `mark_reply_consumed`, `load_consumed_replies`, `clear_reply_context`, `find_stranded_unconsumed_replies`, `insert_email_message` round param, `set_clarification_round`) needs a mirror with real semantics. Convention: the fake duplicates scope constants rather than importing them (`conftest.py:247-250`) so a scope change forces a visible test failure.

---

### `tests/test_multiround_context_edge.py` — assertion flip (CLAR2-05)

**Analog: its own flip instructions + the money-value assertion shape** (`:295-313`):
```python
line_items = fake_repo.load_line_items(run_id)
chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
final_regular = chen_items[0].hours_regular
assert final_regular == Decimal("40"), ("KNOWN EDGE ... If this test starts failing because "
    "hours_regular now correctly resolves to 30, the ... gap has been fixed -- update or retire this test ...")
```
Pitfall #10: rewrite to assert DESIRED behavior (`== Decimal("30")`), rename, rewrite the module docstring (`:14-46`) — keep the scenario identical. Style model: the sibling CX-03 test (`:322+`) which asserts desired behavior on paid VALUES.

---

### `tests/test_alias_write.py` — update to nested shape + real resolution

**Analog: the faked-state pattern being retired** (`:720-792`) — these tests monkeypatch `load_run` to return hand-built pre/post reconciliation dicts. Keep their fixture data shapes (reconciliation dicts with `submitted_name`/`matched_employee_id`/`source`/`resolved`) but update candidate values to `{token: {"suggested": ..., "bound": ...}}`, and per D-11-17 at least the full-loop test must exercise REAL `reconcile_names` resolution, not faked post-state.

---

### New test modules (all unguarded — no module-level DATABASE_URL skip; warning restated at `test_multiround_context_edge.py:1-12`)

| New Module | Copy From | What to Copy |
|------------|-----------|--------------|
| `tests/test_clarify_rounds.py` | `tests/test_atomic_persist.py:170` (crash-injection: monkeypatch a repo fn to raise mid-path, assert run not advanced / round not behind sent-row count) and `:234-298` (AST source-order guard: parse `_clarify`, assert increment+`set_status` inside one `with conn.transaction()` and status is LAST) | Both idioms verbatim — they are this repo's proof style for D-9-02 ordering |
| `tests/test_needs_operator.py` | `tests/test_stuck_run_recovery.py:68-93` (scope-pin: assert the executed SQL's scope param equals the exact list AND asserts parked statuses absent) + `tests/test_status_drift.py` (auto-forces enum/CHECK parity) + `tests/test_dashboard.py` (route/badge rendering) | Add explicit `needs_operator`-excluded assertions to sweep scope, retrigger `stale_statuses`, `IN_FLIGHT_STATUSES`, D-11-05 scope (CONTEXT: "must be added to the exclusion tests") |
| `tests/test_combined_context.py` | pure-function string tests; hermetic module conventions of `test_multiround_context_edge.py` | Exact-string assertions on the code-owned anchor + round-ordered accumulation (D-11-10 is string-for-string testable by design) |
| `tests/test_alias_full_loop.py` | `test_multiround_context_edge.py` end-to-end drive: seeds `fake_repo` rows, drives real `resume_pipeline` with `mock_llm`, asserts persisted VALUES (`:295-313`) | The D-11-17 stops-asking loop: nickname → capture → suggest persist → confirming reply → real bind → approve (`_deliver` + real `_write_aliases_if_safe`) → `known_aliases` written → second submission resolves stored-alias with NO clarification |
| `tests/test_reply_redelivery.py` | `tests/test_ingest.py:65-75` (TestClient + fake_repo + ALLOW_UNSIGNED_FIXTURES fixture) and `:133`, `:256` (duplicate-delivery matrix tests) | POST the same webhook payload twice; assert unconsumed→re-schedule, consumed→no-op, and CAS collapses double-schedules |

## Shared Patterns

### Status transitions — two sanctioned writers only (D-12)
**Source:** `app/db/repo.py:405-447` (`set_status` uncontended, `claim_status` CAS at every contended gate)
**Apply to:** escalation write (`set_status(NEEDS_OPERATOR)` inside a finalize txn, status-advance-LAST), operator resume (`claim_status(NEEDS_OPERATOR, EXTRACTING)`), consumed-marker gating, WR-04/D-11-05 double-schedule safety. Never a raw UPDATE on status.

### Atomic-unit shape — no LLM/provider call inside a transaction; status-advance last (D-9-01/02)
**Source:** `orchestrator.py:1175-1178` (and its twins `:1033-1037`, `:1154-1158`)
**Apply to:** all three `_clarify` finalize paths (round increment slots before `set_status`), the escalation write, the retrigger clear (commit before `_run_pipeline` is scheduled).

### Post-commit background scheduling
**Source:** `main.py:453-454` (comment: "Everything below is post-commit") + `:549-550` (`background_tasks.add_task(_resume_pipeline, run_id, reply)`)
**Apply to:** WR-04 duplicate re-schedule, D-11-05 runs-list re-schedule, operator-resume dispatch. Never schedule inside the ingest transaction.

### PII-safe logging — exception TYPE only, counts not names
**Source:** `orchestrator.py:735-743` (`reason = type(exc).__name__`), `suggest.py:82-89` (counts only, no exc_info)
**Apply to:** every new log line (escalation, bind/skip reasons, redelivery, stranded-reply sweep). run_id + counts, never token+roster-name together.

### Swallow-on-unavailable dashboard resilience
**Source:** `main.py:1073-1084` (try/except-debug around sweep and load_all_runs)
**Apply to:** the D-11-05 stranded-unconsumed query on runs-list load — a recovery-sweep failure must never 500 the dashboard.

### Deliberately-divergent scope lists, each pinned by a test
**Source:** `main.py:766-782` (retrigger docstring: "Do NOT 'fix' this into parity"), `repo.py:450-456`, `conftest.py:247-250`, `tests/test_stuck_run_recovery.py:68-93`
**Apply to:** `needs_operator` joins NO existing scope; D-11-05's auto-resume scope is a new fourth list with its own pin test.

## No Analog Found

None — every file has a direct in-repo analog. Two items are *partial* precedents worth flagging to the planner:

| Item | Nearest Precedent | Gap |
|------|-------------------|-----|
| Operator-resume pipeline entry (`needs_operator → EXTRACTING` without a new inbound reply) | `resume_pipeline` (`orchestrator.py:227+`) | No existing path resumes without a `reply` argument. RESEARCH Open Question #1 recommends generalizing `resume_pipeline` (from_status param, absent current-reply section) over a parallel `_operator_resume` — decide at plan time |
| Per-run operator override in name resolution | `reconcile_names` (exact/stored-alias only) | No override mechanism exists. RESEARCH Open Question #2 recommends a new optional `overrides` param (wins before exact/alias, tagged `source: "operator"`) + bound-candidate write when the remember-checkbox is ON |

## Metadata

**Analog search scope:** `app/` (db, models, pipeline, templates, main), `tests/` — all touch points pre-verified by 11-RESEARCH.md (2026-07-05) and re-read from live source this session
**Files scanned:** 20 (10 modified targets + 10 analog/test-pattern sources)
**Pattern extraction date:** 2026-07-05
**Key upstream constraints inherited verbatim:** D-9-01/02 (txn shapes), D-12 (status writers), D-13b/c (error isolation, send lifecycle), CLAR-04 (true-duplicate suppression), 7.5 four-outcome machine (`is_round_2` untouched — Pitfall #12), Phase 7.5 lesson (assert paid VALUES, not labels)
