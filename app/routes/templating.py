"""Shared Jinja2Templates instance + badge class/label filters.

Every router that renders a TemplateResponse imports `templates` from this
module, so there is exactly one Jinja2Templates instance for the whole app.

Also owns the React page shell plumbing: the Vite manifest loader, the
`json_script()` XSS-safe data-island serializer, and `render_react_page()` --
the one function every React-rendered route calls through.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fastapi import Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import BaseModel

from app.config import get_settings

templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# React page shell: Vite manifest loading, the JSON data island, and the one
# shared render_react_page() entrypoint every React-rendered route calls.
# ---------------------------------------------------------------------------

# The DOM id of the embedded JSON data island every React entry reads its
# initial page data from. Must match frontend/src/boot/pageData.ts's
# INITIAL_DATA_ELEMENT_ID exactly -- there is no automatic cross-language
# sharing of this literal, so a change here requires the matching TS change.
INITIAL_DATA_ELEMENT_ID = "__INITIAL_DATA__"

# The DOM id of the element a React entry mounts its root into. Must match
# the literal `document.getElementById(...)` call in every frontend/src/entries/*.tsx
# module.
REACT_MOUNT_ID = "react-root"


class ManifestMissingError(RuntimeError):
    """The Vite build manifest is absent -- fail closed rather than render a
    bundle-less shell. Raised by a missing manifest FILE and by a manifest
    that does not carry the requested entry's chunk."""


# Relative to the app's WORKDIR (see Dockerfile's WORKDIR=/app rationale),
# matching the real path recorded in frontend/MANIFEST-SHAPE.md from an
# actual `npm run build`: app/static/dist/.vite/manifest.json. A module-level
# variable (not a constant baked into load_manifest's body) so tests can
# monkeypatch it to point at the committed fixture manifest.
MANIFEST_PATH: Path = Path("app/static/dist/.vite/manifest.json")


@lru_cache
def load_manifest() -> MappingProxyType[str, Any]:
    """Load and cache the Vite build manifest as a read-only mapping.

    Raises ManifestMissingError when the manifest file is absent -- a
    bundle-less production deploy is a 500, never a silently blank console.
    Cached (and clearable via `load_manifest.cache_clear()`, mirroring this
    repo's `get_settings`/`cache_clear` idiom) so a hot path does not re-read
    and re-parse the manifest file on every request.
    """
    if not MANIFEST_PATH.exists():
        raise ManifestMissingError(
            f"Vite manifest not found at {MANIFEST_PATH!s} -- run `npm run build` "
            "in frontend/, or check the Docker image's frontend build stage."
        )
    raw = json.loads(MANIFEST_PATH.read_text())
    return MappingProxyType(raw)


# The three characters that can prematurely terminate a `<script>` element (or
# open an HTML comment) when a JSON-serialized value is embedded literally
# inside one. Escaping them to their unicode escapes is valid inside a JSON
# string and invisible to JSON.parse(), but makes the substring that would
# otherwise close the element never appear in the emitted markup. Standard
# "json_script" pattern (Django precedent); this repo has no framework helper
# for it, so it is implemented once, here, and every React-rendered route
# calls through this one function.
_JSON_SCRIPT_ESCAPES: dict[str, str] = {
    "<": "\\u003c",
    ">": "\\u003e",
    "&": "\\u0026",
}


def json_script(model: BaseModel) -> Markup:
    """Serialize `model` to a `Markup`-safe JSON string for embedding inside a
    `<script type="application/json">` element.

    The three script-terminating characters are replaced by their unicode
    escapes; the result is real, harmless-to-the-embedding-context JSON that
    `JSON.parse()` reads back byte-for-byte equal to the source model.
    """
    raw = model.model_dump_json()
    for char, escape in _JSON_SCRIPT_ESCAPES.items():
        raw = raw.replace(char, escape)
    return Markup(raw)


def render_react_page(
    request: Request,
    *,
    entry: str,
    template_name: str,
    page_title: str,
    data: BaseModel,
    extra_context: dict[str, Any] | None = None,
) -> Response:
    """Render `template_name` (a template extending `react_page.html`) with
    `entry`'s built asset(s) and `data` embedded as the page's JSON data island.

    Two mutually exclusive branches, gated on Settings.vite_dev_server_url,
    kept in one function with a single early return so the production path
    can never be reached through the dev path's code:

    - DEV (setting non-empty, local-only): emits the Vite dev client module
      plus `entry`'s raw source path from the configured dev-server origin.
      The manifest is never read in this branch -- there is no build output
      to read in dev, so requiring one would make the dev branch unusable.
    - PRODUCTION (setting empty, the default and the only state a deployed
      container can be in): resolves `entry`'s hashed asset paths through the
      Vite build manifest exactly as before. Fails closed: a missing manifest
      file, or a manifest that does not carry `entry`'s chunk, raises
      ManifestMissingError rather than rendering a shell with no bundle to
      hydrate against.
    """
    base_context: dict[str, Any] = {
        "page_title": page_title,
        "mount_id": REACT_MOUNT_ID,
        "island_id": INITIAL_DATA_ELEMENT_ID,
        "island_json": json_script(data),
    }

    dev_origin = get_settings().vite_dev_server_url
    if dev_origin:
        context: dict[str, Any] = {
            **base_context,
            "stylesheet_hrefs": [],
            "dev_client_src": f"{dev_origin}/@vite/client",
            "module_src": f"{dev_origin}/src/entries/{entry}.tsx",
        }
        if extra_context:
            context.update(extra_context)
        return templates.TemplateResponse(request, template_name, context)

    manifest = load_manifest()
    manifest_key = f"src/entries/{entry}.tsx"
    chunk = manifest.get(manifest_key)
    if chunk is None:
        raise ManifestMissingError(
            f"Vite manifest has no entry for {manifest_key!r} "
            f"(known entries: {sorted(manifest)})"
        )
    css_files = chunk.get("css", [])
    context = {
        **base_context,
        "stylesheet_hrefs": [f"/static/dist/{href}" for href in css_files],
        "dev_client_src": None,
        "module_src": f"/static/dist/{chunk['file']}",
    }
    if extra_context:
        context.update(extra_context)
    return templates.TemplateResponse(request, template_name, context)

# Badge class mapping: status -> CSS badge class suffix.
# needs_operator gets its own distinct attention-drawing class — "pending" is
# already taken by awaiting_approval (a routine settled gate state) and "bad"
# is already taken by rejected/error (failure states); needs_operator is neither
# routine nor a failure, it is an explicit escalation that needs the operator's
# attention NOW, so it gets "escalate" (its own CSS rule).
_BADGE_CLASS: dict[str, str] = {
    "received": "neutral",
    "extracting": "neutral",
    "awaiting_reply": "neutral",
    "approved": "neutral",
    "computed": "neutral",
    "awaiting_approval": "pending",
    "sent": "good",
    "reconciled": "good",
    "rejected": "bad",
    "error": "bad",
    "needs_operator": "escalate",
}

# Badge label mapping: status -> the operator-facing display label.
_BADGE_LABEL: dict[str, str] = {
    "received": "Received",
    "extracting": "Extracting",
    "awaiting_reply": "Awaiting Reply",
    "awaiting_approval": "Needs Approval",
    "approved": "Approved",
    "computed": "Computed",
    "sent": "Sent",
    "reconciled": "Complete",
    "rejected": "Rejected",
    "error": "Error",
    "needs_operator": "Needs Operator",
}


def badge_class_filter(status: str) -> str:
    """Map a payroll_runs.status to a CSS badge class suffix."""
    return _BADGE_CLASS.get(str(status), "neutral")


def badge_label_filter(status: str) -> str:
    """Map a payroll_runs.status to its display label."""
    return _BADGE_LABEL.get(str(status), str(status).replace("_", " ").title())


templates.env.filters["badge_class"] = badge_class_filter
templates.env.filters["badge_label"] = badge_label_filter
