# Phase 4: The Eval (the proof) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-22
**Phase:** 4-The Eval (the proof)
**Areas discussed:** Label format & location, Extraction scoring + cached LLM, The chart deliverable, LLM-judge scope, Phase-scope tiering, Dual-path scoring — plus a full external-Claude adversarial review whose accepted findings reshaped several decisions.

---

## Area selection (multiSelect)

User chose to discuss **all four** offered gray areas: Label format & location, Extraction scoring + cached LLM, The chart deliverable, LLM-judge scope. (The requirements-locked items — same functions, 15–25 hand-curated fixtures, the 4 metrics + taxonomy, eval_results write + chart, hermetic CI — were explicitly not re-asked.)

---

## Label format & location

### Storage
| Option | Description | Selected |
|--------|-------------|----------|
| One self-contained file per fixture | Each fixture = one JSON with input + `expected` block + category; new `eval/` set; demo fixtures untouched | ✓ |
| Input files + one labels manifest | Separate input emails + a single labels.json mapping fixture_id → expected | |
| Reuse the 4 demo fixtures + extend in place | Add `expected` to existing fixtures/*.json and grow to 15–25 | |

**User's choice:** One self-contained file per fixture.

### Label granularity
| Option | Description | Selected |
|--------|-------------|----------|
| Full per-stage expected outputs | Expected extraction fields + per-name resolution + decision; net_pay NOT labeled (Phase 3 owns it) | ✓ |
| Decision + reconciliation only | Only final_action + per-name source/resolved | |
| Add expected net_pay too | Full per-stage + expected net_pay (duplicates Phase 3 golden) | |

**User's choice:** Full per-stage expected outputs.

### Category tagging
| Option | Description | Selected |
|--------|-------------|----------|
| Explicit `category` field per fixture | Fixed enum, drives chart x-axis, fails loud on bad value | ✓ |
| Infer category from expected outcome | Derive at scoring time (can't distinguish typo vs unknown) | |
| Folder-per-category | eval/exact/, eval/typo/ … (moving a file recategorizes it) | |

**User's choice:** Explicit `category` field per fixture. *(Later revised by review → TWO groupings: fixture-level category + per-name buckets. See review section.)*

### Roster binding
| Option | Description | Selected |
|--------|-------------|----------|
| from_addr → business, reuse seed roster | Production INGEST-03 path; roster from importable seed; no duplication | ✓ |
| Inline roster snapshot per fixture | Each fixture embeds its Roster/Employee list (divergence hazard) | |

**User's choice:** from_addr → seeded business → seed roster.

---

## Extraction scoring + cached LLM

### Cached outputs
| Option | Description | Selected |
|--------|-------------|----------|
| Committed cached extraction per fixture | record live once (gated), commit raw Extracted, replay in eval+CI; pin model IDs | ✓ |
| Mock LLM returns the expected extraction | Inject mock returning the labels (makes extraction always 100% — meaningless) | |
| Live extraction every run | Real LLM every run incl CI (non-deterministic, costs, violates EVAL-05) | |

**User's choice:** Committed cached extraction per fixture.

### Extraction field accuracy
| Option | Description | Selected |
|--------|-------------|----------|
| Per-field accuracy across employees | correct-fields / total-expected; hours Decimal-exact; name normalized | ✓ |
| Per-employee exact-match (all-or-nothing) | Employee = 1.0 only if every field matches | |
| Per-email exact-match | Whole fixture = 1.0 only if every employee perfect | |

**User's choice:** Per-field accuracy across employees. *(Later revised by review → precision/recall/F1 so hallucinated employees count as false positives. See review section.)*

### Feed source for deterministic-stage metrics
| Option | Description | Selected |
|--------|-------------|----------|
| Score both — isolated + end-to-end | (a) labeled extraction → deterministic code; (b) cached real extraction → real path | ✓ |
| Cached real extraction only (end-to-end) | One realistic number; confounds decision metric with extraction noise | |
| Labeled expected extraction only (isolated) | Cleanest thesis measure; never exercises real extract→decide handoff | |

**User's choice:** Score both. *(Later revised by review → (a) always, (b) conditional/"if time" only where extraction diverges. See review + dual-path section.)*

---

## The chart deliverable

### Artifact
| Option | Description | Selected |
|--------|-------------|----------|
| Committed JSON summary + emitted chart image | summary.json (machine-readable, dashboard+DB source) + committed image (README proof) | ✓ |
| DB write + dashboard renders (defer the picture) | Write eval_results; chart only once Phase 5 dashboard exists | |
| JSON summary only (no image in P4) | Emit summary.json; defer all rendering to Phase 5 | |

**User's choice:** Committed JSON summary + emitted chart image. *(Image format later revised by review → SVG not PNG.)*

### Chart lib
| Option | Description | Selected |
|--------|-------------|----------|
| matplotlib (dev-only dependency) | uv add --dev; never in runtime image; battle-tested bar chart | ✓ |
| Hand-rolled SVG (no dependency) | Bespoke chart code; easy to get subtly wrong | |
| Defer lib choice to the planner | Lock "committed image", let planner pick tool | |

**User's choice:** matplotlib as a dev/eval-only dependency.

### DB write
| Option | Description | Selected |
|--------|-------------|----------|
| JSON authoritative; DB write optional | summary.json always produced (CI hermetic); eval_results write only when DATABASE_URL present, derived from summary | ✓ |
| Always write to eval_results | Forces every CI run to have a live DB (contradicts hermetic CI) | |

**User's choice:** JSON authoritative; DB write optional. *(Later demoted by review → DB write is "if time", stub only.)*

---

## LLM-judge scope

### Scope
| Option | Description | Selected |
|--------|-------------|----------|
| In scope, local-only, drop-last | Built behind allow_live_llm; never in CI; secondary section in summary | ✓ |
| Explicitly defer to a follow-up | Ship only 3 core metrics; note judge as deferred | |
| Full judge, same priority as core | Judge as first-class metric (over-invests in lowest-value metric) | |

**User's choice:** In scope, local-only, drop-last. *(Later by review → drop-FIRST; not per-category; show 3 drafts in README; add a wrong-real-employee correctness floor.)*

### Judge input
| Option | Description | Selected |
|--------|-------------|----------|
| Score committed recorded drafts | record draft once (gated), commit, judge scores it against a rubric — reproducible | ✓ |
| Draft + judge live each run | Doubly non-reproducible; can't replay/inspect | |
| Defer rubric specifics to the planner | Lock "rubric scores committed drafts", planner words anchors | |

**User's choice:** Score committed recorded drafts.

---

## External adversarial review (separate Claude) — accepted findings

User pasted the four-area decisions into a separate Claude for an adversarial review and brought the feedback back. **All substantive findings were accepted** (a couple sharpened against the actual source, which the orchestrator read to verify):

- **Extraction → precision/recall/F1, not recall-only** (`[review pt 1]`). Verified against `app/pipeline/validate.py`: the deterministic gate only flags missing hours when ALL five are None, so a hallucinated "40" passes clean and would `process` a fabricated line — the extraction metric is the ONLY guard against invention. **Accepted, D-06.**
- **Two category groupings, not one** (`[review pt 2]`): fixture-level `category` (decision/field charts) + per-NAME buckets (reconciliation chart), because multi-employee fixtures carry several name-categories. **Accepted, D-03.**
- **Decision accuracy = two levels** (`[review pt 3]`): final_action headline + gate-structure set-match rigor layer (catches "clarified for the wrong reason"). **Accepted, D-10.**
- **Confusion matrix + false-process headline** (`[review pt A]`): the clarify-heavy suite is gameable by "always clarify"; report a category × outcome matrix with false-process (pays the wrong person) as the headline; include enough clean PROCESS fixtures that "always clarify" fails visibly. **Accepted, D-11** (called out as the single best credibility add).
- **One decide→calculate wiring smoke test** (`[review pt B]`): assert calculate() == the existing Phase-3 golden; closes the only gap to the "computes payroll" headline with no second oracle. **Accepted, D-09.**
- **Fractions k/n not percentages at small n; grid over bars for decision** (`[review pt 4]`). **Accepted, D-12.**
- **Taxonomy honesty caveat** — the resolver emits none/exact/alias; the six categories are coverage buckets, not predicted classes; label bars accordingly. **Accepted, D-13.**
- **CI gate via `run_eval.py --check` on parsed/rounded values, not bytes, not a reimpl; name it a regression gate; green CI ≠ extraction is good.** **Accepted, D-17.**
- **Bootstrap: draft with a DIFFERENT model than the extractor to avoid quiet phrasing-leakage.** **Accepted, D-19.**
- **Corpus: ~15 denser multi-employee fixtures, not 25 single-purpose.** **Accepted, D-18.**
- **Judge: drop-first, not per-category, show 3 drafts in README, add a wrong-real-employee correctness floor.** Verified against `app/pipeline/suggest.py`: off-roster names are already dropped, so the floor is specifically "names the WRONG REAL employee." **Accepted, sharpened, D-15/D-16.**
- **Commit SVG not PNG** (diffable, scales). **Accepted, D-08.**
- **Scope: Phase 4 is priority #3 — don't gold-plate; split into a hard exit bar vs "if time".** **Accepted as the framing, D-EXIT.**

### Tiering decision (post-review gate)
| Option | Description | Selected |
|--------|-------------|----------|
| Lean core + confusion matrix + 1 wiring test | Hard bar = 3 fixed core metrics + matrix + wiring test + SVG/summary + --check CI over ~15 fixtures; judge/DB/(b) = if time | ✓ |
| Everything is exit bar | Keep judge, DB write, dual a/b as required | |
| Minimal — 3 metrics + chart only | Cut matrix + wiring test to "if time" | |

**User's choice:** Lean core + confusion matrix + 1 wiring test.

### Dual-path decision (post-review gate)
| Option | Description | Selected |
|--------|-------------|----------|
| Conditional — keep (a), (b) only if extraction diverges | (a) always; (b) only for hard-extraction fixtures (vague/buried); drop if (a)==(b) everywhere | ✓ |
| Always compute both (a) and (b) | Report both for every fixture (noise on clean fixtures) | |
| Drop (b) — ship (a) only | Isolated path only; loses the real-path signal | |

**User's choice:** Conditional — (a) always, (b) only where extraction diverges.

---

## Claude's Discretion

- Exact `eval/` directory layout, fixture filename scheme, `run_eval.py` location, cached-extraction filename convention, bootstrap helper location.
- The `expected` block's exact JSON schema (what it carries is fixed; field names/nesting are open, kept diffable/hand-editable).
- Confusion-matrix rendering details (false-process must be the headline; small-n shown as k/n).
- Precise F1 formulation (micro vs macro), provided extras count as false positives.
- Whether the wiring smoke test lives in run_eval.py or as a pytest (it must assert == the Phase-3 golden).
- Exact rubric anchor wording (structure fixed: one line, 2–3 anchors, wrong-real-employee floor).

## Deferred Ideas

- Full synthetic fixture generator → v2 (EVAL-V2-02); multi-judge ensemble / larger corpus → v2 (EVAL-V2-01).
- Phase 5 dashboard eval view (DASH-04) consumes Phase 4's summary.json; rendering is Phase 5.
- eval_results DB write beyond a stub → "if time" within Phase 4 (D-14); otherwise lands with Phase 5.
- LLM judge → "if time", drop-first (D-15). (b) end-to-end scoring → "if time"/conditional (D-07).
- Over-40-no-OT validation rule (Phase 3 D-05) → still its own insertion before Phase 5 (backlog.md); not a Phase 4 deliverable, but any weekly >40-no-OT eval fixture must label current behavior, not the future rule.
