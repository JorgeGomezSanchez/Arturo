"""TileService + cache: evict truncated files, refetch, fill from a parent."""

from __future__ import annotations

import asyncio
import io
import struct
from pathlib import Path

from PIL import Image

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError, TileProvider
from app.providers.cached import CachedTileProvider
from app.services.images import is_cacheable
from app.services.tiles import TileService


def _png(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", compress_level=0)
    return buf.getvalue()


def _truncate_png(data: bytes) -> bytes:
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
        return out[: max(len(out) // 2, 16)]
    last_len = struct.unpack(">I", out[last_idat_at : last_idat_at + 4])[0]
    return out[: last_idat_at + 8 + max(last_len // 2, 1)]


CTX = LayerConfig(
    id="ctx_global_5m",
    name="CTX",
    format="png",
    tile_size=512,
    levels={"min": 0, "max": 12},
    transform={"nodata_to_transparent": True},
)


class FakeCtx(TileProvider):
    """Serves a given (z, x, y) -> bytes map; counts calls per key."""

    name = "fake"

    def __init__(self, tiles: dict[tuple[int, int, int], bytes]):
        self.tiles = tiles
        self.calls: list[tuple[int, int, int]] = []

    async def get_tile(self, layer, z, x, y):
        self.calls.append((z, x, y))
        try:
            content = self.tiles[(z, x, y)]
        except KeyError:
            raise TileNotFoundError()
        return Tile(content, "image/png", "fake")


class _Registry:
    def get(self, layer_id: str) -> LayerConfig:
        assert layer_id == CTX.id
        return CTX


def _run(service: TileService, z: int, x: int, y: int) -> Tile:
    return asyncio.run(service.get_tile(CTX.id, z, x, y))


def test_truncated_cache_is_evicted_and_replaced_with_good_upstream(tmp_path: Path):
    """If the cache holds a truncated file but upstream is fine, refetch."""
    good = _png(Image.new("L", (512, 512), 120))
    assert is_cacheable(good)
    path = tmp_path / "ctx_global_5m" / "5" / "1" / "1.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(_truncate_png(good))
    assert not is_cacheable(path.read_bytes())

    remote = FakeCtx({(5, 1, 1): good})
    service = TileService(_Registry(), CachedTileProvider(remote, tmp_path))
    tile = _run(service, 5, 1, 1)

    assert tile.origin in {"fake", "fake+truncated"} or "fake" in tile.origin
    # Recached the good upstream copy (nodata transform may re-encode, but
    # the cache itself stores the provider's original good bytes).
    assert path.is_file() and is_cacheable(path.read_bytes())
    assert remote.calls == [(5, 1, 1)]


def test_truncated_cache_and_upstream_are_filled_from_parent(tmp_path: Path):
    """The five Gale-style tiles: cache and upstream are both truncated.

    The bad cache file is deleted, upstream is asked again, and because
    it is still truncated the service fills the missing rows from the
    parent (fetched from upstream and then cached).
    """
    parent = Image.new("L", (512, 512), 80)
    parent.paste(180, (256, 256, 512, 512))  # SE quadrant → child 5/1/1
    parent_bytes = _png(parent)
    assert is_cacheable(parent_bytes)

    child = Image.new("L", (512, 512))
    pix = child.load()
    for y in range(512):
        for x in range(512):
            pix[x, y] = 40 + ((x + y * 3) % 80)
    truncated = _truncate_png(_png(child))
    # Keep only the first third so plenty of bottom rows are missing,
    # like the truncated CTX tiles Esri serves over Gale.
    truncated = truncated[: max(len(truncated) // 3, 64)]
    assert not is_cacheable(truncated)

    child_path = tmp_path / "ctx_global_5m" / "5" / "1" / "1.png"
    child_path.parent.mkdir(parents=True)
    child_path.write_bytes(truncated)

    remote = FakeCtx({(5, 1, 1): truncated, (4, 0, 0): parent_bytes})
    service = TileService(_Registry(), CachedTileProvider(remote, tmp_path))
    tile = _run(service, 5, 1, 1)

    assert tile.origin.endswith("+parent")
    img = Image.open(io.BytesIO(tile.content))
    img.load()
    # Top: recovered native rows; bottom: parent SE fill (180).
    top = img.convert("L").getpixel((256, 4))
    assert 40 <= top <= 119, top
    bottom = img.convert("LA").getpixel((256, 500))
    assert abs(bottom[0] - 180) <= 5 and bottom[1] == 255

    # Truncated child was evicted and not recached; complete parent was.
    assert not child_path.is_file()
    parent_path = tmp_path / "ctx_global_5m" / "4" / "0" / "0.png"
    assert parent_path.is_file() and is_cacheable(parent_path.read_bytes())
    assert (5, 1, 1) in remote.calls and (4, 0, 0) in remote.calls
