"""Hermetic half of the generated-DTO staleness gate.

Everything here runs with no Node toolchain and no live database -- it answers "does
the committed frontend/src/generated/dtos.d.ts still match what
scripts/generate_openapi_doc.py would produce from app/schemas/'s models today", not
"does openapi-typescript itself, run fresh, produce byte-identical output" (that half
needs Node and lives in the frontend job's own "Generated DTO staleness" step, see
.github/workflows/ci.yml). The common real failure -- a field added or renamed on a
Pydantic model and never regenerated -- is caught by the assertions below without
requiring the TypeScript generator to run at all.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, cast

from pydantic import BaseModel

import app.schemas as schemas_package
from app.schemas.runs_list import RunListRow
from scripts.generate_openapi_doc import build_components_document

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DECLARATIONS_PATH = REPO_ROOT / "frontend" / "src" / "generated" / "dtos.d.ts"


def _public_model_names() -> set[str]:
    """The same discovery rule the generator itself uses: every name in
    app.schemas.__all__ that resolves to a Pydantic model class."""
    names = getattr(schemas_package, "__all__", ())
    result: set[str] = set()
    for name in names:
        obj = getattr(schemas_package, name)
        if isinstance(obj, type) and issubclass(obj, BaseModel):
            result.add(name)
    return result


def _schema_names(document: dict[str, object]) -> set[str]:
    components = cast(dict[str, Any], document["components"])
    return set(components["schemas"])


def test_generated_document_schema_keys_equal_the_public_model_set() -> None:
    """A model exported from app/schemas/ but silently dropped by the generator (or
    a schema present that no longer corresponds to an exported model) is a drift the
    other assertions below can't catch on their own -- this one is the key-set-level
    check GUARD-04's own sibling module trusts as its foundation."""
    document = build_components_document()
    schema_names = _schema_names(document)
    expected = _public_model_names()
    assert schema_names == expected, (
        f"generated document's schema keys {sorted(schema_names)} do not match "
        f"app.schemas.__all__'s Pydantic model set {sorted(expected)}."
    )


def test_generated_document_is_byte_identical_across_two_generations() -> None:
    """A non-deterministic key order would make the staleness gate flap and train a
    reader to ignore it -- regenerating twice must produce the exact same bytes the
    generator would write to stdout, not just an equal in-memory structure."""
    first = build_components_document()
    second = build_components_document()
    assert first == second, "regenerating the document twice produced different output"
    assert json.dumps(first, indent=2) == json.dumps(second, indent=2), (
        "regenerating the document twice produced structurally-equal but "
        "differently-serialized output -- the staleness gate diffs bytes, not "
        "Python dict equality"
    )


def test_every_generated_schema_name_is_declared_in_the_committed_file() -> None:
    """Every schema name the generator discovers today must appear as a declared
    type name in the committed declarations -- a model exported from app/schemas/
    with no matching declaration means the frontend was never regenerated after it
    was added."""
    document = build_components_document()
    schema_names = _schema_names(document)
    declarations = DECLARATIONS_PATH.read_text(encoding="utf-8")

    missing = {
        name
        for name in schema_names
        if not re.search(rf"^\s+{re.escape(name)}: ", declarations, re.MULTILINE)
    }
    assert not missing, (
        f"schema(s) {sorted(missing)} exist in the generated document but have no "
        f"declared type in {DECLARATIONS_PATH.relative_to(REPO_ROOT)} -- regenerate "
        "with `npm run generate:types` from inside frontend/."
    )


def test_every_run_list_row_field_appears_in_the_committed_declarations() -> None:
    """The common real failure this whole gate exists to catch: a field added or
    renamed on RunListRow (list_exposed by definition -- every field it declares is
    meant to reach the browser) and never regenerated. Catches it with no Node
    required at all."""
    declarations = DECLARATIONS_PATH.read_text(encoding="utf-8")
    # Isolate RunListRow's own interface body (indentation matches openapi-typescript's
    # committed output: two levels under `components { schemas: {` ) so a field name
    # that happens to also appear in some OTHER interface can't mask a real miss.
    match = re.search(r"RunListRow:\s*\{(.*?)\n {8}\};", declarations, re.DOTALL)
    assert match is not None, (
        f"no RunListRow interface body found in {DECLARATIONS_PATH.relative_to(REPO_ROOT)}"
    )
    body = match.group(1)

    missing = [
        field
        for field in RunListRow.model_fields
        if not re.search(rf"\b{re.escape(field)}\b", body)
    ]
    assert not missing, (
        f"field(s) {missing} are declared on RunListRow but do not appear in the "
        f"committed {DECLARATIONS_PATH.relative_to(REPO_ROOT)} -- regenerate with "
        "`npm run generate:types` from inside frontend/."
    )
