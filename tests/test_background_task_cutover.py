"""Permanent guard for the durable payroll-producer cutover.

The inventory is intentionally explicit. It covers the eight historical route
producers, the pipeline bridge that used to own process-local wrappers, and every
former consumer migrated before wrapper deletion. Unrelated framework background
facilities outside these payroll surfaces remain out of scope.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_HISTORICAL_PRODUCERS: dict[Path, frozenset[str]] = {
    REPO_ROOT / "app/routes/webhook.py": frozenset({"inbound"}),
    REPO_ROOT / "app/routes/demo.py": frozenset(
        {"demo_compose", "demo_send_test"}
    ),
    REPO_ROOT / "app/routes/runs.py": frozenset(
        {"approve", "resolve", "retrigger", "runs_list", "simulate_reply"}
    ),
}
_PIPELINE_GLUE = REPO_ROOT / "app/routes/pipeline_glue.py"
_REQUIRED_DURABLE_GLUE = frozenset(
    {
        "row_to_inbound",
        "reply_sender_ok",
        "persist_and_enqueue_reply",
        "resume_pipeline_now",
        "run_pipeline_now",
    }
)

# The nine Plan 19-11 consumer modules named by the deletion dependency.
_FORMER_CONSUMERS = (
    REPO_ROOT / "tests/test_retrigger_threading.py",
    REPO_ROOT / "tests/test_ingest.py",
    REPO_ROOT / "tests/test_concurrency_proof.py",
    REPO_ROOT / "tests/test_gateway.py",
    REPO_ROOT / "tests/test_stuck_run_recovery.py",
    REPO_ROOT / "tests/test_hitl.py",
    REPO_ROOT / "tests/test_webhook_dedup_race.py",
    REPO_ROOT / "tests/test_queue_drain.py",
    REPO_ROOT / "tests/test_send_idempotency.py",
)

# Plan 19-11's full-suite gate and Plan 19-12's deletion exposed these additional
# historical references. Keep them guarded without changing the exact nine-file
# dependency inventory above.
_ADDITIONAL_CUTOVER_TESTS = (
    REPO_ROOT / "tests/test_job_kind_drift.py",
    REPO_ROOT / "tests/test_reply_redelivery.py",
    REPO_ROOT / "tests/test_threading.py",
    REPO_ROOT / "tests/test_dashboard.py",
    REPO_ROOT / "tests/test_needs_operator.py",
    REPO_ROOT / "tests/test_webhook.py",
)

_RETIRED_SYMBOLS = frozenset(
    {
        "finish_reply_resume",
        "_consume_background_result",
        "resume_pipeline_bg",
        "run_pipeline_bg",
        "operator_resume_bg",
    }
)


def _top_level_functions(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _annotation_text(annotation: ast.expr | None) -> str:
    return "" if annotation is None else ast.unparse(annotation)


def _cutover_violations(source: str) -> list[str]:
    """Return structural payroll cutover violations for one inventoried source."""
    tree = ast.parse(source)
    violations: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
            if any(alias.name == "BackgroundTasks" for alias in node.names):
                violations.append(f"line {node.lineno}: BackgroundTasks import")
        elif (
            isinstance(node, ast.Name)
            and node.id == "BackgroundTasks"
            or isinstance(node, ast.Attribute)
            and node.attr == "BackgroundTasks"
        ):
            violations.append(f"line {node.lineno}: BackgroundTasks reference")

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _RETIRED_SYMBOLS:
                violations.append(
                    f"line {node.lineno}: retired definition {node.name}"
                )
            annotations = [
                *(_annotation_text(arg.annotation) for arg in node.args.posonlyargs),
                *(_annotation_text(arg.annotation) for arg in node.args.args),
                *(_annotation_text(arg.annotation) for arg in node.args.kwonlyargs),
                _annotation_text(node.args.vararg.annotation)
                if node.args.vararg is not None
                else "",
                _annotation_text(node.args.kwarg.annotation)
                if node.args.kwarg is not None
                else "",
                _annotation_text(node.returns),
            ]
            if any("BackgroundTasks" in annotation for annotation in annotations):
                violations.append(
                    f"line {node.lineno}: BackgroundTasks function signature"
                )

        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_task"
        ):
            violations.append(f"line {node.lineno}: process-local add_task call")

        if isinstance(node, ast.Name) and node.id in _RETIRED_SYMBOLS:
            violations.append(f"line {node.lineno}: retired reference {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in _RETIRED_SYMBOLS:
            violations.append(f"line {node.lineno}: retired reference {node.attr}")

    return violations


def test_payroll_background_cutover_inventory_is_exact_nonempty_and_green() -> None:
    """All historical producer and consumer seams stay on durable replacements."""
    assert sum(map(len, _HISTORICAL_PRODUCERS.values())) == 8
    assert len(_FORMER_CONSUMERS) == 9
    assert len(set(_FORMER_CONSUMERS)) == len(_FORMER_CONSUMERS)

    inventoried = {
        *_HISTORICAL_PRODUCERS,
        _PIPELINE_GLUE,
        *_FORMER_CONSUMERS,
        *_ADDITIONAL_CUTOVER_TESTS,
    }
    assert inventoried
    assert all(path.is_file() for path in inventoried)

    sources = {
        path: path.read_text(encoding="utf-8") for path in sorted(inventoried)
    }
    assert all(source.strip() for source in sources.values())

    for path, expected in _HISTORICAL_PRODUCERS.items():
        discovered = _top_level_functions(ast.parse(sources[path]))
        assert expected <= discovered, (
            f"historical producer inventory drifted in {path.relative_to(REPO_ROOT)}: "
            f"missing {sorted(expected - discovered)}"
        )

    glue_functions = _top_level_functions(ast.parse(sources[_PIPELINE_GLUE]))
    assert glue_functions >= _REQUIRED_DURABLE_GLUE

    violations = {
        str(path.relative_to(REPO_ROOT)): found
        for path, source in sources.items()
        if (found := _cutover_violations(source))
    }
    assert not violations, f"payroll background cutover regressed: {violations}"

    from app.routes import pipeline_glue

    for name in _RETIRED_SYMBOLS:
        assert not hasattr(pipeline_glue, name), f"retired wrapper returned: {name}"


def test_cutover_guard_detects_process_local_producer_mutation() -> None:
    """A synthetic FastAPI scheduling producer must make the detector bite."""
    synthetic = """
from fastapi import BackgroundTasks

def inbound(run_id, background_tasks: BackgroundTasks):
    background_tasks.add_task(pipeline_glue.run_pipeline_now, run_id)
"""
    violations = _cutover_violations(synthetic)
    assert any("BackgroundTasks import" in item for item in violations)
    assert any("BackgroundTasks function signature" in item for item in violations)
    assert any("process-local add_task call" in item for item in violations)


def test_cutover_guard_detects_retired_wrapper_definition_mutation() -> None:
    """A synthetic compatibility definition must fail the same real scanner."""
    synthetic = """
def run_pipeline_bg(run_id):
    return run_pipeline_now(run_id)
"""
    violations = _cutover_violations(synthetic)
    assert any("retired definition run_pipeline_bg" in item for item in violations)

    with pytest.raises(AssertionError):
        assert not violations
