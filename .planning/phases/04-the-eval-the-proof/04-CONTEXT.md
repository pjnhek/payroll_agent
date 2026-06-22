# Phase 4: The Eval (the proof) - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Phase 4 builds **a reproducible eval** that imports and scores the **exact same production judgment functions** over ~15 committed **hand-curated** email fixtures, producing a **legible per-category chart + a false-process headline number** that proves the gated decisioning works. It is the **credibility lever for the recruiter audience** — but it is **priority #3** behind "visibly works end-to-end" (#1) and "clean 60–90s demo" (#2), so it must NOT be gold-plated.

**The 5 Phase 4 requirements (authoritative, per ROADMAP.md / REQUIREMENTS.md):** EVAL-01, EVAL-02, EVAL-03, EVAL-04, EVAL-05.

**Locked by requirements (NOT re-opened in discussion):**
- The eval imports and runs the **SAME** production pipeline functions and scores the **code-owned `final_action`**, not a model action (EVAL-03).
- **~15–25 hand-curated** email+label fixtures committed to the repo; a **throwaway bootstrap drafting helper** named honestly; committed fixtures are the source of truth — no train/test leakage (EVAL-01, EVAL-02).
- **Three core metrics** (extraction field accuracy, name-reconciliation accuracy, decision accuracy) broken out per category + a **secondary, drop-if-tight LLM-as-judge** email-quality score with a one-line rubric + 2–3 anchors (EVAL-04).
- Results write to `eval_results` and render as **one clean per-category chart**; **local eval is authoritative; CI scores cached fixtures with NO live LLM calls** (EVAL-05).

**Nature of the work:** This is **new tooling that rides finished code** — the four pure judgment stages (extract → reconcile → validate → decide) and `calculate` already work (Phase 2/2.1/3, ~195 mocked tests green; calc golden-tested to the penny in Phase 3). Phase 4 adds: a fixture corpus with labels, a `run_eval.py` scorer, a committed chart artifact, and the project's **FIRST `.github/workflows` file**. No change to production pipeline code is expected (additive eval surface only).

**The thesis being proved:** every money-moving judgment call is **deterministic code that never guesses** — names resolve as exact/stored-alias/none in pure code, collisions always clarify, `decide.py` computes `final_action` with no LLM call and no confidence number. The eval's job is to make that **visible and auditable**, with the asymmetry made explicit: a **false-process pays the wrong person** (the headline risk); a false-clarify is merely annoying.

**Phase-scope tiering (the load-bearing scope decision — see D-EXIT):**
- **HARD exit bar:** the 3 core metrics *with the review fixes below*, the confusion matrix with false-process rate as headline, ONE decide→calculate wiring smoke test, committed SVG chart + `summary.json`, and the `--check` CI regression gate, over **~15 denser fixtures**.
- **"If time" — cut without guilt:** the LLM-as-judge metric (drop-FIRST), the live `eval_results` DB write (stub only), and the (b) end-to-end-real-extraction scoring line (only where extraction genuinely diverges).

</domain>

<decisions>
## Implementation Decisions

> A separate-Claude adversarial review was run against the first-pass decisions and **its accepted findings are folded in below** (marked `[review]`). The review's three "wrong as written" points (extraction recall→precision, single→dual category grouping, decision final_action→two-level) and its two highest-value adds (confusion matrix + false-process headline; decide→calculate wiring test) are now **locked decisions**, not options.

### Area 1 — Fixture labels & storage

- **D-01 (storage):** **ONE self-contained JSON file per fixture**, in a **NEW `eval/` fixture set** (path is Claude's discretion — e.g. `eval/fixtures/`). Each file holds the input email **and** an `expected` block, a fixture-level `category`, and its roster binding. The existing **4 `fixtures/*.json` demo files stay input-only and untouched** (they serve the on-camera DASH-05 demo path, a different purpose).

- **D-02 (label granularity):** the `expected` block carries **full per-stage expected outputs**:
  - expected **extracted** per-employee fields — name-as-written + the five hours fields (`hours_regular/overtime/vacation/sick/holiday`) + any `contribution_401k_override`;
  - expected **per-name resolution** — `source` (exact/alias/none) + `resolved` + the intended `matched_employee` (so a wrong-but-real match is detectable);
  - expected **decision** — `final_action` + `gate_reasons` + `unresolved_names` + `missing_fields`.
  - **`net_pay` is NOT labeled** — Phase 3's golden penny-tests (CALC-06) already own calc correctness; a second hand-label oracle invites drift. **EXCEPTION:** the single e2e wiring smoke fixture (D-09) asserts `calculate()` output equals the **existing Phase-3 golden**, not a new hand-label.

- **D-03 (category grouping) `[review pt 2 — locked, was a single field]`:** there are **TWO independent groupings**, and the `expected` schema must support both:
  1. a **fixture-level `category`** enum field (drives the **decision/field** charts; one primary category per fixture; fails loudly on a bad enum value);
  2. **per-NAME** category buckets derived from the per-name expected resolutions (drives the **reconciliation** chart). A **multi-employee fixture carries several name-categories at once** (e.g. one email with an exact name + a typo + a collision), so reconciliation accuracy is bucketed per name, not per fixture. The taxonomy enum is the locked one: `exact / stored-alias / first-time-alias / typo / collision / unknown` + field cases `missing-hours / vague-hours / buried-reply`.

- **D-04 (roster binding):** the fixture's **`from_addr` matches a seeded business `contact_email`** (the production INGEST-03 sender-matching path); the eval loads that business's roster from the **SAME importable seed module** the pipeline uses (`app/db/seed.py` values — no live DB needed). **No roster is duplicated into fixtures.** The collision pair (David/Daniel Reyes share alias `"D. Reyes"`) and the SS-straddle employee (Thomas Bergmann, `ytd_ss_wages=183,900`) are already seeded.

### Area 2 — Extraction scoring + the cached-LLM mechanism

- **D-05 (cached extraction — the hermetic-CI enabler):** extraction is the **ONLY** judgment stage that calls the LLM. A **`record` step runs LIVE extraction ONCE per fixture** (manual/local, gated by the project's existing `allow_live_llm` two-factor flag) and **commits the raw `Extracted` JSON beside the fixture**. The eval (local default **and** CI) **replays from the committed cache** — no live call on push. The **pinned model IDs** that produced each cache are recorded in `summary.json` (EVAL-05). Re-recording is a deliberate, explicit step (a `--record` / `workflow_dispatch` path), never the default.

- **D-06 (extraction field accuracy) `[review pt 1 — locked, was recall-only]`:** score **precision + recall (report F1)** on the **employee set**, NOT recall-only:
  - a **dropped** employee = a **recall** miss (their expected fields go unmatched);
  - an **extra / hallucinated** employee = a **precision** miss (a false positive);
  - within **matched** employees, per-field correctness still applies — hours as **`Decimal` exact equality** (discrete, no tolerance); name-as-written after the **same casefold + whitespace-normalize the resolver uses**; employees aligned by normalized `submitted_name`.
  - **WHY THIS IS LOAD-BEARING:** `app/pipeline/validate.py` confirms the deterministic gate **cannot catch invention** — `validate` only flags missing hours when **all five** hours fields are `None`. If the model **hallucinates a "40"** for an employee the email never mentioned (or invents hours on a missing-hours fixture), `validate` sees `any_hours=True`, passes clean, and `decide` would **`process` a fabricated line**. The **extraction metric is the ONLY guard against invention** — the most dangerous payroll extraction failure — so a recall-only metric (blind to extras) would miss exactly the failure mode that matters most.

- **D-07 (feed source for the deterministic-stage metrics) `[review — (b) made conditional]`:** name-reconciliation + decision accuracy are scored on **path (a) ALWAYS**; **path (b) is conditional and "if time"**:
  - **(a) isolated** — feed the **labeled expected extraction** into reconcile/validate/decide → measures the **deterministic code in isolation** (the thesis, unconfounded by extraction noise). **The chart leads with (a).**
  - **(b) end-to-end** — feed the **cached real extraction** → measures the real `extract→decide` handoff a client actually gets. **Compute (b) only for fixtures where extraction genuinely diverges** (vague-hours, buried-reply). If (a) == (b) everywhere (clean fixtures), **drop (b) as redundant** (it would be a chart line implying a distinction that isn't there). (b) is an "if time" item; (a) is the exit bar.

### Area 3 — The chart deliverable + decision/aggregation shape

- **D-08 (artifact):** `run_eval.py` emits a versioned, committed **`eval/summary.json`** (per-category metrics + per-fixture details + pinned model IDs + a `suite_run_id`) **and** a committed standalone **chart image**. The JSON is the machine-readable source that **Phase 5's dashboard reads** and the optional DB write derives from; the image is **recruiter-visible proof in the README today**, with no dashboard dependency. **Commit the chart as `[review]` SVG, not PNG** — SVG is text (diffable, no binary git churn on re-record, scales in the README).

- **D-09 (decide→calculate wiring smoke test) `[review pt B — locked, highest-value]`:** add **ONE** end-to-end smoke fixture — a clean **process** case that runs all the way through `calculate` and **asserts the result equals the existing Phase-3 golden** for that employee/hours. This closes the only gap between the eval (which otherwise stops at `decide`) and the **"computes payroll" headline**, with **no second net_pay oracle** (reuses the golden already trusted). Not a per-category metric — a single wiring assertion.

- **D-10 (decision accuracy = two levels) `[review pt 3 / #5 — locked, was final_action-only]`:** report decision accuracy at **two levels**, as two metrics (not one strict pass/fail):
  - **headline:** `final_action` match (process vs request_clarification);
  - **rigor layer:** **gate-structure set-match** — `gate_reasons` / `unresolved_names` / `missing_fields` compared as **sets**. WHY: `final_action`-only lets a fixture "pass" by **clarifying for the wrong reason** (e.g. flags missing-hours when it should flag the D. Reyes collision) — a gate that works by accident. The set-match layer is what **proves** the thesis rather than asserting it.

- **D-11 (confusion matrix + false-process headline) `[review pt A — locked, single best credibility add]`:** the suite is **clarify-heavy** (4 of 6 resolution categories + all 3 field cases trigger clarification), so a scalar "decision accuracy %" is **gameable by a degenerate "always clarify"**. Therefore:
  1. the suite **MUST include enough clean exact/stored-alias PROCESS fixtures** that an "always clarify" baseline **fails visibly**;
  2. report a **category × outcome confusion matrix**, not a scalar, because the two error directions are **asymmetric in cost** — **false-process (pays the wrong person) is the headline number**; false-clarify is annoying. Surfacing the **false-process rate separately** is the strongest single credibility move in the phase.

- **D-12 (aggregation shape) `[review pt 4 — locked]`:** the three metrics have **different units / denominators** — extraction is per-field (large n), reconciliation is per-name (medium n, accumulates across multi-employee fixtures), decision is per-fixture (genuinely small n). **Do NOT force one denominator.** **Report decision results as fractions `k/n`, not percentages** ("collision: 3/3 clarified" is honest at n=3; "100%" is not); **annotate every bar with `k/n`**. Prefer the **category × outcome grid** (the D-11 matrix) over percentage bars for the decision metric at tiny n.

- **D-13 (taxonomy honesty caveat) `[review — locked, goes in doc + chart label]`:** the resolver emits only **exact / alias / none** — `first-time-alias`, `typo`, `collision`, and `unknown` **all collapse to `none → clarify`**. So a per-category reconciliation bar for "typo" does **not** measure "accuracy of *detecting typos*" (the resolver has no typo concept) — it measures "on inputs I labeled typos, the resolver correctly returned `none`." Chart bars MUST be labeled **"accuracy on fixtures of category X"**, never implying a classification capability the code lacks. One-liner for the README/chart: *"the resolver returns `none` for all four unresolved categories; these are coverage buckets, not classes the system predicts."*

- **D-14 (DB write) `[review — demoted to "if time"]`:** `summary.json` (+ SVG) is **authoritative and always produced** (CI stays hermetic: no DB, no live LLM). Writing rows to the tall `eval_results` table (`suite_run_id, fixture_id, metric_name, value, details JSONB`) is an **OPTIONAL "if time" step** (stub acceptable) — runs only when a `DATABASE_URL` is present, **derived from the same `summary.json`** so the two cannot diverge. Satisfies EVAL-05's DB write where a DB exists while keeping "local eval authoritative."

### Area 4 — LLM-as-judge email quality (EVAL-04, secondary)

- **D-15 (scope — "if time", drop-FIRST) `[review — extended the pre-cut]`:** the judge is **local-only** (gated by `allow_live_llm`), **never runs in CI**, and is **the first thing cut** under time pressure. It is **NOT broken out per category** (n≈1 per category is decoration, not a metric). **For recruiters, showing 3 actual clarification drafts in a README appendix beats any quality score** — the drafts are the proof; lead with those.

- **D-16 (judge input + correctness floor) `[review — floor added]`:** if built, the judge **scores COMMITTED RECORDED drafts** — a `record` step generates the clarification draft once per clarify-category fixture (live, gated) and commits it (same record-once/replay discipline as D-05 → reproducible/auditable). Score against a **one-line rubric with 2–3 calibration anchors** (e.g. 1 = generic / names no specific employee; 3 = names the suggested employee + asks the precise question; 5 = specific + warm + actionable). **ADD A CORRECTNESS FLOOR:** `app/pipeline/suggest.py` already drops any suggested name that isn't a real roster `full_name`, so off-roster invention can't happen — but the draft **can still name the WRONG real employee** (e.g. "David Reyes" when the fixture's intended answer is "Daniel Reyes"). A warm, specific email confidently naming the **wrong** employee must be **capped low regardless of polish** — that "confident-LLM-wrongness" is exactly what the architecture exists to prevent, so the judge must not reward it.

### Area 5 — CI workflow (project's first `.github/workflows`)

- **D-17 (CI = regression gate via `--check`) `[review — locked]`:** the eval runs in GitHub Actions **on push** against the **committed cached extraction** (no live LLM, no DB — hermetic). The gate runs the **SAME `run_eval.py` entrypoint in a `--check` mode** (NOT a parallel scoring reimplementation, or CI and the real eval silently diverge), and compares **parsed + rounded values** against the committed `summary.json` (**not file bytes** — JSON key order and float formatting would cause false failures). **Name the gate for what it is:** a *regression gate on deterministic scoring against the frozen cache*. **Green CI ≠ "extraction is good"** — CI never calls the LLM; it only proves the deterministic scoring didn't regress. A **separate `workflow_dispatch`** job runs the live eval (re-record extraction + judge).

### Area 6 — Corpus & bootstrap helper (assumptions surfaced by review, now decided)

- **D-18 (corpus target) `[review — locked the floor]`:** target **~15 fixtures (the floor), several MULTI-EMPLOYEE**, NOT 25 single-purpose. One 4-employee email can cover `exact + stored-alias + typo + collision` for the reconciliation metric in a **single labeled file** → ≥3 name-results per category in aggregate while keeping per-fixture labeling effort sane. **25 fully per-stage-labeled single-purpose fixtures is the unrealistic option**; ~15 richer/denser fixtures over a focused day or two is realistic. Must still include enough clean **process** fixtures for D-11.

- **D-19 (bootstrap helper) `[review — anti-leakage rule added]`:** build the **trivial throwaway** (EVAL-01 locks it) — ~20-line `draft_candidate_emails.py`, docstring says throwaway, prompts a model to **draft** candidate messy emails that the builder then **hand-edits and hand-labels**; committed fixtures are the source of truth. Its value is **messy-phrasing variety** (signatures, "oh and also," reply cruft), **not labor** (you could hand-write 15 faster than you'll debug a generator). **ANTI-LEAKAGE RULE:** if the drafter and the extractor are the **same model** (DeepSeek), drafted phrasing may be **unnaturally easy** for it to extract — quiet leakage even without label leakage. **Draft with a DIFFERENT model** (the Kimi `draft` tier) **or hand-edit hard.**

### D-EXIT — Phase-scope tiering (the most important framing) `[review — locked]`

Phase 4 is **priority #3**; the plan must not be scoped like priority #1. The exit bar and the "if time" set:

- **HARD exit bar:** D-06 (precision/recall extraction) + D-10 (two-level decision) + D-03 (per-NAME reconciliation bucketing) + D-11 (confusion matrix, false-process headline) + D-09 (one decide→calculate wiring smoke test) + D-08 (committed **SVG** chart + `summary.json`) + D-17 (`--check` CI regression gate), over **~15 denser fixtures** (D-18).
- **"If time" — cut without guilt:** D-15 LLM judge (drop-FIRST) · D-14 `eval_results` DB write (stub only) · D-07 path (b) end-to-end scoring (only where extraction diverges).

### Claude's Discretion

- **Exact paths / module names:** the `eval/` directory layout, the fixture filename scheme, the `run_eval.py` location (e.g. top-level vs `eval/run_eval.py`), the cached-extraction filename convention, the bootstrap helper's exact location. The decisions fix the *shape* (one self-contained labeled file per fixture; cached extraction committed beside it; SVG + summary.json artifacts); the layout is the planner's call.
- **The `expected` block's exact JSON schema** — D-02/D-03 fix *what* it must carry (per-stage outputs, both category groupings); the field names/nesting are the planner's call (keep it diffable and hand-editable).
- **Confusion-matrix rendering details** — exact cells, colors, whether it's one matrix or per-grouping, as long as **false-process rate is the headline** (D-11) and small-n is shown as `k/n` (D-12).
- **The precise F1 formulation** (micro vs macro across employees/fixtures) — D-06 fixes precision+recall on the employee set with per-field correctness inside matches; the aggregation choice is the planner's, provided extras count as false positives.
- **Whether the wiring smoke test (D-09) lives in `run_eval.py` or as a pytest** — D-09 fixes *what* it asserts (== Phase-3 golden); placement is the planner's.
- **The exact rubric anchor wording** (D-16) — the *structure* (one line, 2–3 anchors, a correctness floor for wrong-real-employee) is fixed; the prose is the planner/researcher's.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & roadmap (the locked scope)
- `.planning/REQUIREMENTS.md` §Eval (the proof) — **EVAL-01 through EVAL-05** (full text: the bootstrap-helper-not-generator framing, the ~15–25 hand-curated fixtures, the SAME-production-functions scoring of code-owned `final_action`, the 3 core metrics + the rubric'd drop-if-tight judge, the eval_results write + chart + hermetic CI). Also §Dashboard **DASH-04** (Phase 5 renders the eval view + per-category breakdown + per-fixture drill-in — Phase 4's `summary.json` is what it consumes).
- `.planning/ROADMAP.md` §Phase 4 — the goal + the 4 success criteria (same functions, the taxonomy + field cases, the 3 core metrics per category + secondary judge, the eval_results write + one chart + local-authoritative / CI-no-live-calls).
- `.planning/PROJECT.md` — Key Decisions: *"Eval = all 4 metrics over ~15–25 fixtures, one summary chart"* and *"v1 eval uses hand-curated fixtures + a throwaway bootstrap drafting helper (full synthetic generator → v2)"*. Also the DRY-seam decision (the eval imports and scores the SAME pure judgment functions).
- `./CLAUDE.md` §7 (dashboard/eval framing) + §2 (DeepSeek JSON mode, temp 0 for extraction; the two-tier model routing) + the **uv** tooling rule (`uv run pytest -q`, `uv add --dev` for eval-only deps — never pip).

### Prior-phase context that constrains Phase 4
- `.planning/phases/02.1-deterministic-decisioning/02.1-CONTEXT.md` §`<eval_changes>` — **the locked taxonomy** (`exact / stored-alias / first-time-alias / typo / collision / unknown`); name-reconciliation + decision now test the **deterministic resolver** (not LLM judgment); extraction stays the LLM metric; judge unchanged/lowest-priority. §`<decisions>` D-21-01..09 — the deterministic decision model the eval scores.
- `.planning/phases/03-harden-the-calc/03-CONTEXT.md` — the golden-test oracle (CALC-06) the **D-09 wiring smoke test reuses**; `Decimal` + ROUND_HALF_UP; the pure-function `calculate` the eval rides.

### Pipeline functions the eval imports (verified signatures — file:line)
- `app/pipeline/extract.py:32` — `extract(email, roster, *, run_id, llm=llm_client) -> Extracted` (the ONLY LLM judgment stage; replayed from cache in the eval).
- `app/pipeline/reconcile_names.py:95` — `reconcile_names(submitted_names, roster) -> list[NameMatchResult]` (PURE, no `llm`).
- `app/pipeline/validate.py:50` — `validate(extracted, roster, matches) -> list[ValidationIssue]` (PURE; **only flags missing hours when all five are None** — the basis of the D-06 invention argument).
- `app/pipeline/decide.py:86` — `decide(extracted, matches, issues) -> Decision` (PURE, no `llm`; computes `final_action`).
- `app/pipeline/calculate.py:180` — `calculate(resolved_hours, employee, contribution_401k_override=None) -> PaystubLineItem` (PURE; golden-tested in Phase 3 — D-09 reuses that golden).
- `app/pipeline/suggest.py:60` — `suggest_employees(unresolved_names, roster, *, llm=llm_client) -> dict[str, str]` (LLM, copy-only; **drops off-roster names** but CAN name a wrong real employee — the D-16 floor).
- `app/pipeline/compose_email.py:88` — `compose_clarification(decision, *, suggestions=None, llm=llm_client) -> str` (LLM; the draft the judge scores).
- `app/pipeline/orchestrator.py:168` — `_run_stages(...)` — the shared spine showing the exact call order extract→reconcile→validate→decide→branch (reference for how the eval composes stages).

### Contracts the labels compare against (file:line)
- `app/models/contracts.py:103` `Extracted` (+ `ExtractedEmployee`: submitted_name + 5 hours fields + `contribution_401k_override`), `:119` `Decision` (`final_action`, `gate_reasons`, `unresolved_names`, `missing_fields`, `resolutions`), `:149` `PaystubLineItem`, `:35` `InboundEmail`.
- `app/models/roster.py:149` `NameMatchResult` (`submitted_name`, `matched_employee_id`, `source`, `resolved`, `reason`), `:205` `ValidationIssue` (`field`, `issue_type`, `message`), `:26` `Employee` (full calc-input set + `known_aliases`), `:115` `Roster`.

### Data & schema the eval touches
- `app/db/seed.py:50` — 3 businesses / 7 employees; the **collision pair** David Reyes (e0000003) + Daniel Reyes (e0000007) sharing alias `"D. Reyes"`; the **SS-straddle** Thomas Bergmann (`ytd_ss_wages=183,900`); the importable roster the fixtures bind to via `from_addr` (D-04).
- `app/db/schema.sql:144` — `eval_results` (tall: `id, suite_run_id, fixture_id, metric_name, value NUMERIC(8,4), details JSONB, created_at`) — Phase 4 is the first consumer (D-14, "if time").
- `app/config.py` — `allow_live_llm: bool = False` (the two-factor gate for the `record` step and the judge) + the two model tiers (`extraction` DeepSeek / `draft` Kimi — relevant to the D-19 anti-leakage rule).
- `app/llm/client.py` — `call_structured` (JSON mode, temp 0, 1 retry) + `call_text`; how the eval injects a mock/cached `llm`.

### Existing fixtures & tests to mirror / extend
- `fixtures/*.json` — the 4 input-only demo fixtures (stay untouched; the eval set is new — D-01).
- `tests/test_reconcile.py`, `tests/test_gate.py`, `tests/test_demo_fixtures.py` — existing taxonomy + fixture-replay coverage the eval's scoring should be consistent with (not duplicate).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **All seven pipeline stages are eval-ready by design** — the four judgment stages + `calculate` are pure importable functions (data in, data out, no DB); `extract`/`suggest`/`compose_clarification` take an injectable `llm=` kwarg so the eval controls live-vs-mock per stage. This is the DRY seam the whole eval credibility rests on — **the eval imports the SAME functions production runs**.
- **`app/db/seed.py` is importable values** — the eval binds fixtures to rosters from it without a live DB. The collision pair and SS-straddle employees are already seeded for the relevant taxonomy categories.
- **Phase 3 golden tests** are the trusted calc oracle the D-09 wiring smoke test reuses — no new net_pay oracle is built.
- **The existing `allow_live_llm` two-factor gate** is the exact pattern the `record` step (D-05) and the judge (D-15) reuse — no new gating mechanism.

### Established Patterns
- **Pure-function judgment stages (D-14 / DRY seam)** — the eval scores the SAME functions; this is non-negotiable and already true.
- **Record-once / replay-from-cache** — the project already env-gates live network behind `allow_live_llm`; D-05 (extraction cache) and D-16 (draft cache) extend that discipline to make the eval reproducible/hermetic.
- **`Decimal` exact equality** for money/hours (no float tolerance) — D-06 scores hours as Decimal equality; D-09 compares against Phase-3 Decimal goldens.
- **`uv run` for everything; `uv add --dev`** for eval-only deps (matplotlib goes here — NOT in the runtime image).
- **No `.github/workflows` exists yet** — D-17 is the project's first CI workflow (STATE.md note: "CI/CD deferred — eval CI = Phase 4").

### Integration Points
- **`run_eval.py`** (new) imports the pipeline stages, replays cached extraction, scores against committed labels, writes `summary.json` + the SVG chart, and exposes a `--check` mode (D-17) and a `--record` path (D-05).
- **`eval_results` table** (D-14, "if time") — the optional DB write derives from `summary.json`; the **Phase 5 dashboard (DASH-04)** is the real consumer of both the JSON and any DB rows.
- **`.github/workflows/eval.yml`** (new) — push job runs `run_eval.py --check` (hermetic); a `workflow_dispatch` job runs the live re-record/judge.
- **matplotlib** added via `uv add --dev` — never imported by `app/` runtime code, so the Render image and cold-start are unaffected.

</code_context>

<specifics>
## Specific Ideas

- **The false-process rate is the headline number, not "decision accuracy %."** A payroll eval whose headline is a single accuracy % over a clarify-heavy suite is gameable by "always clarify"; surfacing false-process (pays the wrong person) separately is the one number that says "I built the *right* eval, not just an eval." (D-11.)
- **Score the deterministic stages in isolation first (a), end-to-end only where it differs (b).** The thesis is "the code never guesses" — measure that unconfounded by extraction noise; add the real-path line only where extraction is genuinely hard so it carries information. (D-07.)
- **The extraction metric is the only thing standing between a hallucinating model and a fabricated paystub** — `validate.py` proves the deterministic gate can't see invention, so the extraction metric must be precision-aware (extras = false positives), not recall-only. (D-06.)
- **Reuse the Phase-3 golden for the one e2e wiring test** — don't build a second net_pay oracle; the gap to close is the decide→calculate *join*, and the golden you already trust closes it. (D-09.)
- **Show 3 real clarification drafts in the README appendix** — for recruiters, the drafts themselves outprove any 1–5 quality score; the judge is decoration at n≈1 per category. (D-15.)
- **Draft fixtures with a different model than the extractor** to avoid quiet phrasing-leakage (DeepSeek extracting DeepSeek-drafted prose is unnaturally easy). (D-19.)
- **Commit the chart as SVG** (text, diffable, scales) — a PNG churns git on every re-record and can't be diffed. (D-08.)
- **Label reconciliation bars as "accuracy on fixtures of category X"** — the resolver predicts none/exact/alias, not the six categories; the buckets are coverage, not classes. (D-13.)

</specifics>

<deferred>
## Deferred Ideas

- **Full decoupled-persona synthetic fixture generator (scales to thousands)** → **v2 (EVAL-V2-02)**. Phase 4 uses the throwaway bootstrap helper + ~15 hand-curated fixtures only.
- **Larger fixture corpus + multi-judge ensemble for email quality** → **v2 (EVAL-V2-01)**. Phase 4's single judge is local-only, drop-first.
- **The Phase 5 dashboard eval view (DASH-04)** — Phase 4 produces `summary.json` + the SVG chart + (optionally) `eval_results` rows; **rendering them in the dashboard with per-fixture drill-in is Phase 5**. Phase 4 must produce a self-contained proof that does NOT depend on the dashboard.
- **Live `eval_results` DB write beyond a stub** → **"if time" within Phase 4** (D-14); if cut, it lands naturally with the Phase 5 dashboard work that consumes it.
- **The LLM-as-judge metric** → **"if time" within Phase 4, drop-FIRST** (D-15). If cut, the 3 deterministic core metrics + confusion matrix + chart still fully satisfy the phase's proof value.
- **The (b) end-to-end-real-extraction scoring line** → **"if time" / conditional** (D-07) — only where extraction genuinely diverges.
- **Over-40-no-OT validation rule (Phase 3 D-05)** → still its own focused insertion **before Phase 5** (tracked in `.planning/backlog.md`); **NOT a Phase 4 deliverable**, but if any eval fixture exercises a weekly >40-no-OT case, note that the rule isn't implemented yet so the expected label reflects current behavior, not the future rule.

### Reviewed Todos (not folded)
None — STATE.md "Pending Todos" is empty; the `todo.match-phase` query returned zero matches for Phase 4.

</deferred>

---

*Phase: 4-The Eval (the proof)*
*Context gathered: 2026-06-22*
