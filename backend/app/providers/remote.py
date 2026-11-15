"""Remote provider: downloads tiles from Earth-side APIs (Earth mode).

It uses each layer's ``source.url_template`` from layers.yaml, so it works
with any XYZ/WMTS-REST service (NASA Mars Trek, Esri, USGS...) without
code changes.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from app.models.layer import LayerConfig
from app.providers.base import (
    Tile,
    TileNotFoundError,
    TileProvider,
    TileProviderError,
    sniff_media_type,
)

log = logging.getLogger(__name__)

# Retry these; they are often transient on the Esri / Trek CDNs.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}



def _body_matches_content_length(resp: httpx.Response) -> bool:
    """False if the server advertised a length and we got fewer bytes.

    A dropped connection can otherwise yield a 200 whose body is a
    truncated PNG/JPEG that we would have cached as if it were complete.
    """
    raw = resp.headers.get("Content-Length")
    if raw is None:
        return True
    try:
        expected = int(raw)
    except ValueError:
        return True
    return expected == len(resp.content)


class RemoteTileProvider(TileProvider):
    name = "remote"

    def __init__(
        self,
        timeout_s: float = 15.0,
        user_agent: str = "Arturo/0.1",
        retries: int = 2,
        retry_backoff_s: float = 0.25,
    ):
        self._retries = retries
        self._retry_backoff_s = retry_backoff_s
        # URLs that exhausted retries on a 5xx: skip them for a while so
        # a viewport full of persistent Esri 500s is not retried on every
        # pan. The tile service then falls back to a parent immediately.
        self._failure_ttl_s = 600.0
        self._failed_until: dict[str, float] = {}
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

        now = time.monotonic()
        until = self._failed_until.get(url)
        if until is not None and until > now:
            raise TileNotFoundError(f"{url} recently failed; not retrying yet")
        if until is not None:
            self._failed_until.pop(url, None)

        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.get(url)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self._retries:
                    log.warning("network error %s (attempt %s): %s", url, attempt + 1, exc)
                    await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    continue
                raise TileProviderError(f"Error contacting {url}: {exc}") from exc

            # Mars Trek answers 404 outside its levels; Esri answers 404
            # where there is no coverage and 400 above its maximum level.
            if resp.status_code in (400, 404):
                raise TileNotFoundError(f"{url} -> HTTP {resp.status_code}")

            if resp.status_code in _RETRYABLE_STATUS:
                last_error = TileProviderError(f"{url} -> HTTP {resp.status_code}")
                if attempt < self._retries:
                    log.warning(
                        "%s -> HTTP %s (attempt %s), retrying",
                        url, resp.status_code, attempt + 1,
                    )
                    await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    continue
                # After retries, raise TileNotFoundError so TileService can
                # fall back to a parent tile instead of returning 502.
                log.warning("%s -> HTTP %s after %s attempts", url, resp.status_code, attempt + 1)
                self._failed_until[url] = time.monotonic() + self._failure_ttl_s
                raise TileNotFoundError(f"{url} -> HTTP {resp.status_code}")

            if resp.status_code != 200:
                raise TileProviderError(f"{url} -> HTTP {resp.status_code}")

            content = resp.content
            if not _body_matches_content_length(resp):
                log.warning(
                    "%s Content-Length mismatch (header=%s, body=%s, attempt %s)",
                    url, resp.headers.get("Content-Length"), len(content), attempt + 1,
                )
                if attempt < self._retries:
                    await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    continue
                raise TileNotFoundError(
                    f"{url} was truncated in transit "
                    f"(Content-Length {resp.headers.get('Content-Length')}, "
                    f"got {len(content)} bytes)"
                )

            media_type = sniff_media_type(content, default="")
            if not media_type.startswith("image/"):
                # A 200 HTML error page: retry once, then treat as missing.
                last_error = TileProviderError(f"{url} did not return an image")
                if attempt < self._retries:
                    await asyncio.sleep(self._retry_backoff_s * (2 ** attempt))
                    continue
                raise TileNotFoundError(f"{url} did not return an image")
            return Tile(content=content, media_type=media_type, origin=self.name)

        # Unreachable, but keeps type-checkers happy.
        raise TileProviderError(f"Error contacting {url}: {last_error}")

    async def close(self) -> None:
        await self._client.aclose()
