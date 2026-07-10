"""Routes package — APIRouter modules split by URL-prefix concern (Phase 13 Plan 03).

Carved out of the former monolithic app/main.py: webhook.py (inbound ingest),
runs.py (operator gate + run detail), dashboard.py (landing/eval views),
demo.py (demo affordances), health.py (liveness/readiness/schema probes),
plus two shared modules — pipeline_glue.py (HTTP-to-orchestrator bridge
helpers) and templating.py (the shared Jinja2Templates instance + badge
filters). app/main.py itself is now thin app assembly only.
"""
