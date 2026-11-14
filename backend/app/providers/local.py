"""Local provider: reads tiles from a folder on disk (Mars mode).

Expected layout (the same one the cache writes)::

    {root}/{layer_id}/{z}/{x}/{y}.{format}

e.g. ``data/tiles/viking_mdim21_color/3/5/2.jpg``. No network involved:
this is how the app would run in a habitat on Mars, where a real-time
connection to Earth is impossible (4-24 min of light delay each way).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError, TileProvider, sniff_media_type


def tile_path(root: Path, layer: LayerConfig, z: int, x: int, y: int) -> Path:
    """Path of a tile inside a tile folder (shared by local and cache)."""
    return root / layer.id / str(z) / str(x) / f"{y}.{layer.format}"


class LocalTileProvider(TileProvider):
    name = "local"

    def __init__(self, root: Path):
        self.root = Path(root)

    async def get_tile(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        path = tile_path(self.root, layer, z, x, y)
        try:
            content = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            raise TileNotFoundError(f"Not in the local pack: {path}") from None
        return Tile(
            content=content,
            media_type=sniff_media_type(content, layer.media_type),
            origin=self.name,
        )

    def describe(self) -> str:
        return f"local ({self.root})"
