"""Remote provider: downloads tiles from Earth-side APIs (Earth mode).

It uses each layer's ``source.url_template`` from layers.yaml, so it works
with any XYZ/WMTS-REST service (NASA Mars Trek, Esri, USGS...) without
code changes.
"""

from __future__ import annotations

import httpx

from app.models.layer import LayerConfig
from app.providers.base import (
    Tile,
    TileNotFoundError,
    TileProvider,
    TileProviderError,
    sniff_media_type,
)


class RemoteTileProvider(TileProvider):
    name = "remote"

    def __init__(self, timeout_s: float = 15.0, user_agent: str = "Arturo/0.1"):
        self._client = httpx.AsyncClient(
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": user_agent},
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )

    async def get_tile(self, layer: LayerConfig, z: int, x: int, y: int) -> Tile:
        template = layer.source.url_template
        if not template:
            raise TileNotFoundError(f"Layer '{layer.id}' has no remote source")
        url = template.format(z=z, x=x, y=y)

        try:
            resp = await self._client.get(url)
        except httpx.HTTPError as exc:
            raise TileProviderError(f"Error contacting {url}: {exc}") from exc

        # Mars Trek answers 404 outside its levels; Esri answers 404 where
        # there is no coverage and 400 above its maximum level.
        if resp.status_code in (400, 404):
            raise TileNotFoundError(f"{url} -> HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise TileProviderError(f"{url} -> HTTP {resp.status_code}")

        content = resp.content
        media_type = sniff_media_type(content, default="")
        if not media_type.startswith("image/"):
            raise TileProviderError(f"{url} did not return an image")
        return Tile(content=content, media_type=media_type, origin=self.name)

    async def close(self) -> None:
        await self._client.aclose()
