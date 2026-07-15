---
phase: 17-the-pump
reviewer: codex-cli 0.144.0 (cross-AI confirming review)
reviewed: 2026-07-15
scope: git diff 9614161..HEAD (all of Phase 17, production source + tests)
status: issues_found
findings:
  critical: 0
  high: 1
  medium: 0
  low: 0
  total: 1
orchestrator_severity_note: "Codex rated the single finding HIGH; the orchestrator assesses it MEDIUM/LOW (log-only, operator-visible Render logs, requires a rare double-failure whose exception is typically a psycopg host/dbname message — not the password; pre-existing and deliberately kept by plan 17-01). Real but debatable."
---

# Phase 17 — Codex Cross-AI Confirming Review

A second, independent adversarial pass over the merged Phase 17 implementation (requested via
`/gsd-code-review 17 --codex`), complementing the in-house `17-REVIEW.md`. Run with `codex exec`
in a read-only sandbox over `git diff 9614161..HEAD`.

## Findings

### CODEX-01 — Upstream double-failure log discloses `str(exc)` / traceback (Codex: High; orchestrator: Medium/Low)

**File:** `app/queue/drain.py:216`

**Defect:** The double-failure branch (`fail_job()` itself raised) logs with `logger.exception(...)`.
The message template interpolates only `job.id`, but `logger.exception` appends the current
exception's full traceback — whose final line is `type(exc): str(exc)`. If the `fail_job` write
failed with a psycopg error whose message carries DB connection detail (host/port/dbname/user), that
detail is emitted to Render logs — even though the pump route deliberately logs only
`type(exc).__name__` and returns a fixed 503 body. So the phase's stated "never log `str(exc)` — it
could carry a connection string" disclosure discipline (T-17-05) is enforced at the route but
undermined one level upstream.

**Failure scenario:** `dispatch.handle` fails → `fail_job()` raises `OperationalError("connection to
server at db.<ref>...:6543 failed: ...")` → `drain_once()`'s inner except runs `logger.exception(...)`
(emitting that message + traceback to logs) before re-raising → the route returns the sanitized 503,
but the connection detail is already in the log stream.

**Nuance / why not clearly High:** (a) it is a *log* disclosure into operator-only Render logs, not
an HTTP-response leak; (b) it requires the rare double-failure (a DB outage precisely during the
`fail_job` write); (c) psycopg connection-error messages typically expose host/dbname, not the
password; (d) it is pre-existing — plan 17-01 explicitly said "keep the existing `logger.exception`
message verbatim." It is nevertheless a genuine inconsistency with an invariant Phase 17 itself
adopted, and Phase 17 is the phase that routed this branch into an HTTP-facing endpoint.

**Recommended fix (operability-preserving):** change the inner `except Exception:` to
`except Exception as exc:` and replace `logger.exception(...)` with `logger.error(<same message
template>, job.id, type(exc).__name__)` (append the exception *type name* — the safe, useful part —
and drop the traceback/`str(exc)`). This matches the route's disclosure discipline exactly while
keeping the branch, job id, and error category in the log. Trade-off: loses the full psycopg
message/traceback that aids diagnosing *why* the write failed (that detail is the same string that
carries the small disclosure risk). Before applying, grep tests for any assertion on the current
`logger.exception` call/traceback (e.g. `caplog`) and adjust.

## Confirmed invariants (Codex verified, no defect)

- **D-10 holds** — a failed `fail_job()` write re-raises from `drain_once()` → HTTP 503, never a
  truthy `DrainOutcome`/200.
- **Auth** fails closed on empty/unset token (before compare), `hmac.compare_digest` over the full
  `Bearer <token>` bytes, 401 not 404.
- **503 body** is fixed/short; the *route* logs only `type(exc).__name__` (CODEX-01 is the sole
  disclosure gap, and it is upstream of the route).
- **`claimed == done + retried + dead + fenced`** holds by construction.
- **Dual bound** — max-jobs and between-jobs wall-clock are both independently enforced; `EMPTY` is
  the only falsy `DrainOutcome`, preserving `worker.py` busy-vs-sleep behavior.
- Static/parameterized SQL, no cross-module `_private` imports in the route, no `--no-verify`.
- **`pump.yml`** — block-scalar drain step, both health steps carry `if: always()`, all three curls
  are independent RED signals, `keepalive.yml` removed without losing either health endpoint.
- **The durability anchor** is genuinely anti-vacuous — verifies the pump-driven handler call, job/run
  state, counts, and final queue depth (not merely status 200).
- The five durability-test citation edits are comments/docstrings only and weaken no assertions.
- The accepted final-attempt lease-strand residual (T-17-16, deferred to Phase 18/FAIL-02) was
  correctly NOT reported as a new defect.

_Note: Codex could not run the pytest suite (its read-only sandbox blocked `uv`'s cache); the
orchestrator had already run the full suite green (hermetic 735 passed; live queueproof 19 passed,
0 skipped) and independently falsification-tested the durability anchor._
