"""Decode, repair and upscale map-tile images.

The Esri OnMars/CTX service (and occasionally other upstreams) sometimes
answers HTTP 200 with a PNG that is truncated or internally corrupt:
Content-Length matches the body, but the stream has no IEND and the last
IDAT is cut short. Pillow then raises ``OSError`` ("image file is
truncated" / "broken data stream"), and a strict load would drop the
tile. Non-interlaced PNGs are written top-to-bottom, so the recoverable
part is a strip of good rows at the top; the rest comes out black.

These helpers:

* load such tiles anyway (``LOAD_TRUNCATED_IMAGES``);
* detect a *complete* image (well-formed PNG/JPEG) vs a partial decode;
* fill the missing bottom from an ancestor tile (the parent covers the
  same area at half the resolution), compositing any recovered native
  rows on top.
"""

from __future__ import annotations

import io
import struct
from contextlib import contextmanager

from PIL import Image, ImageFile

from app.providers.base import Tile, sniff_media_type


@contextmanager
def _load_truncated(enabled: bool):
    previous = ImageFile.LOAD_TRUNCATED_IMAGES
    ImageFile.LOAD_TRUNCATED_IMAGES = enabled
    try:
        yield
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = previous


def is_complete_png(data: bytes) -> bool:
    """True if ``data`` is a PNG with every chunk in bounds and an IEND.

    Extra bytes after IEND are tolerated (some upstream tiles append
    leftover payload). A truncated or length-corrupted stream is not
    complete, even if the file starts with the PNG signature.
    """
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return False
    pos = 8
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        end = pos + 8 + length + 4
        if end > len(data):
            return False
        pos = end
        if ctype == b"IEND":
            return True
    return False


def is_complete_jpeg(data: bytes) -> bool:
    """True if ``data`` is a JPEG with SOI and EOI markers."""
    return data.startswith(b"\xff\xd8") and b"\xff\xd9" in data


def is_complete_image(data: bytes) -> bool:
    if data.startswith(b"\x89PNG"):
        return is_complete_png(data)
    if data.startswith(b"\xff\xd8"):
        return is_complete_jpeg(data)
    return False


def _try_open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image


def decode_image(data: bytes) -> tuple[Image.Image | None, bool]:
    """Return ``(image, is_complete)``.

    ``is_complete`` is True only when the bytes are a well-formed image
    *and* Pillow could load them strictly. A truncated PNG that still
    decodes with ``LOAD_TRUNCATED_IMAGES`` comes back as
    ``(image, False)``. Undecodable input returns ``(None, False)``.
    """
    if not data:
        return None, False
    complete = is_complete_image(data)
    try:
        with _load_truncated(False):
            return _try_open(data), complete
    except OSError:
        pass
    try:
        with _load_truncated(True):
            return _try_open(data), False
    except OSError:
        return None, False


def last_decoded_row(image: Image.Image) -> int:
    """Index of the last row that is not entirely black (0), or -1.

    Used on a *partial* decode: Pillow fills unread rows of a truncated
    greyscale/RGB PNG with zeros, so this is the end of the recovered
    strip. Do not use it on a complete tile — genuine no-data can also
    be black.
    """
    grey = image.convert("L")
    width, height = grey.size
    rows = grey.tobytes()
    blank = b"\x00" * width
    for y in range(height - 1, -1, -1):
        start = y * width
        if rows[start : start + width] != blank:
            return y
    return -1


def descendant_from_ancestor(
    ancestor: Image.Image,
    x: int,
    y: int,
    steps: int,
    out_size: int,
) -> Image.Image:
    """Crop the window of ``ancestor`` that covers descendant tile (x, y).

    ``steps`` is the zoom difference (1 = immediate parent). The ancestor
    is assumed to be the tile at coordinates ``(x >> steps, y >> steps)``.
    """
    if steps < 1:
        raise ValueError("steps must be >= 1")
    n = 2**steps
    left = x & (n - 1)
    top = y & (n - 1)
    width, height = ancestor.size
    tile_w = width / n
    tile_h = height / n
    crop = ancestor.crop((
        round(left * tile_w),
        round(top * tile_h),
        round((left + 1) * tile_w),
        round((top + 1) * tile_h),
    ))
    return crop.resize((out_size, out_size), Image.Resampling.LANCZOS)


def composite_truncated(partial: Image.Image, fill: Image.Image) -> Image.Image:
    """Paste the recovered top rows of ``partial`` over ``fill``.

    ``fill`` is typically an upscaled ancestor covering the same area.
    If ``partial`` has no recovered rows, ``fill`` is returned as-is.
    """
    last = last_decoded_row(partial)
    if last < 0:
        return fill
    # Match modes so paste keeps the fill's channels (e.g. RGB parent,
    # greyscale partial).
    top = partial.crop((0, 0, partial.width, last + 1))
    if top.mode != fill.mode:
        top = top.convert(fill.mode)
    out = fill.copy()
    if out.size != (partial.width, partial.height):
        out = out.resize((partial.width, partial.height), Image.Resampling.LANCZOS)
    out.paste(top, (0, 0))
    return out


def encode_image(image: Image.Image, fmt: str) -> tuple[bytes, str]:
    """Encode ``image`` as PNG or JPEG; return ``(bytes, media_type)``."""
    buf = io.BytesIO()
    if fmt == "png" or image.mode in ("RGBA", "LA", "P"):
        if image.mode == "P":
            image = image.convert("RGBA")
        image.save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    image.convert("RGB").save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


def tile_from_image(image: Image.Image, fmt: str, origin: str) -> Tile:
    content, media_type = encode_image(image, fmt)
    return Tile(content=content, media_type=media_type, origin=origin)


def media_type_for(content: bytes, default: str) -> str:
    return sniff_media_type(content, default)
