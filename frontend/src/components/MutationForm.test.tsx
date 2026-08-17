// Covers both MutationForm and ConfirmForm (the plan's single listed test file for
// Task 1). MutationForm's own behaviors, ConfirmForm's cancellation semantics -- proven
// by asserting on the submit event's default-prevented state, never on a handler's
// return value -- and the negative paths this project's money-adjacent controls demand:
// submit-without-confirm, double-submit, and a disabled submit button actually blocking
// submission.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmForm } from "./ConfirmForm";
import { MutationForm } from "./MutationForm";
// Raw source text of the runs list page, read via Vite's `?raw` import so this
// assertion never needs Node's `fs` (see src/vite-env.d.ts for why: src/ is
// browser-bundle code, and this import works identically under Vitest and a real build).
import runsPageSource from "../pages/RunsPage.tsx?raw";

describe("MutationForm", () => {
  it("renders exactly one native form element carrying the post method and the given action", () => {
    const { container } = render(
      <MutationForm action="/runs/abc/approve">
        <button type="submit">Approve</button>
      </MutationForm>,
    );
    const forms = container.querySelectorAll("form");
    expect(forms).toHaveLength(1);
    expect(forms[0]).toHaveAttribute("method", "post");
    expect(forms[0]).toHaveAttribute("action", "/runs/abc/approve");
  });

  it("renders only its caller's children -- no button, input, or extra interactive element of its own", () => {
    const { container } = render(
      <MutationForm action="/runs/abc/approve">
        <button type="submit">Approve</button>
      </MutationForm>,
    );
    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    expect(form?.querySelectorAll("button, input")).toHaveLength(1);
  });

  it("attaches no submit handler when the caller supplies none -- the default is never prevented", () => {
    const { container } = render(
      <MutationForm action="/runs/abc/approve">
        <button type="submit">Approve</button>
      </MutationForm>,
    );
    const form = container.querySelector("form");
    expect(form).not.toBeNull();
    const event = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(event);
    // Nothing intercepted the submit -- a plain native POST/navigation proceeds.
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("ConfirmForm", () => {
  const CONFIRM_MESSAGE = "Reject this payroll run? This cannot be undone.";

  function renderConfirmForm(confirmFn: (message: string) => boolean, disabled = false) {
    return render(
      <ConfirmForm action="/runs/abc/reject" confirmMessage={CONFIRM_MESSAGE} confirmFn={confirmFn}>
        <button type="submit" disabled={disabled}>
          Reject
        </button>
      </ConfirmForm>,
    );
  }

  it("renders the same native form MutationForm renders, composed rather than reinvented", () => {
    const { container } = renderConfirmForm(() => true);
    const forms = container.querySelectorAll("form");
    expect(forms).toHaveLength(1);
    expect(forms[0]).toHaveAttribute("method", "post");
    expect(forms[0]).toHaveAttribute("action", "/runs/abc/reject");
  });

  it("passes the caller-supplied prompt text verbatim to confirmFn -- it invents no wording of its own", () => {
    const confirmFn = vi.fn(() => true);
    const { container } = renderConfirmForm(confirmFn);
    const form = container.querySelector("form");
    fireEvent.submit(form!);
    expect(confirmFn).toHaveBeenCalledTimes(1);
    expect(confirmFn).toHaveBeenCalledWith(CONFIRM_MESSAGE);
  });

  it("does not suppress the submit event when the operator confirms", () => {
    const { container } = renderConfirmForm(() => true);
    const form = container.querySelector("form");
    const event = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("cancels the submit event by calling preventDefault when the operator declines -- asserted on the event's default-prevented state, never on the handler's return value", () => {
    const { container } = renderConfirmForm(() => false);
    const form = container.querySelector("form");
    const event = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("submit-without-confirm: a decline never lets the submission through, proven on two separate submit attempts against the same mounted form", () => {
    const confirmFn = vi.fn(() => false);
    const { container } = renderConfirmForm(confirmFn);
    const form = container.querySelector("form");

    const first = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(first);
    expect(first.defaultPrevented).toBe(true);

    const second = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(second);
    expect(second.defaultPrevented).toBe(true);

    expect(confirmFn).toHaveBeenCalledTimes(2);
  });

  it("double-submit: two submissions in a row each resolve independently against the current confirm answer -- no state leaks from the first call into the second", () => {
    const confirmFn = vi.fn().mockReturnValueOnce(false).mockReturnValueOnce(true);
    const { container } = renderConfirmForm(confirmFn);
    const form = container.querySelector("form");

    const first = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(first);
    expect(first.defaultPrevented).toBe(true); // declined -> cancelled

    const second = new Event("submit", { bubbles: true, cancelable: true });
    form?.dispatchEvent(second);
    expect(second.defaultPrevented).toBe(false); // confirmed -> proceeds

    expect(confirmFn).toHaveBeenCalledTimes(2);
  });

  it("a disabled submit button blocks the click from ever reaching the form's submit handler", () => {
    const confirmFn = vi.fn(() => true);
    renderConfirmForm(confirmFn, /* disabled */ true);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    // A disabled button's activation behavior (triggering form submission) is
    // suppressed at the button, so the form's submit event -- and this handler -- must
    // never fire.
    expect(confirmFn).not.toHaveBeenCalled();
  });
});

describe("Neither component is mounted on the runs list page", () => {
  it("RunsPage.tsx imports neither MutationForm nor ConfirmForm", () => {
    expect(runsPageSource).not.toMatch(/from ["'].*MutationForm["']/);
    expect(runsPageSource).not.toMatch(/from ["'].*ConfirmForm["']/);
  });
});
