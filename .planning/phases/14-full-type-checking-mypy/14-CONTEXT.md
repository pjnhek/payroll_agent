# Phase 14: Full Type-Checking (mypy) - Context

**Gathered:** 2026-07-10
**Status:** Ready for planning

<domain>
## Phase Boundary

The entire repo — `app/` (52 files, ~10.5k lines), `eval/`, `scripts/`, and `tests/` (56 files, ~26.8k lines) — becomes statically type-clean under mypy with the pydantic plugin, configured in `pyproject.toml`, and that guarantee is enforced as a blocking check extending Phase 12's `ci.yml`. Requirements: TYPE-01, TYPE-02, TYPE-03.

Behavior-neutral by default: the phase's diff is annotations, narrowing, and config. Any genuine runtime bug mypy exposes is handled under D-08's separate test-first protocol — never buried in annotation commits. Phase 13's post-split module layout is final; annotations land in the final file locations.

</domain>

<decisions>
## Implementation Decisions

### Strictness tiering (TYPE-01, TYPE-02)
- **D-01:** Runtime code (`app/`, `eval/`, `scripts/`) is checked with **`strict = true`** — the full strict bundle, no cherry-picking. The legible headline is "mypy --strict clean"; it matches the v3 production-ready-codebase narrative.
- **D-02:** `tests/` gets a **relaxed override**: one `[[tool.mypy.overrides]]` block for `tests.*` with `check_untyped_defs = true` and `disallow_untyped_defs = false` (relax other strict `disallow_*` flags as needed for the same effect). Every test body is still type-checked — no blind spot per TYPE-02 — but the ~785 unannotated test defs do not have to be hand-annotated. Honest, documented tiering, not an exclusion.

### Untyped third-party handling
- **D-03:** reportlab is the only dependency without types (4 imports: `app/pipeline/pdf.py`, `app/pipeline/delivery.py`, plus tests). Handle it with a **scoped `[[tool.mypy.overrides]]` for `reportlab.*`** setting `ignore_missing_imports = true`, with a comment stating why. No global `ignore_missing_imports` — Phase 12's zero-blanket-ignores precedent applies to mypy config too.
- **D-04:** The same pattern (scoped override + justification comment) is the documented policy for any future untyped dependency.

### CI wiring & proof (TYPE-03)
- **D-05:** `ci.yml` gains a **third parallel job `typecheck`** alongside `lint` and `test`, following the identical house recipe (pinned checkout → `astral-sh/setup-uv` with Python 3.12 → `uv sync --locked` → run). Each gate stays its own named red/green check per Phase 12 D-10.
- **D-06:** The gate command is **bare `uv run mypy`** with `files = ["app", "eval", "scripts", "tests"]` set in `[tool.mypy]` — scope lives in committed config, so local and CI invocations agree byte-for-byte (Phase 12 CI-03 philosophy). mypy is added as a dev dependency via `uv add --dev mypy`.
- **D-07:** The gate is **red-proofed** the Phase 12 way: push a throwaway branch with a deliberately injected type error, capture the red run URL (plus the green master run URL) in the phase VERIFICATION.md, delete the branch.

### Fix philosophy (bringing ~39k lines to green)
- **D-08:** **Real bugs get separate, test-first commits.** If mypy exposes a genuinely reachable runtime bug (None-path, wrong type — especially in money-path code), it is fixed in its own commit: failing test proving the bug first, then the minimal fix, clearly separated from annotation commits. Never bury a behavior change inside a mechanical diff (Phase 7.5/11 review lesson).
- **D-09:** **Zero-tolerance ignore policy:** fix errors properly (annotations, narrowing, `cast()` where truly needed). A `# type: ignore[code]` is allowed only with a specific error code AND a stated reason comment — the mypy analog of Phase 12 D-03. strict's `warn_unused_ignores` keeps ignores from going stale.
- **D-10:** **`Any` at dynamic edges only:** `dict[str, Any]` is acceptable for genuinely dynamic data — JSONB context payloads, raw LLM JSON, DB row dicts at the psycopg boundary. Once values cross into pipeline logic they get concrete types (`Decimal`, `UUID`, TypedDict/Pydantic where a stable shape exists). No `Any` as a shortcut for types the code actually knows.

### Claude's Discretion
- Exact `[tool.mypy]` config layout and pydantic-plugin settings; which specific strict flags the `tests.*` override relaxes to achieve D-02's effect.
- Handling strict's `no_implicit_reexport` for the `app/db/repo/` facade (explicit `from x import y as y` vs `__all__`) — pick one style and apply it consistently.
- mypy version pin and whether to enable mypy caching in the CI job (follow the house pattern of pinned action SHAs).
- Commit sequencing/granularity across the four directories — as long as each commit is behavior-neutral (except D-08 bug-fix commits), the suite and existing lint gate stay green at every commit.
- `cast()` usage specifics within D-09/D-10 discipline.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements & milestone framing
- `.planning/ROADMAP.md` — Phase 14 goal + success criteria 1–3; v3 dependency chain (Phase 13 layout is final; Phase 15 comment pass runs after this so comment-only diffs don't re-trigger type review).
- `.planning/REQUIREMENTS.md` — TYPE-01, TYPE-02, TYPE-03 exact wording.

### Prior-phase constraints that bind this phase
- `.planning/phases/12-ci-quality-gates/12-CONTEXT.md` — the `ci.yml` structure this phase extends (parallel named jobs, push-to-all-branches, per-branch cancellable concurrency, byte-for-byte local/CI parity, red-proof evidence pattern, zero-blanket-ignores philosophy).
- `.planning/phases/13-module-structure-boundaries/13-CONTEXT.md` — final module layout (`app/db/repo/` package facade, `app/routes/`, pipeline carve-outs), module-object import discipline, and the monkeypatch seam patterns annotations must not break.

### Files this phase directly extends
- `.github/workflows/ci.yml` — the two existing jobs (`lint`, `test`) whose recipe the new `typecheck` job mirrors; pinned action SHAs are the house style.
- `pyproject.toml` — where `[tool.mypy]` lands; existing `[tool.ruff]` / `[tool.ruff.lint]` and `[dependency-groups].dev` sections; `uv.lock` updated via `uv add --dev mypy`.

### Tooling rules
- `CLAUDE.md` §Tooling Rule — uv-only; `uv run mypy` / `uv run pytest -q` for every verification; never pip.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ci.yml`'s `lint` job is a copy-paste template for the `typecheck` job — same checkout/setup-uv/sync steps, only the run command differs.
- Annotation coverage is already decent in runtime code: `app/` 107/175 defs return-annotated, `eval/` 19/21, `scripts/` 6/7 — the strict pass is completion work, not greenfield annotation.
- `tests/` is the outlier: 244/1,029 defs annotated across 26.8k lines — the D-02 relaxed override exists specifically because of this.

### Established Patterns
- All major deps ship types: FastAPI, Pydantic (with its mypy plugin), psycopg/psycopg_pool, openai, httpx, jinja2, pytest. Only reportlab is untyped (D-03).
- The repo already uses modern typing idioms in places (`X | None`, `Literal`, `TYPE_CHECKING` imports from Phase 12's F821 fixes); ruff's UP rules enforce modern syntax, so new annotations should match.
- Test seams are module-attribute monkeypatches (`monkeypatch.setattr(repo, "fn", ...)`, orchestrator attribute stubs) — annotations must not change module structure or names; this phase adds types, it does not move code.
- Execute-phase hazard (v2/v3 experience): this repo's `.env` has LIVE LLM keys — any executor running tests must keep LLM seams stubbed; never rely on env emptiness.

### Integration Points
- `pyproject.toml` `[tool.mypy]` + `[[tool.mypy.overrides]]` (tests relaxation, reportlab ignore) — the single config source for D-06's bare-command parity.
- `.github/workflows/ci.yml` — third job slot Phase 12 deliberately left trivial to add.
- `app/db/repo/__init__.py` facade re-exports will trip strict's `no_implicit_reexport` — needs the explicit-reexport treatment (Claude's discretion on style).
- Phase 15 depends on this phase completing first: the comment pass touches the same files mypy just annotated.

</code_context>

<specifics>
## Specific Ideas

- The recruiter-legible headline is "the whole repo is mypy --strict clean, enforced in CI" — the config should make that claim true and easy to verify (one committed config, one bare command, a visibly red run when someone breaks it).
- Tiering for tests is deliberate and documented, not an apology: every test body is still checked; only annotation *requirements* are relaxed.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

### Reviewed Todos (not folded)
- All 5 keyword-matched pending todos are the same false positives dispositioned in Phases 12 and 13: `260623-01` (Phase 05 review warnings) and `260623-05` (fixture_category label) → Phase 15 (POLISH-01/POLISH-02); `260623-02/03/04` (frontend enhancement, paystub YTD, eval-chart restyle) → out of v3 per ROADMAP backlog. None relate to type-checking; none folded.

</deferred>

---

*Phase: 14-Full Type-Checking (mypy)*
*Context gathered: 2026-07-10*
