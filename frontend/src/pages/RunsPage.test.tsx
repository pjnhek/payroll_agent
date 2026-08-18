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
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FailureSummary, type FailureInfo } from "../components/FailureSummary";
import { QueueBadge } from "../components/QueueBadge";
import { StatusBadge } from "../components/StatusBadge";
import { RunsPage, type RunListRow, type RunsListPage } from "./RunsPage";

// vitest.config.ts sets test.globals=false deliberately (explicit imports over
// ambient Jest-style globals), so @testing-library/react's usual automatic
// afterEach(cleanup) registration never fires. Without this, jsdom accumulates every
// prior test's rendered DOM in document.body, and a getByText/querySelector call in a
// later test can match a leftover node from an earlier one -- exactly the multi-match
// failure this line prevents.
afterEach(cleanup);

const NO_FAILURE: FailureInfo = {
  secondary_label: null,
  stage: null,
  reason: null,
  attempts: null,
};

function makeRow(overrides: Partial<RunListRow> = {}): RunListRow {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    created_at: "2026-08-17T12:34:00Z",
    created_at_display: "2026-08-17 12:34",
    business_name: "Acme Co",
    status: "received",
    badge_class: "neutral",
    badge_label: "Received",
    queue_label: null,
    queue_badge_class: "neutral",
    has_open_job: false,
    failure: NO_FAILURE,
    summary_gate_reason: null,
    employee_count: 0,
    ...overrides,
  };
}

function makePage(runs: RunListRow[]): RunsListPage {
  return { runs, in_flight_statuses: ["received", "extracting"] };
}

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

// ---------------------------------------------------------------------------
// Task 2: RunsPage -- columns, ordering, empty state, summary precedence
// ---------------------------------------------------------------------------

describe("RunsPage", () => {
  it("renders two rows with the identical created-at value as two distinct rows, each with its own run-id data attribute", () => {
    const rows = [
      makeRow({ id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", created_at: "2026-08-17T12:00:00Z" }),
      makeRow({ id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", created_at: "2026-08-17T12:00:00Z" }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    const trs = document.querySelectorAll("tbody tr");
    expect(trs).toHaveLength(2);
    expect(trs[0]?.getAttribute("data-run-id")).toBe("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa");
    expect(trs[1]?.getAttribute("data-run-id")).toBe("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb");
  });

  it("given an empty rows array renders the empty-state title and helper sentence, and no table element", () => {
    render(<RunsPage data={makePage([])} />);
    expect(screen.getByText("No payroll runs yet")).not.toBeNull();
    expect(
      screen.getByText(
        "Use the Send Test Email button below to fire a demo fixture through the pipeline.",
      ),
    ).not.toBeNull();
    expect(document.querySelector("table")).toBeNull();
  });

  it("given exactly one row renders one body row inside a table", () => {
    render(<RunsPage data={makePage([makeRow()])} />);
    const table = document.querySelector("table");
    expect(table).not.toBeNull();
    expect(table?.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  it("renders rows in the exact input order with no client-side sort", () => {
    const rows = [
      makeRow({ id: "cccccccc-cccc-cccc-cccc-cccccccccccc", business_name: "Zed Co" }),
      makeRow({ id: "dddddddd-dddd-dddd-dddd-dddddddddddd", business_name: "Alpha Co" }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    const ids = Array.from(document.querySelectorAll("tbody tr")).map((tr) =>
      tr.getAttribute("data-run-id"),
    );
    expect(ids).toEqual([
      "cccccccc-cccc-cccc-cccc-cccccccccccc",
      "dddddddd-dddd-dddd-dddd-dddddddddddd",
    ]);
  });

  it("renders the five column headers in the order Created, Business, Status, Summary, Action", () => {
    render(<RunsPage data={makePage([makeRow()])} />);
    const headers = Array.from(document.querySelectorAll("thead th")).map(
      (th) => th.textContent,
    );
    expect(headers).toEqual(["Created", "Business", "Status", "Summary", "Action"]);
  });

  it("summary precedence: renders the failure summary when any of stage, reason or attempts is present", () => {
    const rows = [
      makeRow({
        failure: { secondary_label: null, stage: "Extraction", reason: null, attempts: null },
        summary_gate_reason: "Missing hours",
        employee_count: 3,
      }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    expect(screen.getByText("Extraction")).not.toBeNull();
    expect(screen.queryByText("Missing hours")).toBeNull();
    expect(screen.queryByText("3 employees")).toBeNull();
  });

  it("summary precedence: renders the gate reason when there is no failure summary", () => {
    const rows = [
      makeRow({ failure: NO_FAILURE, summary_gate_reason: "Missing hours", employee_count: 3 }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    expect(screen.getByText("Missing hours")).not.toBeNull();
  });

  it("summary precedence: renders the employee count with plural agreement when there is no failure or gate reason", () => {
    const rows = [
      makeRow({ failure: NO_FAILURE, summary_gate_reason: null, employee_count: 3 }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    expect(screen.getByText("3 employees")).not.toBeNull();
  });

  it("summary precedence: renders the employee count with singular agreement for exactly one employee", () => {
    const rows = [
      makeRow({ failure: NO_FAILURE, summary_gate_reason: null, employee_count: 1 }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    expect(screen.getByText("1 employee")).not.toBeNull();
  });

  it("summary precedence: renders the em-dash placeholder when none of the three are present", () => {
    const rows = [
      makeRow({ failure: NO_FAILURE, summary_gate_reason: null, employee_count: 0 }),
    ];
    render(<RunsPage data={makePage(rows)} />);
    const summaryCell = document.querySelectorAll("tbody td")[3];
    expect(summaryCell?.textContent).toBe("—");
  });

  it("links each row's action cell to the run's detail path", () => {
    const rows = [makeRow({ id: "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee" })];
    render(<RunsPage data={makePage(rows)} />);
    const link = screen.getByRole("link", { name: "View" });
    expect(link.getAttribute("href")).toBe("/runs/eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee");
  });

  it("renders the preformatted created-at display string verbatim, with no date/time formatting in the component", () => {
    const rows = [makeRow({ created_at_display: "2026-08-17 12:34" })];
    render(<RunsPage data={makePage(rows)} />);
    expect(screen.getByText("2026-08-17 12:34")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Task 3: scroll-region structure -- a jsdom-level structural pin, not a layout
// measurement. jsdom performs no layout, so this asserts only what jsdom CAN see:
// element nesting, attributes and presence/absence. The real 375/374/376px overflow
// proof is manual and recorded in SUMMARY.md (or explicitly left open there if no
// browser was available), matching this repo's precedent for the same property.
// ---------------------------------------------------------------------------

describe("RunsPage scroll region structure", () => {
  it("renders the scroll region as the table's direct parent, carrying the region role, a zero tab index and the accessible label", () => {
    render(<RunsPage data={makePage([makeRow()])} />);
    const region = document.querySelector('[role="region"]') as HTMLElement;
    expect(region).not.toBeNull();
    expect(region.getAttribute("tabindex")).toBe("0");
    expect(region.getAttribute("aria-label")).toBe("Payroll runs");
    // :scope > table asserts DIRECT parentage, not merely a shared ancestor --
    // a table nested one level deeper (e.g. inside a wrapper div) would fail this.
    const table = region.querySelector(":scope > table");
    expect(table).not.toBeNull();
  });

  it("with zero rows renders no such region element at all", () => {
    render(<RunsPage data={makePage([])} />);
    expect(document.querySelector('[role="region"]')).toBeNull();
    expect(document.querySelector(".table-scroll")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Live polling (LIST-02): wires usePoller into one instance per in-flight row,
// preserving the pre-conversion poller's exact per-row start condition (a row polls
// only when it is in-flight or carries an open job) and updating badges in place on
// each tick. Fake timers throughout -- no real sleeps.
// ---------------------------------------------------------------------------

describe("RunsPage live polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  function okResponse(payload: unknown) {
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
  }

  // A poll tick's state update (usePoller's onUpdate -> RunRow's setVolatile) happens
  // inside a fake-timer-driven promise chain, outside any event handler React's own
  // batching would otherwise wrap in act() automatically -- wrapping the advance in
  // act() here is what makes the resulting re-render actually flush to the DOM before
  // the next assertion reads it, rather than leaving a stale render committed only in
  // React's internal fiber tree.
  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it("a row that is neither in-flight nor carrying an open job issues no requests at all", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const settledRow = makeRow({ status: "sent", has_open_job: false });
    render(<RunsPage data={makePage([settledRow])} />);

    await advance(2000 * 3);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a row that is in-flight issues requests, and a row with an open job (but a settled status) issues requests too", async () => {
    // Typed with an explicit url parameter (unused in the body -- both rows get the
    // same response shape) so `fetchMock.mock.calls` carries the called url at index 0.
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const fetchMock = vi.fn((_url: string) =>
      okResponse({
        status: "received",
        badge_class: "neutral",
        badge_label: "Received",
        queue_label: null,
        queue_badge_class: "neutral",
        has_open_job: false,
        failure: NO_FAILURE,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const inFlightRow = makeRow({
      id: "10000000-0000-0000-0000-000000000001",
      status: "received",
    });
    const openJobRow = makeRow({
      id: "20000000-0000-0000-0000-000000000002",
      status: "sent",
      has_open_job: true,
    });
    render(<RunsPage data={makePage([inFlightRow, openJobRow])} />);

    await advance(2000);
    const calledUrls = fetchMock.mock.calls.map(([url]) => url);
    expect(calledUrls).toContain(`/runs/${inFlightRow.id}/status`);
    expect(calledUrls).toContain(`/runs/${openJobRow.id}/status`);
  });

  it("when a tick returns a new status, the row's status badge text and class change in place with no full re-render of the table (row element identity preserved) -- replaces the deleted test_script_hook_classes_carry_js_prefix_and_stay_out_of_css guard", async () => {
    const row = makeRow({ status: "received", badge_class: "neutral", badge_label: "Received" });
    const fetchMock = vi.fn(() =>
      okResponse({
        status: "sent",
        badge_class: "good",
        badge_label: "Sent",
        queue_label: null,
        queue_badge_class: "neutral",
        has_open_job: false,
        failure: NO_FAILURE,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<RunsPage data={makePage([row])} />);

    const rowElBefore = document.querySelector(`[data-run-id="${row.id}"]`);
    expect(screen.getByText("Received").className).toBe("badge badge-neutral");

    await advance(2000);

    const rowElAfter = document.querySelector(`[data-run-id="${row.id}"]`);
    expect(rowElAfter).toBe(rowElBefore);
    expect(screen.getByText("Sent").className).toBe("badge badge-good");
    expect(screen.queryByText("Received")).toBeNull();
  });

  it("when a tick returns an unchanged status, the badge's text and class name stay byte-identical to before and no duplicate badge node exists", async () => {
    const row = makeRow({ status: "received", badge_class: "neutral", badge_label: "Received" });
    const fetchMock = vi.fn(() =>
      okResponse({
        status: "received",
        badge_class: "neutral",
        badge_label: "Received",
        queue_label: null,
        queue_badge_class: "neutral",
        has_open_job: false,
        failure: NO_FAILURE,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<RunsPage data={makePage([row])} />);

    const before = screen.getByText("Received");
    const classBefore = before.className;
    const textBefore = before.textContent;

    await advance(2000);

    const badges = screen.getAllByText("Received");
    expect(badges).toHaveLength(1);
    expect(badges[0]?.className).toBe(classBefore);
    expect(badges[0]?.textContent).toBe(textBefore);
  });

  it("when a tick returns a settled status with no open job, that row stops issuing requests while another still-in-flight row keeps issuing them", async () => {
    const settlingRow = makeRow({
      id: "30000000-0000-0000-0000-000000000003",
      status: "received",
    });
    const staysInFlightRow = makeRow({
      id: "40000000-0000-0000-0000-000000000004",
      status: "extracting",
    });
    const settlingUrl = `/runs/${settlingRow.id}/status`;
    const staysUrl = `/runs/${staysInFlightRow.id}/status`;
    const fetchMock = vi.fn((url: string) => {
      if (url === settlingUrl) {
        return okResponse({
          status: "sent",
          badge_class: "good",
          badge_label: "Sent",
          queue_label: null,
          queue_badge_class: "neutral",
          has_open_job: false,
          failure: NO_FAILURE,
        });
      }
      return okResponse({
        status: "extracting",
        badge_class: "pending",
        badge_label: "Extracting",
        queue_label: "Running",
        queue_badge_class: "running",
        has_open_job: true,
        failure: NO_FAILURE,
      });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<RunsPage data={makePage([settlingRow, staysInFlightRow])} />);

    const countFor = (url: string) =>
      fetchMock.mock.calls.filter(([calledUrl]) => calledUrl === url).length;

    await advance(2000);
    expect(countFor(settlingUrl)).toBe(1);
    expect(countFor(staysUrl)).toBe(1);

    await advance(2000 * 2);
    expect(countFor(settlingUrl)).toBe(1);
    expect(countFor(staysUrl)).toBeGreaterThan(1);
  });

  it("a queue label transition updates the queue badge and its hidden state in place", async () => {
    const row = makeRow({ status: "received", has_open_job: false, queue_label: null });
    const fetchMock = vi.fn(() =>
      okResponse({
        status: "received",
        badge_class: "neutral",
        badge_label: "Received",
        queue_label: "Running",
        queue_badge_class: "running",
        has_open_job: true,
        failure: NO_FAILURE,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<RunsPage data={makePage([row])} />);

    const queueBadgeBefore = document.querySelector(".queue-badge") as HTMLElement;
    expect(queueBadgeBefore.hidden).toBe(true);

    await advance(2000);

    const queueBadgeAfter = document.querySelector(".queue-badge") as HTMLElement;
    expect(queueBadgeAfter).toBe(queueBadgeBefore);
    expect(queueBadgeAfter.hidden).toBe(false);
    expect(queueBadgeAfter.textContent).toBe("Running");
    expect(queueBadgeAfter.className).toBe("badge badge-running queue-badge");
  });

  it("a failure appearing on a tick renders the failure summary and secondary badge in place", async () => {
    const row = makeRow({
      status: "extracting",
      failure: NO_FAILURE,
      summary_gate_reason: null,
      employee_count: 3,
    });
    const fetchMock = vi.fn(() =>
      okResponse({
        status: "error",
        badge_class: "bad",
        badge_label: "Error",
        queue_label: null,
        queue_badge_class: "neutral",
        has_open_job: false,
        failure: {
          secondary_label: "Retries exhausted",
          stage: "Extraction",
          reason: "Provider timeout",
          attempts: "5 of 5 attempts",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<RunsPage data={makePage([row])} />);

    expect(screen.queryByText("Retries exhausted")).toBeNull();

    await advance(2000);

    expect(screen.getByText("Retries exhausted")).not.toBeNull();
    expect(screen.getByText("Extraction · Provider timeout · 5 of 5 attempts")).not.toBeNull();
  });
});
