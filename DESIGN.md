---
name: Pyrl
description: A cool-neutral audit surface where tabular figures carry the weight, one accent marks the single next action, and depth never exceeds two steps.
colors:
  accent: "#4F46E5"
  accent-hover: "#4338CA"
  accent-soft: "#EEF0FE"
  page-ground: "#F7F8FA"
  surface: "#FFFFFF"
  surface-subtle: "#F9FAFB"
  border: "#E8EAED"
  border-strong: "#D6DAE0"
  ink: "#1A1D21"
  ink-muted: "#6B7280"
  ink-subtle: "#9CA3AF"
  danger: "#DC2626"
  danger-hover: "#B91C1C"
  state-good-fg: "#15803D"
  state-good-bg: "#DCFCE7"
  state-bad-fg: "#B91C1C"
  state-bad-bg: "#FEE2E2"
  state-pending-fg: "#3730A3"
  state-pending-bg: "#EEF0FE"
  state-escalate-fg: "#9A3412"
  state-escalate-bg: "#FFEDD5"
  state-neutral-fg: "#4B5563"
  state-neutral-bg: "#F3F4F6"
  banner-process-fg: "#166534"
  banner-process-bg: "#F0FDF4"
  banner-process-edge: "#BBF7D0"
  banner-clarify-fg: "#92400E"
  banner-clarify-bg: "#FFFBEB"
  banner-clarify-edge: "#FDE68A"
  banner-error-fg: "#991B1B"
  banner-error-bg: "#FFF1F2"
  banner-error-edge: "#FECDD3"
  thread-inbound-edge: "#94A3B8"
typography:
  display:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.1
    letterSpacing: "-0.02em"
    fontVariation: "tabular-nums"
  headline:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "-0.01em"
  lede:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  body:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
    letterSpacing: "normal"
  label:
    fontFamily: "Inter, system-ui, -apple-system, BlinkMacSystemFont, Segoe UI, Helvetica Neue, Arial, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "0.04em"
  mono:
    fontFamily: "ui-monospace, SF Mono, JetBrains Mono, Consolas, Liberation Mono, Menlo, monospace"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.6
    letterSpacing: "normal"
rounded:
  sm: "6px"
  md: "8px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "48px"
  3xl: "64px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#FFFFFF"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 18px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-danger:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.danger}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 18px"
  button-danger-hover:
    backgroundColor: "#FEF2F2"
    textColor: "{colors.danger-hover}"
  button-neutral:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 18px"
  button-neutral-hover:
    backgroundColor: "{colors.surface-subtle}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 11px"
    width: "100%"
  select:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "8px 30px 8px 11px"
    width: "100%"
  badge-good:
    backgroundColor: "{colors.state-good-bg}"
    textColor: "{colors.state-good-fg}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  badge-bad:
    backgroundColor: "{colors.state-bad-bg}"
    textColor: "{colors.state-bad-fg}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  badge-pending:
    backgroundColor: "{colors.state-pending-bg}"
    textColor: "{colors.state-pending-fg}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  badge-escalate:
    backgroundColor: "{colors.state-escalate-bg}"
    textColor: "{colors.state-escalate-fg}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  badge-neutral:
    backgroundColor: "{colors.state-neutral-bg}"
    textColor: "{colors.state-neutral-fg}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.xl}"
  table-header-cell:
    backgroundColor: "{colors.surface-subtle}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    padding: "10px 14px"
  table-cell:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    padding: "12px 14px"
  navigation:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    height: "56px"
    padding: "0 64px"
  banner-process:
    backgroundColor: "{colors.banner-process-bg}"
    textColor: "{colors.banner-process-fg}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  banner-clarify:
    backgroundColor: "{colors.banner-clarify-bg}"
    textColor: "{colors.banner-clarify-fg}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
  banner-error:
    backgroundColor: "{colors.banner-error-bg}"
    textColor: "{colors.banner-error-fg}"
    rounded: "{rounded.md}"
    padding: "{spacing.md}"
---

# Design System: Pyrl

<!-- Captured by scan from app/static/style.css and app/templates/*.html. One value is
     deliberately provisional: colors.accent (#4F46E5) is confirmed to be replaced with a
     non-AI accent. The token is normative; its current value is not. See Colors. -->

## Overview

**Creative North Star: "The Audit Trail"**

Every screen exists to make a claim checkable. Evidence sits beside conclusion rather than replacing it, figures align so they can be compared down a column, and nothing is asserted without its source visible on the same page. This is not a decorative stance: the run-detail page shows the raw client email next to the machine's reading of it precisely so a human can catch the machine being wrong. The design's job is to keep that comparison easy and to stay out of the way of it.

The system is cool, quiet, and dense-but-breathing. Neutrals do almost all the work: a faint blue-grey page ground with pure white surfaces lifted just off it, hairline borders instead of heavy rules, and near-black text at a comfortable 14px. Exactly one accent exists, and it marks the single next action or the one thing to follow. Color is otherwise reserved entirely for state, where it is doing real work: telling an operator whether a run is waiting, escalated, or wrong.

Two anti-references are confirmed and binding. The first is **AI-product atmosphere**: dark surfaces, violet glow, orbs, shimmer, gradient mesh, intelligence signaled through mood. This product's entire thesis is that it does not guess, so borrowing the visual language of vibes-based software actively undermines the claim. The second is **generic AI-generated SaaS**: the default indigo-on-white card dashboard that is competent and completely forgettable. This one requires honesty. Parts of the current implementation sit inside that anti-reference rather than outside it, which is why the accent is being replaced and why distinctiveness has to be earned through typography, tabular rigor, measure, and the signature components below rather than through hue. Treat the token layer as sound and the current character as unfinished.

**Key Characteristics:**

- Neutral-dominant; a single accent used sparingly and purposefully
- Tabular figures wherever numbers can be compared vertically
- Exactly two elevations, ever
- Radius encodes function: 6px for what you touch, 8px for what holds, pill for state
- Content measure chosen per content type, never per page
- Uppercase 11px eyebrow labels as the only region-naming device
- Server-rendered and legible with JavaScript off, by requirement

## Colors

A cool blue-grey neutral field carrying one accent and two parallel status palettes.

### Primary

- **Signal Indigo** (`{colors.accent}`): The single next action and the single thing to follow. It appears on the primary button, on links inside tables and page footers, on the focus ring, on the outbound stripe of a thread message, and on the disclosure marker. It never fills a large surface.

> **Provisional value.** The accent slot is normative; `#4F46E5` is not. It has been confirmed for replacement with a hue that reads accounting rather than machine learning. Until that replacement is chosen, do not add new hard-coded indigo values anywhere, and reference the token so the swap stays a one-line change. The five status families below are tuned against this indigo and will need re-checking when it moves.

### Neutral

- **Cool Paper** (`{colors.page-ground}`): The page ground. Every surface sits on top of it; it is never used for a card.
- **Surface White** (`{colors.surface}`): Cards, tables, table rows, the nav bar, the code-face panels, and inputs at rest.
- **Recessed White** (`{colors.surface-subtle}`): Table headers, hovered table rows, thread-message meta strips, and the neutral button's hover. Signals "this is chrome, not content."
- **Hairline** (`{colors.border}`): The default divider and container edge. One pixel, low contrast, everywhere.
- **Stated Edge** (`{colors.border-strong}`): Reserved for interactive edges: input, select, and secondary/neutral button borders. A control is distinguishable from a container by border weight alone.
- **Near-Black Ink** (`{colors.ink}`): All primary text and headings.
- **Muted Ink** (`{colors.ink-muted}`): Secondary text, helper copy, eyebrow labels, table headers, timestamps, nav links at rest.
- **Subtle Ink** (`{colors.ink-subtle}`): The faintest tier; currently only the neutral button's hover border.

### Semantic: state

Two parallel status palettes exist, and the distinction is deliberate and load-bearing.

- **Badge palette** (saturated fill, `state-*`): high-contrast, small-area. Five families map to run state: neutral (inert), pending (`awaiting_approval`, running), good (processed, sent, reconciled), bad (rejected, error), escalate (`needs_operator`). Escalate is its own family on purpose: an escalation is neither routine-pending nor a failure.
- **Banner palette** (tinted wash, `banner-*`): low-contrast, large-area, always paired with a matching hairline edge. Three families: process, clarify/awaiting, error.
- **Danger** (`{colors.danger}` / `{colors.danger-hover}`): destructive intent on controls, and the ops alarm border. Never used as a status fill.
- **Inbound Slate** (`{colors.thread-inbound-edge}`): the 4px left stripe on a message from the client, opposite the accent stripe on a message from the system. Direction is readable without reading a word.

### Named Rules

**The Two Palettes Rule.** Badges are saturated because they are small; banners are tinted because they are large. Never cross them. A badge must not use a banner wash, and a banner must not use a badge fill. If a new state needs both a badge and a banner, it needs one entry in each family, not one shared color.

**The Accent Is A Pointer Rule.** The accent marks what to do next or what to follow. It is never a background for content, never a decorative panel, and never more than a small fraction of any screen. Its scarcity is what makes it readable.

**The Token-First Rule.** Every status color currently lives as a literal hex inside its component rule rather than in `:root`. That is the system's main drift risk and the reason the accent replacement is more expensive than it should be. New state colors are declared as custom properties first and referenced second.

## Typography

**Display Font:** Inter (with `system-ui`, `-apple-system`, `BlinkMacSystemFont`, `Segoe UI`, `Helvetica Neue`, Arial, sans-serif)
**Body Font:** Inter (same stack; one family carries the whole interface)
**Label/Mono Font:** the platform mono stack (`ui-monospace`, SF Mono, JetBrains Mono, Consolas, Liberation Mono, Menlo)

**Character:** One neutral grotesque doing everything, tightened at the top of the scale and never pushed heavy. Only three weights exist in the entire system (400, 500, 600), and the webfont request loads exactly those three: nothing is faked and nothing is loaded unused. Monospace is not a stylistic choice here; it marks machine-verbatim content, meaning anything a human must read exactly as the machine received or produced it.

### Hierarchy

- **Display** (600, 30px, -0.02em, tabular): eval metric values only. The largest type in the product is a number, which is correct for the North Star.
- **Headline** (600, 24px, -0.02em, 1.2): the page `h1`. One per page.
- **Title** (600, 18px, -0.01em, 1.3): section headings, empty-state titles, disclosure summaries. The brand mark is a near-sibling at 17px/600/-0.01em.
- **Lede** (400, 15px, 1.55, max 640px): the single orienting paragraph under a page headline.
- **Body** (400, 14px, 1.55): all table cells, form controls, banners, and paragraph text.
- **Label** (600, 11px, 0.04em, uppercase): the eyebrow. Names a region above the thing it names. Table headers are a near-sibling at 11px/600/0.03em uppercase.
- **Mono** (400, 12px, 1.6): raw email bodies, thread message bodies, provider keys. Steps to 13px in the composer textarea and down to 11px for truncated fixture previews.
- **Micro** (12px): helper text, timestamps, cell labels, badges. The floor; nothing smaller than 11px exists.

### Named Rules

**The Tabular Money Rule.** Any figure a reader might compare down a column takes `font-variant-numeric: tabular-nums`. It is currently on numeric table cells, timestamp cells, thread times, and metric values. Every new numeric column joins them. In a payroll product, digits that shift width between rows are a legibility bug, not a stylistic preference.

**The Monospace Means Verbatim Rule.** Mono is reserved for content the machine received or emitted exactly as shown: the raw client email, a thread body, a provider idempotency key. Never use it for emphasis, headings, or UI labels. When a reader sees mono, they should trust it has not been prettified.

**The Eyebrow Is Not A Heading Rule.** The 11px uppercase label names a region; it never carries the region's meaning alone and never substitutes for a real heading in the document outline.

## Layout

A single centered column shell: max 1280px wide, 48px vertical and 64px horizontal padding, sitting under a 56px fixed-height nav that shares the same 64px horizontal inset so the brand mark aligns with the content edge below it.

Inside that shell, **width is a property of content, not of page**. The implementation is consistent about this and the values are meaningful: 560px for forms, roster tables, and callouts; 640px for lede prose; 680px for the reply composer; 820px for the email conversation; 960px for the payroll detail panel; the full 1280px only for wide data tables. Nothing spans the full shell just because it can.

Spacing runs on a 4/8/16/24/32/48/64 scale with 8px and 16px carrying most of the rhythm: 16px between stacked fields and messages, 24px between field groups and callouts, 32px between page sections, 48px around the page interior.

Repeating grid patterns: a two-column equal grid for the ops transport panels, a three-column equal grid for the eval metric strip, and `auto-fit minmax()` grids for the delivery-review fact list (180px floor) and its action groups (260px, or 220px for the clarification variant). The `auto-fit` grids are the only genuinely fluid layout in the system.

**Known gap, recorded as fact not doctrine:** there is exactly one breakpoint (`max-width: 700px`) and it adjusts only two things, stacking the conversation heading and the disclosure summary. Everything else relies on the intrinsic `auto-fit` grids and `max-width` caps. Wide data tables in particular have no small-screen treatment. This is thin coverage, not a considered mobile strategy, and should not be cited as an intentional minimalism.

There is no dark mode anywhere in the system; no `prefers-color-scheme` block exists.

### Named Rules

**The Measure Rule.** Choose a max-width from the content type, not the viewport. Prose caps near 640px, forms near 560px, reading surfaces near 820px. Full-shell width is for tabular data only.

## Elevation & Depth

A deliberately two-step system, confirmed as doctrine rather than accident. Every resting container carries a soft low-opacity double shadow that lifts it off the cool page ground without announcing itself; hover raises it exactly one step further. There is no third level and nothing floats dramatically. Depth here is about separating surface from ground, not about drama or hierarchy theatre.

The evidence that this is considered rather than sprayed: nested tables explicitly zero their own shadow so a table inside a card never reads as a double frame.

### Shadow Vocabulary

- **Resting lift** (`box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06)`): every container at rest, including cards, tables, code-face panels, thread messages, the payroll disclosure, the nav bar, and the demo thumbnail.
- **Hover lift** (`box-shadow: 0 2px 4px rgba(16, 24, 40, 0.04), 0 4px 12px rgba(16, 24, 40, 0.07)`): the primary button and the demo thumbnail on hover. Nothing else.
- **Focus ring** (`box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.18)`): a 3px accent-tinted ring replacing the native outline on every control. The destructive button uses a danger-tinted ring at the same geometry.

### Named Rules

**The Two-Step Rule.** Two elevations exist: resting and hover. Adding a third is a design change requiring a decision, not a local judgment call. If something needs to feel higher, restructure the layout rather than inventing a shadow.

**The No Double Frame Rule.** A container nested inside another container drops its shadow. One border plus one shadow per visual boundary.

## Shapes

Rectilinear and calm. Nothing is circular except the badge status dot and the play overlay; nothing is clipped or angled; no shape is decorative.

Radius carries meaning on a three-step scale. **6px** belongs to things you operate: buttons, inputs, selects, textareas. **8px** belongs to things that hold content: cards, tables, banners, callouts, code panels, thread messages, the disclosure panel, the demo thumbnail. **Pill** belongs to state: badges only. Reading radius alone tells you whether something is a control, a container, or a status.

Borders are almost always exactly 1px. The two deliberate exceptions both encode information rather than style: a **4px left stripe** on a thread message (accent for outbound, slate for inbound) makes conversation direction scannable without reading, and a **6px round dot** inside each badge, drawn from `currentColor` at 90% opacity, gives all five status families one shared mechanism with five palettes.

The select control's chevron is an inline data-URI SVG stroked to match muted ink, so no icon font or network request is involved.

### Named Rules

**The 6/8/Pill Rule.** Radius is functional. 6px operates, 8px holds, pill states. A new component inherits the radius of its function, not of its neighbor.

**The One Mechanism, Many Palettes Rule.** When a family needs N variants, build one structural rule and vary only color, as the badge dot does through `currentColor`. Never fork the structure per variant.

## Components

**Character: precise and restrained.** Controls recede so the data has the only real presence. Hairline borders, tight padding, 150ms transitions, and a half-pixel press. Nothing bounces, nothing glows, nothing asks for attention it has not earned.

### Buttons

- **Shape:** gently rounded (6px), inline-flex, centered, 8px by 18px padding, 14px/500 label.
- **Primary:** accent fill, white label, resting lift; hovers to the deeper accent and the hover lift. One per view: it is the run's next action.
- **Destructive:** white fill, danger label, stated edge. Outlined rather than filled, so the loud option is not the visually loudest one. Hovers to a faint red wash with a red-tinted edge.
- **Neutral:** white fill, ink label, stated edge; hovers to recessed white with a subtle-ink edge.
- **Focus:** native outline removed and replaced by the 3px accent ring on every variant; the destructive variant uses a danger-tinted ring. Never remove the ring without replacing it.
- **Press:** `translateY(0.5px)`. A half pixel, felt rather than seen.

**Known drift.** A base `.btn` class exists at `app/static/style.css:418` and is used by no template. The three real variants each re-declare its seven base properties independently. New variants compose the base plus a modifier.

### Badges

- **Style:** pill, 3px by 9px, 12px/500, with a 6px `currentColor` dot at 90% opacity drawn by `::before`.
- **Families:** neutral, pending, good, bad, escalate. One structural rule, five palettes.
- **Variants:** an uppercase treatment drops to 11px with 0.03em tracking; an inline treatment used beside a run-detail heading rises to 13px and drops the dot.

### Cards / Containers

- **Corner:** 8px.
- **Background:** surface white on the cool page ground.
- **Border:** 1px hairline.
- **Shadow:** resting lift; see The No Double Frame Rule for nesting.
- **Padding:** 32px for the padded variant.

### Tables

- **Frame:** separated borders with 8px radius and clipped overflow, so the header fill respects the corner.
- **Header:** recessed white, 11px/600 uppercase muted ink with 0.03em tracking, 10px by 14px padding, hairline bottom.
- **Cell:** 14px ink, 12px by 14px padding, hairline bottom; the last row drops its border.
- **Row hover:** recessed white, 150ms.
- **Numeric cell:** right-aligned and tabular.
- **Nested:** the subtable variant drops the shadow and keeps bottom margin.

### Inputs / Fields

- **Style:** white fill, 1px stated edge, 6px radius, 8px by 11px padding, full width, 14px sans.
- **Focus:** border shifts to accent and the 3px accent ring appears. No layout shift.
- **Select:** the same shell with appearance stripped, a muted-ink data-URI chevron 10px from the right, and 30px right padding to clear it.
- **Textarea:** vertical resize only; the mono variant steps to 13px mono for composing raw email.
- **Label:** 13px/500 ink, block, 4px below. Helper text is 12px muted ink.

### Navigation

- **Style:** 56px fixed height, surface white, hairline bottom, resting lift, 64px horizontal inset matching the page, 24px gap.
- **Brand:** 17px/600 at -0.01em in full ink, pushed left with `margin-right: auto`; hovers to accent.
- **Links:** 14px/500 muted ink; hover to full ink. Underline is never used for nav state.
- **Mobile:** no treatment. The nav does not adapt below 700px.

### Signature: the thread message

The system's most characteristic component and the one that carries the North Star. A conversation is a vertical stack of bordered 8px cards, each with a 4px left stripe encoding direction (accent for what the system sent, slate for what the client sent), a recessed-white meta strip carrying purpose badges and a right-pushed tabular timestamp, an optional subject line at 15px/600, a muted 12px address block, and a mono body that preserves whitespace and wraps anywhere rather than truncating. The refusal to truncate is the design decision: this is the evidence surface, and hidden evidence defeats the page's purpose.

### Signature: the payroll disclosure

A `<details>` panel at 960px with the standard card treatment, whose summary is a flex row with an eyebrow label above a 16px bold title and an accent `+` marker that becomes `–` when open. Opening adds a hairline under the summary and reveals a 32px-gap grid at 24px padding. It exists so the computed payroll is available beside the evidence without dominating it, collapsed by default.

### Signature: the metric strip

Three equal columns, 32px gutters, each an 11px uppercase muted eyebrow above a 30px/600 tabular figure at -0.02em. The largest type in the product, used for the eval's headline numbers. Restraint is what makes it land: no cards, no borders, no color, just label and figure.

## Do's and Don'ts

### Do:

- **Do** reference tokens through `var(--…)` rather than repeating a literal, especially for the accent, which is scheduled to change.
- **Do** declare a new status color as a custom property in `:root` before using it, and add it to both the badge family and the banner family if it needs both.
- **Do** put `font-variant-numeric: tabular-nums` on every numeric or timestamp column you add.
- **Do** compose a new button as the base `.btn` plus a modifier that changes only color and border.
- **Do** pick a max-width from the content type (560 forms, 640 prose, 820 reading, 960 detail, 1280 tabular).
- **Do** keep every surface legible with JavaScript disabled; the 2-second status poller is enhancement only, and `/ops` is verified JS-free.
- **Do** replace a removed focus outline with the 3px ring at the same geometry, always.
- **Do** use monospace only for content the machine received or produced verbatim.

### Don't:

- **Don't** introduce a third elevation. Two exist; restructure instead.
- **Don't** clone the button base into a new class, as the three current variants do.
- **Don't** hard-code a new status hex inline. The existing literals are the system's main drift risk, not its pattern.
- **Don't** add another indigo literal anywhere while the accent is pending replacement.
- **Don't** use the accent as a large fill or a decorative panel background.
- **Don't** cross the two status palettes: no banner wash on a badge, no badge fill on a banner.
- **Don't** ship a class name with no CSS behind it. Four already exist (`status-badge`, `mt-md`, `failure-summary`, `failure-secondary`) and each is either dead markup or a silently missing style.
- **Don't** truncate evidence content. Thread bodies and raw email wrap and scroll; they never ellipsize.
- **Don't** reach for dark surfaces, glow, gradient mesh, shimmer, or orbs. AI-product atmosphere is a confirmed anti-reference and it contradicts the product's core claim.
- **Don't** settle for the default indigo-on-white card dashboard. Generic AI-generated SaaS is a confirmed anti-reference, and the current implementation is close enough to it that new work must actively earn distinction through type, measure, and tabular rigor.
- **Don't** add a build step, bundler, or client framework to achieve a visual effect. Server-rendered with one hand-authored stylesheet is a binding product constraint.
- **Don't** add a font weight outside 400, 500, and 600, or the webfont request stops matching what is used.
