---
phase: 17
reviewers: [codex]
review_round: 3
reviewed_at: 2026-07-15T04:55:00Z
plans_reviewed: [17-01-PLAN.md,17-02-PLAN.md,17-03-PLAN.md,17-04-PLAN.md,17-05-PLAN.md]
supersedes: "round 1 (bdc91d9) + round 2 (e88af21); their findings were incorporated in 9614161 and 74bb023 respectively"
---

# Cross-AI Plan Review — Phase 17 (Round 3, confirming)

> Rounds 1–2 (Codex) found 3 HIGH + 6 MEDIUM/LOW across two replans (`9614161`, `74bb023`). This round-3 confirming pass verifies the round-2 fixes and looks for fix-induced/newly-exposed issues. **Verified against live source by the orchestrator** for the one HIGH.

## Codex Review (Round 3)

## 1) Summary

Round-2 fixes are largely implemented correctly in the plans, but the plans are not yet fully sound.

- The route-test, worker-survival, COMPUTED-label, and workflow-static-guard fixes are confirmed.
- The revised timeout accounting is internally coherent and no longer claims fictional headroom.
- However, its load-bearing lease-reclaim guarantee is not universally true: a job interrupted on its final permitted attempt becomes an expired `leased` row that `claim_job()` can never reclaim or dead-letter.
- Several authoritative supporting artifacts still contain the rejected 360-second/headroom model and the obsolete double-failure→FENCED behavior.

Overall: one new HIGH correctness issue and two MEDIUM documentation/verification issues remain.

## 2) Per-fix confirmation

### HIGH — timeout method and lease-reclaim safety: PARTIAL

The accounting correction itself is confirmed:

- 17-03 explicitly calls 420 seconds nominal, includes cold-start, identifies 240 seconds as external-call allowance, puts deterministic/DB overhead on top, and withdraws all headroom claims at [17-03-PLAN.md:48](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-03-PLAN.md:48>).
- 17-04 uses the same `60 + 120 + 240 + overhead` model and explicitly admits it can exceed 420 seconds at [17-04-PLAN.md:54](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-04-PLAN.md:54>).
- The source supports the stated provider terms: structured calls have a 45-second timeout and one application retry at [client.py:47](</Users/pnhek/usf msds/github/payroll_agent/app/llm/client.py:47>), while clarification drafting is capped at 30 seconds.
- The source also confirms 210 seconds is an inter-write staleness gap, not total job runtime, at [runs.py:43](</Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:43>).

For ordinary non-exhausted jobs, the recovery chain is real:

1. The claim commits before work begins at [jobs.py:116](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:116>).
2. Expired leases are eligible for atomic `FOR UPDATE SKIP LOCKED` reclaim at [jobs.py:154](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:154>).
3. Completion and failure writes fence on the new lease token at [jobs.py:182](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:182>) and [jobs.py:204](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:204>).
4. Reclaimed pipeline runs use recovery and forward CAS writes at [pipeline.py:126](</Users/pnhek/usf msds/github/payroll_agent/app/queue/handlers/pipeline.py:126>).
5. The send guard refuses an uncertain duplicate send at [send_guard.py:40](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/send_guard.py:40>).

But the blanket claim that every interrupted job is reclaimed next cadence is false because the claim query first requires:

```sql
c.attempts < c.max_attempts
```

at [jobs.py:157](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:157>). Since attempts increment at claim time at [jobs.py:148](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo/jobs.py:148>), a worker dying during the final allowed attempt leaves:

```text
state='leased'
attempts == max_attempts
leased_until < now()
```

That row fails the claim predicate forever. `fail_job()` could turn it dead, but the dead worker never calls it; no other reaper exists. This makes the round-2 safety resolution incomplete.

There is also an accuracy problem in attributing interruption to curl: a client-side curl timeout does not normally cancel the sync server-side route. The current research correctly says server work continues after disconnect at [17-RESEARCH.md:326](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-RESEARCH.md:326>), while 17-04 says a curl-overrun RED means “auto-retried” at [17-04-PLAN.md:72](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-04-PLAN.md:72>). It may instead finish successfully server-side.

### MEDIUM — real double-failure route chain: CONFIRMED

Both required tests are now unambiguously specified.

The real-chain test:

- Returns a real leased job from `repo.claim_job`.
- Makes `dispatch.handle` raise.
- Makes `repo.fail_job` raise.
- Calls the production HTTP endpoint through `TestClient`.
- Exercises the real `drain_once()` double-failure re-raise.
- Asserts HTTP 503 and `held_tokens() == [token]` after the HTTP call.

This is specified at [17-04-PLAN.md:220](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-04-PLAN.md:220>).

The separate narrow exception→503 mapping test remains specified at [17-04-PLAN.md:229](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-04-PLAN.md:229>). Acceptance requires both at [17-04-PLAN.md:240](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-04-PLAN.md:240>).

This correctly exercises the production re-raise path, not merely a route stub.

### LOW — worker resumes polling after exception: CONFIRMED

The plan requires:

- First `drain_once()` call raises.
- A second invocation signals a separate event.
- The test waits for that second event or `calls >= 2`.
- Only afterward does it assert thread liveness.

See [17-01-PLAN.md:194](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-01-PLAN.md:194>) and its acceptance gate at [17-01-PLAN.md:215](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-01-PLAN.md:215>). This directly proves the production catch-and-continue behavior at [worker.py:203](</Users/pnhek/usf msds/github/payroll_agent/app/queue/worker.py:203>).

### LOW — COMPUTED status wording: CONFIRMED

17-05 consistently describes COMPUTED as observable post-handler state that is recoverable/in-flight, not terminal, at [17-05-PLAN.md:13](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-05-PLAN.md:13>) and [17-05-PLAN.md:110](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-05-PLAN.md:110>).

That matches source: COMPUTED is included among fresh in-flight states at [runs.py:66](</Users/pnhek/usf msds/github/payroll_agent/app/routes/runs.py:66>).

### LOW — comment-insensitive workflow guard: CONFIRMED

The guard now explicitly strips every comment-only line before schedule and endpoint checks at [17-03-PLAN.md:219](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-03-PLAN.md:219>).

If YAML is used, it requires `d.get(True, d.get("on"))`, addressing PyYAML’s YAML-1.1 coercion at [17-03-PLAN.md:221](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-03-PLAN.md:221>). This is complete.

## 3) New/missed concerns

### HIGH — final-attempt crash strands the job permanently

As described above, `attempts` increments when the lease is acquired, while every candidate—including expired leased candidates—is filtered through `attempts < max_attempts`.

Consequences:

- The fifth claim with `max_attempts=5` succeeds and writes `attempts=5`.
- If that worker dies before `complete_job()` or `fail_job()`, the lease eventually expires.
- Future pump calls cannot claim it because `5 < 5` is false.
- It remains `leased` indefinitely rather than being re-run or dead-lettered.
- The planned `count_open_jobs()` will continue counting it because it counts all leased rows, creating permanent nonzero queue depth without progress.

This directly invalidates the categorical safety language in [17-03-PLAN.md:52](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-03-PLAN.md:52>) and [17-04-PLAN.md:56](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-04-PLAN.md:56>).

This can be fixed without adding a sixth `DrainOutcome`; an exhausted expired lease naturally maps to the locked `DEAD` outcome.

### MEDIUM — authoritative phase references still contradict the round-2 resolution

The current plans are coherent with each other, but their required reading remains stale:

- Research still calls 210 seconds total single-job runtime and recommends 360 seconds with headroom at [17-RESEARCH.md:323](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-RESEARCH.md:323>).
- Its example workflow still uses 360 seconds.
- Its assumptions still discuss a ~330-second worst case at [17-RESEARCH.md:455](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-RESEARCH.md:455>).
- Most seriously, its “resolved” double-failure decision still says to map the failure to FENCED and claims 17-01 adopted that behavior at [17-RESEARCH.md:463](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-RESEARCH.md:463>).
- PATTERNS still instructs 360 seconds at [17-PATTERNS.md:104](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-PATTERNS.md:104>).
- VALIDATION still asks the live smoke to prove a ~330-second ceiling at [17-VALIDATION.md:76](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-VALIDATION.md:76>).

Because executors are explicitly told to read these files, this is more than archival prose drift.

### MEDIUM — the proposed live smoke cannot establish the server-side ceiling

The revised method makes 420 seconds provisional until live smoke, but the validation instruction only says to run “a small backlog” at [17-VALIDATION.md:76](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/17-the-pump/17-VALIDATION.md:76>). A normal small backlog may complete in seconds and proves nothing about a proxy ceiling near 330–420 seconds.

The smoke needs a controlled request whose duration crosses the threshold being validated, while avoiding paid or duplicate-send behavior.

## 4) Suggestions

1. Add an explicit exhausted-expired-lease transition:

   - Detect `state='leased' AND leased_until < now() AND attempts >= max_attempts`.
   - Atomically move it to `dead`, clearing its lease fields.
   - Surface the existing `DrainOutcome.DEAD`; do not add a sixth value.
   - Add a live test with `max_attempts=1`: claim, simulate worker death by expiring the lease, pump again, and assert the row becomes `dead`, not permanently `leased`.

2. Narrow the timeout wording:

   - Curl timeout: request goes RED while sync server work may continue.
   - Actual server/process interruption: lease recovery applies.
   - Avoid saying every 420-second RED means “auto-retried.”

3. Update 17-RESEARCH, 17-PATTERNS, and 17-VALIDATION to the accepted 420-second nominal model and double-failure re-raise behavior.

4. Make the live smoke deliberately long-running enough to test the suspected proxy boundary; a routine backlog is insufficient.

## 5) Overall risk

**HIGH until the exhausted-final-lease case is fixed.**

Apart from that queue-liveness defect and the stale supporting artifacts, the round-2 edits are careful and complete. The route-level double-failure coverage, second-poll worker proof, COMPUTED wording, and comment-insensitive workflow guard are now sound.

---

## Consensus Summary (Round 3)

Single source-grounded reviewer (Codex). It **CONFIRMED** 4 of the 5 round-2 fixes (route double-failure chain test, worker second-poll handshake, COMPUTED relabel, comment-insensitive workflow guard) and confirmed the timeout *accounting* is now internally honest (no fictional headroom). But the round-2 **lease-reclaim safety claim is not universally true**, and the plans' required-reading artifacts still carry the old model.

### Still-open / actionable

1. **HIGH — final-attempt crash strands a job permanently [ORCHESTRATOR-VERIFIED against `app/db/repo/jobs.py:145-168`].**
   `attempts` increments at claim (`jobs.py:148`), and the claim candidate filter requires `c.attempts < c.max_attempts` (`jobs.py:157`). A job whose worker/pump dies on its *final* allowed attempt becomes `state='leased', attempts=max_attempts, leased_until<now()` — which the claim predicate can never re-select and no code dead-letters (the dead worker never calls `fail_job`; no reaper exists). It stays `leased` forever and `count_open_jobs()` counts it forever (permanent nonzero queue depth, no progress). **This directly falsifies the round-2 categorical safety claim in `17-03-PLAN.md:52` / `17-04-PLAN.md:56`.**
   - *Mandatory:* correct the false categorical claim (the "every interrupted job is reclaimed next cadence" language is wrong for the exhausted-attempt case).
   - *Fix option (Codex's, maps to the locked DEAD — no 6th DrainOutcome):* detect `state='leased' AND leased_until<now() AND attempts>=max_attempts` and atomically move it to `dead`; surface `DrainOutcome.DEAD`; add a live `max_attempts=1` test (claim → expire lease → pump → assert `dead`, not permanently `leased`).
   - *Scope note:* terminal-failure handling is fenced to Phase 18 (FAIL-01/02/03) in CONTEXT.md. The planner must decide: add the minimal reaper now (closes a real durability hole in the durability phase) OR defer to Phase 18 with a PROMINENT documented residual — but the false claim must be corrected either way.

2. **HIGH-adjacent accuracy — curl timeout ≠ server cancellation [17-04].** A client-side `curl --max-time` overrun does NOT normally cancel the sync server-side route (RESEARCH.md:326 says server work continues after disconnect). So `17-04-PLAN.md:72`'s "a curl-overrun RED means auto-retried" is imprecise: the job likely *finishes successfully server-side* (RED-but-succeeded), not RED-but-reclaimed. Narrow the wording: curl RED = request-level signal; actual server/process interruption is what triggers lease recovery.

3. **MEDIUM — stale required-reading artifacts contradict the accepted model.** Executors are told to read these:
   - `17-RESEARCH.md:323` still calls 210s total single-job runtime + recommends 360s/headroom; `:455` still discusses ~330s worst case; **`:463` still says "RESOLVED: map the double-failure to FENCED, adopted in 17-01" — doubly wrong (round 1 overturned it to re-raise).**
   - `17-PATTERNS.md:104` still instructs 360s.
   - `17-VALIDATION.md:76` still asks the live smoke to prove a ~330s ceiling.
   Reconcile all to the accepted 420s-nominal + lease-reclaim + re-raise model.

4. **MEDIUM — live smoke can't establish the proxy ceiling [17-VALIDATION.md:76].** "A small backlog" may finish in seconds and prove nothing about a 330–420s server-side request ceiling. The smoke needs a deliberately long-running controlled request that crosses the threshold, without paid/duplicate-send behavior.

### Confirmed complete (no further action)
Timeout accounting honesty (17-03/17-04 coherent, headroom withdrawn); the real fake-repo double-failure chain test + narrow mapping test (17-04); the worker second-poll handshake (17-01); COMPUTED relabel (17-05); the comment-insensitive criterion-#4 guard (17-03); and everything CONFIRMED in rounds 1–2 (re-raise production design, Fix #3 stub, the MEDIUM bundle).

### My read (orchestrator triage)
Finding #1 is the real prize of the whole review loop — a genuine, verified durability bug (pre-existing in the Phase-16 substrate) that the round-2 safety *claim* dragged into the light. It needs the false claim corrected NOW; whether the reaper lands in Phase 17 or Phase 18 is a scope call the planner should make against CONTEXT.md's fence (my lean: it maps cleanly to the locked DEAD outcome and closes a hole in the *durability* phase, so a minimal in-scope reaper is attractive — but a prominently-documented deferral is defensible). #2–#4 are wording/artifact/verification hygiene and cheap. This is the last planned round; after incorporation the plans should be execution-ready.

### Divergent Views
None — single reviewer.
