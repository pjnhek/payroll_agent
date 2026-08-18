// The single sanctioned browser-request call site in this tree (GUARD-06). Reproduces
// the five observable properties of the vanilla-JS per-row poller it replaces, recovered
// from git history before the /runs React conversion (`git show <pre-conversion
// commit>:app/templates/runs_list.html`, lines 10-59): the same request path shape (a
// caller-supplied GET url), the same two-second interval, the same sixty-attempt cap, the
// same settle condition (the caller decides when a tick's payload counts as settled, via
// stopWhen), and the same per-tick error swallowing.
//
// Single-URL, one instance per row (D-22-14): usePoller(url, opts, onUpdate) takes one
// request path and mounts once per caller. /runs mounts one instance per in-flight row,
// preserving the original per-row network shape and per-row stop behavior; a future
// run-detail page reuses this hook unchanged with a single instance and no adaptation.
import { useEffect } from "react";

export interface UsePollerOptions<T> {
  intervalMs: number;
  maxAttempts: number;
  stopWhen: (data: T) => boolean;
}

export function usePoller<T>(
  url: string,
  opts: UsePollerOptions<T>,
  onUpdate: (data: T) => void,
): void {
  // The effect below intentionally captures url/opts/onUpdate once per mount rather
  // than re-deriving them per render (empty dependency array, disabled below). RunsPage
  // mounts one usePoller instance per in-flight row; if this effect re-ran on every
  // parent re-render it would restart every row's poll (a fresh setInterval, attempts
  // reset to zero) on every unrelated state change in the page, not just when the row
  // itself changes identity. A row's poller instance is remounted (a real identity
  // change, via conditional rendering keyed to the row) rather than re-run in place,
  // which is the actual boundary that matters here.
  useEffect(() => {
    let attempts = 0;
    let cancelled = false;

    const timer = setInterval(() => {
      if (attempts >= opts.maxAttempts) {
        clearInterval(timer);
        return;
      }
      attempts++;
      fetch(url)
        .then((response) => (response.ok ? (response.json() as Promise<T>) : null))
        .then((data) => {
          // `cancelled` is checked here, not in the interval tick's synchronous entry
          // above -- clearInterval() in the cleanup below already prevents any FUTURE
          // tick from firing at all, so re-checking it there would be redundant. This
          // check guards the one race clearInterval cannot: a fetch already in flight
          // at the moment of unmount, whose response resolves after cleanup ran. Without
          // it, that late resolution would call onUpdate (a setState, typically) on an
          // unmounted row.
          if (data === null || cancelled) return;
          onUpdate(data);
          if (opts.stopWhen(data)) {
            clearInterval(timer);
          }
        })
        // Deliberate -- matches the replaced poller's per-tick .catch(function() {}):
        // a network blip on one tick must not kill the poller, and must not throw an
        // unhandled rejection. Every other tick keeps firing on schedule. This is a
        // network-blip guard, not error hiding -- do not delete it because it looks
        // like an empty rejection handler; deleting it turns a transient blip into a
        // stalled badge instead of a self-healing retry two seconds later.
        .catch(() => {});
    }, opts.intervalMs);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- url/opts/onUpdate deliberately captured once per mount, see the comment above useEffect
  }, []);
}
