"""Committed static regression test for ROADMAP criterion #4: the keepalive-into-pump
fold-in must never silently drop a monitor.

A hermetic, text/structure guard over `.github/workflows/` — no live DB, no marker,
no live-cron proof (the live cron firing itself stays a manual-only verification). It
asserts:

1. `.github/workflows/pump.yml` exists.
2. `.github/workflows/keepalive.yml` does NOT exist (deleted, not deprecated-in-place).
3. Exactly ONE workflow across `.github/workflows/` is scheduled — pump.yml is the sole
   cron hitting the service.
4. All three endpoints (`/internal/pump`, `/health/ready`, `/health/schema`) appear in
   pump.yml — the schema-drift monitor is the criterion #4 trap: carrying only the wake
   ping forward would silently drop the only monitor for a manual Supabase edit that
   bypasses deploy-migrate.yml.
5. `workflow_dispatch` is present in pump.yml (GitHub's 60-day auto-disable escape hatch).

Two deliberate landmines this scanner avoids:

- **PyYAML's `on` -> boolean-True coercion (YAML 1.1).** An unquoted `on:` key parses as
  the Python boolean `True`, not the string `'on'` — indexing a parsed dict by the
  literal string key `on` KeyErrors on perfectly valid workflow YAML. This module never
  does that; where YAML is loaded at all, the trigger key is resolved via
  `d.get(True, d.get('on'))`.
- **Comment-insensitivity.** Both pump.yml and (historically) keepalive.yml mention
  `schedule:` inside PROSE comment blocks (see pump.yml's own header comment explaining
  its cadence), so a raw substring scan over raw file text would miscount. Every
  presence/count check here runs against COMMENT-STRIPPED text — every line whose first
  non-whitespace character is `#` is dropped first — so a `schedule:` mention in a
  comment can never inflate the "exactly one scheduled workflow" count, and a mere
  comment mention of an endpoint can never satisfy the endpoint-presence check.
"""
from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
PUMP_WORKFLOW = WORKFLOWS_DIR / "pump.yml"
KEEPALIVE_WORKFLOW = WORKFLOWS_DIR / "keepalive.yml"


def _strip_comment_lines(text: str) -> str:
    """Drop every line whose first non-whitespace character is `#`.

    Keeps real YAML lines that carry a trailing inline comment (e.g.
    `workflow_dispatch:  # manual re-enable`) while removing `#`-prefixed prose
    blocks entirely, so a comment mentioning `schedule:` or an endpoint path cannot
    be mistaken for the real trigger/step it merely describes.
    """
    kept_lines = [
        line for line in text.splitlines() if not line.strip().startswith("#")
    ]
    return "\n".join(kept_lines)


def _is_scheduled_workflow(workflow_file: pathlib.Path) -> bool:
    """True when `workflow_file` DECLARES a `schedule` trigger — resolved two ways:

    (i) `schedule:`/`cron:` present in the comment-stripped TEXT (a mere prose
        mention, already stripped, cannot trigger this); OR
    (ii) `yaml.safe_load`, with the trigger key resolved as `d.get(True,
         d.get('on'))` (the documented workaround for YAML 1.1's unquoted-`on`
         boolean coercion) — `isinstance(triggers, dict) and 'schedule' in triggers`.

    Either signal alone is sufficient; both independently avoid the comment/prose
    false-positive and the PyYAML unquoted-`on`-key KeyError landmine.
    """
    raw_text = workflow_file.read_text(encoding="utf-8")
    stripped = _strip_comment_lines(raw_text)
    if "schedule:" in stripped or "cron:" in stripped:
        return True

    parsed = yaml.safe_load(raw_text)
    if not isinstance(parsed, dict):
        return False
    triggers = parsed.get(True, parsed.get("on"))
    return isinstance(triggers, dict) and "schedule" in triggers


def test_pump_yml_exists_and_keepalive_yml_deleted() -> None:
    """The fold-in is a DELETION, not a deprecation-in-place: pump.yml must exist
    and keepalive.yml must be gone, so pump.yml is the only cron hitting the
    service (ROADMAP criterion #4)."""
    assert PUMP_WORKFLOW.is_file(), f"expected {PUMP_WORKFLOW} to exist"
    assert not KEEPALIVE_WORKFLOW.exists(), (
        f"expected {KEEPALIVE_WORKFLOW} to be deleted (fold-in, not deprecation)"
    )


def test_exactly_one_scheduled_workflow() -> None:
    """pump.yml is the SOLE cron across .github/workflows/ — a `schedule:` mention
    in another workflow's prose comment must NOT inflate this count (comment-
    insensitive scan), and neither must the PyYAML `on`->True coercion cause a
    false negative (resolved via `d.get(True, d.get('on'))`)."""
    scheduled = [
        wf.name
        for wf in sorted(WORKFLOWS_DIR.glob("*.yml"))
        if _is_scheduled_workflow(wf)
    ]
    assert scheduled == ["pump.yml"], (
        f"expected exactly one scheduled workflow (pump.yml), got: {scheduled}"
    )


def test_pump_yml_carries_all_three_endpoints() -> None:
    """The criterion #4 trap: carrying only the wake ping forward would silently
    drop the /health/schema drift monitor — the only thing that catches a manual
    Supabase edit bypassing deploy-migrate.yml. All three endpoints must appear in
    pump.yml's COMMENT-STRIPPED text (a mere comment mention must not satisfy
    this — each endpoint must be a real curl target)."""
    stripped = _strip_comment_lines(PUMP_WORKFLOW.read_text(encoding="utf-8"))
    for endpoint in ("/internal/pump", "/health/ready", "/health/schema"):
        assert endpoint in stripped, (
            f"expected {endpoint} in pump.yml's comment-stripped text, "
            "the endpoint must be a real curl target, not only a comment mention"
        )


def test_pump_yml_has_workflow_dispatch() -> None:
    """GitHub auto-disables a scheduled workflow after ~60 days of no repository
    commit activity; workflow_dispatch is the one-click re-enable from the Actions
    tab (carried forward from keepalive.yml's rationale)."""
    stripped = _strip_comment_lines(PUMP_WORKFLOW.read_text(encoding="utf-8"))
    assert "workflow_dispatch" in stripped, (
        "expected workflow_dispatch in pump.yml's comment-stripped text"
    )
