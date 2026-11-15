"""Arturo API entry point.

Run in development (from the ``backend/`` folder)::

    uvicorn app.main:app --reload --port 8000

Interactive docs: http://localhost:8000/docs
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import features, health, layers, map, point, pois, routes, tiles
from app.catalog.map_config import get_map_config
from app.catalog.registry import get_registry
from app.catalog.routes_config import load_routes_config
from app.core.config import get_settings
from app.providers.factory import build_tile_provider
from app.rasters.factory import build_raster_datasets, describe as describe_rasters
from app.repositories.features import GeoJsonDirFeatureRepository
from app.repositories.pois import build_poi_repository
from app.repositories.routes import build_route_repository
from app.services.point import PointService
from app.services.route_analysis import RouteAnalyzer
from app.services.route_planner import RoutePlanner
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
    # Point queries: numeric GeoTIFFs behind the RasterSource abstraction
    # (local files; Earth mode may add the remote 200 m DEM).
    datasets = build_raster_datasets(settings)
    app.state.raster_datasets = datasets
    app.state.point_raster = describe_rasters(datasets)
    app.state.point_service = PointService(
        datasets, app.state.feature_repository, get_map_config().radius_m,
        app.state.point_raster, settings.rasters_dir,
    )
    # Routes: storage chosen by ROUTE_STORE; analysis on the same rasters.
    app.state.route_repository = build_route_repository(settings)
    app.state.route_analyzer = RouteAnalyzer(
        datasets, app.state.feature_repository, load_routes_config(settings.routes_file)
    )
    # Automatic planning: least-cost path on the same rasters, analysed
    # by the same analyser (the planner algorithm is swappable).
    app.state.route_planner = RoutePlanner(app.state.route_analyzer)
    yield
    await provider.close()
    for ds in datasets.values():
        if ds.source:
            ds.source.close()


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
app.include_router(point.router, prefix="/api")
app.include_router(routes.router, prefix="/api")


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
        "point": "/api/point?lat=-4.59&lon=137.44",
        "frontend": "Run the frontend (npm run dev) and open http://localhost:5173",
    }
