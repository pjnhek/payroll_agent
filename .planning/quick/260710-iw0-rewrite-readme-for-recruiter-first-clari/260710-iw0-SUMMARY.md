---
quick_id: 260710-iw0
status: complete
commit: 5b9eda1
---

# README rewrite summary

Reworked the README into a recruiter-first project landing page while keeping the engineering
details defensible against the current repository.

## Completed

- Removed the duplicated Mermaid/PNG architecture rendering.
- Added one simplified workflow diagram and linked the detailed SVG separately.
- Corrected the `David Reyez` unresolved-name story and distinguished it from the `D. Reyes`
  collision fixture.
- Clarified when confirmed aliases are persisted and how the human gate fits the learning loop.
- Reframed the eval snapshot as 18 labeled fixtures rather than a universal guarantee.
- Replaced the zero-cost, continuously-warm, automatic-deploy, and exactly-once implications with
  narrower descriptions supported by the implementation.
- Consolidated tax and runtime caveats in a single Known limitations section.
- Added concise local quality-gate and deployment instructions.

## Verification

- `git diff --check` passed.
- All local README links resolve to committed files.
- Eval counts and percentages match `eval/summary.json`.
- The README commit contains only `README.md`; existing Phase 1-11 deletions were not staged.

