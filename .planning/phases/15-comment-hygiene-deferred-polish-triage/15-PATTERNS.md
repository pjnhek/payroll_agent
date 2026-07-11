# Phase 15: Comment Hygiene & Deferred-Polish Triage - Pattern Map

**Mapped:** 2026-07-10
**Files analyzed:** 6 new/modified code surfaces (plus the ~100-file comment-only sweep, which creates no new files)
**Analogs found:** 6 / 6

Note: the bulk of this phase (COMM-01/02/03 sweep) is text-only edits to existing files and needs no analog — RESEARCH.md's inventory + D-01..D-06 rubric govern it. Pattern mapping below covers the files where NEW code or NEW tests are written.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/test_comment_provenance_guard.py` (new) | test (static source scanner) | batch/file-I/O | `tests/test_bound01_private_imports.py` | exact (D-07 names it) |
| WR-01 threading regression test (new, or extend `tests/test_threading.py`) | test (hermetic pipeline regression) | event-driven (crash→retrigger→send) | `tests/test_retrigger_epoch.py` | exact |
| `app/routes/dashboard.py` (WR-05 fix, `eval_view`) | route/controller | file-I/O + request-response | itself — existing missing-file fallback branch, lines 112-123 | exact |
| WR-05 containment test (extend `tests/test_dashboard.py`) | test (route security regression) | request-response | `tests/test_dashboard.py::test_paystub_pdf_content_disposition_sanitized` (lines 380-429) | exact |
| `app/llm/client.py` (INFO-02 fix, retry prompt) | service (LLM client) | request-response | itself — retry loop lines 150-191 | exact |
| INFO-02 scrub test (extend `tests/test_llm_client.py`) | test (fake-client capture) | request-response | `tests/test_llm_client.py` FakeOpenAI harness + `test_invalid_then_valid_retries_exactly_once` (line 268) | exact |
| `eval/fixtures/10_multi_employee_coastal.json` (relabel) | config/data | batch | `eval/fixtures/05_*.json` (existing `"typo"` category fixture) | exact |

## Pattern Assignments

### `tests/test_comment_provenance_guard.py` (guard test, static scan)

**Analog:** `tests/test_bound01_private_imports.py` (576 lines) — D-07 mandates this precedent.

**Structure to copy** (the file's shape, verified by read):
1. Module docstring stating the invariant the guard enforces and naming BOTH entry points (spec-as-docstring style, lines 1-36 of the analog). Per COMM-03, the new guard's own docstring must be purpose+invariant prose with no ticket IDs.
2. Module-level constants (analog lines 38-45):
```python
from __future__ import annotations

import pathlib

SCAN_ROOTS = ["app", "eval", "scripts"]

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
```
**Scope difference from analog (call out in plan):** BOUND-01 deliberately excludes `tests/`; the COMM guard must INCLUDE `tests/` and the non-Python surfaces (`app/db/schema.sql`, `app/templates/*.html`, `app/static/*.css`, `eval/fixtures/*.md`) per D-05/D-09. Use glob patterns instead of the analog's `rglob("*.py")`.

3. Reusable pure `scan_*` function returning human-readable violation strings with `f"{path}:{lineno} ..."` format (analog `scan_tree_for_violations`, lines 330-357):
```python
def scan_tree_for_violations(scan_roots, root_parent) -> list[str]:
    violations: list[str] = []
    for root in scan_roots:
        if not root.is_dir():
            continue
        for py_file in sorted(root.rglob("*.py")):
            source = py_file.read_text(encoding="utf-8")
            ...
    return violations
```

4. **Two pytest entry points** — copy this dual-test pattern exactly (analog lines 360-430):
```python
def test_no_cross_module_private_imports() -> None:
    """The permanent CI gate: scans the LIVE app/, eval/, scripts/ trees..."""
    scan_roots = [REPO_ROOT / name for name in SCAN_ROOTS]
    violations = scan_tree_for_violations(scan_roots, REPO_ROOT)
    assert not violations, "BOUND-01 violation(s) found:\n" + "\n".join(violations)


def test_scanner_detects_synthetic_violation(tmp_path: pathlib.Path) -> None:
    """Prove the scanner's own detection logic against synthetic fixtures BEFORE
    trusting it as a permanent gate — covers every violation shape ... and every
    legitimate-pattern exemption ..."""
    pkgroot = tmp_path / "pkgroot"
    pkgroot.mkdir()
    (pkgroot / "module_a.py").write_text("_private_thing = 1\n", encoding="utf-8")
    ...
```
For the COMM guard the synthetic corpus = one tmp file per D-08 pattern (each must fire) + legit-prose lines ("fix the rounding", "this phase of parsing", `# noqa: BLE001`, `# type: ignore[attr-defined]`, requirement IDs like `CALC-03`) that must pass.

5. Self-exemption (D-09): skip the guard's own file, mirroring the analog's declared-exemption style (analog line 61 `_DECLARED_INTERNAL_PLUMBING_PACKAGE` — a named module constant with a comment explaining WHY, not an inline magic check). RESEARCH.md §Code Examples already sketches the regex table and walker; use it, tuned against the final tree.

---

### WR-01 threading regression test (crash → retrigger → outbound send)

**Analog:** `tests/test_retrigger_epoch.py` — the only existing test that drives the real retrigger/epoch seams hermetically.

**Imports/fixtures pattern** (analog lines 99-101, 111): tests take `monkeypatch, fake_repo, mock_llm` (conftest fixtures) and import the gateway module for the spy:
```python
def test_retrigger_sends_fresh_clarification_despite_stale_round0_sent_row(
    monkeypatch, fake_repo, mock_llm
):
    import app.email.gateway as gateway_mod
```

**Bare-object builders** (analog lines 48-97): module-local `_bare_roster()`, `_bare_inbound()`, `_bare_decision()`, `_bare_extracted(run_id)` helpers construct minimal contract objects. Copy/reuse these.

**Seed-state pattern** (analog lines 119-139): write run + email rows directly into `fake_repo.runs[str(run_id)]` / `fake_repo.outbound[str(run_id)]` dicts, including `message_id`, `round`, `epoch`, `send_state` keys.

**Real-seam + spy pattern** (analog lines 141-162) — this is the anti-vacuous-proof pattern (Pitfall 5 / Phase 10 lesson): call the real seam (`fake_repo.clear_reply_context(run_id)`), spy on the outbound send WITHOUT stubbing it:
```python
    send_calls: list[dict[str, Any]] = []
    real_send_outbound = gateway_mod.send_outbound

    def _spy_send_outbound(**kw):
        send_calls.append(kw)
        return real_send_outbound(**kw)

    monkeypatch.setattr(gateway_mod, "send_outbound", _spy_send_outbound)
    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")
```

**Assertion pattern** (analog lines 164-199): assert on the CAPTURED send kwargs and persisted rows with failure messages explaining the invariant. The WR-01 test's key delta: assert the spy-captured `in_reply_to`/`references` values anchor to the client's inbound `Message-ID` after crash→`POST /runs/{run_id}/retrigger` (route at `app/routes/runs.py:266`)→send. Durable chain source: `get_outbound_references_chain` in `app/email/gateway.py:240-250`. Keep LLM seams stubbed (`suggest_employees`) — `.env` has live keys.

---

### `app/routes/dashboard.py` — WR-05 containment fix

**Analog:** the function's own existing missing-file fallback (lines 112-123, verified by read):
```python
    if summary is not None and "per_fixture" in summary:
        fixtures_dir = Path("eval/fixtures")
        for fixture in summary["per_fixture"]:
            fixture_file = fixtures_dir / fixture["fixture_path"]
            if fixture_file.exists():
                fixture_data = json.loads(fixture_file.read_text())
                fixture["raw_body"] = fixture_data.get("body_text", "")
            else:
                fixture["raw_body"] = "‹fixture file missing›"
```
**Fix shape:** insert `fixture_file = (fixtures_dir / fixture["fixture_path"]).resolve()` + `if not fixture_file.is_relative_to(fixtures_dir.resolve()):` routing to the SAME `"‹fixture file missing›"` fallback string — reuse the existing branch, don't invent a new error path. Note this docstring contains "DASH-04"/"R2-MEDIUM fix" strings the sweep rewrites in the same phase — keep fix and comment edits in separate commits (test-first commit for the fix, per 14 D-08).

---

### WR-05 containment test (extend `tests/test_dashboard.py`)

**Analog:** `test_paystub_pdf_content_disposition_sanitized` (lines 380-429) — the file's security-regression idiom.

**Pattern to copy:**
- Module-level TestClient `client` (already exists in the file) driven via `client.get(...)`.
- Monkeypatch the data seams the route reads (analog patches `_repo.load_line_items` etc. with lambdas returning crafted objects, lines 405-415). For WR-05: point the route at a tmp `summary.json` containing a traversal `fixture_path` (e.g. `"../../.env"`), or monkeypatch `Path.read_text`/cwd equivalently.
- Assert the security PROPERTY on the response, with an explanatory failure message (analog lines 419-426):
```python
    response = client.get(f"/runs/{run_id}/pdf/{emp_id}")
    assert response.status_code == 200
    cd = response.headers.get("content-disposition", "")
    assert "\r" not in cd and "\n" not in cd, "CRLF must not reach the Content-Disposition header"
```
For WR-05 the property is: response 200, escaped file content NOT present in the body, fallback placeholder rendered instead.

---

### `app/llm/client.py` — INFO-02 retry-prompt scrub

**Analog:** the retry loop itself (lines 150-191, verified). The exact line to change (line 181-189):
```python
            convo = convo + [
                {
                    "role": "user",
                    "content": (
                        f"Your last output failed validation: {exc}. "
                        "Return ONLY valid JSON matching the schema."
                    ),
                }
            ]
```
Replace `{exc}` with a scrubbed summary built from `exc.errors(include_input=False, include_url=False)` (pydantic v2 — verify kwargs against pydantic 2.13 at plan time, fallback: format only `loc`/`type` from `exc.errors()` dicts). **Keep everything else in the loop untouched** — the one-retry contract (`for attempt in (1, 2)`), empty-content ValueError normalization, and second-failure propagation (lines 167-178) are locked behavior with existing tests.

---

### INFO-02 scrub test (extend `tests/test_llm_client.py`)

**Analog:** the file's FakeOpenAI capture harness + `test_invalid_then_valid_retries_exactly_once` (line 268).

**Harness pattern** (lines 100-140, verified):
```python
@pytest.fixture(autouse=True)
def _patch_openai(monkeypatch):
    """Inject FakeOpenAI over the `OpenAI` symbol the client module imports."""
    _FakeOpenAI.instances = []
    _FakeOpenAI.next_script = []
    monkeypatch.setattr("app.llm.client.OpenAI", _FakeOpenAI)
    yield
```
- Script responses via `_FakeOpenAI.next_script = ['bad json', '{"name": "Ann", "score": "0.9"}']` (invalid then valid → drives exactly one retry).
- Env setup via the existing `_set_tier_env(monkeypatch, prefix="EXTRACTION", model=..., ...)` helper (includes the required `DATABASE_URL` stub).
- Assertion seam: `_FakeOpenAI.instances[0].create_calls` records every `create(**kwargs)` — the new test inspects `create_calls[1]["messages"][-1]["content"]` (the retry prompt) and asserts the offending model-output values do NOT appear in it while the "Return ONLY valid JSON" instruction still does. Use a distinctive sentinel value in the bad first response so the negative assertion is unambiguous.

---

### `eval/fixtures/10_multi_employee_coastal.json` — POLISH-02 relabel

**Analog:** fixture 05 (existing `"typo"` category fixture) — the relabel merges fixture 10 into that existing bucket; no code pattern needed, it is a one-key JSON edit (`"fixture_category": "exact"` → `"typo"`).

**Mandatory atomic-commit pattern** (RESEARCH Pitfall 4, hermetic — no live keys):
```bash
uv run python eval/run_eval.py            # rewrites eval/summary.json from committed caches
uv run python eval/run_eval.py --chart    # rewrites eval/chart.svg
uv run python eval/run_eval.py --check    # must exit 0 before committing
# commit fixture + summary.json + chart.svg TOGETHER
```

## Shared Patterns

### Failure messages that teach the invariant
**Source:** `tests/test_retrigger_epoch.py:164-188`, `tests/test_dashboard.py:423-426`
**Apply to:** all new tests (guard, WR-01, WR-05, INFO-02)
Every `assert` carries a multi-line message stating WHY the property must hold — but per D-01/D-08, new messages must be plain English with NO ticket IDs (the analogs' own "GAP-2:"/"CR-01" prefixes are exactly what the sweep strips; do not copy those prefixes, only the explanatory style).

### Monkeypatch module-attribute seams
**Source:** `tests/test_retrigger_epoch.py:157`, `tests/test_llm_client.py:113`, `tests/test_dashboard.py:405-415`
**Apply to:** WR-01, WR-05, INFO-02 tests
`monkeypatch.setattr(module_object, "name", replacement)` on the module attribute the production code reads at call time. Never move code to create a seam (13-CONTEXT invariant); the sweep must not change module/function structure.

### Green-at-every-commit gate
**Source:** existing CI (pyproject.toml ruff/mypy config)
**Apply to:** every commit in this phase
`uv run pytest -q && uv run ruff check && uv run mypy`. Comment rewrites must respect E501 (line-length 100) and never delete/relocate `# type: ignore[code]` / `# noqa: CODE` markers (`warn_unused_ignores` is on) — rewrite only their reason text.

### Rename-neutrality proof (D-06)
**Apply to:** all test-function/file renames
`uv run pytest -q --collect-only | tail -1` before/after must show an identical count (guards against duplicate-name shadowing, Pitfall 3). CI workflows reference test FILES not function names; if renaming `test_cr_regressions.py` / `test_cr01_classify_union.py`, re-check `deploy-migrate.yml` and `concurrency-proof.yml` (neither references them).

## No Analog Found

None — every new code surface has an exact in-repo precedent. The comment-only sweep is governed by the D-01..D-06 rubric + RESEARCH.md's per-file inventory, not by a code analog. One judgment call the planner must make explicit (RESEARCH Open Q1): the guard enforces only D-08's ticket-shaped list; requirement IDs (CALC-03, BOUND-01, …) are sweep-judgment territory, not guard-enforced.

## Metadata

**Analog search scope:** `tests/`, `app/routes/`, `app/llm/`, `eval/fixtures/` (targets pre-identified by 15-RESEARCH.md's grep-verified inventory)
**Files read this session:** tests/test_bound01_private_imports.py (structure + both entry points), tests/test_retrigger_epoch.py (full first test), app/routes/dashboard.py:95-140, app/llm/client.py:150-205, tests/test_llm_client.py:100-175, tests/test_dashboard.py:375-429
**Pattern extraction date:** 2026-07-10
