// Modeled directly off app/templates/run_detail.html:99-208 (the "Decision reason
// banner" region, plus the standalone "Cross-round hours CHANGE banner" that follows
// it). That template is an if/elif chain with SIX mutually exclusive arms and an
// implicit fallthrough (no trailing `{% else %}`) when none of the six match, followed
// by a SEPARATE, independent `{% if run.hours_changes %}` -- never an `elif` of the
// chain above -- so it renders alongside whichever banner (or no banner) is showing.
//
// The six branches, read off the template's own conditions and wording:
//   1. run.status == 'error'                                            (:99)
//   2. delivery_review or (needs_operator and delivery_review_marker)   (:112)
//   3. run.status == 'needs_operator'                                   (:116)
//   4. run.status == 'awaiting_reply'                                   (:149)
//   5. run.decision.final_action == 'process'                          (:161)
//   6. run.decision.final_action == 'request_clarification'            (:165)
// Falling through all six renders nothing -- the explicit `none` variant below.
//
// Encoding the hours-changed notice as a SEVENTH union variant (a flat switch) would
// make "no banner, overlay present" and "a banner, overlay present" mutually exclusive
// states, which the template proves they are not (:196's `if` sits entirely outside the
// if/elif chain above it). That is precisely the modeling error DETAIL-01 exists to
// prevent, so the overlay is a field on the state object instead.

export type BannerBranch =
  | { kind: "error" }
  | { kind: "delivery_review_required" }
  | { kind: "needs_operator" }
  | { kind: "awaiting_reply" }
  | { kind: "decision_process" }
  | { kind: "decision_clarification_requested" }
  | { kind: "none" };

export interface HoursChangeItem {
  submitted_name: string;
  field: string;
  original_value: string;
  resumed_value: string;
}

// Orthogonal to `branch` -- present or absent independent of which branch (or no
// branch) is showing. Maps to the persisted `payroll_runs.hours_changes` pipeline-time
// fact rendered at run_detail.html:196-208, never a render-time re-derivation.
export interface HoursChangesOverlay {
  changes: HoursChangeItem[];
}

export interface DecisionBannerState {
  branch: BannerBranch;
  hoursChangesOverlay: HoursChangesOverlay | null;
}
