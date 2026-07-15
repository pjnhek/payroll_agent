"""FastAPI entrypoint — thin app assembly only. Routes live in app/routes/*."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.queue import worker
from app.routes import dashboard, demo, health, pump, runs, webhook

app = FastAPI(title="Pyrl", lifespan=worker.lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(health.router)
app.include_router(webhook.router)
app.include_router(runs.router)
app.include_router(dashboard.router)
app.include_router(demo.router)
app.include_router(pump.router)
