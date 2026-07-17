"""Regression boundaries for the offline evaluation chart.

The chart is presentation-only. D-04 and D-13 require changing a committed eval
artifact to remain incapable of replaying provider snapshots or mutating completed
outbound audit records, so these tests pin both the visual contract and the import
boundary without asserting unstable Matplotlib SVG bytes.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, cast

from eval import run_eval


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SUMMARY_PATH = _REPO_ROOT / "eval" / "summary.json"
_RUN_EVAL_PATH = _REPO_ROOT / "eval" / "run_eval.py"


def _render_committed_aggregate(tmp_path: Path, monkeypatch: Any) -> str:
    committed = json.loads(_SUMMARY_PATH.read_text())
    output_path = tmp_path / "chart.svg"
    monkeypatch.setattr(run_eval, "CHART_PATH", output_path)

    run_eval._write_svg_chart(
        cast(list[run_eval.FixtureResult], committed["per_fixture"]),
        cast(run_eval.AggregateResult, committed["aggregate"]),
    )
    return output_path.read_text()


def test_chart_style_metadata_matches_dashboard_tokens() -> None:
    """The generator declares the dashboard-aligned palette and sans typography."""
    assert run_eval.CHART_PALETTE == {
        "primary": "#1E3A5F",
        "secondary": "#6B7280",
        "accent": "#4F46E5",
        "surface": "#FFFFFF",
        "background": "#F7F8FA",
        "border": "#E8EAED",
        "danger": "#DC2626",
        "danger_soft": "#FEE2E2",
    }
    assert run_eval.CHART_STYLE["font.family"] == "sans-serif"


def test_chart_svg_is_styled_aggregate_only_and_does_not_mutate_summary(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Rendering uses aggregate metrics and keeps the committed report untouched."""
    before = _SUMMARY_PATH.read_text()
    svg = _render_committed_aggregate(tmp_path, monkeypatch)
    after = _SUMMARY_PATH.read_text()

    lowered = svg.lower()
    assert "#1e3a5f" in lowered
    assert "#6b7280" in lowered
    assert "#e8eaed" in lowered
    assert "#4682b4" not in lowered
    assert "#2e8b57" not in lowered
    assert "stroke: #000000" not in lowered
    assert "Extraction scored against committed extraction caches" in svg
    assert "FALSE-PROCESS" in svg
    assert "Thomas Bergmann" not in svg
    assert "David Reyes" not in svg
    assert before == after


def test_eval_chart_module_boundary_excludes_delivery_and_mutation_code() -> None:
    """D-04/D-13: eval chart code cannot import delivery or persistence writers."""
    tree = ast.parse(_RUN_EVAL_PATH.read_text())
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )

    forbidden_prefixes = (
        "app.email.gateway",
        "app.pipeline.delivery",
        "app.pipeline.snapshot",
        "app.queue",
        "app.db.bootstrap",
        "app.db.repo",
    )
    assert not {
        module
        for module in imported_modules
        if module.startswith(forbidden_prefixes)
    }
    assert "app.db.seed" in imported_modules
