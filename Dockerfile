# Multi-stage uv-in-image Dockerfile (D-19, Astral official pattern).
# Verified against astral-sh/uv-docker-example/multistage.Dockerfile, 2026-06-23.
#
# HIGH-1 FIX: Runtime CMD uses .venv/bin/uvicorn directly — NOT `uv run`.
# The `uv` binary is NOT copied into the runtime stage (uv is a build tool only).
# Shell form required so ${PORT:-10000} expands at container start (Pitfall 3).
#
# WORKDIR=/app is REQUIRED in both stages — the app uses relative paths for
# app/templates, app/static, and eval/chart.svg (Pitfall 2, D-21).

# ── Builder stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Pin uv version for reproducible builds (latest at research time: 0.11.23)
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

# Configure uv for Docker (Astral recommended env vars):
#   UV_COMPILE_BYTECODE=1   → compile .py to .pyc at install time (faster startup)
#   UV_LINK_MODE=copy       → copy files instead of hardlinks (cross-device from layer cache)
#   UV_PYTHON_DOWNLOADS=0   → use the system Python in the base image (not uv-managed)
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

# WORKDIR=/app required for relative paths (templates, static, eval/chart.svg)
WORKDIR /app

# Layer 1: install dependencies (cached until pyproject.toml / uv.lock changes)
# --no-install-project: skip installing the project itself (source not copied yet)
# --frozen: fails if lockfile would change (stricter than --locked; correct for Docker)
# --no-dev: dev/test deps not needed in the image
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: copy the full source and install the project
COPY . .
RUN uv sync --frozen --no-dev

# ── Runtime stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# WORKDIR=/app required — uvicorn launched from here so relative paths resolve:
#   app/templates  → Jinja2Templates(directory="app/templates")
#   app/static     → StaticFiles(directory="app/static")
#   eval/chart.svg → Path("eval/chart.svg") in FileResponse route (D-21)
WORKDIR /app

# Copy the entire built app (source + venv) from the builder stage.
# The uv binary is NOT copied — it is a build tool only and is not needed at runtime.
# CMD uses .venv/bin/uvicorn directly (HIGH-1 fix: no `uv run` at runtime).
COPY --from=builder /app /app

# Add the venv to PATH so uvicorn and all installed executables are found.
ENV PATH="/app/.venv/bin:$PATH"

# Shell form required — Docker exec form does NOT expand ${PORT:-10000} (Pitfall 3).
# .venv/bin/uvicorn is used directly (HIGH-1 fix: uv binary not present in runtime stage).
# Render injects $PORT (default 10000). Bind to 0.0.0.0 — 127.0.0.1 causes 502.
CMD ["/bin/sh", "-c", ".venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
