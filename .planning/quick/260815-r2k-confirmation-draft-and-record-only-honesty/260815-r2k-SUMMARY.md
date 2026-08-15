---
phase: quick-260815-r2k
plan: 01
subsystem: confirmation-drafting, operator-console
tags: [compose_email, llm-prompts, run-detail, hitl, record-only, demo-deliverability, testing]

requires:
  - phase: quick-260814-q0y
    provides: NOTICE_LABELS / _operator_notice.html notice mechanism, callout badge vocabulary on run_detail.html
provides:
  - app/llm/prompts/confirm.py — the confirmation-drafting system prompt, moved out of compose_email.py and given the same plain-text/no-subject/no-signature format guard clarify.py already had
  - app/pipeline/compose_email._strip_format_violations — deterministic post-processing that strips a Subject: line and any [bracket] placeholder from a drafted confirmation body, unconditionally
  - app/routes/runs.run_detail now threads repo.get_record_only_flag(run_id) into the template context as `record_only` (one read per page load)
  - app/templates/run_detail.html — outbound messages on a record_only run get a "recorded, not sent" badge plus a plain-language callout
affects: [compose_email, run-detail, demo]

tech-stack:
  added: []
  patterns:
    - "A drafted free-text email body gets a deterministic post-processing floor (strip-then-fallback), not just a prompt instruction — the prompt reduces frequency, the code guarantees the invariant"
    - "Per-page best-effort flag reads (try/except → safe default) threaded into the template context once, matching every other best-effort load already on run_detail"

key-files:
  created:
    - app/llm/prompts/confirm.py
  modified:
    - app/pipeline/compose_email.py
    - app/routes/runs.py
    - app/templates/run_detail.html
    - tests/test_compose_confirmation.py
    - tests/test_dashboard.py

key-decisions:
  - "T1: chose the deterministic-strip design over a reject-and-refallback design. The prompt now also asks the model not to include a subject line or sign-off, but the guarantee that matters (a placeholder must be impossible) comes from _strip_format_violations regex-stripping any Subject: line and any [bracket] token from the returned body before it is ever sent, with a fallback to the template floor only if stripping empties the body entirely."
  - "T1: moved the confirmation prompt into app/llm/prompts/confirm.py alongside clarify.py (plan's judgement call, taken) — the diff is mechanical: same messages list, same call site, just relocated + given the format guard."
  - "T1: confirmed _confirmation_template_body (the deterministic floor) was already clean — no Subject: line, no signature placeholder. No change needed there; only the LLM-drafted path had the gap."
  - "T2: did NOT add a new send_state value (locked constraint). record_only is read via the existing repo.get_record_only_flag and threaded through the run_detail context dict once, not queried per message. The label only changes what the UI SAYS about an outbound message, never send_state, the proof-of-delivery guards, or the provider handoff."
  - "T2: reused the existing badge (badge-neutral badge-uppercase) and callout (callout callout-info) vocabulary already on run_detail.html rather than inventing new styling, per the plan's explicit constraint (echoing the q0y sweep's earlier consolidation of exactly this kind of drift)."

requirements-completed: [BUG-13, BUG-14]

metrics:
  duration_minutes: n/a (single continuous session)
  files_changed: 6
  commits: 2

actuals:
  tokens: 3745
  tasks: 2
  commits: 2

status: complete
---

# Quick 260815-r2k: confirmation draft guards + record-only honesty — Summary

Two independent, RED-first fixes, one commit each, tree green after both. Both were found
by a real delivered email, not by the test suite — every existing test mocks the LLM
(BUG-13) or never rendered a message thread through the record_only case (BUG-14).

**One-liner:** the confirmation-drafting prompt now gets the same format guard
`clarify.py` already had, backed by a deterministic strip so a placeholder/subject-line
leak is structurally impossible; a record_only run's outbound messages are now labeled
"recorded, not sent" in the conversation thread instead of looking identical to a real send.

## What landed

### T1 — BUG-13: confirmation drafting prompt had no format guard

- Read `_confirmation_template_body` (`compose_email.py:231`, the deterministic floor)
  first, as directed. **It was already clean** — no `Subject:` line, no signature
  placeholder. No change was needed there; only the LLM-drafted path had the gap.
- Moved the confirmation system prompt out of `compose_email.py` and into
  `app/llm/prompts/confirm.py`, alongside `clarify.py`, giving it the same format
  constraints clarify.py's prompt already enforces: plain text, no subject line, no
  sign-off/signature placeholder, do not invent details beyond what is given.
- Did **not** leave the guarantee to the prompt alone. Added
  `compose_email._strip_format_violations`, applied unconditionally to every drafted
  body before it is returned: strips any line matching `^subject:` (case-insensitive)
  and any `[bracket]`-enclosed token, then `.strip()`s the result. If stripping empties
  the body out entirely (a draft that was ONLY a placeholder sign-off), it falls through
  to the existing templated floor rather than sending a blank confirmation — the
  "a draft failure never strands the run" guarantee from the module docstring now also
  covers "a draft violates the format contract."
- RED test (`tests/test_compose_confirmation.py`): drives `compose_confirmation` through
  a stubbed LLM that ignores the prompt entirely and returns a body carrying both a
  literal `Subject: ...` line and a `[Your Name]` sign-off (the exact shape of the real
  send that triggered BUG-13); asserts neither survives in the result. Failed RED against
  the old inline prompt (no stripping existed), passes GREEN now.

### T2 — BUG-14: a simulated send was indistinguishable from a real one in the UI

- Confirmed the plan's framing before touching anything: this is a visibility gap, not a
  correctness bug. `record_only` is set once at `create_run` and never mutated
  (`set_record_only` has zero callers); `send_state='sent'` is accurate for what the
  record_only branch of `outbound_handoffs.py` actually did (recorded the send
  successfully, never called the provider). Nothing here reads or writes `send_state`,
  the proof-of-delivery guard at `emails.py:426`, `outbound_provider_handoffs`, or any
  Phase 20 at-most-once machinery.
- `app/routes/runs.py`'s `run_detail` route now calls `repo.get_record_only_flag(run_id)`
  once (best-effort, same try/except-degrade-to-safe-default pattern as every other read
  on that route; the safe default here is `False` — never falsely claim a real send was
  only recorded) and threads it into the template context as `record_only`.
- `run_detail.html`: for each outbound message in the conversation thread, when
  `record_only` is true, renders a `badge-neutral badge-uppercase` "recorded, not sent"
  badge next to the existing direction/purpose badges, plus a `callout callout-info`
  paragraph: "This run was created with the in-app composer, so this email was drafted
  and recorded but never sent to the email provider — it never reached a real inbox."
  Inbound messages are unaffected. Reused the page's existing badge/callout classes
  verbatim — no new styling mechanism.
- RED tests (`tests/test_dashboard.py`): one asserts a `record_only=True` run's page
  contains the recorded-not-sent language for its outbound message; a companion negative
  test asserts a normal (`record_only=False`) run's page does NOT contain it. Both failed
  RED against the pre-fix template (the positive test failed; the negative test happened
  to pass vacuously since the label didn't exist anywhere yet), both pass GREEN now.
- One iteration note: the callout paragraph was initially written wrapped across three
  source lines for readability; Jinja does not collapse the embedded newline/indentation,
  so `"drafted and recorded"` as a contiguous substring failed even though the rendered
  page was semantically correct. Rewrote the paragraph on a single source line — matches
  how the page's other one-line callouts (`resolution_superseded`, alias-rationale notes)
  are already written.

## Deviations from Plan

None. Both tasks executed as specified; the one judgement call the plan left open (moving
the confirmation prompt into `app/llm/prompts/`) was taken, and the diff was mechanical as
requested.

## Known Stubs

None.

## Threat Flags

None. No new endpoints, auth paths, or trust-boundary schema changes. T1 only tightens an
existing free-text drafting call's output contract (parses/strips its own return value, no
new external input). T2 only reads an existing boolean flag and changes template copy; no
new query shape, no new write path.

## Final gate (actual numbers)

```
uv run pytest -q       # 1390 passed, 107 skipped, 1 warning  (baseline: 1387 passed / 107 skipped)
uv run ruff check .    # All checks passed!
uv run mypy             # Success: no issues found in 178 source files  (baseline: 177 — app/llm/prompts/confirm.py is new)
git log --oneline e92a9cf..HEAD   # 2 commits, each independently green
```

## Self-Check: PASSED

Verified files exist:
- FOUND: app/llm/prompts/confirm.py
- FOUND: app/pipeline/compose_email.py
- FOUND: app/routes/runs.py
- FOUND: app/templates/run_detail.html
- FOUND: tests/test_compose_confirmation.py
- FOUND: tests/test_dashboard.py

Verified commits exist (git log --oneline --all):
- FOUND: 0fcb2b3 fix(compose_email): guard confirmation drafts against subject/placeholder leakage
- FOUND: ac76d91 fix(runs): label record_only outbound messages as recorded, not sent
