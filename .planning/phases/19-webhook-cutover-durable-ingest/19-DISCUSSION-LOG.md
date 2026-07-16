# Phase 19: Webhook Cutover & Durable Ingest - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 19-Webhook Cutover & Durable Ingest
**Areas discussed:** Webhook response, Demo navigation, Competing operator resolutions, Queued feedback

---

## Webhook Response

### New event versus redelivery

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit status | `accepted` for a new event and `duplicate` for the same Svix event again; both return 200 with the durable event ID | ✓ |
| Uniform acceptance | Always return `accepted` with the event ID | |
| Bare success | Empty success response; keep dedup internal | |

**User's choice:** Explicit status.
**Notes:** A run ID cannot be returned because the worker has not created a run yet.

### Correlation identifier

| Option | Description | Selected |
|--------|-------------|----------|
| Event ID only | Return the durable event ID; keep queue internals private | ✓ |
| Event and job IDs | Expose both durable identifiers | |
| Job ID only | Use the queue job as the response correlation key | |

**User's choice:** Event ID only.
**Notes:** The webhook contract must not couple callers to `jobs.id`.

### Durability transaction failure

| Option | Description | Selected |
|--------|-------------|----------|
| 503 Service Unavailable | Bounded retryable response with no database detail | ✓ |
| Generic 500 | Non-success but less precise | |
| Planner discretion | Preserve non-2xx semantics but defer the exact code | |

**User's choice:** `503 Service Unavailable`.
**Notes:** A 200 is forbidden unless event and job have committed.

### Pre-acceptance validation

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal transport envelope | Verify signature, parse JSON, and require the Resend fetch identifier | ✓ |
| Any signed JSON object | Persist and let the worker reject malformed content | |
| Signature-only raw bytes | Persist without JSON validation | |

**User's choice:** Validate the minimal transport envelope.
**Notes:** Body fetch, sender routing, and payroll processing remain entirely after acceptance.

---

## Demo Navigation

### Destination after enqueue

| Option | Description | Selected |
|--------|-------------|----------|
| Run detail for both | Composer and fixture trigger open the new run detail | ✓ |
| Preserve current split | Composer opens detail; fixture returns to list | |
| Runs list for both | Both return to the operator queue | |

**User's choice:** Run detail for both.
**Notes:** Run detail already supports live status polling and settled-state reload.

### Polling duration

| Option | Description | Selected |
|--------|-------------|----------|
| Two minutes | Poll every two seconds for at most 120 seconds | ✓ |
| Current 60 seconds | Preserve the existing cap | |
| Until settlement | Poll indefinitely | |

**User's choice:** Two minutes.
**Notes:** The longer bound accommodates queue delay plus bounded model calls.

### Polling timeout

| Option | Description | Selected |
|--------|-------------|----------|
| Stay on detail | Stop polling; leave manual refresh; never auto-retrigger | ✓ |
| Return to runs list | Move the operator back to the overview | |
| Continue indefinitely | Warn but keep polling | |

**User's choice:** Stay on run detail.
**Notes:** A polling timeout does not mean the durable job is lost.

### Demo enqueue failure

| Option | Description | Selected |
|--------|-------------|----------|
| Visible bounded redirect | Return to the demo/runs surface with a simple retry message | ✓ |
| Plain 503 page | Interrupt navigation with an HTTP error page | |
| Silent redirect | Preserve current behavior with no feedback | |

**User's choice:** Visible bounded redirect.
**Notes:** No internal diagnostics appear in the UI.

---

## Competing Operator Resolutions

### Winning authority

| Option | Description | Selected |
|--------|-------------|----------|
| First committed wins | Earliest valid immutable generation controls payroll | ✓ |
| Latest committed wins | Newest submission supersedes earlier authority | |
| First worker wins | Queue scheduling decides the outcome | |

**User's choice:** First committed generation wins.
**Notes:** Money-moving authority must be deterministic and independent of worker timing.

### Losing generation

| Option | Description | Selected |
|--------|-------------|----------|
| Audited no-op | Preserve mapping and job history; mark superseded; apply nothing | ✓ |
| Reject without persistence | Store no second generation | |
| Mapping without job | Keep the attempted mapping but do not enqueue work | |

**User's choice:** Preserve as an audited no-op.
**Notes:** Immutable history remains available without changing payroll.

### Alias-learning authority

| Option | Description | Selected |
|--------|-------------|----------|
| Winning generation only | Only the payroll-authoritative generation may teach aliases | ✓ |
| Merge all choices | Every generation's remember checkboxes can teach | |
| Latest controls learning | Payroll and alias authority come from different generations | |

**User's choice:** Winning generation only.
**Notes:** Losing generations must not mutate alias candidates or learned aliases.

### Losing-submitter feedback

| Option | Description | Selected |
|--------|-------------|----------|
| Bounded notice | Redirect to detail and state that an earlier resolution won | ✓ |
| Silent redirect | Provide no explicit feedback | |
| 409 Conflict | Interrupt dashboard navigation with an HTTP conflict | |

**User's choice:** Bounded notice.
**Notes:** The notice contains no names, mappings, or other PII.

---

## Queued Feedback

### Relationship to payroll status

| Option | Description | Selected |
|--------|-------------|----------|
| Secondary indicator | Preserve the primary payroll status and derive queue feedback separately | ✓ |
| Existing status only | Add no queue feedback | |
| Replace primary status | Turn `Queued` into the visible payroll status | |

**User's choice:** Secondary indicator.
**Notes:** This preserves invariant J-1.

### Placement

| Option | Description | Selected |
|--------|-------------|----------|
| List and detail | Show consistent queue feedback on both operator surfaces | ✓ |
| Detail only | Hide queue feedback from overview | |
| List only | Hide immediate feedback on the action page | |

**User's choice:** Runs list and run detail.
**Notes:** No separate queue-operations page is added in Phase 19.

### Indicator precision

| Option | Description | Selected |
|--------|-------------|----------|
| State-aware labels | `Queued`, `Retry queued`, and `Running` | ✓ |
| One label | Use `Queued` for every open state | |
| Pending only | Hide the indicator while leased | |

**User's choice:** State-aware labels.
**Notes:** Job IDs, attempt counts, and raw diagnostics stay out of the badge.

### Durability explanation

| Option | Description | Selected |
|--------|-------------|----------|
| Concise sentence | Explain that the action is durable and the page may be left safely | ✓ |
| Badge only | Provide no explanatory copy | |
| Queue internals | Show job IDs, attempts, and scheduling data | |

**User's choice:** Add one concise sentence.
**Notes:** Selected copy: “This action is durably saved; you can safely leave this page.”

---

## the agent's Discretion

- Exact bounded response JSON spelling, notice transport/styling, badge styling, polling-helper organization, SQL decomposition, and repository boundaries within the locked decisions.

## Deferred Ideas

- Frontend progressive enhancement, paystub YTD columns, and eval-chart restyling remain deferred.
- Exactly-once outbound send remains Phase 20.
- Queue operations, dead-letter tooling, alarms, and job-detail diagnostics remain Phase 21.
