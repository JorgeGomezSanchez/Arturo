"""Unit tests for tile image repair and ancestor fill (no network)."""

from __future__ import annotations

import io
import struct

from PIL import Image

from app.services.images import (
    composite_truncated,
    decode_image,
    descendant_from_ancestor,
    is_complete_png,
    last_decoded_row,
)


def _png(image: Image.Image, compress_level: int = 6) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=compress_level)
    return buf.getvalue()


def _truncate_png(data: bytes, drop_iend_and_cut_last_idat: bool = True) -> bytes:
    """Strip IEND and cut the last IDAT short so the stream is incomplete."""
    pos = 8
    out = data[:8]
    last_idat_at = None
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        ctype = data[pos + 4 : pos + 8]
        end = pos + 8 + length + 4
        if ctype == b"IEND":
            break
        if ctype == b"IDAT":
            last_idat_at = len(out)
        out += data[pos:end]
        pos = end
    if last_idat_at is None:
        return out[:-20]
    # Keep only the first half of the last IDAT (header included).
    last_len = struct.unpack(">I", out[last_idat_at : last_idat_at + 4])[0]
    keep = last_idat_at + 8 + max(last_len // 2, 1)
    return out[:keep]


def test_complete_png_roundtrip():
    data = _png(Image.new("L", (32, 32), 80))
    assert is_complete_png(data)
    image, complete = decode_image(data)
    assert complete and image is not None and image.size == (32, 32)


def test_truncated_png_is_not_complete_but_decodes():
    # A unique vertical gradient so we can tell how many rows survived.
    img = Image.new("L", (64, 64))
    pix = img.load()
    for y in range(64):
        for x in range(64):
            pix[x, y] = 40 + y * 2
    # Uncompressed so a mid-IDAT cut leaves a predictable top strip.
    truncated = _truncate_png(_png(img, compress_level=0))
    assert not is_complete_png(truncated)
    image, complete = decode_image(truncated)
    assert image is not None and complete is False
    last = last_decoded_row(image)
    # Some, but not all, rows must have been recovered.
    assert 0 <= last < 63


def test_garbage_with_png_signature_does_not_decode():
    image, complete = decode_image(b"\x89PNG\r\n\x1a\n" + b"nope")
    assert image is None and complete is False


def test_descendant_from_ancestor_picks_the_right_quadrant():
    # 4-colour parent: NW=10, NE=20, SW=30, SE=40 (values well above nodata).
    parent = Image.new("L", (64, 64))
    parent.paste(10, (0, 0, 32, 32))
    parent.paste(20, (32, 0, 64, 32))
    parent.paste(30, (0, 32, 64, 64))
    parent.paste(40, (32, 32, 64, 64))
    # Child (5, 3) with 1 step: parent is (2, 1), quadrant (1, 1) = SE.
    # We pass x=5, y=3, steps=1 → left=1, top=1.
    child = descendant_from_ancestor(parent, 5, 3, steps=1, out_size=64)
    # Every pixel should be close to 40 (LANCZOS at a hard edge may blend
    # a 1-px seam, so sample the centre).
    assert child.size == (64, 64)
    assert abs(child.getpixel((32, 32)) - 40) <= 2


def test_composite_truncated_keeps_native_top_and_fills_the_bottom():
    fill = Image.new("L", (32, 32), 200)
    partial = Image.new("L", (32, 32), 0)
    partial.paste(80, (0, 0, 32, 10))  # 10 recovered rows
    out = composite_truncated(partial, fill)
    assert out.getpixel((16, 5)) == 80
    assert out.getpixel((16, 20)) == 200
