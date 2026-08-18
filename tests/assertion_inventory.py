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
carry a falsifying mutation (that is a separate, smaller sibling registry
scoped to PII scrubbing, XSS, path traversal, and the delivery-review Reject
gate — GUARD-02). This module is inert data plus two small enums — no I/O, no
test collection, so it costs nothing at import time and stays fast under
`mypy --strict` and pytest collection.

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
(the React mount boundary is lines 64-115) and by tracing each assertion's
own enclosing test function back to its `client.get(...)`/`client.post(...)`
call — never guessed from the assertion's file name or from a substring
inside its own message. `layer=UNCONVERTED` is used for every route not yet
converted to React (`/runs/{run_id}`, `/eval`, `/runs/{run_id}/status`,
`/runs/{run_id}/delivery-review/email`, `/health/*`, `/webhook/inbound`, and
`route="none"` non-HTTP bodies such as `caplog.text`) — the classification
pass covers every affected assertion up front, but only the assertions on a
page actually being converted are pinned and rewritten at conversion time;
`/ops` and `/` are `layer=JINJA_SHELL` because they are never converted at
all (permanent, not merely "not yet"). Only `/runs`-attributed entries were
split further into `JINJA_SHELL` (chrome outside the React mount: the
`<h1>`, the `?notice=` banner, the demo form, and whole-page checks like the
meta-refresh absence), `JSON_ISLAND` (content that originates in a
`RunListRow`/`RunStatusPoll` DTO field — a run id, a badge class/label, a
failure reason — and will therefore live inside the `__INITIAL_DATA__` JSON
blob after conversion, where the correct rewritten assertion is a positive
exact-shape check against parsed JSON, not a substring search over
`response.text`), and `REACT_DOM` (static JSX markup with no DTO field
behind it, such as the empty-state copy "No payroll runs yet" — the
genuinely vacuous class, because `TestClient` never executes JavaScript and
cannot see it after conversion).

Baseline counts (files/entries; per-file and per-route/class/layer breakdowns
are derived output printed by `scripts/render_assertion_inventory.py`, never
hand-pinned here):
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
    'tests/assertion_inventory.py': (
        'Zero `.text` comparisons: this is the GUARD-01 registry itself. The'
        ' substring `.text` appears only in this module\'s own docstring prose'
        ' (describing what a `.text` comparison is) and inside the captured'
        ' `source_text` string VALUES of other files\' entries — never as a'
        ' left operand or comparator of an `ast.Compare` node in this file.'
    ),
    'tests/test_inventory_completeness.py': (
        'Zero `.text` comparisons: this is the GUARD-01 completeness guard'
        ' itself. The substring `.text` appears only in docstrings, comments,'
        ' and the guard\'s own field/variable names (`entry.route`,'
        ' `_is_text_attribute`) — never as a left operand or comparator of an'
        ' `ast.Compare` node in this file.'
    ),
    'tests/safety_mutation_registry.py': (
        'Zero `.text` comparisons: this is the GUARD-02 safety mutation registry.'
        ' The substring `.text` appears only inside string-literal VALUES (a'
        ' `PinnedAssertion.assertion_text` field naming `response.text`, and the'
        ' TypeScript `element.textContent` fragment the `tsx_fragment` resolver'
        ' searches for) — never as a left operand or comparator of an'
        ' `ast.Compare` node in this file.'
    ),
    'tests/test_safety_mutation_registry.py': (
        'Zero `.text` comparisons: this is the GUARD-02 registry\'s completeness'
        ' guard. The substring `.text` appears only inside synthetic TypeScript'
        ' source strings passed to `resolve_tsx_fragment` (`element.textContent`)'
        ' and prose describing that fragment — never as a left operand or'
        ' comparator of an `ast.Compare` node in this file.'
    ),
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
    'tests/test_page_shell_pins.py': (
        'Zero `.text` comparisons: all three `.text` usages (lines 63, 105, 118) read'
        ' `response.text` as a call ARGUMENT into an extractor helper'
        ' (`_extract_title`, `_extract_nav_html`); every assertion in this file then'
        ' compares the extracted `title`/`nav_html` string, never `response.text`'
        ' directly, so no `ast.Compare` node has a `.text` attribute operand. The page'
        ' shell pins it guards are structural (one title per page, one current nav'
        ' item) and survive the React conversion unchanged.'
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
        ' classified individually below as JINJA_SHELL — the ?notice= channel is a'
        ' server-rendered banner that never round-trips through JSON.'
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
        ' below as layer=UNCONVERTED — /runs/{run_id} is not yet converted to React.'
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
        ' email/attachment content endpoint) — both layer=UNCONVERTED; neither route is'
        ' converted to React yet.'
    ),
    'tests/test_queue_durability.py': (
        '1 `.text` comparison, zero affected: caplog.text (route=none, layer=UNCONVERTED) — log'
        ' output, not an HTTP response body.'
    ),
    'tests/test_react_page_render.py': (
        '2 `.text` comparisons, both attributed to /runs: the demo form presence check'
        ' (layer=JINJA_SHELL) and the hostile-business-name script-injection round-trip check'
        ' (layer=JSON_ISLAND). Every other assertion in this new file (added by the same plan'
        ' that converted /runs to React) parses the __INITIAL_DATA__ island once via the'
        ' shared `_parse_island` helper and asserts on the resulting dict/list — those compares'
        ' operate on parsed values, not on a `.text` attribute access, so they are outside this'
        " guard's scope by construction, the same shape as tests/test_gateway.py's intermediate-"
        ' variable pattern noted above.'
    ),
    'tests/test_react_dev_mode.py': (
        '5 `.text` comparisons, all attributed to /runs: the dev-server render'
        ' branch boot-tag assertions (no developer-host URL leaking into a'
        ' default-settings render; the Vite dev client module and entry source'
        ' path present in a dev-mode render; no manifest-resolved hashed asset'
        ' path leaking into a dev-mode render). All five inspect the boot-tag'
        ' script elements react_page.html renders around the mount point --'
        ' Jinja-owned chrome, not React DOM or the JSON data island -- so all'
        ' are layer=JINJA_SHELL.'
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
        ' (runs_list.html:62, outside the React mount region at runs_list.html:64-115),'
        ' classified as layer=JINJA_SHELL.'
    ),
}


ASSERTION_INVENTORY: dict[str, AssertionEntry] = {
    'test_dashboard:88:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=88,
        col_offset=11,
        source_text='[row["id"] for row in island["runs"]] == [str(run_id)]',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_dashboard.py::test_runs_list_returns_200 -- rewritten as a positive'
            ' exact-shape assertion against the parsed island\'s rows array (no longer a literal'
            ' `.text` substring search)'
        ),
    ),
    'test_dashboard:66:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=66,
        col_offset=11,
        source_text='"No payroll runs yet" not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.REACT_DOM,
        replaced_by=(
            'frontend/src/pages/RunsPage.test.tsx::given an empty rows array renders the'
            ' empty-state title and helper sentence, and no table element -- empty-state'
            ' copy is pure JSX with no server-side surface after conversion'
        ),
    ),
    'test_dashboard:74:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=74,
        col_offset=11,
        source_text='"No payroll runs yet" in empty.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.REACT_DOM,
        replaced_by=(
            'frontend/src/pages/RunsPage.test.tsx::given an empty rows array renders the'
            ' empty-state title and helper sentence, and no table element -- empty-state'
            ' copy is pure JSX with no server-side surface after conversion'
        ),
    ),
    'test_dashboard:204:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=204,
        col_offset=11,
        source_text='"chart.svg" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:260:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=260,
        col_offset=15,
        source_text='"No eval results" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:260:53': AssertionEntry(
        file='tests/test_dashboard.py',
        line=260,
        col_offset=53,
        source_text='"chart.svg" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:334:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=334,
        col_offset=11,
        source_text='sentinel not in response.text',
        route='/eval',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:338:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=338,
        col_offset=11,
        source_text='"‹fixture file missing›" in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:341:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=341,
        col_offset=11,
        source_text='legit_body in response.text',
        route='/eval',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:440:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=440,
        col_offset=11,
        source_text='\'http-equiv="refresh"\' not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:488:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=488,
        col_offset=11,
        source_text='"/status" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:489:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=489,
        col_offset=11,
        source_text='str(run_id) in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:498:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=498,
        col_offset=11,
        source_text='"/status" not in settled.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:548:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=548,
        col_offset=11,
        source_text='"Maria Chen" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:549:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=549,
        col_offset=11,
        source_text='"maria@example.test" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:550:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=550,
        col_offset=11,
        source_text='"provider said" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:551:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=551,
        col_offset=11,
        source_text='"Error" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:552:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=552,
        col_offset=11,
        source_text='f\'/runs/{run_id}/retrigger\' in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:585:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=585,
        col_offset=11,
        source_text='"Maria Chen" in leaking.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:643:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=643,
        col_offset=11,
        source_text='"Retries exhausted" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:644:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=644,
        col_offset=11,
        source_text='"Extraction" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:645:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=645,
        col_offset=11,
        source_text='"Provider timeout" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:646:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=646,
        col_offset=11,
        source_text='"5 of 5 attempts" in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:647:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=647,
        col_offset=11,
        source_text='hostile not in detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:674:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=674,
        col_offset=15,
        source_text='derived not in mismatched_detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:675:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=675,
        col_offset=15,
        source_text='derived not in mismatched_poll.text',
        route='/runs/{run_id}/status',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:676:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=676,
        col_offset=11,
        source_text='"Stage:</strong> Extraction" not in mismatched_detail.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:720:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=720,
        col_offset=11,
        source_text='row["badge_label"] == "Error"',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_dashboard.py::test_runs_list_uses_safe_failure_projection -- rewritten'
            ' as a positive exact-shape assertion against the parsed island\'s'
            ' RunListRow.badge_label field'
        ),
    ),
    'test_dashboard:721:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=721,
        col_offset=11,
        source_text='row["failure"]["secondary_label"] == "Retries exhausted"',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_dashboard.py::test_runs_list_uses_safe_failure_projection -- rewritten'
            ' as a positive exact-shape assertion against the parsed island\'s'
            ' RunListRow.failure.secondary_label field'
        ),
    ),
    'test_dashboard:723:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=723,
        col_offset=11,
        source_text='row["failure"]["reason"] == "Final attempt lease expired"',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_dashboard.py::test_runs_list_uses_safe_failure_projection -- rewritten'
            ' as a positive exact-shape assertion against the parsed island\'s'
            ' RunListRow.failure.reason field'
        ),
    ),
    'test_dashboard:724:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=724,
        col_offset=11,
        source_text='row["failure"]["attempts"] == "5 of 5 attempts"',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_dashboard.py::test_runs_list_uses_safe_failure_projection -- rewritten'
            ' as a positive exact-shape assertion against the parsed island\'s'
            ' RunListRow.failure.attempts field'
        ),
    ),
    'test_dashboard:725:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=725,
        col_offset=11,
        source_text='hostile not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_dashboard:896:8': AssertionEntry(
        file='tests/test_dashboard.py',
        line=896,
        col_offset=8,
        source_text='"This action is durably saved; you can safely leave this page."\n        not in settled.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:899:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=899,
        col_offset=11,
        source_text='"var MAX_ATTEMPTS = 60" not in settled.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1109:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1109,
        col_offset=11,
        source_text='"Fallback payroll request" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1110:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1110,
        col_offset=11,
        source_text='"2026-07-18 12:34" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1151:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1151,
        col_offset=11,
        source_text='(\n        "An earlier resolution was already accepted. This submission was recorded "\n        "but not applied."\n    ) in response.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1155:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1155,
        col_offset=11,
        source_text='hostile not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1163:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1163,
        col_offset=11,
        source_text='(\n        "An earlier resolution was already accepted. This submission was recorded "\n        "but not applied."\n    ) not in no_flag.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1179:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1179,
        col_offset=11,
        source_text='"start this payroll run." in labeled.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:1184:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1184,
        col_offset=11,
        source_text='hostile not in hostile_resp.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:1185:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1185,
        col_offset=11,
        source_text='"start this payroll run." not in hostile_resp.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:1243:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1243,
        col_offset=11,
        source_text='"Frozen confirmation" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1244:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1244,
        col_offset=11,
        source_text='"Frozen confirmation body" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1245:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1245,
        col_offset=11,
        source_text='"Changed after reservation" not in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1378:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1378,
        col_offset=11,
        source_text='"Review confirmation delivery" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1379:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1379,
        col_offset=11,
        source_text='"Frozen payload mismatch" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1380:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1380,
        col_offset=11,
        source_text='"Frozen confirmation" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1381:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1381,
        col_offset=11,
        source_text='"View frozen email" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1382:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1382,
        col_offset=11,
        source_text='"View frozen attachment" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1383:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1383,
        col_offset=11,
        source_text='"Mark delivered" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1384:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1384,
        col_offset=11,
        source_text='"Authorize a new confirmation" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1385:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1385,
        col_offset=11,
        source_text='"AUTHORIZE A NEW CONFIRMATION" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1386:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1386,
        col_offset=11,
        source_text='"Resolve unresolved names" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1397:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1397,
        col_offset=15,
        source_text='unsafe_name not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1419:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1419,
        col_offset=11,
        source_text='"Review clarification delivery" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1423:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1423,
        col_offset=11,
        source_text='">Retry same question</button>" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1424:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1424,
        col_offset=11,
        source_text='f"/runs/{run_id}/delivery-review/clarification/retry-now" not in response.text',  # noqa: E501 — exact live-source capture, must not be reformatted
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1425:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1425,
        col_offset=11,
        source_text='"the replay budget for this reservation is spent" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1426:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1426,
        col_offset=11,
        source_text='"Mark handled" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1427:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1427,
        col_offset=11,
        source_text='"Reject" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1428:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1428,
        col_offset=11,
        source_text='f"/runs/{run_id}/delivery-review/clarification/mark-handled" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1429:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1429,
        col_offset=11,
        source_text='f"/runs/{run_id}/delivery-review/clarification/reject" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1430:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1430,
        col_offset=11,
        source_text='"One payroll name needs clarification" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1431:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1431,
        col_offset=11,
        source_text='"frozen-question.pdf" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1432:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1432,
        col_offset=11,
        source_text='"Review confirmation delivery" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1433:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1433,
        col_offset=11,
        source_text='"Mark delivered" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1434:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1434,
        col_offset=11,
        source_text='"Authorize a new confirmation" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1435:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1435,
        col_offset=11,
        source_text='"AUTHORIZE A NEW CONFIRMATION" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1436:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1436,
        col_offset=11,
        source_text='"Resolve &amp; Resume" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1437:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1437,
        col_offset=11,
        source_text='"remember this alias" not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1442:15': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1442,
        col_offset=15,
        source_text='unsafe_name not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1462:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1462,
        col_offset=11,
        source_text='"Which employee did you mean by D. Reyes?" in email.text',
        route='/runs/{run_id}/delivery-review/email',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1673:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1673,
        col_offset=11,
        source_text='"location.reload()" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1683:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1683,
        col_offset=11,
        source_text='"location.reload()" not in settled.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:1748:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=1748,
        col_offset=11,
        source_text='\'http-equiv="refresh"\' not in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_dashboard:2412:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=2412,
        col_offset=11,
        source_text=(
            '(\n        "Couldn&#39;t start this payroll run. Pyrl&#39;s free hosting'
            ' sleeps after "\n        "15 idle minutes and can take up to a minute to'
            ' wake, so a first "\n        "attempt right after arriving can fail. Wait'
            ' a moment and try again."\n    ) in banner.text'
        ),
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:2437:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=2437,
        col_offset=11,
        source_text='\'class="callout callout-error"\' not in hostile_resp.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:2453:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=2453,
        col_offset=11,
        source_text=(
            '(\n        "Couldn&#39;t start this payroll run. Pyrl&#39;s free hosting'
            ' sleeps after "\n        "15 idle minutes and can take up to a minute to'
            ' wake, so a first "\n        "attempt right after arriving can fail. Wait'
            ' a moment and try again."\n    ) in labeled.text'
        ),
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:2469:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=2469,
        col_offset=11,
        source_text='\'method="post"\' in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_dashboard:2473:11': AssertionEntry(
        file='tests/test_dashboard.py',
        line=2473,
        col_offset=11,
        source_text='\'action="/demo/send-test"\' in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
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
    'test_needs_operator:858:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=858,
        col_offset=11,
        source_text='"SECRET" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:859:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=859,
        col_offset=11,
        source_text='"e0000001" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:860:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=860,
        col_offset=11,
        source_text='"e0000002" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:861:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=861,
        col_offset=11,
        source_text='"e0000003" not in caplog.text',
        route='none',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1282:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1282,
        col_offset=11,
        source_text='"Needs Operator" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1285:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1285,
        col_offset=11,
        source_text='"badge-escalate" in response.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1298:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1298,
        col_offset=11,
        source_text='"Needs Operator" not in perturbed.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1299:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1299,
        col_offset=11,
        source_text='"badge-escalate" not in perturbed.text',
        route='/runs/{run_id}',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.UNCONVERTED,
    ),
    'test_needs_operator:1326:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1326,
        col_offset=11,
        source_text='row["badge_label"] == "Needs Operator"',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_needs_operator.py::test_runs_list_renders_needs_operator_badge_label --'
            ' rewritten as a positive exact-shape assertion against the parsed island\'s'
            ' RunListRow.badge_label field'
        ),
    ),
    'test_needs_operator:1327:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1327,
        col_offset=11,
        source_text='row["badge_class"] == "escalate"',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JSON_ISLAND,
        replaced_by=(
            'tests/test_needs_operator.py::test_runs_list_renders_needs_operator_badge_label --'
            ' rewritten as a positive exact-shape assertion against the parsed island\'s'
            ' RunListRow.badge_class field'
        ),
    ),
    'test_needs_operator:1575:11': AssertionEntry(
        file='tests/test_needs_operator.py',
        line=1575,
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
    'test_react_page_render:99:11': AssertionEntry(
        file='tests/test_react_page_render.py',
        line=99,
        col_offset=11,
        source_text='\'action="/demo/send-test"\' in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_react_page_render:129:11': AssertionEntry(
        file='tests/test_react_page_render.py',
        line=129,
        col_offset=11,
        source_text='"<script>alert(1)</script>" not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JSON_ISLAND,
    ),
    'test_react_dev_mode:63:11': AssertionEntry(
        file='tests/test_react_dev_mode.py',
        line=63,
        col_offset=11,
        source_text='"localhost" not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_react_dev_mode:64:11': AssertionEntry(
        file='tests/test_react_dev_mode.py',
        line=64,
        col_offset=11,
        source_text='_DEV_ORIGIN not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_react_dev_mode:108:8': AssertionEntry(
        file='tests/test_react_dev_mode.py',
        line=108,
        col_offset=8,
        source_text=(
            'f\'<script type="module" src="{_dev_mode_enabled}/@vite/client"></script>\'\n'
            '        in response.text'
        ),
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_react_dev_mode:112:8': AssertionEntry(
        file='tests/test_react_dev_mode.py',
        line=112,
        col_offset=8,
        source_text=(
            'f\'<script type="module" src="{_dev_mode_enabled}/src/entries/runs.tsx"></script>\'\n'
            '        in response.text'
        ),
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
    'test_react_dev_mode:116:11': AssertionEntry(
        file='tests/test_react_dev_mode.py',
        line=116,
        col_offset=11,
        source_text='"/static/dist/" not in response.text',
        route='/runs',
        assertion_class=AssertionClass.ABSENCE,
        layer=AssertionLayer.JINJA_SHELL,
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
    'test_stuck_run_recovery:123:11': AssertionEntry(
        file='tests/test_stuck_run_recovery.py',
        line=123,
        col_offset=11,
        source_text='"Payroll Runs" in response.text',
        route='/runs',
        assertion_class=AssertionClass.PRESENCE,
        layer=AssertionLayer.JINJA_SHELL,
    ),
}
