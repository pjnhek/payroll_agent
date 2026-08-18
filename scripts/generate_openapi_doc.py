"""Generates a components-schemas-only document from app/schemas/'s public models.

`build_components_document()` returns a minimal OpenAPI-shaped document -- `openapi`/
`info`/`paths` are the smallest legal values that shape requires, `paths` deliberately
empty because nothing here is ever served over its own HTTP route. The only meaningful
content is `components.schemas`, assembled from every Pydantic model
`app/schemas/__init__.py` names in its own `__all__`.

`frontend/package.json`'s `generate:types` script pipes this document's stdout into
`openapi-typescript`, which writes the committed `frontend/src/generated/dtos.d.ts` --
the frontend's declared view of every response shape, generated from the same models
FastAPI itself validates against, never hand-written. Do NOT hand-edit that generated
file; regenerate it with `npm run generate:types` from inside `frontend/`, or verify it
is not stale with `npm run generate:types:check`.

Do NOT add an HTTP endpoint that serves this document. The embedded page-data island
never travels over its own route, and the key-set assertions behind the allowlist DTOs
work by parsing that island out of a page's response text -- a route here would add
public surface and buy nothing for that testability. `RunStatusPoll`'s own status-poll
endpoint separately declares it as a `response_model`, so that shape already appears in
the application's real, live OpenAPI document too; the two must agree on it.

Usage:
  uv run python scripts/generate_openapi_doc.py   # write the document to stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaMode, models_json_schema

import app.schemas as schemas_package


def _discover_public_models() -> list[type[BaseModel]]:
    """Collect every Pydantic model class named in `app.schemas.__all__`.

    Reads the package's own declared public exports rather than a hard-coded list
    here, so a model added to `app/schemas/` and exported from `__init__.py` is
    picked up automatically -- and a model that exists but is never exported is a
    deliberate, reviewable choice at the package boundary, not a second list this
    generator would otherwise have to be kept in sync with by hand.
    """
    names = getattr(schemas_package, "__all__", ())
    models: list[type[BaseModel]] = []
    for name in names:
        obj = getattr(schemas_package, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            models.append(obj)
    return models


def build_components_document() -> dict[str, object]:
    """Build a components-schemas-only document from every model `app/schemas/`
    exports.

    Uses Pydantic's own multi-model schema builder (`models_json_schema`) rather
    than calling `model_json_schema()` per model in a loop, so a model nested
    inside another (`FailureInfo` inside `RunStatusPoll`) resolves as a single
    shared `$ref` into `components/schemas` instead of being inlined once per
    parent that references it -- the same `ref_template` shape FastAPI's own
    OpenAPI generation uses internally.

    Schema keys are sorted so regenerating twice produces byte-identical output:
    a non-deterministic key order would make the staleness gate flap and train a
    reader to ignore it.
    """
    models = _discover_public_models()
    if not models:
        # A generator that silently finds nothing would emit a valid empty
        # document, and the staleness gate would then pass forever on nothing --
        # refuse instead of degrading into a vacuous pass.
        raise RuntimeError(
            "generate_openapi_doc: app.schemas.__all__ exported no Pydantic model "
            "subclasses -- refusing to emit an empty components-schemas document"
        )

    mode: JsonSchemaMode = "serialization"
    _mapping, top_level = models_json_schema(
        [(model, mode) for model in models],
        ref_template="#/components/schemas/{model}",
    )
    defs = top_level.get("$defs", {})
    schemas = {name: defs[name] for name in sorted(defs)}

    return {
        "openapi": "3.1.0",
        "info": {"title": "payroll-agent generated DTOs", "version": "0"},
        "paths": {},
        "components": {"schemas": schemas},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)

    document = build_components_document()
    json.dump(document, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
