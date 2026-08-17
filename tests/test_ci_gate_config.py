"""Hermetic coverage for the CI gate configuration in .github/workflows/ci.yml.

A misconfigured trigger is invisible until the day it matters: a workflow can stay
green on every push while never once running against a pull request, and the first
sign of trouble is a merged change whose gate simply never fired. This module parses
the COMMITTED workflow file and asserts on its structure, so that class of drift is
caught by the hermetic suite rather than discovered the hard way.

Everything here reads the workflow YAML off disk and asserts on the parsed structure
-- no subprocess, no network, no Docker daemon, no live GitHub Actions run. It answers
"is the gate wired correctly", not "does the gate currently pass"; the latter is what
actually running `npm run typecheck`, a real `docker build`, and a scratch-branch diff
prove, and those proofs (with full transcripts) live in this plan's own summary rather
than as code here, precisely because they need a Node toolchain and a Docker daemon
this hermetic test job does not have.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CI_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
EVAL_WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "eval.yml"
FRONTEND_PACKAGE_JSON = REPO_ROOT / "frontend" / "package.json"

REQUIRED_FRONTEND_SCRIPTS = ("typecheck", "lint", "test", "build")
EXPECTED_JOB_NAMES = {"lint", "test", "typecheck", "frontend", "docker-build"}


def _load_workflow(path: pathlib.Path) -> dict[Any, Any]:
    loaded: object = yaml.safe_load(path.read_text())
    assert isinstance(loaded, dict)
    return loaded


def _trigger_block(workflow: dict[Any, Any]) -> dict[str, Any]:
    # PyYAML's default (YAML 1.1) resolver treats the bare scalar key `on` as the
    # boolean `True`, not the string "on" -- this is a PyYAML quirk, not a workflow
    # authoring mistake, and every reader of this workflow via `yaml.safe_load` hits
    # it identically (including the ci.yml verification commands used while building
    # this gate).
    trigger = workflow[True]
    assert isinstance(trigger, dict)
    return trigger


def _job(workflow: dict[Any, Any], name: str) -> dict[str, Any]:
    jobs = workflow["jobs"]
    assert name in jobs, f"job {name!r} is missing from ci.yml; jobs present: {sorted(jobs)}"
    result: dict[str, Any] = jobs[name]
    return result


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    steps = job.get("steps", [])
    assert isinstance(steps, list)
    return steps


def _find_step_by_name_substring(job: dict[str, Any], substring: str) -> dict[str, Any] | None:
    """Locate a step by a case-insensitive substring of its `name`, never by index --
    a renamed or reordered step must not silently escape this test's coverage."""
    for step in _steps(job):
        if substring.lower() in str(step.get("name", "")).lower():
            return step
    return None


def _npm_script_step_map(job: dict[str, Any]) -> dict[str, int]:
    """Map each `npm run <script>` invocation found anywhere in the job's step
    `run` bodies to the (0-based) step index it appears in. Discovered by scanning
    step command text, not by pinning a step index -- a reordered or renamed step
    is still found."""
    mapping: dict[str, int] = {}
    for idx, step in enumerate(_steps(job)):
        run_text = step.get("run") or ""
        for match in re.finditer(r"\bnpm run (\w+)\b", run_text):
            mapping.setdefault(match.group(1), idx)
    return mapping


def test_ci_triggers_on_pull_request_unlike_the_push_only_eval_workflow() -> None:
    """The trigger block is what makes every job in this file a pre-merge gate. The
    eval workflow in this same repo is the explicit anti-analog: it is push-only, so
    a job added there would never once run against a pull request before merging."""
    ci_workflow = _load_workflow(CI_WORKFLOW_PATH)
    ci_trigger = _trigger_block(ci_workflow)
    assert "pull_request" in ci_trigger, (
        f"ci.yml's trigger block does not include pull_request: {ci_trigger!r}. "
        "Without it, none of this file's jobs -- including the frontend and "
        "docker-build jobs -- actually gate a pull request; they would only ever "
        "run after a push already landed, which is the eval workflow's shape, "
        "not this one's."
    )

    eval_workflow = _load_workflow(EVAL_WORKFLOW_PATH)
    eval_trigger = _trigger_block(eval_workflow)
    assert "pull_request" not in eval_trigger, (
        "the eval workflow now has a pull_request trigger, which invalidates this "
        "test's anti-analog assumption -- if that change is intentional, this "
        "assertion should be revisited, but ci.yml's own jobs must still inherit "
        "ci.yml's trigger block regardless of what eval.yml does."
    )


def test_ci_workflow_has_exactly_the_five_expected_jobs() -> None:
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    jobs = set(workflow["jobs"].keys())
    assert jobs == EXPECTED_JOB_NAMES, (
        f"ci.yml's job set is {sorted(jobs)}, expected exactly {sorted(EXPECTED_JOB_NAMES)}"
    )


def test_new_jobs_declare_no_own_concurrency_group_or_needs_dependency() -> None:
    """Neither new job may declare a job-level `concurrency` group: both must inherit
    the workflow-level group keyed on the ref, so two simultaneous pull requests on
    different refs each get their own run and never cancel each other's. Neither may
    declare `needs:` either -- they are independent and must fail independently."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    for job_name in ("frontend", "docker-build"):
        job = _job(workflow, job_name)
        assert "concurrency" not in job, (
            f"{job_name} job declares its own concurrency group, which would scope "
            "cancellation to that job alone instead of inheriting the workflow-level "
            "ci-${{ github.ref }} group -- two pull requests on different refs could "
            "then cancel each other's run."
        )
        assert "needs" not in job, (
            f"{job_name} job declares a needs dependency -- it must fail "
            "independently of the other new job."
        )


def test_workflow_permissions_stay_read_only_for_the_new_jobs() -> None:
    """The docker-build job only ever builds an image, never pushes one, so the
    workflow's read-only token must stay sufficient -- no job may escalate it."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    assert workflow.get("permissions") == {"contents": "read"}, workflow.get("permissions")
    for job_name in ("frontend", "docker-build"):
        job = _job(workflow, job_name)
        assert "permissions" not in job, (
            f"{job_name} job overrides the workflow-level read-only permissions block"
        )


def test_frontend_job_runs_the_four_npm_scripts_as_four_separate_steps() -> None:
    """Typecheck, lint, test, and build must each be their own named step -- one
    chained command would make a red run ambiguous about which half broke."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "frontend")
    script_to_step = _npm_script_step_map(job)

    missing = set(REQUIRED_FRONTEND_SCRIPTS) - script_to_step.keys()
    assert not missing, (
        f"frontend job never invokes npm run {sorted(missing)}; found scripts "
        f"{sorted(script_to_step)}"
    )

    step_indices = [script_to_step[script] for script in REQUIRED_FRONTEND_SCRIPTS]
    assert len(set(step_indices)) == len(REQUIRED_FRONTEND_SCRIPTS), (
        f"expected four distinct steps (one per script), got script->step mapping "
        f"{script_to_step} -- a chained command would collapse two or more scripts "
        "onto the same step index."
    )


def test_frontend_job_installs_with_the_lockfile_asserting_npm_ci() -> None:
    """`npm ci` fails on any lockfile/package.json mismatch instead of silently
    re-resolving. `npm install` (the resolving command) must not appear anywhere in
    the job -- a stale lockfile must fail the job, not merge green."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "frontend")
    run_bodies = [step.get("run") or "" for step in _steps(job)]

    assert any("npm ci" in body for body in run_bodies), (
        "frontend job has no `npm ci` install step"
    )
    resolving_install = [body for body in run_bodies if re.search(r"\bnpm install\b", body)]
    assert not resolving_install, (
        f"frontend job invokes the resolving `npm install` somewhere: {resolving_install} "
        "-- use `npm ci` so a lockfile drift fails the job instead of silently "
        "re-resolving a different dependency tree than what is committed."
    )


def test_frontend_job_test_step_never_adds_a_watch_flag() -> None:
    """A watch-mode invocation never exits, which would hang the job forever instead
    of gating the pull request."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "frontend")
    test_steps = [
        step.get("run") or "" for step in _steps(job) if "npm run test" in (step.get("run") or "")
    ]
    assert test_steps, "no frontend job step invokes npm run test"
    assert not any("--watch" in body or "watch" in body.lower() for body in test_steps), (
        f"frontend job's test step looks like it enables watch mode: {test_steps}"
    )


def test_frontend_package_json_test_script_is_not_a_watcher() -> None:
    """The underlying npm script the CI step invokes must itself be a non-watch
    (single-run) invocation, independent of what the CI step's own command line
    says -- a watcher script would hang the job even if the step invoking it never
    passes --watch explicitly."""
    package = json.loads(FRONTEND_PACKAGE_JSON.read_text())
    test_script = package["scripts"]["test"]
    assert "watch" not in test_script.lower(), (
        f"frontend/package.json's test script ({test_script!r}) looks like a watch-"
        "mode invocation -- a CI job that never exits cannot gate a pull request."
    )


def test_docker_build_job_builds_the_whole_image_with_no_registry_credentials() -> None:
    """No stage target -- the whole point is that the runtime stage's build-time
    manifest assertion actually executes. No registry credentials -- this job only
    proves the image builds, it never pushes anywhere."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "docker-build")
    run_bodies = [step.get("run") or "" for step in _steps(job)]
    build_bodies = [body for body in run_bodies if "docker build" in body]
    assert build_bodies, "docker-build job has no step that runs `docker build`"
    assert not any("--target" in body for body in build_bodies), (
        f"docker-build job passes --target, which would skip building (and "
        f"therefore skip proving) the runtime stage: {build_bodies}"
    )

    step_names = " ".join(str(step.get("name", "")).lower() for step in _steps(job))
    for forbidden in ("login", "registry", "push"):
        assert forbidden not in step_names, (
            f"docker-build job appears to configure {forbidden!r}, which this job "
            "must never do -- it builds only."
        )


def test_lint_job_contains_the_diff_scope_fence() -> None:
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "lint")
    fence_step = _find_step_by_name_substring(job, "scope")
    assert fence_step is not None, (
        "lint job has no step whose name references the diff-scope fence"
    )


def test_diff_scope_fence_covers_five_untouchable_directories_that_actually_exist() -> None:
    """The set of protected directories is pulled straight out of the fence step's
    own shell body via regex -- never restated as a hand-typed list in this test --
    so a directory silently dropped from the fence fails THIS assertion, not a
    copy-paste mismatch between two independently maintained lists. Each extracted
    path is also checked against the real repository layout, so a typo'd directory
    name (which would still "count" toward five) is caught too."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "lint")
    fence_step = _find_step_by_name_substring(job, "scope")
    assert fence_step is not None
    body = fence_step.get("run") or ""

    protected_dirs = sorted(set(re.findall(r"\bapp/[a-z]+/", body)))
    assert len(protected_dirs) == 5, (
        f"expected the fence step to name exactly five untouchable directories, "
        f"found {protected_dirs} in its shell body"
    )
    for directory in protected_dirs:
        assert (REPO_ROOT / directory).is_dir(), (
            f"{directory!r} named in the diff-scope fence does not exist under "
            f"{REPO_ROOT} -- likely a typo in the fence step's pathspec"
        )


def test_diff_scope_fence_resolves_base_commit_per_event_with_a_first_push_fallback() -> None:
    """Resolves the base commit from the pull-request payload on a PR event and from
    the before-SHA on a push event, with an explicit fallback for the all-zeros
    first-push case -- a bare shallow diff against an unresolved base would either
    crash the job or, worse, silently diff nothing and pass with an empty change
    set, both of which defeat the fence."""
    workflow = _load_workflow(CI_WORKFLOW_PATH)
    job = _job(workflow, "lint")
    fence_step = _find_step_by_name_substring(job, "scope")
    assert fence_step is not None
    body = fence_step.get("run") or ""

    assert "pull_request" in body, "fence step never branches on the pull_request event"
    assert re.search(r"merge-base", body), (
        "fence step has no merge-base fallback for the all-zeros first-push before-SHA"
    )

    checkout_step = job["steps"][0]
    assert checkout_step.get("with", {}).get("fetch-depth") == 0, (
        "lint job's checkout step does not fetch full history (fetch-depth: 0) -- "
        "the fence step has nothing to diff against without it"
    )


def test_diff_scope_fence_names_removal_owner_in_a_comment() -> None:
    """Without a stated removal owner, a future milestone silently inherits a gate
    nobody can explain."""
    ci_text = CI_WORKFLOW_PATH.read_text()
    # Anchor on the step DEFINITION ("- name: ..."), not a bare substring match --
    # an earlier comment elsewhere in the file also mentions "Diff-scope fence" in
    # passing (the checkout step explains why it fetches full history), and that
    # earlier mention sits nowhere near the removal-owner comment this test looks for.
    fence_marker_index = ci_text.find("- name: Diff-scope fence")
    assert fence_marker_index != -1, "no step definition named for the diff-scope fence"
    # The removal-owner comment sits directly above the fence step in the committed
    # file; search a generous window around the step rather than pin an exact line
    # range, so a reflow does not make this assertion brittle.
    window = ci_text[max(0, fence_marker_index - 1200) : fence_marker_index + 400]
    assert "milestone" in window.lower() and (
        "remove" in window.lower() or "retire" in window.lower()
    ), "no removal-owner comment found near the diff-scope fence step"
