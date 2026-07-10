"""GET /, /eval, /eval/chart.svg — dashboard views (D-06).

Carved out of app/main.py (Phase 13 Plan 03).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from app.db import repo
from app.routes.demo import DEMO_FIXTURES, DEMO_OPERATOR_EMAIL, SEED_BUSINESS_IDS, SEED_CONTACTS
from app.routes.templating import templates

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()


# ---------------------------------------------------------------------------
# GET / — recruiter landing page (self-serve demo, Path-1 in-app composer)
# ---------------------------------------------------------------------------


@router.get("/")
def landing(
    request: Request,
    business: str = Query(default=""),
    bound: str = Query(default=""),
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

    # Read-only armed business display (Path-2 state).
    try:
        armed_business_id = repo.get_demo_binding(DEMO_OPERATOR_EMAIL)
    except Exception:
        armed_business_id = None

    # Resolve the armed business_id to its human name HERE (not in the template): a
    # Jinja `{% set %}` inside a `{% for %}` does not escape the loop scope, so the
    # template's match always fell back to showing the raw UUID. Match in Python so the
    # landing page shows "Metro Deli Group", not "b0000002-…".
    armed_business_name = None
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
            "demo_operator_email": DEMO_OPERATOR_EMAIL,
        },
    )


# ---------------------------------------------------------------------------
# DASH-04: GET /eval — eval view with headline metrics + chart + per-fixture drill-in
# ---------------------------------------------------------------------------


@router.get("/eval")
def eval_view(request: Request) -> Response:
    """DASH-04: Render the eval view. Hermetic disk read of committed eval artifacts.

    R2-MEDIUM fix: enriches each per_fixture record with raw_body loaded from the
    committed fixture file at eval/fixtures/<fixture_path>. eval/summary.json does
    NOT store body_text — the body lives in the fixture files. Rendering '—' does
    NOT satisfy DASH-04; each fixture's raw body is shown in the drill-in table.
    """
    summary_path = Path("eval/summary.json")
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None

    if summary is not None and "per_fixture" in summary:
        fixtures_dir = Path("eval/fixtures")
        for fixture in summary["per_fixture"]:
            fixture_file = fixtures_dir / fixture["fixture_path"]
            if fixture_file.exists():
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

    # D-21: serves committed eval/chart.svg baked into image; relative path requires
    # WORKDIR=/app (Dockerfile).
    """
    chart_path = Path("eval/chart.svg")
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="eval/chart.svg not found")
    return FileResponse(str(chart_path), media_type="image/svg+xml")
