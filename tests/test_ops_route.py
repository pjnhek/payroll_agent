"""GET /ops — the transport-surface view.

Hermetic route tests, no live DB. Covers the render, the DB-unavailable
fallback, the per-panel context, the nav's fourth entry, the as-of stamp,
the alarm banner's present/absent states, the bounded dead-letter
projection, and — the strengthened half of this suite — a read-only
contract proved two ways at once:

* the positive half asserts the five facade reads the page depends on were
  genuinely invoked, so a panel silently rendering a hardcoded default
  instead of real data reds;
* the negative half enumerates the facade's mutation surface directly from
  `app.db.repo.__all__` (everything that is NOT one of the five reads) and
  patches every one of those names to raise if called, so any write this
  route performs today — or one a future edit adds — reds this test by
  construction, without a human having to anticipate which name to check.

"No write happened" is otherwise an unfalsifiable claim: unless calling a
writer would have failed the test, the assertion proves nothing.
"""
from __future__ import annotations

import pathlib
import re
from collections.abc import Iterable, Iterator
from typing import Any

import yaml
from fastapi.testclient import TestClient

import app.db.repo as repo_mod
from app.config import get_settings
from app.main import app
from app.routes import ops

client = TestClient(app, raise_server_exceptions=False)

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_PUMP_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "pump.yml"

# The exact five side-effect-free facade reads the route depends on.
_READ_NAMES = frozenset(
    {
        "count_jobs_by_state",
        "oldest_due_pending_age_seconds",
        "attempts_distribution",
        "list_dead_letter_jobs",
        "list_unaccounted_error_runs",
    }
)


def _recording_read(name: str, calls: set[str]):
    """A stand-in for one of the five reads that records it was called and
    returns a minimal, correctly-shaped value so the template renders."""

    def _fn(*args, **kwargs):
        calls.add(name)
        if name == "count_jobs_by_state":
            return {"pending": 0, "leased": 0}
        if name == "oldest_due_pending_age_seconds":
            return None
        if name == "attempts_distribution":
            return []
        return []

    return _fn


def _raise_if_called(name: str):
    """A stand-in for a facade function this route must never invoke."""

    def _fn(*args, **kwargs):
        raise AssertionError(
            f"GET /ops must be read-only, but it called {name!r} — "
            "a mutation function on the facade."
        )

    return _fn


def _flatten_routes(routes: Iterable[Any]) -> Iterator[Any]:
    """FastAPI wraps each included router in a lazy container whose concrete
    routes live on `.original_router.routes` rather than directly on
    `app.routes`; walk through that indirection to reach real endpoints."""
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            yield from _flatten_routes(original_router.routes)
        else:
            yield route


# ---------------------------------------------------------------------------
# Basic render + cold-start tolerance
# ---------------------------------------------------------------------------


def test_ops_returns_200_and_renders_template(fake_repo):
    response = client.get("/ops")
    assert response.status_code == 200
    assert "Transport Ops" in response.text


def test_ops_renders_200_with_db_unavailable(monkeypatch):
    """With every read raising (DB unavailable), the route still renders
    200 with zeroed/empty metrics instead of a 500 — matching runs_list's
    cold-start tolerance."""

    def _boom(*args, **kwargs):
        raise RuntimeError("no pool")

    for name in _READ_NAMES:
        monkeypatch.setattr(repo_mod, name, _boom, raising=False)

    response = client.get("/ops")
    assert response.status_code == 200
    assert "No due pending work" in response.text
    assert "No open jobs." in response.text
    assert "No dead-lettered jobs." in response.text


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_ops_is_registered_exactly_once_as_a_get_route():
    all_routes = list(_flatten_routes(app.routes))
    paths = sorted({r.path for r in all_routes if getattr(r, "path", "") == "/ops"})
    assert paths == ["/ops"]
    get_routes = [
        r
        for r in all_routes
        if getattr(r, "path", "") == "/ops" and "GET" in getattr(r, "methods", set())
    ]
    assert len(get_routes) == 1


# ---------------------------------------------------------------------------
# Context keys reach the template
# ---------------------------------------------------------------------------


def test_ops_context_keys_reach_the_template(fake_repo, monkeypatch):
    """Every value the route puts in the template context is genuinely
    visible in the rendered page — not merely computed and discarded."""
    monkeypatch.setattr(
        repo_mod, "count_jobs_by_state", lambda conn=None: {"pending": 7, "leased": 4}
    )
    monkeypatch.setattr(
        repo_mod, "oldest_due_pending_age_seconds", lambda conn=None: 42.0
    )
    monkeypatch.setattr(repo_mod, "attempts_distribution", lambda conn=None: [(3, 9)])
    monkeypatch.setattr(
        repo_mod,
        "list_dead_letter_jobs",
        lambda limit=50, conn=None: [
            {
                "id": "job-x",
                "kind": "pipeline",
                "run_id": None,
                "attempts": 5,
                "max_attempts": 5,
                "last_error": "provider timeout",
                "updated_at": None,
            }
        ],
    )
    unaccounted_run_id = "33333333-3333-3333-3333-333333333333"
    monkeypatch.setattr(
        repo_mod,
        "list_unaccounted_error_runs",
        lambda limit=50, conn=None: [
            {"id": unaccounted_run_id, "error_reason": "timeout", "updated_at": None}
        ],
    )

    response = client.get("/ops")
    body = response.text
    assert response.status_code == 200
    assert "7" in body  # pending_count
    assert "4" in body  # leased_count
    assert "9" in body  # attempts_rows' count
    assert "provider timeout" in body  # dead_letter_rows' last_error
    assert unaccounted_run_id in body  # unaccounted_error_rows
    assert str(get_settings().max_attempts) in body  # max_attempts bound
    assert str(ops.PUMP_CADENCE_MINUTES) in body  # pump_cadence_minutes bound


# ---------------------------------------------------------------------------
# Panel content
# ---------------------------------------------------------------------------


def test_ops_context_carries_depth_split_not_a_combined_total(fake_repo, monkeypatch):
    monkeypatch.setattr(
        repo_mod, "count_jobs_by_state", lambda conn=None: {"pending": 3, "leased": 2}
    )
    response = client.get("/ops")
    assert response.status_code == 200
    assert ">3<" in response.text
    assert ">2<" in response.text
    # The split is the point: no combined "5" total anywhere in the page.
    assert ">5<" not in response.text


def test_ops_renders_attempts_distribution_against_max_attempts(fake_repo, monkeypatch):
    monkeypatch.setattr(
        repo_mod, "attempts_distribution", lambda conn=None: [(1, 4), (2, 1)]
    )
    response = client.get("/ops")
    assert response.status_code == 200
    assert "1 of 5" in response.text
    assert "2 of 5" in response.text


def test_ops_renders_oldest_due_pending_bound(fake_repo, monkeypatch):
    monkeypatch.setattr(
        repo_mod, "oldest_due_pending_age_seconds", lambda conn=None: 125.0
    )
    response = client.get("/ops")
    assert response.status_code == 200
    assert "min" in response.text
    assert f"{ops.PUMP_CADENCE_MINUTES}-minute cadence" in response.text


def test_ops_renders_no_due_pending_work_not_a_zero(fake_repo, monkeypatch):
    monkeypatch.setattr(repo_mod, "oldest_due_pending_age_seconds", lambda conn=None: None)
    response = client.get("/ops")
    assert response.status_code == 200
    assert "No due pending work" in response.text


def test_ops_dead_letter_row_links_to_run_detail(fake_repo, monkeypatch):
    run_id = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setattr(
        repo_mod,
        "list_dead_letter_jobs",
        lambda limit=50, conn=None: [
            {
                "id": "job-1",
                "kind": "pipeline",
                "run_id": run_id,
                "attempts": 5,
                "max_attempts": 5,
                "last_error": "provider timeout",
                "updated_at": None,
            }
        ],
    )
    response = client.get("/ops")
    assert response.status_code == 200
    assert f"/runs/{run_id}" in response.text


def test_ops_dead_letter_row_with_no_run_id_renders_no_link(fake_repo, monkeypatch):
    monkeypatch.setattr(
        repo_mod,
        "list_dead_letter_jobs",
        lambda limit=50, conn=None: [
            {
                "id": "job-2",
                "kind": "ingest",
                "run_id": None,
                "attempts": 5,
                "max_attempts": 5,
                "last_error": "malformed webhook payload",
                "updated_at": None,
            }
        ],
    )
    response = client.get("/ops")
    assert response.status_code == 200
    assert "malformed webhook payload" in response.text
    assert "/runs/None" not in response.text


def test_ops_dead_letter_projects_only_the_bounded_fields(fake_repo, monkeypatch):
    """No lease token, dedup key, or payload value may cross into the page,
    even if a future repo edit widens the dict a mocked/real read hands the
    template — the template itself must reference only the bounded fields
    by name, not forward whatever a row happens to carry."""
    monkeypatch.setattr(
        repo_mod,
        "list_dead_letter_jobs",
        lambda limit=50, conn=None: [
            {
                "id": "job-3",
                "kind": "outbound_send",
                "run_id": None,
                "attempts": 5,
                "max_attempts": 5,
                "last_error": "provider timeout",
                "updated_at": None,
                # Fields the real projection never includes — present here
                # only to prove the template does not forward extra keys.
                "lease_token": "SECRET-LEASE-TOKEN-ABC123",
                "dedup_key": "dedupe-xyz-999",
                "payload": {"ssn": "123-45-6789"},
            }
        ],
    )
    response = client.get("/ops")
    body = response.text
    assert "SECRET-LEASE-TOKEN-ABC123" not in body
    assert "dedupe-xyz-999" not in body
    assert "123-45-6789" not in body


# ---------------------------------------------------------------------------
# The alarm banner
# ---------------------------------------------------------------------------


def test_ops_alarm_banner_absent_when_no_unaccounted_errors(fake_repo, monkeypatch):
    monkeypatch.setattr(repo_mod, "list_unaccounted_error_runs", lambda limit=50, conn=None: [])
    response = client.get("/ops")
    assert response.status_code == 200
    assert "ops-alarm-banner" not in response.text


def test_ops_alarm_banner_present_and_links_to_the_run(fake_repo, monkeypatch):
    run_id = "22222222-2222-2222-2222-222222222222"
    monkeypatch.setattr(
        repo_mod,
        "list_unaccounted_error_runs",
        lambda limit=50, conn=None: [
            {"id": run_id, "error_reason": "extraction_failed", "updated_at": None}
        ],
    )
    response = client.get("/ops")
    assert response.status_code == 200
    assert "ops-alarm-banner" in response.text
    assert f"/runs/{run_id}" in response.text
    assert "no job" in response.text.lower()
    # No acknowledge/mute/dismiss control anywhere in the markup — the page
    # renders no interactive control of any kind (no form, no button).
    assert "<form" not in response.text
    assert "<button" not in response.text
    assert "acknowledge" not in response.text.lower()


# ---------------------------------------------------------------------------
# Nav, as-of stamp, no polling
# ---------------------------------------------------------------------------


def test_ops_nav_has_four_entries_in_order(fake_repo):
    response = client.get("/ops")
    body = response.text
    nav_start = body.index("<nav>")
    nav_end = body.index("</nav>")
    nav_html = body[nav_start:nav_end]
    order = [href for href in ("/", "/runs", "/eval", "/ops") if f'href="{href}"' in nav_html]
    assert order == ["/", "/runs", "/eval", "/ops"]


def test_ops_as_of_stamp_present(fake_repo):
    response = client.get("/ops")
    assert "As of" in response.text


def test_ops_page_has_no_script_or_polling(fake_repo):
    response = client.get("/ops")
    assert "<script" not in response.text
    assert "setInterval" not in response.text
    assert "meta http-equiv=\"refresh\"" not in response.text.lower()


# ---------------------------------------------------------------------------
# Read-only contract — positive half: every one of the five reads is called
# ---------------------------------------------------------------------------


def test_ops_route_calls_all_five_reads(monkeypatch):
    calls: set[str] = set()
    for name in _READ_NAMES:
        monkeypatch.setattr(repo_mod, name, _recording_read(name, calls), raising=False)

    response = client.get("/ops")
    assert response.status_code == 200
    assert calls == _READ_NAMES, (
        f"expected all five reads called, got {calls} — a panel may be "
        "rendering a hardcoded default instead of real data"
    )


# ---------------------------------------------------------------------------
# Read-only contract — negative half: every OTHER facade name must never
# be invoked, derived from app.db.repo.__all__ rather than hand-picked.
# ---------------------------------------------------------------------------


def test_ops_route_never_calls_any_facade_mutation(fake_repo, monkeypatch):
    mutation_names = [
        name
        for name in repo_mod.__all__
        if name not in _READ_NAMES and callable(getattr(repo_mod, name))
    ]
    # Sanity: the facade must expose real mutation surface beyond the five
    # reads, or this guard would vacuously pass.
    assert len(mutation_names) > 50

    for name in mutation_names:
        monkeypatch.setattr(repo_mod, name, _raise_if_called(name), raising=False)

    response = client.get("/ops")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# The pump-cadence constant is pinned against the workflow that sets it
# ---------------------------------------------------------------------------


def test_pump_cadence_minutes_pinned_to_workflow_cron():
    workflow = yaml.safe_load(_PUMP_WORKFLOW.read_text())
    # YAML 1.1 parses a bare `on:` top-level key as the boolean True, not the
    # string "on" — a well-known GitHub Actions workflow parsing trap.
    triggers = workflow.get("on", workflow.get(True))
    cron_expr = triggers["schedule"][0]["cron"]
    minute_field = cron_expr.split()[0]
    match = re.fullmatch(r"\*/(\d+)", minute_field)
    assert match, f"unexpected cron minute field: {minute_field!r}"
    assert int(match.group(1)) == ops.PUMP_CADENCE_MINUTES, (
        "the pump workflow's cadence and the constant the /ops page renders "
        "as a bound have drifted apart"
    )
