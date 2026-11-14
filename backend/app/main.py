"""Arturo API entry point.

Run in development (from the ``backend/`` folder)::

    uvicorn app.main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import features, health, layers, map, pois, tiles
from app.catalog.map_config import get_map_config
from app.catalog.registry import get_registry
from app.core.config import get_settings
from app.providers.factory import build_tile_provider
from app.repositories.features import GeoJsonDirFeatureRepository
from app.repositories.pois import build_poi_repository
from app.services.tiles import TileService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create the tile provider on startup and close it on shutdown.

    The provider is chosen from DATA_SOURCE (see providers/factory.py).
    """
    provider = build_tile_provider(settings)
    app.state.tile_provider = provider
    app.state.tile_service = TileService(get_registry(), provider)
    # Named features (labels): static GeoJSON shipped with the repo.
    app.state.feature_repository = GeoJsonDirFeatureRepository.from_dir(
        settings.features_dir, get_map_config().radius_m
    )
    # User POIs: storage chosen by POI_STORE (json file by default).
    app.state.poi_repository = build_poi_repository(settings)
    yield
    await provider.close()


app = FastAPI(
    lifespan=lifespan,
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
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Every public route lives under /api
app.include_router(health.router, prefix="/api")
app.include_router(layers.router, prefix="/api")
app.include_router(tiles.router, prefix="/api")
app.include_router(map.router, prefix="/api")
app.include_router(features.router, prefix="/api")
app.include_router(pois.router, prefix="/api")


@app.get("/", tags=["system"], summary="API index (what lives where)")
def root() -> dict:
    """Small index so opening the backend URL in a browser is not a bare 404.

    The real API lives under ``/api``; the interactive docs under ``/docs``.
    The map itself is served by the frontend (Vite, port 5173).
    """
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "api": "/api",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "/api/health",
        "frontend": "Run the frontend (npm run dev) and open http://localhost:5173",
    }
