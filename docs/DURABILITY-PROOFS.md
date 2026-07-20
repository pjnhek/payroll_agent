# Durability Proofs

This project claims a payroll pipeline that survives crashes, retried webhook deliveries, and
network failures without losing an accepted email or double-charging a client. A claim like that
is cheap to write and easy to get wrong, so every one of the claims below carries the same evidence
shape: the exact code mutation that would break it, the real pytest output from the run where the
mutation was in place, and confirmation that reverting the mutation restores the passing state
byte-for-byte.

The reasoning is simple: a passing test proves the system works today. It does not prove the test
would notice if the system stopped working. A demonstrated red — a mutation applied, the test
failing at a named assertion, then a byte-identical revert back to green — is what closes that gap.
Four proofs establish durability guarantees against a real Postgres database. A fifth section
covers the CI gate that keeps all four from silently going unrun. A closing section states plainly
what none of this guarantees.

Every proof needs a real Postgres database and self-skips without one — **a skip is not a pass.**
Commands that touch a database are shown with an explicit `DATABASE_URL=<throwaway-postgres-url>`
prefix and a warning: **do not run them against a production database.** These proofs execute
`ALLOW_DB_RESET=1`-guarded fixtures that drop and recreate every table.

## PROOF-01 — A worker killed mid-run does not lose the job

**The claim.** If a worker claims a job and dies before finishing it, the job is not lost. A later
worker (or the recovery cron) reclaims the expired lease and the run completes exactly as if the
first worker had never touched it.

**The mutation.** The claim query increments `attempts` in the same `UPDATE` that grants the lease,
so a poison job that repeatedly kills its worker is still bounded by an attempt cap even though the
worker never lives long enough to report failure. Freezing that increment is the load-bearing line
to break, because it is the one piece of state the claim transaction commits before any real work
starts — if it doesn't hold, nothing downstream can be trusted either.

```diff
--- a/app/db/repo/jobs.py
+++ b/app/db/repo/jobs.py
@@ -432,7 +432,7 @@ def claim_job(
                    SET state        = 'leased',
                        lease_token  = gen_random_uuid(),
                        leased_until = now() + (%(lease_seconds)s || ' seconds')::interval,
-                       attempts     = j.attempts + 1,
+                       attempts     = j.attempts,
                        updated_at   = now()
                  WHERE j.id = (
                        SELECT c.id
```

**The pasted red.** With the mutation in place, `tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease` fails at the **initial-claim assertion**, `assert claimed.attempts == 1`:

```
tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease FAILED [100%]

>       assert claimed.attempts == 1
E       AssertionError: assert 0 == 1
E        +  where 0 = Job(id=UUID('05d76540-708e-429a-8caf-3230bdf12572'), ..., attempts=0, ...).attempts

tests/test_queue_durability.py:3048: AssertionError
================= 1 failed, 57 deselected, 1 warning in 0.70s ==================
```

**The revert.** `git diff --stat app/db/repo/jobs.py` produced no output after reverting —
byte-identical. The proof passed again immediately after (`1 passed, 57 deselected`), against
commit `fb3b10a`.

**Re-run it yourself.**

```bash
# WARNING: destructive, ALLOW_DB_RESET-guarded fixtures. Never point at a production database.
DATABASE_URL=<throwaway-postgres-url> ALLOW_DB_RESET=1 \
  uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-01')" -v -rs
```

## PROOF-02 — A redelivered webhook event creates exactly one job, one run, one email

**The claim.** If a webhook provider redelivers the same event (Resend/Svix retries on a timeout,
for example), the system creates exactly one inbound event record, one ingest job, one payroll run,
and one confirmation email — never two, no matter how the redelivery races the original.

A separate, structural property has to hold for this claim to mean anything: the value the dedup
check keys on has to be derivable **before** the provider's message body is fetched, not after.
If it depended on something only available post-fetch (like the RFC `Message-ID` inside the
fetched message), the system would have already done the expensive, side-effecting fetch twice
before it could even tell the deliveries apart. This repository pins that property with a
structural check over the actual code (not prose): every assignment to the dedup key inside the
webhook handler is proven, by walking the parsed source tree, to come from either the request's
signed `svix-id` header or a raw-body digest — never from a call that only runs after a provider
fetch.

**The mutation.** Assuming that pre-fetch derivation as fixed, this mutation targets whether the
key stays **stable** across two independent deliveries of the same event:

```diff
--- a/app/routes/webhook.py
+++ b/app/routes/webhook.py
@@ -140,7 +140,7 @@ async def inbound(request: Request) -> JSONResponse:
                 status_code=400,
                 content={"error": "invalid signature"},
             )
-        external_event_id = request.headers["svix-id"]
+        external_event_id = str(uuid.uuid4())
         fixture_payload = False
```

**The pasted red.** With the mutation in place, `tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` fails at the **response-status-set assertion**:

```
>   assert {result["status"] for result in results} == {"accepted", "duplicate"}
E   AssertionError: assert {'accepted'} == {'accepted', 'duplicate'}
E
E   Extra items in the right set:
E   'duplicate'

tests/test_webhook_dedup_race.py:296: AssertionError
=============================== 1 failed, 5 deselected, 1 warning in 0.58s ===============================
```

**Named failing assertion:** `{result['status'] for result in results} == {'accepted', 'duplicate'}`
— the response-status-set assertion.

With a fresh random identity minted per delivery, both concurrent deliveries independently insert —
the `ON CONFLICT (external_event_id)` arbiter never fires, so both responses come back `"accepted"`
instead of one `"accepted"` and one `"duplicate"`.

**The revert.** `git diff --stat app/routes/webhook.py` produced no output after reverting. The
proof passed again immediately after, against commit `f7a7b2d4`.

**Re-run it yourself.**

```bash
# WARNING: destructive, ALLOW_DB_RESET-guarded fixtures. Never point at a production database.
DATABASE_URL=<throwaway-postgres-url> ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true \
  uv run pytest tests/test_webhook_dedup_race.py -m "proof(id='PROOF-02')" -v -rs
```

The pre-fetch structural check needs no database at all and can be re-run hermetically:

```bash
uv run pytest tests/test_webhook_dedup_race.py::test_prefetch_dedup_key_derivation_guard -v
```

## PROOF-03 — A crash between provider-accept and the local commit sends no second email

**The claim.** Sending a confirmation email is a two-step handoff: the provider (Resend) accepts
the send, and only afterward does the local database commit that the send succeeded. If a worker
crashes in between those two steps — the email is genuinely out, but the local record never says
so — a naive retry would send the client a second, duplicate confirmation. This project's send path
is built around Resend's `Idempotency-Key`, keyed on a `message_id` that is reserved and frozen
**before** the first send attempt and never re-minted on retry, so a replay reuses the exact same
key the provider already saw.

This claim has two genuinely different halves, and collapsing them into one loses the more
interesting one:

**Half A — the retry is refused before it reaches the provider.** If the crash-recovery worker
retries while the original attempt's provider-handoff lease is still active (`outbound_provider_handoffs.owner_leased_until` has not yet expired), the system's own app-level fence refuses
the second attempt outright — `authorize_outbound_provider_handoff` returns
`ProviderHandoffActive(reason="active_handoff_unexpired")`, and the provider is never called a
second time. **Provider call count: exactly 1**, asserted as the literal integer, not "at least 1."

**Half B — a genuine replay reaches the provider, safely.** Once *both* the job's own lease and the
handoff's owner lease have expired, a second worker legitimately reclaims the same handoff row (not
a new one — the same `handoff_id`) and drives a real second call to Resend. **Provider call count:
exactly 2.** What makes this safe is that both calls carry the identical `Idempotency-Key` — the one
`message_id` captured before the first attempt ever ran. Resend recognizes the replay and returns
the original result instead of sending a second email.

**The mutation.** The version of the send path this proof falsifies is the one that existed before
this exact-once mechanism landed: a freshly-minted, per-attempt idempotency key instead of the
frozen `message_id`, inside `send_reserved_outbound_snapshot` in `app/email/gateway.py` — the
function that owns the actual call to the provider.

```diff
--- a/app/email/gateway.py
+++ b/app/email/gateway.py
@@ def send_reserved_outbound_snapshot(
     try:
-        resend.Emails.send(send_params, {"idempotency_key": message_id})
+        resend.Emails.send(send_params, {"idempotency_key": str(uuid.uuid4())})
     except Exception as exc:
```

**The pasted red.** With the mutation in place, `tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email` fails at the **identical-Idempotency-Key assertion**:

```
>       assert provider_calls[0]["idempotency_key"] == captured_message_id
E       AssertionError: assert '72039660-c2b...-82f260abe8b6' == '<proof03-eda...-agent.local>'
E
E         - <proof03-edacf629-b505-4b68-b93e-104a1d206ef3@payroll-agent.local>
E         + 72039660-c2b2-4818-a7e9-82f260abe8b6

tests/test_send_idempotency.py:872: AssertionError
======================= 1 failed, 41 deselected in 0.43s =======================
```

**Named failing assertion:** `provider_calls[0]['idempotency_key'] == captured_message_id` — the
identical-Idempotency-Key assertion.

**The revert.** `git diff --stat app/email/gateway.py app/db/repo/emails.py` produced no output
after reverting. The proof passed again immediately after (`1 passed, 41 deselected`), against
commit `9796bdc`.

**Re-run it yourself.**

```bash
# WARNING: destructive, ALLOW_DB_RESET-guarded fixtures. Never point at a production database.
DATABASE_URL=<throwaway-postgres-url> ALLOW_DB_RESET=1 \
  uv run pytest tests/test_send_idempotency.py -m "proof(id='PROOF-03')" -v -rs
```

## PROOF-04 — An expired lease is reclaimed, and the zombie worker's late writes are fenced

**The claim.** If a worker's lease expires (it stalled, crashed, or got orphaned by a redeploy) a
second worker can reclaim the same job. If the first worker — now a "zombie" — later wakes up and
tries to write a result anyway, using its now-stale lease token, that write must be rejected
(fenced), not silently accepted alongside or over the second worker's result.

This claim needs **two real operating-system threads racing on two separate database connections**
to mean anything, and this repository has been burned by a version of this proof that looked
genuine but wasn't: an earlier concurrency proof fired threads at an `async def` HTTP route behind
a single shared test client, which serialized every "concurrent" request through one connection —
the race never actually happened, and the proof passed even with the guarding clause deleted. This
project publishes two separate tests to avoid repeating that:

**The ordered fencing proof** (carries the `PROOF-01`-style stable id) uses a `threading.Barrier` to
release two real threads together, then a `threading.Event` to force worker B's reclaim to complete
*before* zombie worker A's late writes run. This ordering makes the "both writes are fenced"
assertions reliably reachable — worker A's late `complete_job` returns `False`, and its late
`fail_job` returns `None`, both checked as independently named assertions. **What this test does
not establish:** the barrier-plus-event structure proves two live workers existed, not that their
writes ever overlapped in time. That is a separate, narrower guarantee than the phrase "genuine
concurrency proof" implies, and this document says so rather than implying more than the ordered
test shows.

**The genuine-contention companion proof** removes the `Event` and lets the two threads' single
database call each race for real after the barrier releases them. Each thread brackets its call
with `time.monotonic_ns()` readings, and the test asserts the two `[start, end]` intervals
**intersect** — proof of actual temporal overlap, not an inference from thread count. It then
asserts the order-independent invariant holds across both legitimate outcomes: either the reclaim
wins (the zombie's stale write is fenced) or the zombie's write lands first (the reclaim finds
nothing eligible) — and that the forbidden third outcome, both settlements taking effect, is
impossible in either branch. Run ten consecutive times, both outcomes were observed in practice (3
reclaim-wins, 7 write-lands-first), not asserted from one lucky run.

**The mutation.** The reclaim clause itself — the disjunct that lets the claim query pick up a
`leased` row whose lease has already expired, not just a `pending` one:

```diff
--- a/app/db/repo/jobs.py
+++ b/app/db/repo/jobs.py
@@ -440,7 +440,6 @@ def claim_job(
                         WHERE c.attempts < c.max_attempts
                           AND (
                                 (c.state = 'pending' AND c.available_at <= now())
-                             OR (c.state = 'leased'  AND c.leased_until <  now())
                               )
                         ORDER BY c.priority, c.available_at
                         FOR UPDATE SKIP LOCKED
```

**The pasted red.** With the mutation in place, `tests/test_queue_durability.py::test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes` fails at the **reclaim assertion**:

```
    reclaimed = results["reclaimed"]
>       assert reclaimed is not None, "worker B must have reclaimed the expired lease"
E       AssertionError: worker B must have reclaimed the expired lease
E       assert None is not None

tests/test_queue_durability.py:2499: AssertionError
======================= 1 failed, 57 deselected, 1 warning in 0.42s =======================
```

This is not a barrier timeout, not a thread error, and not a skip — both threads reached the
barrier and neither raised; worker B's reclaim call itself returned cleanly with nothing to claim,
because the mutated `WHERE` clause no longer matches any expired `leased` row.

**The revert.** `git diff --stat app/db/repo/jobs.py` produced no output after reverting. The
proof passed again immediately after, against commit `895ad7d`.

**Re-run it yourself.**

```bash
# WARNING: destructive, ALLOW_DB_RESET-guarded fixtures. Never point at a production database.
DATABASE_URL=<throwaway-postgres-url> ALLOW_DB_RESET=1 \
  uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-04')" -v -rs
```

## PROOF-05 — The completeness gate: a durability proof cannot silently stop running

This one is not a durability claim about the payroll pipeline. It is a claim about the other four
proofs' own execution — and a guard is a claim too, deserving the same evidence.

**The claim.** Each of PROOF-01 through PROOF-04 is a single pytest node, selected in CI by the
intersection of two independent markers: a stable `proof(id=...)` identity, and a `queueproof`
marker that puts it in the one CI job with a real database. Watching that job's console output —
"N passed, 0 skipped" — cannot catch a specific failure shape: a test whose id was typo'd, or one
that carries its proof identity but is simply missing the `queueproof` marker CI actually selects
on. In either case, the job's log still reads "N passed" — for the *other* tests — while the
affected proof silently never ran at all. That gap lives at the *selection* layer, before pytest
ever executes anything, so no amount of watching exit codes or pass counts at the *execution* layer
can see it.

A small pure function checks this at the selection layer directly: for each of the four expected
proof ids, it confirms exactly one test is selected by the CI-executed intersection
(`queueproof and proof(id='PROOF-0N')`), and separately flags a proof-tagged test whose id doesn't
match any of the four (a typo), and a proof-tagged test that is well-formed but missing the
`queueproof` marker entirely. It runs as the third step in the same CI job that executes the
proofs, immediately after them, with no database access of its own.

**The falsification — a typo'd id.** Changing `PROOF-01` to `PROOF-O1` (a capital letter O for
digit zero) on the sole test carrying that id:

```
$ uv run python -m scripts.check_proof_inventory
PROOF id 'PROOF-01' matched no test under the CI-executed selection "queueproof and proof(id='PROOF-01')" — expected exactly one
node 'tests/test_queue_durability.py::test_retrigger_survives_worker_crash_mid_lease' carries @pytest.mark.proof with an id that matches none of the expected ids ('PROOF-01', 'PROOF-02', 'PROOF-03', 'PROOF-04') — check for a typo'd id
exit: 1
```

Reverted (`git checkout --`), `git diff --stat` empty, checker back to exit 0.

**The falsification — a missing `queueproof` marker.** Removing `@pytest.mark.queueproof` from
PROOF-02's test while leaving its `proof(id="PROOF-02")` identity intact:

```
$ uv run python -m scripts.check_proof_inventory
PROOF id 'PROOF-02' matched no test under the CI-executed selection "queueproof and proof(id='PROOF-02')" — expected exactly one
node 'tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run' carries @pytest.mark.proof but is absent from the queueproof selection — it will never execute in CI's 'Run the queue durability proofs (real Postgres)' step in .github/workflows/concurrency-proof.yml; add @pytest.mark.queueproof
exit: 1
```

Reverted, `git diff --stat` empty, checker back to exit 0.

**Re-run it yourself.** This check needs no database — it is pure text-and-marker collection.

```bash
uv run python -m scripts.check_proof_inventory
```

A second, companion guard binds the four proofs' published mutation evidence — the diffs and
assertions shown above — to the live source they claim to describe, so a refactor that moves or
rewrites a mutated line without changing its behavior reds the guard instead of leaving a
falsification claim that no longer matches the code. It is also fully hermetic:

```bash
uv run pytest tests/test_proof_mutation_targets.py -v
```

## What is not guaranteed

A system that states precisely what it does *not* guarantee is making a stronger claim about the
rest of it, not a weaker one. These are the three limits accepted on purpose:

- **Exactly-once delivery is not achievable.** This is the Two Generals problem, not a library gap
  — no amount of engineering closes it, because the network between this system and the client's
  inbox can always fail silently after the message is genuinely sent. What is actually guaranteed
  is *at most one confirmation per approved run, per epoch* — narrower, and true.
- **Recovery is best-effort within roughly thirty minutes, not an absolute bound.** The recovery
  cron runs on a fixed cadence chosen to fit inside a hosting platform's free-tier hour budget, and
  GitHub Actions scheduling can delay any individual run. Separately, a scheduled workflow
  auto-disables itself after sixty days with no repository commit activity — a one-click
  re-enable, but a real failure mode if it goes unnoticed. The stated fallback for either case is
  operator retry, which is why a manual retrigger affordance exists on every stuck run.
- **An operator retrigger can legitimately send a second email.** Retriggering a run intentionally
  advances its reply epoch, which mints a fresh idempotency key under that epoch. That is why the
  claim above is written as *"at most once per approved run, per epoch"* and not the flatter, false
  "never twice" — a retrigger is a deliberate new attempt, not a bug in the exactly-once machinery.
- **CI does not run every live-database test — and this is the gap the five proofs came out of.**
  The proofs above run in CI by marker, so a new one is picked up with no workflow edit. But the
  older step beside them still selects two files *by name*. Counting at test granularity: of the
  104 tests marked as requiring a live database, 78 are executed by some CI step and **26 are
  executed by none** — spread across nine files, the largest being `test_seed_roundtrip.py` and
  `test_atomic_persist.py` at eight apiece. They pass locally against a real Postgres and are simply
  never run by CI. Widening that selection is not a one-line change: it would wake every dormant
  module at once against a single shared Postgres service, each running a destructive schema reset.
  The honest status is that these tests are green but unwatched, so a future regression in one of
  them would not be caught here.

  This is worth stating plainly because it is exactly how the preceding phase shipped a red build
  undetected: its own sign-off recorded a passing run that, on inspection, was an exact match for
  a run with no database configured at all. Twenty-three live-database tests were failing at that
  moment. Every one is fixed and the proofs above now run on every push — but a reader evaluating
  this system should know the difference between *"proven"* and *"proven, and watched"*.

## The operational counterpart

The five sections above establish what the system guarantees and how each guarantee was tested to
destruction. They say nothing about whether the system is, right now, inside those guarantees. The
`/ops` dashboard page is where that question gets answered — queue depth split by pending and
leased, the oldest overdue job's age compared against the recovery cadence, attempts compared
against the maximum before a job is given up on, and the dead-letter list of jobs that exhausted
their retries. Every number on that page is shown beside the bound that makes it meaningful, so an
operator can tell healthy from unhealthy without doing arithmetic from memory.
