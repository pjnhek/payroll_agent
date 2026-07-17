# Deferred items from Plan 20-14

Resolved by the Wave 8 regression correction on 2026-07-17. The ten failures
were stale fake cursor rows, not production failures: the fixtures now match the
current persisted-email settlement projection, final-lease projection, and
job-first retry projection. The temporary deferred record is closed.
