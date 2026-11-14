"""Shared fixtures. Tests NEVER touch the network: they run the backend
in Mars mode (DATA_SOURCE=local) over a temporary tile folder."""

from __future__ import annotations

import importlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image


def make_image(fmt: str, color=(200, 100, 50), size=256, black_square=False) -> bytes:
    img = Image.new("RGB", (size, size), color)
    if black_square:
        img.paste((0, 0, 0), (0, 0, size // 2, size // 2))
    buf = io.BytesIO()
    img.save(buf, format="PNG" if fmt == "png" else "JPEG")
    return buf.getvalue()


@pytest.fixture
def tiles_dir(tmp_path: Path) -> Path:
    root = tmp_path / "tiles"
    # A Viking tile (no transform) and a CTX tile with a black gap.
    viking = root / "viking_mdim21_color" / "0" / "1"
    viking.mkdir(parents=True)
    (viking / "0.jpg").write_bytes(make_image("jpg"))
    ctx = root / "ctx_global_5m" / "3" / "4"
    ctx.mkdir(parents=True)
    (ctx / "2.png").write_bytes(make_image("png", size=512, black_square=True))
    return root


@pytest.fixture
def client(tiles_dir: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATA_SOURCE", "local")
    monkeypatch.setenv("LOCAL_TILES_DIR", str(tiles_dir))

    from app.catalog import map_config, registry
    from app.core import config

    config.get_settings.cache_clear()
    registry.get_registry.cache_clear()
    map_config._raw.cache_clear()

    import app.main

    importlib.reload(app.main)
    with TestClient(app.main.app) as c:
        yield c
    config.get_settings.cache_clear()
