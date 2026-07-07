---
phase: 10-concurrency-proof
audit_type: threat-mitigation-verification
asvs_level: 1
block_on: high
status: secured
threats_total: 4
threats_closed: 4
threats_open: 0
register_authored_at_plan_time: true
audited: 2026-07-07
---

# SECURITY.md — Phase 10: Concurrency Proof

**Phase:** 10 — concurrency-proof
**Audit type:** Threat-mitigation verification (register authored at plan time; verified against CURRENT implementation on disk)
**ASVS Level:** 1
**block_on:** high
**Result:** SECURED — 4/4 threats resolved (2 mitigated CLOSED, 1 accepted-risk CLOSED, 1 n/a CLOSED)
**threats_open:** 0
**Audited:** 2026-07-07

## Scope note

Test-only phase. `git diff --name-only 7df5dac HEAD -- app/` is empty — ZERO
production-code changes. The phase adds two files: `tests/test_concurrency_proof.py`
and `.github/workflows/concurrency-proof.yml`. A gap-closure plan (10-02) modified
the CI workflow AFTER the register was authored: it REMOVED the `bootstrap --reset`
step (reset ownership moved to the `seeded_db` fixture behind its `ALLOW_DB_RESET`
guard). All threats verified against the current on-disk file, not the plan-time
description.

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-10-01 | Tampering / Destructive-op | mitigate | CLOSED | `.github/workflows/concurrency-proof.yml:31` — `DATABASE_URL: "postgresql://postgres:postgres@localhost:5432/postgres"` (plain local container URL). `grep -c 'pooler.supabase.com'` == 0; no real-Supabase host anywhere. 10-02 STRENGTHENED this: `grep -c 'app.db.bootstrap --reset'` == 0 — the destructive reset step is gone (line 49 runs non-destructive `uv run python -m app.db.bootstrap`; reset now owned by the `seeded_db` fixture behind `ALLOW_DB_RESET`). No destructive op can touch anything but the ephemeral container. |
| T-10-02 | Elevation / Guard-leak | accept (test/CI-only) | CLOSED | Two-factor guards (`ALLOW_UNSIGNED_FIXTURES`, `ALLOW_DB_RESET`) appear as *runtime setters* ONLY in the CI job env (`.github/workflows/concurrency-proof.yml:32-33`) and the `tests/` tree. In `app/` they are read-only and default-safe: `app/config.py:62` `allow_unsigned_fixtures: bool = False` (production-safe default; comment at :61 explicitly forbids setting it in `render.yaml`); `app/main.py:303,321-326` reads the flag and rejects unsigned webhooks with HTTP 400 when it is False. The lone `ALLOW_DB_RESET` string in `app/` (`app/config.py:47`) is a comment, not code. `render.yaml` and `Dockerfile` set NEITHER guard (`grep` == 0). Accepted risk logged below. |
| T-10-03 | Information disclosure | mitigate | CLOSED | `.github/workflows/concurrency-proof.yml`: `grep -c 'secrets\.'` == 0 and `grep -c 'pooler.supabase.com'` == 0. The container password (`POSTGRES_PASSWORD: postgres`, line 17) is an ephemeral, network-isolated CI value — not a secret. Contrast with the sibling `.github/workflows/eval.yml:58` which legitimately uses `${{ secrets.EXTRACTION_API_KEY }}`; the concurrency-proof job needs no secret and references none. |
| T-10-SC | Tampering / supply-chain | n/a | CLOSED | `git diff --name-only 7df5dac HEAD -- pyproject.toml uv.lock` is empty — no dependency added/changed by the phase. The new workflow uses only already-present actions: `actions/checkout@v4` (line 36) and `astral-sh/setup-uv@v5` (line 38), both used verbatim by the pre-existing `eval.yml`. No new package-manager install surface; no legitimacy checkpoint required. |

## Accepted Risks Log

### AR-T-10-02 — Test/CI-only two-factor guards (`ALLOW_UNSIGNED_FIXTURES`, `ALLOW_DB_RESET`)

- **Disposition:** accept (test/CI-only), per PLAN register.
- **What is accepted:** The concurrency-proof CI job sets `ALLOW_UNSIGNED_FIXTURES: "true"` and `ALLOW_DB_RESET: "1"` in its job env, and the test suite sets them in-process. These enable, respectively, the unsigned-webhook dev bypass and the destructive DB reset.
- **Why it is safe:**
  1. Both are scoped to the CI job env + the test process only. Verified they appear as *setters* nowhere in `app/` runtime code, `render.yaml`, or the `Dockerfile`.
  2. Production defaults are safe: `allow_unsigned_fixtures` defaults `False` (`app/config.py:62`); unsigned webhooks are rejected with 400 in prod (`app/main.py:321-326`). `--reset` is opt-in via argv only (`app/db/bootstrap.py:139-140`).
  3. Render (the deploy target) sets neither variable, so neither guard is ever permissive in production.
- **Residual risk:** None in production. The CI value is confined to an ephemeral, network-isolated `postgres:16` container that is torn down after the job.

## Unregistered Flags

None. `10-01-SUMMARY.md` and `10-02-SUMMARY.md` declare no new production trust
boundary, endpoint, input, auth, or crypto surface (`tech-stack.added: []` in
both). The only new boundary is CI runner ↔ ephemeral Postgres container, already
covered by T-10-01/T-10-03. No new attack surface appeared during implementation
that lacks a threat mapping.

## Verification Commands (reproducible)

```
git diff --name-only 7df5dac HEAD -- app/            # empty (zero prod change)
git diff --name-only 7df5dac HEAD -- pyproject.toml uv.lock   # empty (no deps)
grep -c 'pooler.supabase.com' .github/workflows/concurrency-proof.yml   # 0
grep -c 'secrets\.'           .github/workflows/concurrency-proof.yml   # 0
grep -c 'app.db.bootstrap --reset' .github/workflows/concurrency-proof.yml   # 0
grep -rn 'ALLOW_UNSIGNED_FIXTURES\|ALLOW_DB_RESET' app/   # read-only refs / comment only, defaults False
grep -rln '...guards...' render.yaml Dockerfile           # (none — deploy sets neither)
```
