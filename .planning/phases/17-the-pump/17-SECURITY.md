---
phase: 17
slug: the-pump
status: verified
# threats_open = count of OPEN threats at or above workflow.security_block_on severity (the blocking gate)
threats_open: 0
asvs_level: 1
created: 2026-07-15
---

# Phase 17 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Phase 17 ("the pump") adds the authenticated external-cron drain trigger
> (`GET /internal/pump`), the `count_open_jobs` queue-depth read, the
> `DrainOutcome` enum + double-failure re-raise in `drain_once()`, the
> `pump.yml` GitHub Actions cron (folding in the deleted `keepalive.yml`), and
> the live-DB endpoint durability proof. Register authored at plan time across
> all 5 plans; verified retroactively at ASVS L1 (grep-depth) — the short-circuit
> path (`threats_open: 0`, register authored at plan time, `asvs_level == 1`).

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| worker/pump loop → `drain_once()` return | The loop's continue-vs-sleep decision depends entirely on the return's truthiness; a mistyped `__bool__` is a control-flow hazard. | `DrainOutcome` enum (in-process value, never persisted) |
| pump route → `count_open_jobs` SQL | The only input is a static, parameterless SQL string; no user-controlled value reaches the query. | Bare integer count (no row data) |
| GitHub Actions cron → Render service | The cron carries the `PUMP_TOKEN` Bearer secret over the network; the secret must never live in the repo, the URL, or step output. | `PUMP_TOKEN` shared secret |
| repo file → committed secret | A `value:` (not `sync:false`) entry, or a hardcoded token in `pump.yml`, would ship a live secret to a public portfolio repo. | `PUMP_TOKEN` at rest |
| cron/client → `/internal/pump` | Untrusted network request; the only trusted input is the Bearer secret, compared (constant-time) before any drain. | Authorization header |
| pump route → DB (claim/count) | A DB outage here must surface RED (503), never be swallowed into a GREEN 200. | Job rows, connection errors |
| test → live Postgres | The endpoint durability proof runs against a real database in CI (`concurrency-proof.yml`); it must isolate its jobs via `_isolated_jobs` so it neither pollutes nor is polluted by sibling proofs. | Seeded job rows |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-17-01D | Denial of Service | `drain.py` `DrainOutcome.__bool__` | medium | mitigate | `__bool__` returns `self is not DrainOutcome.EMPTY` — EMPTY is the ONLY falsy member, so `worker.py`'s `if drain.drain_once():` cannot busy-spin (`drain.py:138-139`). | closed |
| T-17-03D | Repudiation (silent infra failure) | `drain_once()` double-failure branch | high | mitigate | A `fail_job()`-write failure during a DB outage re-raises out of `drain_once()` (`drain.py:230`) instead of being swallowed as a truthy FENCED; the worker loop catches and survives, the pump route surfaces 503. Log is type-name-only. | closed |
| T-17-02D | Tampering | `test_job_kind_drift` collision guard | low | mitigate | `DrainOutcome` is deliberately NOT added to `tests/test_job_kind_drift.py` (verified absent) — its coincidental "done"/"dead" strings are a transport vocabulary, not a business-status column. | closed |
| T-17-06 | Tampering (SQL injection) | `count_open_jobs` query | low | mitigate | Fixed literal `SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')` with an empty params tuple — zero interpolation, zero injection surface (`jobs.py:304-306`). | closed |
| T-17-07 | Information Disclosure | `count_open_jobs` return value | low | accept | Returns a bare integer count; no row data, employee names, or error strings leak. | closed (accepted) |
| T-17-08 | Information Disclosure | `PUMP_TOKEN` provisioning | high | mitigate | `PUMP_TOKEN` is a `render.yaml` `sync: false` entry (never committed, `render.yaml:30-31`) and a GitHub Actions repo secret; `pump.yml` sends it in the `Authorization` header via `${{ secrets.PUMP_TOKEN }}`, never the query string — stays out of access logs and step output. | closed |
| T-17-09 | Repudiation / Monitoring-loss | keepalive fold-in | high | mitigate | `pump.yml` carries the `/health/schema` drift-monitor curl forward (plus `/health/ready`), both `if: always()` — the deleted `keepalive.yml`'s only drift monitor is preserved, not silently dropped. | closed |
| T-17-10 | Denial of Service (false RED) | pump step curl timeout | medium | mitigate | The pump step uses `curl -f --max-time 420` — a nominal budget (cold-start + between-jobs cap + one worst-case job's summed provider timeouts), intentionally larger than the health steps' 90s so a routine pump is not false-REDed. A rare overrun goes RED but is safe: correctness rests on lease-reclaim, not the curl budget. | closed |
| T-17-01 | Information Disclosure | `_authorized()` Bearer compare | medium | mitigate | `hmac.compare_digest(bytes, bytes)`, never `==` — timing-attack-resistant (`pump.py:79`). | closed |
| T-17-02 | Elevation of Privilege | unset `PUMP_TOKEN` | high | mitigate | Fail-closed: `_authorized()` returns `False` immediately when the token is falsy, BEFORE the compare (`pump.py:75-76`) — a misconfigured deploy can never be satisfied by an empty header. | closed |
| T-17-03 | Denial of Service | drain loop | medium | mitigate | Dual cap — `_MAX_JOBS_PER_PUMP` (20) and `_MAX_WALL_CLOCK_SECONDS` (120, checked between jobs) bound each invocation (`pump.py:61-62,96`) so a backlog flood cannot pin the request. | closed |
| T-17-04 | Information Disclosure | 401-vs-404 status | low | accept | 401 (not 404) deliberately reveals the route exists, in exchange for a loud RED on a misconfigured token. The route is not a data-disclosure surface. | closed (accepted) |
| T-17-05 | Information Disclosure | 503 body / logs | medium | mitigate | The infra branch logs only `type(exc).__name__` and returns a fixed `"pump unavailable"` body — never `str(exc)` (which could carry a connection string) (`pump.py:110-111`). | closed |
| T-17-13 | Repudiation (false GREEN over an outage) | `drain_once()` double-failure → 503 | high | mitigate | A DB-write failure inside `drain_once()` re-raises (`drain.py:230`); the route's try/except maps it to 503 (`pump.py:103-111`), so the cron goes RED over a real outage rather than reporting a 200. | closed |
| T-17-16 | Denial of Service (queue liveness) | `count_open_jobs` vs the final-attempt lease strand | medium | accept | A job whose worker/pump dies on its FINAL allowed attempt stays `state='leased', attempts=max_attempts, leased_until<now()` forever — the claim query's `attempts < max_attempts` guard can never re-select it and no reaper exists this phase, so it counts toward `queue_depth` indefinitely. PRE-EXISTING Phase-16 substrate limitation; low real impact (transport-liveness cosmetic; no payroll lost/duplicated, operator can retrigger); the fix (a dead-letter transition) is chartered to Phase-18/FAIL-02. See Accepted Risks Log. | closed (accepted) |
| T-17-11 | Repudiation (vacuous proof) | the durability test | high | mitigate | `test_pump_drains_future_due_job_with_zero_workers` carries the four non-vacuity traps (no `live_worker` race; asserts future job is genuinely unclaimable; asserts `claimed==1`/`done==1` from the JSON body + by-id re-read, never merely `status_code==200`; stubs the orchestrator and asserts `orchestrator_calls == [run_id]`) plus a documented falsifying mutation. | closed |
| T-17-14 | Tampering (real spend in CI) | unstubbed `run_pipeline_now` | high | mitigate | `pipeline_glue.run_pipeline_now` is stubbed via monkeypatch before the endpoint drain (`test_queue_durability.py:1194`) — draining the seeded `run_pipeline` job cannot invoke real paid LLM providers. | closed |
| T-17-15 | Tampering (settings leak) | `get_settings` lru_cache | low | mitigate | The test sets `PUMP_TOKEN` then clears the settings cache both before (`:1201`) and after (`:1286`, try/finally) so a cached token cannot leak into a later test. | closed |
| T-17-12 | Tampering | test isolation | low | mitigate | The endpoint proof's signature is `(seeded_db, monkeypatch)` — it does NOT request `live_worker`, so no real worker races the pump or complicates the delete-gate teardown; jobs are scoped by the module's `_isolated_jobs`. | closed |
| T-17-SC | Tampering (supply chain) | package installs | low | accept | Zero new packages this phase across all 5 plans (`enum`/`hmac`/stdlib only) — RESEARCH Package Legitimacy Audit not applicable. | closed (accepted) |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above workflow.security_block_on (high) count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-17-01 | T-17-07 | `count_open_jobs` returns a bare integer backlog count — no row data, names, or error strings leak; the pump route governs how it is surfaced. | Phase 17 plan authors | 2026-07-15 |
| AR-17-02 | T-17-04 | `/internal/pump` returns 401 (not 404) on a bad token — deliberately reveals the route exists so a misconfigured cron goes loudly RED; the route exposes no data. | Phase 17 plan authors | 2026-07-15 |
| AR-17-03 | T-17-16 | Final-attempt lease-strand: a job whose worker dies on its last allowed attempt stays `leased` and inflates `queue_depth` with no reaper this phase. Low real impact (cosmetic transport-liveness; no payroll lost/duplicated; operator can retrigger), a pre-existing Phase-16 substrate limitation, and the dead-letter fix is chartered to Phase-18/FAIL-02 (+ OPS-01 surfacing, Phase 21). CONTEXT.md fences recovery-mechanism reconciliation to Phase 18. | Phase 17 plan authors | 2026-07-15 |
| AR-17-04 | T-17-SC | Zero new third-party packages introduced this phase (stdlib `enum`/`hmac` only); no supply-chain surface to audit. | Phase 17 plan authors | 2026-07-15 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-15 | 20 | 20 | 0 | /gsd-secure-phase (orchestrator, ASVS L1 grep-depth short-circuit) |

Verification method: L1 grep-depth against live source. All 16 `mitigate` threats confirmed present in the implementation (`app/queue/drain.py`, `app/routes/pump.py`, `app/db/repo/jobs.py`, `.github/workflows/pump.yml`, `render.yaml`, `tests/test_queue_durability.py`, `tests/test_job_kind_drift.py`); all 4 `accept` threats documented in the Accepted Risks Log. No open threats at or above the `high` block threshold.

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-15
