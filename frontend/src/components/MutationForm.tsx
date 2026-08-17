// The one sanctioned native-form emitter (alongside ConfirmForm -- see
// eslint.config.js's no-restricted-syntax override, scoped to exactly these two
// component paths). Every operator mutation in app/templates/run_detail.html today is a
// plain `<form method="post" action="...">`; this component reproduces exactly that
// shape so a submission is a full browser navigation, never a client-side network call.
// That native navigation is what carries the redirect-encoded operator feedback the
// server sets on the redirect target (see app/routes/operator_feedback.py's `?notice=`
// channel), and what keeps every mutation usable with JavaScript disabled.
//
// Do NOT mount this on the runs list page in this plan -- the demo send-test form at
// runs_list.html:117-128 stays server-rendered Jinja (D-22-12). This component's only
// consumer in Phase 22 is its own test suite; Phase 23 is where the 14 real mutation
// forms compose it.
import type { FormEventHandler, ReactNode } from "react";

// The full set of real mutation route paths this project's operator console exposes,
// read off app/routes/runs.py's @router.post handlers. Typing `action` against this
// union instead of a free-form string means a typo'd path fails at compile time rather
// than posting to a route that does not exist.
export type MutationActionPath =
  | `/runs/${string}/approve`
  | `/runs/${string}/reject`
  | `/runs/${string}/resolve`
  | `/runs/${string}/retrigger`
  | `/runs/${string}/simulate-reply`
  | `/runs/${string}/delivery-review/retry-now`
  | `/runs/${string}/delivery-review/clarification/retry-now`
  | `/runs/${string}/delivery-review/clarification/mark-handled`
  | `/runs/${string}/delivery-review/clarification/reject`
  | `/runs/${string}/delivery-review/mark-delivered`
  | `/runs/${string}/delivery-review/authorize`;

export interface MutationFormProps {
  action: MutationActionPath;
  className?: string;
  children: ReactNode;
  // Composition seam for ConfirmForm ONLY. A caller that mounts MutationForm directly
  // never supplies this, and in that case MutationForm attaches no handler of its own:
  // the native POST proceeds as a plain browser navigation with nothing intercepting it.
  onSubmit?: FormEventHandler<HTMLFormElement>;
}

export function MutationForm({ action, className, children, onSubmit }: MutationFormProps) {
  return (
    <form method="post" action={action} className={className} onSubmit={onSubmit}>
      {children}
    </form>
  );
}
