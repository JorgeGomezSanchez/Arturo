"""Disk cache decorator for any provider.

Wraps another provider: if the tile is already on disk it is served from
there; otherwise it is requested from the wrapped provider and saved.

Key detail: the cache uses EXACTLY the same layout as
:class:`LocalTileProvider`. So everything you browse in Earth mode is
also an offline data pack: copy ``cache/tiles`` to ``data/tiles``, set
``DATA_SOURCE=local`` and the app works without Internet.

Only well-formed, strictly decodable images are written (atomic
tempfile + ``fsync`` + ``os.replace``). Truncated or corrupt files —
a download cut short, or a PNG that the upstream already serves
without an IEND — are never stored. If one is already on disk (an
older cache, or a crash before this check existed) it is deleted and
treated as a miss, so the inner provider can refetch it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileProvider, sniff_media_type
from app.providers.local import tile_path
from app.services.images import is_cacheable

log = logging.getLogger(__name__)


class CachedTileProvider(TileProvider):
    def __init__(self, inner: TileProvider, cache_dir: Path):
        self.inner = inner
        self.cache_dir = Path(cache_dir)
        self.name = f"{inner.name}+cache"

    async def get_tile(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        path = tile_path(self.cache_dir, layer, z, x, y)
        if path.is_file():
            content = await asyncio.to_thread(path.read_bytes)
            if is_cacheable(content):
                return Tile(content, sniff_media_type(content, layer.media_type), "cache")
            log.warning(
                "evicting unreadable/truncated cache file %s (%s bytes)",
                path, len(content),
            )
            await asyncio.to_thread(path.unlink, True)

        tile = await self.inner.get_tile(layer, z, x, y)
        if is_cacheable(tile.content):
            await asyncio.to_thread(self._write_atomic, path, tile.content)
        else:
            log.warning(
                "not caching incomplete %s %s/%s/%s (%s bytes)",
                layer.id, z, x, y, len(tile.content),
            )
        return tile

    @staticmethod
    def _write_atomic(path: Path, content: bytes) -> None:
        """Write to a temp file, fsync, then rename over the destination.

        Concurrent readers never see a half-written tile. ``fsync``
        before ``os.replace`` also means a process killed mid-write
        leaves a ``*.part`` orphan at worst, not a truncated final file.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            dir_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def close(self) -> None:
        await self.inner.close()

    def describe(self) -> str:
        return f"{self.inner.describe()} + disk cache ({self.cache_dir})"
