"""Tile service: the logic between the endpoint and the provider.

1. Checks that the layer exists and the tile is inside its grid.
2. Asks the provider (whichever is configured) for the tile.
3. If the tile is missing, the source failed, or the image is truncated
   / corrupt, fills the gap from the nearest complete ancestor (parent,
   grandparent, ...) and composites any recovered native rows on top.
4. Applies the layer's post-processing (``transform`` in layers.yaml).
"""

from __future__ import annotations

import logging

from PIL import Image

from app.catalog.registry import LayerRegistry
from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError, TileProvider, TileProviderError
from app.services.images import (
    composite_truncated,
    decode_image,
    descendant_from_ancestor,
    tile_from_image,
)
from app.services.transforms import apply_transforms

log = logging.getLogger(__name__)


class TileService:
    def __init__(self, registry: LayerRegistry, provider: TileProvider):
        self.registry = registry
        self.provider = provider

    async def get_tile(self, layer_id: str, z: int, x: int, y: int) -> Tile:
        layer = self.registry.get(layer_id)  # LayerNotFoundError if missing
        if not layer.is_valid_tile(z, x, y):
            raise TileNotFoundError(f"Tile {z}/{x}/{y} is outside the grid of '{layer_id}'")
        tile = await self._get_or_repair(layer, z, x, y)
        return apply_transforms(layer, tile)

    async def _get_or_repair(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        native = await self._fetch(layer, z, x, y)
        image, complete = decode_image(native.content) if native is not None else (None, False)
        if image is not None and complete:
            return native

        fill, fill_origin = await self._ancestor_fill(layer, z, x, y)
        if image is not None and fill is not None and not complete:
            repaired = composite_truncated(image, fill)
            log.info(
                "repaired truncated %s %s/%s/%s from ancestor",
                layer.id, z, x, y,
            )
            return tile_from_image(repaired, layer.format, f"{native.origin}+parent")
        if fill is not None:
            reason = "missing" if native is None else "unreadable"
            log.info(
                "synthesized %s %s/%s/%s from ancestor (%s)",
                layer.id, z, x, y, reason,
            )
            return tile_from_image(fill, layer.format, fill_origin)
        if image is not None:
            # Best effort: serve the recovered strip (bottom stays black
            # and, for CTX, becomes transparent in the transform).
            log.warning(
                "truncated %s %s/%s/%s has no ancestor to fill from",
                layer.id, z, x, y,
            )
            return tile_from_image(image, layer.format, f"{native.origin}+truncated")

        raise TileNotFoundError(f"Tile {z}/{x}/{y} of '{layer.id}' is unavailable")

    async def _fetch(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile | None:
        """Provider tile, or None if it is missing or the source failed.

        Failures are swallowed here so we can fall back to a parent tile
        instead of bubbling a 502 up to the viewer.
        """
        try:
            return await self.provider.get_tile(layer, z, x, y)
        except TileNotFoundError:
            return None
        except TileProviderError as exc:
            log.warning("source error for %s %s/%s/%s: %s", layer.id, z, x, y, exc)
            return None

    async def _ancestor_fill(
        self, layer: LayerConfig, z: int, x: int, y: int
    ) -> tuple[Image.Image | None, str | None]:
        """Upscaled crop of the nearest complete ancestor, if any."""
        for steps in range(1, z - layer.levels.min + 1):
            az, ax, ay = z - steps, x >> steps, y >> steps
            if not layer.is_valid_tile(az, ax, ay):
                continue
            ancestor = await self._fetch(layer, az, ax, ay)
            if ancestor is None:
                continue
            image, complete = decode_image(ancestor.content)
            if image is None or not complete:
                continue
            fill = descendant_from_ancestor(image, x, y, steps, layer.tile_size)
            origin = f"{ancestor.origin}+parent"
            return fill, origin
        return None, None
