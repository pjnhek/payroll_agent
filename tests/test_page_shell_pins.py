"""Per-page `<title>` and single-`aria-current` nav pins (SHELL-10).

This is the repo's FIRST `<title>` coverage — every prior phase has pinned
`aria-current` (test_dashboard.py's `test_nav_marks_current_page_with_aria_
current`, covering `/`, `/runs`, `/eval`) and script-free nav
(test_ops_route.py's `test_ops_nav_has_four_entries_in_order`) but never the
per-page title contract, and never the `/runs/{id}` nav state at all.

`/runs` and `/runs/{uuid}` are adjacent nav states that both resolve to the
Runs link (`base.html`'s `nav_path.startswith('/runs/')` condition) — this
module is what proves that adjacency never produces two matches or zero,
which is the one nav state prior coverage never touched.

Every test here renders through the real routes with the hermetic
`client`/`fake_repo` fixtures — no live database. `aria-current` counts are
scoped to the `<nav>...</nav>` region only, never the whole document, so a
future page that legitimately uses the attribute inside page content does
not make this pin unsatisfiable.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.routes.templating import templates

# The bare base.html fallback (`{% block title %}Pyrl{% endblock %}`) — every
# operator-facing page must declare a title distinct from this.
_BASE_FALLBACK_TITLE = "Pyrl"

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.DOTALL)


def _extract_title(html: str) -> str:
    match = _TITLE_RE.search(html)
    assert match is not None, "response carries no <title> element at all"
    return match.group(1).strip()


def _extract_nav_html(html: str) -> str:
    """The `<nav>...</nav>` region only — mirrors the idiom already
    established in tests/test_ops_route.py::test_ops_nav_has_four_entries_
    in_order, so `aria-current` counts here can never be inflated by a
    future page that legitimately uses the attribute inside `{% block
    content %}`."""
    assert "<nav>" in html and "</nav>" in html, "response carries no <nav> element"
    nav_start = html.index("<nav>")
    nav_end = html.index("</nav>")
    return html[nav_start:nav_end]


@pytest.mark.parametrize("path", ["/", "/runs", "/eval", "/ops"])
def test_every_operator_page_declares_a_distinct_title(
    path: str, client: TestClient, fake_repo
) -> None:
    """Each operator-facing page's rendered `<title>` is non-empty and is
    not the bare base fallback. Parametrized by path so a new converted
    page joins this coverage by adding one row."""
    response = client.get(path)
    assert response.status_code == 200, f"GET {path} must return 200"
    title = _extract_title(response.text)
    assert title, f"GET {path} rendered an empty <title>"
    assert title != _BASE_FALLBACK_TITLE, (
        f"GET {path} rendered the bare base fallback title {title!r} — it "
        "must declare its own {% block title %}"
    )


def test_missing_title_block_falls_back_to_the_base_title() -> None:
    """A template that extends the base layout and declares no `{% block
    title %}` renders the bare base fallback ('Pyrl'). Pins the empty case
    explicitly rather than assuming it, through the SAME shared
    `Jinja2Templates` instance every real route renders through — not a
    separate, disconnected Environment."""

    class _FakeURL:
        path = "/throwaway-page-declaring-no-title-block"

    class _FakeRequest:
        url = _FakeURL()

    throwaway = templates.env.from_string(
        '{% extends "base.html" %}{% block content %}<p>no title block here</p>{% endblock %}'
    )
    rendered = throwaway.render(request=_FakeRequest())
    assert _extract_title(rendered) == _BASE_FALLBACK_TITLE, (
        "a template with no {% block title %} must fall back to the bare base title"
    )


def test_exactly_one_aria_current_per_page(client: TestClient, fake_repo) -> None:
    """`/`, `/runs`, `/runs/<uuid>`, `/eval`, and `/ops` each mark exactly
    one nav item `aria-current="page"` — never two, never zero. `/runs` and
    `/runs/{uuid}` are adjacent nav states that both resolve to the Runs
    link; this is the one adjacency prior coverage never exercised."""
    business_id = next(iter(fake_repo.contact_to_business.values()))
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)

    paths = ["/", "/runs", f"/runs/{run_id}", "/eval", "/ops"]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200, f"GET {path} must return 200"
        nav_html = _extract_nav_html(response.text)
        count = nav_html.count('aria-current="page"')
        assert count == 1, (
            f'GET {path} must mark exactly one nav item aria-current="page" '
            f"within the <nav> region; found {count}"
        )


def test_nav_link_order_is_unchanged(client: TestClient, fake_repo) -> None:
    """The ordered nav link labels are Pyrl, Runs, Eval, Ops — unchanged by
    any conversion."""
    response = client.get("/")
    assert response.status_code == 200
    nav_html = _extract_nav_html(response.text)
    labels = re.findall(r"<a[^>]*>([^<]+)</a>", nav_html)
    assert labels == ["Pyrl", "Runs", "Eval", "Ops"], (
        f"expected nav link order ['Pyrl', 'Runs', 'Eval', 'Ops'], got {labels}"
    )
