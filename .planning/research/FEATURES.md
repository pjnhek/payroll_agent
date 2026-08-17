# Feature Research — v5 React/TypeScript Operator Console (Slices 1–3)

**Domain:** Behavioral-parity conversion of a server-rendered operator dashboard (3 of 5 pages) to React + TypeScript, zero mutation-route changes.
**Researched:** 2026-08-17
**Confidence:** HIGH — every behavior below is grounded in `file:line` citations against the live templates, routes, and the ~4,500 LOC of tests that assert against rendered markup (the actual parity contract).

## How to read this document

The milestone (`.planning/PROJECT.md:182-217`) already falsified three assumptions a naive React port would make:
1. Mutations MUST stay native `<form method="post">` + 303 (never `fetch`) — `app/routes/runs.py:580` (`?resolution_superseded=1` baked into the redirect target only), `app/routes/demo.py:252` (redirect to the newly created run), and the `onsubmit="return confirm(...)"` reject guard (`run_detail.html:143,155,320`).
2. `_safe_run_for_browser` (`app/routes/runs.py:220-245`) is a **denylist**, not an allowlist — a wholesale-serialized DTO would leak `alias_candidates`, `reply_epoch`, `business_id`.
3. The three pages ship as **independently deployable vertical slices**, not a horizontal API-then-UI split.

Everything below assumes those three constraints hold. Each behavior is marked with a complexity for slice-sizing, and Section 4 lists what a planner must NOT add.

---

## 1. Per-page behavior inventory

### 1.1 `/runs` (Slice 1) — `app/templates/runs_list.html`, `app/routes/runs.py:855-882`

| # | Behavior | Source | Complexity |
|---|----------|--------|------------|
| R1 | Renders a reverse-chronological table: Created, Business, Status, Summary, Action columns | `runs_list.html:66-108` | LOW |
| R2 | Empty state (`No payroll runs yet`) when `runs` is empty, distinct from the table | `runs_list.html:110-114` | LOW |
| R3 | Table wrapped in a horizontally-scrollable, keyboard-focusable region: `role="region" tabindex="0" aria-label="Payroll runs"` | `runs_list.html:65` | LOW — easy to drop; React devs default to a plain `<div>` |
| R4 | Status badge (`badge-{class} js-status-badge`) driven by `badge_class`/`badge_label` Jinja filters, itself driven by `_BADGE_CLASS`/`_BADGE_LABEL` dicts (`app/routes/templating.py:18-45`) — 11 statuses incl. the dedicated `escalate` class for `needs_operator` | `runs_list.html:87`, `templating.py:18-45` | MEDIUM — the class/label maps must be ported verbatim, not re-derived |
| R5 | Secondary "queue" badge (`Running`/`Queued`/`Retry queued`), only rendered when `has_open_job`; `aria-live="polite"`; `hidden` attribute (not CSS display) when absent | `runs_list.html:88-90` | MEDIUM |
| R6 | Secondary failure badge (`js-failure-secondary`, e.g. "Retries exhausted"), `hidden` when no `secondary_label` | `runs_list.html:91` | LOW |
| R7 | Summary cell is a 4-way priority fallback: failure summary (`stage · reason · attempts`) → `summary_gate_reason` → `"{n} employee(s)"` (singular/plural) → em dash `—` | `runs_list.html:93-103` | MEDIUM — order matters, must be ported exactly |
| R8 | Row-level 2-second poller: `GET /runs/{id}/status`, starts only for rows where `data-in-flight="true"` OR `data-has-open-job="true"`; swaps 4 DOM targets in place (status badge class+text, queue badge class+text+hidden, failure-secondary text+hidden, failure-summary text+hidden built by filtering+joining `[stage, reason, attempts]`); **stops** polling that row once `!IN_FLIGHT.has(status) && !has_open_job`; hard cap 60 attempts (120s), timeout has no recovery side effect; network errors are silently swallowed per tick | `runs_list.html:10-59` | **HIGH** — this is the named differentiator; see §2 |
| R9 | Poller explicitly does **not** reload the page — "the demo-business `<select>` and scroll position survive" | `runs_list.html:4-9` comment | MEDIUM (a design constraint, not just an implementation detail) |
| R10 | `?notice=<code>` operator-feedback banner rendered via `_operator_notice.html` include, `role="alert"`, at top of page | `runs_list.html:61`, `_operator_notice.html` | LOW |
| R11 | Demo "Send Test Email" form: native `<form method="post" action="/demo/send-test">` with a `<select name="fixture_key">` populated from `demo_fixtures` dict | `runs_list.html:118-128` | LOW |
| R12 | No `<meta http-equiv="refresh">` anywhere — pinned by test | `tests/test_dashboard.py:400-418` (`test_runs_list_has_no_meta_refresh`) | — (regression pin, not a new behavior) |
| R13 | `load_all_runs` never `SELECT *`; failure-vocabulary fields (`error_reason`/`error_detail`/`queue_label`) are bounded/reduced server-side before reaching the template — `_safe_run_for_browser` strips `error_detail`, `last_error`, `payload`, `diagnostics`, any `job_*` field | `app/routes/runs.py:220-245`, asserted by `tests/test_dashboard.py:654-693,694-718` | MEDIUM (must preserve: the React page receives the SAME reduced JSON, never a raw column) |
| R14 | `aria-current="page"` on the nav `Runs` link when on `/runs` or any `/runs/*` path — exactly one match, proven live | `base.html:13`, `tests/test_dashboard.py:572-583` | LOW |

### 1.2 `/runs/{id}` (Slice 2) — `app/templates/run_detail.html`, `app/routes/runs.py:1232-1354`

This is the heaviest page. The milestone description says "8-branch decision-banner matrix" — the actual branch count in the template's `if/elif` chain is **7**, plus one fully **independent** banner that can render alongside any of them (documented in-template as deliberately not an `elif`). If "8" is meant to include that independent banner, the count is defensible; a planner sizing this slice should treat it as **7 mutually exclusive branches + 1 independent overlay**, not 8 mutually exclusive branches, or the port will silently make the 8th an `elif` and break the one case it exists to fix.

**Decision/status banner — enumerated branches** (`run_detail.html:99-208`, in source order, each an `elif` off the one `if` chain unless noted):

| Branch | Condition | Renders | Source |
|---|---|---|---|
| B1 | `run.status == 'error'` | Error banner + optional secondary-label badge + optional stage/reason/attempts divider | `:99-111` |
| B2 | `delivery_review or (run.status == 'needs_operator' and delivery_review_marker)` | "Delivery review required" banner (covers BOTH the loadable-review case and the unavailable-review case handled later in a separate section) | `:112-115` |
| B3 | `run.status == 'needs_operator'` (falls through only if B2 didn't match, i.e. non-delivery-review escalation) | "Needs Operator" banner with an inline per-token resolve form (`<select>` per unresolved name + "remember this alias" checkbox, pre-selected from `unresolved_suggestions`) + a Reject form with `onsubmit="return confirm(...)"` | `:116-148` |
| B4 | `run.status == 'awaiting_reply'` | "Awaiting client reply" banner + Reject form (only escape hatch for a client that will never reply) | `:149-160` |
| B5 | `run.decision and run.decision.final_action == 'process'` | "Decision: Process" banner (this is also the branch active at `awaiting_approval`, since that status has no earlier `elif` of its own) | `:161-164` |
| B6 | `run.decision and run.decision.final_action == 'request_clarification'` | "Decision: Clarification requested" banner + optional `gate_reasons` list + optional unresolved-names line | `:165-178` |
| (implicit B7) | none of the above match (e.g. `decision` is `None`, still `received`/`extracting`/`computed`) | **No banner renders at all** — an implicit "nothing to show yet" state | (no `else` clause — verify by absence) |
| **Overlay** | `run.hours_changes` truthy — **independent `if`, not `elif`**, so it renders *alongside* whichever banner above is showing, most importantly alongside B5 at `awaiting_approval` (the one moment a silent hours-correction must be visible before a human signs) | Per-change: `{name} — {field}: {original} → {new}` | `:181-208`, extensive in-template comment explaining WHY this must not be folded into the chain |

That is 6 real mutually-exclusive `elif` conditions covering distinct states + 1 implicit no-banner state + 1 independent overlay = the true shape. Porting this as "8 branches" without reading the source risks either (a) missing the implicit no-banner state, or (b) folding the hours-changed overlay into the `elif` chain and silently killing the one case the comment says the overlay exists for.

**Delivery-review — two variants** (`run_detail.html:267-287`), gated by `{% if delivery_review %}` then `{% if delivery_review.review_kind == 'clarification' %}...{% else %}...{% endif %}`, PLUS a third degraded state:

| Variant | Trigger | Actions offered | Source |
|---|---|---|---|
| Confirmation delivery review | `delivery_review.review_kind != 'clarification'` | "Mark delivered" (always) + conditionally EITHER "Authorize a new confirmation" (typed-acknowledgement gate, exact string `AUTHORIZE A NEW CONFIRMATION`) when `can_fresh_send` OR "Reject" when NOT `can_fresh_send` — **mutually exclusive, never both** (explicit anti-BUG-1 comment: offering both would let an operator reject a run whose confirmation may have already reached the client) | `:277-283` |
| Clarification delivery review | `delivery_review.review_kind == 'clarification'` | Conditionally "Retry same question" (only if `can_replay`, else a `form-help` explaining the blocker) + always "Mark handled" + always "Reject" — 3 possible actions, purpose-isolated from confirmation controls (no alias/resolve UI ever shown here) | `:268-275`, pinned by `tests/test_dashboard.py:1372-1403` |
| Delivery review unavailable | `run.status == 'needs_operator' and delivery_review_marker` but `delivery_review` itself is `None` (the frozen evidence failed to load) | "Delivery review unavailable" card — Reject is the ONLY action offered, no retry/resolve/re-trigger | `:285-286` |

Both real variants share a facts `<dl>` (Recipient, Subject/Frozen question, Reserved timestamp, Attempts, Safe failure category, Message-ID/replay key) and an evidence block (link to frozen email + per-attachment links). Every action-gating boolean (`can_replay`, `can_fresh_send`) is **computed server-side** from `DELIVERY_REVIEW_CATEGORIES`, never re-derived client-side from a category string (`app/routes/runs.py:311-322` docstring: "so a template edit can never accidentally offer an action the classification says cannot succeed"). Complexity: **HIGH**.

**Conversation thread** (`run_detail.html:210-265`):
- Single chronological list from `thread_messages` (falls back to `raw_email` only if the thread load itself failed — NOT as a "no thread yet" empty state; falls back further to a `text-muted` "No email messages are available yet." if both are empty).
- Each message: direction badge (`neutral` inbound / `pending` outbound), purpose badge (color-coded: `good`=confirmation, `pending`=clarification/clarification_field_regression, `neutral`=other), a `record_only`-gated "recorded, not sent" badge + explanatory callout on **outbound, non-inbound** messages only, timestamp (handles both `str` and `datetime` created_at — string is sliced `[:16]`, datetime is `.strftime`), subject (`(no subject)` fallback), From/To `<dl>`, and body in a `<pre>` (autoescaped, **no truncation** — proven live with a 300+ char body: `tests/test_dashboard.py:989,1023`).
- Exactly one `>Conversation<` heading renders, verified live (`tests/test_dashboard.py:1015`), and message order is guaranteed chronological (`tests/test_dashboard.py:1016-1020`).
- The old 3-column grid + duplicate "Sent Emails"/"Conversation thread" surfaces are gone and pinned gone (`tests/test_dashboard.py:1024-1025`, `run-detail-grid` must not appear).

**Collapsed payroll-details disclosure** (`run_detail.html:289-311`):
- Native `<details class="payroll-details">` / `<summary>` — expand/collapse works with **zero JavaScript** (this is a progressive-enhancement property React will lose unless it re-implements open/closed state explicitly).
- Contains: optional alias-rationale callout, per-employee extraction+reconciliation subtable (badge: exact/stored-alias/unresolved) with a **per-field provenance macro** (`provenance_badge`, `run_detail.html:299`) rendering 4 possible outcome badges (carried-forward/client-removed/client-supplied/awaiting-reply) keyed by `clarified_fields_by_name`, and a per-employee computed-paystub subtable (gross, pre-tax 401k conditional, FICA SS/Medicare, federal withholding, conditional state withholding, net pay, conditional "Additional Medicare not modeled" note, PDF download link).
- "Payroll details" heading must appear **before** "Reply to client" in document order (`tests/test_dashboard.py:1030`) — an ordering assertion a component-tree React port could easily invert.

**Operator controls** (`run_detail.html:313-348`):
- Approve & Send / Reject pair, only at `awaiting_approval`.
- Re-trigger form, shown for `['error', 'approved', 'received', 'extracting', 'computed', 'sent']` — a **6-status allowlist**, not "anything not terminal" (`needs_operator` and `awaiting_reply` are deliberately excluded — the latter has its own Reject-only escape per B4).
- Demo reply composer (`<textarea>` + submit), only at `awaiting_reply`, pre-filled with placeholder correction text.

**Header cluster + live-status poller** (`run_detail.html:4-96`):
- Status badge + conditional queue badge (`aria-live="polite"`), conditional durability note ("This action is durably saved; you can safely leave this page.", `aria-live="polite"`).
- `?resolution_superseded=1` info callout (`role="status"`), rendered when the redirect encoded that query flag.
- Poller (only rendered — i.e. the `<script>` block is entirely absent server-side — when `run.status in in_flight_statuses or run.has_open_job`): every 2s, `GET /runs/{id}/status`, swaps badge class/text, queue badge class/text/hidden, durability-note text/hidden; **reloads the whole page via `window.location.reload()`** the moment `status !== INITIAL_STATUS` (not just "left the in-flight set" — the in-template comment explains this was a real bug: the earlier version missed the `extracting → awaiting_reply` transition) OR `queue_label !== INITIAL_QUEUE_LABEL`; otherwise stops when settled; 60-attempt cap; network errors silently skipped. This full-page-reload-on-transition behavior is fundamentally different from the `/runs` list poller (which patches in place forever within its cap) and is the **load-bearing reason** the page can stay this simple: every status has different page content (different banner, different forms, different columns), so a full reload is correct here even though it would be wrong on `/runs`.

**Accessibility / progressive enhancement, `/runs/{id}` specific:**
- `aria-live="polite"` on queue badge and durability note (both pages).
- `<section aria-labelledby="conversation-title">`, `<section aria-labelledby="delivery-review-title">`, `<section aria-labelledby="reply-composer-title">` — each region has a real heading id, not just visual structure.
- Every native `<form method="post">` works with JS entirely disabled: Approve/Reject/Resolve/Retrigger/Simulate-reply/all delivery-review actions. Only the poller and the reload-on-transition are JS-dependent; losing JS means the operator must manually refresh, not that any action becomes impossible.
- The `Reject` `onsubmit="return confirm(...)"` guard is native browser `confirm()` — with JS off the form still submits (no confirmation gate), which is itself a documented trade the current build already accepts.

### 1.3 `/eval` (Slice 3) — `app/templates/eval.html`, `app/routes/dashboard.py:150-192`

| # | Behavior | Source | Complexity |
|---|----------|--------|------------|
| E1 | Headline metric strip: Extraction F1 (`%`), Decision Accuracy (computed client-template-side from the confusion matrix: `(true_process+true_clarify)/(true_process+false_process+false_clarify+true_clarify)`, guarded against divide-by-zero), False Process Rate (`%`) | `eval.html:9-26` | LOW — but the divide-by-zero guard and the exact formula must be ported, not re-derived differently |
| E2 | Meta line: `Eval run: {generated_at} — Models: {extraction_model_id}` | `eval.html:27` | LOW |
| E3 | Chart image served from a **committed, build-time-baked** static file `/eval/chart.svg`, not generated per request — `<img src="/eval/chart.svg">` | `eval.html:32`, `app/routes/dashboard.py:200-211` | LOW (React just needs an `<img>`; do not regenerate client-side) |
| E4 | Per-fixture drill-in table: Fixture id, Category badge, truncated (200 char, Jinja `truncate` filter) raw input in `<code>`, expected decision, actual decision, extraction F1 %, PASS/FAIL badge (string-equality of `final_action` vs `expected_final_action`) | `eval.html:36-76` | MEDIUM |
| E5 | `raw_body` is joined server-side per fixture from the committed fixture JSON file (`eval/summary.json` does NOT itself store body text) — a path-traversal-safe join (`resolve()` + `is_relative_to()` containment check) with a `'‹fixture file missing›'` sentinel on failure | `app/routes/dashboard.py:162-183` | LOW (server behavior only, page just displays the string) |
| E6 | Graceful "No eval results available" fallback (with the exact `uv run python eval/run_eval.py` instruction) when `eval/summary.json` doesn't exist | `eval.html:78-86` | LOW |
| E7 | Same demo "Send Test Email" form (fixture picker), identical markup/behavior to `/runs` | `eval.html:88-99` | LOW (shared component candidate) |
| E8 | `aria-current="page"` on nav `Eval` link for any `/eval*` path, live-proven | `base.html:14`, `tests/test_dashboard.py:572-583` | LOW |
| E9 | Table wrapped in the same scrollable/focusable region pattern as `/runs` (`role="region" tabindex="0" aria-label="Fixture drill-in"`) | `eval.html:39` | LOW |
| E10 | No live poller on this page at all — it is a static read of a committed artifact, refreshed only on navigation | (absence, confirmed by no `<script>` block in `eval.html`) | — |

---

## 2. Table stakes vs differentiators vs anti-features

### Table stakes (parity — MUST survive; phase exit criteria)

- **All 5+7+10 = 22 enumerated per-page behaviors above**, verbatim, including the exact ordering assertions (`Payroll details` before `Reply to client`; conversation messages chronological; nav `aria-current` count == 1).
- The **7-branch decision matrix + implicit no-banner state + independent hours-changed overlay** — reproduced as a rendering decision tree, not flattened into a single `elif` chain that accidentally makes the overlay exclusive.
- Both delivery-review variants **and** the third degraded "review unavailable" state, with the confirmation variant's Authorize/Reject mutual exclusivity preserved exactly (this is a named anti-BUG-1 regression pin: `run_detail.html:282` comment + no direct test citation beyond the comment itself — flag this for an explicit new UAT check in Slice 2, since it is currently proven only by code comment + the absence of a counter-test).
- The `?notice=<code>` allow-listed mechanism (`NOTICE_LABELS` dict, `app/routes/operator_feedback.py:25-95`) — the React page must render the SAME fixed label set from the SAME query param, never echo the raw code, and must raise/fail loudly (mirroring `notice_url`'s `KeyError`) rather than silently drop an unrecognized code.
- The `<details class="payroll-details">` native disclosure semantics (works with JS off; React must at minimum preserve the visual/interaction contract, ideally via a real `<details>` element rather than a JS-toggled `<div>`, to keep the JS-off case honest).
- Native `<form method="post">` + 303 for every one of the ~20 mutation routes (approve, reject, resolve, retrigger, simulate-reply, all 6 delivery-review actions, demo send-test) — this is a PROJECT.md-locked decision, not a stylistic preference.
- Progressive enhancement: every mutation must remain reachable and correct with JavaScript disabled. The poller and the reload-on-status-change are pure enhancement; their absence must degrade to "operator manually refreshes," never to "action unavailable."
- Money-safety copy: PII-safe failure vocabulary (bounded stage/reason/attempts labels only, never `error_detail`/`last_error` raw text — `tests/test_dashboard.py:481-651` is the direct regression pin), record-only "drafted and recorded... never" labeling (`tests/test_dashboard.py:1733-1757`), no silent truncation of conversation bodies (`tests/test_dashboard.py:960,989,1023`).
- `aria-live="polite"` regions and `aria-current="page"` nav marking — accessibility affordances that currently work without any JS framework and are trivial to forget in a component rewrite that manages focus/announcement differently.
- The row/run status poller's stop condition and 60-attempt/120s cap, and its explicit choice to swallow fetch errors per tick (not surface them) — silently "fixing" this into a toast/error state would change observable behavior under test.

### Differentiators (things React genuinely makes better here — name them specifically)

| Differentiator | Where it helps | Why React is a genuine win |
|---|---|---|
| **The poller as a typed hook** (`useRunPoll` / `useRunListPoll`) | `/runs` row poller (R8) and `/runs/{id}` header poller | Today the poller logic is duplicated (with subtly different reload semantics) between `runs_list.html:10-59` and `run_detail.html:32-95`. A shared, typed hook that takes `(runId, mode: 'patch-in-place' | 'reload-on-change')` collapses two near-duplicate vanilla-JS blocks into one tested unit — this is the single strongest case for the conversion. |
| **The 8-way-shaped decision-banner render** as a discriminated union / exhaustive switch | `/runs/{id}` banner matrix | TypeScript's exhaustiveness checking on a discriminated union over `RunStatus`/`final_action`/`delivery_review` combos catches "you added a 9th state and forgot to handle it in the banner" at compile time — something the current `if/elif` chain cannot do (the implicit no-banner fallthrough above is exactly the kind of silent gap a `never`-checked switch would force a developer to acknowledge). |
| **The disclosure's provenance-badge macro** (`provenance_badge`, `run_detail.html:299`) | payroll-details section | A small typed component (`<ProvenanceBadge outcome=... />`) replacing an inline Jinja macro reads and tests better, and its 4-value enum is a natural TS union. |
| **Delivery-review action-eligibility booleans as typed props** | both delivery-review variants | `can_replay` / `can_fresh_send` / `blocker` are already computed server-side (§1.2) — React's job is just to consume them as typed booleans and never recompute a category string client-side. This is a place where TypeScript's type system can make the "never offer an action the classification forbids" invariant a compile-time-checked prop contract instead of a comment. |
| **Shared "demo send-test" form** as one component | `/runs`, `/eval` (identical markup today, duplicated) | Straightforward DRY win once both pages are componentized — low risk, low complexity. |

### Anti-features (things a React rewrite is tempted to add — refuse these)

| Anti-feature | Why it's tempting | Why it's wrong here |
|---|---|---|
| **Client-side routing between operator pages** (React Router across `/runs`, `/runs/{id}`, `/eval`) | "It's an SPA now, why hard-navigate?" | PROJECT.md's falsified-decision #3 already established these are three **independently deployable vertical slices**, and `/` and `/ops` deliberately stay Jinja and outside the bundle. A client router spanning pages that don't all exist in the same deploy (Slice 1 ships before Slices 2/3) would either 404 or require faking routes for not-yet-built pages. Each converted page should be its own mount point navigated via normal `<a href>` / full page loads, exactly like today. |
| **Optimistic UI on money-moving mutations** (Approve & Send, Resolve & Resume, Authorize a new confirmation) | Standard SPA UX pattern — "show it approved immediately, roll back on error" | These are literally the single human gate and the delivery-authorization gate for a payroll system. `claim_status` is an atomic CAS specifically because a second concurrent approval must lose and no-op (`app/routes/runs.py:404-411`). An optimistic UI that shows "Approved" before the 303 lands can show a state that isn't real, exactly the class of bug the whole codebase's CAS discipline exists to prevent. Always wait for the server round-trip. |
| **A client-side data cache that can show stale payroll state** (React Query / SWR caching run details across navigations) | Avoids "refetch on every visit" | A cached, possibly-stale `run.status` or `run.decision` displayed after a mutation (e.g., viewing a run, approving it in another tab, then navigating back to a cached view) is exactly the kind of drift the poller's `reload-on-status-change` behavior is designed to eliminate today. Any client cache must be invalidated on every navigation to a run detail page at minimum; simplest safe answer is no cross-navigation cache at all — reload fresh, matching current behavior. |
| **A spinner replacing server-rendered first paint on a cold-started free-tier instance** | "Show a loading state while the bundle hydrates" | Render's free tier cold-starts in ~1 minute after 15 minutes idle (documented project constraint). A blank-page-then-spinner-then-content sequence during a cold start reads as broken far worse than a slow-but-real server-rendered page. The React pages should still be served with real initial data in the HTML response (SSR/prerender the initial JSON payload into the mount, not client-fetch-on-mount) so first paint shows real content, not a spinner. |
| **Re-deriving `can_replay`/`can_fresh_send`/badge classes client-side from raw status strings** | Feels more "React-native" than consuming server-computed booleans | Explicitly the thing `_safe_delivery_review_projection`'s docstring (`app/routes/runs.py:311-322`) says the reduction boundary exists to prevent — "so a template edit can never accidentally offer an action the classification says cannot succeed." Consume the booleans; never reconstruct them from `failure_category` text. |
| **A generic "toast on fetch error"** on the pollers | Nicer perceived UX than silent skip | Both existing pollers explicitly swallow fetch errors per tick (`.catch(function() {})`) as a deliberate network-blip guard, counting toward the same attempt cap. Surfacing errors would change observable behavior under the existing 60-attempt-cap tests and would likely spam transient blips during a Render cold start. |

---

## 3. Complexity summary (for slice sizing)

| Slice | Behavior count (table-stakes items) | Complexity mix | Notable HIGH items |
|---|---|---|---|
| **Slice 1** (`/runs` + toolchain + Docker + CI) | 14 | 1 HIGH, 4 MEDIUM, 9 LOW | R8 (in-place row poller) is the one HIGH item and the primary reason this slice exists first — everything else here is comparatively mechanical, which is why toolchain/Docker/CI risk (not UI risk) dominates Slice 1's actual cost. |
| **Slice 2** (`/runs/{id}`) | ~30 (banner branches, both delivery-review variants + degraded state, conversation thread, disclosure, controls, header poller) | 2 HIGH (decision-banner matrix, delivery-review variants), rest split MEDIUM/LOW | By far the heaviest slice — size it accordingly; the roadmapper should not treat "3 roughly equal phases" as a safe default. |
| **Slice 3** (`/eval`) | 10 | 0 HIGH, 2 MEDIUM, 8 LOW | Lightest slice — static-artifact display with one server-computed metric formula to port exactly (E1). |

---

## 4. Dependencies on existing behavior (must NOT change)

- **Native `<form method="post">` + 303-redirect mutation semantics.** Every one of the ~20 mutation routes in `app/routes/runs.py` and `app/routes/demo.py` returns a `RedirectResponse(..., status_code=303)`, several encoding state into the redirect target itself (`?resolution_superseded=1` at `app/routes/runs.py:626`, the newly created run id at `app/routes/demo.py:252`). React pages must issue the SAME POST + follow-the-303 flow — a `fetch()` + manual re-fetch-and-re-render loses the encoded redirect state and the `onsubmit="return confirm(...)"` native guard.
- **The `?notice=<code>` allow-listed operator-feedback mechanism.** `app/routes/operator_feedback.py` is a fixed vocabulary (`NOTICE_LABELS`) reduced server-side; the query param must never be echoed raw, and an unrecognized code must render no banner (mirrors `notice_label`'s `dict.get(..., None)` semantics) rather than a passthrough string.
- **The `js-` prefixed poller hook classes are live selectors, not dead markup**, but **only in `runs_list.html`** (`js-status-badge`, `js-failure-secondary`, `js-failure-summary`) — `run_detail.html`'s poller instead uses element `id`s (`run-status-badge`, `run-queue-badge`, `run-durability-note`). A React port replacing these with component state removes the DOM-selector coupling entirely (a legitimate simplification), but must preserve the exact element/attribute pairs the poller currently updates (class + text content + `hidden` boolean, never a CSS `display` toggle) since `hidden` is what several tests assert on.
- **The design tokens** (`--space-*`, `--radius-*`, `--font-sans`/`--font-mono` custom properties, `app/static/style.css:7-59`) — badge classes (`badge-good`/`badge-bad`/`badge-pending`/`badge-neutral`/`badge-escalate`/`badge-running`), banner classes (`banner-process`/`banner-clarify`/`banner-awaiting`/`banner-error`), and the disclosure/conversation/delivery-review component classes are an established visual system already shared with `/` and `/ops` (which stay Jinja). The React pages must consume the SAME `style.css` (or a token-identical CSS Modules/styled system) rather than fork a parallel design system, or `/ops` and `/` will visibly diverge from the converted pages.
- **`_safe_run_for_browser` / `_safe_delivery_review_projection` as the sole reduction boundary.** Any new JSON endpoint the React pages fetch from must reuse these existing reduction functions (or equivalents with identical field sets) rather than re-serializing `RUN_COLS` directly — this is PROJECT.md's falsified decision #2, and building a new Pydantic allowlist DTO risks exactly the field-exposure regression that falsification already found.
- **`IN_FLIGHT_STATUSES` frozenset** (`app/routes/runs.py:84-86`) and the 6-status retrigger-eligible set (`error, approved, received, extracting, computed, sent`, `run_detail.html:327`) are the two authoritative status-set constants driving poller/control visibility — these must be threaded from the server response (already are, as `in_flight_statuses`) rather than hardcoded a second time in TypeScript, or a future status addition silently desyncs the two implementations.
- **`GET /runs/{id}/status`** (`app/routes/runs.py:890-917`) is the one existing JSON endpoint already shaped for this conversion — it returns exactly the fields both pollers consume (`status`, `badge_class`, `badge_label`, `failure`, `queue_label`, `queue_badge_class`, `has_open_job`) and already goes through `_safe_run_with_queue_projection`. Slice 1/2 should reuse this endpoint as-is rather than inventing a new one.

---

## 5. What is only *asserted by tests*, not obvious from the templates

These are the parity-contract items most likely to be silently dropped by a planner who reads only the HTML:

- **The Authorize/Reject mutual exclusivity in the confirmation delivery-review variant** is explained only by an inline template comment (`run_detail.html:282`) — there is no direct positive test proving "when `can_fresh_send` is true, Reject never renders" (only the general delivery-review shape tests exist). Flag this as needing an explicit new test in Slice 2, since the comment alone will not survive a component rewrite that doesn't also read it.
- **The full-page reload semantics of the `/runs/{id}` poller** — "reload whenever `status !== INITIAL_STATUS` OR `queue_label !== INITIAL_QUEUE_LABEL`, not just 'left the in-flight set'" — is a fix for a real regression (missing the `extracting → awaiting_reply` transition), asserted at `tests/test_dashboard.py:1604-1693` (`test_run_detail_inflight_poll_reloads_on_settle`, `test_run_detail_poll_reloads_on_status_change_not_just_settle`). A React implementation using local component state instead of a hard reload must reproduce this exact "any observable status OR queue-label delta re-syncs everything" trigger, not just "left the in-flight set."
- **No silent truncation of conversation message bodies** past 300 characters — asserted with a deliberately >300-char fixture (`tests/test_dashboard.py:960,989,1023`); nothing in the template itself signals this (`<pre>{{ msg.body_text }}</pre>` looks unbounded, but only the test proves no filter/truncate was silently reintroduced).
- **Exactly one `>Conversation<` heading, chronological order, and `>inbound<`/`>outbound<` badge counts** are asserted with exact `.count()`/`.index()` checks (`tests/test_dashboard.py:1015-1021`) — a React key-based render that reorders on data changes (common with unstable array keys) could violate this silently.
- **The clarification delivery-review card never renders confirmation-only controls** (`Mark delivered`, `Authorize a new confirmation`, the `AUTHORIZE A NEW CONFIRMATION` literal, `Resolve & Resume`, `remember this alias`) — proven by explicit `not in response.text` assertions (`tests/test_dashboard.py:1393-1398`), not evident from reading the clarification branch of the template alone (you'd have to also read the confirmation branch to know what must NOT bleed across).
- **`record_only` outbound-message labeling is send_state-independent** — a `record_only` run's outbound message still has `send_state='sent'` in the DB (the record-only "send" genuinely completed its own branch), so the "recorded, not sent" label is driven by a *separate* flag (`get_record_only_flag`, `app/routes/runs.py:1330-1334`), not by inspecting `send_state`. This distinction is invisible from the template's simple `{% if record_only and msg.direction != 'inbound' %}` guard unless you trace where `record_only` itself comes from.
- **The negative pin that `<meta http-equiv="refresh">` never appears on either page** (`tests/test_dashboard.py:400-418,1694-1711`) is a regression guard for a fix that predates this milestone — a React SSR/hydration setup that (re)introduces a meta-refresh fallback for no-JS support would violate this pin even though it might feel like a reasonable accessibility fallback.
- **`aria-current="page"` fires from `request.url.path` resolving live through `base.html`**, proven with an exact `count() == 1` assertion per route (`tests/test_dashboard.py:572-583`) — a React router's active-link logic must produce exactly one match per page, including for `/runs/{id}` (which is not one of the three routes directly tested but shares the identical `nav_path.startswith('/runs/')` wiring, `base.html:13`).
- **Diagnostic/failure text is bounded by a strict regex grammar and cross-checked against `error_reason`**, not just "hide `error_detail`" — `_safe_failure_presentation` (`app/routes/runs.py:161-217`) refuses to render `stage`/`reason`/`attempts` at all unless the full string matches `_DIAGNOSTIC_CODE_RE` AND the run-level `error_reason` agrees with the parsed reason (with special-cased exceptions for `FinalAttemptLeaseExpired`/`RetryExhausted`). This asymmetric validation is proven by both a positive case and a "malformed detail string produces NONE of the derived labels" falsification (`tests/test_dashboard.py:586-651`) — a React port that just does `error.stage && <span>{error.stage}</span>` without the matching cross-check would be strictly more permissive than the current behavior.

---

## Orchestrator addendum (verified against source 2026-08-17)

Two findings surfaced by a second, independent research run on the same brief. Both were
re-verified directly against the cited source by the orchestrator before being recorded here;
everything else in this document comes from the run that wrote it.

- **The provenance badges require a route-side re-keying join, not just a lookup.**
  `repo.load_clarified_fields(run_id)` returns outcomes keyed by **`employee_id`**
  (`app/routes/runs.py:1273`), which the route then re-keys to **`submitted_name`** by walking the
  reconciliation (`app/routes/runs.py:1281-1285`) and passes to the template as
  `clarified_fields_by_name` (`app/routes/runs.py:1345`). The template's `provenance_badge` macro
  (`run_detail.html:299`) consumes only the re-keyed form. **Consequence for the JSON projection:**
  a DTO cannot expose the raw `clarified_fields` and expect the client to resolve badges — the
  employee_id→submitted_name mapping lives in the reconciliation, so the API must either perform
  this join server-side (preferred; keeps the existing behavior byte-for-byte) or ship all three
  source collections and re-implement the join in TypeScript (a second source of truth for a
  provenance label attached to money fields — reject). The `except`/degrade path at
  `app/routes/runs.py:1287-1288` sets the mapping to `{}` on repo failure rather than erroring,
  so the DTO must model "badges unavailable" as a legitimate state, not an error.

- **The `queue_label` half of the poller's reload trigger.** The reload condition is
  `data.status !== INITIAL_STATUS || data.queue_label !== INITIAL_QUEUE_LABEL`
  (`run_detail.html:76`) — a queue-label transition alone (Running / Queued / Retry queued) forces
  the full re-sync even when `status` is unchanged. A port that watches only `status` silently
  drops half this trigger.

**Toolchain risk that lands on this page (cross-reference to `STACK.md:185`).** STACK.md recommends
Biome over ESLint and concedes that Biome's React-hooks rule coverage is thinner than
`eslint-plugin-react-hooks`. The poller is an effect-dependency problem: a stale dep array
reintroduces exactly the `extracting → awaiting_reply` staleness bug that the in-source comment at
`run_detail.html:39-44` documents as already-fixed, and `exhaustive-deps` is the rule that catches
that class. Whichever slice converts the poller must prove the reload trigger behaviorally (both
halves of the OR, against a status change AND a queue-label-only change) rather than relying on
lint to catch a wrong dependency list.

---

## Sources

- `app/templates/runs_list.html`, `app/templates/run_detail.html`, `app/templates/eval.html`, `app/templates/base.html`, `app/templates/_operator_notice.html` — full read.
- `app/routes/runs.py` (1534 lines, full read across two passes), `app/routes/dashboard.py`, `app/routes/operator_feedback.py`, `app/routes/templating.py`, `app/routes/demo.py` — full read.
- `app/static/style.css` — grepped for `js-` selectors (confirmed: none exist as CSS rules; all three `js-` classes are pure JS hooks) and design-token declarations.
- `tests/test_dashboard.py` (2,296 lines) and `tests/test_needs_operator.py` (2,223 lines) — function-name inventory plus targeted reads of the tests cited by line number above; these two files are the behavioral spec per the milestone context and PROJECT.md's own characterization ("2,218 LOC / 85 markup assertions" + "2,009 LOC / 10").
- `.planning/PROJECT.md:182-217` (Current Milestone: v5 section) — locked scope, non-goals, and the three falsified decisions.
