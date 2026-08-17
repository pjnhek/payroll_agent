r"""Baseline registry for GUARD-01: every `.text` comparison in the test suite,
attributed to the route it exercises, classified presence-or-absence, and tagged
with the layer that will render its guarded content after conversion.

What this registry establishes: for each `ast.Compare` node under `tests/` whose
left operand or any comparator is a `.text` attribute access (e.g.
`response.text`, `caplog.text`, `page.text`), a durable record of exactly where
it lives (file, line, `col_offset`), what its source read at inventory time
(`source_text`), which route produced the value it inspects (`route` — `/runs`,
`/runs/{run_id}`, `/eval`, `/ops`, or `none` for a non-HTTP body such as
`caplog.text`), whether it asserts presence or absence of a substring
(`assertion_class`), and which of the four rendering layers will carry the
guarded content once its page converts (`layer`). `FILE_SCOPE_NOTES` covers
every file under `tests/` whose text contains the substring `.text` at all,
including the ones with zero real `.text` comparisons, each with a written
reason — nothing is silently out of scope.

What this registry does NOT establish: it does not itself prove completeness
(that is `tests/test_inventory_completeness.py`'s job, walking the same AST
shape independently and asserting the discovered set equals this dict's key
set) and it does not decide whether an assertion is safety-critical enough to
carry a falsifying mutation (that is the separate, smaller
`tests/test_safety_mutation_registry.py`, GUARD-02/D-22-11). This module is
inert data plus two small enums — no I/O, no test collection, so it costs
nothing at import time and stays fast under `mypy --strict` and pytest
collection.

Why an AST walk was chosen over a regex scan: a live re-derivation this session
found 17 files under `tests/` containing the substring `.text`
(``grep -rl "\.text" tests/ | wc -l``), but a naive single-line regex
(``assert[^#]*\.text``) matches only 14 of them — the 3-file gap
(`conftest.py`, `test_clarify_round_hours_safety.py`, `test_gateway.py`) is
real `.text` usage a line-anchored regex silently under-counts: a fake response
double's own `self.text = text` attribute assignment, and a `.text` read into
an intermediate `body`/`page` variable that gets compared several lines later
rather than as a literal `response.text` token on the assert line itself. An
AST walk over every `ast.Compare` node, scanning left operand and every
comparator for a `.text` attribute access regardless of how many lines the
statement spans, closes that gap structurally rather than by adding more regex
special-cases.

Every registry entry's `route`, `assertion_class`, and `layer` were classified
by hand against this session's own read of `app/templates/runs_list.html`
(the D-22-12 React mount boundary, lines 64-115) and by tracing each
assertion's own enclosing test function back to its `client.get(...)`/
`client.post(...)` call — never guessed from the assertion's file name or from
a substring inside its own message. `layer=UNCONVERTED` is used for every
route this phase does not convert (`/runs/{run_id}`, `/eval`,
`/runs/{run_id}/status`, `/runs/{run_id}/delivery-review/email`, `/health/*`,
`/webhook/inbound`, and `route="none"` non-HTTP bodies such as `caplog.text`)
per D-22-10 ("classify all in Phase 22, pin and rewrite per slice"); `/ops` and
`/` are `layer=JINJA_SHELL` because they are never converted at all (permanent,
not merely "not yet"). Only `/runs`-attributed entries were split further into
`JINJA_SHELL` (chrome outside the React mount: the `<h1>`, the `?notice=`
banner, the demo form, and whole-page checks like the meta-refresh absence),
`JSON_ISLAND` (content that originates in a `RunListRow`/`RunStatusPoll` DTO
field — a run id, a badge class/label, a failure reason — and will therefore
live inside the `__INITIAL_DATA__` JSON blob after conversion, where the
correct rewritten assertion is a positive exact-shape check against parsed
JSON, not a substring search over `response.text`), and `REACT_DOM` (static
JSX markup with no DTO field behind it, such as the empty-state copy "No
payroll runs yet" — the genuinely vacuous class D-22-09 names by example,
because `TestClient` never executes JavaScript and cannot see it after
conversion).

Baseline counts (files/entries; per-file and per-route/class/layer breakdowns
are derived output printed by `scripts/render_assertion_inventory.py`, never
hand-pinned here, per D-22-06):
"""


from __future__ import annotations

import enum
from dataclasses import dataclass


class AssertionClass(enum.StrEnum):
    """Whether the guarded `.text` comparison asserts a substring IS present
    (`in`) or is NOT present (`not in`). Every comparison operator discovered
    across the suite is one of these two — no `==`/`!=` `.text` comparison
    exists in `tests/` today (re-verified this session)."""

    PRESENCE = "presence"
    ABSENCE = "absence"


class AssertionLayer(enum.StrEnum):
    """The layer that will render the guarded content after its page
    converts. `UNCONVERTED` covers every route this milestone has not yet
    converted (or never converts as HTML markup at all, e.g. a JSON API body
    or a log line) — see the module docstring for the full placement
    rationale."""

    JINJA_SHELL = "jinja_shell"
    JSON_ISLAND = "json_island"
    REACT_DOM = "react_dom"
    UNCONVERTED = "unconverted"


@dataclass(frozen=True)
class AssertionEntry:
    """One classified `.text` comparison, keyed in `ASSERTION_INVENTORY` by
    `{module_stem}:{line}:{col_offset}` — `col_offset` is load-bearing: two
    assertions sharing one physical line (a chained comparison, or two
    `assert`s folded onto one line) get distinct entries because their
    `col_offset` differs."""

    file: str
    line: int
    col_offset: int
    source_text: str
    route: str
    assertion_class: AssertionClass
    layer: AssertionLayer
    replaced_by: str | None = None


FILE_SCOPE_NOTES: dict[str, str] = {
    'tests/conftest.py': (
        'Zero `.text` comparisons: `.text` appears only once (line 3120), as a fake-response'
        " test double's own attribute assignment (`self.text = text`) — never as the left"
        ' operand or a comparator of an `ast.Compare` node anywhere in this file.'
    ),
    'tests/test_clarify_round_hours_safety.py': (
        'Zero `.text` comparisons: the sole `.text` usage (line 491) reads `response.text` into'
        ' an intermediate `body` variable; every assertion in this file then compares `body`,'
        ' never `response.text` directly, so no `ast.Compare` node has a `.text` attribute'
        ' operand.'
    ),
    'tests/test_dashboard.py': (
        "76 `.text` comparisons, the suite's largest cost-center file (v5 PROJECT.md). Spans"
        ' all three converting pages plus two permanently-unconverted support routes: /runs'
        ' (16), /runs/{run_id} (46), /eval (6), /runs/{run_id}/status (1),'
        ' /runs/{run_id}/delivery-review/email (3, via the `email` fixture variable) — every one'
        ' classified individually below, none folded into a zero-affected note.'
    ),
    'tests/test_demo_fixtures.py': (
        '1 `.text` comparison, attributed to /runs: the demo-queue-error rollback notice'
        " (reached via response.headers['location'] -> /runs?notice=demo_queue_error) is"
        ' classified individually below as JINJA_SHELL — the ?notice= channel stays server-side'
        ' per D-22-12.'
    ),
    'tests/test_demo_landing.py': (
        '2 `.text` comparisons, zero affected: both exercise GET / (the landing page — one'
        " directly, one via the compose-rollback notice's response.headers['location'] ->"
        " /?notice=demo_queue_error), which is explicitly out of the v5 milestone's conversion"
        " scope and stays Jinja permanently (PROJECT.md 'Explicitly NOT converted')."
    ),
    'tests/test_durable_ingest.py': (
        "1 `.text` comparison, zero affected: POST /webhook/inbound's bounded 503 JSON error"
        " body ('private diagnostics' not in response.text) — a JSON API response, not a"
        ' converting page; route=/webhook/inbound, layer=UNCONVERTED.'
    ),
    'tests/test_gateway.py': (
        'Zero `.text` comparisons: `.text` appears twice (lines 514, 651) — a fake-response'
        " test double's own attribute assignment (`self.text = text`, same shape as conftest.py)"
        ' and a reference to `email_obj.text` inside an assertion failure MESSAGE string, not as'
        ' a compared operand.'
    ),
    'tests/test_health_queue_alarm.py': (
        '6 `.text` comparisons, zero affected: all six are PII/secret-leak negative controls'
        " over GET /health/queue's JSON error body (route=/health/queue, layer=UNCONVERTED) — a"
        ' JSON API response, not a converting page.'
    ),
    'tests/test_health_schema.py': (
        '2 `.text` comparisons, zero affected: both are PII/secret-leak negative controls over'
        " GET /health/schema's JSON error body (route=/health/schema, layer=UNCONVERTED)."
    ),
    'tests/test_hitl.py': (
        '2 `.text` comparisons, attributed to /runs/{run_id}: both are retrigger-blocked'
        ' explanatory-notice assertions on the run detail page (BUG-6), classified individually'
        ' below as layer=UNCONVERTED (Phase 23 converts /runs/{run_id}).'
    ),
    'tests/test_needs_operator.py': (
        '11 `.text` comparisons: 4 are caplog.text (non-HTTP, route=none, layer=UNCONVERTED —'
        ' log output is never a page), the remaining 7 split across /runs (2, badge label/class'
        ' data fields) and /runs/{run_id} (5, needs-operator badge + resolve-error notice), all'
        ' classified individually below.'
    ),
    'tests/test_ops_route.py': (
        "23 `.text` comparisons, zero affected: every one traces to client.get('/ops') — five"
        " of them assert the presence of a /runs/{run_id} link's HREF TEXT inside the /ops"
        ' response, which is still an /ops-sourced assertion, not a /runs/{run_id} request. /ops'
        ' stays permanently Jinja and script-free (tests/test_ops_route.py:364), so every entry'
        ' here is route=/ops, layer=JINJA_SHELL.'
    ),
    'tests/test_phase20_clarification_review.py': (
        '30 `.text` comparisons, attributed to /runs/{run_id} (24, the 8-branch delivery-'
        ' review-card decision matrix) and /runs/{run_id}/delivery-review/email (6, the frozen'
        ' email/attachment content endpoint) — both UNCONVERTED in this phase; Phase 23 owns'
        ' /runs/{run_id}.'
    ),
    'tests/test_queue_durability.py': (
        '1 `.text` comparison, zero affected: caplog.text (route=none, layer=UNCONVERTED) — log'
        ' output, not an HTTP response body.'
    ),
    'tests/test_reply_redelivery.py': (
        '4 `.text` comparisons, attributed to /runs/{run_id}: three reached via the ?notice='
        ' query channel after a simulate-reply mutation, one on the reject-form action markup —'
        ' all layer=UNCONVERTED.'
    ),
    'tests/test_resume_pipeline.py': (
        '3 `.text` comparisons, zero affected: all three are caplog.text (route=none,'
        ' layer=UNCONVERTED) — log output, not an HTTP response body.'
    ),
    'tests/test_stuck_run_recovery.py': (
        '1 `.text` comparison, attributed to /runs: the <h1>Payroll Runs</h1> chrome heading'
        ' (runs_list.html:62, outside the D-22-12 React mount region), classified as'
        ' layer=JINJA_SHELL.'
    ),
}


ASSERTION_INVENTORY: dict[str, AssertionEntry] = {
    'test_dashboard:62:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=62,
        col_offset=11,
        source_text='str(run_id) in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:66:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=66,
        col_offset=11,
        source_text='"No payroll runs yet" not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.REACT_DOM,
    ),
    'test_dashboard:74:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=74,
        col_offset=11,
        source_text='"No payroll runs yet" in empty.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.REACT_DOM,
    ),
    'test_dashboard:179:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=179,
        col_offset=11,
        source_text='"chart.svg" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:235:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=235,
        col_offset=15,
        source_text='"No eval results" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:235:53': AssertionEntry(
        file='tests/test_dashboard.py',
        line=235,
        col_offset=53,
        source_text='"chart.svg" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:309:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=309,
        col_offset=11,
        source_text='sentinel not in response.text',
        route='/eval',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:313:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=313,
        col_offset=11,
        source_text='"‹fixture file missing›" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:316:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=316,
        col_offset=11,
        source_text='legit_body in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:415:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=415,
        col_offset=11,
        source_text='\'http-equiv="refresh"\' not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:463:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=463,
        col_offset=11,
        source_text='"/status" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:464:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=464,
        col_offset=11,
        source_text='str(run_id) in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:473:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=473,
        col_offset=11,
        source_text='"/status" not in settled.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:523:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=523,
        col_offset=11,
        source_text='"Maria Chen" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:524:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=524,
        col_offset=11,
        source_text='"maria@example.test" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:525:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=525,
        col_offset=11,
        source_text='"provider said" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:526:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=526,
        col_offset=11,
        source_text='"Error" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:527:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=527,
        col_offset=11,
        source_text="f'/runs/{run_id}/retrigger' in response.text",
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:560:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=560,
        col_offset=11,
        source_text='"Maria Chen" in leaking.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:618:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=618,
        col_offset=11,
        source_text='"Retries exhausted" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:619:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=619,
        col_offset=11,
        source_text='"Extraction" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:620:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=620,
        col_offset=11,
        source_text='"Provider timeout" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:621:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=621,
        col_offset=11,
        source_text='"5 of 5 attempts" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:622:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=622,
        col_offset=11,
        source_text='hostile not in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:649:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=649,
        col_offset=15,
        source_text='derived not in mismatched_detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:650:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=650,
        col_offset=15,
        source_text='derived not in mismatched_poll.text',
        route='/runs/{run_id}/status',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:651:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=651,
        col_offset=11,
        source_text='"Stage:</strong> Extraction" not in mismatched_detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:687:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=687,
        col_offset=11,
        source_text='">Error<" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:688:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=688,
        col_offset=11,
        source_text='"Retries exhausted" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:689:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=689,
        col_offset=11,
        source_text='"Final attempt lease expired" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:690:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=690,
        col_offset=11,
        source_text='"5 of 5 attempts" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:691:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=691,
        col_offset=11,
        source_text='hostile not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:862:8': AssertionEntry(
        file='tests/test_dashboard.py',
        line=862,
        col_offset=8,
        source_text='"This action is durably saved; you can safely leave this page."\n        not in settled.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:865:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=865,
        col_offset=11,
        source_text='"var MAX_ATTEMPTS = 60" not in settled.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1070:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1070,
        col_offset=11,
        source_text='"Fallback payroll request" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1071:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1071,
        col_offset=11,
        source_text='"2026-07-18 12:34" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1112:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1112,
        col_offset=11,
        source_text='(\n        "An earlier resolution was already accepted. This submission was recorded "\n        "but not applied."\n    ) in response.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1116:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1116,
        col_offset=11,
        source_text='hostile not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1124:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1124,
        col_offset=11,
        source_text='(\n        "An earlier resolution was already accepted. This submission was recorded "\n        "but not applied."\n    ) not in no_flag.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1140:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1140,
        col_offset=11,
        source_text='"start this payroll run." in labeled.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:1145:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1145,
        col_offset=11,
        source_text='hostile not in hostile_resp.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:1146:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1146,
        col_offset=11,
        source_text='"start this payroll run." not in hostile_resp.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:1204:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1204,
        col_offset=11,
        source_text='"Frozen confirmation" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1205:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1205,
        col_offset=11,
        source_text='"Frozen confirmation body" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1206:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1206,
        col_offset=11,
        source_text='"Changed after reservation" not in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1339:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1339,
        col_offset=11,
        source_text='"Review confirmation delivery" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1340:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1340,
        col_offset=11,
        source_text='"Frozen payload mismatch" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1341:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1341,
        col_offset=11,
        source_text='"Frozen confirmation" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1342:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1342,
        col_offset=11,
        source_text='"View frozen email" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1343:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1343,
        col_offset=11,
        source_text='"View frozen attachment" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1344:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1344,
        col_offset=11,
        source_text='"Mark delivered" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1345:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1345,
        col_offset=11,
        source_text='"Authorize a new confirmation" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1346:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1346,
        col_offset=11,
        source_text='"AUTHORIZE A NEW CONFIRMATION" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1347:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1347,
        col_offset=11,
        source_text='"Resolve unresolved names" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1358:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1358,
        col_offset=15,
        source_text='unsafe_name not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1380:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1380,
        col_offset=11,
        source_text='"Review clarification delivery" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1384:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1384,
        col_offset=11,
        source_text='">Retry same question</button>" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1385:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1385,
        col_offset=11,
        source_text='f"/runs/{run_id}/delivery-review/clarification/retry-now" not in response.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1386:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1386,
        col_offset=11,
        source_text='"the replay budget for this reservation is spent" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1387:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1387,
        col_offset=11,
        source_text='"Mark handled" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1388:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1388,
        col_offset=11,
        source_text='"Reject" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1389:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1389,
        col_offset=11,
        source_text='f"/runs/{run_id}/delivery-review/clarification/mark-handled" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1390:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1390,
        col_offset=11,
        source_text='f"/runs/{run_id}/delivery-review/clarification/reject" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1391:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1391,
        col_offset=11,
        source_text='"One payroll name needs clarification" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1392:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1392,
        col_offset=11,
        source_text='"frozen-question.pdf" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1393:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1393,
        col_offset=11,
        source_text='"Review confirmation delivery" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1394:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1394,
        col_offset=11,
        source_text='"Mark delivered" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1395:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1395,
        col_offset=11,
        source_text='"Authorize a new confirmation" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1396:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1396,
        col_offset=11,
        source_text='"AUTHORIZE A NEW CONFIRMATION" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1397:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1397,
        col_offset=11,
        source_text='"Resolve &amp; Resume" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1398:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1398,
        col_offset=11,
        source_text='"remember this alias" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1403:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1403,
        col_offset=15,
        source_text='unsafe_name not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1423:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1423,
        col_offset=11,
        source_text='"Which employee did you mean by D. Reyes?" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1634:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1634,
        col_offset=11,
        source_text='"location.reload()" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1644:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1644,
        col_offset=11,
        source_text='"location.reload()" not in settled.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1709:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1709,
        col_offset=11,
        source_text='\'http-equiv="refresh"\' not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_demo_fixtures:493:15': AssertionEntry(
        file='tests/test_demo_fixtures.py',
        line=493,
        col_offset=15,
        source_text='forbidden not in notice.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_demo_landing:1040:11': AssertionEntry(
        file='tests/test_demo_landing.py',
        line=1040,
        col_offset=11,
        source_text='\'class="page-disclaimer"\' in resp.text',
        route='/',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_demo_landing:1854:15': AssertionEntry(
        file='tests/test_demo_landing.py',
        line=1854,
        col_offset=15,
        source_text='forbidden not in notice.text',
        route='/',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_durable_ingest:661:11': AssertionEntry(
        file='tests/test_durable_ingest.py',
        line=661,
        col_offset=11,
        source_text='"private diagnostics" not in response.text',
        route='/webhook/inbound',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_queue_alarm:74:11': AssertionEntry(
        file='tests/test_health_queue_alarm.py',
        line=74,
        col_offset=11,
        source_text='"secret" not in r.text',
        route='/health/queue',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_queue_alarm:74:38': AssertionEntry(
        file='tests/test_health_queue_alarm.py',
        line=74,
        col_offset=38,
        source_text='"postgresql://" not in r.text',
        route='/health/queue',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_queue_alarm:107:11': AssertionEntry(
        file='tests/test_health_queue_alarm.py',
        line=107,
        col_offset=11,
        source_text='"leak-me-run-id-should-never-appear" not in r.text',
        route='/health/queue',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_queue_alarm:108:11': AssertionEntry(
        file='tests/test_health_queue_alarm.py',
        line=108,
        col_offset=11,
        source_text='"leak-me-error-reason-should-never-appear" not in r.text',
        route='/health/queue',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_queue_alarm:151:11': AssertionEntry(
        file='tests/test_health_queue_alarm.py',
        line=151,
        col_offset=11,
        source_text='"secret" not in r.text',
        route='/health/ready',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_queue_alarm:151:38': AssertionEntry(
        file='tests/test_health_queue_alarm.py',
        line=151,
        col_offset=38,
        source_text='"postgresql://" not in r.text',
        route='/health/ready',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_schema:45:11': AssertionEntry(
        file='tests/test_health_schema.py',
        line=45,
        col_offset=11,
        source_text='"secret" not in r.text',
        route='/health/schema',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_health_schema:45:38': AssertionEntry(
        file='tests/test_health_schema.py',
        line=45,
        col_offset=38,
        source_text='"postgresql://" not in r.text',
        route='/health/schema',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_hitl:330:11': AssertionEntry(
        file='tests/test_hitl.py',
        line=330,
        col_offset=11,
        source_text='"Resolve the delivery review below before re-triggering" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_hitl:365:11': AssertionEntry(
        file='tests/test_hitl.py',
        line=365,
        col_offset=11,
        source_text='"still in flight with the email provider" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:842:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=842,
        col_offset=11,
        source_text='"SECRET" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:843:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=843,
        col_offset=11,
        source_text='"e0000001" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:844:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=844,
        col_offset=11,
        source_text='"e0000002" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:845:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=845,
        col_offset=11,
        source_text='"e0000003" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1266:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1266,
        col_offset=11,
        source_text='"Needs Operator" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1269:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1269,
        col_offset=11,
        source_text='"badge-escalate" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1282:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1282,
        col_offset=11,
        source_text='"Needs Operator" not in perturbed.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1283:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1283,
        col_offset=11,
        source_text='"badge-escalate" not in perturbed.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1305:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1305,
        col_offset=11,
        source_text='"Needs Operator" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_needs_operator:1306:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1306,
        col_offset=11,
        source_text='"badge-escalate" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_needs_operator:1554:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1554,
        col_offset=11,
        source_text='bogus_id not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_ops_route:102:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=102,
        col_offset=11,
        source_text='"Transport Ops" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:118:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=118,
        col_offset=11,
        source_text='"No due pending work" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:119:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=119,
        col_offset=11,
        source_text='"No open jobs." in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:120:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=120,
        col_offset=11,
        source_text='"No dead-lettered jobs." in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:202:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=202,
        col_offset=11,
        source_text='">3<" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:203:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=203,
        col_offset=11,
        source_text='">2<" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:205:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=205,
        col_offset=11,
        source_text='">5<" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:214:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=214,
        col_offset=11,
        source_text='"1 of 5" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:215:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=215,
        col_offset=11,
        source_text='"2 of 5" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:224:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=224,
        col_offset=11,
        source_text='"min" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:225:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=225,
        col_offset=11,
        source_text='f"{ops.PUMP_CADENCE_MINUTES}-minute cadence" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:232:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=232,
        col_offset=11,
        source_text='"No due pending work" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:254:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=254,
        col_offset=11,
        source_text='f"/runs/{run_id}" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:275:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=275,
        col_offset=11,
        source_text='"malformed webhook payload" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:276:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=276,
        col_offset=11,
        source_text='"/runs/None" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:320:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=320,
        col_offset=11,
        source_text='"ops-alarm-banner" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:334:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=334,
        col_offset=11,
        source_text='"ops-alarm-banner" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:335:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=335,
        col_offset=11,
        source_text='f"/runs/{run_id}" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:339:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=339,
        col_offset=11,
        source_text='"<form" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:340:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=340,
        col_offset=11,
        source_text='"<button" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:361:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=361,
        col_offset=11,
        source_text='"As of" in response.text',
        route='/ops',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:366:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=366,
        col_offset=11,
        source_text='"<script" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_ops_route:367:11': AssertionEntry(
        file='tests/test_ops_route.py',
        line=367,
        col_offset=11,
        source_text='"setInterval" not in response.text',
        route='/ops',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_phase20_clarification_review:104:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=104,
        col_offset=11,
        source_text='"One payroll name needs clarification" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:105:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=105,
        col_offset=11,
        source_text='"Which employee did you mean by D. Reyes?" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:106:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=106,
        col_offset=11,
        source_text='"In-Reply-To: <source@payroll-agent.local>" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:107:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=107,
        col_offset=11,
        source_text='"References: <prior@payroll-agent.local> <source@payroll-agent.local>" in email.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:108:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=108,
        col_offset=11,
        source_text='snapshot["message_id"] in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:698:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=698,
        col_offset=11,
        source_text='"AUTHORIZE A NEW CONFIRMATION" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:748:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=748,
        col_offset=11,
        source_text='_AUTHORIZE_ACTION not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:749:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=749,
        col_offset=11,
        source_text='"the recipient or sender configuration must change first" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:751:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=751,
        col_offset=11,
        source_text='_MARK_DELIVERED_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:773:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=773,
        col_offset=11,
        source_text='_AUTHORIZE_ACTION not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:776:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=776,
        col_offset=11,
        source_text='f\'action="/runs/{run_id}/reject"\' in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:799:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=799,
        col_offset=11,
        source_text='_AUTHORIZE_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:800:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=800,
        col_offset=11,
        source_text='f\'action="/runs/{run_id}/reject"\' not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:810:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=810,
        col_offset=11,
        source_text='_CLARIFICATION_RETRY_ACTION not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:811:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=811,
        col_offset=11,
        source_text='"the recipient or sender configuration must change first" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:814:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=814,
        col_offset=11,
        source_text='_MARK_HANDLED_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:815:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=815,
        col_offset=11,
        source_text='_CLARIFICATION_REJECT_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:825:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=825,
        col_offset=11,
        source_text='_AUTHORIZE_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:826:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=826,
        col_offset=11,
        source_text='_MARK_DELIVERED_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:840:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=840,
        col_offset=11,
        source_text='_AUTHORIZE_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:841:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=841,
        col_offset=11,
        source_text='_MARK_DELIVERED_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:851:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=851,
        col_offset=11,
        source_text='_CLARIFICATION_RETRY_ACTION not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:852:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=852,
        col_offset=11,
        source_text='_MARK_HANDLED_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:853:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=853,
        col_offset=11,
        source_text='_CLARIFICATION_REJECT_ACTION in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:882:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=882,
        col_offset=11,
        source_text='DELIVERY_REVIEW_CATEGORIES[category].uncertainty in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:909:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=909,
        col_offset=11,
        source_text='"Delivery review unavailable" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:910:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=910,
        col_offset=11,
        source_text='"Action required" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:911:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=911,
        col_offset=11,
        source_text='f\'action="/runs/{run_id}/reject"\' in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:912:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=912,
        col_offset=11,
        source_text='f\'action="/runs/{run_id}/resolve"\' not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_phase20_clarification_review:913:11': AssertionEntry(
        file='tests/test_phase20_clarification_review.py',
        line=913,
        col_offset=11,
        source_text='f\'action="/runs/{run_id}/retrigger"\' not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_queue_durability:1449:15': AssertionEntry(
        file='tests/test_queue_durability.py',
        line=1449,
        col_offset=15,
        source_text='token not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_reply_redelivery:602:11': AssertionEntry(
        file='tests/test_reply_redelivery.py',
        line=602,
        col_offset=11,
        source_text='"has not been confirmed sent yet" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_reply_redelivery:636:11': AssertionEntry(
        file='tests/test_reply_redelivery.py',
        line=636,
        col_offset=11,
        source_text='"original email for this run could not be loaded" in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_reply_redelivery:650:11': AssertionEntry(
        file='tests/test_reply_redelivery.py',
        line=650,
        col_offset=11,
        source_text='"<script>alert(1)</script>" not in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_reply_redelivery:674:11': AssertionEntry(
        file='tests/test_reply_redelivery.py',
        line=674,
        col_offset=11,
        source_text='f\'action="/runs/{run_id}/reject"\' in page.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_resume_pipeline:420:15': AssertionEntry(
        file='tests/test_resume_pipeline.py',
        line=420,
        col_offset=15,
        source_text='token not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_resume_pipeline:455:11': AssertionEntry(
        file='tests/test_resume_pipeline.py',
        line=455,
        col_offset=11,
        source_text='"SECRET" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_resume_pipeline:456:11': AssertionEntry(
        file='tests/test_resume_pipeline.py',
        line=456,
        col_offset=11,
        source_text='"Maria Chen" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_stuck_run_recovery:102:11': AssertionEntry(
        file='tests/test_stuck_run_recovery.py',
        line=102,
        col_offset=11,
        source_text='"Payroll Runs" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
}
