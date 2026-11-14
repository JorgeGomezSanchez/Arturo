"""Tile provider interface (the "black box" contract).

Any data source —NASA APIs over the Internet (Earth), a folder on disk
(Mars habitat), a future Martian network or database— only has to
implement :meth:`TileProvider.get_tile`. Endpoints, services and the
frontend never change when the source changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.layer import LayerConfig


@dataclass(frozen=True)
class Tile:
    """A tile image ready to be sent to the client."""

    content: bytes
    media_type: str
    # Where it came from: "remote", "cache", "local"... (debug header)
    origin: str


class TileNotFoundError(Exception):
    """The tile doesn't exist in this source (no coverage, off-grid...)."""


class TileProviderError(Exception):
    """The source failed (network down, timeout, unexpected answer...)."""


class TileProvider(ABC):
    """Abstract tile source.

    Implementations:
      * ``RemoteTileProvider`` — downloads from the URL in layers.yaml
        (NASA Mars Trek / Esri). Earth mode.
      * ``LocalTileProvider`` — reads ``{root}/{layer}/{z}/{x}/{y}.{ext}``.
        Mars mode (offline).
      * ``CachedTileProvider`` — decorator: wraps another provider and
        stores every tile on disk with the SAME layout as the local
        provider, so the cache doubles as an offline data pack.
    """

    #: Short name, shown in /api/health
    name: str = "abstract"

    @abstractmethod
    async def get_tile(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        """Return tile (z, x, y) of ``layer``.

        ``z`` is the NATIVE source level, ``x`` the column (from the
        left, -180°) and ``y`` the row (from the top, +90°).

        Raises:
            TileNotFoundError: the tile doesn't exist in this source.
            TileProviderError: the source failed.
        """

    async def close(self) -> None:  # pragma: no cover - optional
        """Free resources (HTTP connections...). Called on shutdown."""

    def describe(self) -> str:
        return self.name


def sniff_media_type(content: bytes, default: str) -> str:
    """Detect the real image type from its first bytes."""
    if content.startswith(b"\x89PNG"):
        return "image/png"
    if content.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return default
