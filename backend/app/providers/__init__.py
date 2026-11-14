"""Data providers ("where do tiles come from?").

The rest of the backend only knows the :class:`TileProvider` interface.
Which implementation is used is decided by ``factory.build_tile_provider``
from the ``DATA_SOURCE`` setting. See the README for the Earth/Mars design.
"""

from app.providers.base import (  # noqa: F401
    Tile,
    TileNotFoundError,
    TileProvider,
    TileProviderError,
)
