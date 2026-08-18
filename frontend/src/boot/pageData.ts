import type { components } from "../generated/dtos";

// Reads the server-embedded initial page data island. Must stay byte-for-byte
// consistent with app/routes/templating.py's INITIAL_DATA_ELEMENT_ID -- there is no
// automatic cross-language sharing of this literal, so a change here requires the
// matching Python change (and vice versa).
export const INITIAL_DATA_ELEMENT_ID = "__INITIAL_DATA__";

/**
 * The /runs list page's embedded payload -- generated from
 * app/schemas/runs_list.py's RunsListPage model (via
 * scripts/generate_openapi_doc.py + openapi-typescript, see
 * frontend/src/generated/dtos.d.ts). Re-exported here so a consuming page reads a
 * named type rather than indexing into the generated file's
 * `components["schemas"][...]` shape directly.
 */
export type RunsListPage = components["schemas"]["RunsListPage"];

/**
 * Read and parse the /runs page's embedded `__INITIAL_DATA__` JSON island.
 *
 * Never returns a silent empty object: a missing island element, an element with no
 * text content, or unparsable JSON all throw a descriptive error instead. The server
 * always emits a real island (even for a zero-row page, it is a valid JSON object
 * with an empty runs array) -- a missing or unparsable island means the page shell
 * itself is broken, and that must fail loudly rather than render a component against
 * `undefined`.
 *
 * The return type is generated from the Pydantic model, not hand-typed: a field the
 * allowlist withheld (app/schemas/runs_list.py's RunListRow.EXCLUDED) does not exist
 * on this type, so reading it is a compile error here rather than an undefined value
 * discovered at runtime. The type assertion below is a compile-time claim about the
 * server's contract, not a runtime check -- the throws above are what actually
 * enforce that the payload exists and parses.
 */
export function readInitialData(): RunsListPage {
  const element = document.getElementById(INITIAL_DATA_ELEMENT_ID);
  if (!element || !element.textContent) {
    throw new Error(
      `readInitialData: no element with id "${INITIAL_DATA_ELEMENT_ID}" (or it has ` +
        "no text content) -- the server must always emit a data island, even for an " +
        "empty page.",
    );
  }
  try {
    return JSON.parse(element.textContent) as RunsListPage;
  } catch (cause) {
    throw new Error(
      `readInitialData: element "${INITIAL_DATA_ELEMENT_ID}" content is not valid JSON`,
      { cause },
    );
  }
}
