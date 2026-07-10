# Phase 14: Full Type-Checking (mypy) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-10
**Phase:** 14-Full Type-Checking (mypy)
**Areas discussed:** Strictness tiering, Untyped 3rd-party strategy, CI wiring & proof, Fix philosophy & real bugs

---

## Strictness tiering

**Q1: How strict should mypy be for the runtime code (app/, eval/, scripts/)?**

| Option | Description | Selected |
|--------|-------------|----------|
| strict = true (Recommended) | Full --strict for runtime code; legible "mypy --strict clean" headline; app/ already 61% return-annotated | ✓ |
| Curated strict-ish set | Hand-picked flags without the full bundle; less churn but "mostly strict" headline | |
| mypy defaults | Cheapest, but default mode skips unannotated bodies — a real blind spot | |

**Q2: What strictness tier should tests/ get? (1,029 defs, only 244 annotated)**

| Option | Description | Selected |
|--------|-------------|----------|
| Relaxed override (Recommended) | tests.* override: check_untyped_defs = true, disallow_untyped_defs = false — bodies still checked, no annotation of ~785 defs | ✓ |
| Fully strict tests too | Uniform strict; cleanest story but triples the diff for marginal gain | |
| Middle: strict for new, relaxed for old | Per-file ratchet; maintenance-heavy config | |

**User's choice:** strict = true for runtime; relaxed-but-checked override for tests/
**Notes:** Remaining strictness details (pydantic plugin knobs, repo facade re-exports under no_implicit_reexport, annotation syntax) left to planner discretion.

---

## Untyped 3rd-party strategy

**Q: How should mypy handle reportlab, the one dependency with no type stubs?**

| Option | Description | Selected |
|--------|-------------|----------|
| Scoped override (Recommended) | [[tool.mypy.overrides]] for reportlab.* only, ignore_missing_imports = true + why-comment; matches Phase 12 zero-blanket-ignores precedent | ✓ |
| Scoped override + typed boundary | Same plus enforce fully-typed pdf.py public signature | |
| Global ignore_missing_imports | Simplest but swallows typos in any import name | |
| Write local stub files | Hand-written .pyi for ~4 APIs; disproportionate effort | |

**User's choice:** Scoped override
**Notes:** Same pattern documented as the policy for any future untyped dep.

---

## CI wiring & proof

**Q1: How should the mypy gate be wired into ci.yml?**

| Option | Description | Selected |
|--------|-------------|----------|
| Third parallel job (Recommended) | `typecheck` alongside `lint`/`test`, same setup recipe; one gate = one named check (Phase 12 D-10) | ✓ |
| Step inside the lint job | One fewer runner but mypy/ruff failures indistinguishable at check level | |

**Q2: Red-proof the mypy gate like Phase 12?**

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, same red-proof (Recommended) | Throwaway branch with injected type error; red run URL in VERIFICATION.md; delete branch | ✓ |
| No, green run is enough | Leaves "blocking" unproven | |

**Q3: Exact gate command (byte-for-byte local/CI parity)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Bare `uv run mypy` + files in config (Recommended) | files = ["app", "eval", "scripts", "tests"] in [tool.mypy]; scope lives in committed config | ✓ |
| Explicit paths in the command | Scope visible in CI file but local invocations can silently under-check | |
| You decide | Planner picks, holding parity requirement | |

**User's choice:** Third parallel job; yes to red-proof; bare command with config-driven scope.

---

## Fix philosophy & real bugs

**Q1: `# type: ignore` policy when bringing existing code to green?**

| Option | Description | Selected |
|--------|-------------|----------|
| Zero-tolerance, justified only (Recommended) | Fix properly; ignore only with error code + stated reason; warn_unused_ignores prevents staleness | ✓ |
| Pragmatic budget | Free-ish ignores; faster but guarantee erodes | |
| You decide | Planner discretion | |

**Q2: If mypy exposes a genuine runtime bug (especially money-path)?**

| Option | Description | Selected |
|--------|-------------|----------|
| Fix separately, test-first (Recommended) | Own commit: failing test first, then minimal fix, separate from annotation commits (Phase 7.5/11 lesson) | ✓ |
| Record only, fix later | Ships a known bug behind a green badge | |
| Fix inline with annotations | Behavior change hidden in mechanical diff | |

**Q3: How liberal can annotations be with `Any` for dynamic spots?**

| Option | Description | Selected |
|--------|-------------|----------|
| Any at dynamic edges only (Recommended) | dict[str, Any] fine for JSONB/LLM-JSON/DB rows; concrete types once inside pipeline logic | ✓ |
| TypedDicts everywhere | Parallel-maintenance duplication of Pydantic edge models | |
| You decide | Planner discretion | |

**User's choice:** Zero-tolerance ignores; separate test-first bug commits; Any at dynamic edges only.

---

## Claude's Discretion

- Exact `[tool.mypy]` layout and pydantic-plugin settings; which strict flags the tests override relaxes.
- `no_implicit_reexport` treatment for the `app/db/repo/` facade (explicit re-exports vs `__all__`).
- mypy version pin, CI caching, action pinning per house style.
- Commit sequencing/granularity across the four directories.
- `cast()` usage specifics within the agreed discipline.

## Deferred Ideas

None — discussion stayed within phase scope. The 5 keyword-matched todos were prior-phase false positives (dispositioned to Phase 15 / backlog); none folded.
