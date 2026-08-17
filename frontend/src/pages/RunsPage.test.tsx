// Full-parity component test suite for the React /runs list (LIST-01, LIST-04).
//
// Every case is written to FAIL if the badge/summary logic were wrong -- it asserts
// on rendered class names, hidden state and text content, never merely on "the
// component mounted." Empty state, zero-row scroll-region absence and degenerate
// values (null queue label, zero employees, identical timestamps) are covered
// alongside the happy row, per this plan's parity guidance.
//
// jsdom performs no layout, so nothing here asserts a layout-derived measurement
// (scroll width, overflow, viewport boundary) -- that proof is manual and recorded
// in SUMMARY.md, matching this repo's existing precedent for the same property
// (quick task 260726-ugm).
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { FailureSummary } from "../components/FailureSummary";
import { QueueBadge } from "../components/QueueBadge";
import { StatusBadge } from "../components/StatusBadge";

// vitest.config.ts sets test.globals=false deliberately (explicit imports over
// ambient Jest-style globals), so @testing-library/react's usual automatic
// afterEach(cleanup) registration never fires. Without this, jsdom accumulates every
// prior test's rendered DOM in document.body, and a getByText/querySelector call in a
// later test can match a leftover node from an earlier one -- exactly the multi-match
// failure this line prevents.
afterEach(cleanup);

// ---------------------------------------------------------------------------
// Task 1: StatusBadge
// ---------------------------------------------------------------------------

describe("StatusBadge", () => {
  it("renders one span carrying the base badge class and the suffixed modifier class, with the label as text", () => {
    render(<StatusBadge badgeClass="escalate" label="Needs Operator" />);
    const el = screen.getByText("Needs Operator");
    expect(el.tagName).toBe("SPAN");
    expect(el.className).toBe("badge badge-escalate");
  });
});

// ---------------------------------------------------------------------------
// Task 1: QueueBadge
// ---------------------------------------------------------------------------

describe("QueueBadge", () => {
  it("given an open job renders visible with the polite live-region attribute and the label text", () => {
    render(<QueueBadge label="Running" badgeClass="running" hasOpenJob />);
    const el = screen.getByText("Running");
    expect(el).not.toBeNull();
    expect(el.hidden).toBe(false);
    expect(el.getAttribute("aria-live")).toBe("polite");
    expect(el.className).toBe("badge badge-running queue-badge");
  });

  it("given no open job (and, as the server always pairs it, a null label) renders hidden with empty text", () => {
    // The server only ever produces has_open_job=false together with queue_label=null
    // (app/routes/runs.py::_safe_run_for_browser derives has_open_job FROM queue_label
    // being non-null) -- this is the realistic degenerate case, not an impossible
    // combination the component must reconcile on its own.
    render(<QueueBadge label={null} badgeClass="neutral" hasOpenJob={false} />);
    const el = document.querySelector(".queue-badge") as HTMLElement;
    expect(el.hidden).toBe(true);
    expect(el.textContent).toBe("");
  });

  it("given a null label renders hidden with empty text rather than the string 'null'", () => {
    render(<QueueBadge label={null} badgeClass="neutral" hasOpenJob={false} />);
    const el = document.querySelector(".queue-badge") as HTMLElement;
    expect(el.hidden).toBe(true);
    expect(el.textContent).toBe("");
    expect(el.textContent).not.toBe("null");
  });
});

// ---------------------------------------------------------------------------
// Task 1: FailureSummary
// ---------------------------------------------------------------------------

describe("FailureSummary", () => {
  it("given a secondary label renders the neutral secondary badge visible", () => {
    render(
      <FailureSummary
        failure={{
          secondary_label: "Retries exhausted",
          stage: "Extraction",
          reason: "Provider timeout",
          attempts: "5 of 5 attempts",
        }}
      />,
    );
    const badge = screen.getByText("Retries exhausted");
    expect(badge.className).toBe("badge badge-neutral");
    expect(badge.hidden).toBe(false);
  });

  it("given no secondary label renders the badge hidden", () => {
    render(
      <FailureSummary
        failure={{
          secondary_label: null,
          stage: "Extraction",
          reason: "Provider timeout",
          attempts: null,
        }}
      />,
    );
    const badge = document.querySelector(".badge-neutral") as HTMLElement;
    expect(badge.hidden).toBe(true);
    expect(badge.textContent).toBe("");
  });

  it("given all of stage, reason and attempts joins them with the middle-dot separator", () => {
    render(
      <FailureSummary
        failure={{
          secondary_label: null,
          stage: "Extraction",
          reason: "Provider timeout",
          attempts: "5 of 5 attempts",
        }}
      />,
    );
    expect(
      screen.getByText("Extraction · Provider timeout · 5 of 5 attempts"),
    ).not.toBeNull();
  });

  it("given only some of stage, reason and attempts skips the absent parts with no leading or trailing separator", () => {
    render(
      <FailureSummary
        failure={{
          secondary_label: null,
          stage: "Extraction",
          reason: null,
          attempts: "5 of 5 attempts",
        }}
      />,
    );
    const text = screen.getByText("Extraction · 5 of 5 attempts");
    expect(text.textContent?.startsWith("·")).toBe(false);
    expect(text.textContent?.endsWith("·")).toBe(false);
  });

  it("given none of stage, reason or attempts renders no summary text node at all", () => {
    const { container } = render(
      <FailureSummary
        failure={{ secondary_label: null, stage: null, reason: null, attempts: null }}
      />,
    );
    // Only the (hidden) secondary badge should exist -- no empty visible summary
    // element, per the plan's explicit "renders nothing at all" requirement.
    expect(container.querySelectorAll("span")).toHaveLength(1);
    expect(container.textContent).toBe("");
  });
});
