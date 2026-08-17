// Added alongside DecisionBanner.tsx and banner.ts (both listed in 22-08-PLAN.md's
// files_modified) so `npm run test -- DecisionBanner`, the plan's own verify command,
// has a matching test file to run. Not itself named in the plan's files_modified list --
// see SUMMARY.md's Deviations section.
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DecisionBanner } from "./DecisionBanner";
import type { DecisionBannerState, HoursChangesOverlay } from "../types/banner";

const BRANCH_CASES: Array<{
  branch: DecisionBannerState["branch"];
  className: string;
  heading: string;
}> = [
  { branch: { kind: "error" }, className: "banner-error", heading: "Error" },
  {
    branch: { kind: "delivery_review_required" },
    className: "banner-awaiting",
    heading: "Delivery review required",
  },
  { branch: { kind: "needs_operator" }, className: "banner-clarify", heading: "Needs Operator" },
  {
    branch: { kind: "awaiting_reply" },
    className: "banner-awaiting",
    heading: "Awaiting client reply",
  },
  { branch: { kind: "decision_process" }, className: "banner-process", heading: "Decision: Process" },
  {
    branch: { kind: "decision_clarification_requested" },
    className: "banner-clarify",
    heading: "Decision: Clarification requested",
  },
];

const SAMPLE_OVERLAY: HoursChangesOverlay = {
  changes: [
    {
      submitted_name: "Jane Doe",
      field: "hours_regular",
      original_value: "40",
      resumed_value: "42",
    },
  ],
};

describe("DecisionBanner", () => {
  it.each(BRANCH_CASES)(
    "renders exactly one banner for the $branch.kind branch",
    ({ branch, className, heading }) => {
      const { container } = render(
        <DecisionBanner state={{ branch, hoursChangesOverlay: null }} />,
      );
      const banners = container.querySelectorAll(".banner");
      expect(banners).toHaveLength(1);
      expect(banners[0]).toHaveClass(className);
      expect(banners[0]).toHaveTextContent(heading);
    },
  );

  it("renders nothing for the no-banner state with no overlay", () => {
    const { container } = render(
      <DecisionBanner state={{ branch: { kind: "none" }, hoursChangesOverlay: null }} />,
    );
    expect(container.querySelectorAll(".banner")).toHaveLength(0);
  });

  it("renders only the overlay for the no-banner state with an overlay present", () => {
    const { container } = render(
      <DecisionBanner
        state={{ branch: { kind: "none" }, hoursChangesOverlay: SAMPLE_OVERLAY }}
      />,
    );
    const banners = container.querySelectorAll(".banner");
    expect(banners).toHaveLength(1);
    expect(banners[0]).toHaveTextContent("Hours changed on the client's reply");
  });

  it("renders both the branch banner and the overlay when a branch state carries an overlay -- the overlay does not replace the branch", () => {
    const { container } = render(
      <DecisionBanner
        state={{ branch: { kind: "decision_process" }, hoursChangesOverlay: SAMPLE_OVERLAY }}
      />,
    );
    const banners = container.querySelectorAll(".banner");
    expect(banners).toHaveLength(2);
    expect(banners[0]).toHaveTextContent("Decision: Process");
    expect(banners[1]).toHaveTextContent("Hours changed on the client's reply");
  });
});
