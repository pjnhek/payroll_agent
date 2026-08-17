"""GUARD-05's response-level half: the six unauthenticated service routes
never answer with an HTML content-type.

`/health/live` is Render's own healthCheckPath target and `/internal/pump`
is the sole execution trigger for the durable job queue on a platform with
no background-worker primitive (v4, PUMP-01). If either ever answered
200+HTML — the exact failure mode a root-mounted catch-all SPA shell would
introduce — Render would mark a broken deploy healthy while `pump.yml`'s
`curl -f` goes green and the durable queue is never drained: a frontend
routing choice silently voiding v4's durability guarantee.

Asserted on content-type only, never status code: these routes legitimately
return 4xx without credentials or a signature (`/webhook/inbound` needs a
valid Svix signature, `/internal/pump` needs a bearer token), so a
status-code assertion would not distinguish "correctly rejected" from
"served an HTML error page instead of a rejection body."

Reuses the existing hermetic `client`/`fake_repo` fixtures — no live
database, no live provider.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

_SERVICE_ROUTES: list[tuple[str, str]] = [
    ("/webhook/inbound", "POST"),
    ("/health/live", "GET"),
    ("/health/ready", "GET"),
    ("/health/queue", "GET"),
    ("/health/schema", "GET"),
    ("/internal/pump", "GET"),
]


@pytest.mark.parametrize("path,method", _SERVICE_ROUTES, ids=[p for p, _ in _SERVICE_ROUTES])
def test_service_route_never_answers_html(
    path: str, method: str, client: TestClient, fake_repo
) -> None:
    """Every service route's content-type header never carries `text/html`,
    regardless of the (possibly 4xx, credential-less) status it returns."""
    response = client.request(method, path)
    content_type = response.headers.get("content-type", "")
    assert "text/html" not in content_type, (
        f"{method} {path} answered with content-type {content_type!r} "
        f"(status {response.status_code}) — a catch-all mount would produce "
        "exactly this shape"
    )
