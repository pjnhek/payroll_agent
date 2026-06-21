# Payroll Agent

An email-driven system that automates a weekly payroll intake: a client business
emails its employees' hours; an LLM-driven pipeline reads the email, reconciles the
submitted names against the business's roster, decides whether it can process the
run or must ask a clarifying question, computes the payroll, and routes the result
to a single human operator for one approval before the confirmation goes back to
the client.

The core value: every LLM judgment call (name match, process-vs-clarify) is **gated
by code** so a low-confidence match can never reach a real payroll calculation.

## Disclaimers (read these first)

> **This is an explicitly educational model — not a production payroll system.** It
> is built to demonstrate a gated, agentic judgment pipeline end-to-end on a free
> stack. Do not use it to run real payroll.

> **Net pay is PRE-FEDERAL in this slice.** The current calculation is deliberately
> thin: it computes gross pay and FICA (Social Security + Medicare) only. There is
> **no federal income-tax withholding** yet — `federal_withholding` is `0` and no
> federal figure is fabricated anywhere. Net pay is therefore labeled
> **"Net pay (pre-federal — real federal withholding lands in Phase 3)."** Real IRS
> Pub 15-T federal withholding is added in Phase 3, before any correctness claim.

_(The full README — setup, architecture, demo, eval chart, and the complete
FICA/IRS citations and OBBBA / Additional-Medicare disclaimers — is added in the
hosting/demo phase.)_
