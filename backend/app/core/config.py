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

    # Allowed CORS origins (comma separated). In development the frontend
    # uses the Vite proxy, so this is usually not needed.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the settings (read once and reused)."""
    return Settings()
