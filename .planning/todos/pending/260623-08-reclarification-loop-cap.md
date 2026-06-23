---
id: 260623-08
created: 2026-06-23
source: Phase 05 UAT discussion (off-roster reply behavior)
resolves_phase:
priority: low
---

# No cap on re-clarification rounds (correct, but no human-escape)

If a client (or the demo Simulate-reply) keeps replying with a name that doesn't resolve
(off-roster / ambiguous / still-typo'd), decide.py correctly keeps returning
request_clarification → the run loops awaiting_reply → extracting → awaiting_reply, sending
a fresh clarification email each round. This is the RIGHT default (never guess on a
money-moving name), and there is no infinite-loop in the code — each round needs a new inbound
reply, so it only advances on human/client action.

But there is no "give up after N rounds → route to a human operator" escape. In a real
deployment, a client who can never disambiguate would get clarification emails indefinitely.

v2 consideration (NOT a Phase 5 bug): add a clarification-round counter on the run; after N
unresolved rounds, route to a dedicated operator-review state (or surface a "needs manual
resolution" flag on the dashboard) instead of auto-sending another clarification. Keep the
deterministic no-guess guarantee — the escape hands off to a human, it does not start guessing.
