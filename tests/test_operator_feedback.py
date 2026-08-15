"""Unit tests for the shared operator-notice mechanism (app/routes/operator_feedback.py).

Pure static tests -- no HTTP, no DB. HTTP-level coverage of individual notice
codes lives with each consuming handler's own test file (e.g.
tests/test_reply_redelivery.py for the simulate_reply codes migrated here).
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from app.routes.operator_feedback import NOTICE_LABELS, notice_label, notice_redirect, notice_url

_ROUTES_DIR = pathlib.Path(__file__).parent.parent / "app" / "routes"


def test_notice_label_rejects_hostile_input() -> None:
    """An unrecognised (e.g. attacker-supplied) code reduces to None, never itself."""
    assert notice_label("<script>alert(1)</script>") is None


def test_every_label_is_non_empty_and_markup_free() -> None:
    assert NOTICE_LABELS, "NOTICE_LABELS must not be empty"
    for code, label in NOTICE_LABELS.items():
        assert label.strip(), f"label for {code!r} must be non-empty"
        for char in "<>{}":
            assert char not in label, f"label for {code!r} contains {char!r}: {label!r}"


def test_notice_url_raises_on_unknown_code() -> None:
    with pytest.raises(KeyError):
        notice_url("/runs/x", "not_a_real_code")


def test_notice_redirect_raises_on_unknown_code() -> None:
    with pytest.raises(KeyError):
        notice_redirect("/runs/x", "not_a_real_code")


def test_notice_redirect_carries_the_code_and_default_303() -> None:
    response = notice_redirect("/runs/abc", "reply_no_proof")
    assert response.status_code == 303
    assert response.headers["location"] == "/runs/abc?notice=reply_no_proof"


def _notice_redirect_call_site_codes() -> list[tuple[str, int, str]]:
    """AST-collect every string literal passed as the `code` arg of a
    notice_redirect(...) call across every router module.

    Positional-or-keyword aware: `notice_redirect(base, "code")` and
    `notice_redirect(base, code="code")` are both recognised. A call whose code
    argument is not a literal (e.g. a variable) is skipped -- this guard only
    pins STATIC call sites, which is every call site in this codebase today.
    """
    found: list[tuple[str, int, str]] = []
    for path in sorted(_ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            if node.func.id != "notice_redirect":
                continue
            code_node: ast.expr | None = None
            if len(node.args) >= 2:
                code_node = node.args[1]
            else:
                for kw in node.keywords:
                    if kw.arg == "code":
                        code_node = kw.value
            if isinstance(code_node, ast.Constant) and isinstance(code_node.value, str):
                found.append((path.name, node.lineno, code_node.value))
    return found


def test_every_static_notice_redirect_call_site_uses_a_labeled_code() -> None:
    """The durable guard: a code introduced at a call site that has no entry in
    NOTICE_LABELS would render nothing at all -- exactly the BUG-6/7/8/9/4/3
    class this mechanism exists to prevent. Fails the moment a future call
    site ships a typo'd or unregistered code."""
    call_sites = _notice_redirect_call_site_codes()
    assert call_sites, (
        "expected at least one static notice_redirect(...) call site across "
        "app/routes/*.py once T2+ lands; if this fires before then the glob/AST "
        "walk itself is broken"
    )
    unlabeled = [
        (fname, lineno, code)
        for fname, lineno, code in call_sites
        if code not in NOTICE_LABELS
    ]
    assert not unlabeled, (
        "notice_redirect(...) call site(s) use a code with no NOTICE_LABELS "
        f"entry: {unlabeled}"
    )
