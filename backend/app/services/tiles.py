"""Tile service: the logic between the endpoint and the provider.

1. Checks that the layer exists and the tile is inside its grid.
2. Asks the provider (whichever is configured) for the tile.
3. Applies the layer's post-processing (``transform`` in layers.yaml).
"""

from __future__ import annotations

from app.catalog.registry import LayerRegistry
from app.providers.base import Tile, TileNotFoundError, TileProvider
from app.services.transforms import apply_transforms


class TileService:
    def __init__(self, registry: LayerRegistry, provider: TileProvider):
        self.registry = registry
        self.provider = provider

    async def get_tile(self, layer_id: str, z: int, x: int, y: int) -> Tile:
        layer = self.registry.get(layer_id)  # LayerNotFoundError if missing
        if not layer.is_valid_tile(z, x, y):
            raise TileNotFoundError(f"Tile {z}/{x}/{y} is outside the grid of '{layer_id}'")
        tile = await self.provider.get_tile(layer, z, x, y)
        return apply_transforms(layer, tile)
