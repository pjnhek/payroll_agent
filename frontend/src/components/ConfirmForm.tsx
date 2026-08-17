// Composes MutationForm and adds the operator confirmation guard that every destructive
// action in app/templates/run_detail.html carries today, e.g.
// `onsubmit="return confirm('Reject this payroll run? This cannot be undone.')"`.
//
// The React footgun this component exists to close: returning `false` from a React
// `onSubmit` handler does NOT cancel form submission -- only calling `preventDefault()`
// on the SyntheticEvent does. A component written against the return-value idiom would
// make a "Reject" click a one-click irreversible action the moment someone copied the
// old inline `onsubmit="return confirm(...)"` string into JSX. See
// MutationForm.test.tsx for the two independent mutations that prove this component
// does not make that mistake.
import type { ReactNode } from "react";

import { MutationForm, type MutationActionPath } from "./MutationForm";

export interface ConfirmFormProps {
  action: MutationActionPath;
  className?: string;
  children: ReactNode;
  // The prompt shown to the operator before the destructive action proceeds. Supplied by
  // the caller verbatim -- this component invents no wording of its own, matching every
  // inline confirm() guard in run_detail.html today.
  confirmMessage: string;
  // Testability seam. Real usage relies on the default (window.confirm, a real blocking
  // dialog); tests inject a deterministic stub so both the confirm and decline paths can
  // be proven without a real dialog blocking the test runner.
  confirmFn?: (message: string) => boolean;
}

export function ConfirmForm({
  action,
  className,
  children,
  confirmMessage,
  confirmFn = (message) => window.confirm(message),
}: ConfirmFormProps) {
  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    const confirmed = confirmFn(confirmMessage);
    if (!confirmed) {
      // The decline path, and the whole point of this component. Only preventDefault()
      // cancels a form submission from a React onSubmit handler -- a bare `return false`
      // (or no call at all) lets the native POST proceed regardless of what this
      // function returns.
      event.preventDefault();
    }
    // On confirm, no preventDefault is called: the native POST proceeds exactly as
    // MutationForm's plain (unwrapped) case would.
  }

  return (
    <MutationForm action={action} className={className} onSubmit={handleSubmit}>
      {children}
    </MutationForm>
  );
}
