"""Arturo API entry point.

Run in development (from the ``backend/`` folder)::

    uvicorn app.main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import health, layers
from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Arturo API — Martian survival map (NASA Space Apps 2026). "
        "The frontend only talks to this API; where the data comes from "
        "(NASA APIs or local storage) is an internal detail."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Every public route lives under /api
app.include_router(health.router, prefix="/api")
app.include_router(layers.router, prefix="/api")
