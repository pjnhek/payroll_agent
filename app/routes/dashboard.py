"""GET /, /eval, /eval/chart.svg — dashboard views."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from app.db import repo
from app.routes.demo import DEMO_FIXTURES, SEED_BUSINESS_IDS, SEED_CONTACTS, resolve_operator_email
from app.routes.operator_feedback import notice_label
from app.routes.templating import templates

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

# The eval view's two on-disk inputs. Module-level (not function-local) so tests can
# redirect them with monkeypatch.setattr — the same seam eval/run_eval.py's FIXTURE_DIR /
# SUMMARY_PATH constants provide. They stay RELATIVE: a Path built at import time stores
# the relative string and resolves against the cwd at I/O time, so this is behaviour-
# identical to building them inside the request handler (the container sets WORKDIR=/app).
EVAL_SUMMARY_PATH = Path("eval/summary.json")
EVAL_FIXTURES_DIR = Path("eval/fixtures")

# The landing page's primary action fires this fixture through /demo/send-test. Named as
# a module constant rather than a template literal because /demo/send-test:267-269
# silently falls back to DEMO_FIXTURE_DEFAULT_KEY (coastal_exact, a clean exact-match
# run) on any key not present in DEMO_FIXTURES — a rename inside that allowlist would
# therefore swap the page's demonstrated refusal for its exact opposite with nothing
# failing anywhere. A test pins this key to the allowlist and to the fixture's own
# expected.decision.final_action == "request_clarification".
LANDING_GATE_FIXTURE_KEY = "unknown_shorthand_metro"


def _gate_fixture_body() -> str:
    """Read the gate fixture's own email body verbatim, for the landing page's proof section.

    Total: a missing key, an OSError, a malformed/non-dict JSON payload, or a non-string
    body_text all return the empty string rather than raising, because this runs on the
    route an evaluator hits first and a broken fixture must cost the page its evidence
    block, not its response. The path is resolved from DEMO_FIXTURES[LANDING_GATE_FIXTURE_KEY]
    — a server-owned constant — and never from a request value, so no query parameter or
    form field can steer this read.
    """
    try:
        fixture_meta = DEMO_FIXTURES[LANDING_GATE_FIXTURE_KEY]
        fixture_path = Path(fixture_meta["path"])
        raw = json.loads(fixture_path.read_text())
    except (KeyError, OSError, ValueError):
        return ""
    if not isinstance(raw, dict):
        return ""
    body_text = raw.get("body_text")
    if not isinstance(body_text, str):
        return ""
    return body_text


# ---------------------------------------------------------------------------
# GET / — recruiter landing page (self-serve demo, Path-1 in-app composer)
# ---------------------------------------------------------------------------


@router.get("/")
def landing(
    request: Request,
    business: str = Query(default=""),
    bound: str = Query(default=""),
    notice: str = Query(default=""),
) -> Response:
    """Recruiter landing page with business picker + in-app composer.

    GET /: shows all three businesses; defaults to the first in list.
    GET /?business=<name>: shows the selected business's roster.

    The /demo/bind form is NOT on this page — it is an unlinked operator URL.
    The currently-armed binding (if any) is displayed read-only.
    """
    try:
        businesses = repo.list_businesses()
    except Exception:
        logger.debug("list_businesses unavailable — rendering empty picker")
        businesses = []

    # Resolve selected business name: prefer ?business= query param, else first in list.
    if business in SEED_CONTACTS:
        selected_business_name = business
    elif businesses:
        selected_business_name = businesses[0]["name"]
    else:
        selected_business_name = ""

    # Resolve employees for the selected business (no DB call if name not in seed IDs).
    employees = []
    if selected_business_name in SEED_BUSINESS_IDS:
        selected_business_id = SEED_BUSINESS_IDS[selected_business_name]
        try:
            roster = repo.load_roster_for_business(selected_business_id)
            employees = roster.employees
        except Exception:
            logger.debug("load_roster_for_business unavailable for %s", selected_business_name)

    # Read-only armed business display (Path-2 state), gated on bound == "1" so the
    # get_demo_binding lookup — and the operator confirmation it feeds — never reaches
    # a plain visitor. Only the /demo/bind redirect (GET /?bound=1) triggers this read,
    # which also drops one DB round-trip from every other landing render.
    armed_business_id = None
    armed_business_name = None
    if bound == "1":
        try:
            armed_business_id = repo.get_demo_binding(resolve_operator_email())
        except Exception:
            armed_business_id = None

        # Resolve the armed business_id to its human name HERE (not in the template): a
        # Jinja `{% set %}` inside a `{% for %}` does not escape the loop scope, so the
        # template's match always fell back to showing the raw UUID. Match in Python so
        # the landing page shows "Metro Deli Group", not "b0000002-…".
        if armed_business_id is not None:
            armed_business_name = next(
                (b["name"] for b in businesses if str(b["id"]) == str(armed_business_id)),
                None,
            )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "businesses": businesses,
            "selected_business_name": selected_business_name,
            "employees": employees,
            "armed_business_id": armed_business_id,
            "armed_business_name": armed_business_name,
            "bound": bound,
            "notice_label": notice_label(notice),
            "gate_fixture_key": LANDING_GATE_FIXTURE_KEY,
            "gate_fixture_body": _gate_fixture_body(),
        },
    )


# ---------------------------------------------------------------------------
# GET /eval — eval view with headline metrics + chart + per-fixture drill-in (DASH-04)
# ---------------------------------------------------------------------------


@router.get("/eval")
def eval_view(request: Request) -> Response:
    """DASH-04: Render the eval view. Hermetic disk read of committed eval artifacts.

    Enriches each per_fixture record with raw_body loaded from the committed fixture
    file at eval/fixtures/<fixture_path>. eval/summary.json does NOT store body_text —
    the body lives in the fixture files, so without this join the drill-in table would
    show a placeholder dash instead of each fixture's raw email body.
    """
    summary_path = EVAL_SUMMARY_PATH
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None

    if summary is not None and "per_fixture" in summary:
        fixtures_root = EVAL_FIXTURES_DIR.resolve()
        for fixture in summary["per_fixture"]:
            # fixture_path is data, not code: a relative-parent path would otherwise read a
            # file outside the fixtures directory and render it here. Resolve the join and
            # refuse anything that escapes the fixtures root — a refusal is indistinguishable
            # from a missing file, so it reuses the same placeholder and adds no error path.
            # resolve() collapses "..", rejects absolute paths via the containment check, and
            # follows symlinks BEFORE the check, so a symlink out of the tree is caught too.
            #
            # THREAT MODEL — the check is deliberately not TOCTOU-safe. A race between
            # resolve() and read_text() is only exploitable by someone who can already write
            # into eval/fixtures/ on the running container, which means they already have code
            # execution. The fixtures are committed artifacts baked into the image on an
            # ephemeral filesystem. Hardening this with openat/O_NOFOLLOW would buy nothing
            # against an attacker who is already inside. Filesystem mutation is out of scope.
            fixture_file = (EVAL_FIXTURES_DIR / fixture["fixture_path"]).resolve()
            if fixture_file.is_relative_to(fixtures_root) and fixture_file.exists():
                fixture_data = json.loads(fixture_file.read_text())
                fixture["raw_body"] = fixture_data.get("body_text", "")
            else:
                fixture["raw_body"] = "‹fixture file missing›"

    return templates.TemplateResponse(
        request,
        "eval.html",
        {
            "summary": summary,
            "demo_fixtures": DEMO_FIXTURES,
        },
    )


# ---------------------------------------------------------------------------
# GET /eval/chart.svg — serve the committed eval chart
# ---------------------------------------------------------------------------


@router.get("/eval/chart.svg")
def eval_chart() -> FileResponse:
    """Serve the committed eval/chart.svg as image/svg+xml.

    The chart is baked into the image at build time, not generated per request. The
    path is relative, so it only resolves if the container keeps WORKDIR=/app
    (Dockerfile) — change that and this route 404s in production but passes locally.
    """
    chart_path = Path("eval/chart.svg")
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="eval/chart.svg not found")
    return FileResponse(str(chart_path), media_type="image/svg+xml")
