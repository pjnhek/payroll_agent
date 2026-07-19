---
status: complete
phase: 20-exactly-once-send
source: 20-01-SUMMARY.md, 20-02-SUMMARY.md, 20-03-SUMMARY.md, 20-04-SUMMARY.md, 20-05-SUMMARY.md, 20-06-SUMMARY.md, 20-07-SUMMARY.md, 20-08-SUMMARY.md, 20-09-SUMMARY.md, 20-10-SUMMARY.md, 20-11-SUMMARY.md, 20-13-SUMMARY.md, 20-14-SUMMARY.md, 20-16-SUMMARY.md, 20-17-SUMMARY.md, 20-18-SUMMARY.md, 20-19-SUMMARY.md, 20-20-SUMMARY.md, 20-21-SUMMARY.md, 20-22-SUMMARY.md, 20-23-SUMMARY.md, 20-24-SUMMARY.md, 20-25-SUMMARY.md, 20-26-SUMMARY.md, 20-27-SUMMARY.md
started: 2026-07-18T18:10:52Z
updated: 2026-07-19T04:55:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Safe delivery-review experience
expected: Start the app with a delivery-review fixture. The review shows only bounded status information and frozen email/attachment evidence; retrying or refreshing must not alter that frozen content or create a duplicate send.
result: pass

### 2. Transient delivery reuses the existing job only inside the reservation cutoff and keeps approval intact.
expected: This scenario requires a controlled provider failure and queue state that the public demo does not expose. Reply `skip — no transient-failure fixture` to record it as unavailable for browser UAT; its automated coverage is already green.
result: skipped
reason: "no transient-failure fixture"

### 3. Final confirmation and clarification lease expiry preserves the frozen snapshot and enters bounded purpose-specific delivery review.
expected: This scenario needs a controlled lease-expiry fixture for both confirmation and clarification delivery. The public demo cannot create it. Reply `skip — no lease-expiry fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no lease-expiry fixture"

### 4. Clarification reply routing rejects stale epoch headers and accepts only the current epoch.
expected: This scenario needs two specially threaded inbound replies with different epochs, which the public demo cannot create. Reply `skip — no stale-epoch fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no stale-epoch fixture"

### 5. Clarification delivery review shows the frozen question with safe choices only.
expected: This scenario needs a clarification-specific delivery-review fixture, which the public demo does not expose. Reply `skip — no clarification-review fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no clarification-review fixture"

### 6. Confirmation delivery proof stays scoped to the active reply epoch.
expected: This scenario needs a multi-epoch clarification-and-confirmation fixture, which the public demo cannot create. Reply `skip — no multi-epoch fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no multi-epoch fixture"

### 7. A stale outbound handler stops before provider delivery.
expected: This scenario needs a controlled concurrent worker race before provider delivery, which the public demo cannot create. Reply `skip — no worker-race fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no worker-race fixture"

### 8. Stale delivery settlement and final-lease reaping cannot mutate the current run.
expected: This scenario needs controlled concurrent delivery leases and reaping, which the public demo cannot create. Reply `skip — no lease-race fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no lease-race fixture"

### 9. Stale outbound leases retire without writing delivery state.
expected: This scenario needs a controlled stale lease token, which the public demo cannot create. Reply `skip — no stale-lease fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no stale-lease fixture"

### 10. The repository-wide static and default-running test gates are clean.
expected: The repository-wide static and default-running test gates are clean.
result: pass
source: automated
verification: "2026-07-19: uv run ruff check .; uv run pytest -q (1190 passed, 95 skipped)"

### 11. Active provider handoff blocks a concurrent retrigger from advancing the epoch.
expected: This scenario needs two controlled database connections paused around a provider handoff, which the public demo cannot create. Reply `skip — no handoff-race fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no handoff-race fixture"

### 12. The deliberately unsafe control exposes the concurrent epoch change after handoff release.
expected: This scenario needs the intentionally unsafe concurrent PostgreSQL control, which is test-only and not exposed in the public demo. Reply `skip — no unsafe-control fixture` to record it as unavailable for browser UAT; automated coverage is already green.
result: skipped
reason: "no unsafe-control fixture"

### 13. A same-slot retry receives the original Message-ID, envelope, headers, and attachment bytes while review and attachment reads remain owner-scoped.
expected: A same-slot retry receives the original Message-ID, envelope, headers, and attachment bytes while review and attachment reads remain owner-scoped.
result: pass
source: automated
coverage_id: 20-01-D2

### 14. The durable queue accepts an outbound send only with a run UUID, frozen email UUID, and snapshot-derived dedup key.
expected: The durable queue accepts an outbound send only with a run UUID, frozen email UUID, and snapshot-derived dedup key.
result: pass
source: automated
coverage_id: 20-02-D1

### 15. An operator retry advances only one existing, pending, unexpired send job and cannot synchronously send or insert another job.
expected: An operator retry advances only one existing, pending, unexpired send job and cannot synchronously send or insert another job.
result: pass
source: automated
coverage_id: 20-02-D2

### 16. The staged send kind fails closed through dispatch until the fenced handler is available.
expected: The staged send kind fails closed through dispatch until the fenced handler is available.
result: pass
source: automated
coverage_id: 20-02-D3

### 17. Bounded delivery classifications allow only documented transient failures to replay.
expected: Bounded delivery classifications allow only documented transient failures to replay.
result: pass
source: automated
coverage_id: 20-03-D1

### 18. Automatic replay schedule remains anchored to the original reservation and stops before 20 hours.
expected: Automatic replay schedule remains anchored to the original reservation and stops before 20 hours.
result: pass
source: automated
coverage_id: 20-03-D2

### 19. The Resend adapter sends only the persisted snapshot with a stable idempotency key.
expected: The Resend adapter sends only the persisted snapshot with a stable idempotency key.
result: pass
source: automated
coverage_id: 20-03-D3

### 20. A confirmation is composed and converted into exactly one frozen send job, while a replay loads the existing slot without drafting, PDF generation, or mutable reads.
expected: A confirmation is composed and converted into exactly one frozen send job, while a replay loads the existing slot without drafting, PDF generation, or mutable reads.
result: pass
source: automated
coverage_id: 20-04-D1

### 21. Approval commits its durable handoff before waking a worker, creates no second job on a repeated submission, and retains approved while delivery is owed.
expected: Approval commits its durable handoff before waking a worker, creates no second job on a repeated submission, and retains approved while delivery is owed.
result: pass
source: automated
coverage_id: 20-04-D2

### 22. A record-only confirmation uses the frozen snapshot contract without calling the provider.
expected: A record-only confirmation uses the frozen snapshot contract without calling the provider.
result: pass
source: automated
coverage_id: 20-04-D3

### 23. A frozen outbound job validates durable ownership and invokes only the stored snapshot gateway payload.
expected: A frozen outbound job validates durable ownership and invokes only the stored snapshot gateway payload.
result: pass
source: automated
coverage_id: 20-05-D1

### 24. The shared drain settles SEND_OUTBOUND through the exact claimed lease rather than generic pipeline settlement.
expected: The shared drain settles SEND_OUTBOUND through the exact claimed lease rather than generic pipeline settlement.
result: pass
source: automated
coverage_id: 20-05-D2

### 25. Dispatch equality, dynamic handler lookup, and the fake facade all cover SEND_OUTBOUND.
expected: Dispatch equality, dynamic handler lookup, and the fake facade all cover SEND_OUTBOUND.
result: pass
source: automated
coverage_id: 20-05-D3

### 26. Delivery-review evidence routes return only an owned frozen email and attachment, without mutable payroll reads.
expected: Delivery-review evidence routes return only an owned frozen email and attachment, without mutable payroll reads.
result: pass
source: automated
coverage_id: 20-06-D1

### 27. Retry-now advances only the existing pending job; mark delivered cannot reach the provider; stale submissions are safe no-ops.
expected: Retry-now advances only the existing pending job; mark delivered cannot reach the provider; stale submissions are safe no-ops.
result: pass
source: automated
coverage_id: 20-06-D2

### 28. Typed authorization creates one distinct confirmation slot with byte-identical frozen content and one durable job.
expected: Typed authorization creates one distinct confirmation slot with byte-identical frozen content and one durable job.
result: pass
source: automated
coverage_id: 20-06-D3

### 29. The review card exposes safe facts, frozen evidence links, and exactly the two operator outcomes without client-side recovery.
expected: The review card exposes safe facts, frozen evidence links, and exactly the two operator outcomes without client-side recovery.
result: pass
source: automated
coverage_id: 20-06-D4

### 30. A first-time confirmation uses employee-scoped, complete reconciled YTD totals for every displayed category.
expected: A first-time confirmation uses employee-scoped, complete reconciled YTD totals for every displayed category.
result: pass
source: automated
coverage_id: 20-07-D1

### 31. Existing confirmation snapshots replay without YTD derivation or a regenerated PDF attachment.
expected: Existing confirmation snapshots replay without YTD derivation or a regenerated PDF attachment.
result: pass
source: automated
coverage_id: 20-07-D2

### 32. New paystubs show aligned Current and YTD values for all supported earnings, deduction, and net-pay categories.
expected: New paystubs show aligned Current and YTD values for all supported earnings, deduction, and net-pay categories.
result: pass
source: automated
coverage_id: 20-07-D3

### 33. Offline eval chart uses dashboard-aligned palette, typography, restrained chrome, and stable aggregate labels.
expected: Offline eval chart uses dashboard-aligned palette, typography, restrained chrome, and stable aggregate labels.
result: pass
source: automated
coverage_id: 20-08-D1

### 34. Chart polish leaves evaluation scores and regression semantics unchanged.
expected: Chart polish leaves evaluation scores and regression semantics unchanged.
result: pass
source: automated
coverage_id: 20-08-D2

### 35. The eval chart remains isolated from provider delivery, queue, snapshot, and database mutation code.
expected: The eval chart remains isolated from provider delivery, queue, snapshot, and database mutation code.
result: pass
source: automated
coverage_id: 20-08-D3

### 36. Confirmation delivery success, replay, terminal review, and lost-lease paths are fenced and append only bounded delivery facts.
expected: Confirmation delivery success, replay, terminal review, and lost-lease paths are fenced and append only bounded delivery facts.
result: pass
source: automated
coverage_id: 20-09-D1

### 37. Standard clarification freezes one RFC-threaded envelope, queues one immutable send job, and pauses awaiting a reply.
expected: Standard clarification freezes one RFC-threaded envelope, queues one immutable send job, and pauses awaiting a reply.
result: pass
source: automated
coverage_id: 20-10-D1

### 38. Repeated standard and field-regression clarification entry reuses the original snapshot and job before drafting.
expected: Repeated standard and field-regression clarification entry reuses the original snapshot and job before drafting.
result: pass
source: automated
coverage_id: 20-10-D2

### 39. Field-regression delivery cannot cross into alias confirmation.
expected: Field-regression delivery cannot cross into alias confirmation.
result: pass
source: automated
coverage_id: 20-10-D3

### 40. Clarification delivery success completes only the frozen send slot and preserves the awaiting-reply workflow.
expected: Clarification delivery success completes only the frozen send slot and preserves the awaiting-reply workflow.
result: pass
source: automated
coverage_id: 20-11-D1

### 41. Clarification retry stays on the original leased job, while terminal delivery uses clarification-safe escalation and a fenced loser changes nothing.
expected: Clarification retry stays on the original leased job, while terminal delivery uses clarification-safe escalation and a fenced loser changes nothing.
result: pass
source: automated
coverage_id: 20-11-D2

### 42. Clarification transport settlement cannot reach the confirmed-alias write seam.
expected: Clarification transport settlement cannot reach the confirmed-alias write seam.
result: pass
source: automated
coverage_id: 20-11-D3

### 43. Outbound settlement fences persisted email identity and rejects unsafe retryable delivery reasons.
expected: Outbound settlement fences persisted email identity and rejects unsafe retryable delivery reasons.
result: pass
source: automated
coverage_id: 20-13-D1

### 44. Operator retry-now and clarification delivery-review retry share job-first locking and reuse the existing durable row.
expected: Operator retry-now and clarification delivery-review retry share job-first locking and reuse the existing durable row.
result: pass
source: automated
coverage_id: 20-13-D3

### 45. Delivery-review facts are body-free while the authorized frozen snapshot reader retains the exact body and attachments.
expected: Delivery-review facts are body-free while the authorized frozen snapshot reader retains the exact body and attachments.
result: pass
source: automated
coverage_id: 20-14-D2

### 46. The legacy arbitrary email-state writer cannot mutate inbound or invalid state, and the retained sent helper is outbound reserved-only.
expected: The legacy arbitrary email-state writer cannot mutate inbound or invalid state, and the retained sent helper is outbound reserved-only.
result: pass
source: automated
coverage_id: 20-14-D3

### 47. Confirmation and clarification delivery ambiguity load purpose-matched frozen evidence and expose isolated actions.
expected: Confirmation and clarification delivery ambiguity load purpose-matched frozen evidence and expose isolated actions.
result: pass
source: automated
coverage_id: 20-16-D1

### 48. Confirmation delivery consumes the purpose-aware current-epoch proof seam without broad lookup or frozen-content rebuilding.
expected: Confirmation delivery consumes the purpose-aware current-epoch proof seam without broad lookup or frozen-content rebuilding.
result: pass
source: automated
coverage_id: 20-17-D2

### 49. The in-memory repository preserves the current reserved Message-ID when stale settlement or final reaping is rejected.
expected: The in-memory repository preserves the current reserved Message-ID when stale settlement or final reaping is rejected.
result: pass
source: automated
coverage_id: 20-18-D3

### 50. Drain distinguishes invalid context from a reclaimed lease and discards held tokens only after the durable result.
expected: Drain distinguishes invalid context from a reclaimed lease and discards held tokens only after the durable result.
result: pass
source: automated
coverage_id: 20-19-D2

### 51. Clarification delivery reviews cannot use confirmation retry, reconciliation, or authorization POST endpoints.
expected: Clarification delivery reviews cannot use confirmation retry, reconciliation, or authorization POST endpoints.
result: pass
source: automated
coverage_id: 20-20-D1

### 52. Generic retry requires a confirmation reservation and DeliveryReview-owned needs_operator run under repository locks.
expected: Generic retry requires a confirmation reservation and DeliveryReview-owned needs_operator run under repository locks.
result: pass
source: automated
coverage_id: 20-20-D2

### 53. Schema installs an identifier-only handoff record with one unreleased authorization per run and a bounded release vocabulary.
expected: Schema installs an identifier-only handoff record with one unreleased authorization per run and a bounded release vocabulary.
result: pass
source: automated
coverage_id: 20-21-D1

### 54. Provider authority locks the exact leased job, immutable snapshot, current run generation, and handoff in order; a record-only run receives no provider authority.
expected: Provider authority locks the exact leased job, immutable snapshot, current run generation, and handoff in order; a record-only run receives no provider authority.
result: pass
source: automated
coverage_id: 20-21-D2

### 55. Exact-owner release and an active-handoff query fence stale owners and block a reply-epoch advance before mutation.
expected: Exact-owner release and an active-handoff query fence stale owners and block a reply-epoch advance before mutation.
result: pass
source: automated
coverage_id: 20-21-D3

### 56. SEND_OUTBOUND forwards only an authorized frozen snapshot and treats record-only or active outcomes as bounded no-provider results.
expected: SEND_OUTBOUND forwards only an authorized frozen snapshot and treats record-only or active outcomes as bounded no-provider results.
result: pass
source: automated
coverage_id: 20-22-D1

### 57. Resend I/O is denied when the immutable authorization cannot cover its fixed timeout and safety margin after payload preparation.
expected: Resend I/O is denied when the immutable authorization cannot cover its fixed timeout and safety margin after payload preparation.
result: pass
source: automated
coverage_id: 20-22-D2

### 58. Every synchronous Resend request shares one 10-second RequestsClient and preserves the stored Message-ID idempotency key.
expected: Every synchronous Resend request shares one 10-second RequestsClient and preserves the stored Message-ID idempotency key.
result: pass
source: automated
coverage_id: 20-22-D3

### 59. Both proofs are selected by the existing marker-based queue durability CI command.
expected: Both proofs are selected by the existing marker-based queue durability CI command.
result: pass
source: automated
coverage_id: 20-23-D3

### 60. Delivery settlement and final-lease reaping release or finalize only the exact current provider handoff before job state changes.
expected: Delivery settlement and final-lease reaping release or finalize only the exact current provider handoff before job state changes.
result: pass
source: automated
coverage_id: 20-24-D1

### 61. An expired provider authorization becomes purpose-aware delivery review with a bounded deadline category and no retry job.
expected: An expired provider authorization becomes purpose-aware delivery review with a bounded deadline category and no retry job.
result: pass
source: automated
coverage_id: 20-24-D2

### 62. The in-memory repository preserves crash adoption, predecessor-token rejection, original frozen snapshot identity, and record-only completion semantics.
expected: The in-memory repository preserves crash adoption, predecessor-token rejection, original frozen snapshot identity, and record-only completion semantics.
result: pass
source: automated
coverage_id: 20-24-D3

### 63. Generic retrigger rolls back its status claim and creates no epoch, job, or wake while an active provider handoff exists; a released handoff permits the normal route.
expected: Generic retrigger rolls back its status claim and creates no epoch, job, or wake while an active provider handoff exists; a released handoff permits the normal route.
result: pass
source: automated
coverage_id: 20-25-D1

### 64. D-09 mark-delivered resolves only its matching active confirmation handoff without another send, job, or wake.
expected: D-09 mark-delivered resolves only its matching active confirmation handoff without another send, job, or wake.
result: pass
source: automated
coverage_id: 20-25-D2

### 65. Only the exact typed D-11 acknowledgement releases an ambiguous handoff and creates a distinct slot with byte-identical frozen content.
expected: Only the exact typed D-11 acknowledgement releases an ambiguous handoff and creates a distinct slot with byte-identical frozen content.
result: pass
source: automated
coverage_id: 20-25-D3

### 66. The handler preserves the closed replay-window result as a terminal authorization-expired delivery outcome and makes no gateway or Resend call.
expected: The handler preserves the closed replay-window result as a terminal authorization-expired delivery outcome and makes no gateway or Resend call.
result: pass
source: automated
coverage_id: 20-26-D1

### 67. An expired confirmation or clarification reservation with no provider handoff appends one authorization_expired review fact, preserves its snapshot, and completes its exact job.
expected: An expired confirmation or clarification reservation with no provider handoff appends one authorization_expired review fact, preserves its snapshot, and completes its exact job.
result: pass
source: automated
coverage_id: 20-26-D2

### 68. Stale leases, foreign active handoffs, and unrelated terminal results cannot use the no-handoff review branch.
expected: Stale leases, foreign active handoffs, and unrelated terminal results cannot use the no-handoff review branch.
result: pass
source: automated
coverage_id: 20-26-D3

### 69. Fresh installs and the non-reset deployed-schema repair accept the exact bounded authorization_expired attempt category.
expected: Fresh installs and the non-reset deployed-schema repair accept the exact bounded authorization_expired attempt category.
result: pass
source: automated
coverage_id: 20-27-D1

### 70. Pre-provider and gateway-boundary replay expiry write delivery-review evidence without provider I/O or regenerated frozen content.
expected: Pre-provider and gateway-boundary replay expiry write delivery-review evidence without provider I/O or regenerated frozen content.
result: pass
source: automated
coverage_id: 20-27-D2

### 71. The protected and intentionally unsafe control schedules both run against real PostgreSQL, proving the provider handoff fence blocks the dangerous epoch bump and exposes its release.
expected: The protected and intentionally unsafe control schedules both run against real PostgreSQL, proving the provider handoff fence blocks the dangerous epoch bump and exposes its release.
result: pass
source: automated
coverage_id: 20-27-D3

## Summary

total: 71
passed: 61
issues: 0
pending: 0
skipped: 10
blocked: 0

## Gaps

[none yet]
