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
    app_version: str = "0.1.0"

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

    # Allowed CORS origins (comma separated). In development the frontend
    # uses the Vite proxy, so this is usually not needed.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("layers_file", "map_file", "local_tiles_dir", "tile_cache_dir")
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
