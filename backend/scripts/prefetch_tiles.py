"""Build an offline tile pack (for Mars mode / demos without Internet).

Downloads every tile of a layer for a range of levels (optionally only
inside a bounding box) and stores it with the layout that
``LocalTileProvider`` reads: ``{out}/{layer}/{z}/{x}/{y}.{ext}``.
Tiles that are already present are skipped, so it can be re-run safely.

Usage (from the ``backend/`` folder, with the venv active)::

    # Whole planet, Viking colour mosaic, levels 0-4 (~680 tiles, ~35 MB)
    python -m scripts.prefetch_tiles --layer viking_mdim21_color --max-level 4

    # EVERY layer of the catalog, levels 0-3 (global offline overview)
    python -m scripts.prefetch_tiles --layer all --max-level 3

    # Gale crater in CTX detail, levels 6-10
    python -m scripts.prefetch_tiles --layer ctx_global_5m \
        --min-level 6 --max-level 10 --bbox=-6.9,136.3,-3.9,139.3

Then set ``DATA_SOURCE=local`` (and ``LOCAL_TILES_DIR`` if you used a
different --out) and the app runs without network.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import sys
from pathlib import Path
from typing import Iterator, Optional

from app.catalog.registry import get_registry
from app.core.config import get_settings
from app.models.layer import LayerConfig
from app.providers.base import TileNotFoundError, TileProviderError
from app.providers.cached import CachedTileProvider
from app.providers.remote import RemoteTileProvider

BBox = tuple[float, float, float, float]  # south, west, north, east


def tiles_in(layer: LayerConfig, z: int, bbox: Optional[BBox]) -> Iterator[tuple[int, int]]:
    """(x, y) of every tile of level z intersecting the bbox."""
    cols, rows = 2 * 2**z, 2**z
    deg = 180.0 / 2**z  # degrees covered by one tile (both axes)
    if bbox is None:
        xs, ys = range(cols), range(rows)
    else:
        south, west, north, east = bbox
        xs = range(max(0, math.floor((west + 180) / deg)), min(cols, math.ceil((east + 180) / deg)))
        ys = range(max(0, math.floor((90 - north) / deg)), min(rows, math.ceil((90 - south) / deg)))
    for x in xs:
        for y in ys:
            yield x, y


async def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--layer", required=True,
                        help="Layer id from layers.yaml, comma separated ids, or 'all'")
    parser.add_argument("--min-level", type=int, default=None)
    parser.add_argument("--max-level", type=int, required=True)
    parser.add_argument("--bbox", default=None, help="south,west,north,east in degrees (use --bbox=... when it starts with a minus sign)")
    parser.add_argument("--out", type=Path, default=settings.local_tiles_dir)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()

    registry = get_registry()
    if args.layer == "all":
        layers = registry.all()
    else:
        layers = [registry.get(i.strip()) for i in args.layer.split(",")]
    bbox: Optional[BBox] = tuple(map(float, args.bbox.split(","))) if args.bbox else None  # type: ignore

    jobs = []
    for layer in layers:
        min_level = layer.levels.min if args.min_level is None else max(args.min_level, layer.levels.min)
        max_level = min(args.max_level, layer.levels.max)
        layer_jobs = [(layer, z, x, y) for z in range(min_level, max_level + 1) for x, y in tiles_in(layer, z, bbox)]
        print(f"{layer.id}: {len(layer_jobs)} tiles, levels {min_level}-{max_level} -> {args.out}")
        jobs += layer_jobs

    provider = CachedTileProvider(
        RemoteTileProvider(settings.remote_timeout_s, settings.remote_user_agent), args.out
    )
    sem = asyncio.Semaphore(args.concurrency)
    stats = {"ok": 0, "missing": 0, "error": 0}

    async def fetch(layer: LayerConfig, z: int, x: int, y: int) -> None:
        async with sem:
            try:
                await provider.get_tile(layer, z, x, y)
                stats["ok"] += 1
            except TileNotFoundError:
                stats["missing"] += 1
            except TileProviderError as exc:
                stats["error"] += 1
                print(f"  ! {layer.id} {z}/{x}/{y}: {exc}", file=sys.stderr)
        done = sum(stats.values())
        if done % 100 == 0 or done == len(jobs):
            print(f"  {done}/{len(jobs)} {stats}")

    try:
        await asyncio.gather(*(fetch(*job) for job in jobs))
    finally:
        await provider.close()
    print("Done:", stats)
    return 1 if stats["error"] else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
