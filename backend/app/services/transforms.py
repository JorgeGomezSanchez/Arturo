"""Optional tile post-processing (``transform`` field of layers.yaml).

Transforms run AFTER the provider, so they behave the same in Earth and
Mars mode, and the cache/local packs keep the original, untouched tiles.
"""

from __future__ import annotations

import io
import logging

from PIL import Image

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError

log = logging.getLogger(__name__)


def apply_transforms(layer: LayerConfig, tile: Tile) -> Tile:
    if layer.transform.nodata_to_transparent:
        tile = nodata_to_transparent(tile)
    return tile


def nodata_to_transparent(tile: Tile) -> Tile:
    """Make pure black pixels (value 0 = "no data") transparent.

    Mosaics like CTX paint the areas without coverage in black. Making
    them transparent lets the layer underneath (Viking colour) fill the
    gaps instead of showing black holes.
    """
    try:
        img = Image.open(io.BytesIO(tile.content))
        grey = img.convert("L")
    except OSError as exc:
        # Some upstream tiles at the edge of the CTX mosaic arrive
        # truncated. Treat them as "no data" (404) so the layer below
        # shows through, instead of failing the request with a 500.
        log.warning("unreadable tile from %s: %s", tile.origin, exc)
        raise TileNotFoundError(f"unreadable image: {exc}") from exc
    # Alpha channel: 0 where the pixel is pure black, 255 elsewhere.
    alpha = grey.point(lambda v: 0 if v == 0 else 255)
    if alpha.getextrema() == (255, 255):
        return tile  # no gaps: return the original as-is (cheaper)

    if img.mode in ("L", "LA", "P", "I", "I;16"):
        out = grey.convert("LA")
    else:
        out = img.convert("RGBA")
    out.putalpha(alpha)

    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return Tile(content=buf.getvalue(), media_type="image/png", origin=tile.origin)
