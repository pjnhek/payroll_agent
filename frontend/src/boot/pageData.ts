// Reads the server-embedded initial page data island. Must stay byte-for-byte
// consistent with app/routes/templating.py's INITIAL_DATA_ELEMENT_ID -- there is no
// automatic cross-language sharing of this literal, so a change here requires the
// matching Python change (and vice versa).
export const INITIAL_DATA_ELEMENT_ID = "__INITIAL_DATA__";

/**
 * Read and parse this page's embedded `__INITIAL_DATA__` JSON island.
 *
 * Never returns a silent empty object: a missing island element, an element with no
 * text content, or unparsable JSON all throw a descriptive error instead. The server
 * always emits a real island (even for a zero-row page, it is a valid JSON object
 * with an empty array) -- a missing or unparsable island means the page shell itself
 * is broken, and that must fail loudly rather than render a component against
 * `undefined`.
 */
export function readInitialData<T>(): T {
  const element = document.getElementById(INITIAL_DATA_ELEMENT_ID);
  if (!element || !element.textContent) {
    throw new Error(
      `readInitialData: no element with id "${INITIAL_DATA_ELEMENT_ID}" (or it has ` +
        "no text content) -- the server must always emit a data island, even for an " +
        "empty page.",
    );
  }
  try {
    return JSON.parse(element.textContent) as T;
  } catch (cause) {
    throw new Error(
      `readInitialData: element "${INITIAL_DATA_ELEMENT_ID}" content is not valid JSON`,
      { cause },
    );
  }
}
