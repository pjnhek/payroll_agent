// Registered via vitest.config.ts test.setupFiles. Extends Vitest's `expect` with the
// DOM matchers (toBeInTheDocument, toHaveTextContent, ...) every component test in this
// project relies on -- without this import those matcher calls would be a runtime
// TypeError, not a clear assertion failure.
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// @testing-library/react's automatic afterEach cleanup only self-registers when it can
// see a global `afterEach` -- this project's vitest.config.ts sets `globals: false`
// (explicit `import { afterEach } from "vitest"` over ambient globals), so that
// auto-detection never fires and every test's rendered tree would otherwise stay
// mounted in document.body for the rest of the file, letting a later test's
// `getByRole`/querySelector calls silently match a PRIOR test's leftover DOM. Unmounting
// after each test is what makes each test's queries see only what that test rendered.
afterEach(() => {
  cleanup();
});
