# Deferred items from Plan 20-14

The full-suite run (`uv run pytest -q`) reported 10 failures outside this plan's
files and boundary. They all exercise the earlier durable settlement/job-locking
changes in `app/db/repo/job_settlement.py` and `app/db/repo/jobs.py`, which Plan
20-14 does not modify:

- `tests/test_clarify.py`: three settlement fake-row shape failures.
- `tests/test_queue_drain.py`: five settlement/reaper fake-row shape failures.
- `tests/test_repo_jobs_sql.py`: two retry-now fake-row shape failures.

These failures were left unchanged to preserve Plan 20-13's committed work. The
Plan 20-14 focused suite, lint, type check, and guarded database command pass or
report the database evidence unavailable as documented in the plan summary.
