---
quick_id: 260816-ffv
plan: 01
type: execute
autonomous: true
files_modified:
  - app/config.py
  - render.yaml
  - app/routes/demo.py
  - app/routes/dashboard.py
  - app/db/repo/demo.py
  - app/routes/operator_feedback.py
  - scripts/demo_reset.py
  - tests/test_demo_landing.py
  - tests/test_dashboard.py
must_haves:
  truths:
    - "POST /demo/bind never binds an empty or whitespace-only operator email; it redirects to /?notice=demo_operator_unset instead, and repo.bind_demo_business is never called in that case."
    - "find_business_by_sender('') returns None (no accidental empty-string match against a demo_sender_bindings row)."
    - "The operator email is resolved at call time from Settings (resolve_operator_email()), not frozen at import time, so tests can monkeypatch it via the established setenv + get_settings.cache_clear() idiom."
    - "No file under app/, tests/, or scripts/ contains the literal string 'pjnhek@gmail.com' or the retired env var name 'DEMO_CONTACT_EMAIL'."
    - "scripts/demo_reset.py and the FastAPI app both key off the same env var name, DEMO_OPERATOR_EMAIL."
    - "Full test suite passes: 1403 passed (1400 baseline + 3 new tests), 107 skipped — same as baseline HEAD c3e1595 plus the new coverage, no unexplained deltas."
  artifacts:
    - "app/config.py (new demo_operator_email str Settings field, empty default)"
    - app/routes/demo.py (resolve_operator_email() function; DEMO_OPERATOR_EMAIL constant deleted; demo_bind guard)
    - app/routes/dashboard.py (imports and calls resolve_operator_email(); dead demo_operator_email template key removed)
    - app/db/repo/demo.py (bind_demo_business docstring no longer claims a hardcoded constant)
    - app/routes/operator_feedback.py (NOTICE_LABELS gains demo_operator_unset)
    - scripts/demo_reset.py (_rearm_demo_identity reads DEMO_OPERATOR_EMAIL)
    - render.yaml (new DEMO_OPERATOR_EMAIL sync:false entry; DEMO_OUTBOUND_TO comment updated)
    - tests/test_demo_landing.py (3 new tests; 6 literal fixes)
    - tests/test_dashboard.py (1 literal fix)
  key_links:
    - "demo_bind() guard -> resolve_operator_email() -> get_settings().demo_operator_email -> DEMO_OPERATOR_EMAIL env var"
    - "dashboard.py landing() armed-binding lookup -> resolve_operator_email() (same accessor, second call site)"
    - "scripts/demo_reset.py _rearm_demo_identity -> os.environ['DEMO_OPERATOR_EMAIL'] (same env var name, independent read path — this script never imports app.config)"
---

<objective>
`app/routes/demo.py:72` hardcodes `DEMO_OPERATOR_EMAIL = "pjnhek@gmail.com"` in a public
portfolio repo. This is a hygiene task, not a security fix (the human approval gate carries
the safety weight) — but the constant is not decorative: it is one of exactly four senders
`find_business_by_sender` will accept mail from, and `POST /demo/bind` writes it into
`demo_sender_bindings.operator_email`.

Make the address config-driven (`DEMO_OPERATOR_EMAIL` env var, empty production-safe
default), resolve it at call time (not import time, so tests can monkeypatch it — the
existing `DEMO_OPERATOR_EMAIL` constant is unreachable from a test because
`dashboard.py` imports its own frozen copy at import time), refuse `POST /demo/bind`
outright when it is unset or whitespace-only rather than ever binding an empty string,
unify the parallel `scripts/demo_reset.py` env var onto the same name, and remove every
`pjnhek@gmail.com` literal from `app/`, `tests/`, and `scripts/` (git history is left
alone — do not rewrite it).

Purpose: stop shipping a personal email address in public source, without weakening or
reinterpreting any of the deterministic, code-gated access-control behavior the rest of
the project is built around.

Output: `app/config.py` gains `demo_operator_email`; `app/routes/demo.py` gains
`resolve_operator_email()` and a refusal guard in `demo_bind`; `app/routes/dashboard.py`
and `app/db/repo/demo.py` are updated to match; `app/routes/operator_feedback.py` gains
one new notice code; `scripts/demo_reset.py` reads the same env var name; `render.yaml`
gets a `sync: false` entry; every hardcoded test literal is replaced with a fixture
placeholder or a monkeypatched setting; a `.env.example` manual-paste snippet and a raw
RED-proof pytest transcript land in `260816-ffv-SUMMARY.md` for the user.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
This task's full design (locked decisions D1-D9) was already reconnoitered and decided by
the orchestrator this session — do not re-litigate it, only implement it. All decisions
below have been independently re-verified against live source by the planner (see the
"Verified facts" note per task); none were found false.

@app/config.py
@app/routes/demo.py
@app/routes/dashboard.py
@app/db/repo/demo.py
@app/db/repo/runs.py
@app/routes/operator_feedback.py
@app/email/routing.py
@scripts/demo_reset.py
@tests/test_demo_landing.py
@tests/test_dashboard.py
@tests/test_outbound_routing.py
@render.yaml

**Baseline (verified live, HEAD c3e1595):** `uv run pytest -q` -> `1400 passed, 107
skipped`. `uv run ruff check app/ tests/ scripts/` -> `All checks passed!`.

**The pattern to mirror (D2):** `app/email/routing.py::resolve_outbound_recipient()` and
its test file `tests/test_outbound_routing.py` are the exact precedent for both the new
accessor function's shape and the exact `get_settings.cache_clear()` +
`monkeypatch.setenv(...)` idiom every settings-dependent test below must use. This
codebase has no other reusable "settings env fixture" to call instead — grepping
`tests/conftest.py` confirms the only reusable piece is the autouse
`_stub_database_url_when_absent` fixture, which already clears the `get_settings` cache
before AND after every test unconditionally; per-test code only needs to clear again +
`monkeypatch.setenv`/`delenv`, exactly as `test_outbound_routing.py` does, with no
teardown cache-clear of its own required.

**Ordering constraint discovered during planning (read before starting Task 3):** in
`demo_bind`, the pre-existing `if business_name not in SEED_CONTACTS: return
notice_redirect("/", "demo_unknown_business")` check MUST stay first and MUST NOT be
reordered. `test_bind_route_rejects_unknown_business_with_notice` (existing, unmodified by
this plan) posts `business_name="Unknown Corp"` with no operator email configured
(default empty) and asserts the redirect is `demo_unknown_business`, not
`demo_operator_unset`. If the new operator-email guard ran before the business-name
check, that existing test would break. The new guard goes second, immediately before the
`repo.bind_demo_business(...)` call.
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add the demo_operator_email config field</name>
  <files>app/config.py, render.yaml</files>
  <action>
    In `app/config.py`, insert a new field immediately after the `demo_outbound_to: str =
    ""  # DEMO_OUTBOUND_TO env var` line (currently line 82), before the blank line that
    precedes the "── Durable job queue ──" section comment. Add a WHY comment in the same
    verbose house style as the neighbouring `demo_outbound_to` comment block, then the
    field itself:

    Comment content (wrap each line to stay well under the file's existing line length):
    "DEMO OPERATOR EMAIL: the INBOUND leg of the demo's Path-2 real-email routing —
    POST /demo/bind writes this address into demo_sender_bindings.operator_email so an
    inbound sender matching it resolves to the bound business
    (app/db/repo/runs.py::find_business_by_sender). DEMO_OUTBOUND_TO above is the
    OUTBOUND leg (where client replies get redirected); this is the opposite direction.
    Empty default is the production-safe value: unset, /demo/bind refuses rather than
    binding an empty string, which would otherwise let a sender with from_addr="" match a
    demo_sender_bindings row — see app/routes/demo.py::resolve_operator_email()."

    Field: `demo_operator_email: str = ""  # DEMO_OPERATOR_EMAIL env var`

    In `render.yaml`:
    1. Update the existing comment block directly above `- key: DEMO_OUTBOUND_TO`
       (currently lines 67-79). It currently reads "...Should hold the same address as
       DEMO_OPERATOR_EMAIL (app/routes/demo.py) — that constant is the INBOUND leg
       (Path-2 sender binding); this is the OUTBOUND leg." `DEMO_OPERATOR_EMAIL` is about
       to stop being a constant — change "app/routes/demo.py) — that constant is the
       INBOUND leg" to "see app/config.py) — that setting is the INBOUND leg", leaving
       every other word of that comment block unchanged.
    2. Add a new envVar block for `DEMO_OPERATOR_EMAIL` directly after the
       `DEMO_OUTBOUND_TO` block (i.e. after its `sync: false` line) and before the
       "── Durable job queue" section comment, mirroring the DEMO_OUTBOUND_TO block's
       comment style:
       "DEMO OPERATOR EMAIL: the INBOUND leg of Path-2 demo routing (POST /demo/bind
       writes this address into demo_sender_bindings so inbound mail from this sender
       routes to the bound business). DEMO_OUTBOUND_TO above is the OUTBOUND leg. sync:
       false, not a committed value, for the same personal-address reason as
       DEMO_OUTBOUND_TO. Leaving it unset means POST /demo/bind refuses rather than
       binding an empty operator address — the production-safe default (see
       app/config.py). Must be set in the Render dashboard for the deployed demo's
       /demo/bind route to work."
       Entry: `- key: DEMO_OPERATOR_EMAIL` / `  sync: false` — never a `value:` line (a
       personal mailbox does not belong in version control).
    Do not touch the existing `DEMO_OUTBOUND_TO` entry's `sync: false` line itself, and
    do not touch any other envVar block.
  </action>
  <verify>
    <automated>uv run python -c "from app.config import Settings; assert 'demo_operator_email' in Settings.model_fields; f = Settings.model_fields['demo_operator_email']; assert f.default == ''; print('OK')"</automated>
  </verify>
  <verify>
    <automated>grep -A1 "key: DEMO_OPERATOR_EMAIL" render.yaml | grep -q "sync: false" && echo OK</automated>
  </verify>
  <verify>
    <automated>uv run ruff check app/config.py</automated>
  </verify>
  <done>
    Settings has a `demo_operator_email: str = ""` field with a WHY comment; render.yaml
    has one new `DEMO_OPERATOR_EMAIL` entry with `sync: false` (no `value:`); the
    DEMO_OUTBOUND_TO comment no longer calls DEMO_OPERATOR_EMAIL a "constant"; ruff
    clean; commit created with message `feat(config): add demo_operator_email setting`.
  </done>
</task>

<task type="auto">
  <name>Task 2: Replace the DEMO_OPERATOR_EMAIL constant with a call-time accessor</name>
  <files>app/routes/demo.py, app/routes/dashboard.py, app/db/repo/demo.py</files>
  <action>
    This is a DELIBERATE deviation from "keep the public name so call sites don't churn":
    a module-level `DEMO_OPERATOR_EMAIL = get_settings().demo_operator_email` would freeze
    at import time AND be un-monkeypatchable, because `app/routes/dashboard.py:12`
    currently does `from app.routes.demo import ... DEMO_OPERATOR_EMAIL ...`, binding its
    OWN copy at import time — `monkeypatch.setenv` + `get_settings.cache_clear()` could
    never reach that frozen copy. Do not "fix" this back to a constant.

    In `app/routes/demo.py`:
    1. Add `from app.config import get_settings` to the imports (alphabetically before
       `from app.db import repo`; run ruff --fix at the end to confirm exact ordering).
    2. Delete the three lines currently at 70-72 (the "# Hardcoded operator email for
       Path-2 demo binding..." comment and `DEMO_OPERATOR_EMAIL = "pjnhek@gmail.com"`).
       In their place, in the same "Demo routing constants" section, define:
       `def resolve_operator_email() -> str:` returning
       `get_settings().demo_operator_email.strip()`, with this exact docstring intent
       (mirroring `app/email/routing.py::resolve_outbound_recipient`'s docstring):
       "Return the configured demo operator email, or "" if unset. A whitespace-only
       DEMO_OPERATOR_EMAIL is treated as unset (mirrors
       app/email/routing.py::resolve_outbound_recipient): a stray env var containing only
       spaces must not silently arm a binding for an effectively-empty operator address."
    3. Update the module docstring (currently lines 1-6): remove `DEMO_OPERATOR_EMAIL, `
       from the list of public constant names (it is no longer a constant), and add one
       sentence noting `resolve_operator_email()` resolves the configured operator
       address at call time.
    4. In `demo_bind`'s docstring (currently ~144-153), the SECURITY paragraph says
       "operator_email is the hardcoded DEMO_OPERATOR_EMAIL constant — accepting either
       from the form would let any caller bind an arbitrary address...". Change only the
       "is the hardcoded DEMO_OPERATOR_EMAIL constant" clause to "is resolved from the
       configured DEMO_OPERATOR_EMAIL setting via resolve_operator_email(), never taken
       from the form". Keep every other word of that SECURITY paragraph, including the
       "accepting either from the form would let any caller..." consequence sentence,
       unchanged.
    5. Change the call at (currently) line 157 from
       `repo.bind_demo_business(business_name, DEMO_OPERATOR_EMAIL, SEED_BUSINESS_IDS)`
       to `repo.bind_demo_business(business_name, resolve_operator_email(),
       SEED_BUSINESS_IDS)`. (Task 3 will restructure this further to add the refusal
       guard — do not add that guard here, this task is the accessor swap only.)

    In `app/routes/dashboard.py`:
    1. Change the import at line 12 from
       `from app.routes.demo import DEMO_FIXTURES, DEMO_OPERATOR_EMAIL, SEED_BUSINESS_IDS, SEED_CONTACTS`
       to import `DEMO_FIXTURES, SEED_BUSINESS_IDS, SEED_CONTACTS, resolve_operator_email`
       instead (drop the constant, add the function).
    2. Change (currently) line 114 from
       `armed_business_id = repo.get_demo_binding(DEMO_OPERATOR_EMAIL)` to
       `armed_business_id = repo.get_demo_binding(resolve_operator_email())`.
    3. First re-run `git grep -rn "demo_operator_email" -- app/templates/` yourself and
       confirm it returns nothing (planner already verified this — zero hits — but
       re-verify before deleting, per house discipline: never delete on someone else's
       stale claim). Then DELETE (currently) line 139,
       `"demo_operator_email": DEMO_OPERATOR_EMAIL,`, from the template context dict
       entirely (dead — no template consumes it).

    In `app/db/repo/demo.py`, in `bind_demo_business`'s docstring (currently lines
    39-53): line 43-45 says "...is the hardcoded DEMO_OPERATOR_EMAIL constant from the
    call site, never user-supplied: this table feeds sender→business routing, so a
    user-supplied value here would let an arbitrary sender bind themselves to a
    business." — change only "is the hardcoded DEMO_OPERATOR_EMAIL constant from the call
    site" to "is the configured operator address, resolved via
    app.routes.demo.resolve_operator_email()", keeping the rest of that sentence (the
    SECURITY point) unchanged. Line 49, "operator_email: the hardcoded operator email
    (DEMO_OPERATOR_EMAIL)." — change to "operator_email: the configured operator email
    (resolved via app.routes.demo.resolve_operator_email())."

    Finally run `uv run ruff check --fix app/routes/demo.py app/routes/dashboard.py
    app/db/repo/demo.py` to normalize import ordering, then confirm a plain (non-fix)
    `ruff check` on the same three files is clean.

    Do NOT run the test suite (full or file-level) after this task. `tests/
    test_demo_landing.py` still has 6 literal-string assertions comparing against
    "pjnhek@gmail.com" (fixed in Task 5) that will now fail because
    `resolve_operator_email()` returns "" by default with no env var set — this is
    EXPECTED and tracked, not a bug to chase down here. Use only the scoped checks below.
  </action>
  <verify>
    <automated>uv run python -c "from app.routes import demo, dashboard; assert hasattr(demo, 'resolve_operator_email'); assert not hasattr(demo, 'DEMO_OPERATOR_EMAIL'); assert hasattr(dashboard, 'resolve_operator_email'); print('OK')"</automated>
  </verify>
  <verify>
    <automated>git grep -rn "demo_operator_email" -- app/templates/ ; test $? -eq 1 && echo "OK: no template references"</automated>
  </verify>
  <verify>
    <automated>uv run ruff check app/routes/demo.py app/routes/dashboard.py app/db/repo/demo.py</automated>
  </verify>
  <done>
    `DEMO_OPERATOR_EMAIL` no longer exists as a module attribute anywhere in `app/`;
    `resolve_operator_email()` exists in `app/routes/demo.py` and is used at both call
    sites (demo_bind, dashboard.py's landing()); the dead `demo_operator_email` template
    context key is gone; all three touched docstrings describe a "configured" address,
    not a "hardcoded constant"; ruff clean; commit created with message
    `refactor(demo): resolve the operator email from config, not a constant`.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Refuse /demo/bind when no operator email is configured</name>
  <files>app/routes/operator_feedback.py, app/routes/demo.py, tests/test_demo_landing.py</files>
  <behavior>
    - Empty DEMO_OPERATOR_EMAIL (unset) + POST /demo/bind with a valid business_name ->
      303 to /?notice=demo_operator_unset, repo.bind_demo_business is NEVER called.
    - Whitespace-only DEMO_OPERATOR_EMAIL ("   ") -> same refusal (proves .strip() makes
      it count as unset, not just falsy-empty-string).
    - find_business_by_sender("") -> None (the access-control claim, proven directly
      against the repo function with a FakeConnection — this does not require any new
      production code, it proves the existing lookup already returns None for an empty
      sender as long as no demo_sender_bindings row with operator_email='' ever exists,
      which the two behaviors above now guarantee).
    - business_name off the allowlist is still reported as demo_unknown_business, not
      demo_operator_unset, even when the operator email is also unset (ordering
      constraint — proven by the existing, unmodified
      test_bind_route_rejects_unknown_business_with_notice, which this task must not
      break).
  </behavior>
  <action>
    Step 1 — infra (no behavior change yet): in `app/routes/operator_feedback.py`, add
    one new entry to `NOTICE_LABELS`, alongside (not replacing) the other `demo_*`
    entries — insert it directly after the `"demo_queue_error": (...)` entry, before the
    dict's closing `}`:
    `"demo_operator_unset": ("No operator address is configured for this demo, so "
    "nothing was bound. Set DEMO_OPERATOR_EMAIL and try again.")` — wrap it across two
    parenthesized string literals like its neighbours.

    Step 2 — write the RED tests first, in `tests/test_demo_landing.py`. Insert two new
    test functions directly after the existing (unmodified)
    `test_bind_route_rejects_unknown_business_with_notice` (ends ~line 1438), before
    `test_run_detail_thread_includes_source_inbound`:

    `test_bind_route_refuses_when_operator_email_unset(monkeypatch)` — mirror
    `test_bind_route_rejects_unknown_business_with_notice`'s structure exactly (same
    `bind_calls` spy pattern on `repo_mod.bind_demo_business`, same `TestClient(
    fastapi_app, raise_server_exceptions=False)` usage, `follow_redirects=False`). Before
    constructing the TestClient: `from app.config import get_settings;
    get_settings.cache_clear(); monkeypatch.delenv("DEMO_OPERATOR_EMAIL",
    raising=False)`. POST to `/demo/bind` with `business_name="Metro Deli Group"` (a
    VALID SEED_CONTACTS name, so this proves the operator-email guard fires
    independently of the business-name check). Assert `resp.status_code in (302, 303)`,
    `resp.headers.get("location", "") == "/?notice=demo_operator_unset"`, and
    `bind_calls == []`.

    `test_bind_route_refuses_when_operator_email_whitespace_only(monkeypatch)` —
    identical, except `monkeypatch.setenv("DEMO_OPERATOR_EMAIL", "   ")` instead of
    `delenv`.

    Insert a third new test directly after the existing
    `test_find_business_by_sender_primary_path_unchanged` (ends ~line 244), before the
    "create_run record_only parameter tests" section comment:
    `test_find_business_by_sender_empty_string_returns_none(fake_conn)` — mirror
    `test_find_business_by_sender_additive_binding_check`'s shape: script two `None`
    fetches (`fake_conn.script_fetchone(None)` twice — the primary contact_email lookup,
    then the additive demo_sender_bindings lookup), call
    `find_business_by_sender("", conn=fake_conn)`, assert the result `is None`.

    Step 3 — RED PROOF (mandatory, do this before writing the guard): run
    `uv run pytest tests/test_demo_landing.py -k "refuses_when_operator_email" -v` and
    confirm BOTH new tests FAIL (the guard does not exist yet, so bind_demo_business gets
    called and the redirect goes to `/?bound=1`, not the notice URL). Copy the complete,
    unedited terminal output of this failing run — you will paste it verbatim into
    SUMMARY.md in Task 6. Do not paraphrase, summarize, or clean it up; if it does not
    actually fail here, stop and re-examine your test code before proceeding.

    Step 4 — GREEN: in `app/routes/demo.py`'s `demo_bind`, restructure the body. Keep the
    existing `if business_name not in SEED_CONTACTS: return notice_redirect("/",
    "demo_unknown_business")` check FIRST, unchanged. Immediately after it, add:
    `operator_email = resolve_operator_email()` then
    `if not operator_email: return notice_redirect("/", "demo_operator_unset")` — both
    BEFORE the `repo.bind_demo_business(...)` call. Change that call's second argument
    from the inline `resolve_operator_email()` (added in Task 2) to the new
    `operator_email` local variable, so the setting is only read once per request.

    Step 5 — re-run the same targeted selection and confirm both PASS now:
    `uv run pytest tests/test_demo_landing.py -k "refuses_when_operator_email or find_business_by_sender_empty_string" -v`.

    Step 6 — confirm the existing AST drift pin and label-hygiene test already cover the
    new call site and label with no changes needed on your part:
    `uv run pytest tests/test_operator_feedback.py -v` (all tests in that file, including
    `test_every_static_notice_redirect_call_site_uses_a_labeled_code` and
    `test_every_label_is_non_empty_and_markup_free`, must pass).

    Step 7: `uv run ruff check --fix app/routes/operator_feedback.py app/routes/demo.py
    tests/test_demo_landing.py`, then confirm a plain `ruff check` on the same three
    files is clean.
  </action>
  <verify>
    <automated>uv run pytest tests/test_demo_landing.py -k "refuses_when_operator_email or find_business_by_sender_empty_string" -v</automated>
  </verify>
  <verify>
    <automated>uv run pytest tests/test_operator_feedback.py -q</automated>
  </verify>
  <verify>
    <automated>uv run ruff check app/routes/operator_feedback.py app/routes/demo.py tests/test_demo_landing.py</automated>
  </verify>
  <done>
    NOTICE_LABELS has one new `demo_operator_unset` entry; `demo_bind` refuses (redirects
    to `/?notice=demo_operator_unset`, never calls `bind_demo_business`) when the
    operator email is unset or whitespace-only, while still reporting
    `demo_unknown_business` first when the business_name itself is off the allowlist;
    `find_business_by_sender("")` returns None; 3 new tests exist and pass; the real RED
    (pre-guard) pytest output was captured verbatim for SUMMARY.md; ruff clean; commit
    created with message
    `fix(demo): refuse /demo/bind when no operator email is configured`.
  </done>
</task>

<task type="auto">
  <name>Task 4: Unify scripts/demo_reset.py onto DEMO_OPERATOR_EMAIL</name>
  <files>scripts/demo_reset.py, tests/test_dashboard.py</files>
  <action>
    Verified fact: `scripts/demo_reset.py` never imports `app.config` at module level or
    anywhere — its only `app.*` imports (`app.db.repo`, `app.db.seed`,
    `app.db.supabase`) are deferred, function-local imports, and the sibling
    `DEMO_BUSINESS_NAME` env var it reads in the same function uses a plain
    `os.environ.get(...)` call with no Settings model involved at all. Introducing
    `from app.config import get_settings` here — reading operator_email through Settings
    while business_name stays a raw env read in the very same function — would be a new,
    surprising, inconsistent pattern for this one field alone. Per the task's own
    fallback instruction ("choose the least-surprising option... but the env var name
    must end up DEMO_OPERATOR_EMAIL either way"), do the minimal rename instead:

    In `_rearm_demo_identity` (currently line 79), change
    `operator_email = os.environ.get("DEMO_CONTACT_EMAIL", "").strip()` to
    `operator_email = os.environ.get("DEMO_OPERATOR_EMAIL", "").strip()` — the read
    mechanism is unchanged, only the env var key string changes.

    Update the function's docstring (currently line 71, "Uses DEMO_CONTACT_EMAIL
    (operator_email) and DEMO_BUSINESS_NAME...") and the warning print string (currently
    line 85, "WARNING: DEMO_CONTACT_EMAIL / DEMO_BUSINESS_NAME not set or invalid...") to
    say `DEMO_OPERATOR_EMAIL` instead of `DEMO_CONTACT_EMAIL` in both places — no other
    wording changes.

    In `tests/test_dashboard.py`, in the `test_env` dict inside
    `test_demo_reset_rearming_writes_demo_sender_bindings_not_contact_email` (currently
    line 2242), change the key `"DEMO_CONTACT_EMAIL"` to `"DEMO_OPERATOR_EMAIL"` and its
    value from `"pjnhek@gmail.com"` to `"operator@example.test"` (a fixture placeholder —
    this test only needs a non-empty address, never a real one).
  </action>
  <verify>
    <automated>git grep -n "DEMO_CONTACT_EMAIL" -- app/ tests/ scripts/ ; test $? -eq 1 && echo "OK: no remaining references"</automated>
  </verify>
  <verify>
    <automated>uv run pytest tests/test_dashboard.py -k test_demo_reset_rearming_writes_demo_sender_bindings_not_contact_email -v</automated>
  </verify>
  <verify>
    <automated>uv run ruff check scripts/demo_reset.py tests/test_dashboard.py</automated>
  </verify>
  <done>
    `scripts/demo_reset.py` reads `DEMO_OPERATOR_EMAIL` (docstring, warning string, and
    the actual `os.environ.get` call all consistent); `tests/test_dashboard.py`'s
    demo_reset test uses the renamed key and a fixture placeholder value; zero remaining
    `DEMO_CONTACT_EMAIL` references anywhere in `app/`, `tests/`, `scripts/`; targeted
    test green; ruff clean; commit created with message
    `refactor(demo-reset): unify on DEMO_OPERATOR_EMAIL`.
  </done>
</task>

<task type="auto">
  <name>Task 5: Drop the remaining hardcoded operator address from test literals</name>
  <files>tests/test_demo_landing.py</files>
  <action>
    Verified fact: exactly 6 occurrences of the literal `"pjnhek@gmail.com"` remain in
    this file at this point (lines 173, 190, 202, 226, 1361, 1406 — all independently
    re-confirmed against live source during planning).

    Add a module-level constant near the top of the file, directly after the existing
    `from tests.conftest import FakeConnection, patch_get_connection` import line:
    `_TEST_OPERATOR_EMAIL = "operator@example.test"` — this mirrors the `@example.test`
    RFC 2606 placeholder convention this suite already uses elsewhere (e.g.
    `tests/test_queue_drain.py`). Also add `from app.config import get_settings` to this
    file's top-level imports (needed by the two monkeypatch-based fixes below).

    Line 173 (`bind_demo_business("Metro Deli Group", "pjnhek@gmail.com", seed_ids,
    conn=fake_conn)`): replace the literal argument with `_TEST_OPERATOR_EMAIL`.

    Line 190 (`assert "pjnhek@gmail.com" in all_params, ...`): replace the literal with
    `_TEST_OPERATOR_EMAIL` — this asserts the params captured from line 173's call, so
    both must use the same constant.

    Line 202 (`bind_demo_business("Unknown Corp", "pjnhek@gmail.com", seed_ids,
    conn=fake_conn)`): replace the literal argument with `_TEST_OPERATOR_EMAIL`.

    Line 226 (`find_business_by_sender("pjnhek@gmail.com", conn=fake_conn)`): replace
    the literal argument with `_TEST_OPERATOR_EMAIL`.

    In `test_compose_from_addr_is_seed_contact_not_operator` (the negative assertion at
    line 1361, `assert captured_from != "pjnhek@gmail.com"`): this test does not
    currently configure any operator email, which per the task's own instructions would
    make the assertion vacuous once the dead literal is gone. Fix: at the top of the test
    body (it already takes `monkeypatch`), add `get_settings.cache_clear()` then
    `monkeypatch.setenv("DEMO_OPERATOR_EMAIL", _TEST_OPERATOR_EMAIL)` BEFORE the
    `TestClient(...)` block runs. Change line 1361 to
    `assert captured_from != _TEST_OPERATOR_EMAIL`, keeping the trailing message. This
    makes the test strictly stronger than before: it now proves `/demo/compose`'s
    `from_addr` is never influenced by the operator email even while one is actively
    configured (previously it only proved independence from a dead literal that nothing
    could ever equal).

    In `test_bind_route_writes_demo_sender_bindings_not_contact_email` (the positive
    assertion at line 1406, `assert called_email == "pjnhek@gmail.com", "operator_email
    must be DEMO_OPERATOR_EMAIL"`): at the top of the test body (it already takes
    `monkeypatch`), add `get_settings.cache_clear()` then
    `monkeypatch.setenv("DEMO_OPERATOR_EMAIL", _TEST_OPERATOR_EMAIL)` BEFORE the
    `TestClient(...)` block runs — otherwise, with the empty default, Task 3's guard
    refuses the bind and this test fails for an unrelated reason. Change line 1406 to
    `assert called_email == _TEST_OPERATOR_EMAIL, "operator_email must be the configured
    DEMO_OPERATOR_EMAIL setting"`. The test's existing `assert "bound=1" in location`
    assertion (a few lines above) stays true only because an operator email is now
    configured — leave it as-is, it still holds.

    Run `uv run ruff check --fix tests/test_demo_landing.py`, then confirm a plain
    `ruff check` is clean.
  </action>
  <verify>
    <automated>git grep -n "pjnhek@gmail.com" -- tests/ ; test $? -eq 1 && echo "OK: no remaining literals in tests/"</automated>
  </verify>
  <verify>
    <automated>uv run pytest tests/test_demo_landing.py -v</automated>
  </verify>
  <verify>
    <automated>uv run ruff check tests/test_demo_landing.py</automated>
  </verify>
  <done>
    Zero occurrences of `"pjnhek@gmail.com"` remain in `tests/test_demo_landing.py`; all
    tests in the file pass (this is the first point at which the whole file is green
    again since Task 2); the negative assertion at the old line 1361 still proves
    from_addr never leaks the operator address, now against a real configured value; the
    positive assertion at the old line 1406 proves the CONFIGURED setting (not a stale
    constant) flows through to `bind_demo_business`; ruff clean; commit created with
    message `test(demo): drop the hardcoded operator address from test literals`.
  </done>
</task>

<task type="auto">
  <name>Task 6: Full verification sweep and SUMMARY.md</name>
  <files>none — verification only, plus writing SUMMARY.md (not committed by this task)</files>
  <action>
    Run the complete verification bar and record the results.

    1. `uv run pytest -q` — the summary line MUST read `1403 passed, 107 skipped` (1400
       baseline + the 3 new tests from Task 3; skip count unchanged). Any other number is
       a real regression — stop and investigate, do not edit the expected count to match
       an unexplained result.
    2. `uv run ruff check app/ tests/ scripts/` — must print `All checks passed!`.
    3. Run these three greps and confirm each returns nothing (exit 1, no matching
       lines):
       - `git grep -n "pjnhek@gmail.com" -- app/ tests/ scripts/`
       - `git grep -n "DEMO_CONTACT_EMAIL" -- app/ tests/ scripts/`
       - `git grep -n "DEMO_OPERATOR_EMAIL" -- app/` piped through
         `grep -v '\.py:.*#'` and eyeballed: it will still show config.py's field
         declaration and comment, demo.py's function/docstring/comment references, and
         dashboard.py's/repo/demo.py's docstring references — confirm none of these is a
         `DEMO_OPERATOR_EMAIL = "..."` constant assignment (the constant must be gone,
         only the env-var NAME survives in comments/config/docstrings).
    4. Re-run the consolidated guard proof once more as the final check:
       `uv run pytest tests/test_demo_landing.py -k "refuses_when_operator_email or find_business_by_sender_empty_string" -v`
       — all 3 must pass (green, post-guard, distinct from the RED transcript captured
       in Task 3).
    5. Non-blocking bonus check (this repo's convention is strict-mypy-clean CI; this
       plan's changes are small and typed, so this should be free): run
       `uv run mypy app/config.py app/routes/demo.py app/routes/dashboard.py
       app/db/repo/demo.py scripts/demo_reset.py app/routes/operator_feedback.py` and
       record the result. If it surfaces a real error introduced by this plan's changes,
       fix it. Do not attempt to fix any pre-existing, unrelated mypy finding outside
       this plan's scope.
    6. Write `.planning/quick/260816-ffv-make-the-hardcoded-demo-operator-email-c/260816-ffv-SUMMARY.md`
       containing:
       - A one-line summary of each of the 5 commits made (config field, accessor
         refactor, refusal guard, demo-reset unification, test literal cleanup).
       - A "RED-PROOF" section with the COMPLETE, VERBATIM pytest output captured in
         Task 3 step 3 (the failing run, before the guard existed) — paste exactly as
         printed, do not clean it up or summarize it.
       - The final `uv run pytest -q` summary line and the `uv run ruff check` result.
       - The three grep commands from step 3 above and confirmation each was empty.
       - A clearly marked "MANUAL STEP — paste into your local .env.example" section
         containing exactly these two lines for the user to hand-paste (the executor
         cannot write .env.example directly — a dotenv guard denies Read/Write on
         `.env.*` — do not attempt to work around this):

         `# DEMO OPERATOR EMAIL: inbound leg of Path-2 demo routing (POST /demo/bind`
         `# writes this address into demo_sender_bindings). DEMO_OUTBOUND_TO above is`
         `# the outbound leg. Unset (empty) is the production-safe default: /demo/bind`
         `# refuses rather than binding an empty operator address. See app/config.py.`
         `DEMO_OPERATOR_EMAIL=`

       - A note that the deployed Render service needs `DEMO_OPERATOR_EMAIL` set in the
         Render dashboard's Environment tab before `/demo/bind` will work there — this is
         the intended, honest behavior from D9, not a regression to fix.
       - `status: complete` in the SUMMARY.md frontmatter.

    Do NOT commit SUMMARY.md, STATE.md, or PLAN.md — the orchestrator handles the docs
    commit separately.
  </action>
  <verify>
    <automated>uv run pytest -q 2>&1 | tail -5</automated>
  </verify>
  <verify>
    <automated>uv run ruff check app/ tests/ scripts/</automated>
  </verify>
  <verify>
    <automated>git grep -n "pjnhek@gmail.com" -- app/ tests/ scripts/ ; test $? -eq 1 && git grep -n "DEMO_CONTACT_EMAIL" -- app/ tests/ scripts/ ; test $? -eq 1 && echo "OK: both greps empty"</automated>
  </verify>
  <done>
    Full suite reports 1403 passed / 107 skipped; ruff reports all checks passed; all
    three mandatory greps are empty; the consolidated guard proof passes green;
    SUMMARY.md exists with a verbatim RED-proof transcript, the manual .env.example
    paste block, and the Render-dashboard note; SUMMARY.md is NOT committed by this task.
  </done>
</task>

</tasks>

<verification>
End-to-end check, run in order after all 6 tasks:
1. `git log --oneline -6` shows exactly 5 new commits matching the 5 commit messages
   named in each task's `<done>` (Task 6 makes no commit).
2. `uv run pytest -q` -> `1403 passed, 107 skipped`.
3. `uv run ruff check app/ tests/ scripts/` -> `All checks passed!`.
4. `git grep -n "pjnhek@gmail.com" -- app/ tests/ scripts/` -> empty.
5. `git grep -n "DEMO_CONTACT_EMAIL" -- app/ tests/ scripts/` -> empty.
6. `git grep -n "DEMO_OPERATOR_EMAIL =" -- app/` -> empty (no constant assignment
   survives; only the config field declaration, which reads `demo_operator_email: str =
   ""`, a different identifier, and free-text mentions in comments/docstrings).
7. `260816-ffv-SUMMARY.md` exists and contains a non-empty RED-proof transcript and the
   `.env.example` manual-paste block.
</verification>

<success_criteria>
- The personal address `pjnhek@gmail.com` no longer appears anywhere in `app/`, `tests/`,
  or `scripts/` (git history untouched, as instructed).
- `POST /demo/bind` provably refuses to bind when `DEMO_OPERATOR_EMAIL` is unset or
  whitespace-only, routed through the existing allow-listed notice mechanism (one new
  code, not a bespoke query param).
- `find_business_by_sender("")` provably returns `None`.
- The operator email is resolved at call time via `resolve_operator_email()`, reachable
  by `monkeypatch.setenv` + `get_settings.cache_clear()` in tests — no frozen
  import-time copy remains anywhere (dashboard.py's old dead import in particular).
- `scripts/demo_reset.py` and the FastAPI app agree on one env var name,
  `DEMO_OPERATOR_EMAIL`; `DEMO_CONTACT_EMAIL` is fully retired.
- `render.yaml` documents the new var as `sync: false` (never a committed value).
- Full test suite green at `1403 passed, 107 skipped`; `ruff check` clean.
- A real, verbatim RED pytest transcript (captured before the guard existed) is in
  SUMMARY.md, proving the new test actually exercises the guard rather than trivially
  passing regardless of it.
- The `.env.example` line is handed to the user in SUMMARY.md as a manual paste step
  (the dotenv Read/Write guard is respected, not worked around).
</success_criteria>

<output>
Create `.planning/quick/260816-ffv-make-the-hardcoded-demo-operator-email-c/260816-ffv-SUMMARY.md`
when done (produced by Task 6; frontmatter must include `status: complete`).
</output>
