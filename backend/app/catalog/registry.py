"""Layer registry: loads and validates ``layers.yaml``.

It is the only place in the backend that knows where the catalog lives.
The rest of the code asks the registry for layers (``get_registry()``).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.models.layer import LayerConfig


class LayerNotFoundError(KeyError):
    """A layer that is not in the catalog was requested."""


class LayerRegistry:
    def __init__(self, layers: list[LayerConfig]):
        ids = [layer.id for layer in layers]
        duplicated = {i for i in ids if ids.count(i) > 1}
        if duplicated:
            raise ValueError(f"Duplicated layer IDs in the catalog: {duplicated}")
        self._layers = {layer.id: layer for layer in layers}

    @classmethod
    def from_yaml(cls, path: Path) -> "LayerRegistry":
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        return cls([LayerConfig(**item) for item in raw.get("layers", [])])

    def all(self) -> list[LayerConfig]:
        """Every layer, sorted by group and stacking order."""
        return sorted(self._layers.values(), key=lambda l: (l.group != "base", l.z_index))

    def get(self, layer_id: str) -> LayerConfig:
        try:
            return self._layers[layer_id]
        except KeyError:
            raise LayerNotFoundError(layer_id) from None


@lru_cache
def get_registry() -> LayerRegistry:
    return LayerRegistry.from_yaml(get_settings().layers_file)
