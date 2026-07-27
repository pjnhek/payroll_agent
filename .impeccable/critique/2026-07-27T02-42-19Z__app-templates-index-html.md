---
target: the landing page /
total_score: 21
max_score: 36
na_heuristics: 7
p0_count: 1
p1_count: 3
timestamp: 2026-07-27T02-42-19Z
slug: app-templates-index-html
---
Method: dual-agent (A: design review, isolated · B: detector + evidence, isolated)

Browser automation was unavailable to both agents (Claude-in-Chrome extension reported "not connected"). No user-visible overlay exists. Contrast ratios and the 390px overflow finding are computed from source, not observed in a rendered browser, and are labeled as such.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 1 | No in-flight feedback on picker reload or composer submit; "Run pipeline" redirects with no transition cue; no cold-start messaging despite it being a first-class product concern |
| 2 | Match System / Real World | 2 | Domain metaphor is right, but "Operator Path-2 armed for: Metro Deli Group" is undefined internal jargon shown to every visitor |
| 3 | User Control and Freedom | 3 | Simple reversible form page; back/reselect work; no traps |
| 4 | Consistency and Standards | 2 | Picker and composer float on bare page background while the system cards everything else; `.btn-approve` does double duty as demo trigger and money-gate approval |
| 5 | Error Prevention | 3 | maxlength backed by real server-side checks (demo.py:194); locked dropdown prevents typos |
| 6 | Recognition Rather Than Recall | 3 | Roster sits directly above the composer that needs those names; nothing connects it to the proof path |
| 7 | Flexibility and Efficiency | n/a | One-shot Persuade visit; no repeat-use path exists to accelerate |
| 8 | Aesthetic and Minimalist Design | 2 | Restrained per intent, but a passive video CTA outweighs the real one and narrow-width layout is unresolved |
| 9 | Error Recovery | 2 | `callout-error` is present and real but generic; no diagnostic detail, no cold-start-aware guidance |
| 10 | Help and Documentation | 3 | Loom video plus /eval link function as genuine in-page documentation for a zero-context visitor |
| **Total** | | **21/36** | **Acceptable (58%)** |

Heuristic 7 scored n/a. Applicable maximum is 36, not 40.

## Design Specificity Verdict

**Structurally generic, with specificity surviving only in content.** The shell is a SaaS landing template, and the stylesheet says so in its own first line: "Linear/Stripe-style SaaS design system" (style.css:2-3). None of the system's signature components appear on this page. The thread message, the payroll disclosure, and the metric strip all live downstream on /runs/{id} and /eval, which means the least product-specific screen in the product is the only screen the confirmed primary audience actually lands on. "Try it live" plus a lede describing generic pipeline mechanics could sit in front of a resume parser or an invoice OCR tool with zero rewrite.

The one genuine touch is content, not structure: the composer's default body names "Maria" and "James", matching the live roster of the selected business (index.html:66-71 against :36-42).

**Deterministic scan:** exit code 2, 2 findings, both at app/templates/base.html:10, zero in index.html.
- `overused-font` | base.html:10 | "Google Fonts: inter"
- `single-font` | base.html:10 | "only font used is inter"

Directory context run surfaced 2 more outside this target: `design-system-font-size` at ops.html:51 (20px) and ops.html:54 (26px), both off the DESIGN.md type ramp.

**Adjudication:** B flagged the Inter findings as "a judgment call, not a detector error." For this project they are neither a false positive nor a judgment call. The user confirmed "generic AI-generated SaaS" as a binding anti-reference hours ago, and Inter on white with an indigo accent and 8px cards is the precise center of that reference. The detector mechanically located the anti-reference at a single line. That is the most on-target finding in this run.

**Visual overlays:** none. Script injection was never attempted because no browser tab was reachable.

## Overall Impression

The engineering underneath this page is unusually strong and the page does almost nothing to say so. It is composed as a generic "try our demo" surface for a user who already knows what the product is, while the confirmed primary user is an outsider with roughly 90 seconds who does not. The single biggest opportunity is that the product's actual claim, "the LLM reads, deterministic code decides," is absent from the one screen built to be evaluated by outsiders. Everything else on this list is downstream of that.

## What's Working

1. **Composer defaults are integrated, not lorem.** The prefilled body references real roster names for the selected business, so a first click plausibly just works. Cheap, effective trust (index.html:66-71).
2. **Roster-before-composer ordering is a real recognition win.** The names a visitor needs sit immediately above the field that needs them, rather than demanding recall (index.html:24-46 into :49-80).
3. **`record_only=True` is load-bearing invisible design.** The in-app composer cannot send real mail to a `.example` address (demo.py:174-178), which is exactly what lets the page offer an unguarded, no-signup button safely.

## Priority Issues

**1. [P0] The page never states the product's claim.** "The LLM reads. Deterministic code decides." appears nowhere in index.html. README.md leads with it; the interface built specifically to be evaluated by outsiders does not. PRODUCT.md defines success as an evaluator reaching that conclusion from the interface itself.
*Why it matters:* the differentiator is the entire reason a hiring manager would keep reading. Without it, the page is a generic demo and the evaluation fails before the first click.
*Fix:* one sentence at or beside the lede, in product vocabulary (index.html:3-7).
*Suggested command:* `/impeccable clarify`

**2. [P1] The one interactive action cannot reach the differentiator.** The default composer body exercises only the exact-match happy path. The curated fixtures that trigger the clarify gate (`unknown_shorthand_metro` and siblings, demo.py:57-61) exist only on the downstream /runs page.
*Why it matters:* a 90-second evaluator's single click is statistically likely to produce the least interesting possible outcome, proving nothing that a plain script could not.
*Fix:* surface one or two curated fixtures on `/` itself, or hint under the textarea that an unlisted name triggers the gate (index.html:64-72, demo.py:36-62).
*Suggested command:* `/impeccable shape`

**3. [P1] Operator-internal state leaks onto the outsider-facing page.** "Operator Path-2 armed for: Metro Deli Group" renders unconditionally to every visitor whenever a demo binding exists (index.html:83-91, dashboard.py:74-97), in a success-green callout, naming a different business than the one selected above it. Confirmed rendering live.
*Why it matters:* it directly violates PRODUCT.md Principle 1, legibility to an outsider outranks operator efficiency, on the one page where that principle applies most.
*Fix:* move it to an operator-only surface (POST /demo/bind already exists unlinked at demo.py:135-159) or rewrite in outsider-legible language.
*Suggested command:* `/impeccable distill`

**4. [P1] The shell is the confirmed anti-reference.** Detector-located at base.html:10: Inter fetched from Google Fonts, and the only family in the system. Combined with indigo-on-white cards and 8px radius, this is the "generic AI-generated SaaS" look the user confirmed as binding anti-reference.
*Why it matters:* the visual system currently signals "competent template" at exactly the moment it needs to signal "authored by someone who thinks carefully." It also costs a render-blocking third-party request on a page whose first impression may already be a 23-second wake.
*Fix:* self-host or replace the typeface and let type carry the distinction the accent cannot. Pairs with the accent replacement already recorded as pending in DESIGN.md.
*Suggested command:* `/impeccable typeset`

## Persona Red Flags

**Jordan (confused first-timer):** "Try it live" names no product category. Five competing elements in the first five seconds (picker, composer, video, two footer links) with no ranking. The visually loudest element is a passive video, so Jordan watches instead of trying.

**Casey (distracted mobile):** the business picker is the first interactive element and is the one most likely to overflow at ~390px. No in-flight feedback means a slow-connection tap on "Run pipeline" reads as "nothing happened."

**Riley (stress tester):** maxlength is genuinely backed server-side (demo.py:194), no exploit there. Open gap: a failure occurring after the redirect to /runs/{run_id} is not covered by the `demo_queue_error` callout at all (demo.py:239).

**Morgan (the evaluator, where damage concentrates):** needs prior README context to know what to look for, because the interface never teaches the claim. Meets operator plumbing that actively contradicts the product's own stated principle. Gets a safe-path default that will not demonstrate the gate. And has a coin-flip chance of first meeting Render's unbranded 503 for 23 seconds.

## Minor Observations

- index.html:62 ships a dangling `{{ '' }}`, so the live subject field reads "Payroll submission — week of " with a trailing space and no date. Verified live.
- The 56px accent-filled play button (style.css:1040-1067) outweighs the real "Run pipeline" button, putting two accent-weighted CTAs on one page and violating DESIGN.md's own Accent Is A Pointer Rule.
- Picker and composer sit uncontained on bare page background while the roster table is carded; inconsistent with the system's own card vocabulary.
- Narrow-width risk at ~390px: nav and .page-wrapper keep fixed 64px side padding (style.css:73-82, :113-118), leaving ~262px of content, against a select with min-width 240px plus its label and no wrap on .form-inline. This is CSS arithmetic, not an observed screenshot.
- `.btn-approve` is reused for "Run pipeline" (index.html:74), sharing an identity with the real money-gate approval button elsewhere.
- No current-page indicator in the nav.
- Every page's `<title>` is the bare string "Pyrl" (base.html:6), so an evaluator with several tabs open cannot tell them apart.
- Contrast: muted ink on page ground computes to ~4.55:1 across .lede, .form-help, and .column-label. That passes 4.5:1 by 0.05 and needs live confirmation before being trusted.

## Questions to Consider

1. If "the LLM reads, code decides" is not on the one page built for outside evaluators, whose job is it to say it?
2. Is `/` trying to be a product demo or a proof-of-claim page? It currently reads as the former while PRODUCT.md defines an audience that needs the latter.
3. Would leading with a curated "watch it catch a mistake" fixture serve a 90-second evaluator better than a blank happy-path slate?
4. The accent is already confirmed for replacement. Is the outsider's literal first screen where that swap should land first?
