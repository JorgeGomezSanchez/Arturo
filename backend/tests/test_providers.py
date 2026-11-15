"""Unit tests of the provider layer (no network)."""

from __future__ import annotations

import asyncio

import pytest

from app.models.layer import LayerConfig
from app.providers.base import Tile, TileNotFoundError, TileProvider
from app.providers.cached import CachedTileProvider
from app.providers.local import LocalTileProvider

LAYER = LayerConfig(id="demo", name="Demo", format="jpg", levels={"min": 0, "max": 3})


class FakeRemote(TileProvider):
    name = "fake"

    def __init__(self):
        self.calls = 0

    async def get_tile(self, layer, z, x, y):
        self.calls += 1
        if (z, x, y) == (0, 0, 0):
            return Tile(b"\xff\xd8fake-jpeg", "image/jpeg", "fake")
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
        return httpx.Response(200, content=b"\xff\xd8fake-jpeg", headers={"content-type": "image/jpeg"})

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
    assert tile.content.startswith(b"\xff\xd8")


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

