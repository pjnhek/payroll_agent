# PLAN: confirmation draft guards + record-only honesty

Two small, independent fixes. One commit each. Tree green after both.

Both were found by a real delivered email, not by tests — every test mocks the LLM, so the suite
structurally cannot see BUG-13.

---

## T1 — BUG-13: the confirmation drafting prompt has no format guard

**Evidence.** A real confirmation email sent tonight arrived signed `[Your Name]` and carried a
literal `Subject: Payroll Run Approval - Coastal Cleaning Co.` line *inside the body*, on top of the
real RFC subject `Re: Payroll submission`.

**Cause.** `app/pipeline/compose_email.py:299-304` is an inline system prompt:

> "You are a payroll assistant. Write a brief, warm confirmation email telling the client their
> payroll run has been approved. Include the per-employee net pay summary. Keep it professional and
> concise."

It specifies no output format. Compare `app/llm/prompts/clarify.py:22-28`, which does:

> "... Write a brief, warm email (plain text, **no subject line, no signature placeholder**) that
> clearly asks them to confirm exactly the items listed. Do NOT invent details ..."

The lower-stakes email is guarded; the one that goes to a client after money is approved is not.

**Fix.**
1. Add the same format constraints to the confirmation system prompt: plain text, no subject line,
   no signature placeholder, do not invent details.
2. Do NOT leave the sign-off to the model. Give it a deterministic one, or instruct it to end after
   the summary and let the code append a fixed sign-off. A placeholder must be impossible, not
   merely discouraged.
3. Consider moving this prompt into `app/llm/prompts/` alongside `clarify.py` so the two live
   together and the next person sees both. Judgement call; if you move it, keep the diff mechanical.
4. Check `_confirmation_template_body` (`compose_email.py:231`) — the deterministic floor used when
   the LLM fails. Confirm IT does not have the same placeholder/subject problem. If it is already
   clean, say so in the summary; that is the behavior the LLM path should match.

**RED first.** A test asserting a drafted confirmation body contains no `[` + `]` placeholder token
and no line starting with `Subject:`. Drive it through the real `compose_confirmation` with a stubbed
LLM returning a placeholder-laden body, and assert the guard rejects or the prompt forbids it —
whichever the chosen design makes testable. Put it where `uv run pytest -q` runs it.

---

## T2 — BUG-14: a simulated send is indistinguishable from a real one in the UI

**Evidence.** Run `58707a43` (Coastal Cleaning, created via `/demo/compose`) rendered a full
confirmation email in its conversation thread. `send_state='sent'`. Nothing was ever sent — Resend
has no record, `outbound_delivery_attempts` for its snapshot is empty, and there is no
`outbound_provider_handoffs` row. The owner reasonably concluded an email had been sent and went
looking for it in Gmail.

**This is working as designed.** `app/routes/demo.py:232` sets `record_only=True` for
compose-created runs; `demo.py:333` sets `False` for fixture runs. `outbound_handoffs.py:266` takes
the `ProviderHandoffRecordOnly` branch and never calls the provider. `schema.sql:134` documents it.

**DO NOT add a new `send_state` value.** `get_outbound_message_id` (`app/db/repo/emails.py:426`)
filters `send_state='sent'`, so a distinct `'recorded'` state would make composer runs fail the
proof-of-delivery lookup and land `simulate_reply` on its `no_proof` guard — reintroducing the dead
end fixed in `78542f1` on a different path. There is also no correctness exposure to close:
`record_only` is set once at `create_run` and never mutated (`set_record_only` in
`app/db/repo/demo.py:88` has zero callers and is documented as an ad-hoc repair helper), so such a
run cannot cross into a real send.

**Fix — make it visible, not different.** On the run detail page, when the run is `record_only`,
label the outbound messages in the conversation thread as recorded-not-sent, in plain language that
a stranger understands. Something to the effect of: this run was created with the in-app composer,
so the email was drafted and recorded but never handed to the email provider.

Constraints:
- `record_only` is already readable via `repo.get_record_only_flag` (`app/db/repo/demo.py:103`).
  Prefer passing it through the existing run-detail context dict rather than a new query per message.
- Applies to outbound messages only. Inbound is unaffected.
- Keep it consistent with the existing badge/notice vocabulary on that page. Do not invent a fourth
  parallel styling mechanism — this page already had that problem and the sweep just consolidated it.
- Do not touch `send_state`, the proof-of-delivery guards, the provider handoff, or anything in the
  Phase 20 at-most-once path.

**RED first.** A test asserting a `record_only` run's detail page states the email was not actually
sent, and that a non-record-only run's page does not.

---

## Constraints (both tasks)

- uv only: `uv run pytest -q`, `uv run ruff check .`, `uv run mypy`.
- Do not touch `app/pipeline/` money logic, `federal_withholding.py`, `tax_tables_2026.py`,
  `calculate.py`, or `app/queue/`.
- Do not add JS to `ops.html` (`tests/test_ops_route.py:364` asserts no `<script>`).
- Conventional commits, no emojis, no em-dashes, small reviewable diffs.
- Commit locally. Do NOT push, deploy, or touch live Supabase.
- Finish by reporting actual numbers from the full suite, ruff, and mypy.

## Baseline

`e92a9cf`, deployed. Suite at 1387 passed / 107 skipped, ruff clean, mypy clean over 177 files.
