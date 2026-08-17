// Renders the shape declared in ../types/banner.ts: exactly one arm per union variant,
// plus the orthogonal hours-changed overlay when present. Phase 22 renders
// placeholder-free but minimal content per arm -- the banner's existing callout class
// and its existing heading text from app/templates/run_detail.html, taken from the
// template's own wording. Phase 23 fills in each arm's full body (gate reasons,
// unresolved-name lists, the resolve/reject sub-forms); adding that body content
// requires no change to the union, the discriminator, or the overlay composition below.
import type { DecisionBannerState, HoursChangesOverlay } from "../types/banner";

type BannerBranch = DecisionBannerState["branch"];

const BANNER_CLASS = "banner-mb";

function Banner({ variant, heading }: { variant: string; heading: string }) {
  return (
    <div className={`banner ${variant} ${BANNER_CLASS}`}>
      <strong>{heading}</strong>
    </div>
  );
}

function renderBranch(branch: BannerBranch) {
  switch (branch.kind) {
    case "none":
      return null;
    case "error":
      return <Banner variant="banner-error" heading="Error" />;
    case "delivery_review_required":
      return <Banner variant="banner-awaiting" heading="Delivery review required" />;
    case "needs_operator":
      return <Banner variant="banner-clarify" heading="Needs Operator" />;
    case "awaiting_reply":
      return <Banner variant="banner-awaiting" heading="Awaiting client reply" />;
    case "decision_process":
      return <Banner variant="banner-process" heading="Decision: Process" />;
    case "decision_clarification_requested":
      return <Banner variant="banner-clarify" heading="Decision: Clarification requested" />;
    default: {
      // Exhaustiveness check: if BannerBranch ever gains a variant without a case
      // above, `branch` is no longer assignable to `never` here and this line becomes a
      // compile error, not a silently missing banner. See DecisionBanner.test.tsx /
      // SUMMARY.md for the demonstrated proof (a variant added without an arm).
      const exhaustive: never = branch;
      return exhaustive;
    }
  }
}

function HoursChangesOverlayBanner({ overlay }: { overlay: HoursChangesOverlay }) {
  return (
    <div className={`banner banner-awaiting ${BANNER_CLASS}`}>
      <strong>Hours changed on the client&apos;s reply</strong>
      {overlay.changes.length > 0 && (
        <div className="banner-divider">
          {overlay.changes.map((change, index) => (
            <p key={`${change.submitted_name}-${change.field}-${index}`}>
              {change.submitted_name} — {change.field.replace("hours_", "")}:{" "}
              <strong>{change.original_value}</strong> &rarr; <strong>{change.resumed_value}</strong>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

export function DecisionBanner({ state }: { state: DecisionBannerState }) {
  return (
    <>
      {renderBranch(state.branch)}
      {state.hoursChangesOverlay && (
        <HoursChangesOverlayBanner overlay={state.hoursChangesOverlay} />
      )}
    </>
  );
}
