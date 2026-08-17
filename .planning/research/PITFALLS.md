# Pitfalls Research

**Domain:** Adding React + TypeScript to an established, heavily-tested FastAPI + Jinja2 server-rendered operator console (money-moving payroll pipeline)
**Researched:** 2026-08-17
**Confidence:** HIGH (every claim below verified against live source at the cited `file:line`, not against the milestone's own summary)

**Slice map used throughout:**
- **Slice 1 / Phase 22** — toolchain + `/runs` (list) + the in-place row poller
- **Slice 2 / Phase 23** — `/runs/{id}` (run detail)
- **Slice 3 / Phase 24** — `/eval`

---

## Corrections to the milestone's own numbers (verify-not-repeat)

`.planning/PROJECT.md:254-256` states the test cost center is "roughly 4,650 LOC ... `tests/test_dashboard.py` 2,218 LOC / 85 markup assertions, `tests/test_needs_operator.py` 2,009 LOC / 10". Measured against live source:

| Claim in PROJECT.md | Measured reality | Delta |
|---|---|---|
| 2 affected test files | **6** affected test files | +4 files |
| ~4,650 LOC | **7,271 LOC** | +56% |
| 95 markup assertions | **131 markup assertions** | +38% |
| `test_dashboard.py` 2,218 LOC | 2,296 LOC | — |
| `test_needs_operator.py` 2,009 LOC | 2,223 LOC | — |
| `/ops` pinned at `tests/test_ops_route.py:364` | :364 is the `def`; the assertion is **:366** (`assert "<script" not in response.text`) | cite :366 |
| `_safe_run_for_browser` at `runs.py:224` | **`app/routes/runs.py:220`**; denylist set at **:232-241**; pop loop at **:242-245** | cite :220 / :232 |
| demo redirect at `demo.py:337` | **`app/routes/demo.py:352`** | cite :352 |
| resolution_superseded at `runs.py:580` | suffix built at **`app/routes/runs.py:626`**, used at **:627** | cite :626 |

**The scope-underestimate is itself the first pitfall.** The two files PROJECT.md names are not the blast radius. `tests/test_phase20_clarification_review.py` (919 LOC, 30 markup assertions) and `tests/test_reply_redelivery.py` (720 LOC) assert against `run_detail.html` markup — and they hold **money-safety absence pins**, e.g. `tests/test_phase20_clarification_review.py:800` `assert f'action="/runs/{run_id}/reject"' not in page.text`, `:912-913` (Reject must be offered, Resolve/Retrigger must not). A planner working from PROJECT.md's two-file scope will not open those files. This is the same "guard blind exactly where it doesn't look" pattern the project has already hit twice.

---

## Measured markup-assertion inventory (the real cost center)

Assertion statements collected by joining continuation lines; "markup" = the statement references a rendered-response `.text`/`.content` (excludes `caplog.text` and `body_text`).

| File | LOC | Total asserts | Markup asserts | of which **absence** (`not in`) | Owning slice |
|---|---:|---:|---:|---:|---|
| `tests/test_dashboard.py` | 2,296 | 293 | 86 | 33 | 1, 2, 3 (spans all) |
| `tests/test_needs_operator.py` | 2,223 | 165 | 8 | 3 | 2 |
| `tests/test_phase20_clarification_review.py` | 919 | 137 | 30 | 7 | 2 |
| `tests/test_reply_redelivery.py` | 720 | 78 | 4 | 1 | 2 |
| `tests/test_hitl.py` | 564 | 73 | 2 | 0 | 2 |
| `tests/test_clarify_round_hours_safety.py` | 547 | 27 | 1 | 0 | 2 |
| **TOTAL** | **7,271** | **773** | **131** | **44** | |

**Route attribution of the 60 `client.get` calls in those files** (this is the sequencing fact the roadmap needs):

| Target | GET count | Slice |
|---|---:|---|
| `/runs/{id}` (incl. `?notice=` variants) | 44 | **2** |
| `/runs` (list) | 8 | 1 |
| `/runs/{id}/status` (JSON poller) | 5 | 1 + 2 |
| `/runs/{id}/delivery-review/email` | 3 | 2 |
| `/eval` | 3 | 3 |
| `/runs/{id}/pdf/{employee_id}` | 2 | 2 |

**Slice 2 owns roughly 80% of the migration cost.** The intuition that Slice 1 is the big one (because it carries the toolchain) is wrong: Slice 1 touches 8 list-page GETs and 3 `js-` hooks; Slice 2 touches 44 detail-page GETs, 14 of the 18 server-rendered forms, all 5 `confirm()` guards, and every delivery-review safety pin. Do not size the three slices equally.

### Classification of the 131

**Class A — survives unchanged (behavior lives in the route/DTO, not the page): 642 of 773 non-markup asserts, plus these markup ones.**
Status codes (59 in `test_dashboard.py` alone), `headers["location"]` on the 15 POST routes, repo call/state assertions, and everything against `GET /runs/{id}/status` — which **already returns JSON** (`app/routes/runs.py:891-917`) and is therefore already framework-agnostic. These need zero work.

**Class B — must move to a JS-side test (87 positive-substring markup asserts).**
`assert "Retries exhausted" in detail.text`, `assert "5 of 5 attempts" in detail.text`, `assert "chart.svg" in response.text` (`tests/test_dashboard.py:179`). These **fail loudly** against a React shell that renders `<div id="root">`. Loud failure is the good case: you cannot ship without confronting them.

**Class C — the DANGEROUS class: 44 absence assertions.**
`assert X not in response.text` is satisfied *trivially* by a page that renders nothing. Every one of these goes green the instant its content moves into a bundle, and the test file still reports "N passed."

The security- and money-critical members, by line:

| Assertion | What it actually protects | Slice |
|---|---|---|
| `test_dashboard.py:309` `assert sentinel not in response.text` | The `/eval` fixture **path traversal** fixed at `app/routes/dashboard.py:178-182` — a real defect this project already shipped once | **3** |
| `test_dashboard.py:523-525` `"Maria Chen"` / `"maria@example.test"` / `"provider said"` not in text | OPS2-01 **PII scrub** of `error_detail` at the route boundary | **2** |
| `test_dashboard.py:622, 691, 794, 1116, 1145` `assert hostile not in ...text` | **XSS** / hostile-`error_detail` reduction to bounded vocabulary | 1, 2 |
| `test_dashboard.py:1358, 1403` `assert unsafe_name not in response.text` | Roster-name injection into the resolve control | **2** |
| `test_phase20_clarification_review.py:800, 912, 913` `action="..." not in page.text` | The **anti-BUG-1 pin**: Reject must not be offered on the `can_fresh_send` branch, or an operator can reject a run whose confirmation already reached the client (`app/templates/run_detail.html:282` comment) | **2** |
| `test_dashboard.py:1384-1398` (9 asserts) | Delivery-review controls must **not** render outside their state | **2** |
| `test_needs_operator.py:1282-1283` `"Needs Operator"` / `"badge-escalate"` not in perturbed.text | Falsification half of the escalation badge test | **2** |
| `test_dashboard.py:1347` `"Resolve unresolved names" not in response.text` | Resolve control gated on status | **2** |
| `test_dashboard.py:1777` `"drafted and recorded" not in response.text.lower()` | Record-only flag must not read as a real send | **2** |

**Class D — hard-coupled to raw HTML, cannot survive in any form.**
`test_dashboard.py:651` `assert "Stage:</strong> Extraction" not in mismatched_detail.text` literally embeds `</strong>`. `test_dashboard.py:845` slices the response by `text.index("<script>")`. `test_dashboard.py:415` and `:1709` assert `'http-equiv="refresh"' not in response.text`. `test_design_tokens.py:339` regexes `class="([^"]*)"` out of `app/templates/*.html`.

---

## Critical Pitfalls

### Pitfall 1: The vacuous parity test — a falsification half left stranded in Python

**Owning slice:** all three, but the mechanism is *created* in Slice 1 and *most damaging* in Slice 2.

**What goes wrong:**
This repo's markup tests are written as **paired positive/falsification assertions**. Read `tests/test_dashboard.py:460-474`:

```
assert "/status" in response.text          # positive: in-flight run renders the poller
inflight_run["status"] = "reconciled"
settled = client.get(f"/runs/{run_id}")
assert "/status" not in settled.text        # :473 falsification: settled run does NOT
```

Same shape at `:1634` / `:1644` (`location.reload()` in → not in), and `:857-865` (`"var MAX_ATTEMPTS = 60" not in settled.text`).

When the poller moves into a bundle, `/status` and `location.reload()` and `MAX_ATTEMPTS` disappear from the served HTML **in both states**. The positive half turns RED and gets fixed — most likely by porting it to a Vitest/Playwright test. The **negative half turns GREEN and gets left behind**, because nothing fails. The Python file still reports "N passed," the assertion is still in the source where a reviewer sees it, and it now proves exactly nothing.

That is 44 dead pins, of which at least 20 protect PII scrubbing, XSS reduction, path traversal, or the delivery-review Reject gate.

**Why it happens:**
`assert X not in <empty page>` is the archetypal green-for-the-wrong-reason. Verbatim repetition of the project's own history: Phase 10's concurrency proof passed while the harness serialized the threads (`.planning/PROJECT.md:178`); Phase 21's `check_proof_inventory.py` docstring names the general form — *"that gap lives at the selection layer ... so no amount of watching pytest's exit code or 'N passed'/'N skipped' text can close it."* An absence assertion over a page that no longer renders anything is the same class: a **selection-layer** failure invisible from the execution layer.

**How to avoid — three enforceable moves, in order of strength:**

1. **Mutation-gate every migrated absence assertion.** Adopt the PROOF-01..05 discipline directly: for each Class-C pin, delete or neuter the React component that renders the guarded content and prove the migrated test goes **RED**. Register the target in an AST-anchored registry mirroring `MUTATION_TARGETS` / `tests/test_proof_mutation_targets.py`. A pin with no executed red run is not migrated, it is deleted.
2. **Convert every absence assertion into a positive assertion about a bounded vocabulary.** `assert hostile not in text` is unfalsifiable on an empty page; `assert response.json()["failure"] == {"secondary_label": None, "stage": None, "reason": None, "attempts": None}` is not. The existing `/runs/{id}/status` handler already models this: it returns a **fixed 7-key** object (`app/routes/runs.py:907-916`). Exact-equality assertions cannot go vacuous.
3. **Ban the shape at the API seam.** Add a Python-side guard that fails CI on any `assert <expr> not in <response>.text` remaining in the six affected files after the owning slice ships. `assert ... not in ....text` is a trivially AST-detectable pattern (`ast.Compare` with `ast.NotIn`), and `tests/test_operator_feedback.py:48-72` is the exact precedent for walking `ast` over a directory and collecting call sites.

**Warning signs:**
- A migration commit whose diff removes assertions and adds none; net assertion count down.
- Test count stays flat or rises while `grep -c 'not in .*\.text'` in the six files stays flat — meaning the absence pins were *carried forward*, not *migrated*.
- Any migrated test whose docstring still says "Falsification:" but whose subject moved to JS.
- `pytest -q` green on a branch where `app/templates/runs_list.html` has been deleted. That is the tell.

**Detection command to put in the plan:** after each slice, `git stash` the React entry component, run the suite, and require ≥1 failure per Class-C pin owned by that slice.

---

### Pitfall 2: `dist/` is already gitignored — the production bundle silently never ships

**Owning slice:** 1 (toolchain).

**What goes wrong:**
`.gitignore:5` is `dist/`. `Dockerfile:38` is `COPY . .`. Render builds the image from the **Git repo**, not the developer's working tree.

So: Vite's default `outDir` is `dist`. Put the bundle at `app/static/dist/` (the natural choice) and it is gitignored. `docker build` locally succeeds — the working tree has `dist/` on disk, and `.dockerignore` does **not** exclude it. CI succeeds — the Python suite doesn't need the bundle. Render deploys and serves `/runs` with a `<div id="root">` and a 404 on `/static/dist/index.js`. **A blank operator console in production, green everywhere else.**

The repo already documents this exact failure class one line at a time: `app/routes/dashboard.py:207-209` — *"The path is relative, so it only resolves if the container keeps WORKDIR=/app ... change that and this route 404s in production but passes locally."*

**Why it happens:**
`dist/` in `.gitignore` predates the milestone and reads as generic Python hygiene (setuptools build output). Nobody re-reads `.gitignore` when adding a frontend.

**How to avoid — pick ONE, explicitly, in the Slice 1 plan:**

- **(A) Build in the image (recommended).** Add a `node:22-slim AS frontend` stage; `COPY --from=frontend /fe/dist /app/app/static/dist`. **Ordering trap:** that COPY must come **after** `Dockerfile:53` `COPY --from=builder /app /app`, which copies the whole `/app` tree and will otherwise clobber it. Put it after line 53 and add a comment naming the clobber, in the style of the existing `Dockerfile:44-48` WORKDIR comment. Cost: image growth + build time (see Pitfall 8).
- **(B) Commit the bundle,** following the repo's own precedent that `eval/chart.svg` **is** committed and gated by `uv run python eval/run_eval.py --check` (`.github/workflows/eval.yml:29`). Requires un-ignoring the output dir (`!app/static/dist/`) **and** a `--check`-equivalent gate: rebuild in CI, diff against the committed artifact, fail on drift. Without the drift gate, option B is strictly worse than A.

**Either way, add one test that cannot be satisfied by a stale or absent bundle:** a hermetic test that resolves the script `src`/`href` out of the served HTML and asserts the referenced file exists on disk under `app/static/`. Mirror `app/routes/dashboard.py:210-212`'s existence check. That is the only assertion that catches "shipped an index.html pointing at a bundle that isn't there."

**Warning signs:**
- `git status` clean while `app/static/dist/` has files in it.
- `git ls-files app/static/dist | wc -l` returns 0 after a build.
- CI green, Docker build green, and no test anywhere references a built asset filename.
- `.dockerignore` never edited during Slice 1.

---

### Pitfall 3: The Jinja template IS the field allowlist — deleting it deletes the allowlist

**Owning slice:** 1 for the pattern + the guard; 2 for the largest exposure.

**What goes wrong:**
`app/routes/runs.py:220` `_safe_run_for_browser` is a **denylist**. `:232-241` names 8 fields to drop plus everything prefixed `job_`; `:242-245` pops them. What remains is handed **wholesale** to Jinja at `app/routes/runs.py:1339`:

```
"run": _safe_run_with_queue_projection(run_id, run),
```

This has been safe for four milestones **only because `run_detail.html` names the handful of keys it renders.** The template is the de-facto allowlist. Convert the page to React over a JSON API and that allowlist evaporates: `JSONResponse(content=safe_run)` ships everything the denylist forgot.

`RUN_COLS` (`app/db/repo/runs.py:38-42`) selects 15 columns. Subtract the 8 denied. **What leaks:**

| Field surviving the denylist | Why it must not be in a browser payload |
|---|---|
| `business_id` | Internal tenant UUID; the app has **no auth** (`.planning/PROJECT.md:274`), so any leaked id is a public id |
| `source_email_id` | Internal `email_messages` row id |
| `reply_epoch` | Internal concurrency counter (CLAR2-07); exposing it invites an epoch-guessing forgery surface on the resume path |
| `alias_candidates` | The alias-learning `{suggested, bound}` state — employee names + submitted tokens. PII, and the write side of a money-moving learning loop |
| `hours_changes` | Field-regression detection state |
| `extracted_data` | Full LLM extraction: employee names + hours. PII |
| `reconciliation` | Roster match detail: employee names + employee ids. PII |
| `decision` | Full gate reasoning blob |

Note the list view has the same shape from the other direction: `app/db/repo/demo.py:229-239` deliberately selects an **explicit** scalar list with SQL-computed aliases (`summary_gate_reason`, `employee_count`) precisely "so a new payroll_runs column can never silently reach the dashboard list view without a reviewed SQL edit" (`:216-220`). Slice 1's API must not undo that by re-fetching full rows.

**The auto-exposure mechanism:** add a 16th column to `RUN_COLS` — the project has done this before (`error_detail` in Phase 8, `alias_candidates` whose *absence* from `RUN_COLS` was a shipped Critical) — and it appears in the JSON payload with **no code change and no test failure**. A denylist plus a generic serializer is an opt-out security model on a table that grows.

**How to avoid:**
The correct pattern **already exists in this file**. `app/routes/runs.py:907-916` returns an explicit 7-key literal. Do exactly that: per-route Pydantic response models with `model_config = ConfigDict(extra="forbid")`, constructed field-by-field — never `Model(**safe_run)`.

**The failing test to write (Slice 1, extended per slice):**

```python
# 1. Exact-shape pin — superset assertions cannot catch a leak.
def test_run_dto_shape_is_exactly_the_allowlist():
    body = client.get(f"/api/runs/{run_id}").json()
    assert set(body) == EXPECTED_KEYS          # == , never <= , never "in"

# 2. Named-leak pin — asserts the specific fields by name.
def test_run_dto_never_carries_internal_fields():
    body = client.get(f"/api/runs/{run_id}").json()
    for forbidden in ("business_id", "source_email_id", "reply_epoch",
                      "alias_candidates", "hours_changes", "decision"):
        assert forbidden not in body

# 3. THE DRIFT PIN (the one that matters) — parse RUN_COLS from source and
#    force every column to be classified. Mirrors scripts/check_proof_inventory.py
#    and scripts/check_operator_resolution_inventory.py.
def test_every_run_col_is_classified_as_exposed_or_never_exposed():
    cols = {c.strip() for c in _read_run_cols_from_source().split(",")}
    assert cols == EXPOSED_KEYS | NEVER_EXPOSED_KEYS, (
        "a new payroll_runs column reached RUN_COLS without being classified "
        "for the browser API"
    )
```

Test 3 is the one that survives contact with the future: adding a column fails CI until a human writes it into one of two named sets. `RUN_COLS` is a plain string constant, so this is a source read, not a DB round trip — hermetic, no marker needed.

**Warning signs:**
- Any `JSONResponse(content=safe_run)`, `return safe_run`, `Model(**run)`, `model_dump()` on a dict built from `load_run`.
- A response model without `extra="forbid"`.
- A DTO test using `<=` or `assert "x" in body` instead of `==`.
- `/eval` doing the same thing with the whole `summary` dict (`app/routes/dashboard.py:186`) — Slice 3 has an identical exposure, including the `raw_body` the route injects.

---

### Pitfall 4: `fetch` for mutations silently deletes four working browser behaviors

**Owning slice:** 2 (14 of the 18 forms + all 5 confirm guards); 1 owns the enforcement guard; 3 owns `eval.html`'s one form.

**What goes wrong:**
The repo has **18 server-rendered `method="post"` forms**: 14 in `run_detail.html`, 1 in `runs_list.html`, 1 in `eval.html`, 2 in `index.html` (not converted). 15 POST routes; **every single one** returns `RedirectResponse(..., status_code=303)`. A `fetch` + manual refetch is *not* equivalent, in four distinct ways:

1. **Redirect-encoded state.** `app/routes/runs.py:626`:
   ```
   suffix = "?resolution_superseded=1" if not submission.authoritative else ""
   ```
   and `:627` redirects to `/runs/{id}{suffix}`. The flag exists **only in the redirect target**; `app/routes/runs.py:1236` reads it back as a `Query` param and `:1348` passes it to the template (`run_detail.html:18`). A `fetch` that reads the 303 `Location` and then GETs the bare path **drops the query string** and the operator is never told their resolution lost the race. That is a silent money-adjacent state loss.
2. **Redirect-to-new-resource.** `app/routes/demo.py:352` redirects to `/runs/{run_id}` for a run whose id the client did not have. A `fetch` must parse `Location` and route to it — and `fetch` follows redirects transparently by default, so the response you get back is the *rendered detail page*, not a `Location` header you can read.
3. **The Reject confirm guard.** `onsubmit="return confirm('Reject this payroll run? This cannot be undone.')"` appears **5 times** in `run_detail.html` (`:143, :155, :282, :286, :320`). **No test anywhere asserts it** — `grep -rn "onsubmit\|confirm(" tests/` returns zero hits. A React `<button onClick={reject}>` with no confirmation is a **fully undetected** regression on the destructive action.
4. **The `?notice=<code>` channel.** `app/routes/operator_feedback.py` is a whole module (22 allow-listed codes, `:25-95`) whose docstring states the reason plainly: *"A server-rendered form's only channel to explain WHY a POST did nothing is a 303 redirect back to the same page"* (`:3-4`). `notice_url` raises `KeyError` on an unknown code (`:113-115`). Every guard rejection — `approve_claim_lost`, `resolve_invalid_employee`, `authorize_bad_ack`, `retrigger_active_handoff` — reaches the operator through this mechanism. Convert to `fetch` and the operator sees a button that did nothing.

**How to make "no `fetch` for mutations" enforceable, not a convention:**

The repo's AST-guard precedent is real but **Python-only** — `tests/test_operator_feedback.py:48-72`, `tests/test_bound01_private_imports.py`, `tests/test_background_task_cutover.py`, `tests/test_job_kind_drift.py`, `tests/test_proof_mutation_targets.py` (17 test files import `ast`). Python's `ast` cannot parse `.tsx`. Do not pretend otherwise, and do **not** substitute a regex over TypeScript source: this project has already been burned by a verification grep that silently lied (`git grep -E` ignoring `\b`).

Three layers, all three:

- **(a) Architectural, therefore self-enforcing (do this one).** Keep every mutation form **server-rendered**. Render `/runs/{id}` from `base.html`/a Jinja shell that still emits the 14 `<form method="post">` blocks, and mount React as an **island** into the read-only regions. Then the existing Python assertions (`tests/test_phase20_clarification_review.py:776`, `:800`, `:911-913`; `tests/test_reply_redelivery.py:674`; `tests/test_dashboard.py:1029`) keep working **unchanged**, and the 303/notice/confirm semantics keep working because they were never touched. This is the single highest-leverage decision in the milestone: it converts Pitfall 4 from a risk into a non-event and it shrinks Pitfall 1 by most of its blast radius.
- **(b) Python-side, positive, mutation-provable.** A guard test that, for each of the 15 POST routes, GETs the page in the state that should offer the control and asserts the served HTML contains `method="post"` with `action="<that route>"`. This is only *possible* if (a) holds — which is the point. Pair it with a pin on the 5 `confirm()` guards (currently zero coverage): `assert response.text.count("return confirm('Reject this payroll run?") == expected`.
- **(c) Node-side, banning the escape hatch.** In the Slice-1 frontend lint config, `no-restricted-syntax` / `no-restricted-globals` banning `fetch`, `XMLHttpRequest`, `axios`, and `navigator.sendBeacon` outside one allow-listed read-only data module, plus banning `method: 'POST'` anywhere. Red-proof the rule (write a file that violates it, confirm lint fails, revert) before wiring — same discipline as `check_proof_inventory.py` being red-proofed hermetically before CI wiring.

**Warning signs:**
- Any React component importing a mutation helper.
- A test whose fix for a 303 was to assert `status_code == 200`.
- Any route changed from `RedirectResponse(303)` to `JSONResponse` — this violates the stated byte-identity constraint and should fail review immediately.
- `grep -c 'onsubmit' app/templates/run_detail.html` returning less than 5 after Slice 2.

---

### Pitfall 5: An SPA fallback route swallows `/webhook` — inbound payroll email is lost

**Owning slice:** 1. This must not be deferred; Slice 1 is where the mount is created.

**What goes wrong:**
`app/main.py` is 19 lines. Line 11 mounts `/static`; lines 13-19 `include_router` seven routers **after** it. Starlette resolves routes by iterating `app.routes` **in registration order** and taking the first FULL match. A catch-all — `app.mount("/", StaticFiles(directory=..., html=True))` or `@app.get("/{full_path:path}")` — FULL-matches **every** path.

Register it anywhere before line 13 and it shadows:
- `/webhook/inbound` (`app/routes/webhook.py:111`) — **inbound payroll email is silently lost.** The Resend/Svix webhook gets a 200 with an HTML body; the provider considers delivery successful and never retries. Runs simply never exist. `/health/queue` cannot alarm on a run that was never created (its predicate is an anti-join over `error` runs), so the ops view stays green.
- `/health/live`, `/health/ready`, `/health/queue`, `/health/schema` — Render's health check passes on the SPA index, so a genuinely broken app deploys green.
- `/internal/pump` — the 30-minute cron that IS durable execution on Render free (`.planning/PROJECT.md:329`). Shadowed, the queue reverts to durable *storage*: jobs accumulate and nothing drains.
- `/ops` — the page you read when everything is broken.

**The production-only variants (these are the ones that get shipped):**
- **Mount ordering.** `app.mount()` appends. Adding the SPA mount next to the existing `/static` mount at line 11 — the visually natural place — puts it **before** all seven routers.
- **Trailing slash.** Starlette's `redirect_slashes` fallback only runs *after* the whole route table produced no FULL match. A catch-all guarantees a FULL match always exists, so the 307 slash-redirect silently stops happening. `/runs/` today 307s to `/runs`; with a catch-all it serves the SPA index instead. Anything (a bookmark, a Loom demo link, a README URL) with a trailing slash breaks, and only in the deployed app.
- **`StaticFiles(html=True)`** serves `index.html` for a missing path, converting every genuine 404 into a 200. Route-shadowing becomes undetectable by status code alone.

**How to avoid:**

1. **Prefer no catch-all at all.** Server-render each converted page from its existing route (`app/routes/runs.py:855`, `:1232`, `app/routes/dashboard.py:150`) with a Jinja shell that mounts a React island. No client router, no history API, no fallback route, no shadowing surface. Given `/` and `/ops` stay Jinja and there are exactly three converted pages, a client-side router buys nothing.
2. **If a catch-all is unavoidable, prefix-scope it** (`/app/...`) — never mount at `/`.
3. **A route-ordering guard test, in Slice 1, red-proofed.** Two halves:
   ```python
   RESERVED = ("/webhook/inbound", "/health/live", "/health/ready", "/health/queue",
               "/health/schema", "/internal/pump", "/ops", "/runs", "/eval", "/")
   def test_no_route_shadows_a_reserved_prefix():
       # (a) structural: the index of any catch-all in app.routes is greater than
       #     the index of every reserved path's route.
       # (b) behavioral: for each reserved path, resolve it through the real app
       #     and assert the matched endpoint is the expected function object —
       #     NOT that the status is 200 (html=True makes 200 meaningless).
   ```
   Half (b) is load-bearing: assert on the **matched endpoint identity**, not the status code. Then red-proof it by moving the mount above `include_router(webhook.router)` and confirming it fails.
4. **Add `/webhook/inbound` and `/internal/pump` to the reserved list explicitly by name in the test source**, with a comment naming the consequence ("a shadowed webhook loses inbound payroll email; the provider will not retry a 200"). This repo's comment convention is to name the failure the code prevents.

**Warning signs:**
- Any `app.mount("/", ...)` or `{full_path:path}` route.
- `app/main.py` growing past ~25 lines.
- Any 404 test that starts passing with a 200.
- `curl -s https://payroll-agent.onrender.com/health/live | head -c 20` returning `<!DOCTYPE html`.

---

### Pitfall 6: Three design-token guards go blind on `.tsx`, and one dies at import

**Owning slice:** 1 (the `js-` hooks + the guard-scope fix); 2 and 3 inherit the widened globs.

**What goes wrong — four distinct failures in one file.**

**(6a) `tests/test_design_tokens.py:352` reads `runs_list.html` at MODULE IMPORT TIME:**
```python
_RUNS_LIST_HTML = (_REPO_ROOT / "app" / "templates" / "runs_list.html").read_text()
```
Delete `runs_list.html` in Slice 1 and this raises `FileNotFoundError` during **collection** — the whole file errors out, including the WCAG contrast gates and the token-single-source gate. The path of least resistance is to delete the test file. That silently drops the AA contrast assertions at `:217-244` and `:272-297`, and the token-first single-source rule at `:202-214`.

**(6b) The `js-` hooks are LIVE and this mistake was already made once.** `grep -c "js-" app/static/style.css` returns **0** — `js-status-badge`, `js-failure-secondary`, `js-failure-summary` have zero styling. They are pure `document.querySelector` hooks, read at `app/templates/runs_list.html:24, 26, 35, 40` against a `[data-run-id="..."]` root, emitted at `:87, :91, :95`. `tests/test_design_tokens.py:355-365` asserts each hook **is present in `runs_list.html`** and **absent from `style.css`**; `:367-374` asserts the unprefixed former names appear in neither. To a React developer these classes look like dead markup with no CSS behind them. Deleting them breaks in-place status polling — which is Slice 1's own headline feature.

**(6c) Two guards silently narrow their scope.** `tests/test_design_tokens.py:191` and `:337` both iterate `_REPO_ROOT.glob("app/templates/*.html")`. Convert three pages and the glob returns 4 files instead of 7. **Both tests still pass** while covering less: the superseded-accent-hex ban (`#4F46E5`, `#4338CA`, the old ring rgba) and the `btn`-composition rule no longer see the markup that now lives in `.tsx`. A `<button className="btn-approve">` missing the base `btn`, or a hardcoded `#4F46E5` in a component, ships clean.

**(6d) One guard has a hardcoded suffix allowlist.** `tests/test_design_tokens.py:180-186`:
```python
if path.suffix not in {".css", ".html", ".py"}:
    continue
assert "accent-soft" not in contents
```
`.tsx`, `.ts`, and any CSS-in-JS are skipped by construction. This is verbatim the repo's own recorded lesson: *"a passing guard proves nothing about what it doesn't scan."*

**How to avoid (Slice 1 owns all of it, because Slice 1 is where the first template disappears):**

- Widen `{".css", ".html", ".py"}` at `:183` to include `.ts`, `.tsx`, `.css`, `.scss` — **and** add a companion test that asserts the scanned-file **count is non-zero for each extension present in the repo**, so a future extension can't silently escape. Scope-pinning, not just scope-widening.
- Replace both `glob("app/templates/*.html")` calls with a helper that returns templates **plus** frontend sources, and assert the returned set is non-empty for each root.
- Move `_RUNS_LIST_HTML` (`:352`) from module scope into the test body, and re-point the `js-` hook assertions at wherever the poller now lives. If the poller stays server-rendered per Pitfall 4(a), no change is needed at all — another argument for the island architecture.
- **Do not re-derive the token layer in TS/CSS-in-JS.** Keep `app/static/style.css` as the single `:root` source and have React consume `var(--accent)` etc. `tests/test_design_tokens.py:202-214` asserts each waiting-family hex appears **exactly once** in `style.css`; a second declaration in a `.ts` theme object doesn't trip it (wrong file) but does create the exact drift `DESIGN.md` names as the system's main risk.

**The accessibility guarantees, individually, with their real status:**

| Guarantee | Where it lives | Asserted? | Risk on conversion | Slice |
|---|---|---|---|---|
| Per-page `<title>` | `base.html:6` block + `{% block title %}` in each of 5 templates | **No test asserts `<title>`** (`grep -rn "title>" tests/*.py` → 0 hits) | Lost silently. React must set `document.title` or keep the Jinja shell | 1, 2, 3 |
| Nav `aria-current="page"` | `base.html:12-15`, driven by `request.url.path` | **Yes** — `tests/test_dashboard.py:573-582`, exactly-once across `/`, `/runs`, `/eval` | Fails **loudly** if React owns the document; **free** if the Jinja shell is kept | 1, 3 |
| Focusable scroll regions `role="region" tabindex="0"` | `runs_list.html:65`, `eval.html:39` (also `ops.html:69, :94`) | **No test asserts them** | Lost silently in Slice 1 and Slice 3 | 1, 3 |
| `overflow-x: auto` | `style.css:251, :675` | No direct test; `test_design_tokens.py:254-264` pins the `max-width:700px` block reaching `nav`, `.page-wrapper`, `.form-inline`, `.demo-select` | Survives if `style.css` stays authoritative | 1 |
| Zero horizontal overflow at 375px | Verified manually at a real viewport; no automated pin | **No** | Regressible with no signal | 1, 2, 3 |
| `<noscript>` fallback | `app/templates/index.html:53` — **the only one in the repo** | No | **Not at risk**: `/` is not converted. Do not claim credit for preserving it | n/a |

Add the two missing pins (`<title>` per page, `role="region" tabindex="0"` count) in the slice that converts each page — cheap, and they close guarantees that currently have *zero* automated coverage and would otherwise vanish unnoticed.

---

### Pitfall 7: A frontend test suite that isn't actually selected

**Owning slice:** 1.

**What goes wrong:**
Class-B assertions (87 of them) get ported into Vitest/Playwright. The node job runs, prints "12 passed," CI goes green — and it never picked up the migrated files, because of a `testMatch` glob that doesn't cover `src/**`, a `--project` filter, a `describe.skip` left in, or a config `exclude` that also swallowed the new directory.

This is the failure `scripts/check_proof_inventory.py` was written for, restated: *"a typo'd marker on one newly-added test, while the other tests still pass, leaves the CI log reading 'N passed' while the new test silently never ran. That gap lives at the selection layer ... not the execution layer, so no amount of watching pytest's exit code or 'N passed' text can close it."*

**How to avoid:** an inventory gate, exactly like `check_proof_inventory.py` + `tests/test_proof_inventory.py`. A pure decision function over the test runner's **collection** output (`vitest list --json` / `playwright test --list --reporter=json`) that asserts: every `*.test.tsx` file on disk appears in the selected set, and the selected count is ≥ a committed floor per slice. Red-proof it (rename one test file so it stops matching; confirm the gate fails) before wiring.

**Warning signs:** a node job whose "N passed" is suspiciously round or unchanged after adding files; a `vitest.config.ts` `exclude` entry added to "fix" a failure; no committed floor.

---

### Pitfall 8: Render free realities — the demo's first impression becomes a spinner

**Owning slice:** 1 sets the ceiling and the shell strategy; 2 and 3 must stay under it.

**What goes wrong:**
Today's baseline, measured: **25,219 bytes** of CSS (`app/static/style.css`), **zero** external JS files, two small inline `<script>` blocks (`runs_list.html:10`, `run_detail.html:32`). The single largest static asset is `demo-thumbnail.gif` at **382,172 bytes** — and it is only on `/`, which is not converted.

A cold Render free instance sleeps after 15 idle minutes and takes up to ~1 minute to wake. The primary audience is hiring managers clicking a portfolio link — i.e. **always the cold path**.

Sequence today: wake (~40-60s) → one round trip → **fully rendered page with real data**.
Sequence after a naive conversion: wake (~40-60s) → HTML shell → bundle request → parse/execute → API request (which may itself re-wake a cold DB pool) → paint. The reviewer stares at a blank `#root` for the last few seconds *after* already waiting a minute. It reads as broken. The milestone's entire justification is portfolio signal; this pitfall attacks the justification directly.

Docker/cold-start second order:
- `Dockerfile:38` `COPY . .` then `:53` `COPY --from=builder /app /app`. `.dockerignore` excludes `.venv/`, `tests/`, `scripts/`, `.github/`, `.planning/` — **but has no entry for `node_modules/` or a `frontend/` source dir.** A local `node_modules` (commonly 200-400 MB) is copied into the builder and then wholesale into the runtime image. Slower pulls, slower cold starts, on the exact platform where cold start is the constraint.
- Render's ephemeral filesystem means nothing survives a restart, so build-at-boot is not an option; the bundle must be in the image (Pitfall 2).

**How to avoid:**
- **Server-render the shell and the above-fold content.** Keep `base.html` (nav, `<title>`, the already-linked stylesheet) and server-render the page's summary; hydrate/mount React into the interactive regions. Same architecture that fixes Pitfalls 4, 5, and 6b. This is the load-bearing choice.
- **A committed bundle-size budget with a CI gate, in Slice 1.** Assert total gzipped JS under an explicit byte ceiling. Precedent: `eval/chart.svg` is committed and gated. Pick the number in Slice 1 and let Slices 2 and 3 inherit it — a budget added at the end is a budget that gets raised.
- **Never render a bare spinner on a converted page.** Server-rendered skeleton or nothing.
- **Add `node_modules/`, `frontend/node_modules/`, and the frontend source dir to `.dockerignore`** in Slice 1 (source only needed if the build happens in a node stage that copies it explicitly).
- **`/ops` staying script-free (`tests/test_ops_route.py:366`) is the mitigation, and it is only a mitigation if it stays true.** It is the page an operator reads when the bundle is the thing that's broken. Do not "unify the nav" or add a shared header component that injects a `<script>` tag into `base.html` — that would break `:366` from three pages away. If React needs a script tag in the shared layout, it must be conditional and `ops.html` must be pinned as the negative case with a red-proof.

**Warning signs:** first contentful paint on a converted page is an empty container; bundle size ungated; `docker images` size up by >100 MB; anything added unconditionally to `base.html`.

---

### Pitfall 9: Scope creep into money-moving code, dressed up as "making the API cleaner"

**Owning slice:** 1 defines the fence; all three enforce it.

**What goes wrong — the specific gradient, in the order it happens:**
1. The React run-detail page needs a field shaped differently than `RUN_COLS` provides. The clean-looking fix is a new SQL column or a widened `load_run`. That is `app/db/` — out of scope.
2. `run_detail.html` currently derives display values inside Jinja (badge filters, `run.failure` composition). Porting those to TS "duplicates logic," so the tempting move is to compute them in the pipeline and persist them. That is `app/pipeline/` — out of scope, and it puts presentation vocabulary into the money path.
3. A mutation route's 303 is "awkward for the SPA," so it grows a `?format=json` branch or an `Accept`-header switch. That edits a mutation handler — and byte-identity is the milestone's own constraint.
4. `_safe_run_for_browser`'s denylist (`app/routes/runs.py:232-241`) is "obviously wrong, let's make it an allowlist while we're here." Correct instinct, wrong scope: it changes what the **Jinja** pages render too, and `/ops`-adjacent and `/`-adjacent behavior is not covered by the slice's tests.

**Why it happens:** every one of these is a genuinely better design. That is exactly why the fence has to be mechanical rather than a judgment call at review time.

**How to avoid — a per-slice diff-scope gate, in CI, from Slice 1:**
```
git diff --name-only <slice-base>..HEAD | \
  grep -E '^app/(pipeline|queue|db|llm|email)/' && exit 1
```
Fold it into the existing `lint` job (`.github/workflows/ci.yml:30-48`) so it is one of the three already-blocking gates rather than a fourth optional one. Then:
- Add a **mutation-handler byte-identity check**: AST-diff the 15 POST handler bodies against the pre-milestone base with docstrings stripped. This is not novel here — `.planning/PROJECT.md:57-60` records exactly this technique used against `tax_tables_2026.py` (194 numeric literals AST-diffed) in v3. Reuse it.
- If a genuine out-of-scope need appears, it goes to `backlog.md` as a separate item — **not** into the slice. The project's own worst-documented failure is work shipping inside an untracked task while the tracking artifact was never updated (`.planning/PROJECT.md:219-227`), which later caused a whole milestone to be scoped from a stale backlog. A React slice that quietly improves the denylist and never records it is that failure recurring.

**Warning signs:** any diff hunk under `app/pipeline/`, `app/queue/`, `app/db/`, `app/llm/`, `app/email/`; a schema migration in a presentation milestone; a commit message containing "while I was in there"; the phrase "the API needed" in a plan.

---

### Pitfall 10: A cleanup call that IS the assertion, wrapped to make it green

**Owning slice:** all three.

**What goes wrong:**
The project has this exact scar: a test whose cleanup call *was* the assertion under test got wrapped in `try/finally`, turning a real deploy-blocker green over seven tests. The React analogue is `act()` / `cleanup()` / `unmount()`: if a test's subject is "the poller stops on unmount" or "the interval is cleared," then `afterEach(cleanup)` swallowing the failure is suppression, not hygiene. Likewise `await waitFor(...)` wrapped so a timeout is caught, or a Playwright `expect` inside a `try`.

The Slice-1 poller is precisely this shape: `tests/test_dashboard.py:473` currently pins "a settled run does **not** render the poller." Its React equivalent — "the interval is cleared when status settles" — is a teardown-observable property. A leaked interval on a free-tier instance means every open tab polls forever.

**How to avoid:** in the frontend test config, ban `try`/`catch` around any `expect`/`waitFor` via lint. Require that any test whose subject is a teardown property assert on the teardown **observable** (interval id cleared, `fetch` call count stops rising) rather than relying on cleanup not throwing. And apply the general rule the scar taught: **check whether the failure you are routing around originates in the thing you are suppressing.**

**Warning signs:** `try`/`finally` or `try`/`catch` appearing in a frontend test; a flaky test "fixed" by adding a wrapper; `--retries` raised.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|---|---|---|---|
| Convert the whole document to React (client router + SPA fallback) | Feels like "a real SPA" | Creates Pitfall 5 (route shadowing) from nothing; breaks `aria-current` (`base.html:12-15`) and per-page `<title>`; forces the bundle onto the critical path of a cold start | **Never** here — 3 pages, no auth, and `/` + `/ops` stay Jinja |
| Serialize `_safe_run_for_browser` output directly (`app/routes/runs.py:220`) | One-line API | Leaks 8 internal/PII fields today and auto-exposes every future `RUN_COLS` column | **Never** — the correct 7-field pattern is 690 lines away at `:907-916` |
| `fetch` for mutations | No full page reload | Silently deletes 4 behaviors incl. an untested `confirm()` on a destructive action | **Never** in this milestone; it is an explicitly falsified decision |
| Migrate absence assertions verbatim into the React-era tests | Test count preserved; diff looks small | 44 vacuous pins, ~20 of them security/PII/money | **Never** — convert to positive/exact-equality or delete with the reason recorded |
| Delete `tests/test_design_tokens.py` when `runs_list.html` goes away | Unblocks collection immediately | Silently drops all WCAG AA contrast gates + the token single-source rule | Never — move the module-level read at `:352` into the test body instead |
| Build the bundle locally, commit nothing, rely on `COPY . .` | Zero CI change | Blank page in production only (`.gitignore:5` `dist/`) | Never |
| Commit built assets with no rebuild-and-diff gate | Simple Dockerfile | Stale bundle deploys indefinitely, invisible | Only with an `eval --check`-equivalent drift gate (`.github/workflows/eval.yml:29`) |
| Skip the per-slice diff-scope gate; rely on review | Saves an hour in Slice 1 | Money-path edits land in a presentation milestone | Never — one `grep` in the existing `lint` job |
| Duplicate design tokens into a TS theme object | Type-safe tokens | Drift from `style.css`'s single `:root`, which `test_design_tokens.py:202-214` guards *only inside style.css* | Only if the TS object is *generated* from `style.css` and the generation is CI-verified |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|---|---|---|
| Vite `base` + FastAPI `StaticFiles` | Leave `base: '/'`; Vite emits `/assets/index-xxx.js`; dev works, production 404s (nothing is mounted at `/assets`; only `/static` is, at `app/main.py:11`) | Set `base: '/static/dist/'` and `build.outDir` to `app/static/dist`; add a test that resolves the emitted `src` and asserts the file exists on disk |
| Multi-stage Dockerfile | `COPY --from=frontend /fe/dist /app/app/static/dist` placed **before** `Dockerfile:53` `COPY --from=builder /app /app`, which clobbers it | Place it **after** line 53, with a comment naming the clobber (repo convention: comments name the failure prevented, e.g. `Dockerfile:44-48`) |
| `.gitignore` / `.dockerignore` | `dist/` ignored (`.gitignore:5`) so Render's build context has no bundle; `node_modules/` absent from `.dockerignore` so it lands in the image via `COPY . .` | Un-ignore the build output **or** build in-image; add `node_modules/` to `.dockerignore` |
| Render `$PORT` / WORKDIR | Assume relative asset paths are stable | `app/routes/dashboard.py:207-209` already documents that a WORKDIR change makes a route "404 in production but pass locally". Any new relative path inherits this |
| Render free spin-down | Bundle on the critical path of a cold start | Server-render the shell + above-fold; bundle enhances |
| Resend / Svix webhook | Assume a shadowed route surfaces as an error | A 200 with an HTML body is a **successful** delivery to the provider; no retry, no alarm. Assert the matched **endpoint identity**, not the status |
| GitHub Actions `pump.yml` cron | Assume `/internal/pump` is safe because it's authenticated | Auth runs *after* routing. A catch-all registered first never reaches the auth check |
| `uv.lock` + `package-lock.json` | Node deps installed with `npm install` in CI (re-resolves silently) | `npm ci` — the exact analogue of the existing `uv sync --locked` at `ci.yml:45, :65, :92`, whose comment states the rationale: "a stale lockfile fails the job rather than merging green". Commit `package-lock.json`; pin the Node version the way `.python-version` pins Python |
| `mypy --strict` / `ruff` on new Python DTOs | Assume the frontend dir needs excluding | `pyproject.toml` sets `files = ["app", "eval", "scripts", "tests"]` with **no exclude** — a `frontend/` dir is outside that scope already. New DTO modules under `app/` are covered automatically and **will** be `--strict`-checked; Pydantic response models need full annotations plus the `pydantic.mypy` plugin's stricter defaults |
| pytest collection | Fear that `node_modules` breaks `pytest -q` | pytest's default `norecursedirs` already includes `node_modules` and `dist`; ruff's default `exclude` includes both. No config change needed — but this also means **nothing Python-side will ever lint or scan the frontend**, which is why Pitfall 6d matters |

---

## Performance Traps

| Trap | Symptoms | Prevention | When it breaks |
|---|---|---|---|
| Bundle on the cold-start critical path | Blank `#root` for seconds *after* a ~60s wake | Server-rendered shell + above-fold; gzipped-JS budget gated in CI | Immediately, on the very first reviewer visit |
| Per-row polling from React with no unmount cleanup | `fetch` count to `/runs/{id}/status` grows without bound; the free instance never idles | Assert the teardown observable (Pitfall 10), not "cleanup didn't throw" | At 2 in-flight runs on a tab left open |
| Node stage inflating the image | Slower pulls, longer cold start | Multi-stage; `node_modules` in `.dockerignore`; copy only `dist` | Every cold start, forever |
| A React list refetching the whole run object per row | `/runs` list query cost jumps from `demo.py:229-239`'s explicit scalar projection to N full-row reads | Keep the list DTO derived from the existing explicit projection; never `load_run` per row | At ~20 runs on Supabase free |
| `/eval` shipping the whole `summary` + injected `raw_body` as JSON | Payload size jumps; every fixture body crosses the wire on page load | Explicit DTO; lazy-load `raw_body` per fixture on drill-in | At ~20 fixtures (18 exist today) |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---|---|---|
| Serializing the `_safe_run_for_browser` denylist output (`app/routes/runs.py:220-245`) | Exposes `alias_candidates`, `extracted_data`, `reconciliation` (employee names + hours = PII), `business_id`, `source_email_id`, `reply_epoch` on an app with **no auth** (`PROJECT.md:274`) | Explicit per-route DTOs, `extra="forbid"`, exact-shape test, plus the `RUN_COLS` classification drift pin (Pitfall 3) |
| A future `RUN_COLS` column auto-exposed | Silent PII/internal-state leak with no code change and no failing test | The classification drift pin — the only guard that fails on a *future* edit |
| Migrating the path-traversal sentinel (`tests/test_dashboard.py:309`) to check the HTML shell instead of the JSON | Re-opens the `/eval` fixture path traversal (`app/routes/dashboard.py:178-182`) — a defect this project already shipped and fixed once | Re-point the sentinel at the API response body; mutation-prove it red by reverting the `is_relative_to` check |
| Migrating the PII-scrub pins (`tests/test_dashboard.py:523-525`) into a page that no longer renders `error_detail` | Re-opens OPS2-01: raw provider errors carrying roster names + client emails reach the browser | Assert on the **DTO**: `assert body["failure"]["reason"] in BOUNDED_VOCABULARY` and `assert "error_detail" not in body` |
| Client-side XSS reintroduction | The 5 `hostile not in ...text` pins go vacuous; React auto-escapes, but `dangerouslySetInnerHTML` does not | Lint-ban `dangerouslySetInnerHTML`; keep the hostile-string pins as positive bounded-vocabulary assertions on the DTO |
| A catch-all route shadowing `/webhook/inbound` (`app/routes/webhook.py:111`) or `/internal/pump` | Inbound payroll email silently lost (provider sees 200, never retries); the authenticated pump becomes unreachable and the queue stops draining | Endpoint-identity route-ordering guard, red-proofed (Pitfall 5) |
| A shared-layout `<script>` reaching `ops.html` | Breaks `tests/test_ops_route.py:366` and, worse, makes the break-glass page bundle-dependent | Keep any script tag conditional; pin `ops.html` as the negative case with a red-proof |
| Notice codes rendered client-side from the query string | `notice_label` (`operator_feedback.py:98-100`) reduces an unknown code to `None` **server-side**, specifically so a hand-crafted URL renders no banner. Client-side rendering of `?notice=` reintroduces attacker-chosen text | Never read `?notice=` in TS. Server-render the banner (`_operator_notice.html`) |

---

## UX Pitfalls

| Pitfall | User impact | Better approach |
|---|---|---|
| Spinner replaces server-rendered HTML | On a cold free instance the demo reads as broken to the exact audience the milestone exists for | Server-render shell + above-fold; React enhances |
| Reject loses its `confirm()` (`run_detail.html:143, 155, 282, 286, 320`) | One misclick irreversibly rejects a payroll run. Zero test coverage today | Keep native `onsubmit`; add the missing count pin |
| `?resolution_superseded=1` dropped (`app/routes/runs.py:626`) | Operator's resolution silently lost the race and they are never told; they believe they applied a name mapping that was discarded | Preserve the 303 + query round trip |
| `?notice=<code>` dropped (22 codes, `operator_feedback.py:25-95`) | Every guard rejection reads as "the button is broken" — the module's docstring names this as the bug it exists to fix | Preserve native form POST + 303 |
| Focusable scroll regions lost (`runs_list.html:65`, `eval.html:39`) | Keyboard users cannot reach horizontally-scrolling table content | Port `role="region" tabindex="0" aria-label`; add the missing pin |
| Per-page `<title>` lost (5 templates set `{% block title %}`) | Browser tabs and history all read "Pyrl" | Keep the Jinja shell or set `document.title`; add the missing pin |
| In-place badge polling replaced by a full refetch | Loses the "no dropdown reset, no scroll jump" property the vanilla poller was built for (`app/routes/runs.py:895-897`) | Preserve in-place update semantics |

---

## Progressive Enhancement: decide each page explicitly

The question was raised as "what dies quietly." Answered per page, with the honest verdict.

| Page | No-JS behavior today | After conversion | Verdict |
|---|---|---|---|
| `/` (landing) | Fully works; `index.html:53` holds the repo's **only** `<noscript>` | **Unchanged — not converted** | Safe. Do not claim credit for preserving it |
| `/ops` | Fully works, zero `<script>`, pinned at `tests/test_ops_route.py:366` | **Unchanged — not converted** | This is the deliberate counter-example and the mitigation for "the page you read when everything is broken." Protect the pin |
| `/runs` list | Renders fully; the poller is enhancement only (`meta refresh` was already removed — `tests/test_dashboard.py:415`) | **ACCEPT the loss** if React owns the table; **avoid** it if the shell is server-rendered | Decide in Slice 1. Recommendation: server-render the table rows, mount React for interactivity — no-JS keeps working for free |
| `/runs/{id}` | Renders fully; 14 forms all submit natively | **The 14 forms MUST keep working without JS** — that is Pitfall 4(a). Read-only regions may require JS | Split decision, recorded in Slice 2 |
| `/eval` | Renders fully; `chart.svg` is a plain `<img>` served by `app/routes/dashboard.py:200` | **ACCEPT the loss** — read-only, no money path, one form | Cheapest slice; still needs the path-traversal sentinel re-pointed |

**The rule to write into the roadmap:** a page may lose no-JS *reading*; a page may not lose no-JS *mutating*. Every one of the 15 POST routes touches run state and 12 of them touch a money-moving gate (approve, reject, resolve, retrigger, authorize, mark-delivered).

---

## "Looks Done But Isn't" Checklist

- [ ] **Markup-test migration:** Often missing the falsification half — verify by deleting the React component and confirming ≥1 RED per Class-C pin owned by the slice. "N passed" is not evidence.
- [ ] **Test-scope inventory:** Often scoped to the 2 files PROJECT.md names — verify all **6** files (`test_dashboard`, `test_needs_operator`, `test_phase20_clarification_review`, `test_reply_redelivery`, `test_hitl`, `test_clarify_round_hours_safety`) were opened.
- [ ] **Built bundle:** Often gitignored (`.gitignore:5`) — verify `git ls-files app/static/dist | wc -l` is non-zero, **or** that the node stage runs and its COPY sits after `Dockerfile:53`.
- [ ] **Bundle actually referenced:** Often a stale filename — verify a test resolves the `src` out of the served HTML and asserts the file exists.
- [ ] **Route ordering:** Often verified by status code — verify by asserting the **matched endpoint object** for `/webhook/inbound`, `/health/*`, `/internal/pump`, `/ops`; then red-proof by reordering the mount.
- [ ] **Trailing slash:** Often untested — verify `/runs/` still 307s and does not serve the SPA index.
- [ ] **DTO shape:** Often asserted with `<=` or `in` — verify the assertion is `set(body) == EXPECTED`, and that the `RUN_COLS` classification test exists and fails when a 16th column is added.
- [ ] **Mutation forms:** Often "equivalent" — verify `grep -c 'method="post"' app/templates/run_detail.html` is still 14 and `grep -c onsubmit` is still 5.
- [ ] **`?resolution_superseded=1` and `?notice=`:** Often dropped — verify a test drives the POST and asserts the **final URL** carries the query param, not just that the POST returned 303.
- [ ] **`js-` hooks:** Often deleted as dead markup (already happened once) — verify `js-status-badge`, `js-failure-summary`, `js-failure-secondary` still resolve to live poller hooks and status polling works end to end.
- [ ] **Design-token guards:** Often silently narrowed — verify `test_design_tokens.py:183`'s suffix set includes `.ts`/`.tsx`, both `glob("app/templates/*.html")` calls at `:191`/`:337` also scan frontend sources, and each scanned root asserts a non-zero file count.
- [ ] **`/ops` script-free:** Often broken from a shared layout — verify `tests/test_ops_route.py:366` still passes **and** that anything added to `base.html` is conditional.
- [ ] **A11y:** Often silently lost — verify per-page `<title>`, `aria-current` exactly once, `role="region" tabindex="0"` on scroll regions, and zero horizontal overflow at 375px. Three of these four have **no automated pin today**; add them in the owning slice.
- [ ] **Money-path fence:** Often assumed — verify `git diff --name-only <base>..HEAD | grep -E '^app/(pipeline|queue|db|llm|email)/'` is empty, and that the 15 POST handler bodies AST-diff clean against the pre-milestone base.
- [ ] **Frontend suite selected:** Often silently empty — verify a collection-inventory gate exists with a committed floor, and that it was red-proofed.
- [ ] **Deployed, not just merged:** v4 Phase 21's UAT found the whole phase unpushed while CI was green. Run `git rev-list --count origin/master..master` before claiming a slice ships, and hit the live URL.

---

## Recovery Strategies

| Pitfall | Recovery cost | Recovery steps |
|---|---|---|
| Vacuous parity tests discovered late | **HIGH** | You cannot tell which pins are live without re-deriving them. Re-run the whole Class-C list through mutation; expect to rewrite most. Cost scales with slices shipped — this is why the mutation gate belongs in Slice 1, not a cleanup phase |
| Bundle not in the production image | LOW | Un-ignore the dir or add the node stage; redeploy. Cheap *if* caught — but its natural discovery channel is a reviewer seeing a blank page |
| Route shadowing found in production | **HIGH** | Reorder the mount and redeploy is minutes. The damage is the lost inbound emails: they were 200'd, the provider will not retry, and the runs never existed. Recovery means asking clients to resend. **Prevent, do not recover.** |
| Serialization leak shipped | MEDIUM-HIGH | Narrow the DTO and redeploy is small. But the payloads are already out, and with no auth the exposure window is public. Add the drift pin in the same commit |
| `confirm()` guard lost + a run wrongly rejected | **HIGH** | `rejected` is a terminal status (`app/db/repo/runs.py:52-58`) that `record_run_error` must not clobber. Recovery is manual DB surgery on an audit-trail table |
| Design-token guards silently narrowed | MEDIUM | Widen the scope, then re-audit every `.tsx` against `:root` by hand — the gap covers everything shipped since the narrowing |
| Cold-start UX regression | MEDIUM | Re-introducing a server-rendered shell after building a client-routed SPA is a partial rewrite of the shell layer. Cheap only if the island architecture was chosen up front |
| Money-path edit merged | MEDIUM | Revert is mechanical (`/gsd-undo`), but re-verification means re-running the money-path AST diff and the concurrency proofs. The diff-scope gate makes this a non-event |

---

## Pitfall-to-Phase Mapping

Prioritized by likelihood × damage. **Prevention lands in the slice that creates the risk** — nothing is deferred to a cleanup phase.

| # | Pitfall | Prevention slice | Verification |
|---|---|---|---|
| 1 | Vacuous parity tests (44 absence assertions) | **1** (mechanism + registry) · 2 (bulk) · 3 (path-traversal sentinel) | Delete the React component; ≥1 RED per Class-C pin. Registry mirrors `MUTATION_TARGETS`/`test_proof_mutation_targets.py` |
| 2 | `dist/` gitignored → no bundle in production | **1** | `git ls-files` on the output dir non-zero, or the node stage's COPY sits after `Dockerfile:53`; plus a test asserting the referenced asset exists on disk |
| 3 | Denylist serialization leak (8 fields + auto-exposure) | **1** (pattern + `RUN_COLS` drift pin) · 2 (detail DTO) · 3 (`summary` DTO) | `set(body) == EXPECTED`; drift pin fails when a 16th column is added to `app/db/repo/runs.py:38-42` |
| 4 | Route shadowing (`/webhook`, `/health`, `/internal`, trailing slash) | **1** | Endpoint-identity assertion per reserved path; red-proofed by moving the mount above `include_router(webhook.router)` |
| 5 | `fetch` mutations lose 303/query/confirm/notice | **1** (architecture + lint ban) · **2** (the 14 forms + 5 confirms) · 3 (1 form) | `method="post"` count = 14; `onsubmit` count = 5; a test asserting the **final URL** carries `?resolution_superseded=1` and `?notice=` |
| 6 | Test-scope underestimate (6 files, not 2) | **1** (correct the scope in the plan) | Every one of the 6 files named in the slice plan with its owning slice |
| 7 | Design-token guards blind on `.tsx` / dying at import | **1** | `test_design_tokens.py:183` suffix set widened; `:191`/`:337` globs widened; each scanned root asserts a non-zero file count; `:352` module read moved into the test body |
| 8 | `js-` hooks deleted as dead markup | **1** | Live status polling verified end to end; the three hooks still resolve |
| 9 | Cold-start UX + image bloat | **1** (shell strategy, byte budget, `.dockerignore`) · 2, 3 (stay under budget) | Gated gzipped-JS ceiling; no bare spinner; image size delta recorded |
| 10 | Frontend suite not actually selected | **1** | Collection-inventory gate with a committed floor, red-proofed |
| 11 | Scope creep into money-moving code | **1** (gate) · all (enforce) | `git diff --name-only | grep -E '^app/(pipeline\|queue\|db\|llm\|email)/'` empty in the `lint` job; 15 POST handlers AST-diff clean |
| 12 | A11y guarantees silently lost | 1 (`/runs`) · 2 (`/runs/{id}`) · 3 (`/eval`) | New pins for per-page `<title>` and `role="region" tabindex="0"`; existing `aria-current` pin (`test_dashboard.py:573-582`) still green; 375px overflow re-verified |
| 13 | `/ops` script-free pin broken from a shared layout | **1** | `tests/test_ops_route.py:366` green; anything added to `base.html` is conditional and `ops.html` is pinned as the negative case |
| 14 | Progressive enhancement dying by omission | 1, 2, 3 (one recorded decision per page) | Each slice plan states its no-JS verdict; no-JS **mutating** preserved on `/runs/{id}` |
| 15 | Cleanup-as-assertion suppression | 1, 2, 3 | Lint-ban `try`/`catch` around `expect`/`waitFor`; teardown properties assert the observable |
| 16 | Node lockfile discipline | **1** | `npm ci` (not `npm install`), mirroring `ci.yml:45`'s `uv sync --locked`; `package-lock.json` committed; Node version pinned |

**Roadmap sequencing consequences:**
1. **Slice 1 is the guard slice, not just the toolchain slice.** Nine of sixteen preventions must land there because they are all "the first time a template disappears / the first mount / the first DTO." A prevention deferred to Slice 3 is a prevention applied after the damage.
2. **Size Slice 2 as the largest by a wide margin** — 44 of 60 GETs, 14 of 18 forms, all 5 confirm guards, every delivery-review safety pin, and 42 of the 131 markup assertions across three additional test files PROJECT.md does not mention.
3. **Slice 3 is genuinely small** (3 GETs, 1 form) — but it owns the single highest-severity security pin, the `/eval` path-traversal sentinel at `tests/test_dashboard.py:309`, which is exactly the kind of thing a "small easy last slice" waves through.
4. **One architectural decision collapses five pitfalls.** Keeping `base.html` as a server-rendered shell with server-rendered mutation forms and React mounted as islands neutralizes Pitfalls 4 (form semantics), 5 (no fallback route needed), 6 (`aria-current`/`<title>` free), 8 (`js-` hooks may not even move), and 9 (bundle off the critical path). It should be the first decision in the Slice 1 plan, not an implementation detail discovered in Slice 2.

---

## Sources

- **Live source, read and verified 2026-08-17** (primary; every `file:line` above): `app/main.py`, `app/routes/runs.py`, `app/routes/demo.py`, `app/routes/dashboard.py`, `app/routes/operator_feedback.py`, `app/routes/webhook.py`, `app/db/repo/runs.py`, `app/db/repo/demo.py`, `app/templates/*.html`, `app/static/style.css`, `Dockerfile`, `.dockerignore`, `.gitignore`, `pyproject.toml`, `.github/workflows/ci.yml`, `.github/workflows/eval.yml`, `scripts/check_proof_inventory.py`, `scripts/check_operator_resolution_inventory.py`. **HIGH.**
- **Measured test inventory** — AST-ish statement extraction over the 6 affected files (assert-statement joining across continuation lines), route attribution from `client.get` call sites. Reproducible; numbers in the tables above are counts, not estimates. **HIGH.**
- **Project failure history** — `.planning/PROJECT.md:178` (Phase 10 vacuous concurrency proof), `:104-107` (PROOF-05 selection-layer gate), `:219-227` (v4.1 retired: work shipped in an untracked quick task, tracking artifact stale), `:57-60` (AST-diff money-path verification technique), `:274` (no auth on the dashboard). Corroborated by the session memory index (guard-scope blindness; cleanup-as-subject suppression; deferred mutations never run). **HIGH.**
- **`scripts/check_proof_inventory.py:1-27`** — the selection-layer vs execution-layer distinction, quoted directly; the strongest in-repo precedent for both the vacuous-test and unselected-suite pitfalls. **HIGH.**
- **`tests/test_operator_feedback.py:48-72`** — the AST call-site guard shape (`glob("*.py")` + `ast.walk` + `ast.Call`/`ast.Name`), and the honest note that it is Python-only. **HIGH.**
- **Starlette/FastAPI routing semantics** (in-order `Match.FULL` resolution; `redirect_slashes` only fires when the whole table produced no full match; `StaticFiles(html=True)` converts 404 to 200) — standard framework behavior, load-bearing for Pitfall 5. **MEDIUM-HIGH** (framework behavior, not verified by executing a shadowed mount against this app; the route-ordering guard in Pitfall 5 is written to red-proof it directly, which resolves the residual uncertainty in-repo).
- **Render free-tier constraints** (15-min spin-down, ~1-min cold start, ephemeral FS, inbound-HTTP-only wake) — `CLAUDE.md` stack research, re-verified across v1/v4. **HIGH.**

---
*Pitfalls research for: adding React + TypeScript to the Pyrl FastAPI/Jinja2 operator console (milestone v5, Slices 1-3 / Phases 22-24)*
*Researched: 2026-08-17*

---

## Orchestrator addendum (verified against source 2026-08-17)

Findings from a second, independent research run on the same brief that are absent from the
document above. Each was re-verified directly against the cited source by the orchestrator
before being recorded; the numbers here are measured, not estimated.

### A. The frontend CI job must NOT copy `eval.yml`'s trigger shape (owning slice: 1)

`.github/workflows/eval.yml` triggers on `push: branches: ["master"]` + `workflow_dispatch` and
has **no `pull_request` trigger**. `ci.yml` does, and its own header comment states why in as many
words: "`pull_request` is what makes it [a pre-merge gate]."

**Warning sign:** a new `frontend.yml` (or a new job appended to `eval.yml`) whose `on:` block
lists `push` but not `pull_request`.

**Failure mode:** a PR that breaks the TypeScript build or the Vite bundle merges green, and the
break first appears at Render deploy time. This is the same shape as the v4 Phase 21 incident where
CI was green while `/ops` and `/health/queue` 404'd in production because master was 94 commits
unpushed — CI passing on a branch state that is not what deploys.

**Prevention:** the frontend job's `on:` block must include `pull_request`, matching `ci.yml`, not
`eval.yml`. This composes with the "build `dist/` in Docker, don't commit it" decision: if the
bundle is built rather than committed, the build IS the only gate, so it must run pre-merge.

### B. The markup-test blast radius is 14 files, not 2 and not 6 (owning slice: 1)

Measured `grep -rlE 'assert[^#]*\.text' tests/` → **14 files**: `test_dashboard.py`,
`test_needs_operator.py`, `test_phase20_clarification_review.py`, `test_reply_redelivery.py`,
`test_hitl.py`, `test_resume_pipeline.py`, `test_stuck_run_recovery.py`, `test_durable_ingest.py`,
`test_queue_durability.py`, `test_demo_fixtures.py`, `test_demo_landing.py`, `test_ops_route.py`,
`test_health_queue_alarm.py`, `test_health_schema.py`.

Not all 14 target the three converted pages — `test_ops_route.py`, `test_demo_landing.py`, and the
two `test_health_*` files assert against surfaces that stay Jinja. But the count establishes that
both the milestone's 2-file scope statement and this document's 6-file correction are floors, not
the answer.

**Prevention:** Slice 1 owes a **route-attribution pass** — for each of the 14 files, determine
which route(s) its `.text` assertions actually exercise, and record the per-file split of presence
(`assert X in ...text`) versus absence (`assert X not in ...text`) assertions. Absence assertions
are the vacuous-parity surface described above; they must be enumerated before any file is touched,
because after conversion they cannot be distinguished from assertions that genuinely still hold.
Do not begin the migration against an unmeasured inventory.

**Measured anchors for that pass:** `test_dashboard.py` = 2,296 LOC / 295 asserts / 85 `*.text`
refs, split 42 presence vs **31 absence**. `test_needs_operator.py` = 2,223 LOC / 167 asserts /
8 real markup refs (12 `.text` minus 4 `caplog.text`), split 5 presence vs **7 absence**.
`test_phase20_clarification_review.py` = 30 `.text` asserts across 11 `client.get` calls.
`test_reply_redelivery.py` = 4 `.text` asserts across 4 `client.get` calls.
