"""Routes package — APIRouter modules split by URL-prefix concern.

webhook.py (inbound ingest), runs.py (operator gate + run detail),
dashboard.py (landing/eval views), demo.py (demo affordances), health.py
(liveness/readiness/schema probes), plus two shared modules —
pipeline_glue.py (HTTP-to-orchestrator bridge helpers) and templating.py
(the shared Jinja2Templates instance + badge filters). app/main.py is thin
app assembly only.
"""
