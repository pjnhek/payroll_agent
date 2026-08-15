---
quick_id: 260814-q0y
title: Operator-surface defect sweep (12 bugs + demo deliverability)
mode: quick
baseline: 78542f1
source: BRIEF.md (authoritative scope; diagnoses verified against live source, not re-litigated here)
tasks: 12
commits: 12
autonomous: false
---

# PLAN: operator-surface defect sweep

Twelve commits. Each one leaves the tree green (`uv run pytest -q` + `uv run ruff check .` +
`uv run mypy` all clean). Nine of the thirteen items collapse onto one shared mechanism built
in T1; the money gate (BUG-3) is isolated and lands only after that mechanism is proven on
four lower-stakes handlers.

Read the **Design flags** section before starting T0. Four of the BRIEF's premises are wrong
or incomplete, and two of them change what gets built.

---

## Design flags (read first)

The BRIEF asked for these to be surfaced rather than silently followed.

### 1. The BRIEF's test-placement constraint is wrong, and it would push tests into the wrong files

**BRIEF says:** "`tests/test_dashboard.py` and `tests/test_needs_operator.py` are
`@pytest.mark.integration` and do NOT run in CI."

**Measured this session:**

```
uv run pytest tests/test_needs_operator.py tests/test_dashboard.py --collect-only -q
  -> 92 tests collected
uv run pytest ... -m "not integration" --collect-only -q
  -> 89/92 collected (3 deselected)
```

The marker is applied **per test**, never at module level: `test_needs_operator.py:419` (1 test),
`test_dashboard.py:1915` and `:2203` (2 tests). 89 of 92 tests in those two files run in CI on
every push. `ci.yml:77` runs a bare `uv run pytest -q` with no `-m` deselect at all.

**Consequence:** `test_needs_operator.py` is the correct home for the BUG-5 `/resolve` tests. It
already owns the whole `/resolve` harness (`:1310` onward, seven POST tests) and it runs in CI.
Relocating those tests to a new file to satisfy a false constraint would fork the harness.

- **A. (recommended)** Put each test next to the harness that already exercises the route, and
  add `@pytest.mark.integration` to nothing new. Verify placement with a per-test collect
  (`-m "not integration"`) rather than by file name.
- B. Honor the BRIEF literally and create new CI-safe files for resolve/dashboard coverage.
  Costs a duplicated harness and leaves the real files' coverage frozen.
- C. Do nothing; accept the risk that a test lands in a deselected node.

### 2. BUG-1's most likely real-world trigger is a vocabulary mismatch the BRIEF did not name

`_delivery_failure_category` (`app/db/repo/job_settlement.py:140-165`) can return
**`authorization_expired`**. `_DELIVERY_REVIEW_CATEGORY_LABELS` (`app/routes/runs.py:123-133`)
does not contain that key. So `_load_delivery_review` rejects the run at `runs.py:296` and
returns `None`, while `_is_delivery_review_marker` still returns `True`. That is exactly the
BUG-1 dead end: red "Action required" badge, zero buttons.

This is not hypothetical. `app/queue/handlers/send_outbound.py:54` and `app/email/gateway.py:163`
both emit `DELIVERY_AUTHORIZATION_EXPIRED`; `job_settlement.py:465-481` routes a pre-provider
expiry straight into `_settle_delivery_review`; and `tests/test_phase20_fake_parity.py:311`
already asserts `error_detail == "delivery_review:authorization_expired"` lands on the run.

The vocabulary exists in **four** places that can drift independently:
`job_settlement.py:140` (producer), `runs.py:123` (renderer), `app/db/schema.sql:495` and `:525`
(CHECK constraints). Patching one key would leave the drift class alive.

- **A. (recommended)** T0 makes the vocabulary a single source of truth in a new leaf module
  and adds a drift test pinning producer + renderer + schema CHECK to it. One-line behavior fix,
  structural guarantee, matches the repo's existing `test_status_drift.py` / `test_job_kind_drift.py`
  culture (and is the same "pin the map to the enum" remedy BUG-12 asks for).
- B. Add `"authorization_expired": "Delivery authorization expired"` to the dict and move on.
  Fixes today, permits the next drift.
- C. Do nothing and let T8 (the dead-end escape) cover it. Rejected: the escape treats the
  symptom while a renderable review is silently thrown away.

### 3. BUG-2's premise ("both Retry buttons") is half wrong, and the dangerous button is a different one

Grepped every form action in `app/templates/`. There is exactly **one** Retry button:
`run_detail.html:265`, `/delivery-review/clarification/retry-now`. The confirmation route
`retry_delivery_now` (`runs.py:970`) has **no form in any template**; it is POST-reachable but
not offered.

The confirmation card's risky offer is **"Authorize a new confirmation"** (`run_detail.html:273`),
which its own help text describes as "may send the client a second email". Under the
live-proven `validation` category (Resend 403 on a `.example` recipient) that action mints a new
snapshot, a new job, and a new provider call that fails identically, and it costs a delivery slot
to learn nothing. That is a worse offer than an unretryable Retry.

Also, the two actions do not share retry semantics. Replaying the identical frozen email under the
same idempotency key (`gateway.py:167` keys on `message_id`) is a different question from minting
a fresh slot. `payload_mismatch` (Resend 409 `invalid_idempotent_request`) is **terminal for
replay but curable by a fresh slot**; `final_attempt_lease_expired` is the same shape. A single
`terminal|retryable` boolean gets both of those wrong.

- **A. (recommended)** Model two booleans per category, `replay_same_ok` and `fresh_send_ok`, on
  one frozen dataclass. Ten rows, one dict, one table-driven unit test. Gates the clarification
  Retry on `replay_same_ok` and "Authorize a new confirmation" on `fresh_send_ok`, and gets
  `payload_mismatch` / `final_attempt_lease_expired` right instead of backwards.
- B. Single `retryable: bool` as the BRIEF describes. Simpler, but suppresses the one action that
  would actually work for `payload_mismatch`, which is a new instance of the exact defect BUG-2
  is about.
- C. Do nothing on the confirmation card, gate only the clarification Retry. Leaves the more
  expensive wrong offer in place.

Note on wording: `authorization` (401/403), `configuration` (missing API key) and `validation`
are not "can never succeed", they are "will fail identically until something out of band
changes". The copy must say which thing, not claim impossibility. That is why the dataclass
carries a `blocker` sentence rather than just a flag.

### 4. BUG-1's fix must be option (b), and Re-trigger must NOT be one of the offered escapes

The BRIEF leaves the choice open between stopping the `run_detail.html:111` branch from firing
and giving the `:276` card its own actions.

Falling through to the generic `needs_operator` branch (`:115`) would render the resolve form,
but `resolve()` guards `_is_delivery_review_marker` at `runs.py:542` and returns a bare 303. That
converts BUG-1 into a fresh BUG-5: a form that appears to work and silently does nothing.

Offering Re-trigger has the same problem: `retrigger()` guards the marker at `runs.py:736` and
303s. Reject is the only escape that actually completes, because `reject()` accepts
`NEEDS_OPERATOR -> REJECTED` (`runs.py:495`).

- **A. (recommended)** Give the `:276` card a Reject form only. Keep the "Action required" badge.
  Do not relax the `:542` / `:736` marker guards: they exist because a possible provider
  acceptance must be resolved through its purpose-aware review, and evidence being unloadable
  makes that *more* true, not less.
- B. Also offer Re-trigger and relax the `runs.py:736` guard when `_load_delivery_review` returns
  `None`. Rejected: it lets a run whose frozen reservation cannot be inspected restart the
  pipeline and possibly re-send.
- C. Do nothing beyond T0 (which removes the most common trigger). Leaves a genuine dead end for
  any other `None` cause (snapshot row gone, `attempt_count` out of range, purpose mismatch).

### 5. FIX A must override at reservation time, not at send time

Both `to_addr` resolutions are at snapshot-reservation sites: `app/pipeline/delivery.py:155`
(`to_addr=inbound.from_addr if inbound else ""`) and `app/pipeline/clarification.py:473`
(`to_addr=email.from_addr`).

Overriding inside `gateway.send_outbound` instead would (a) make "View frozen email" on the
delivery-review card show a recipient different from the one actually mailed, which is an audit
lie on the one surface whose entire job is evidence, and (b) break replay: the Resend idempotency
key is the `message_id` (`gateway.py:167`), so flipping `DEMO_OUTBOUND_TO` between an attempt and
its replay would reuse one key with two different payloads, which is precisely the
`invalid_idempotent_request` 409 that becomes `payload_mismatch`. Freezing the resolved recipient
into the snapshot makes every replay of that snapshot byte-identical regardless of config.

This also satisfies the BRIEF's "well away from the Phase 20 at-most-once machinery": the
override runs before reservation, before `enqueue_job`, before any key is minted.

Also note the override does not disturb reply threading. `simulate_reply` takes `from_addr` from
the run's **source inbound** email (`runs.py:1422`), never from an outbound `to_addr`, so the
sender spoof guard and `find_business_by_sender` are untouched.

---

## Sequencing rationale

1. **T0 first** even though it is not TIER 1 by the BRIEF's numbering: it is a one-line behavior
   fix that removes the most reachable cause of the TIER-1 dead end, and it establishes the
   category vocabulary that T7, T8 and T9 all consume.
2. **T1 builds the shared mechanism** and proves it by migrating the three codes 78542f1 already
   shipped. Net mechanism count stays at one; `_SIMULATE_REPLY_ERROR_LABELS` is deleted, not
   duplicated.
3. **T2 through T5 apply it** in ascending order of stakes: retrigger, delivery-review outcomes,
   resolve, authorize. By the time T6 touches `approve`, the mechanism has four proven consumers
   and 20+ regression tests.
4. **T6 (approve) is alone in its commit** and is feedback-only.
5. **T7 through T9** are the classification and the two cards that consume it.
6. **T10 (BUG-12) and T11 (FIX A)** are independent of everything above and could be reordered.

Green after every commit. No task depends on a later task.

---

## Shared conventions for every task

- `uv run` for everything. Never pip/venv/poetry.
- RED first: write the failing test, run it, confirm it fails **for the stated reason**, then fix.
- Commit messages: conventional, no emojis, no em-dashes, one line + optional short body.
- Do not touch `app/pipeline/calculate.py`, `federal_withholding.py`, `tax_tables_2026.py`, or
  `app/queue/` durability.
- Do not add JS to `ops.html` (`tests/test_ops_route.py:364` asserts `"<script"` is absent).
- Verify test placement with `uv run pytest <file> -m "not integration" --collect-only -q` and
  confirm the new test is in the collected set.

---

## T0: single-source the delivery-review category vocabulary (root cause of BUG-1)

**Files**
- `app/models/delivery_review.py` (new, leaf module, stdlib imports only)
- `app/routes/runs.py:123-133` (delete `_DELIVERY_REVIEW_CATEGORY_LABELS`, import instead)
- `tests/test_status_drift.py` (add), or `tests/test_delivery_review_vocabulary.py` (new)

**RED test** (`tests/test_status_drift.py`, CI-running, already the home for enum-drift pins)

Three assertions, no HTTP:
1. Every string `_delivery_failure_category` can return is a key of the shared category map.
   Derive the producer's outputs by calling it once per `PipelineReason` member rather than by
   transcribing a list, so a new reason cannot pass silently.
2. The literal `"final_attempt_lease_expired"` written at `job_settlement.py:1103` is a key.
3. The `failure_category` CHECK list parsed out of `app/db/schema.sql:495` equals the shared
   map's keys plus `'none'`.

Assertion 1 fails today on `authorization_expired`.

**GREEN**

Create `app/models/delivery_review.py` holding one dict keyed by category string. For T0 it
carries only `label` (the exact strings currently at `runs.py:123-133`) plus the new
`authorization_expired` entry; T7 extends the value type. Suggested label:
`"Delivery authorization expired"`.

`runs.py` imports the map and keeps the existing local name bound to it so `:296` and `:355`
need no other edit.

**Verify**

```
uv run pytest tests/test_status_drift.py -q
uv run pytest -q && uv run ruff check . && uv run mypy
```

**Done:** a run with `error_detail = "delivery_review:authorization_expired"` renders a populated
delivery-review card instead of the actionless "unavailable" card. Assertion 1 red-proofs by
deleting the new entry.

**Commit:** `fix(delivery-review): render authorization_expired reviews instead of dead-ending`

---

## T1: shared operator-notice mechanism, proven by migrating simulate_reply

This is the DRY core. Nine handlers consume it; none of them gets a bespoke solution.

**Files**
- `app/routes/operator_feedback.py` (new)
- `app/templates/_operator_notice.html` (new, shared include)
- `app/routes/runs.py` (delete `_SIMULATE_REPLY_ERROR_LABELS` at `:141-155`; `run_detail`
  signature at `:1165-1171`; context at `:1270-1272`; the three `simulate_reply` returns at
  `:1406`, `:1418`, `:1454`)
- `app/templates/run_detail.html` (add the include after the `resolution_superseded` callout at
  `:18-22`; delete the in-composer error block at `:331-335`)
- `tests/test_reply_redelivery.py` (update the 19 existing `simulate_reply_error` references)
- `tests/test_operator_feedback.py` (new)

**Shape**

```
NOTICE_LABELS: dict[str, str]              # code -> fixed safe sentence, the ONLY vocabulary
def notice_label(code: str) -> str | None  # allow-list reduction, unknown -> None
def notice_url(base: str, code: str) -> str
def notice_redirect(base: str, code: str) -> RedirectResponse   # raises KeyError on unknown code
```

`notice_url` takes a base path (not a run id) so `demo.py`'s `/` and `/runs` redirects in T5 use
the same function. One query param name for the whole app: `?notice=<code>`.

Carry over the "hostile until proven fixed" docstring from `runs.py:141-145`: the reduction to a
fixed label happens server-side before the template ever sees a value, so a hand-crafted URL
renders no banner rather than an attacker-chosen string.

**RED tests** (`tests/test_operator_feedback.py`, new, no `integration` marker)

1. `notice_label("<script>alert(1)</script>")` returns `None`.
2. Every value in `NOTICE_LABELS` is non-empty and contains no `<`, `>`, `{`, `}`.
3. **Call-site drift pin (the durable guard):** AST-parse `app/routes/runs.py` and
   `app/routes/demo.py`, collect every string literal passed as the `code` argument of a
   `notice_redirect(...)` call, and assert each is a key of `NOTICE_LABELS`. This is what stops
   T2 through T5 from shipping a code that renders nothing. Mirrors `test_job_kind_drift.py`.
4. `notice_redirect("/runs/x", "not_a_real_code")` raises `KeyError`.

Plus, in `tests/test_reply_redelivery.py`, flip the three existing assertions from
`simulate_reply_error=no_proof` to `notice=reply_no_proof` (and the two siblings) and assert the
label text appears in the run-detail body. These fail before the migration.

**GREEN**

Seed `NOTICE_LABELS` with exactly the three migrated codes, namespaced:
`reply_no_proof`, `reply_missing_source`, `reply_enqueue_failed`, keeping the sentence text from
`runs.py:146-155` verbatim.

**Note the banner moves to the top of the page, deliberately.** After a POST-redirect-GET the
browser lands at the top; the current placement inside the reply composer (`run_detail.html:331`)
is below the fold on a long run-detail page, so the operator can miss it entirely. One notice
region, one placement, every code.

**Verify**

```
uv run pytest tests/test_operator_feedback.py tests/test_reply_redelivery.py -q
grep -rn "simulate_reply_error" app/ tests/    # must return nothing
uv run pytest -q && uv run ruff check . && uv run mypy
```

**Done:** one notice mechanism exists, the old one is deleted (not shadowed), and the drift pin
is live before any new consumer is written.

**Commit:** `refactor(operator-feedback): one allow-listed notice code path for silent redirects`

---

## T2: BUG-6, retrigger tells the operator why it refused

Lowest-stakes consumer. Proves the mechanism on a real handler before anything money-adjacent.

**Files:** `app/routes/runs.py:736-737` (delivery-review marker), `:767-769`
(`ActiveOutboundProviderHandoffError`); `app/routes/operator_feedback.py` (2 codes);
`tests/test_hitl.py` (owns the retrigger harness at `:275`) or `tests/test_stuck_run_recovery.py`.

**Codes:** `retrigger_delivery_review`, `retrigger_active_handoff`.

Suggested text, naming the actual next step rather than the internal condition:
- `retrigger_delivery_review`: "This run is held by a delivery review. Resolve the delivery review
  below before re-triggering."
- `retrigger_active_handoff`: "A send for this run is still in flight with the email provider.
  Wait for it to settle, then try again."

**RED test:** two tests, each driving `POST /runs/{id}/retrigger` with `follow_redirects=False`,
asserting the `location` header carries the expected `?notice=` code, and that the run's status is
unchanged. Then a third asserting the rendered detail page contains the label.

**GREEN:** replace the two bare `RedirectResponse(url=f"/runs/{run_id}", status_code=303)` returns
with `notice_redirect(f"/runs/{run_id}", "<code>")`. No control-flow change; the guards, the
transaction boundary, and the post-commit `wake.wake()` are untouched.

**Verify:** `uv run pytest tests/test_hitl.py -q` then the full gate.

**Commit:** `fix(retrigger): explain the two refusals instead of a silent reload`

---

## T3: BUG-7, BUG-8, BUG-9, the delivery-review outcome handlers

One family, one commit. Four handlers, six sites.

**Files:** `app/routes/runs.py:986-990` (`retry_delivery_now`), `:1009-1013`
(`retry_clarification_delivery_now`), `:1047-1049` (`_finish_clarification_delivery_review`),
`:1075-1081` and `:1090-1092` (`mark_delivery_delivered`); `operator_feedback.py`;
`tests/test_phase20_clarification_review.py`.

**Test placement:** `tests/test_phase20_clarification_review.py`. It is not integration-marked,
it runs in CI, and it already owns `_clarification_review_run` / `_confirmation_review_run` /
`_attach_active_handoff` plus a module-level `TestClient(app, raise_server_exceptions=False)`.
Reuse those builders; do not write new ones.

**BUG-9 is not one code, it is four.** Both retry handlers currently collapse
`AdvanceSendJobOutcome.{ADVANCED, MISSING, EXPIRED, NOT_PENDING}` plus a swallowed exception plus
"wrong review kind" into a single return. `app/db/repo/jobs.py:62-68` already gives the outcome
vocabulary; surface it:

| outcome | code | meaning to say |
|---|---|---|
| `ADVANCED` | none (silent success) | the page re-renders with the job queued |
| `MISSING` | `retry_missing` | there is no send job left for this frozen email |
| `EXPIRED` | `retry_expired` | the 20-hour replay window for this reservation has closed |
| `NOT_PENDING` | `retry_not_pending` | a send for this email is already in flight |
| exception | `retry_unavailable` | could not reach the database; try again |
| wrong kind / no review | `review_unavailable` | this run no longer has a loadable delivery review |

For BUG-7 (`mark_delivery_delivered`) the CAS-lost return at `:1081` gets `review_state_changed`
("This run's state changed while you were reading. Reload and check the current status.") and the
swallowed exception at `:1090` gets `review_unavailable`.

For BUG-8, `_finish_clarification_delivery_review` swallows at `:1047`, which silently no-ops
**both** "Mark handled" and clarification "Reject". Track whether the transaction body reached a
successful claim and emit `review_state_changed` on a lost CAS, `review_unavailable` on the
exception. Do not narrow the `except Exception` and do not let the exception escape: the handler's
existing fail-soft contract is correct, only its silence is not.

**RED tests:** one per code, six total. Drive each through the real HTTP route with a fake_repo
seam forced into the target outcome (`monkeypatch` on
`repo.advance_existing_send_job_due_now` for the three outcome codes; a `repo.get_connection`
that raises for the `_unavailable` codes; a status flip for `review_state_changed`). Assert both
the redirect `location` and that no state changed.

**Verify:** `uv run pytest tests/test_phase20_clarification_review.py -q` then the full gate.

**Commit:** `fix(delivery-review): surface why a review action did nothing`

---

## T4: BUG-5, the six resolve guards

**Files:** `app/routes/runs.py:538-541`, `:542-546`, `:550-553`, `:555-559`, `:570-579`,
`:602-606`; `operator_feedback.py`; `tests/test_needs_operator.py`.

**Test placement:** `tests/test_needs_operator.py`, which owns the `/resolve` harness from `:1310`
and runs in CI (see Design flag 1). Confirm with
`uv run pytest tests/test_needs_operator.py -m "not integration" --collect-only -q`.

| line | guard | code |
|---|---|---|
| `:541` | status is not `needs_operator` | `resolve_not_needs_operator` |
| `:546` | delivery-review marker owns the run | `resolve_delivery_review` |
| `:553` | no `unresolved_names` on the decision | `resolve_nothing_unresolved` |
| `:559` | roster load failed | `resolve_roster_unavailable` |
| `:579` | posted `employee_id` missing or off-roster | `resolve_invalid_employee` |
| `:606` | `ValueError` from `commit_operator_resume_resolution` | `resolve_superseded_conflict` |

`:579` is the one the BRIEF singles out: an operator who leaves a dropdown on the
"select employee" placeholder gets an identical page and no explanation. Its text must say the
whole submission was rejected and nothing was applied, because that is the load-bearing safety
property at `runs.py:562-581` and the operator cannot currently tell partial from none.

**Do not** name the index, the token, or the submitted id in the label. The whole point of the
allow-list is that no request-derived text reaches the URL or the page. The existing
`logger.warning` at `:573-578` keeps the index for debugging; that is the right split.

**`:606` interaction:** `resolve_superseded_conflict` is the *rejected* generation. It is distinct
from the existing `?resolution_superseded=1` at `:610`, which is the *accepted-but-not-authoritative*
generation. Two different outcomes, two different messages. Leave `resolution_superseded` alone
(it is a `role="status"` info callout, not an error) but assert in a test that the two cannot both
render for one request.

**RED tests:** six, one per guard, each asserting redirect location + zero state change.
`:559` and `:606` need a monkeypatched raise on `repo.load_roster_for_business` /
`repo.commit_operator_resume_resolution`.

**Verify:** `uv run pytest tests/test_needs_operator.py -q` then the full gate.

**Commit:** `fix(resolve): explain each of the six rejections instead of a bare reload`

---

## T5: BUG-4, authorize_new_confirmation

Its own commit because it guards sending a client a **second** email.

**Files:** `app/routes/runs.py:1101-1102`, `:1107-1109`, `:1110-1116`; `operator_feedback.py`;
`tests/test_phase20_clarification_review.py`.

| line | guard | code |
|---|---|---|
| `:1102` | acknowledgement phrase mistyped | `authorize_bad_ack` |
| `:1109` | no loadable review, or wrong review kind | `review_unavailable` (reuse T3's) |
| `:1116` | CAS `NEEDS_OPERATOR -> APPROVED` lost | `review_state_changed` (reuse T3's) |

`authorize_bad_ack` is the highest-value one: the form at `run_detail.html:273` asks the operator
to type `AUTHORIZE A NEW CONFIRMATION` exactly, and a single character off produces a silent
reload that reads as "the button is broken". Text should name the exact required phrase, which is
safe to interpolate because it is the server-side constant `_NEW_CONFIRMATION_ACKNOWLEDGEMENT`
(`runs.py:156`), not user input.

**Do not touch** the `resolve_outbound_provider_handoff_for_delivery_review` call, the
`_snapshot_clone_fields` validation, the `clear_reply_context`, or the `should_wake` sequencing.
Feedback only.

**RED tests:** three, in `test_phase20_clarification_review.py` using `_confirmation_review_run`.

**Verify:** `uv run pytest tests/test_phase20_clarification_review.py -q` then the full gate.

**Commit:** `fix(delivery-review): explain a refused new-confirmation authorization`

---

## T6: BUG-3, the money gate

Alone in its commit. By this point the mechanism has four proven consumers and roughly twenty
regression tests behind it.

**File:** `app/routes/runs.py:431-432` only.

```
if not claimed:
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
```

becomes a `notice_redirect(f"/runs/{run_id}", "approve_claim_lost")` with the identical
`status_code=303` and the identical position inside the `with repo.get_connection() as conn,
conn.transaction():` block.

**Hard constraints, restated from the BRIEF because this is the single human gate:**
- The `claim_status(AWAITING_APPROVAL -> APPROVED)` CAS is unchanged: same arguments, same
  `conn=conn`, same call site, same early return before `load_run`.
- The `except Exception` error boundary at `:440-459` is unchanged, including
  `getattr(exc, "payroll_roster", None)`.
- `should_wake` / `wake.wake()` sequencing at `:460-462` is unchanged.
- The diff is one return statement. If the diff is larger than that, stop.

**Text:** a lost CAS means either a second tab/double-click already approved, or the run left
`awaiting_approval` some other way. Say that, and say the payroll was **not** approved twice:
"This run is no longer awaiting approval. It may already have been approved in another tab. No
second approval was recorded."

**RED test:** `tests/test_hitl.py`. Two existing tests already cover the CAS
(`test_approve_already_advanced_returns_303:214`, and the double-post at `:151-152`). Extend
rather than duplicate: add an assertion that the second POST's `location` carries
`?notice=approve_claim_lost` while the first carries a bare `/runs/{id}`. Add one test asserting
the run's final status and the delivery-job count are byte-identical to the pre-change behavior
(one job, not two), so a regression in the CAS shows up as a test failure and not as a duplicate
client email.

**Verify:**

```
uv run pytest tests/test_hitl.py tests/test_gate.py tests/test_send_idempotency.py -q
git diff --stat    # must show exactly one file, one hunk
uv run pytest -q && uv run ruff check . && uv run mypy
```

**Done:** a double-click on Approve says why the second click did nothing; nothing else about the
gate changed.

**Commit:** `fix(approve): tell the operator when a second approval lost the claim`

---

## T7: BUG-10, the demo routes

**Files:** `app/routes/demo.py:153-154`, `:190-191`, `:194-195`; `app/routes/dashboard.py`
(add `notice` Query param to the index route); `app/routes/runs.py:839-843` (`runs_list`, add
`notice`); `app/templates/index.html`, `app/templates/runs_list.html` (add the shared include);
`tests/test_demo_landing.py`, `tests/test_demo_fixtures.py`.

| site | guard | code |
|---|---|---|
| `demo.py:154` | `business_name` not in `SEED_CONTACTS` (bind) | `demo_unknown_business` |
| `demo.py:191` | `business_name` not in `SEED_CONTACTS` (compose) | `demo_unknown_business` |
| `demo.py:195` | body > 4000 or subject > 200 | `demo_too_long` |

Both `demo.py:154` and `:191` redirect to `/`; `demo_send_test`'s failure at `:340` redirects to
`/runs?demo_queue_error=1` and `demo_compose`'s at `:241` to `/?demo_queue_error=1`.

**Decision point:** `demo_queue_error` is a fourth parallel mechanism (a boolean flag with the
text in the template) on the same surfaces the new one now covers. Options:

- **A. (recommended)** Fold `demo_queue_error` into `NOTICE_LABELS` as `demo_queue_error` and
  delete the boolean plumbing from `dashboard.py`, `runs.py:842/864`, `index.html`,
  `runs_list.html`. Touches four test files (`test_dashboard.py`, `test_stuck_run_recovery.py`,
  `test_demo_fixtures.py`, `test_demo_landing.py`) but leaves exactly one mechanism, which is the
  point of the sweep.
- B. Leave it. Ships the sweep with two notice mechanisms coexisting on `/` and `/runs`.
- C. Fold it in a follow-up commit inside this task. Same end state as A, smaller diffs, one extra
  commit.

`demo_too_long` should state the actual limits (4000 body / 200 subject) since they are server
constants, and the composer currently discards the typed body on rejection with no explanation.

**RED tests:** three in `tests/test_demo_landing.py` (which owns a local `client` fixture at
`:738`), plus updates to whichever `demo_queue_error` assertions option A moves.

**Verify:** `uv run pytest tests/test_demo_landing.py tests/test_demo_fixtures.py tests/test_dashboard.py -q` then the full gate.

**Commit:** `fix(demo): explain rejected binds and oversized composer submissions`
(plus `refactor(demo): fold demo_queue_error into the shared notice registry` if option A/C)

---

## T8: the delivery-review retry classification (BUG-2 half 1, pure and testable)

No route or template change in this commit. Pure data + pure functions, unit-tested without HTTP,
so the mapping is proven before two consumers depend on it.

**Files:** `app/models/delivery_review.py` (extend T0's map);
`tests/test_delivery_review_categories.py` (new).

**Shape:** extend T0's dict value from a bare label string to one frozen dataclass:

```
@dataclasses.dataclass(frozen=True)
class DeliveryReviewCategory:
    label: str            # existing operator-facing label, unchanged strings
    uncertainty: str      # BUG-11: plain-language "what we do not know"
    replay_same_ok: bool  # can replaying the identical frozen email under the same key succeed
    fresh_send_ok: bool   # can a NEW slot (new Message-ID, new key, same content) succeed
    blocker: str | None   # what must change out of band; None when both flags are True
```

**The table** (see Design flag 3 for why two booleans, not one):

| category | replay_same_ok | fresh_send_ok | blocker |
|---|---|---|---|
| `transport` | yes | yes | none |
| `provider_5xx` | yes | yes | none |
| `rate_limited` | yes | yes | none |
| `authorization_expired` | yes | yes | none |
| `unknown` | yes | yes | none |
| `payload_mismatch` | **no** | yes | the frozen payload no longer matches its reserved key; only a new slot mints a fresh one |
| `final_attempt_lease_expired` | **no** | yes | the replay budget for this reservation is spent |
| `authorization` | **no** | **no** | the provider rejected the credentials or the sender permission; the API key or sending domain must change first |
| `validation` | **no** | **no** | the provider rejected the message itself, most often an undeliverable recipient address; the recipient or sender configuration must change first |
| `configuration` | **no** | **no** | delivery is not configured (no provider API key is set) |

`unknown` fails **open** (both true) on purpose: it is the unclassified catch-all
(`DELIVERY_PROVIDER_FAILURE`), and suppressing an action that might work is a different failure
than offering one that cannot. Say so in the field's comment.

**RED tests** (`tests/test_delivery_review_categories.py`, new, no marker):
1. Table-driven: every category has a non-empty `label`, non-empty `uncertainty`, and a `blocker`
   that is `None` exactly when `replay_same_ok and fresh_send_ok`.
2. Coverage: the keys equal T0's producer-derived vocabulary (reuse T0's derivation, do not
   re-transcribe).
3. The four live-proven cases are pinned by name: `validation` is
   `replay_same_ok=False, fresh_send_ok=False` (this is the Resend 403 on `.example` the BRIEF
   proved against the real API), and `payload_mismatch` is `replay_same_ok=False,
   fresh_send_ok=True`.
4. No `uncertainty` or `blocker` string contains `<`, `>`, `{`, or `}`.

**Verify:** `uv run pytest tests/test_delivery_review_categories.py -q` then the full gate.

**Commit:** `feat(delivery-review): classify each failure category by what a retry can achieve`

---

## T9: BUG-2 half 2 + BUG-11, the two cards consume the classification

**Files:** `app/routes/runs.py:330-359` (`_safe_delivery_review_projection`);
`app/templates/run_detail.html:258-275`; `tests/test_phase20_clarification_review.py`.

**Route change:** extend the projection dict with three new keys derived from T8's map:
`uncertainty`, `can_replay`, `can_fresh_send`, and `blocker`. Keep `failure_category` exactly as
it is (it is already the `label` and existing tests assert on it). The template must receive
booleans, never re-derive from a category string; the projection stays the single reduction
boundary, consistent with the `_safe_*` convention on this router.

**Template, clarification card (`:258-266`):**
- Insert the `uncertainty` sentence as the card's lead paragraph, replacing the generic
  "The client may not have received this clarification question." That generic sentence is
  precisely BUG-11: it never says what was uncertain.
- Wrap the "Retry same question" form at `:265` in `{% if delivery_review.can_replay %}`.
- In the `{% else %}` render `blocker` as a `form-help` paragraph in the button's place, so the
  space is explained rather than silently empty.
- "Mark handled" and "Reject" stay unconditional. They are provider-free and must always be
  available; suppressing them would recreate BUG-1.

**Template, confirmation card (`:267-275`):**
- Same `uncertainty` lead-paragraph substitution.
- Wrap the "Authorize a new confirmation" form at `:273` in
  `{% if delivery_review.can_fresh_send %}`, with the `blocker` sentence in the `{% else %}`.
  See Design flag 3: under `validation`, that button spends a delivery slot on a send that fails
  identically, and its own help text warns it "may send the client a second email".
- "Mark delivered" stays unconditional. It is the provider-free escape.

**Route-level:** leave `retry_delivery_now` and `retry_clarification_delivery_now` semantics
alone. Template suppression is "do not offer"; the T3 notice codes already cover a hand-crafted
POST. Do not add a second gate inside the handlers.

**RED tests** (`tests/test_phase20_clarification_review.py`): parametrize `_clarification_review_run`
and `_confirmation_review_run` over `error_detail` categories.
1. `delivery_review:validation` renders **neither** the `clarification/retry-now` form action nor
   the `delivery-review/authorize` form action, and does render the blocker sentence.
2. `delivery_review:transport` renders both.
3. `delivery_review:payload_mismatch` renders the authorize form but **not** the retry form.
   This is the case a single `retryable` boolean gets backwards.
4. Every category renders its `uncertainty` sentence.
5. `delivery_review:validation` still renders `mark-delivered` (confirmation) and
   `mark-handled` + `reject` (clarification). This is the anti-BUG-1 pin.

**Verify:** `uv run pytest tests/test_phase20_clarification_review.py -q` then the full gate.

**Commit:** `fix(delivery-review): name the uncertainty and hide actions that cannot succeed`

---

## T10: BUG-1, an escape from the actionless card

**Files:** `app/templates/run_detail.html:276-278`;
`tests/test_phase20_clarification_review.py`.

Per Design flag 4, this is option (b) with Reject only. T0 already removed the most reachable
trigger; this closes the remaining `None` causes (snapshot row gone, `attempt_count` outside
`0..100`, purpose mismatch, `email_id` not a UUID, a raise swallowed at `runs.py:1254`).

**Change:** add a Reject form to the "Delivery review unavailable" card at `:277`, matching the
existing markup and confirm-dialog pattern used at `run_detail.html:141-145` and `:153-157`.

Keep the "Action required" badge. The state genuinely does require action; the defect was that it
offered none.

Add one sentence explaining why Reject is the only option here, so the card is not a second
unexplained surface: the frozen evidence cannot be loaded, so no retry, no resolve, and no
re-trigger can be offered safely.

**Explicitly do not:** relax `_is_delivery_review_marker` at `runs.py:542` or `:736`, add a
Re-trigger form, or let the `:111` banner branch fall through to the generic `needs_operator`
branch at `:115` (that renders a resolve form that `resolve()` no-ops at `:546`, converting BUG-1
into a fresh BUG-5).

**RED test:** build a review run, then break the load (for example monkeypatch
`repo.load_delivery_review_snapshot` to return `None`) so `delivery_review is None` while
`delivery_review_marker` is `True`. Assert the response contains the unavailable card, contains a
form posting to `/runs/{id}/reject`, and contains **no** form posting to `/resolve` or
`/retrigger`. Then POST the reject and assert the run reaches `rejected`.

**Verify:** `uv run pytest tests/test_phase20_clarification_review.py -q` then the full gate.

**Commit:** `fix(delivery-review): give the unavailable-evidence card a working exit`

---

## T11: BUG-12, dead `computing` badge config

**Files:** `app/routes/templating.py:21` and `:37`; `tests/test_status_drift.py`.

`computing` is in both `_BADGE_CLASS` and `_BADGE_LABEL` but is not one of the 11 `RunStatus`
members in `app/models/status.py`. The codebase already knows this: `runs.py:677-678` and
`:722-723` both carry a comment saying "COMPUTING is NOT a RunStatus member".

Do both halves of the BRIEF's "remove it, or add a test", because removal alone permits the next
one:

**RED test** (`tests/test_status_drift.py`): assert `set(_BADGE_CLASS) == {s.value for s in
RunStatus}` and the same for `_BADGE_LABEL`. Fails today on the extra `computing` key.

**GREEN:** delete both entries. `badge_class_filter` / `badge_label_filter` already have safe
`.get()` defaults (`"neutral"` and a title-cased fallback), so nothing regresses if a legacy row
ever carries the string.

**Verify:** `uv run pytest tests/test_status_drift.py -q` then the full gate.

**Commit:** `fix(templating): drop the dead computing badge entry and pin the maps to RunStatus`

---

## T12: FIX A, demo outbound deliverability (approach A3)

Independent of BUG-1 through BUG-12. Could ship first or last.

**Files**
- `app/config.py` (one new setting, after the Resend block at `:53-70`)
- `app/email/routing.py` (new, one pure function)
- `app/pipeline/delivery.py:155` (`to_addr=`)
- `app/pipeline/clarification.py:473` (`to_addr=`)
- `.env.example`, `render.yaml`, `README.md`
- `tests/test_delivery.py` and `tests/test_clarify.py` (or one new
  `tests/test_outbound_routing.py`)

**Setting**

```
demo_outbound_to: str = ""    # DEMO_OUTBOUND_TO
```

Empty default is the production-safe value, matching the `resend_reply_to` / `pump_token`
empty-default-secret convention already in this file. Document in the field comment that a
non-empty value routes **every** outbound client email to that address, that it is a demo
affordance and not a production feature, and that it must be resolved at reservation time only.

**Pure helper** (`app/email/routing.py`)

```
def resolve_outbound_recipient(client_addr: str) -> str:
    """Return the address an outbound client email is actually addressed to."""
```

Returns `get_settings().demo_outbound_to.strip() or client_addr`. One function, two call sites,
no branch anywhere else.

**Call sites** (exactly two, both at snapshot reservation, per Design flag 5)
- `delivery.py:155`: `to_addr=resolve_outbound_recipient(inbound.from_addr if inbound else "")`
- `clarification.py:473`: `to_addr=resolve_outbound_recipient(email.from_addr)`

**What this must not touch,** restated from the BRIEF and verified against source:
- `businesses.contact_email` (`NOT NULL UNIQUE`, `app/db/schema.sql:19`; it is the access-control
  seam read by `find_business_by_sender`, `app/db/repo/runs.py:149-173`). No DB write at all,
  so no live Supabase mutation is required.
- The reserved-`message_id` / Idempotency-Key path (`gateway.py:167`), the frozen snapshot replay,
  and the row-locked provider handoff. Reservation-time resolution keeps every replay of a given
  snapshot byte-identical, which is stronger than not touching them.
- `demo_sender_bindings`. That mechanism owns the **inbound** leg
  (`repo/runs.py:157-172`); `DEMO_OUTBOUND_TO` owns the **outbound** leg. Complementary, not
  duplicative. Say so in the README so the next reader does not collapse them.

**Coverage check:** this fixes all three seeded businesses at once, because the override is
applied to whatever recipient the run resolved, not per business. That covers the landing-gate
path: `index.html:24` posts `/demo/send-test` with
`LANDING_GATE_FIXTURE_KEY = "unknown_shorthand_metro"` (`dashboard.py:34`, Metro Deli), which runs
`record_only=False` and therefore does hit Resend. Note that `/demo/compose` sets
`record_only=True` (`demo.py:231`) and never calls Resend at all, so it was never broken; only
`/demo/send-test` and real webhook inbound were.

**RED tests** (new `tests/test_outbound_routing.py`, no marker):
1. `resolve_outbound_recipient("hr@metrodeli.example")` returns the client address when
   `DEMO_OUTBOUND_TO` is unset, and the override when set. Clear the `get_settings` `lru_cache`
   between cases.
2. A whitespace-only `DEMO_OUTBOUND_TO` is treated as unset.
3. Integration-shaped but hermetic: with the override set, the reserved confirmation snapshot's
   `to_addr` equals the override, and its `from_addr`, `message_id`, `in_reply_to`, and
   `references_header` are unchanged. This is the pin that the override lands in the frozen
   envelope and nowhere else.
4. With the override set, `simulate_reply` still threads: the synthetic reply's `from_addr` comes
   from the source inbound (`runs.py:1422`), so `find_business_by_sender` still resolves. Assert
   the run advances past `awaiting_reply`.

**Docs (required, not optional)**
- `.env.example`: `DEMO_OUTBOUND_TO=` with a comment naming the RFC 2606 root cause, that Resend
  free tier with `from=onboarding@resend.dev` only delivers to the account owner's own address,
  and that a plus-addressed variant was live-tested and also rejected.
- `render.yaml`: a plain `value:` entry in the non-secret block (alongside `EXTRACTION_MODEL` at
  `:41`), not `sync: false`. Note the near-duplication with `DEMO_OPERATOR_EMAIL` in
  `demo.py:71`: same literal, different leg (inbound binding vs outbound override). If the owner
  prefers not to commit a second copy of a personal address, use `sync: false` and set it in the
  Render dashboard instead.
- `README.md`: one honest paragraph. Demo mode routes client email to the operator's inbox; the
  client-facing addresses shown in the thread view are the real seeded contacts and the run
  records them faithfully, only the actual SMTP recipient is redirected.

**Verify**

```
uv run pytest tests/test_outbound_routing.py tests/test_delivery.py tests/test_clarify.py -q
grep -rn "resolve_outbound_recipient" app/    # exactly 3 hits: def + 2 call sites
uv run pytest -q && uv run ruff check . && uv run mypy
```

**Done:** with `DEMO_OUTBOUND_TO` set, the landing-page gate demo completes the
clarify -> reply -> resume loop instead of escalating to delivery review. With it unset, behavior
is byte-identical to today.

**Commit:** `feat(demo): config-driven outbound recipient override for deliverable demo email`

---

## Final gate

```
uv run pytest -q          # expect >= 1331 passed / 1 skipped, plus the new tests
uv run ruff check .
uv run mypy
git log --oneline 78542f1..HEAD    # expect 12 commits, each independently green
```

---

## Deploy note (record only, do NOT deploy)

Unchanged from the BRIEF and still true at this baseline. `78542f1` adds column
`email_messages.operator_acknowledged_at` (`app/db/schema.sql`) which is **not** applied to live
Supabase, and three commits will now be unpushed (`abd2170`, `78542f1`, plus this sweep).
Deploying code before the migration would break the live delivery-review path and turn
`/health/schema` red. Schema before code, per the Phase 8 precedent.

This sweep adds **no** new schema. T12 adds one env var (`DEMO_OUTBOUND_TO`) that must be set in
the Render dashboard or committed in `render.yaml` before the demo behaves as documented; with it
unset the deploy is a pure no-op relative to today.

Before any UAT of the deployed service, run `git rev-list --count origin/master..master`. A green
CI on an unpushed branch has previously read as a working production deploy when it was not.

## Milestone v5 spec input

Three of these defects are inherent to the current Jinja structure and should be carried into the
Phase 23 React/TypeScript conversion as requirements rather than re-discovered:

1. **Redirect-after-POST loses all outcome information.** Every one of BUG-3 through BUG-10 exists
   because a 303 to the same URL is the only channel a server-rendered form has. The whole
   `NOTICE_LABELS` allow-list is a workaround for that. A JSON action endpoint returning a typed
   result makes the entire class structurally impossible.
2. **The banner chain at `run_detail.html:98-178` is a single `if/elif` ladder over mixed
   concerns** (run status, delivery-review marker, decision outcome). BUG-1 is a direct
   consequence: one `elif` at `:111` suppresses the unrelated resolve form at `:115`. The
   converted UI should compose independent regions, not chain them.
3. **Actions are rendered without reference to whether they can succeed.** BUG-2 is the instance;
   the general rule for the conversion is that every affordance derives its enabled state from the
   same server-side classification that governs the handler.
