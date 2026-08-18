---
phase: 22-frontend-foundation-runs-list
verified: 2026-08-18T01:38:00Z
status: gaps_found
score: 16/18 requirements verified (2 gaps: SC-2 deploy precondition, LIST-04)
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "An operator uses a React-rendered /runs on the deployed Render service (phase goal, ROADMAP SC-2)."
    status: failed
    reason: >
      `git rev-list --count origin/master..master` = 84 at verification time. All v5 work,
      including the entirety of phase 22, is unpushed. The deployed Render service is running
      pre-v5 code and cannot possibly be serving a React-rendered /runs. This is the exact
      "CI green, prod broken/absent" shape the phase's own CONTEXT.md and PATTERNS.md
      explicitly warn about (v4 Phase 21 precedent) and the phase's own manual-verification
      instructions name as the required precondition ("confirm git rev-list --count
      origin/master..master == 0" before the live check). The precondition is not met, so the
      live check cannot honestly be attempted yet, let alone pass.
    artifacts: []
    missing:
      - "Push master to origin (git push)."
      - "Confirm `git rev-list --count origin/master..master` == 0."
      - "Load the live Render /runs URL and confirm rows render from a real Docker-built bundle (not a blank console) -- see Human Verification #1."
  - truth: "LIST-04: an operator reading the list on a 375px-wide viewport sees no horizontal page overflow, and the wide table scrolls inside its own keyboard-reachable region."
    status: failed
    reason: >
      The real 375/374/376px measurement was never performed -- no browser was reachable from
      the executor sandbox and no Playwright/Puppeteer is installed (recorded honestly in
      .planning/WINDOWS.md id 1 and in 22-VALIDATION.md's own Manual-Only Verifications table).
      jsdom performs no layout, so no Vitest test can substitute for this measurement. The
      structural half (scroll-region role/tabIndex/aria-label, same markup pattern verified at
      a real 375px viewport in quick task 260726-ugm) is present and Vitest-tested, but the
      requirement's actual observable claim -- no overflow at the boundary width -- has not
      been demonstrated on this converted page. Per the instruction to treat an undemonstrated
      check as not satisfying its requirement, this is recorded as a gap rather than rounded
      up to passed.
    artifacts:
      - path: "frontend/src/pages/RunsPage.tsx"
        issue: "Scroll-region markup present and unit-tested; the actual 375px overflow behavior is unmeasured."
    missing:
      - "Chrome DevTools responsive mode at 375/374/376px: confirm body does not scroll horizontally and the table region is keyboard-reachable and scrollable -- see Human Verification #2."
human_verification:
  - test: "Load the live Render /runs URL after pushing master to origin."
    expected: "Rows render from a real Docker-built bundle -- same columns, badges, ordering, empty state as the pre-conversion Jinja page -- not a blank console; /runs/{id}, /eval, /, /ops still work, unconverted."
    why_human: "SHELL-05's trap (`.gitignore` `dist/` + a clone-based Render build) is invisible to any local build by construction -- only a live deploy from the pushed clone exposes it. Blocked until the push precondition above is met."
  - test: "Chrome DevTools responsive mode at 375px, 374px, and 376px on /runs."
    expected: "Page body never scrolls horizontally; the `.table-scroll` region is reachable and scrollable via keyboard (Tab to focus, arrow keys to scroll) at all three widths, with 375px as the boundary case."
    why_human: "jsdom performs no real layout, so no automated pin exists in this repo for viewport overflow; this project's own precedent (quick task 260726-ugm) treats this as a manual check."
---

# Phase 22: Frontend Foundation & Runs List Verification Report

**Phase Goal:** An operator uses a React-rendered `/runs` on the deployed service, and every
shared mechanism the other two slices ride on -- build, deploy, CI, DTO allowlist, guards, test
inventory -- exists and has been demonstrated able to fail.
**Verified:** 2026-08-18T01:38:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Summary

At the code level this phase is exceptionally solid. All 12 plans' artifacts exist, are
substantive, and are wired. I did not stop at reading the code or trusting SUMMARY.md claims:
for every requirement whose text implies a guard, I personally introduced a real, live mutation
against the tracked source (never a scratch copy) and watched the corresponding test go red,
then reverted byte-identically and reconfirmed green. Nine independent falsifying mutations were
run this way (listed under Guard Demonstrations below), covering GUARD-01, GUARD-02 (both
SAFETY-01 and SAFETY-02), GUARD-04, GUARD-05 (both halves), GUARD-06 (both enforcement paths),
SHELL-06's CI trigger gate, and the `ConfirmForm` `preventDefault()` footgun. Every one of them
reverted to a byte-identical working tree (`git status --short` / `git diff --stat` clean after
each), and the full suite (`uv run pytest -q`: 1513 passed / 107 skipped; `cd frontend && npm run
check && npm run test && npm run build`: green, 57/57 Vitest tests) is unchanged from the
pre-verification baseline.

Two things stop this from being a clean pass, and neither is a code defect:

1. **The phase goal's own first half -- "on the deployed service" -- cannot currently be true.**
   `git rev-list --count origin/master..master` is 84, not 0. Nothing in the v5 milestone,
   including all of phase 22, has been pushed. The live Render service is still running
   pre-v5 code. This is exactly the precondition the phase's own planning docs (CONTEXT.md
   "Claude's Discretion" -> "Phase exit includes a real deploy", 22-VALIDATION.md's Manual-Only
   Verifications table) name as required before the live check can even be attempted.
2. **LIST-04's 375px measurement was never run.** Recorded honestly in `.planning/WINDOWS.md`
   (open window id 1) -- no browser was reachable from the executor sandbox. The structural
   markup is present and Vitest-tested; the actual overflow-at-375px claim is unmeasured.

Both are structured as gaps below (not silently passed, not silently failed without a path
forward) with the exact human-verification steps needed to close them once network access is
available.

## Guard Demonstrations (run live, against tracked source, by this verifier)

Every row below: mutation applied to the real tracked file, target test run, failure captured,
`git checkout --`/manual revert applied, `git status --short` confirmed clean, suite re-run green.

| # | Requirement | Mutation | Target test | Result |
|---|---|---|---|---|
| 1 | GUARD-01 | Added one unclassified `.text` assertion to `tests/test_dashboard.py` | `test_every_discovered_assertion_has_a_registry_entry` | RED, names `test_dashboard:2476:11` exactly. Reverted clean. |
| 2 | GUARD-04 | Appended `totally_new_probe_column` to `RUN_COLS` in `app/db/repo/runs.py` | `test_every_run_col_is_classified` | RED, names the column by exact string. Reverted clean. |
| 3 | GUARD-06 (hermetic) | Pre-existing synthetic-offender test (`test_guard_reports_a_synthetic_offender_placed_in_a_temporary_directory`) re-run to confirm it is a genuine positive/negative-control pair, not vacuous | n/a (self-contained) | Confirmed genuinely discriminating. |
| 4 | GUARD-06 (ESLint) | Added `frontend/src/components/__verifier_probe.tsx` calling `fetch(...)` | `npm run lint` | RED, `no-restricted-globals` fires with the project's own message. File deleted after. |
| 5 | GUARD-02 / SAFETY-01 | Removed both `<` and `>` entries from `_JSON_SCRIPT_ESCAPES` in `app/routes/templating.py` | `test_hostile_business_name_does_not_terminate_island_early` | RED -- `<script>alert(1)</script>` reappears verbatim in `response.text`. Reverted clean. Note: removing only one of the two entries does NOT redden this test, exactly as the registry's own docstring documents (the surviving escape of the other character already breaks the substring match) -- confirmed this nuance by hand, it is not a defect. |
| 6 | GUARD-02 / SAFETY-02 | Removed `"source_email_id"` from `RunListRow.EXCLUDED` in `app/schemas/runs_list.py` | `test_payload_excludes_internal_and_pii_fields` | RED -- the allowlist's fail-closed design raises `UnclassifiedColumnError` (500) rather than leaking the field, so the test's earlier `status_code == 200` assertion fails first (a stronger failure mode than the registry's named assertion text, not a weaker one). Reverted clean. |
| 7 | GUARD-05 (route-table half) | Added a second `app.mount("/catchall", ...)` to `app/main.py` | `test_only_mount_is_static` | RED, reports `['/static', '/catchall']`. Reverted clean. |
| 8 | GUARD-05 (content-type half) | Changed `GET /health/live` to `return HTMLResponse("<html>ok</html>")` in `app/routes/health.py` | `test_service_route_never_answers_html[/health/live]` | RED -- `text/html` detected. This closes the WINDOWS.md id 2 concern for practical purposes: the content-type guard IS falsifiable by the realistic mutation it exists to catch (a route directly serving HTML); it only fails to redden via the specific catch-all-`Mount` vector, which FastAPI 0.138's routing precedence makes structurally impossible regardless of source edits -- an accurately self-documented, non-vacuous scope narrowing, not a broken guard. Reverted clean. |
| 9 | SHELL-06 (CI trigger gate) | Removed `pull_request:` from the **tracked** `.github/workflows/ci.yml` | `test_ci_triggers_on_pull_request_unlike_the_push_only_eval_workflow` | RED, names the missing trigger. **This supersedes 22-05-SUMMARY.md's weaker scratch-copy proof** (the plan's own "Sandbox change-control adaptation" note says the sandbox's command classifier blocked editing the tracked file directly during execution, so the executor proved the assertion logic against an untracked scratch copy instead -- a real gap the team lead flagged). I was not blocked and reproduced the red proof against the real tracked file. Reverted clean; `git diff --stat` empty. |
| 10 | SHELL-03 / ConfirmForm | Changed `event.preventDefault()` to `return false` in `frontend/src/components/ConfirmForm.tsx` | `MutationForm.test.tsx` (ConfirmForm suite) | RED, 3 tests fail on `defaultPrevented` being `false` -- exactly the footgun the component exists to prevent. Reverted clean. |
| 11 | Code review WR-01 fix | Confirmed (not mutated) `tests/test_stuck_run_recovery.py`'s restored bare-name-call pin passes for real | `test_runs_list_ast_is_read_only_and_has_no_background_tasks_parameter` | GREEN, and the fix (commit `93b65fd`, this session's own HEAD) matches the review's recommended option A exactly. |

All nine mutations plus the WR-01 fix check left the working tree byte-identical to its
pre-verification state (`git status --short` clean throughout); the full suite was re-run green
at the end.

## Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | An operator uses a React-rendered `/runs` **on the deployed service** (phase goal, first half; ROADMAP SC-2) | FAILED | `git rev-list --count origin/master..master` = 84. Nothing is pushed; the live service cannot be running this code. See Gaps. |
| 2 | `/runs` is rendered by React from a built bundle served through the existing `/static` mount, no catch-all route (SHELL-01, structural half) | VERIFIED | `app/main.py` registers exactly one `Mount`; `runs_list()` calls `render_react_page`; demonstration #7 above. |
| 3 | The page's data is present in the HTML response, no post-load fetch required (SHELL-02) | VERIFIED | `tests/test_react_page_render.py` parses `__INITIAL_DATA__` out of `response.text` directly; island-present, zero-runs, ordering, and two-renders-differ tests all pass. |
| 4 | JS-disabled operators still read the shell and submit every mutation form (SHELL-03) | VERIFIED | `MutationForm` emits a native `<form method="post">`; demo form stays server-Jinja and sibling to the mount point (`test_markup_order_notice_heading_mount_form`); demonstration #10 proves the `ConfirmForm` footgun is closed for real. |
| 5 | One dev-server command, one typecheck+lint command, both documented and run (SHELL-04) | VERIFIED | README documents `VITE_DEV_SERVER_URL=http://localhost:5173 uv run uvicorn ...` + `cd frontend && npm run dev` inline (the env var value is given directly in the command, so the missing `.env.example` entry -- see below -- does not block a developer following the README); `tests/test_react_dev_mode.py` (4/4) proves the fail-closed default, the dev-branch's manifest-skip, and `Dockerfile` never setting the var; I re-ran `npm run check` clean. |
| 6 | Deployed build parity: Render can't ship a bundle-less image (SHELL-05) | VERIFIED | `Dockerfile`'s frontend stage + `RUN test -f .../manifest.json` + `.dockerignore`'s `app/static/dist/` entry; orchestrator independently built a pristine `git archive HEAD` export and confirmed a real 192KB bundle in the image (not re-run here to avoid redundant cost). CI's `docker-build` job builds from the checked-out clone. |
| 7 | Broken TS/lint/test/build blocks a PR merge (SHELL-06) | VERIFIED | `ci.yml`'s `frontend` and `docker-build` jobs inherit the workflow's `pull_request` trigger and `ci-${{ github.ref }}` concurrency group (no job-level override); demonstration #9 and #4 above are real red proofs against tracked source, not config-parsing alone. |
| 8 | JSON responses expose only declared fields; list and detail have separate shapes (SHELL-07) | VERIFIED | `RowProjection.from_row` raises `UnclassifiedColumnError` on any unclassified key; `RunListRow` carries `created_at`, the detail column list (`RUN_COL_CLASSIFICATION`) does not use a shared model; `test_list_and_detail_shapes_are_separate` passes. |
| 9 | `/ops` stays Jinja, script-free (SHELL-09) | VERIFIED | Unmodified per plan key_links; `tests/test_ops_route.py` green in the full suite run. |
| 10 | Per-page `<title>`, single `aria-current`, no color literal outside `:root` (SHELL-10) | VERIFIED | `tests/test_page_shell_pins.py` (new, 3 tests) and widened `tests/test_design_tokens.py` both pass; both were part of the 105-test batch I ran directly. |
| 11 | Committed assertion inventory precedes every conversion, demonstrated able to fail (GUARD-01) | VERIFIED | Demonstration #1. Inventory covers 16 files (excluding `conftest.py`), matching D-22-07's live re-measurement (17 total, 16 excluding conftest) -- not the stale 14-file figure in REQUIREMENTS.md, which the phase's own CONTEXT.md flags as superseded. |
| 12 | An engineer can tell genuine-absence from assertion-can't-see (GUARD-02) | VERIFIED | Demonstrations #5 and #6, both against the real live safety-critical subset (XSS island-escaping, PII/internal-field exclusion) that D-22-09 locked as this phase's scope; SAFETY-03's honestly-narrower catch-all-mount coverage does not weaken this because GUARD-05's own route-table test independently catches that exact mutation (demonstration #7). |
| 13 | New `RUN_COLS` column fails CI, identified by name (GUARD-04) | VERIFIED | Demonstration #2. |
| 14 | Service routes never answer HTML; no catch-all (GUARD-05) | VERIFIED | Demonstrations #7 and #8, both against real live source. |
| 15 | `fetch`/`axios` outside `usePoller` fails CI via two independent paths (GUARD-06) | VERIFIED | Demonstrations #3 and #4. |
| 16 | Full list parity: columns, badges, order, empty state (LIST-01) | VERIFIED | `frontend/src/pages/RunsPage.tsx` read directly: column order Created/Business/Status/Summary/Action, four-way failure-summary precedence, empty-state copy all match the pre-conversion markup; `RunsPage.test.tsx` is part of the 57/57 green Vitest run. |
| 17 | In-place status/queue/failure badge updates, polling stops on settle (LIST-02) | VERIFIED (behavior-dependent, exercised) | Named tests re-run directly and passed: `usePoller.test.ts`'s unmount/per-instance-independence tests (2/2) and `RunsPage.test.tsx`'s "change in place" test (1/1) -- this is the actual state-transition/cleanup invariant, not just presence. |
| 18 | Demo form redirect + queue-failure retry message preserved (LIST-03) | VERIFIED | 7 targeted tests re-run directly and passed, including the wake-failure-after-commit and unknown-notice-renders-no-banner tests. |
| 19 | No 375px overflow, keyboard-reachable scroll region (LIST-04) | FAILED (undemonstrated) | Structural markup present and Vitest-tested; the actual measurement never performed (`.planning/WINDOWS.md` id 1). See Gaps. |

**Score:** 16/18 requirement-level truths verified; 2 gaps (both requiring an operation this
verifier's sandbox cannot perform -- network push and a real browser -- not a code defect in
either case).

### Requirements Coverage

| Requirement | Status | Evidence |
|---|---|---|
| SHELL-01 | SATISFIED (structural); deployed-service half BLOCKED | Row 2 above; deploy gap in Observable Truth #1 |
| SHELL-02 | SATISFIED | Row 3 |
| SHELL-03 | SATISFIED | Row 4 |
| SHELL-04 | SATISFIED | Row 5 |
| SHELL-05 | SATISFIED | Row 6 |
| SHELL-06 | SATISFIED | Row 7 |
| SHELL-07 | SATISFIED | Row 8 |
| SHELL-09 | SATISFIED | Row 9 |
| SHELL-10 | SATISFIED | Row 10 |
| GUARD-01 | SATISFIED | Row 11 |
| GUARD-02 | SATISFIED | Row 12 |
| GUARD-04 | SATISFIED | Row 13 |
| GUARD-05 | SATISFIED | Row 14 |
| GUARD-06 | SATISFIED | Row 15 |
| LIST-01 | SATISFIED | Row 16 |
| LIST-02 | SATISFIED | Row 17 |
| LIST-03 | SATISFIED | Row 18 |
| LIST-04 | NOT SATISFIED | Row 19 -- gap |

All 18 requirement IDs listed in the assignment are accounted for above; none are orphaned. Cross-
referenced against `.planning/REQUIREMENTS.md`: **note that REQUIREMENTS.md's checkbox column still
shows most of these as unchecked `[ ]`** (only SHELL-01, SHELL-09, SHELL-10, GUARD-01, GUARD-05 are
`[x]`), and its Traceability table still reads "Pending" for the rest. The file was last touched at
commit `47f488b` (plan 22-01, 2026-08-17T14:19), before plans 22-03 through 22-12 landed. This is a
stale bookkeeping artifact, not evidence against the code-level findings above -- the code itself
was independently verified by direct reading and live mutation, not by trusting this table. **This
should be corrected before `/gsd-ship`** so REQUIREMENTS.md reflects reality; treat it as an
INFO-level finding, not a gap.

## Anti-Patterns Found

None. Scanned all 66 files changed `4c756bb..HEAD` for `TBD`/`FIXME`/`XXX` (one hit, a base64
integrity hash in `package-lock.json` -- false positive) and `TODO`/`HACK`/`PLACEHOLDER`/"not yet
implemented"/"coming soon" (zero hits). No debt markers.

## Code Review Follow-Up

22-REVIEW.md's WR-01 (the runs_list read-only AST guard losing its render-step pin to bare-name
calls) is genuinely fixed at HEAD (commit `93b65fd`, option A from the review's own recommendation)
-- confirmed by reading the restored test and re-running it green (demonstration #11). IN-01
(`DecisionBanner`/`banner.ts` shipping with zero production consumers this phase) is accurately
described as intentional Phase 23 scaffolding; no action needed.

## Human Verification Required

See frontmatter `human_verification`. Both items are blocked on operations unavailable to this
verifier (network push, a real browser) rather than on anything uncertain about the code itself.

1. **Live deploy check** -- push master to origin, confirm `git rev-list --count
   origin/master..master` == 0, then load the live Render `/runs` URL and confirm rows render
   from the Docker-built bundle.
2. **375/374/376px viewport check** -- Chrome DevTools responsive mode on `/runs`: no horizontal
   page overflow, and the table's scroll region is keyboard-reachable at the boundary width.

## Gaps Summary

Both gaps share the same shape: the code that would satisfy them is already written, tested, and
verified at the unit/integration level -- what's missing is an operation outside this phase's
codebase (a `git push`, a real browser session) that this verifier's sandbox cannot perform. Neither
gap implicates the quality of the 12 plans' implementation, which held up under nine independently
constructed, live, byte-reverted falsifying mutations against tracked source with zero surprises.
Recommended next step: push to origin, then have a human run the two Human Verification items above
and re-run this verifier (or hand-update the frontmatter `gaps` to closed) once both are confirmed.

---

_Verified: 2026-08-18T01:38:00Z_
_Verifier: Claude (gsd-verifier)_

---

## LIST-04 — MEASURED AND CLOSED (orchestrator, post-verification)

The gap recorded above ("the real 375/374/376px measurement was never performed") has since been
performed. Broken-windows ledger entry 1 is marked fixed.

**Environment:** throwaway Docker Postgres (`postgres:16-alpine`, port 55432) seeded with 1
business and 4 payroll runs spanning `awaiting_approval` / `error` / `extracting` /
`needs_operator`; production bundle built via `npm run build`; `uv run uvicorn app.main:app` on
127.0.0.1:8022; Chrome via browser automation.

Chrome on macOS enforces a minimum window width of roughly 400px, so a true 375px *window* was
not reachable. The measurement was taken in a same-origin iframe sized to the exact target width,
which gets its own layout viewport and evaluates media queries against that width.

**Result — no horizontal page overflow at any boundary width:**

| viewport | documentElement.scrollWidth | clientWidth | horizontal overflow |
|---|---|---|---|
| 374px | 374 | 374 | NO |
| 375px | 375 | 375 | NO |
| 376px | 376 | 376 | NO |

**Scroll region at 375px:** `role="region"`, `tabindex="0"`, `aria-label="Payroll runs"`,
`overflow-x: auto`, `scrollWidth` 560 vs `clientWidth` 343 — the 560px-wide table scrolls inside
its own keyboard-reachable region rather than pushing the page. Elements measuring past the
viewport edge in absolute coordinates (`table@576px` and its header cells) are children of that
region and are clipped by it, which is the intended design, not page overflow.

**Negative control — the measurement can fail.** Appending a 900px `div` to `body` OUTSIDE the
scroll region flipped the result: `scrollWidth` 900 vs `clientWidth` 375, horizontal overflow
TRUE. So the clean readings above are evidence, not a check that is structurally incapable of
reporting failure.

**Verdict:** LIST-04 satisfied. Both halves of its claim are demonstrated — no horizontal page
overflow at the boundary width, and the wide table scrolling inside its own keyboard-reachable
region.

**Deploy precondition (SC-2):** `git push origin master` completed with the user's explicit
approval; `git rev-list --count origin/master..master` is now 0. The live-service check remains
outstanding human verification, since it depends on the Render build completing.
