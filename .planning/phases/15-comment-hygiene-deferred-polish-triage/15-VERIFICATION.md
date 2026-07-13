---
status: passed
phase: 15-comment-hygiene-deferred-polish-triage
requirements: [COMM-01, COMM-02, COMM-03, POLISH-01, POLISH-02]
verified_by: orchestrator (gsd-verifier agent died on a session/usage limit before producing output)
date: 2026-07-13
score: 5/5 must-haves verified
gaps_closed_in_phase: [COMM-01 vocabulary hole, COMM-01 scan-scope hole]
---

# Phase 15 Verification

All 11 plans executed, merged, and green. Verification initially scored **4/5**: COMM-01's guard
had a vocabulary hole and a scope hole (documented in full below — the record is kept deliberately,
because *how* the guard was blind is the most useful thing this phase learned). Both were closed
inline in commit `9973c22`. **Final: 5/5.**

## Gates (merged tree, HEAD, after gap closure)

| Gate | Result |
|------|--------|
| `uv run pytest -q` | **623 passed / 52 skipped** |
| `uv run ruff check .` | clean |
| `uv run mypy` (strict) | clean, 117 files |
| Comment-provenance guard | **3/3 passed** |
| Worktrees outstanding | 0 |
| SUMMARY.md present | 11/11 |

## VERIFIED

### POLISH-01 — behavior fixes ✅
Both fixes landed test-first with genuine RED evidence, and both survive 15-09's later sweep of
the same files:
- **Path traversal (WR-05)** — `app/routes/dashboard.py` uses `resolve()` +
  `is_relative_to(fixtures_root)`. The RED run rendered a file from *outside* the fixtures
  directory onto the eval page via `../`. Regression test passes.
- **Prompt echo (INFO-02)** — `app/llm/client.py::_scrubbed_validation_summary()` uses
  `exc.errors(include_url=False, include_input=False)`, so model output is no longer returned to
  the provider in the retry prompt. Regression test passes.
- **Reply threading (WR-01)** — no production bug existed; the epoch machinery already held. The
  test is a regression gate, and it was **proven capable of failing**: narrowing the `ON CONFLICT`
  arbiter and the `uq_email_run_purpose_round_epoch` constraint to three columns makes test 1 fail
  while test 2 still passes — concrete evidence the same-epoch-retry test alone would have missed
  a clobbered delivered email.

### POLISH-02 — deferred-polish triage ✅
Todos `260623-01` and `260623-05` moved `pending/` → `completed/`. The fixture-10 item, filed as
cosmetic, was a **real eval-chart defect**: a mislabeled fixture was dumping an intentional
phantom-employee miss into the `exact` bucket, so the chart reported exact-match extraction failing
at 0.96 when it had never failed. Now `exact.f1 = 1.00`, `typo.f1 = 0.90`. Overall F1 (0.9889) and
the confusion matrix (`false_process = 0`) unchanged, as expected — relabeling rebuckets, it does
not rescore.

### COMM-02 — money-path comment depth ✅
Comments document constraints, not history. Independently verified **no damage to the money path**:

| File | AST identity (docstrings stripped) | Numeric/Decimal literals |
|------|-----------------------------------|--------------------------|
| `tax_tables_2026.py` | IDENTICAL | **194 — all identical** |
| `federal_withholding.py` | IDENTICAL | 5 — all identical |
| `decide.py` | IDENTICAL | — |
| `validate.py` | IDENTICAL | — |
| `calculate.py` | 2 string constants only* | 14 — all identical |

\* the only delta is two exception messages with `D-05:` stripped — no control flow, no arithmetic.
**Zero 2026 tax constants changed.** IRS `irs.gov` citations preserved (3 + 2 in source, 4 + 3 in tests).

The `decide.py` no-confidence guard is intact: 0 occurrences of "confidence", `test_gate.py` 15
passed. Plan 15-04 hit a direct conflict between its own acceptance criteria and this guard and
chose to obey the guard — rewriting its invariant without the banned word rather than weakening the
test that protects the deterministic-decisioning thesis.

### COMM-03 — test identity ✅
32 function renames + 2 file renames. **Test count neutral: 666 → 666 → 666**, proving no test was
silently dropped or duplicated. Assert *conditions* proven untouched by AST comparison (172 + 77
`ast.Assert.test` nodes identical); only assert *messages* changed.

## COMM-01 — the guard ✅ (after gap closure `9973c22`)

**Both gaps below were found by verification and closed inline.** They are recorded in full rather
than deleted, because the lesson generalises: *the guard was green because it was blind, not because
the tree was clean.* A guard's scan scope and vocabulary are part of its correctness, and neither is
visible from a passing run.

### GAPS AS FOUND (now fixed)

The comment-provenance guard (`tests/test_comment_provenance_guard.py`) works and is **not**
vacuous — I independently falsified it rather than trusting the SUMMARY:

| Injection | Expected | Actual |
|---|---|---|
| `CR-02 / Phase 9 / D-11-01 / Finding #3` | red | red ✓ |
| `D-A3-05` (letter-prefixed decision ID) | red | red ✓ |
| `BOUND-01` / `FOUND-04` (live requirement IDs) | green | green ✓ |

But it has two holes, and the tree is green *because of them*, not because it is clean.

### GAP-1 — the `IN-NN` ticket family is absent from the guard's vocabulary
`IN-` appears nowhere in the pattern table. Three live provenance refs survive **in files the guard
actively scans**, and the guard is green:

- `app/db/seed.py:355` — `# (IN-08): no model_dump is called here.` *(owned by plan 15-05)*
- `tests/test_tax_tables_2026.py:287` — `"""IN-02 (review round 2): ..."""` *(owned by plan 15-07)*
- `eval/draft_candidate_emails.py:9` — `...consistent with the other eval scripts (IN-03).`
  *(owned by **no plan** — this file is in no plan's `files_modified`)*

Three separate plans swept these files and left the refs, because every per-plan regex and the final
guard share the same blind spot. This is the same class of miss 15-10 caught with `D-A3-05` — found
by extending the vocabulary — except this one was not caught.

### GAP-2 — `SCAN_GLOBS` excludes the infra/CI surface
The guard's own docstring states its surface is *"every file whose text a maintainer reads."* Its
globs cover `app/`, `eval/`, `scripts/`, `tests/` — but not the build, CI, or config files. **17
provenance refs survive there, unenforced:**

| File | Refs |
|------|------|
| `pyproject.toml` | 9 — `IN-09`, `D-01` ×2, `D-02` ×2, `D-03` ×2, `D-04`, `D-06` |
| `Dockerfile` | 3 — `D-19`, `D-21` ×2 |
| `.github/workflows/eval.yml` | 2 — `CR-01` ×2 |
| `.github/workflows/concurrency-proof.yml` | 2 — `WR-04`, `Phase 9` |
| `.github/workflows/ci.yml` | 1 — `WR-01` |
| `.github/workflows/keepalive.yml` | 2 — `D-16`, `D-20` |
| `.dockerignore` | 1 — `D-21` |
| `.env.example` | 1 — `Phase 6` |

These are rot by the phase's own D-01/D-02 rubric. Several carry genuine rationale that should be
*kept* while the ticket ID is dropped — e.g. `pyproject.toml:47` reads
`# D-02: 100 is the measured tradeoff — 160 lines exceed 100 vs 1,297 that exceed the 88 default.`
The constraint is worth keeping; the `D-02:` prefix is not.

**Out of scope (correctly):** `CLAUDE.md` / `AGENTS.md` (3 `Phase N` refs each) and `docs/**` are
project documents describing the roadmap — narrating project history is their *purpose*, not rot.

## Known, recorded limitation (not a new finding)

The concurrency/epoch proofs gate **push-to-master and manual dispatch, but not `pull_request`**. A
PR can go green without a real database ever executing them. Recorded by plan 15-01 in a comment
above the workflow's `on:` block; adding a `pull_request:` trigger is a CI-policy change outside
POLISH-01's scope.

## Gap closure — `9973c22`

Both gaps closed inline (the `gsd-verifier` agent had died on a usage limit, and the fix was
mechanical and touched no money-path code):

- Added `IN` to the `review-ticket` pattern.
- Extended `SCAN_GLOBS` to `.github/workflows/*.yml`, `Dockerfile`, `pyproject.toml`,
  `.dockerignore`, `.env.example`.
- Widening the guard turned it **red on 32 real violations** — more than the 20 found by hand,
  because the guard's fuller vocabulary also caught `HIGH-1` severity labels, `Pitfall 3/6` refs,
  and `OPS-03` in the Docker/CI files. All 32 swept.
- **Rationale preserved in every case; only labels dropped.** `pyproject.toml` still explains why
  line-length is 100; `keepalive.yml` still explains why `curl -f` matters (a swallowed failure
  would leave the workflow green during a real outage); `concurrency-proof.yml` still explains why
  `--reset` is absent (it would put an unguarded drop outside the `ALLOW_DB_RESET` two-factor guard).
- `app/db/seed.py` confirmed AST-identical — comment-only.
- `.env.example` was edited by the user; the file is behind a permission guard the agent correctly
  declined to route around.

### Guard re-falsified after widening

| Injection | Expected | Actual |
|---|---|---|
| `IN-08` / `CR-02` / `Phase 9` | red | red ✓ (the `IN-` family is now caught) |
| `BOUND-01` / `FOUND-04` | green | green ✓ (no false positive on live requirement IDs) |

Source restored byte-identical after each probe.

## Carried-forward items — ALL CLOSED

Closed after the phase, alongside the Codex cross-AI review fixes:

1. ~~**The concurrency proofs do not gate pull requests.**~~ **CLOSED.** A `pull_request:` trigger
   was added to `.github/workflows/concurrency-proof.yml`. This was the only gap that could let a
   money-path regression reach master unproven: the real-Postgres proofs are the *only* tests that
   touch a real database — the rest of the suite mocks it, so a broken `ON CONFLICT` arbiter or a
   lost update is invisible to them by construction. Safe on fork PRs: the DB is an ephemeral service
   container with throwaway credentials and the job reads no repository secrets.
2. ~~**`FieldDrop` in `app/models/contracts.py` is dead code.**~~ **CLOSED.** Deleted. Verified dead
   first: its only three appearances in the entire tree were its own class definition, its section
   header, and a cross-reference comment pointing at it. Every real code path uses `RawFieldDrop`.
3. ~~**`.claude/settings.local.json` untracked and unignored.**~~ **CLOSED.** Added to `.gitignore`
   along with `.claude/worktrees/`. This was not cosmetic — an unignored harness file makes every
   agent worktree read as dirty, which fail-closed the wave-merge safety check during this very
   phase's execution.

## Cross-AI review (Codex, `codex-cli 0.144.0`)

Codex reviewed the phase and found **no CRITICAL issues**. It independently confirmed the two claims
this verification rests on — that only `dashboard.py` and `client.py` changed real logic, and that
the money path is byte-identical — and confirmed the new threading tests are not vacuous and the
eval relabel rebuckets without rescoring.

Its three warnings and one info were all real and are fixed in `244a7e7`:

- **`app/db/bootstrap.py` docstring lied.** Its Security section claimed *"the default path never
  issues a DROP"*. False — the default path always drops the dead `name_matches` table and the
  `match_confidence` column. The code is correct (deliberate idempotent migrations that must live
  outside `--reset`), but an operator reading that docstring would run it against production
  believing it was non-destructive. **A lying comment in a DB bootstrap's security notes is the exact
  failure mode this phase existed to eliminate, and the sweep walked past it.** Docstring corrected;
  verified AST-identical, so no DROP behavior moved.
- **`render.yaml` was outside the guard's `SCAN_GLOBS`** and still carried `OPS-01`/`D-09`/`D-20`.
  Swept and added to the guard. Two independent reviews, two scan-scope holes — the lesson is that
  *what a guard does not look at is invisible from a passing run.*
- **Path containment is not TOCTOU-safe.** Accepted and documented rather than engineered around:
  exploiting it requires write access to `eval/fixtures/` on the running container, i.e. code
  execution already. `openat`/`O_NOFOLLOW` buys nothing against an attacker already inside.
- **`client.py`'s non-Pydantic branch returned `str(exc)`.** Safe today, but a standing invitation to
  reopen the prompt-echo leak. Now an allowlist, guarded by a test that was falsified (it goes red
  when reverted to a bare passthrough).
