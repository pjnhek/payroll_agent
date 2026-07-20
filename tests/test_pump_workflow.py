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
from typing import Any

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


class TestAlarmStepOrdering:
    """Structural pins over the parsed YAML for the swallowing-bug alarm step:
    recovery runs first and unconditionally, reporting runs last and can never
    suppress it. Structural assertions over the parsed YAML are required here
    rather than substring checks on the file text — a substring check is
    satisfied by a comment, and this repo has already had a verification grep
    silently lie."""

    @staticmethod
    def _steps() -> list[dict[str, Any]]:
        parsed = yaml.safe_load(PUMP_WORKFLOW.read_text(encoding="utf-8"))
        return [
            step
            for job in parsed["jobs"].values()
            for step in job.get("steps", [])
        ]

    @classmethod
    def _drain_index(cls, steps: list[dict[str, Any]]) -> int:
        drain_indices = [
            i for i, step in enumerate(steps) if "Drain" in step.get("name", "")
        ]
        assert len(drain_indices) == 1, (
            f"expected exactly one drain step, found indices {drain_indices}"
        )
        return drain_indices[0]

    @classmethod
    def _alarm_index(cls, steps: list[dict[str, Any]]) -> int:
        alarm_indices = [
            i
            for i, step in enumerate(steps)
            if isinstance(step.get("run"), str) and "/health/queue" in step["run"]
        ]
        assert len(alarm_indices) == 1, (
            f"expected exactly one /health/queue alarm step, found indices {alarm_indices}"
        )
        return alarm_indices[0]

    def test_alarm_step_runs_after_the_drain_step(self) -> None:
        steps = self._steps()
        drain_i = self._drain_index(steps)
        alarm_i = self._alarm_index(steps)
        assert alarm_i > drain_i, (
            "the alarm step must be positioned after the drain step: "
            "recovery runs first, reporting runs second"
        )

    def test_alarm_step_is_the_last_step(self) -> None:
        steps = self._steps()
        alarm_i = self._alarm_index(steps)
        assert alarm_i == len(steps) - 1, (
            "the alarm step must be the last step in the job's steps list"
        )

    def test_alarm_step_carries_the_same_always_guard_as_the_sibling_health_steps(
        self,
    ) -> None:
        steps = self._steps()
        alarm_i = self._alarm_index(steps)
        sibling_health_steps = [
            s
            for s in steps
            if isinstance(s.get("run"), str)
            and ("/health/ready" in s["run"] or "/health/schema" in s["run"])
        ]
        sibling_guards = {str(s.get("if", "")).lower() for s in sibling_health_steps}
        assert len(sibling_guards) == 1, (
            f"expected the two sibling health steps to share one guard, got {sibling_guards}"
        )
        alarm_guard = str(steps[alarm_i].get("if", "")).lower()
        assert alarm_guard == next(iter(sibling_guards)), (
            f"alarm step's `if` guard ({alarm_guard!r}) must match the sibling "
            f"health steps' guard ({sibling_guards!r}) exactly"
        )
        assert "always" in alarm_guard, (
            "the alarm step must carry an `if: always()` guard so an earlier RED "
            "step cannot suppress it either"
        )

    def test_drain_step_carries_no_if_key(self) -> None:
        """This is the specific regression this repo has already been bitten by
        once: an `if:` guard accidentally added to the drain step would let an
        earlier RED (e.g. from the secrets-validation step) skip recovery
        entirely. Recovery must run unconditionally, every time."""
        steps = self._steps()
        drain_i = self._drain_index(steps)
        assert "if" not in steps[drain_i], (
            "the drain step must carry NO `if:` key at all — recovery runs "
            "first and unconditionally, and an alarm ahead of it (or a guard "
            "added to it) would turn a reporting failure into a recovery failure"
        )

    def test_alarm_step_uses_the_failing_curl_form(self) -> None:
        steps = self._steps()
        alarm_i = self._alarm_index(steps)
        run_text = steps[alarm_i].get("run", "")
        assert "curl -f" in run_text, (
            "the alarm step's `run` must use the failing-curl form (`curl -f`) "
            "so a non-200 response reds the scheduled run"
        )


def test_health_steps_run_independently_of_the_drain_step() -> None:
    """The three curl steps are INDEPENDENT RED signals. GitHub Actions skips later
    steps once one fails, so without an `if:` guard a RED drain step (the pump route
    is allowed to go RED on a worst-case overrun or a 503 regression) would silently
    skip the /health/ready wake and /health/schema drift monitors — the exact
    silent-monitor-drop that ROADMAP criterion #4 forbids. Both health steps must
    carry `always()` (or `!cancelled()`) so they fire regardless of the drain step's
    outcome; the job still fails overall if any step fails."""
    parsed = yaml.safe_load(PUMP_WORKFLOW.read_text(encoding="utf-8"))
    steps = [
        step
        for job in parsed["jobs"].values()
        for step in job.get("steps", [])
    ]
    health_steps = [
        s
        for s in steps
        if isinstance(s.get("run"), str)
        and ("/health/ready" in s["run"] or "/health/schema" in s["run"])
    ]
    assert len(health_steps) == 2, (
        f"expected 2 health curl steps in pump.yml, found {len(health_steps)}"
    )
    for step in health_steps:
        guard = str(step.get("if", "")).lower()
        assert "always" in guard or "cancelled" in guard, (
            f"health step {step.get('name')!r} must carry an `if: always()` "
            "(or !cancelled()) guard so a RED drain step cannot skip it"
        )
