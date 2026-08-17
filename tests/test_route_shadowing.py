"""Route-table structural guards (GUARD-05's route-table half).

v5 replaces the "no SPA" architecture with per-page React islands whose
built assets land under the ONE `/static` mount that already exists
(`app/main.py:11`). The rejected alternative — a client-side catch-all
route serving `index.html` for every unmatched path — would silently
shadow every service route behind it: `/health/live` and `/internal/pump`
would answer 200+HTML, making Render mark a broken deploy healthy while
`pump.yml`'s `curl -f` goes green and the durable queue is never drained.
These tests assert that shape can never land, and are demonstrated red
under a real injected root mount.

Reads the live route table from `app.main.app` — never a hand-maintained
path list, so the registry stays the source of truth instead of the prose
describing it.

FastAPI 0.138's lazy-include routing wraps every `include_router()` call in
an internal wrapper object whose own `matches()` discards the child scope,
so `app.router.routes` cannot be walked directly to find which concrete
route a request resolves to. `_flatten_routes` below resolves through that
wrapper via its `effective_route_contexts()` method (detected by duck
typing, not by importing the underscore-prefixed class name, so a FastAPI
upgrade degrades to "treat it as an opaque route" rather than an
ImportError) to reach the real `APIRoute` objects FastAPI actually
dispatches to, in true registration order.
"""
from __future__ import annotations

from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Match, Mount

from app.main import app
from app.routes.dashboard import eval_view, landing
from app.routes.health import health_live, health_queue, health_ready, health_schema
from app.routes.ops import ops_view
from app.routes.pump import pump as _pump_endpoint
from app.routes.runs import runs_list
from app.routes.webhook import inbound


def _flatten_routes(application: Any) -> list[Any]:
    """Resolve `application.router.routes` into the true ordered dispatch
    list, descending into any FastAPI lazy-include wrapper to reach the
    concrete route objects. See the module docstring for why this is
    necessary rather than walking `application.router.routes` directly."""
    flat: list[Any] = []
    for route in application.router.routes:
        if hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                flat.append(ctx.original_route)
        else:
            flat.append(route)
    return flat


def _first_matching_route(flat_routes: list[Any], scope: dict[str, Any]) -> Any | None:
    """The first route in `flat_routes` whose `matches(scope)` is not
    `Match.NONE` — the literal "first non-NONE wins" precedence this guard
    asserts, over the exact live-registered route objects."""
    for route in flat_routes:
        match, _child_scope = route.matches(scope)
        if match is not Match.NONE:
            return route
    return None


# The ten reserved paths every route on this table must resolve correctly,
# each paired with its expected HTTP method and the concrete endpoint
# function object a request must resolve to. Asserted on the endpoint
# object, never on a status code: a catch-all mount serving `html=True`
# returns 200 for everything, which makes a status-code assertion useless.
_RESERVED_PATH_EXPECTATIONS: list[tuple[str, str, Any]] = [
    ("/webhook/inbound", "POST", inbound),
    ("/health/live", "GET", health_live),
    ("/health/ready", "GET", health_ready),
    ("/health/queue", "GET", health_queue),
    ("/health/schema", "GET", health_schema),
    ("/internal/pump", "GET", _pump_endpoint),
    ("/ops", "GET", ops_view),
    ("/runs", "GET", runs_list),
    ("/eval", "GET", eval_view),
    ("/", "GET", landing),
]


def test_only_mount_is_static() -> None:
    """The sole `starlette.routing.Mount` in the live route table is
    `/static` (`app/main.py:11`). A second mount, in either registration
    order, reds — the mechanism by which a catch-all SPA shell would
    shadow every service route behind it."""
    mounts = [route for route in app.router.routes if isinstance(route, Mount)]
    assert [m.path for m in mounts] == ["/static"], (
        f"expected the sole Mount to be ['/static'], found {[m.path for m in mounts]}"
    )


def test_no_route_shadows_a_reserved_prefix() -> None:
    """For each reserved path, the FIRST route that matches an ASGI scope
    built for it is the expected concrete endpoint — never a route
    registered ahead of it, and never a Mount answering on its behalf."""
    flat = _flatten_routes(app)
    for path, method, expected_endpoint in _RESERVED_PATH_EXPECTATIONS:
        scope = {"type": "http", "path": path, "method": method}
        matched = _first_matching_route(flat, scope)
        assert matched is not None, f"no route matched {method} {path}"
        assert isinstance(matched, APIRoute), (
            f"{method} {path} matched a non-APIRoute route {matched!r} — a "
            "catch-all mount would shadow it exactly like this"
        )
        assert matched.endpoint is expected_endpoint, (
            f"{method} {path} resolved to {matched.endpoint!r}, expected "
            f"{expected_endpoint!r} — a route was registered ahead of it"
        )


def test_no_path_converter_route_exists() -> None:
    """No registered route's path declares a `:path` converter segment —
    the Starlette catch-all idiom (`{full_path:path}`) that would swallow
    every request behind it, HTML or otherwise."""
    for route in _flatten_routes(app):
        path = getattr(route, "path", None)
        if path is None:
            continue
        assert ":path" not in path, (
            f"{path} declares a :path converter segment — a catch-all "
            "route that would shadow every path registered behind it"
        )


def test_unregistered_path_is_not_swallowed(client: TestClient) -> None:
    """A path matching no registered router returns 404 with a non-HTML
    content-type — the structural signature of an absent catch-all. A
    root-mounted SPA shell would instead answer 200 with `text/html` for
    literally any path."""
    response = client.get("/does-not-exist")
    assert response.status_code == 404, (
        f"expected 404 for an unregistered path, got {response.status_code}"
    )
    content_type = response.headers.get("content-type", "")
    assert "text/html" not in content_type, (
        f"unregistered path answered with content-type {content_type!r} — "
        "a catch-all is swallowing 404s as an HTML shell"
    )


def test_router_registration_order_is_unchanged() -> None:
    """The ordered list of distinct router modules reachable from the live
    route table still begins with health and webhook ahead of runs — so a
    future registration cannot be inserted in front of the service routes
    (`app/main.py`'s health, webhook, runs, dashboard, demo, pump, ops
    order)."""
    modules: list[str] = []
    for route in _flatten_routes(app):
        endpoint = getattr(route, "endpoint", None)
        if endpoint is None:
            continue
        module = endpoint.__module__
        if not modules or modules[-1] != module:
            modules.append(module)
    assert "app.routes.health" in modules, f"health router missing from {modules}"
    assert "app.routes.webhook" in modules, f"webhook router missing from {modules}"
    assert "app.routes.runs" in modules, f"runs router missing from {modules}"
    assert modules.index("app.routes.health") < modules.index("app.routes.runs"), (
        f"health router must register ahead of runs; got order {modules}"
    )
    assert modules.index("app.routes.webhook") < modules.index("app.routes.runs"), (
        f"webhook router must register ahead of runs; got order {modules}"
    )
