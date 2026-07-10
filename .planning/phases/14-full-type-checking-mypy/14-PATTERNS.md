# Phase 14: Full Type-Checking (mypy) - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 6 config/CI touch points + 4 flagged bug/annotation hotspots (representative of ~150 files across `app/`, `eval/`, `scripts/`, `tests/` that receive mechanical annotation edits)
**Analogs found:** 6 / 6 for the concrete, non-mechanical work items. The remaining ~150 files receiving pure annotation additions do not need per-file analogs — they follow the "Shared Patterns" section below.

<domain_note>
This phase is unusual for pattern-mapping: it is not "new files copy old files" but "existing files gain annotations following the codebase's own established idioms, plus two new config files' worth of content land in two already-existing files (`pyproject.toml`, `ci.yml`)." The analogs below are therefore mostly **the file's own existing conventions** (config block siblings, sibling CI jobs) rather than a different file entirely. Per D-08, two genuine bugs surfaced by the research are also mapped to their exact fix pattern.
</domain_note>

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|---------------|
| `pyproject.toml` (`[tool.mypy]` + 2 overrides block, new) | config | transform (static config → tool behavior) | `pyproject.toml`'s own `[tool.ruff]` / `[tool.ruff.lint]` blocks (same file) | exact — same file, same "one more static-analysis tool config block" role |
| `.github/workflows/ci.yml` (`typecheck` job, new) | config/CI | event-driven (push-triggered pipeline) | `.github/workflows/ci.yml`'s existing `lint` job (same file) | exact — explicitly named as the copy-paste template in CONTEXT.md D-05 |
| `app/pipeline/federal_withholding.py` (`_find_bracket` return-type fix) | utility (pure function) | transform | `app/pipeline/tax_tables_2026.py`'s `BracketRow(NamedTuple)` — the type already exists one file away | exact — the fix is importing and using an existing sibling type, not inventing one |
| `eval/run_eval.py` (`llm_client` import fix, D-08 bug) | service (eval harness) | request-response (LLM call) | `app/pipeline/extract.py:26`, `app/pipeline/suggest.py:31`, `app/pipeline/compose_email.py:21` (all three: `from app.llm import client as llm_client`) | exact — three existing call sites show the correct import shape; `run_eval.py` is the one outlier to fix |
| `app/email/gateway.py` (`parse_inbound` TypedDict access, possible D-08 bug) | service (email gateway adapter) | request-response | `app/email/gateway.py`'s own `verify()` function (same file, lines ~74-104) — already uses dict-subscript access on a `VerifyWebhookOptions` TypedDict pattern | role-match — same file already demonstrates correct TypedDict-subscript style right next to the buggy attribute-access style |
| `app/pipeline/delivery.py` (`exc.payroll_roster = roster`, D-09 sanctioned ignore) | service (delivery/error-scrub) | event-driven (best-effort exception annotation) | No prior `# type: ignore` exists in the repo (first one) — analog is the existing WR-04 comment convention at the same line, which already documents *why* the dynamic attribute assignment is safe | n/a (first-of-kind) — reuse the existing WR-04 comment, append the ignore per D-09 |
| `app/db/repo/__init__.py` (`no_implicit_reexport` — verify-first, likely no-op) | facade/module | re-export | Same file's existing `__all__` list (already present, lines 77-135) | exact — the facade already uses the `__all__` style; **research Pitfall 1 says this is very likely already sufficient and needs zero further change** — confirm via a real `uv run mypy` pass before allocating any task here |

## Pattern Assignments

### `pyproject.toml` — `[tool.mypy]` config block

**Analog:** the file's own `[tool.ruff]` / `[tool.ruff.lint]` blocks (lines 33-46 of the current file)

**Existing sibling-config pattern** (`pyproject.toml` lines 33-46):
```toml
[tool.ruff]
# D-02: 100 is the measured tradeoff — 160 lines exceed 100 vs 1,297 that exceed the 88 default.
line-length = 100
# Explicit pin matching .python-version / the python:3.12-slim Docker target (CLAUDE.md),
# even though ruff can infer this from requires-python — keeps the target version legible
# directly in the ruff config block.
target-version = "py312"

[tool.ruff.lint]
# D-01: curated production ruleset — pycodestyle errors, pyflakes, isort import-sorting,
# flake8-bugbear, pyupgrade, flake8-simplify. Not the bare defaults.
# D-03: no ignore list and no per-file-ignores table — every violation gets fixed or an
# individually-justified inline `# noqa: <CODE> — <reason>`.
select = ["E", "F", "I", "B", "UP", "SIM"]
```

**Convention to copy:** every config decision gets an inline comment citing the Decision ID (`D-XX`) that drove it — exactly as `[tool.ruff]` does. The new `[tool.mypy]` block (and its two `[[tool.mypy.overrides]]` blocks) should cite D-01/D-02/D-03/D-06 the same way. RESEARCH.md's Pattern 1 (Code Examples section) already gives the exact TOML to drop in — treat it as pre-vetted, not a fresh design:

```toml
[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
files = ["app", "eval", "scripts", "tests"]

[[tool.mypy.overrides]]
module = "tests.*"
check_untyped_defs = true
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_decorators = false

[[tool.mypy.overrides]]
module = "reportlab.*"
ignore_missing_imports = true
```

**Dev dependency addition** (mirrors how `pytest`/`ruff` already sit in `[dependency-groups].dev`, `pyproject.toml` lines 23-27):
```toml
[dependency-groups]
dev = [
    "matplotlib>=3.11.0",
    "numpy>=1.26.0",
    "pytest",
    "ruff",
]
```
Add `mypy` here (via `uv add --dev mypy`, never hand-edited) — same list, same alphabetically-loose style already used.

---

### `.github/workflows/ci.yml` — `typecheck` job

**Analog:** the existing `lint` job (same file, lines 17-33)

**Exact copy-paste template** (`.github/workflows/ci.yml` lines 17-33):
```yaml
  lint:
    name: "Lint (ruff check)"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1 (v4)

      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86  # v5.4.2 (v5)
        with:
          python-version: "3.12"

      - name: Install deps (all groups)
        # --locked asserts uv.lock matches pyproject.toml instead of silently
        # re-resolving -- a stale lockfile fails the job rather than merging green.
        run: uv sync --locked

      - name: Run ruff check
        run: uv run ruff check .
```

**New job (D-05/D-06):** identical shape, only the `name:` and final `run:` step change:
```yaml
  typecheck:
    name: "Type check (mypy --strict)"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4.3.1 (v4)

      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86  # v5.4.2 (v5)
        with:
          python-version: "3.12"

      - name: Install deps (all groups)
        run: uv sync --locked

      - name: Run mypy
        run: uv run mypy
```

Note: **pinned action SHAs are the house style** — reuse the exact same `checkout@34e114...` / `setup-uv@d4b2f3b6...` pins already in the file; do not re-pin to a different SHA. `files = [...]` already lives in `pyproject.toml`, so the CI step is bare `uv run mypy` per D-06 (byte-for-byte local/CI parity) — do not pass `app eval scripts tests` as CLI args here, that would create two sources of scope truth.

**Job-level metadata to preserve unchanged:** the file-level `permissions: contents: read` and `concurrency: group: ci-${{ github.ref }}` blocks already apply repo-wide to every job — no per-job changes needed there.

---

### `app/pipeline/federal_withholding.py` — `_find_bracket` return-type fix (mechanical, zero-risk)

**Analog:** `app/pipeline/tax_tables_2026.py`'s own `BracketRow` NamedTuple (lines 24-38), already imported into the withholding engine's neighborhood

**Current buggy-under-strict shape** (`app/pipeline/federal_withholding.py` lines 45-60):
```python
def _find_bracket(annual_wage: Decimal, brackets: list) -> object:
    """Find the matching Pub 15-T bracket row via linear scan (O(n), 8 rows max).
    ...
    """
    for row in reversed(brackets):
        if annual_wage >= row.lower:
            return row
    return brackets[0]
```

**Sibling type already defined** (`app/pipeline/tax_tables_2026.py` lines 24-38):
```python
class BracketRow(NamedTuple):
    """One row from the IRS Pub 15-T Worksheet 1A percentage-method table.
    ...
    """
    lower: Decimal
    upper: Decimal | None
    base: Decimal
    rate: Decimal
```

**Fix pattern (annotation-only, no behavior change):**
```python
from app.pipeline.tax_tables_2026 import BracketRow, ...  # add BracketRow to the existing import

def _find_bracket(annual_wage: Decimal, brackets: list[BracketRow]) -> BracketRow:
    ...
```
This is a pure annotation commit — no logic changes. Bundle with the 3 call sites (`row.lower`, `row.rate`, `row.base` in `federal_withholding_2026`, lines 139-141) which will stop erroring once the return type is concrete.

---

### `eval/run_eval.py` — `llm_client` import fix (D-08 real bug, standalone commit)

**Analog:** `app/pipeline/extract.py:26`, `app/pipeline/suggest.py:31`, `app/pipeline/compose_email.py:21` — three existing, correct call sites

**Correct pattern used everywhere else in the codebase:**
```python
# app/pipeline/extract.py:26
from app.llm import client as llm_client
...
# app/pipeline/extract.py:37 (passed as a duck-typed llm= param)
def extract(..., llm=llm_client, ...):
```

**Current bug** (`eval/run_eval.py:724`):
```python
from app.llm.client import llm_client  # noqa: PLC0415
```
`app/llm/client.py` has no module-level `llm_client` attribute — this import raises `ImportError`/`attr-defined` at runtime, on the `--record` path only (never exercised by hermetic CI).

**Fix (D-08 test-first, standalone commit — NOT bundled with annotation work):**
```python
from app.llm import client as llm_client  # noqa: PLC0415
```
Write a regression test first (e.g., a unit test that imports `eval.run_eval` and directly exercises/asserts the import binds correctly, or a targeted test around `_record_extraction`), confirm it fails against the current code, then apply this one-line fix in its own commit per D-08.

---

### `app/email/gateway.py` — `parse_inbound` TypedDict access (possible D-08 bug, verify runtime shape first)

**Analog (same file):** `verify()` at lines 74-104 already reads a TypedDict-shaped payload correctly via dict-subscript style; `parse_inbound` at line 152/163/169 uses attribute access on what `resend`'s installed types declare as a `TypedDict`.

**Correct existing style in the same file** (`app/email/gateway.py`, `verify()`):
```python
resend.Webhooks.verify(
    ...,
    {
        "headers": {
            "id": headers.get("svix-id", ""),
            "timestamp": headers.get("svix-timestamp", ""),
            "signature": headers.get("svix-signature", ""),
        },
        ...
    },
)
```

**Suspect pattern to fix** (`app/email/gateway.py` lines 148-169):
```python
email_obj = resend.EmailsReceiving.get(email_id)
headers_lower = {k.lower(): v for k, v in email_obj.headers.items()}  # attribute access
...
message_id=email_obj.message_id or inner.get("message_id", ""),
...
body_text=email_obj.text or "",
```

**Before fixing:** per research Open Question 2 / Pitfall 3, read `resend`'s actual `EmailsReceiving.get()` runtime implementation (not just its `.pyi`) to confirm whether it returns a plain `dict` (bracket access is the correct fix) or an attrs-like proxy (a `cast()` at the boundary may be more correct than changing access style). The base fixture to extend is `tests/conftest.py:1144`'s existing "Mirrors the shape returned by resend.EmailsReceiving.get" comment/fixture — do not invent a new fixture shape from scratch.

**If confirmed a real dict-only shape, fix pattern:**
```python
email_obj = resend.EmailsReceiving.get(email_id)
headers_lower = {k.lower(): v for k, v in email_obj["headers"].items()}
...
message_id=email_obj["message_id"] or inner.get("message_id", ""),
...
body_text=email_obj["text"] or "",
```
This is a D-08 test-first fix if genuinely reachable — do not bundle with annotation-only commits. Per the Security Domain note in RESEARCH.md, re-run `tests/test_gateway.py`'s existing signature-verification tests after this change to confirm no incidental regression to `verify()`.

---

### `app/pipeline/delivery.py` — `# type: ignore` for dynamic exception attribute (D-09 sanctioned case)

**Analog:** the file's own existing WR-04 comment at the same line (already documents *why* this is safe) — this is the first `# type: ignore` in the repo, so there is no prior in-repo ignore-comment style to match; follow D-09's stated format exactly.

**Current code** (`app/pipeline/delivery.py` lines 225-231):
```python
except Exception as exc:
    ...
    with contextlib.suppress(Exception):
        exc.payroll_roster = roster
```

**Fix pattern (D-09 — add ignore + reason, do not restructure):**
```python
except Exception as exc:
    ...
    with contextlib.suppress(Exception):
        exc.payroll_roster = roster  # type: ignore[attr-defined]  # WR-04: best-effort debug
        # attribute on an arbitrary exception, suppressed if assignment fails; must never
        # mask the real delivery failure — see WR-04 comment above for full rationale.
```
**Do not** subclass `Exception` or change what `except Exception as exc:` catches — that would be exactly the "mechanical diff hiding a behavior change" D-08/D-09 exist to prevent (see RESEARCH.md Pitfall 4 and Security Domain STRIDE row).

---

### `app/db/repo/__init__.py` — `no_implicit_reexport` (verify-first, likely zero work)

**Analog:** the file's own existing `__all__` list (lines 77-135), already present and already the exact remediation style `no_implicit_reexport` would require if it fired.

**Current state (already correct if the error fires at all):**
```python
__all__ = [
    "get_connection",
    "_conn_ctx",
    "_nulltx",
    "bind_demo_business",
    ...
]
```

**Action:** Per RESEARCH.md Pitfall 1, run `uv run mypy` against the real committed config FIRST. Grep every caller of `app.db.repo` in the codebase — confirmed this session that 100% of callers use `from app.db import repo` (the module object), never `from app.db.repo import some_function`. If the real mypy run confirms zero `attr-defined`/reexport errors tied to this facade (as strongly expected), **do not allocate a task to this file** — note it as verified-unneeded in execution notes instead of pre-emptively touching it.

---

## Shared Patterns

### Mechanical annotation completion (the ~75% bulk of the work: `no-untyped-def` + `type-arg`)
**Source:** the codebase's own already-annotated functions are the template — e.g. `app/db/repo/runs.py`'s fully-annotated functions:
```python
def insert_inbound_email(...) -> tuple[uuid.UUID | None, bool]: ...
def find_business_by_sender(from_addr: str, conn=None) -> uuid.UUID | None: ...
def sweep_stranded_runs(threshold_seconds: int, conn=None) -> list[uuid.UUID]: ...
_ACCENT_CLASS_MAP: dict[str, str] = _build_accent_class_map()
```
**Apply to:** every function currently missing a param/return annotation across `app/`, `eval/`, `scripts/`, and (where the relaxed override still requires it) `tests/`. Two concrete completion patterns recur across the repo:
1. **`conn=None` params** (dozens of occurrences in `app/db/repo/*.py`) → annotate as `conn: psycopg.Connection | None = None`, matching `app/db/supabase.py`'s own `psycopg.Connection` usage (`get_connection() -> Generator[psycopg.Connection, None, None]`).
2. **Bare `dict`/`list` returns** (e.g. `app/db/repo/runs.py:246 load_run(...) -> dict | None`) → add type args: `dict[str, Any] | None`, importing `Any` the same way `app/db/repo/runs.py:8` already does (`from typing import Any`) — this is D-10's "dynamic edge" sanctioned case (DB row dicts at the psycopg boundary).

### Pydantic model typing (already-idiomatic, extend the same way)
**Source:** `app/models/contracts.py` (lines 1-80) — every model already uses `from __future__ import annotations`, `Decimal | None` unions, `Literal`, `ConfigDict(extra="forbid")`.
**Apply to:** any new/edited Pydantic-touching code — do not introduce a different style (e.g. `Optional[X]` instead of `X | None`, or `typing.Dict` instead of `dict`) anywhere; ruff's `UP` (pyupgrade) rules already enforce this and mypy's pydantic plugin expects the modern-union style.

### reportlab boundary (`Any`/ignore scope, D-03/D-10)
**Source:** `app/pipeline/pdf.py` (lines 1-30) — imports `from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle` with no existing type-ignore comments (reportlab has none currently because mypy has never run).
**Apply to:** `app/pipeline/pdf.py` and `app/pipeline/delivery.py` (the only 2 runtime files importing reportlab, per D-03) — the scoped `[[tool.mypy.overrides]] module = "reportlab.*"` config handles these; no per-line ignores needed inside `pdf.py` itself, since the override silences the whole module's missing stubs. Function return types like `_build_header_band(...) -> Table` already exist and should be trusted (Table is reportlab's own class, resolved fine once `ignore_missing_imports` is scoped correctly).

### `from __future__ import annotations` (already the house style)
**Source:** every read file in this research (`federal_withholding.py`, `tax_tables_2026.py`, `pdf.py`, `webhook.py`, `_shared.py`, `contracts.py`) opens with `from __future__ import annotations` immediately after the module docstring.
**Apply to:** confirm this import is present in any file receiving new annotations (most already have it); do not add runtime `typing.get_type_hints()` calls or otherwise assume annotations are evaluated eagerly — the whole codebase relies on PEP 563 lazy evaluation.

### Decision-ID comment convention (config files)
**Source:** `pyproject.toml`'s `[tool.ruff]` block, every line justified by a `D-XX` comment tied to a phase decision.
**Apply to:** the new `[tool.mypy]` block and both `[[tool.mypy.overrides]]` blocks — cite D-01 (strict scope), D-02 (tests override), D-03 (reportlab override), D-06 (files= scope) inline, exactly as the ruff block cites D-01/D-02/D-03 for its own decisions.

## No Analog Found

None — every file/config touch point identified in CONTEXT.md and RESEARCH.md has a concrete in-repo analog (either a sibling config block, a sibling CI job, a sibling call-site convention, or the file's own pre-existing correct pattern a few lines away). The bulk of the phase's diff (mechanical annotations across ~150 files) is explicitly "follow the codebase's own existing idiom" rather than "port a pattern from elsewhere" — captured in Shared Patterns above rather than as 150 individual per-file rows, per the early-stopping guidance (3-5 strong analogs, not exhaustive enumeration).

## Metadata

**Analog search scope:** `pyproject.toml`, `.github/workflows/ci.yml`, `app/pipeline/federal_withholding.py`, `app/pipeline/tax_tables_2026.py`, `app/db/repo/__init__.py`, `app/db/repo/_shared.py`, `app/db/repo/runs.py`, `app/db/supabase.py`, `app/email/gateway.py`, `eval/run_eval.py`, `app/pipeline/delivery.py`, `app/pipeline/pdf.py`, `app/pipeline/extract.py`, `app/pipeline/suggest.py`, `app/pipeline/compose_email.py`, `app/models/contracts.py`, `app/routes/webhook.py`, `app/config.py`.
**Files scanned:** 18 read/grepped directly this session (full file listing of `app/`, `eval/`, `scripts/` also enumerated for completeness — 52 + 3 + 3 files).
**Pattern extraction date:** 2026-07-10
