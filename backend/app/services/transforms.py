"""Optional tile post-processing (``transform`` field of layers.yaml).

Transforms run AFTER the provider, so they behave the same in Earth and
Mars mode, and the cache/local packs keep the original, untouched tiles.
"""

from __future__ import annotations

import logging

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError
from app.services.images import decode_image, tile_from_image

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

    Truncated or mildly corrupt upstream tiles are decoded when possible
    (see :mod:`app.services.images`); only a completely unreadable image
    is treated as "no data" (404) so the layer below shows through,
    instead of failing the request with a 500.
    """
    image, complete = decode_image(tile.content)
    if image is None:
        log.warning("unreadable tile from %s", tile.origin)
        raise TileNotFoundError("unreadable image")

    grey = image.convert("L")
    # Alpha channel: 0 where the pixel is pure black, 255 elsewhere.
    alpha = grey.point(lambda v: 0 if v == 0 else 255)
    if alpha.getextrema() == (255, 255) and complete:
        return tile  # no gaps, well-formed: keep the original bytes

    if image.mode in ("L", "LA", "P", "I", "I;16"):
        out = grey.convert("LA")
    else:
        out = image.convert("RGBA")
    out.putalpha(alpha)
    # Re-encode even when there were no gaps if the source was
    # truncated, so the browser gets a well-formed PNG.
    return tile_from_image(out, "png", tile.origin)
