"""Optional tile post-processing (``transform`` field of layers.yaml)."""

from __future__ import annotations

from app.models.layer import LayerConfig
from app.providers.base import Tile


def apply_transforms(layer: LayerConfig, tile: Tile) -> Tile:
    # Placeholder: transforms are implemented in the next commit.
    return tile
