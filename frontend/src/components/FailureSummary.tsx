// Reproduces the pre-conversion failure presentation from runs_list.html exactly --
// both the secondary "Retries exhausted" badge and the stage/reason/attempts summary
// line, each independently hidden when its own inputs are absent. The former markup
// (before this conversion) rendered a neutral badge whose visibility was gated on
// run.failure.secondary_label, plus a separate span -- present only when at least one
// of stage/reason/attempts was truthy -- joining the non-empty parts with a middle-dot
// separator (Jinja's `| select | join(' · ')`).
//
// Field-for-field mirror of app/schemas/runs_list.py's FailureInfo -- consumed as
// plain server-computed strings, no re-derivation.
//
// The former DOM query-selector hook classes that decorated these two elements before
// this conversion are deliberately NOT reproduced: React holds this state and
// re-renders it directly, so a hook class name here would be dead markup the moment it
// existed (same rationale as StatusBadge).
export interface FailureInfo {
  secondary_label: string | null;
  stage: string | null;
  reason: string | null;
  attempts: string | null;
}

export function FailureSummary({ failure }: { failure: FailureInfo }) {
  const { stage, reason, attempts, secondary_label: secondaryLabel } = failure;
  // Reproduces Jinja's `| select | join(' · ')`: skip absent parts, no leading or
  // trailing separator.
  const summaryText = [stage, reason, attempts].filter(Boolean).join(" · ");

  return (
    <>
      <span className="badge badge-neutral" hidden={!secondaryLabel}>
        {secondaryLabel ?? ""}
      </span>
      {summaryText ? <span>{summaryText}</span> : null}
    </>
  );
}
