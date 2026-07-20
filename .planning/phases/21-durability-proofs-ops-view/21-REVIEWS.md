---
phase: 21
reviewers: [codex]
reviewed_at: 2026-07-20T02:42:51Z
plans_reviewed: [21-01-PLAN.md,21-02-PLAN.md 21-03-PLAN.md,21-04-PLAN.md 21-05-PLAN.md,21-06-PLAN.md 21-07-PLAN.md,21-08-PLAN.md 21-09-PLAN.md,21-10-PLAN.md 21-11-PLAN.md]
verdict: DO NOT EXECUTE UNCHANGED — 9 HIGH findings
---

# Cross-AI Plan Review — Phase 21

Reviewer: **Codex** (codex-cli 0.144.0, source-grounded — run inside the git working tree with file access).

## Codex Review

## Overall assessment

**Risk: HIGH until the proof/evidence issues below are corrected.** The phase is well-scoped and the stale-criterion corrections are sound: CI already has a marker-selected queue-proof step, not just a hard-coded file list ([concurrency-proof.yml:106](.github/workflows/concurrency-proof.yml:106)); and terminal queue settlement legitimately writes `run=error` with `job=done/dead` in one transaction ([job_settlement.py:894](app/db/repo/job_settlement.py:894)). The major weaknesses are in planned falsification assertions, the D-13 anti-join’s false-negative behavior, and proof-inventory coverage of the actual CI selection.

No same-wave plans modify the same file. The dependency ordering is generally coherent.

## 21-01 — Proof inventory substrate

**Summary:** Good separation of pure decision logic from collection, but the collector proves only proof-marker membership, not CI execution membership.

**Strengths**

- Registering a dedicated marker is necessary; only `integration`, `live_llm`, and `queueproof` are currently registered ([pyproject.toml:40](pyproject.toml:40)).
- A pure inventory evaluator with synthetic missing/duplicate/stray cases is the right anti-vacuity shape.

**Concerns**

- **[HIGH]** The proposed checker collects `-m proof`, while CI executes `-m queueproof`. A proof with the correct `proof(id=...)` marker but a missing/misspelled `queueproof` marker passes inventory yet is never run in the real-Postgres CI step. The workflow explicitly selects only `queueproof` ([concurrency-proof.yml:106-110](.github/workflows/concurrency-proof.yml:106)); marker registration does not make one imply the other ([pyproject.toml:42-46](pyproject.toml:42)).
- **[MEDIUM]** Parsing only output lines beginning with `tests/` is brittle if pytest’s collection rendering changes or a proof is parametrized; the script should use pytest’s collection API/plugin output or enforce an intentionally constrained node-id format with a test.

**Suggestions**

- Make the gate collect each ID through `-m "queueproof and proof(id='PROOF-01')"` and assert exactly one node. Also assert bare `proof` and `queueproof` selections have the same four proof node IDs.
- Add a synthetic/live falsification for a missing `queueproof` decorator, not only a typo in `id=`.

**Risk assessment:** **Medium**, becoming low with intersection-selection coverage.

## 21-02 — Queue reads and D-13 alarm predicate

**Summary:** The bounded projection and real-Postgres test plan are strong, but the proposed `updated_at >=` anti-join can hide exactly the swallowed errors the alarm is meant to detect.

**Strengths**

- The queue read seam is appropriate: `count_open_jobs()` and `get_run_queue_label()` already establish read-only repo conventions ([jobs.py:575](app/db/repo/jobs.py:575), [jobs.py:596](app/db/repo/jobs.py:596)).
- The projection discipline is credible: the current jobs API already uses explicit columns rather than `SELECT *` ([jobs.py:48-55](app/db/repo/jobs.py:48)).
- The stale OPS ratio correction is correct. A normal terminal settlement updates the error run and terminal job in one transaction ([job_settlement.py:894-917](app/db/repo/job_settlement.py:894)).

**Concerns**

- **[HIGH]** `NOT EXISTS terminal job with j.updated_at >= run.updated_at` has a false-negative. `record_run_error()` can set a run to error independently ([runs.py:519-588](app/db/repo/runs.py:519)); a previously leased pipeline job that later loses its status CAS returns `OK` ([pipeline.py:138-150](app/queue/handlers/pipeline.py:138)) and is then marked `done` by settlement ([job_settlement.py:852-864](app/db/repo/job_settlement.py:852)). Its later `updated_at` would incorrectly “vouch for” the earlier unaccounted error.
- **[MEDIUM]** The six proposed alarm tests do not cover that late no-op-job scenario, so this false negative would survive.
- **[LOW]** `extract(epoch ...)` may be returned as a `Decimal` by psycopg/Postgres; the planned function promises `float` but does not explicitly require conversion.

**Suggestions**

- Use equality, not `>=`, if the intended proof is “the terminal job and error write were in the same transaction”: PostgreSQL’s transaction `now()` makes those timestamps equal. Add a test for a terminal job completed *after* `record_run_error()` and require the alarm to fire.
- Explicitly classify `settle_background_terminal()`: it creates an error with no job ([job_settlement.py:921-940](app/db/repo/job_settlement.py:921)). It has no production caller today, but the alarm’s future semantics should be documented/tested.
- Convert the scalar age result with `float(...)`.

**Risk assessment:** **High** until the anti-join’s false-negative path is resolved.

## 21-03 — PROOF-01 promotion and mutation

**Summary:** The incumbent is genuinely non-vacuous, but the plan predicts the wrong assertion will fail under its chosen mutation.

**Strengths**

- The incumbent really does prove a lease occurred ([test_queue_durability.py:2885-2900](tests/test_queue_durability.py:2885)) and that reclaim increments attempts ([test_queue_durability.py:2924-2931](tests/test_queue_durability.py:2924)).
- The chosen production target is load-bearing: claim increments attempts at claim time ([jobs.py:428-431](app/db/repo/jobs.py:428)).

**Concerns**

- **[HIGH]** Replacing `attempts = j.attempts + 1` with `attempts = j.attempts` fails first at the existing initial-claim assertion `assert claimed.attempts == 1` ([test_queue_durability.py:2885-2889](tests/test_queue_durability.py:2885)), not the plan’s named final post-reclaim assertion. The required pasted-red/named-assertion evidence would therefore be false as written.

**Suggestions**

- Make the named expected failure the initial claim assertion, or restructure the test so the intended final assertion is genuinely the first failing one. Update the future AST registry and published document to use the observed assertion, not the desired one.

**Risk assessment:** **Medium**; simple plan correction, but important for non-vacuity evidence.

## 21-04 — PROOF-02 promotion and mutation

**Summary:** The positive race proof is solid, but the planned mutation is only a stand-in for the stated RFC-Message-ID premise and its expected first red is wrong.

**Strengths**

- The existing test genuinely races two same-Svix deliveries and asserts one event/job/run/email ([test_webhook_dedup_race.py:232-311](tests/test_webhook_dedup_race.py:232)).
- Production receipt identity is definitely pre-fetch: signed requests use `request.headers["svix-id"]`, fixtures use a raw-body hash ([webhook.py:122-160](app/routes/webhook.py:122)).

**Concerns**

- **[HIGH]** Replacing the event identity with a per-delivery value makes both responses `"accepted"`, so the first failure is the status-set assertion at [test_webhook_dedup_race.py:256-260](tests/test_webhook_dedup_race.py:256), not the planned inbound-event count assertion.
- **[MEDIUM]** A per-delivery identity proves event-key instability, not the success criterion’s specific “keyed on RFC `Message-ID` alone, unavailable until after fetch” failure. The actual webhook deliberately cannot read that message before durable receipt; delayed parsing is in the ingest layer.

**Suggestions**

- Record the expected red as the response-status assertion, unless the test order is intentionally changed.
- Add a narrowly scoped AST/dataflow guard: the signed `external_event_id` assignment must derive from `request.headers["svix-id"]`, and the handler must not invoke provider parsing before `_persist_verified_receipt_sync`. Keep the behavioral per-delivery mutation as a separate stability falsification.

**Risk assessment:** **Medium**.

## 21-05 — PROOF-03 new crash-window proof

**Summary:** The intended seam is correct, but the proposed retry sequence omits the provider-handoff lease that actually blocks replay.

**Strengths**

- The success settlement is outside the dispatch exception handler, so a failure at that point propagates as the intended crash seam ([drain.py:241-255](app/queue/drain.py:241)).
- The handoff fence is real: it blocks a changed lease token while `owner_leased_until` is unexpired ([outbound_handoffs.py:311-361](app/db/repo/outbound_handoffs.py:311)).
- The frozen provider identity is passed through the authorization path, rather than freshly minted there.

**Concerns**

- **[HIGH]** Expiring only `jobs.leased_until`, as the plan instructs, does not expire `outbound_provider_handoffs.owner_leased_until`. The handoff records that value separately at authorization ([outbound_handoffs.py:281-303](app/db/repo/outbound_handoffs.py:281)) and checks it independently ([outbound_handoffs.py:177-202](app/db/repo/outbound_handoffs.py:177)). A reclaimed job therefore remains refused instead of reaching the claimed “genuine replay.”
- **[MEDIUM]** The plan allows either one or two provider calls after discovering runtime behavior. That weakens the predeclared proof contract; the intended behavior must be chosen and explained before writing the assertion.

**Suggestions**

- Split the proof explicitly:
  1. expire only the job lease and prove the active handoff blocks a second provider call;
  2. expire both the job lease and handoff owner lease in controlled test SQL, then prove a replay reaches the provider with the identical idempotency key.
- Define expected provider-call behavior in advance: two calls are acceptable only because the provider idempotency key is identical; “one call” means app-level handoff fencing prevented the replay.

**Risk assessment:** **High** until the separate handoff lease is handled.

## 21-06 — `/ops` transport page

**Summary:** This is appropriately bounded, server-rendered, and read-only; only a minor assembly-count error and test scope clarification are needed.

**Strengths**

- The cold-start fallback mirrors `/runs`, which already catches DB failures and renders an empty list ([runs.py:809-836](app/routes/runs.py:809)).
- The 30-minute cadence is an actual workflow fact, not a remembered constant ([pump.yml:23-26](.github/workflows/pump.yml:23)).
- Existing nav and route assembly are small and suitable for the planned extension ([base.html:14-18](app/templates/base.html:14), [main.py:8-18](app/main.py:8)).

**Concerns**

- **[LOW]** The plan calls the Ops router “sixth,” but `main.py` already includes six routers; it will be the seventh ([main.py:13-18](app/main.py:13)).
- **[MEDIUM]** A test that patches only drain/enqueue does not prove every route dependency is read-only. The stronger contract is to patch all five facade reads and assert no unplanned repo function is touched.

**Suggestions**

- Correct the router count in plan text and summary.
- Assert the exact five repo reads, with all mutation functions set to fail if invoked.

**Risk assessment:** **Low**.

## 21-07 — Queue health endpoint and pump wiring

**Summary:** Correctly preserves recovery-first ordering; the human checkpoint is valuable. The durable workflow pin should be stronger than shape-only testing.

**Strengths**

- The current pump drain is unconditional and precedes health checks ([pump.yml:62-96](.github/workflows/pump.yml:62)); existing health checks already use `always()` ([pump.yml:98-125](.github/workflows/pump.yml:98)).
- A separate health route is justified because the existing health contracts differ: liveness is no-DB, readiness checks DB reachability, schema checks drift ([health.py:17-72](app/routes/health.py:17)).

**Concerns**

- **[MEDIUM]** The proposed route depends on the unsafe D-13 predicate from 21-02, so it can present a misleading green state even though its workflow ordering is correct.
- **[LOW]** The checkpoint expects an alarm-red live run and manually triggered GitHub workflow. That is appropriate, but it needs a written rollback/disposition path for historical baseline rows before production deployment.

**Suggestions**

- Gate this plan on the revised D-13 false-negative test.
- Require the summary to record whether baseline rows were retriggered, terminally settled, or intentionally retained, before enabling the cron alarm.

**Risk assessment:** **Medium**.

## 21-08 — PROOF-04 threaded reclaim/fencing rewrite

**Summary:** Strong intent and good use of separate connections, but the scheduled event ordering does not actually create DB contention.

**Strengths**

- The incumbent tests are indeed sequential today ([test_queue_durability.py:2224-2254](tests/test_queue_durability.py:2224), [test_queue_durability.py:2262-2299](tests/test_queue_durability.py:2262)).
- The underlying fences are correct and distinct: `complete_job` requires the lease token ([jobs.py:469-487](app/db/repo/jobs.py:469)); `fail_job` does too ([jobs.py:491-535](app/db/repo/jobs.py:491)).

**Concerns**

- **[HIGH]** The proposed barrier plus “B claims, then signals; A writes only after the signal” serializes the meaningful DB calls. It proves distinct OS threads and an ordered zombie write, but not that the claim and zombie write genuinely contended. A future serial implementation could satisfy the planned barrier/connection assertions.
- **[MEDIUM]** The existing test file has a static guard that claims direct `worker.start()` calls are only allowed through its wrapper ([test_queue_durability.py:2715-2770](tests/test_queue_durability.py:2715)). The plan should explicitly ensure its new thread variable names/starts do not accidentally violate or evade that guard.

**Suggestions**

- Be precise in the claim: this is a separate-worker, ordered stale-write proof, not a simultaneous write race. If actual DB contention is required, add a deterministic DB synchronization point and assert both connections were active in the overlapping critical section.
- Add a focused test that fails if the second claim is moved back onto the main thread; “distinct connection IDs” alone is weaker than that.

**Risk assessment:** **High** against the literal “genuinely contend” requirement.

## 21-09 — CI completeness wiring

**Summary:** Correctly waits until all markers exist and preserves the intended narrow integration suite, but current tests do not actually byte-pin prior workflow steps.

**Strengths**

- The ordering is right: adding a four-ID gate before the four markers would intentionally break CI.
- The current workflow’s documented gap is exactly the one this plan targets ([concurrency-proof.yml:143-147](.github/workflows/concurrency-proof.yml:143)).

**Concerns**

- **[HIGH]** The plan repeatedly calls existing checks “byte-pinned,” but `TestD14NoWideningGuard` only asserts a command substring and absence of whole-suite `-m integration` ([test_queue_config.py:96-135](tests/test_queue_config.py:96)). It would not catch edits to the existing queueproof step’s `pipefail`, skip guard, environment, or comments.
- **[HIGH]** This plan inherits 21-01’s proof-vs-queueproof blind spot: a correctly inventoried proof can still be excluded from the real-Postgres queueproof step.

**Suggestions**

- Add a structural fingerprint/assertion for both existing workflow steps: name, command, shell, marker, env, and skip/pass guards.
- Make the new gate prove each proof is selected by `queueproof AND proof(id=...)`, not only `proof(id=...)`.

**Risk assessment:** **High** until CI selection equivalence and prior-step integrity are pinned.

## 21-10 — AST mutation-target registry

**Summary:** The anti-rot goal is excellent, but the specified resolver is too weak to establish that a mutation target is an executable AST node.

**Strengths**

- AST parsing is the right direction; the repo already has AST-based guard patterns rather than grep-based checks ([test_fake_repo_pairing.py:55-75](tests/test_fake_repo_pairing.py:55)).
- Excluding docstrings and comments addresses a real hazard because `claim_job()` documents the same SQL fragments it executes ([jobs.py:402-423](app/db/repo/jobs.py:402)).

**Concerns**

- **[HIGH]** The resolver searches only non-docstring string constants. PROOF-02’s actual mutation target is an executable assignment, `external_event_id = request.headers["svix-id"]` ([webhook.py:143](app/routes/webhook.py:143)), not a string constant. The guard cannot resolve it as specified.
- **[HIGH]** “Named assertion exists” is planned as a text search over the proof source. A comment or docstring can satisfy that check, recreating the exact false-positive class D-06 is meant to prevent.

**Suggestions**

- Model targets as AST predicates, not string fragments: e.g. function + node type + normalized AST dump/value path. For PROOF-02, require an `Assign` to `external_event_id` whose value subscripts `request.headers` with `"svix-id"`.
- Find the target test function through AST and require the named text in an `ast.Assert` condition or assertion message, not anywhere in the source file.

**Risk assessment:** **High**.

## 21-11 — Public evidence and documentation guard

**Summary:** Excellent recruiter-facing closeout and residual-risk posture, but it must consume corrected evidence from 21-03/04/05/08 and cannot validate every printed live-DB command indiscriminately.

**Strengths**

- README linking and a machine-checked relative path are appropriate given the primary audience.
- Publishing the operational boundary alongside the claim is aligned with the actual implementation: retries/reclaims are bounded by leases and the pump cadence ([pump.yml:62-93](.github/workflows/pump.yml:62)).

**Concerns**

- **[HIGH]** The document would faithfully publish incorrect named-red claims unless 21-03 and 21-04 are fixed first. Their planned mutation runs fail earlier than the assertions the document is supposed to name.
- **[MEDIUM]** “Every command shown runs as written” is unsafe for commands requiring a real throwaway database unless the plan explicitly supplies isolated credentials and confirms it cannot hit live Supabase.

**Suggestions**

- Make 21-11 verify each evidence block against the actual summary’s named failing assertion and registry entry after the earlier plans are corrected.
- Label live-DB commands with an explicit `DATABASE_URL=<throwaway>` prerequisite; run only hermetic commands automatically.

**Risk assessment:** **Medium**, contingent on earlier evidence corrections.

## Final recommendation

Do not execute unchanged. Address these before implementation:

1. Make proof inventory verify the **same `queueproof` selection CI runs**.
2. Replace or tighten D-13’s `>=` anti-join and add the late-no-op-job false-negative test.
3. Correct PROOF-01 and PROOF-02 expected failing assertions to match the actual first failure.
4. Expire/handle the separate outbound-handoff lease in PROOF-03.
5. Make PROOF-04’s concurrency claim match what it truly proves, or add deterministic overlapping contention.
6. Upgrade 21-10 from string-literal scanning/text presence to executable AST-node and `ast.Assert` verification.

---

## Orchestrator Verification (independent, against live source)

Five of the HIGH findings were spot-checked against the working tree before accepting them.
**All five confirmed.** They are facts about this repo, not reviewer opinion:

| # | Claim | Verified evidence | Verdict |
|---|-------|-------------------|---------|
| 1 | `proof` and `queueproof` are independent markers; CI executes only `queueproof` | `.github/workflows/concurrency-proof.yml:105-110` selects by `queueproof` marker; nothing makes `proof` imply it | **CONFIRMED** |
| 2 | `TestD14NoWideningGuard` does **not** byte-pin | `tests/test_queue_config.py:110-135` asserts a command *substring* + absence of whole-suite `-m integration`. Shell, env, guards, comments are unpinned. The workflow *comment* says "stays byte-identical"; the *test* does not enforce it | **CONFIRMED** |
| 3 | PROOF-01's mutation fails at the initial-claim assertion first | `tests/test_queue_durability.py:2888` `assert claimed.attempts == 1` precedes the post-reclaim assertion the plan names | **CONFIRMED** |
| 4 | `outbound_provider_handoffs.owner_leased_until` is a **separate** lease | `app/db/repo/outbound_handoffs.py:181` (`owner_leased_until < now() AS owner_expired`) and `:345` (reclaim requires it expired). Expiring `jobs.leased_until` does not touch it | **CONFIRMED** |
| 5 | PROOF-02's mutation target is an executable `Assign`, not a string constant | `app/routes/webhook.py:143` — `external_event_id = request.headers["svix-id"]` is an `Assign` whose value is a `Subscript`. A string-constant-only resolver cannot resolve it | **CONFIRMED** |

### Why these matter more than their count

Findings 1, 2 and 5 are all the **same failure class this phase exists to eliminate**: a guard that
looks rigorous but is blind exactly where it matters.

- The completeness gate (D-02) would certify a proof as present while CI never runs it.
- The "byte-pinned" claim is repeated in CONTEXT.md, in the plans, and in the planning summary — an
  unverified belief that propagated through three artifacts unchallenged.
- The AST resolver (D-06) would fail to resolve one of the four mutation targets, and its
  "named assertion exists" check is a text search that a **comment** can satisfy — recreating the
  precise docstring-copy false positive D-06 was written to prevent, one level up.

Finding 4 is a straightforward mechanical defect: PROOF-03's replay never happens as scripted.

Finding on 21-02's anti-join is the one genuine **design tension**, not an oversight: the planner
chose `>=` to suppress false positives from same-transaction settlements; Codex showed the same
clause creates a false negative when `record_run_error()` errors a run and a late CAS-losing
pipeline job is settled `done` afterwards. **For an alarm, a false negative is the worse failure** —
a swallowed error that stays swallowed is exactly the pathology D-13 targets.

## Consensus Summary

Single reviewer, so this is verification rather than consensus.

### Agreed Strengths
- Both stale-criterion corrections (PROOF-05 premise, OPS-01 predicate) independently confirmed sound.
- No same-wave plan pair modifies the same file; dependency ordering coherent.
- `/ops` (21-06) is appropriately bounded, read-only, server-rendered — LOW risk.
- 21-07's recovery-first pump ordering is correct against the live workflow.

### Agreed Concerns (blocking)
1. **Proof inventory must verify the selection CI actually runs** (`queueproof AND proof(id=…)`), not `proof` alone — 21-01, 21-09.
2. **D-13's `>=` anti-join has a false negative**; needs tightening plus a late-no-op-job test — 21-02.
3. **PROOF-01 and PROOF-02 name the wrong expected failing assertion** — 21-03, 21-04, propagating into 21-11.
4. **PROOF-03 does not expire the separate handoff owner lease**, so the replay never occurs — 21-05.
5. **PROOF-04's barrier+ordering serializes the DB calls** — proves ordered stale write, not contention — 21-08.
6. **21-10's resolver is too weak**: string-constant-only targets, and text-search assertion presence — 21-10.

### Divergent Views
None — single reviewer. The 21-08 finding is the most arguable: the planner added the ordering event
deliberately for determinism. That is a real trade-off (determinism vs. literal "genuinely
contend"), and the resolution should either add a deterministic overlapping critical section or
state the narrower claim honestly rather than overclaim.
