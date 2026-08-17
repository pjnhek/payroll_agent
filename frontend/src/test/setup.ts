// Registered via vitest.config.ts test.setupFiles. Extends Vitest's `expect` with the
// DOM matchers (toBeInTheDocument, toHaveTextContent, ...) every component test in this
// project relies on -- without this import those matcher calls would be a runtime
// TypeError, not a clear assertion failure.
import "@testing-library/jest-dom/vitest";
