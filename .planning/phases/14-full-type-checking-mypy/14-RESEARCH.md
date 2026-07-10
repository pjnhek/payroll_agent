# Phase 14: Full Type-Checking (mypy) - Research

**Researched:** 2026-07-10
**Domain:** Python static type checking (mypy strict mode) across a 39k-line FastAPI/Pydantic/psycopg codebase, wired into GitHub Actions CI
**Confidence:** HIGH

## Summary

This research is grounded in an **empirical error census**: mypy 2.2.0 (current PyPI release, 2026-07-08) was temporarily installed via `uv add --dev mypy`, run in `strict = true` mode with the pydantic plugin against the real codebase, and then removed (`uv remove --dev mypy`, `pyproject.toml`/`uv.lock` restored to clean). The counts below are real tool output, not estimates.

`app/` produces **170 errors across 30 of 52 files**. `eval/` + `scripts/` together produce **163 errors across 26 of 6 checked source files** (mypy follows imports, so the count includes transitively-checked `app/` files — the eval/scripts-only new surface is much smaller, dominated by `dict`/`list` missing type-args). `tests/` with the D-02 relaxed override (`check_untyped_defs = true`, `disallow_untyped_defs = false`) still produces **521 errors across 72 files** — the override reduces required annotation work but does not silence real type errors in test bodies, exactly as CONTEXT.md's D-02 intends.

The error mix is dominated by two purely mechanical categories — `no-untyped-def` (missing param/return annotations) and `type-arg` (bare `dict`/`list` needing type arguments) — which make up roughly 75% of all errors and are safe, boilerplate fixes. The remaining ~25% (`arg-type`, `union-attr`, `attr-defined`, `no-any-return`, `no-untyped-call`) cluster around a small number of real design points: `Optional`/`| None` narrowing at call boundaries (`UUID | None` passed where `UUID` is required), a dynamic exception-attribute pattern in `delivery.py` (D-09's `# type: ignore` case), and — critically — **two apparent genuine runtime bugs** surfaced by strict mode that D-08 requires be fixed in their own test-first commits (see Common Pitfalls). Only `reportlab` lacks type stubs; every other runtime dependency (including `python-multipart`, which mypy never actually needs to see since it's never imported by name) ships `py.typed` or equivalent, so D-03's single scoped override is confirmed sufficient — no other dependency needs one.

**Primary recommendation:** Wave the fix by mechanical-vs-design split, not by directory — knock out `no-untyped-def`/`type-arg` first (safe, high-volume, no behavior risk), then the `Optional`-narrowing/`attr-defined` cluster (needs judgment but still behavior-neutral), then isolate the two real bugs (`eval/run_eval.py`'s undefined `llm_client` import and `gateway.py`'s attribute-access-on-TypedDict) as standalone D-08 commits before touching CI. Wire the CI job and red-proof last, exactly mirroring Phase 12's `lint` job recipe.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Static type annotation coverage | Application code (`app/`, `eval/`, `scripts/`, `tests/`) | — | Type annotations are a property of the source files themselves; there is no separate "type-checking tier" in the running system. |
| mypy configuration | Build/tooling config (`pyproject.toml`) | — | Config lives alongside `[tool.ruff]`; both are static-analysis tool config, not runtime code. |
| CI enforcement | CI/CD (`.github/workflows/ci.yml`) | — | Enforcement is a pipeline concern (GitHub Actions), parallel to the existing `lint`/`test` jobs. |
| Third-party type stub resolution | Dependency/packaging tier (`uv.lock`, mypy overrides) | Build/tooling config | Whether a dependency ships types is a packaging fact; the override that works around a gap is committed tooling config. |

This phase has no browser/frontend/API/database tier work — it is purely a source-annotation + tooling-config + CI-pipeline change, which is why the map above collapses to two rows in practice.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Strictness tiering (TYPE-01, TYPE-02)**
- D-01: Runtime code (`app/`, `eval/`, `scripts/`) is checked with `strict = true` — the full strict bundle, no cherry-picking.
- D-02: `tests/` gets a relaxed override — one `[[tool.mypy.overrides]]` block for `tests.*` with `check_untyped_defs = true` and `disallow_untyped_defs = false` (relax other strict `disallow_*` flags as needed for the same effect). Every test body is still type-checked; only annotation *requirements* are relaxed.

**Untyped third-party handling**
- D-03: reportlab is the only dependency without types (4 imports: `app/pipeline/pdf.py`, `app/pipeline/delivery.py`, plus tests). Handle with a scoped `[[tool.mypy.overrides]]` for `reportlab.*` setting `ignore_missing_imports = true`, with a comment stating why. No global `ignore_missing_imports`.
- D-04: The same pattern (scoped override + justification comment) is the documented policy for any future untyped dependency.

**CI wiring & proof (TYPE-03)**
- D-05: `ci.yml` gains a third parallel job `typecheck` alongside `lint` and `test`, following the identical house recipe (pinned checkout → `astral-sh/setup-uv` with Python 3.12 → `uv sync --locked` → run). Each gate stays its own named red/green check per Phase 12 D-10.
- D-06: The gate command is bare `uv run mypy` with `files = ["app", "eval", "scripts", "tests"]` set in `[tool.mypy]` — scope lives in committed config, so local and CI invocations agree byte-for-byte. mypy is added as a dev dependency via `uv add --dev mypy`.
- D-07: The gate is red-proofed the Phase 12 way: push a throwaway branch with a deliberately injected type error, capture the red run URL (plus the green master run URL) in the phase VERIFICATION.md, delete the branch.

**Fix philosophy (bringing ~39k lines to green)**
- D-08: Real bugs get separate, test-first commits. If mypy exposes a genuinely reachable runtime bug (None-path, wrong type — especially in money-path code), it is fixed in its own commit: failing test proving the bug first, then the minimal fix, clearly separated from annotation commits. Never bury a behavior change inside a mechanical diff.
- D-09: Zero-tolerance ignore policy: fix errors properly (annotations, narrowing, `cast()` where truly needed). A `# type: ignore[code]` is allowed only with a specific error code AND a stated reason comment. strict's `warn_unused_ignores` keeps ignores from going stale.
- D-10: `Any` at dynamic edges only: `dict[str, Any]` is acceptable for genuinely dynamic data (JSONB context payloads, raw LLM JSON, DB row dicts at the psycopg boundary). Once values cross into pipeline logic they get concrete types. No `Any` as a shortcut for types the code actually knows.

### Claude's Discretion
- Exact `[tool.mypy]` config layout and pydantic-plugin settings; which specific strict flags the `tests.*` override relaxes to achieve D-02's effect.
- Handling strict's `no_implicit_reexport` for the `app/db/repo/` facade (explicit `from x import y as y` vs `__all__`) — pick one style and apply it consistently. **Research finding: this is very likely a non-issue in practice — see Pitfall "no_implicit_reexport does not actually fire here" below. Verify with a real mypy run at plan-check time before spending a task on it.**
- mypy version pin and whether to enable mypy caching in the CI job (follow the house pattern of pinned action SHAs).
- Commit sequencing/granularity across the four directories — as long as each commit is behavior-neutral (except D-08 bug-fix commits), the suite and existing lint gate stay green at every commit.
- `cast()` usage specifics within D-09/D-10 discipline.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope. (5 pending todos were reviewed and confirmed unrelated to type-checking; none folded in.)

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TYPE-01 | mypy (with the pydantic plugin) is configured in `pyproject.toml` and runs clean over `app/` | Empirical census: 170 real errors across 30/52 files in `app/` today, categorized by error code below; config template provided in Code Examples. |
| TYPE-02 | mypy runs clean over the rest of the codebase (`eval/`, `scripts/`, `tests/`) | Empirical census: 163 errors (eval/scripts, transitively checked with app/) and 521 errors in `tests/` even under the D-02 relaxed override; confirms the override reduces annotation burden without creating a blind spot. |
| TYPE-03 | mypy is a blocking check in the CI workflow | `ci.yml`'s existing `lint`/`test` job structure inspected directly; `typecheck` job is a literal copy with the run command swapped, per D-05/D-06. |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mypy | `2.2.0` `[VERIFIED: PyPI, installed and run directly in this session, 2026-07-10]` | Static type checker | Locked by REQUIREMENTS.md (`pyright` explicitly rejected — "mypy chosen: conventional for Python-only repos, official pydantic plugin, plain uv dev dep"). 2.2.0 confirmed current via WebSearch + direct `uv add --dev mypy` resolution. Released 2026-07-08, two days before this research. |
| pydantic (mypy plugin) | `2.13.4` (already a runtime dep) `[VERIFIED: already pinned in pyproject.toml]` | Teaches mypy about `BaseModel`/`BaseSettings` semantics (`model_config`, `extra="forbid"`, field defaults) | Without the plugin, mypy treats Pydantic models as ordinary classes and misses `extra="forbid"`/required-field semantics used pervasively in `app/models/contracts.py` (11 models use `ConfigDict(extra="forbid")`). Confirmed the plugin changes the real error count (172 without plugin vs 170 with, on `app/` census). |

**Installation:**
```bash
uv add --dev mypy
```

**Version verification:** Confirmed live in this session — `uv add --dev mypy` resolved `mypy==2.2.0` (plus `mypy-extensions==1.1.0`, `pathspec==1.1.1`, `ast-serialize==0.6.0`, `librt==0.13.0` as transitive deps), then `uv remove --dev mypy` cleanly reverted `pyproject.toml`/`uv.lock` to their pre-research state (`git diff` confirmed empty). The pydantic mypy plugin ships inside the already-pinned `pydantic==2.13.4` package — no separate install needed, just `plugins = ["pydantic.mypy"]` in config.

### Supporting
None beyond mypy itself and the pydantic plugin it already depends on — no `types-*` stub packages are needed (see Package Legitimacy Audit).

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| mypy | pyright | Already excluded by REQUIREMENTS.md's Out of Scope table ("pyright — mypy chosen"). Not re-litigated. |

## Package Legitimacy Audit

Only one new package is added this phase: `mypy` (dev dependency). No `types-*` stub packages are required — the census below confirms every runtime dependency except `reportlab` ships its own `py.typed` marker.

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|--------------|
| mypy | PyPI | ~13 years (since 2013) | Very high (tens of millions/month; core Python tooling) | github.com/python/mypy (official, Python Software Foundation-adjacent) | not run (see below) | Approved |

**slopcheck status:** slopcheck was not installed/run in this research session (no network install attempted for it). Given `mypy` is (a) resolved directly and successfully via `uv add --dev mypy` against the real PyPI registry in this session, (b) a 13-year-old, extremely high-download-count, universally-known core Python tool with an official `github.com/python/mypy` repo, and (c) the exact package REQUIREMENTS.md already named as the chosen tool (not a name discovered via search) — this is about as low-risk as a package identification gets. Per the package-name provenance rule, it is still tagged `[VERIFIED: PyPI, installed and run directly this session]` rather than a search-sourced `[ASSUMED]`, because existence + identity were confirmed by direct tool execution against the authoritative registry, not merely cited from training data. If the planner wants a hard slopcheck gate regardless, it can be run in a `checkpoint:human-verify`-gated task with negligible risk of a different outcome.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
 Developer / CI trigger
        │
        ▼
 [git push] ──────────────────────────────────────────────┐
        │                                                  │
        ▼                                                  ▼
 .github/workflows/ci.yml (3 parallel jobs, unchanged shape)
   ┌─────────────┐   ┌─────────────┐   ┌──────────────────┐
   │ lint         │   │ test        │   │ typecheck (NEW)  │
   │ ruff check . │   │ pytest -q   │   │ uv run mypy      │
   └─────────────┘   └─────────────┘   └──────────────────┘
        │                   │                   │
        ▼                   ▼                   ▼
   pass/fail          pass/fail          pass/fail
   (independent, named checks — a mypy failure blocks merge
    the same way a lint or test failure does; D-05)

 uv run mypy reads:
   pyproject.toml [tool.mypy]  →  files = ["app","eval","scripts","tests"]
                               →  strict = true (default tier)
                               →  plugins = ["pydantic.mypy"]
                               →  [[tool.mypy.overrides]] for "tests.*" (relaxed)
                               →  [[tool.mypy.overrides]] for "reportlab.*" (ignore_missing_imports)
   same config file, same command, local dev machine AND CI — byte-for-byte parity (D-06)
```

### Recommended Project Structure
No new directories. All changes are:
```
pyproject.toml            # [tool.mypy] + [tool.pydantic-mypy] + [[tool.mypy.overrides]] x2
.github/workflows/ci.yml   # + typecheck job
app/**/*.py                # annotations added in place (Phase 13 layout is final — no moves)
eval/**/*.py                # annotations added in place
scripts/**/*.py              # annotations added in place
tests/**/*.py                 # annotations only where the relaxed override still requires them
```

### Pattern 1: Strict-by-default with a scoped test override
**What:** One `[tool.mypy]` block sets `strict = true` for everything matched by `files`, then a single `[[tool.mypy.overrides]]` block narrows requirements for `tests.*` only.
**When to use:** Exactly this phase's shape — a codebase where production code should be fully annotated but a large legacy test suite (244/1,029 defs currently annotated per CONTEXT.md) would be disproportionately expensive to fully annotate for no safety benefit, since `check_untyped_defs = true` still type-checks every test body.
**Example:**
```toml
# Source: mypy official docs (config-file.html#confval-strict) + this session's
# empirical verification (tests/ still produces 521 real errors under this override,
# proving it is not a blanket exclusion).
[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
files = ["app", "eval", "scripts", "tests"]

[[tool.mypy.overrides]]
module = "tests.*"
check_untyped_defs = true          # still type-check every test body (no blind spot)
disallow_untyped_defs = false      # ...but don't require full annotations on test defs
disallow_incomplete_defs = false
disallow_untyped_decorators = false

[[tool.mypy.overrides]]
module = "reportlab.*"
ignore_missing_imports = true       # reportlab ships no type stubs (verified this session:
                                     # no py.typed marker, no types-reportlab on PyPI needed)
```

### Pattern 2: `NamedTuple` return typed correctly instead of `object`
**What:** `app/pipeline/federal_withholding.py`'s `_find_bracket()` currently declares `-> object` even though it always returns a `BracketRow` (a real `NamedTuple` defined in `app/pipeline/tax_tables_2026.py`, imported into the same module's neighborhood).
**When to use:** Anywhere a function's return type was widened to `object`/`Any` historically to sidestep an unannotated caller — strict mode will flag every attribute access on the result (`row.lower`, `row.rate`, `row.base` all fail today), and the fix is a one-line, zero-risk annotation change, not new logic.
**Example:**
```python
# Source: this session's direct grep of app/pipeline/federal_withholding.py:45
# and app/pipeline/tax_tables_2026.py's BracketRow(NamedTuple) definition.
# BEFORE (strict-mode errors on every attribute access at the 3 call sites):
def _find_bracket(annual_wage: Decimal, brackets: list) -> object: ...

# AFTER:
def _find_bracket(annual_wage: Decimal, brackets: list[BracketRow]) -> BracketRow: ...
```

### Anti-Patterns to Avoid
- **Widening a return type to `object`/`Any` to silence a caller:** `federal_withholding.py`'s `_find_bracket` is the textbook example already present in this codebase — the correct concrete type (`BracketRow`) already existed one file away. D-10 explicitly rules this out except at genuinely dynamic boundaries (JSONB, raw LLM JSON, DB row dicts).
- **Reaching for `# type: ignore` before checking whether the underlying API is a `TypedDict`:** `app/email/gateway.py` accesses `email_obj.headers` / `.message_id` / `.text` as attributes on a `resend.ReceivedEmail`, but that class is a `TypedDict` (confirmed by reading `resend/emails/_received_email.py` directly in this session) — the correct fix is subscript access (`email_obj["headers"]`), not an ignore comment. See Common Pitfalls.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pydantic model type-awareness | A custom mypy plugin or manual `# type:` scattering on every model field | `plugins = ["pydantic.mypy"]` (ships inside the already-installed `pydantic` package) | Official, zero extra install, directly understands `model_config`/`extra="forbid"`/required-vs-optional fields already used across all 11+ contract models. |
| Missing stubs for an untyped dependency | Hand-writing a full `.pyi` stub file for reportlab | Scoped `ignore_missing_imports = true` override (D-03) | reportlab's public surface used here (`SimpleDocTemplate`, `Table`, styles) is broad; a hand stub is a maintenance burden for zero safety gain versus the officially-sanctioned override pattern. |
| Detecting whether a dependency has types | Guessing from memory / assuming stub packages exist | Check `py.typed` presence directly (`python -c "import X, os; print(os.path.isfile(os.path.join(os.path.dirname(X.__file__),'py.typed')))"`) or just run mypy and read the `import-untyped` errors | Verified directly in this session across all 11 runtime deps — only reportlab lacked `py.typed`; guessing would have risked adding unnecessary `types-*` stub packages (a supply-chain-hardening non-issue since none are needed). |

**Key insight:** This phase's "don't hand-roll" risk isn't about a complex algorithm — it's about not hand-rolling stub files or ignore-comment sprawl when the correct, sanctioned single-override pattern (D-03/D-04) already covers the one real gap.

## Common Pitfalls

### Pitfall 1: `no_implicit_reexport` (part of `strict`) very likely does not fire on the `app/db/repo/` facade at all
**What goes wrong:** CONTEXT.md flags handling `no_implicit_reexport` for the repo facade as a Claude's-discretion item, implying real work is needed (`__all__` vs `from x import y as y`).
**Why it happens (research finding):** `no_implicit_reexport` only triggers on `from module import name` — i.e., when a caller imports an individual attribute through a package boundary without `as` or `__all__`. This session verified with a minimal isolated repro (two-file package, `from pkg.sub import foo` re-exported through `__init__.py`, then `from pkg import foo` in a caller) that the error **does** fire in that shape (`Module "pkg" does not explicitly export attribute "foo"`). But grepping every actual caller of `app.db.repo` in this codebase shows **100% of callers use `from app.db import repo` (the module object itself)**, not `from app.db.repo import some_function`. A full strict mypy run over all of `app/` (which includes every one of these callers) produced **zero** `attr-defined`/reexport errors tied to the repo facade — confirmed by grepping the actual error output for `attr-defined` and finding all 9 hits are unrelated (federal_withholding, gateway, delivery, clarification, validate).
**How to avoid:** Don't pre-emptively spend a task converting the facade's imports to `from x import y as y` or building an `__all__` list. Run mypy first; if zero reexport errors appear (as this session's evidence strongly suggests), skip this work entirely and note it as verified-unneeded in the phase's execution notes. If a future caller pattern changes (some code starts doing `from app.db.repo import get_connection`, which one test file's docstring shows *does* exist as a pattern — `tests/test_bound01_private_imports.py:201`), only fix the specific module that trips it.
**Warning signs:** If the plan allocates a dedicated task/wave to "fix `no_implicit_reexport` across the repo facade" without first running `uv run mypy` to confirm the error actually exists, that task is very likely unnecessary busywork based on a discretion note, not a confirmed error.

### Pitfall 2: `eval/run_eval.py`'s `--record` path imports a name that doesn't exist — a real, currently-undetected bug
**What goes wrong:** `eval/run_eval.py:724` does `from app.llm.client import llm_client`, but `app/llm/client.py` has no module-level `llm_client` attribute — every other caller in the codebase (`app/pipeline/suggest.py`, `compose_email.py`, `extract.py`) imports the pattern as `import app.llm.client as llm_client` (the module object itself, passed as a duck-typed `llm=` parameter to `extract()`/etc.), never `from app.llm.client import llm_client`.
**Why it happens:** This code path (`_record_extraction()`) is only invoked when `--record` is passed AND `_require_live_llm()` passes — i.e., only against real DeepSeek/Kimi API keys, a path the hermetic CI test suite structurally never exercises. mypy strict mode catches it immediately (`attr-defined` on the import) precisely because it doesn't need to execute the code to know the attribute doesn't exist.
**How to avoid:** Per D-08, this needs a standalone test-first commit — not folded into an annotation-only commit. A reasonable test: import `eval.run_eval` and directly assert `_record_extraction` is well-formed (e.g., a targeted unit test around the import statement, or simply fixing the import to `import app.llm.client as llm_client` and letting the existing `--record`-path smoke test, if any exists, or a new minimal test cover it). Flag this to the user/planner explicitly — it is a genuine, if currently low-blast-radius (manual `--record` runs only), bug this phase surfaces.
**Warning signs:** Any `attr-defined` error on an import statement (not a runtime attribute access) is almost always a real bug, not a type-narrowing nuance — these should be triaged first and separately from the bulk annotation work.

### Pitfall 3: `app/email/gateway.py` accesses `resend.ReceivedEmail` fields as attributes, but it's a `TypedDict`
**What goes wrong:** `parse_inbound()` (the real, non-fixture inbound-webhook parsing path) does `email_obj.headers`, `email_obj.message_id`, `email_obj.text` after calling `resend.EmailsReceiving.get(email_id)`. `resend`'s own shipped types (confirmed by reading `resend/emails/_received_email.py` directly, package ships `py.typed`) define these as `TypedDict` fields, meaning the correct access is `email_obj["headers"]`, `email_obj["message_id"]`, `email_obj["text"]` — attribute access on a `TypedDict` fails both at the type level and, depending on what `resend.EmailsReceiving.get` actually returns at runtime (a real `dict` vs. some other wrapper), may fail at runtime too.
**Why it happens:** `tests/test_gateway.py:507-508` only asserts `hasattr(resend, "EmailsReceiving")` and `hasattr(resend.EmailsReceiving, "get")` — i.e., that the *function* exists, never that the *returned shape* matches how `parse_inbound` reads it. The hermetic test suite exercises `parse_inbound` only via a stubbed/fixture path (`test_parse_inbound_canonical_fixture_still_works`), never the real `resend.EmailsReceiving.get(...)` → attribute-access chain. This is exactly the kind of "fixture-vs-reality gap" this project has hit before (see MEMORY.md's "Live-gate dateless-email bug").
**How to avoid:** Per D-08, verify against the live `resend` SDK's actual runtime return type (not just its declared `TypedDict`, in case the SDK actually returns an object with both dict and attribute access, e.g., via `__getattr__` shims) before deciding whether this is a real bug or a false positive from stub-only formalization. If confirmed real, fix with a test-first commit (mock `resend.EmailsReceiving.get` to return the SDK's documented `TypedDict` shape, assert `parse_inbound` reads it correctly) separated from annotation-only commits, exactly as Pitfall 2.
**Warning signs:** Any `attr-defined` error where the receiving type is a third-party `TypedDict` (not a project-owned `dict[str, Any]`) is worth a five-minute check against that package's actual source before assuming it's just a missing-annotation problem.

### Pitfall 4: `# type: ignore` for the dynamic-exception-attribute pattern in `delivery.py`
**What goes wrong:** `app/pipeline/delivery.py`'s WR-04 pattern does `exc.payroll_roster = roster` inside `except Exception as exc:` — attaching a debugging attribute to an arbitrary exception instance before re-raising. mypy strict flags `"Exception" has no attribute "payroll_roster"` because base `Exception` genuinely has no such field.
**Why it happens:** This is a deliberate, already-`contextlib.suppress(Exception)`-guarded best-effort pattern (comment explicitly says "Attribute assignment is best-effort... must never mask the real delivery failure"), not a bug — it's dynamic monkey-patching of an exception object for the caller's scrub boundary.
**How to avoid:** This is exactly D-09's sanctioned case for `# type: ignore[attr-defined]` with a reason comment (e.g., `# type: ignore[attr-defined]  # WR-04: best-effort debug attribute on an arbitrary exception, suppressed if it fails`) — do not attempt to "properly type" this by subclassing `Exception` or using `setattr` tricks that would change runtime behavior of a money-path error-handling seam.
**Warning signs:** If a task tries to eliminate this with a structural change (e.g., wrapping the roster in a custom exception subtype), check it doesn't change what `except Exception as exc` catches or how the outer caller reads `exc.payroll_roster` — this is exactly the kind of "mechanical diff hiding a behavior change" D-08 exists to prevent.

## Code Examples

### Full census commands used (reproducible by the planner/executor)
```bash
# Source: this session, run directly against the real repo, mypy 2.2.0.
uv add --dev mypy                      # temporary; removed after research (uv remove --dev mypy)

# Strict census, app/ only:
uv run mypy --strict --config-file <(cat <<'EOF'
[mypy]
python_version = 3.12
strict = true
plugins = pydantic.mypy
EOF
) app
# => Found 170 errors in 30 files (checked 52 source files)

# Error code breakdown (app/):
#   80 no-untyped-def   51 type-arg   12 arg-type   9 attr-defined
#    5 no-any-return     4 import-untyped   3 union-attr   2 no-untyped-call
#    1 var-annotated     1 operator    1 call-overload   1 assignment

# tests/ with the D-02 relaxed override still surfaces real errors:
# => Found 521 errors in 72 files (checked 56 source files)
#   141 type-arg   139 no-untyped-call   83 no-untyped-def   47 index
#    38 attr-defined   23 arg-type   17 no-any-return   13 func-returns-value
#     4 var-annotated  4 union-attr   4 import-untyped   3 operator
#     2 call-arg   1 misc   1 call-overload   1 assignment
```

### Checking third-party `py.typed` presence directly (used to confirm D-03's scope)
```python
# Source: this session, run against the real .venv for every runtime dependency.
import importlib, os
for pkg in ["psycopg", "psycopg_pool", "openai", "httpx", "jinja2", "fastapi",
            "pydantic", "pydantic_settings", "resend", "multipart", "uvicorn", "reportlab"]:
    m = importlib.import_module(pkg)
    d = os.path.dirname(m.__file__)
    print(pkg, "py.typed" if os.path.isfile(os.path.join(d, "py.typed")) else "NO py.typed")
# Result: every package has py.typed EXCEPT reportlab (matches D-03) and
# python-multipart/"multipart" (but it is never imported by name anywhere in
# app/eval/scripts/tests — confirmed by grep — so it needs no override at all).
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| N/A — this is the first mypy adoption in the repo | mypy 2.2.0, `strict = true` + pydantic plugin | mypy 2.2.0 released 2026-07-08 (two days before this research); no prior mypy config existed in `pyproject.toml` or `uv.lock` (confirmed by grep) | Baseline; no migration from an older mypy version is needed. |

**Deprecated/outdated:** Nothing to deprecate — greenfield mypy adoption on top of an existing, already-partially-annotated codebase (CONTEXT.md's code_context notes `app/` is 107/175 defs return-annotated already).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `no_implicit_reexport` will not fire on the real `app/db/repo/` facade in the actual planned config (only tested against a temporary strict-only config without the full `files=[...]` + overrides combination) | Common Pitfalls #1 | Low — if wrong, the fix is well-understood (`__all__` or `from x import y as y`) and CONTEXT.md already anticipated it as a discretion item; worst case is one extra small task, not a design problem. |
| A2 | `eval/run_eval.py`'s `llm_client` import and `gateway.py`'s attribute-vs-TypedDict access are both genuinely reachable bugs (not, e.g., a `__getattr__`/duck-typing shim in `resend` that makes attribute access work at runtime despite the `TypedDict` declaration) | Common Pitfalls #2, #3 | Medium for #3 specifically — resend's TypedDict could theoretically be paired with a runtime object that also supports attribute access (some SDKs do this); the planner should have a task verify actual runtime behavior (e.g., a quick live/recorded fixture check) before assuming the fix is purely "switch to bracket access," in case the real fix is narrower (e.g., only the type annotation needs a `cast()`, not the runtime code). #2 is HIGH confidence (no ambiguity — the name genuinely does not exist in the module). |

**None of the Standard Stack, Package Legitimacy, or CI wiring claims are flagged `[ASSUMED]`** — all were verified directly by running the real tools in this session.

## Open Questions

1. **Exact final error count once the full committed config (with both overrides + `files=[...]`) is in place**
   - What we know: Directory-by-directory strict censuses (170 app-only, 163 eval+scripts, 521 tests-relaxed) were run with slightly different config shapes (isolated per-directory rather than the single combined `files=[...]` run the plan will actually ship).
   - What's unclear: A single combined run may surface a handful of additional cross-module errors not visible when directories are checked in isolation (e.g., a type mismatch only detectable when `eval/run_eval.py` and `app/pipeline/extract.py` are checked together in the same pass).
   - Recommendation: The plan's first task should be running the actual committed config as a discovery/inventory step before wave-sizing the fix work, rather than trusting this research's directory-by-directory numbers as exact. Treat 170+163+521 (net of overlap) as a strong upper-bound estimate, not a guarantee.

2. **Whether `gateway.py`'s TypedDict-vs-attribute mismatch is a live bug or dead code on an unused path**
   - What we know: The mismatch is real at the type level and the fixture-only tests never exercise it.
   - What's unclear: Whether `resend`'s actual runtime object (as opposed to its declared type) supports both dict and attribute access (some SDKs wrap TypedDicts in attrs-like proxy objects for ergonomics) — this can only be confirmed by reading `resend`'s runtime implementation (not just its `.pyi`/type declarations) or by a live call.
   - Recommendation: Spend five minutes reading `resend/emails/_receiving.py`'s actual `get()` implementation (not just the type file) before writing the D-08 test — if it returns a plain `dict`, the fix is straightforward bracket access; if it returns some proxy object, the type-level fix may be a `cast()` at the boundary instead of a runtime behavior change.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | All dev commands (`uv run`, `uv add --dev`) | ✓ | (already in use throughout repo) | — |
| mypy | TYPE-01/02/03 | ✓ (installed + verified this session, then removed) | 2.2.0 (current PyPI release) | — |
| pydantic mypy plugin | TYPE-01 (pydantic-aware checking) | ✓ (ships inside already-pinned `pydantic==2.13.4`) | 2.13.4 | — |
| GitHub Actions (`astral-sh/setup-uv`, `actions/checkout`) | TYPE-03 CI job | ✓ (already used by `lint`/`test` jobs, same pinned SHAs reusable) | v5.4.2 / v4.3.1 (already pinned in `ci.yml`) | — |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** none — everything needed is either already present or trivially installable via `uv add --dev mypy`.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (via `uv run pytest -q`), already configured in `pyproject.toml` `[tool.pytest.ini_options]` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) |
| Quick run command | `uv run pytest -q -m "not integration and not live_llm"` (existing hermetic-only convention; no DATABASE_URL/live keys needed) |
| Full suite command | `uv run pytest -q` (665 tests collected, confirmed this session) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TYPE-01 | `uv run mypy` exits 0 over `app/` | tool-run (not a pytest test) | `uv run mypy` (scoped via `files=` config) | N/A — verified by running the tool directly, not a pytest assertion |
| TYPE-02 | `uv run mypy` exits 0 over `eval/`, `scripts/`, `tests/` too | tool-run | `uv run mypy` (same command — scope is config-driven, not per-directory) | N/A |
| TYPE-03 | CI fails on a type error | integration (CI-level, red-proofed) | Push a throwaway branch with an injected error, confirm the `typecheck` job goes red; delete branch (D-07) | N/A — no pytest file; this is a CI red-proof exercise identical to Phase 12's D-14 pattern |
| D-08 (bug fixes surfaced by mypy) | Each real bug gets a failing-test-first regression test | unit | New `tests/test_*.py::test_*` per bug, e.g., a test asserting `eval.run_eval`'s live-record import path is well-formed, and a test asserting `gateway.parse_inbound` correctly reads a `resend.ReceivedEmail`-shaped object | ❌ — both need to be written as part of the D-08 fix commits; see Open Question 2 for the gateway case specifically |

### Sampling Rate
- **Per task commit:** `uv run mypy` (scoped to whatever directory/module the task touched, using the committed config) + `uv run pytest -q -m "not integration and not live_llm"` to confirm no behavior regression.
- **Per wave merge:** `uv run mypy` (full scope) + `uv run pytest -q` (full suite, 665 tests).
- **Phase gate:** Full `uv run mypy` clean + full `uv run pytest -q` green + the CI red-proof (D-07) captured in VERIFICATION.md, before `/gsd-verify-work`.

### Wave 0 Gaps
- [ ] No mypy config exists yet — `[tool.mypy]` + both `[[tool.mypy.overrides]]` blocks must be authored as the very first commit (before any annotation work), so every subsequent commit can be checked against the real, final config rather than an ad hoc one.
- [ ] Two new regression tests needed for the D-08 bugs found in this research (see Phase Requirements → Test Map row above) — not yet written; these are net-new test files/cases, not gaps in existing infrastructure.
- [ ] Framework install: `uv add --dev mypy` — not yet applied to the real `pyproject.toml`/`uv.lock` (this research session added and then removed it to keep the repo clean; the plan's first task should re-add it for real).

## Security Domain

This phase is a static-analysis/CI-tooling change with no new attack surface — no new endpoints, no new data flows, no new auth/session/crypto code. Per the phase's own scope ("behavior-neutral by default: the phase's diff is annotations, narrowing, and config"), the ASVS categories below are not newly implicated by this phase itself, though the D-08 bug fixes (gateway.py's TypedDict mismatch) touch inbound-email-parsing code that is itself security-relevant (webhook signature verification lives in the same file, per `resend.Webhooks.verify` at gateway.py's line ~87 — confirmed present but untouched by the bug at hand).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Not touched by this phase. |
| V3 Session Management | no | Not touched by this phase. |
| V4 Access Control | no | Not touched by this phase. |
| V5 Input Validation | indirectly | The D-08 gateway.py fix must not weaken `resend.Webhooks.verify` (webhook signature check) — the fix is scoped strictly to `parse_inbound`'s post-verification field access, and any executor task touching `gateway.py` should re-run `tests/test_gateway.py`'s existing signature-verification tests to confirm no incidental regression. |
| V6 Cryptography | no | Not touched by this phase (webhook signature verification is pre-existing, unmodified code). |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A type-annotation-only refactor accidentally changing exception-handling behavior in `delivery.py`'s WR-04 pattern (widening the `except` clause or changing what gets suppressed) | Tampering (money-path integrity) | D-09's sanctioned `# type: ignore[attr-defined]` with a reason comment (see Pitfall #4) — never restructure the `except Exception as exc: ... contextlib.suppress(Exception): exc.payroll_roster = roster` shape to "properly type" it. |
| Fixing the gateway.py TypedDict mismatch in a way that silently changes what fields are read from a real inbound webhook payload (e.g., using `.get()` with a wrong default instead of the exact expected key) | Tampering / Information Disclosure (misparsed inbound email could misroute or drop fields silently) | The D-08 fix must be test-first with a fixture that mirrors the real `resend.EmailsReceiving.get` shape (see `tests/conftest.py:1144`'s existing "Mirrors the shape returned by resend.EmailsReceiving.get" comment/fixture as the base to extend), not a guess at the correct keys. |

## Sources

### Primary (HIGH confidence)
- Direct tool execution, this session: `uv add --dev mypy` (resolved mypy 2.2.0), `uv run mypy --strict`/`--config-file` against `app/`, `eval/`, `scripts/`, `tests/` with and without the pydantic plugin and with/without the D-02 relaxed override; `uv remove --dev mypy` (confirmed clean revert via `git diff`).
- Direct source inspection, this session: `app/db/repo/__init__.py`, `app/pipeline/federal_withholding.py`, `app/pipeline/tax_tables_2026.py`, `app/email/gateway.py`, `eval/run_eval.py`, `app/llm/client.py`, `resend/emails/_received_email.py` (installed package source), `.github/workflows/ci.yml`, `pyproject.toml`.
- Minimal isolated repro, this session: two-file mypy package/`__init__.py` re-export test confirming `no_implicit_reexport`'s actual trigger condition.
- `py.typed` presence check, this session: direct Python introspection of every runtime dependency's installed package directory.

### Secondary (MEDIUM confidence)
- WebSearch: mypy 2.2.0 release date and headline features (PEP 728 closed TypedDicts, PEP 696 type-var defaults) — cross-referenced against the version actually resolved by `uv add --dev mypy` in this session (matches).
- WebSearch: pydantic mypy plugin config keys (`init_forbid_extra`, `warn_untyped_fields`, etc.) and general `no_implicit_reexport` behavior discussion (GitHub issues python/mypy#10198, #11706) — used to interpret and then directly verify (not just trust) the repo-facade reexport question.

### Tertiary (LOW confidence)
None — every substantive claim in this document was either verified by direct tool execution against the real repository in this session, or is a direct quote/copy from CONTEXT.md/REQUIREMENTS.md.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — mypy version and pydantic-plugin availability confirmed by direct installation and execution, not inferred.
- Architecture: HIGH — the CI/config shape is a direct, verified extension of Phase 12's existing `lint` job; no novel architecture introduced.
- Pitfalls: HIGH for the mechanical error categories (directly counted); MEDIUM for the two suspected real bugs (Pitfalls #2/#3) pending the Open Questions' five-minute runtime-behavior confirmation, which the planner should schedule as an early task, not skip.

**Research date:** 2026-07-10
**Valid until:** 2026-08-09 (30 days — mypy releases roughly monthly; the underlying codebase is also actively changing across Phase 13/14/15, so re-verify error counts if more than a couple weeks pass before execution starts).
