"""Unit tests of the provider layer (no network)."""

from __future__ import annotations

import asyncio

import pytest

import io

from PIL import Image

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError, TileProvider
from app.providers.cached import CachedTileProvider
from app.providers.local import LocalTileProvider
from app.services.images import is_cacheable

LAYER = LayerConfig(id="demo", name="Demo", format="jpg", levels={"min": 0, "max": 3})


def _complete_jpeg(color=(200, 100, 50), size=32) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="JPEG", quality=90)
    data = buf.getvalue()
    assert is_cacheable(data)
    return data


GOOD_JPEG = _complete_jpeg()


class FakeRemote(TileProvider):
    name = "fake"

    def __init__(self, content: bytes | None = None):
        self.calls = 0
        self.content = content if content is not None else GOOD_JPEG

    async def get_tile(self, layer, z, x, y):
        self.calls += 1
        if (z, x, y) == (0, 0, 0):
            return Tile(self.content, "image/jpeg", "fake")
        raise TileNotFoundError()


def test_cache_stores_tile_and_reuses_it(tmp_path):
    remote = FakeRemote()
    cached = CachedTileProvider(remote, tmp_path)

    first = asyncio.run(cached.get_tile(LAYER, 0, 0, 0))
    second = asyncio.run(cached.get_tile(LAYER, 0, 0, 0))

    assert first.origin == "fake" and second.origin == "cache"
    assert remote.calls == 1
    # Same layout as LocalTileProvider => the cache is an offline pack
    assert (tmp_path / "demo" / "0" / "0" / "0.jpg").read_bytes() == first.content
    local = asyncio.run(LocalTileProvider(tmp_path).get_tile(LAYER, 0, 0, 0))
    assert local.content == first.content


def test_cache_does_not_store_missing_tiles(tmp_path):
    cached = CachedTileProvider(FakeRemote(), tmp_path)
    with pytest.raises(TileNotFoundError):
        asyncio.run(cached.get_tile(LAYER, 1, 1, 1))
    assert not any(tmp_path.rglob("*.jpg"))


def test_cache_does_not_store_incomplete_tiles(tmp_path):
    """A truncated upstream body is returned for salvage but not written."""
    truncated = GOOD_JPEG[: len(GOOD_JPEG) // 2]
    assert not is_cacheable(truncated)
    cached = CachedTileProvider(FakeRemote(truncated), tmp_path)
    tile = asyncio.run(cached.get_tile(LAYER, 0, 0, 0))
    assert tile.content == truncated and tile.origin == "fake"
    assert not any(tmp_path.rglob("*.jpg"))


def test_truncated_cache_is_evicted_and_refetched(tmp_path):
    """A half-written / truncated file already on disk is a cache miss."""
    path = tmp_path / "demo" / "0" / "0" / "0.jpg"
    path.parent.mkdir(parents=True)
    path.write_bytes(GOOD_JPEG[:40])
    remote = FakeRemote(GOOD_JPEG)
    cached = CachedTileProvider(remote, tmp_path)

    tile = asyncio.run(cached.get_tile(LAYER, 0, 0, 0))

    assert tile.origin == "fake" and tile.content == GOOD_JPEG
    assert remote.calls == 1
    assert path.read_bytes() == GOOD_JPEG
    # Next hit comes from the recached good file.
    again = asyncio.run(cached.get_tile(LAYER, 0, 0, 0))
    assert again.origin == "cache" and remote.calls == 1


def test_grid_validation():
    assert LAYER.is_valid_tile(0, 1, 0)
    assert not LAYER.is_valid_tile(0, 2, 0)
    assert not LAYER.is_valid_tile(0, 0, 1)
    assert not LAYER.is_valid_tile(4, 0, 0)


def test_remote_retries_then_succeeds():
    """A transient upstream 500 is retried and then served."""
    import httpx

    from app.providers.remote import RemoteTileProvider

    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(500, text="temporary")
        return httpx.Response(200, content=GOOD_JPEG, headers={"content-type": "image/jpeg"})

    layer = LayerConfig(
        id="demo",
        name="Demo",
        format="jpg",
        levels={"min": 0, "max": 3},
        source={"url_template": "https://example.test/{z}/{y}/{x}.jpg"},
    )
    provider = RemoteTileProvider(retries=2, retry_backoff_s=0)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    tile = asyncio.run(provider.get_tile(layer, 0, 0, 0))
    assert tile.origin == "remote" and hits["n"] == 2
    assert tile.content == GOOD_JPEG


def test_remote_persistent_5xx_is_not_found():
    """After retries, a persistent 500 becomes TileNotFoundError (so the
    service can fall back to a parent) rather than a 502. Further calls
    inside the failure TTL do not hit the network again."""
    import httpx

    from app.providers.remote import RemoteTileProvider

    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        return httpx.Response(500, text="nope")

    layer = LayerConfig(
        id="demo",
        name="Demo",
        format="jpg",
        levels={"min": 0, "max": 3},
        source={"url_template": "https://example.test/{z}/{y}/{x}.jpg"},
    )
    provider = RemoteTileProvider(retries=2, retry_backoff_s=0)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TileNotFoundError):
        asyncio.run(provider.get_tile(layer, 0, 0, 0))
    assert hits["n"] == 3  # initial + 2 retries
    with pytest.raises(TileNotFoundError):
        asyncio.run(provider.get_tile(layer, 0, 0, 0))
    assert hits["n"] == 3



def test_remote_rejects_content_length_mismatch():
    """A 200 whose body is shorter than Content-Length is retried, then
    treated as missing so the service can fall back to a parent."""
    import httpx

    from app.providers.remote import RemoteTileProvider

    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        # httpx would normally not let us lie about Content-Length on a
        # real socket; MockTransport delivers exactly the body we set,
        # and we stamp a larger Content-Length to simulate a cut-off
        # download.
        return httpx.Response(
            200,
            content=GOOD_JPEG[:50],
            headers={"content-type": "image/jpeg", "content-length": str(len(GOOD_JPEG))},
        )

    layer = LayerConfig(
        id="demo",
        name="Demo",
        format="jpg",
        levels={"min": 0, "max": 3},
        source={"url_template": "https://example.test/{z}/{y}/{x}.jpg"},
    )
    provider = RemoteTileProvider(retries=2, retry_backoff_s=0)
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(TileNotFoundError):
        asyncio.run(provider.get_tile(layer, 0, 0, 0))
    assert hits["n"] == 3
