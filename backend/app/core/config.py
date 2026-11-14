"""Central backend configuration.

Every setting is read from environment variables (or from a
``backend/.env`` file). This lets us change the backend's behaviour —for
example switching from "Earth mode" (remote NASA APIs) to "Mars mode"
(everything local)— without touching any code.

See ``backend/.env.example`` for the full, commented list.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Backend root folder (…/backend)
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuration settings (each field = one environment variable)."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Name shown in /docs and /api/health
    app_name: str = "Arturo API"
    app_version: str = "0.2.0"

    # Layer catalog (which layers exist and where they come from)
    layers_file: Path = BACKEND_DIR / "app" / "catalog" / "layers.yaml"
    # Map configuration (initial view, zoom limits) and detail zones
    map_file: Path = BACKEND_DIR / "app" / "catalog" / "map.yaml"

    # ------------------------------------------------------------------
    # DATA SOURCE (the Earth <-> Mars switch)
    #   remote -> Earth mode: tiles come from NASA Mars Trek / Esri over
    #             the Internet (and are stored in the disk cache).
    #   local  -> Mars mode: tiles are read ONLY from LOCAL_TILES_DIR,
    #             no network at all.
    # ------------------------------------------------------------------
    data_source: Literal["remote", "local"] = "remote"

    # Folder with offline tile packs: {dir}/{layer}/{z}/{x}/{y}.{ext}
    local_tiles_dir: Path = BACKEND_DIR / "data" / "tiles"

    # Disk cache for remote mode (same layout as LOCAL_TILES_DIR)
    tile_cache_enabled: bool = True
    tile_cache_dir: Path = BACKEND_DIR / "cache" / "tiles"

    # HTTP client for remote mode
    remote_timeout_s: float = 15.0
    remote_user_agent: str = "Arturo/0.1 (NASA Space Apps 2026 project)"

    # ------------------------------------------------------------------
    # NAMED FEATURES (labels): folder with *.geojson files (IAU names,
    # landing sites, exploration zones). Small static data shipped with
    # the repo, so it is read from disk in BOTH modes (works offline).
    # ------------------------------------------------------------------
    features_dir: Path = BACKEND_DIR / "data" / "features"

    # ------------------------------------------------------------------
    # USER POIs (points of interest placed by hand)
    #   json   -> one JSON file on disk (POI_STORE_FILE). Default.
    #   memory -> in RAM, lost on restart (tests / throwaway demos).
    # The rest of the backend only sees the PoiRepository interface,
    # so a SQLite / habitat database can be plugged in later.
    # ------------------------------------------------------------------
    poi_store: Literal["json", "memory"] = "json"
    poi_store_file: Path = BACKEND_DIR / "data" / "pois" / "pois.json"

    # ------------------------------------------------------------------
    # ROUTES: hand-drawn routes, same storage abstraction as POIs.
    #   ROUTE_STORE       json (file) | memory
    #   ROUTE_STORE_FILE  file of the json store (not in git)
    #   ROUTES_FILE       travel modes + hazard thresholds (routes.yaml)
    # ------------------------------------------------------------------
    route_store: Literal["json", "memory"] = "json"
    route_store_file: Path = BACKEND_DIR / "data" / "routes" / "routes.json"
    routes_file: Path = BACKEND_DIR / "app" / "catalog" / "routes.yaml"

    # ------------------------------------------------------------------
    # POINT QUERIES (GET /api/point): numeric rasters (GeoTIFF).
    #   RASTERS_DIR       folder with the GeoTIFFs built by
    #                     scripts/build_rasters.py (coarse global grids
    #                     are committed, so it works offline).
    #   RASTERS_FILE      catalog: which dataset lives in which file.
    #   POINT_REMOTE_DEM  in remote mode (Earth), also read the 200 m
    #                     HRSC+MOLA DEM from USGS with HTTP range
    #                     requests where no local 200 m crop exists.
    #                     Ignored in local mode (Mars): never online.
    # ------------------------------------------------------------------
    rasters_dir: Path = BACKEND_DIR / "data" / "rasters"
    rasters_file: Path = BACKEND_DIR / "app" / "catalog" / "rasters.yaml"
    point_remote_dem: bool = True
    point_remote_timeout_s: float = 8.0

    # Allowed CORS origins (comma separated). In development the frontend
    # uses the Vite proxy, so this is usually not needed.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator(
        "layers_file", "map_file", "local_tiles_dir", "tile_cache_dir", "features_dir", "poi_store_file",
        "rasters_dir", "rasters_file", "route_store_file", "routes_file",
    )
    @classmethod
    def _resolve_relative_to_backend(cls, value: Path) -> Path:
        """Relative paths are resolved against backend/, not the CWD."""
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the settings (read once and reused)."""
    return Settings()
