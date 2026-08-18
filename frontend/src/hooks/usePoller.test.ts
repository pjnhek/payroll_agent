// usePoller's teardown-observable test suite (LIST-02).
//
// Reproduces the five observable properties of the vanilla-JS per-row poller this hook
// replaces (recovered from git history: `git show <pre-conversion commit>:app/templates/
// runs_list.html`, lines 10-59, before the React /runs conversion): the same request
// path shape, the same two-second interval, the same sixty-attempt cap, the same settle
// condition, and the same per-tick error swallowing.
//
// Fake timers throughout -- no real sleeps, per this repo's own precedent for testing
// interval-driven code deterministically and fast.
//
// Plain .ts, not .tsx: the harness is built with React.createElement instead of JSX so
// this file needs no JSX transform.
import { createElement } from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePoller, type UsePollerOptions } from "./usePoller";

interface PollPayload {
  status: string;
  has_open_job: boolean;
}

function Harness<T>({
  url,
  opts,
  onUpdate,
}: {
  url: string;
  opts: UsePollerOptions<T>;
  onUpdate: (data: T) => void;
}) {
  usePoller(url, opts, onUpdate);
  return null;
}

function renderHarness<T>(props: {
  url: string;
  opts: UsePollerOptions<T>;
  onUpdate: (data: T) => void;
}) {
  return render(createElement(Harness<T>, props));
}

function okResponse(payload: unknown) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("usePoller", () => {
  it("given a settle predicate that never returns true, issues one request per interval tick and stops after exactly the configured attempt cap", async () => {
    const fetchMock = vi.fn(() => okResponse({ status: "pending", has_open_job: false }));
    vi.stubGlobal("fetch", fetchMock);
    const onUpdate = vi.fn();

    renderHarness<PollPayload>({
      url: "/runs/abc/status",
      opts: { intervalMs: 2000, maxAttempts: 3, stopWhen: () => false },
      onUpdate,
    });

    await vi.advanceTimersByTimeAsync(2000 * 3);
    expect(fetchMock).toHaveBeenCalledTimes(3);

    // Past the cap: no further requests, ever.
    await vi.advanceTimersByTimeAsync(2000 * 5);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("given a response whose payload satisfies the settle predicate, stops issuing requests immediately after that tick", async () => {
    const fetchMock = vi.fn(() => okResponse({ status: "sent", has_open_job: false }));
    vi.stubGlobal("fetch", fetchMock);
    const onUpdate = vi.fn();

    renderHarness<PollPayload>({
      url: "/runs/abc/status",
      opts: {
        intervalMs: 2000,
        maxAttempts: 60,
        stopWhen: (data) => data.status === "sent" && !data.has_open_job,
      },
      onUpdate,
    });

    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onUpdate).toHaveBeenCalledTimes(1);

    await vi.advanceTimersByTimeAsync(2000 * 5);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("given a rejected request, swallows the failure for that tick and issues the next tick on schedule", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("network blip"))
      .mockImplementation(() => okResponse({ status: "pending", has_open_job: false }));
    vi.stubGlobal("fetch", fetchMock);
    const onUpdate = vi.fn();

    renderHarness<PollPayload>({
      url: "/runs/abc/status",
      opts: { intervalMs: 2000, maxAttempts: 60, stopWhen: () => false },
      onUpdate,
    });

    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onUpdate).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onUpdate).toHaveBeenCalledTimes(1);
  });

  it("given a non-ok response, does not invoke the update callback for that tick", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve({ ok: false, json: () => Promise.resolve({ status: "pending", has_open_job: false }) }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const onUpdate = vi.fn();

    renderHarness<PollPayload>({
      url: "/runs/abc/status",
      opts: { intervalMs: 2000, maxAttempts: 2, stopWhen: () => false },
      onUpdate,
    });

    await vi.advanceTimersByTimeAsync(2000 * 2);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("on unmount, the request counter stops increasing when fake timers are advanced past several further intervals", async () => {
    const fetchMock = vi.fn(() => okResponse({ status: "pending", has_open_job: false }));
    vi.stubGlobal("fetch", fetchMock);
    const onUpdate = vi.fn();

    const { unmount } = renderHarness<PollPayload>({
      url: "/runs/abc/status",
      opts: { intervalMs: 2000, maxAttempts: 60, stopWhen: () => false },
      onUpdate,
    });

    await vi.advanceTimersByTimeAsync(2000 * 2);
    const countAtUnmount = fetchMock.mock.calls.length;

    unmount();
    await vi.advanceTimersByTimeAsync(2000 * 5);

    // No try/finally, no suppression around this assertion -- it IS the property
    // under test. A cleanup call that stopped clearing the interval must red this
    // line directly, not be caught and hidden by a wrapping construct.
    expect(fetchMock.mock.calls.length).toBe(countAtUnmount);
  });

  it("mounts one poller per instance -- unmounting one leaves the other's counter still increasing", async () => {
    // Typed with an explicit url parameter (unlike the other cases' fetchMock) so
    // `fetchMock.mock.calls` carries the called url at index 0 -- needed below to
    // attribute each call to the row that made it. The parameter itself is unused in
    // the body (both instances return the same shape), only its presence in the type
    // signature matters for what `mock.calls` records.
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const fetchMock = vi.fn((_url: string) => okResponse({ status: "pending", has_open_job: false }));
    vi.stubGlobal("fetch", fetchMock);

    const { unmount: unmountA } = renderHarness<PollPayload>({
      url: "/runs/a/status",
      opts: { intervalMs: 2000, maxAttempts: 60, stopWhen: () => false },
      onUpdate: vi.fn(),
    });
    const { unmount: unmountB } = renderHarness<PollPayload>({
      url: "/runs/b/status",
      opts: { intervalMs: 2000, maxAttempts: 60, stopWhen: () => false },
      onUpdate: vi.fn(),
    });

    const countFor = (url: string) =>
      fetchMock.mock.calls.filter(([calledUrl]) => calledUrl === url).length;

    await vi.advanceTimersByTimeAsync(2000);
    expect(countFor("/runs/a/status")).toBe(1);
    expect(countFor("/runs/b/status")).toBe(1);

    unmountA();
    const bCountBeforeFurtherAdvance = countFor("/runs/b/status");
    await vi.advanceTimersByTimeAsync(2000 * 2);

    expect(countFor("/runs/a/status")).toBe(1);
    expect(countFor("/runs/b/status")).toBeGreaterThan(bCountBeforeFurtherAdvance);

    unmountB();
  });

  it("passes the parsed JSON payload to the update callback, typed as the poll shape", async () => {
    const payload = {
      status: "received",
      badge_class: "neutral",
      badge_label: "Received",
      failure: { secondary_label: null, stage: null, reason: null, attempts: null },
      queue_label: null,
      queue_badge_class: "neutral",
      has_open_job: false,
    };
    const fetchMock = vi.fn(() => okResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const onUpdate = vi.fn();

    renderHarness<typeof payload>({
      url: "/runs/abc/status",
      opts: { intervalMs: 2000, maxAttempts: 1, stopWhen: () => true },
      onUpdate,
    });

    await vi.advanceTimersByTimeAsync(2000);
    expect(onUpdate).toHaveBeenCalledWith(payload);
  });
});
