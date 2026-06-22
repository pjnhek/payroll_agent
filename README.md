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

> **Net pay includes IRS Pub 15-T 2026 federal income-tax withholding** (Worksheet 1A
> percentage method, all filing statuses). The calculation is tested against the
> independently-transcribed wage-bracket method tables as a cross-check oracle.

## Known Limitations

**Additional Medicare surtax (0.9% over $200k YTD) is not modeled.**
The Additional Medicare Tax of 0.9% that applies to wages over $200,000 (single/MFS)
or $250,000 (MFJ) in a calendar year is **not computed** by this engine. When an
employee's Medicare-wage proxy (YTD SS wages + current gross) exceeds $200,000, the
engine sets `additional_medicare_not_modeled = True` on the returned `PaystubLineItem`
as a known-limitation flag. No surtax amount is withheld. This is an accepted scope
limitation for a demo at typical wage levels.

_(The full README — setup, architecture, demo, eval chart, and the complete
FICA/IRS citations and OBBBA / Additional-Medicare disclaimers — is added in the
hosting/demo phase.)_
