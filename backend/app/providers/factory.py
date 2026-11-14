"""Picks the tile provider from the configuration.

THIS is the switch between Earth and Mars. To add a new source (a
Martian network, a database...), implement ``TileProvider`` and add a
branch here; nothing else in the backend or frontend changes.
"""

from __future__ import annotations

from app.core.config import Settings
from app.providers.base import TileProvider
from app.providers.cached import CachedTileProvider
from app.providers.local import LocalTileProvider
from app.providers.remote import RemoteTileProvider


def build_tile_provider(settings: Settings) -> TileProvider:
    if settings.data_source == "local":
        # Mars mode: everything from disk, zero network.
        return LocalTileProvider(settings.local_tiles_dir)

    # Earth mode: NASA APIs (optionally with a disk cache).
    provider: TileProvider = RemoteTileProvider(
        timeout_s=settings.remote_timeout_s,
        user_agent=settings.remote_user_agent,
    )
    if settings.tile_cache_enabled:
        provider = CachedTileProvider(provider, settings.tile_cache_dir)
    return provider
