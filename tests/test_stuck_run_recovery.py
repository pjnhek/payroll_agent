"""Regression proofs that ``GET /runs`` is a read-only operator view.

Automatic recovery belongs to the durable queue.  Loading the dashboard may read and
render run state, but it must never mutate a run, consume a reply, enqueue work, or
schedule an in-process task.  The legacy repository functions intentionally remain
available until the follow-up deletion plan removes their definitions.
"""
from __future__ import annotations

import ast
import inspect
from typing import Any

from fastapi.testclient import TestClient

import app.main as app_main
import app.routes.pipeline_glue as pipeline_glue
import app.routes.runs as runs_module
from app.db import repo


def _qualified_call(node: ast.Call) -> str | None:
    """Return ``owner.name`` for direct attribute calls in a route body."""
    if not isinstance(node.func, ast.Attribute):
        return None
    if not isinstance(node.func.value, ast.Name):
        return None
    return f"{node.func.value.id}.{node.func.attr}"


def test_runs_list_ast_is_read_only_and_has_no_background_tasks_parameter() -> None:
    """The route shape permits only list reads, presentation, and rendering."""
    source = inspect.getsource(runs_module.runs_list)
    tree = ast.parse(source)
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))

    assert [argument.arg for argument in function.args.args] == [
        "request",
        "demo_queue_error",
    ]
    calls = {
        qualified
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and (qualified := _qualified_call(node)) is not None
    }
    assert calls == {
        "logger.debug",
        "repo.load_all_runs",
        "router.get",
        "templates.TemplateResponse",
    }


def test_runs_route_and_repo_have_no_legacy_recovery_surface() -> None:
    """Caller-first subtraction is closed by deleting the retired facade APIs."""
    source = inspect.getsource(runs_module)
    assert "sweep_stranded_runs" not in source
    assert "find_stranded_unconsumed_replies" not in source
    assert not hasattr(repo, "sweep_stranded_runs")
    assert not hasattr(repo, "find_stranded_unconsumed_replies")


def test_runs_list_returns_200_without_touching_any_mutation_or_schedule_seam(
    monkeypatch: Any,
) -> None:
    """A successful page load never reaches a mutation, enqueue, or resume seam."""

    def _forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("GET /runs reached a forbidden side-effect seam")

    forbidden_repo_seams: tuple[str, ...] = (
        "load_run",
        "find_business_by_sender",
        "mark_reply_consumed",
        "set_status",
        "claim_status",
        "enqueue_job",
    )
    for name in forbidden_repo_seams:
        monkeypatch.setattr(repo, name, _forbidden)

    forbidden_glue_seams: tuple[str, ...] = (
        "reply_sender_ok",
        "row_to_inbound",
        "resume_pipeline_bg",
    )
    for name in forbidden_glue_seams:
        monkeypatch.setattr(pipeline_glue, name, _forbidden)

    monkeypatch.setattr(repo, "load_all_runs", lambda: [])
    response = TestClient(app_main.app).get("/runs")

    assert response.status_code == 200
    assert "Payroll Runs" in response.text
