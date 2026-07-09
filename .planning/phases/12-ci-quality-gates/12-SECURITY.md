---
phase: 12
slug: 12-ci-quality-gates
status: verified
threats_open: 0
asvs_level: 1
created: 2026-07-09
---

# Phase 12 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|----------------|
| Local dev machine → committed pyproject.toml | Config-only change; no runtime/network surface | Ruff ruleset/line-length config, no secrets |
| ruff autofix / hand-fix → source tree | Automated + manual code rewrite across app/eval/scripts/tests; test suite is the safety net | Source code only, no data |
| Dirty working tree → git commit | Unrelated pre-existing dirty/staged files (mid-flight `.planning` deletions from another session) could be swept into commits if staged carelessly | Repo file paths |
| Any branch push → GitHub Actions runner | `ci.yml` triggers on `push` with no `branches:` filter — any branch (including a fork PR context) runs CI with the workflow's token | Repo checkout, default `GITHUB_TOKEN` |
| ci.yml → external actions (`actions/checkout`, `astral-sh/setup-uv`) | Third-party GitHub Action supply chain | Repo contents, ephemeral runner environment |
| README badge URL → GitHub's badge.svg endpoint | Public, unauthenticated image fetch by anyone viewing the README | None (public status only) |
| Throwaway branch push → GitHub Actions | Deliberately broken code triggers a real CI run; branch discarded after, run history persists | Injected lint error / test failure (non-sensitive) |
| Human-observed run URLs → committed VERIFICATION.md | Human-supplied strings written into a tracked file | GitHub Actions run URLs |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-12-01 | Tampering | `ruff --fix` rewriting source (safe-only, `--unfixable SIM117`, suite green after) | mitigate | `--unfixable SIM117` used (not plain `--fix`), no `--unsafe-fixes`; suite re-verified green (613 passed/50 skipped) immediately after | closed |
| T-12-02 | Info Disclosure | pyproject.toml config commit (no secrets) | accept | Config-only change; verified no secrets/credentials in `[tool.ruff]`/`[tool.ruff.lint]` blocks | closed |
| T-12-03 | Tampering | B904 raise-from edits in app/main.py, app/llm/client.py | mitigate | All 6 `HTTPException` re-raises in app/main.py and the retry re-raise in app/llm/client.py chain `from exc` (verified via grep) | closed |
| T-12-04 | Tampering | StrEnum base-class change on RunStatus | mitigate | `app/models/status.py:9` confirmed `class RunStatus(enum.StrEnum)`; SUMMARY documents the pre-change call-site audit (only `.value`/raw-DB-string renders, no qualified-name `str()` dependency) | closed |
| T-12-05 | Tampering | SIM117 structural collapse (46 sites, 6 files) preserving transaction scoping | mitigate | `uv run ruff check --select SIM117 .` → "All checks passed!"; zero `# ruff: noqa: SIM117` in tracked `.py` files; spot-checked collapsed `with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():` idiom in app/db/repo.py and the hand-collapsed `with get_connection() as conn, conn.transaction():` in app/db/seed.py — semantics preserved, only structure changed | closed |
| T-12-06 | Elevation of Privilege | ci.yml token permissions | mitigate | **Superseded/strengthened by post-plan hardening (commit 7ad2177):** explicit `permissions: contents: read` block now present at workflow level in `.github/workflows/ci.yml` (verified at current HEAD) — stronger than the plan's original "omit permissions block" text | closed |
| T-12-07 | Info Disclosure | lint/test logs leaking secrets (no secrets in env) | accept | Verified zero `env:` blocks and zero `secrets.*` references anywhere in `ci.yml` | closed |
| T-12-SC | Tampering | Supply-chain: actions pinned by tag not SHA | accept (superseded) | **Superseded by post-plan hardening (commit c0d8de4):** both `actions/checkout` and `astral-sh/setup-uv` are now SHA-pinned in `.github/workflows/ci.yml` (`@34e114876b0b11c390a56381ad16ebd13914f8d5` / `@d4b2f3b6ecc6e67c4457f6d3e41ec42d3d0fcb86`, version noted in trailing comments) — the accepted risk no longer exists; closed by hardening, not by acceptance | closed |
| T-12-08 | Tampering | Badge URL spoof/typo | mitigate | README.md badge URL confirmed `https://github.com/pjnhek/payroll_agent/actions/workflows/ci.yml/badge.svg`, matching `git remote -v`'s confirmed slug; exactly one `badge.svg` occurrence | closed |
| T-12-09 | Tampering | Throwaway red-proof branches left on remote | mitigate | `git ls-remote --heads origin` shows only `refs/heads/master` — both `ci-redproof-lint`/`ci-redproof-test` deleted | closed |
| T-12-10 | Spoofing | Run URLs pasted incorrectly / off-repo | mitigate | All three URLs in 12-VERIFICATION.md confirmed to start with `https://github.com/pjnhek/payroll_agent/actions/runs/` (grep-verified); phase 12 verifier additionally independently re-confirmed via live `gh run view` against all three run IDs | closed |
| T-12-11 | Tampering | Dirty worktree sweeping unrelated files into commits (Plan 12-01) | mitigate | `git show --stat 744b857` confirms only `pyproject.toml` + `.py` files under app/eval/scripts/tests touched, no `.planning` files swept in | closed |
| T-12-12 | Tampering | Dirty worktree sweeping unrelated files into commits (Plan 12-02) | mitigate | `git show --stat c2268cb`/`36a9f5d` (per 12-02-SUMMARY) confirm only declared `.py` files touched | closed |
| T-12-13 | Tampering | Dirty worktree sweeping unrelated files into commits (Plan 12-03) | mitigate | `git show --stat 925de84` confirms only `.github/workflows/ci.yml` added; README committed separately (`1a87879`) | closed |
| T-12-14 | Tampering | Dirty worktree sweeping unrelated files into commits (Plan 12-04) | mitigate | `git show --stat ab2676e`/`6935e72`/`49422c5` confirm single-file scope per commit (`app/main.py`, `tests/test_check_schema_cli.py`, `12-VERIFICATION.md` respectively) | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|--------------|------|
| AR-12-01 | T-12-02 | pyproject.toml config commit (ruff ruleset/line-length) carries no secrets or credentials; config-only, no runtime/network surface | Phase 12 plan (D-01/D-02/D-03) | 2026-07-09 |
| AR-12-02 | T-12-07 | `ci.yml` sets no `env:` block and references no `secrets.*` in either job; nothing secret-bearing exists in this workflow's environment to leak into logs | Phase 12 plan (D-11) | 2026-07-09 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|----------------|--------|------|--------|
| 2026-07-09 | 14 | 14 | 0 | Claude (gsd-security-auditor) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-09

---

## Notes

- **Post-plan hardening confirmed superseding two threats:** T-12-06 (workflow permissions) and T-12-SC (supply-chain SHA pinning) were both strengthened beyond their original plan-time disposition by commits `7ad2177`, `c0d8de4`, `c4ad877` — all three verified present at current HEAD via `git show` against `.github/workflows/ci.yml`. T-12-06's mitigation now exceeds the plan text (explicit least-privilege `permissions: contents: read` block, not merely an omitted block); T-12-SC's "accept" disposition is obsolete since both actions (`actions/checkout`, `astral-sh/setup-uv`) are now pinned to full commit SHAs with version-identifying comments. Recorded as closed-by-hardening for both, per the post_plan_changes note — not flagged as a plan/implementation mismatch.
- **No unregistered attack surface found:** none of the four plan SUMMARYs (12-01 through 12-04) contain a `## Threat Flags` section, so there is no new attack surface to reconcile against the register.
- **Live evidence independently re-verified by this audit, not merely trusted from SUMMARY/VERIFICATION narrative:** `uv run ruff check .` → "All checks passed!"; `uv run pytest -q` → 613 passed, 50 skipped; `git ls-remote --heads origin` → only master; all three 12-VERIFICATION.md run URLs grep-confirmed under the correct repo slug.
