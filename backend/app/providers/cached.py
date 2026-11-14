"""Disk cache decorator for any provider.

Wraps another provider: if the tile is already on disk it is served from
there; otherwise it is requested from the wrapped provider and saved.

Key detail: the cache uses EXACTLY the same layout as
:class:`LocalTileProvider`. So everything you browse in Earth mode is
also an offline data pack: copy ``cache/tiles`` to ``data/tiles``, set
``DATA_SOURCE=local`` and the app works without Internet.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileProvider, sniff_media_type
from app.providers.local import tile_path


class CachedTileProvider(TileProvider):
    def __init__(self, inner: TileProvider, cache_dir: Path):
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.name = f"{inner.name}+cache"

    async def get_tile(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        path = tile_path(self.cache_dir, layer, z, x, y)
        if path.is_file():
            content = await asyncio.to_thread(path.read_bytes)
            return Tile(content, sniff_media_type(content, layer.media_type), "cache")

        tile = await self.inner.get_tile(layer, z, x, y)
        await asyncio.to_thread(self._write_atomic, path, tile.content)
        return tile

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        """Write to a temp file and rename it, so concurrent requests
        never see half-written tiles."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def close(self) -> None:
        await self.inner.close()

    def describe(self) -> str:
        return f"{self.inner.describe()} + disk cache ({self.cache_dir})"
