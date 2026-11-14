"""Build the numeric rasters used by ``GET /api/point``.

The map tiles are coloured pictures: you cannot read an elevation or a
thermal inertia back from a PNG. The point query therefore reads REAL
numeric grids, downloaded once from the archives below and converted
into small, tiled, compressed GeoTIFFs under ``backend/data/rasters/``.

All outputs share one convention: geographic lat/lon on the Mars 2000
sphere (R = 3,396,190 m), planetocentric latitude, east-positive
longitude in -180..180, north-up. Values are stored as integers where
possible (with a scale factor written in the GeoTIFF tags and in
``app/catalog/rasters.yaml``) to keep the files small.

| Output                              | Source (numeric)                                   | Grid      |
|-------------------------------------|----------------------------------------------------|-----------|
| mola_megdr_16ppd_elevation.tif      | MGS MOLA MEGDR, PDS Geosciences (megt90n000eb.img) | 16 ppd    |
| tes_ti_night_2007_20ppd.tif         | Putzig & Mellon 2007 TES thermal inertia, PDS      | 20 ppd    |
| tes_ti_day_2007_20ppd.tif (opt.)    | idem, dayside map (``--only ti_day``)              | 20 ppd    |
| tes_albedo_8ppd.tif                 | TES Lambert albedo mosaic, USGS Astropedia         | 8 ppd     |
| tes_dci_16ppd.tif                   | TES dust cover index (Ruff & Christensen), ASU     | 16 ppd    |
| tes_minerals_4ppd.tif               | TES mineral maps (Bandfield 2002), ASU TES          | 4 ppd     |
| sim3292_units_16ppd.tif + .json     | USGS SIM 3292 geologic units (shapefile), USGS     | 16 ppd    |
| zones/<zone>_hrsc_mola_200m.tif     | HRSC+MOLA blended DEM v2, USGS (HTTP range reads)  | 200 m/px  |

Usage (from ``backend/``, venv active, ``pip install -r
requirements-dev.txt`` for pyshp)::

    python -m scripts.build_rasters                     # everything (global grids + default zones)
    python -m scripts.build_rasters --only elevation,ti # a subset
    python -m scripts.build_rasters --zones gale,jezero,arcadia
    python -m scripts.build_rasters --zones none        # skip the 200 m crops

Downloads are cached in ``data/rasters/_downloads/`` (git-ignored), so a
re-run only rebuilds. The big SIM 3292 database (~800 MB zip) is NOT
downloaded: only the shapefile members (~65 MB) are fetched with HTTP
range requests. The 200 m zone crops are read straight from the 11 GB
USGS GeoTIFF with HTTP range requests too (Gale ~190 MB of transfer).
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

import httpx
import numpy as np
import rasterio
import yaml
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.windows import Window, from_bounds

from app.core.config import BACKEND_DIR, get_settings

MARS_CRS = CRS.from_wkt(
    'GEOGCS["GCS_Mars_2000_Sphere",DATUM["Mars_2000_(Sphere)",'
    'SPHEROID["Mars_2000_Sphere_IAU_IAG",3396190,0]],PRIMEM["Reference_Meridian",0],'
    'UNIT["degree",0.0174532925199433]]'
)

URLS = {
    "megdr": "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/megt90n000eb.img",
    "ti_zip": "https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001.zip",
    "albedo": "https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif",
    "dci": "https://mars.asu.edu/~ruff/DCI/dci_lo_ice_dust_16ppd_shifted.pds",
    "minerals": "https://tes.mars.asu.edu/mineral_map/TES_mineral_maps_4_ppd.envi",
    "sim3292_zip": "https://pubs.usgs.gov/sim/3292/downloads/sim3292_database.zip",
    "hrsc_mola": "https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif",
}

# TES mineral cube (13 float32 bands, big-endian, -1 = no data). Only the
# bands whose identity we verified against well-known regions are kept:
#   band 3  plagioclase           (highest in Syrtis Major, as published)
#   band 6  high-Ca pyroxene      (high in Syrtis, low in Acidalia)
#   band 8  hematite              (only high at Meridiani Planum)
#   band 11 sheet silicates/glass (highest in Acidalia / northern plains)
#   band 12 surface dust          (~0.85 on Tharsis, ~0.5 Arabia)
# The other bands could not be identified unambiguously and are skipped.
MINERAL_BANDS = [
    (3, "plagioclase"),
    (6, "high_ca_pyroxene"),
    (8, "hematite"),
    (11, "sheet_silicates_glass"),
    (12, "surface_dust"),
]

UA = {"User-Agent": "Arturo/0.3 (NASA Space Apps 2026; build_rasters.py)"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def download(url: str, dest: Path) -> Path:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  cached  {dest.name}")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  get     {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, headers=UA, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)
    tmp.rename(dest)
    return dest


class HttpRangeFile(io.RawIOBase):
    """Seekable read-only file over HTTP range requests (for zipfile)."""

    def __init__(self, url: str):
        self.url = url
        self.client = httpx.Client(headers=UA, follow_redirects=True, timeout=120)
        self.size = int(self.client.head(url).headers["content-length"])
        self.pos = 0

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=io.SEEK_SET):
        self.pos = {io.SEEK_SET: offset, io.SEEK_CUR: self.pos + offset, io.SEEK_END: self.size + offset}[whence]
        return self.pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        data = self.client.get(self.url, headers={"Range": f"bytes={self.pos}-{end}"}).content
        self.pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def write_tif(path: Path, data: np.ndarray, ppd: float | None = None, transform=None, nodata=None,
              tags: dict | None = None, band_names: list[str] | None = None) -> None:
    """Tiled, DEFLATE-compressed GeoTIFF on the Mars 2000 sphere."""
    if data.ndim == 2:
        data = data[np.newaxis]
    count, height, width = data.shape
    if transform is None:
        transform = from_origin(-180.0, 90.0, 1.0 / ppd, 1.0 / ppd)
    predictor = 3 if data.dtype.kind == "f" else 2
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w", driver="GTiff", width=width, height=height, count=count, dtype=data.dtype,
        crs=MARS_CRS, transform=transform, nodata=nodata, tiled=True, blockxsize=256, blockysize=256,
        compress="deflate", zlevel=9, predictor=predictor,
    ) as dst:
        dst.write(data)
        if tags:
            dst.update_tags(**{k: str(v) for k, v in tags.items()})
        for i, name in enumerate(band_names or [], start=1):
            dst.set_band_description(i, name)
    print(f"  wrote   {path.relative_to(BACKEND_DIR)}  ({path.stat().st_size / 1e6:.1f} MB)")


def to_uint16(values: np.ndarray, scale: float, valid: np.ndarray) -> np.ndarray:
    """Store a float field as uint16 = round(value / scale); 65535 = no data."""
    out = np.full(values.shape, 65535, dtype=np.uint16)
    out[valid] = np.clip(np.round(values[valid] / scale), 0, 65534).astype(np.uint16)
    return out


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------
def build_elevation(dl: Path, out: Path) -> None:
    print("MOLA MEGDR 16 ppd elevation")
    src = download(URLS["megdr"], dl / "megt90n000eb.img")
    # 2880 x 5760 big-endian int16, metres above the MOLA areoid,
    # longitude 0..360 E -> roll by half a width to get -180..180.
    a = np.fromfile(src, dtype=">i2").reshape(2880, 5760)
    a = np.roll(a, 2880, axis=1).astype(np.int16)
    write_tif(out / "mola_megdr_16ppd_elevation.tif", a, ppd=16,
              tags={"units": "m", "datum": "MOLA areoid (IAU 2000)", "source": URLS["megdr"]})


def _build_ti_side(dl: Path, out: Path, side: str) -> None:
    print(f"TES thermal inertia 2007 (Putzig & Mellon), {side}side, 20 ppd")
    z = zipfile.ZipFile(download(URLS["ti_zip"], dl / "mgst_9001.zip"))
    raw = z.read(f"mgst_9001/data/global_ti_{side}_2007.img")
    a = np.frombuffer(raw, dtype=">i2").reshape(3600, 7200).astype(np.int16)  # 0 = null
    write_tif(out / f"tes_ti_{side}_2007_20ppd.tif", a, ppd=20, nodata=0,
              tags={"units": "J m-2 K-1 s-1/2", "source": URLS["ti_zip"]})


def build_ti(dl: Path, out: Path) -> None:
    """Nightside map: the standard one (committed)."""
    _build_ti_side(dl, out, "night")


def build_ti_day(dl: Path, out: Path) -> None:
    """Dayside map: optional (29 MB, not committed); shown when present."""
    _build_ti_side(dl, out, "day")


def build_albedo(dl: Path, out: Path) -> None:
    print("TES Lambert albedo, 8 ppd")
    src = download(URLS["albedo"], dl / "tes_albedo_7410m.tif")
    with rasterio.open(src) as d:
        a = d.read(1)
        # The mosaic is 8-bit quantised between 0.06 and 0.32: the lowest
        # step (0.06) is the fill used poleward of ~87° and in gaps, and
        # 0.32 is a saturation ceiling (polar ice is brighter).
        valid = (a > 0.0605) & (a < 1)
    write_tif(out / "tes_albedo_8ppd.tif", to_uint16(a, 1e-4, valid), ppd=8, nodata=65535,
              tags={"scale_factor": 1e-4, "units": "1", "source": URLS["albedo"]})


def build_dci(dl: Path, out: Path) -> None:
    print("TES dust cover index, 16 ppd")
    src = download(URLS["dci"], dl / "dci_16ppd.pds")
    # PDS QUBE: 1024-byte label, then 5760 x 2880 little-endian float32.
    a = np.fromfile(src, dtype="<f4", offset=1024).reshape(2880, 5760)
    valid = a > 0.8501  # 0.85 is the fill value of the map
    # Real values are 0.85..0.99: store uint8 = (dci - 0.85) / 0.0006
    # (steps of 0.0006, far below the index's meaningful differences of
    # ~0.01); 255 = no data. Halves the file size.
    q = np.full(a.shape, 255, dtype=np.uint8)
    q[valid] = np.clip(np.round((a[valid] - 0.85) / 0.0006), 0, 254).astype(np.uint8)
    write_tif(out / "tes_dci_16ppd.tif", q, ppd=16, nodata=255,
              tags={"scale_factor": 0.0006, "add_offset": 0.85, "units": "1 (emissivity 1350-1400 cm-1)",
                    "source": URLS["dci"]})


def build_minerals(dl: Path, out: Path) -> None:
    print("TES mineral maps (Bandfield 2002), 4 ppd")
    src = download(URLS["minerals"], dl / "TES_mineral_maps_4_ppd.envi")
    cube = np.fromfile(src, dtype=">f4").reshape(13, 720, 1440)  # lon -180..180
    bands = []
    for idx, _name in MINERAL_BANDS:
        b = cube[idx - 1]
        bands.append(to_uint16(b, 1e-4, (b >= 0) & (b <= 1)))
    write_tif(out / "tes_minerals_4ppd.tif", np.stack(bands), ppd=4, nodata=65535,
              tags={"scale_factor": 1e-4, "units": "areal fraction (0-1)", "source": URLS["minerals"]},
              band_names=[n for _, n in MINERAL_BANDS])


def build_geology(dl: Path, out: Path, ppd: int = 16) -> None:
    import shapefile  # pyshp (requirements-dev.txt)
    from rasterio.features import rasterize

    print(f"USGS SIM 3292 geologic units, rasterised at {ppd} ppd")
    base = "SIM3292_MarsGlobalGeologicGIS_20M/SIM3292_Shapefiles/SIM3292_Global_Geology"
    cache = dl / "sim3292"
    cache.mkdir(parents=True, exist_ok=True)
    if not (cache / "geology.shp").exists():
        print("  get     shapefile members of", URLS["sim3292_zip"], "(HTTP range requests)")
        z = zipfile.ZipFile(io.BufferedReader(HttpRangeFile(URLS["sim3292_zip"]), buffer_size=1 << 22))
        for ext in ("shp", "shx", "dbf", "prj"):
            (cache / f"geology.{ext}").write_bytes(z.read(f"{base}.{ext}"))
    r = shapefile.Reader(str(cache / "geology"))
    units: dict[str, dict] = {}
    shapes = []
    for sr in r.iterShapeRecords():
        code, desc = sr.record["Unit"].strip(), sr.record["UnitDesc"].strip()
        if code not in units:
            units[code] = {"code": code, "name": desc}
        shapes.append((sr.shape.__geo_interface__, code))
    codes = sorted(units)
    index = {c: i + 1 for i, c in enumerate(codes)}  # 0 = no unit
    a = rasterize(
        ((geom, index[c]) for geom, c in shapes),
        out_shape=(180 * ppd, 360 * ppd),
        transform=from_origin(-180.0, 90.0, 1.0 / ppd, 1.0 / ppd),
        fill=0, dtype="uint8",
    )
    write_tif(out / f"sim3292_units_{ppd}ppd.tif", a, ppd=ppd, nodata=0,
              tags={"source": URLS["sim3292_zip"], "legend": f"sim3292_units_{ppd}ppd.json"})
    legend = {"source": "Tanaka et al. 2014, Geologic map of Mars, USGS SIM 3292",
              "units": [{"value": index[c], **units[c]} for c in codes]}
    (out / f"sim3292_units_{ppd}ppd.json").write_text(json.dumps(legend, indent=1) + "\n")
    print(f"  {len(codes)} units")


def build_zone(zone: dict, out: Path) -> None:
    b = zone["bounds"]
    print(f"HRSC+MOLA 200 m crop for zone {zone['id']} ({b})")
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_HTTP_MULTIRANGE="YES"):
        with rasterio.open("/vsicurl/" + URLS["hrsc_mola"]) as src:
            win = from_bounds(b["west"], b["south"], b["east"], b["north"], src.transform)
            win = Window(int(win.col_off), int(win.row_off), int(np.ceil(win.width)), int(np.ceil(win.height)))
            a = src.read(1, window=win)
            transform = src.window_transform(win)
    write_tif(out / "zones" / f"{zone['id']}_hrsc_mola_200m.tif", a, transform=transform, nodata=-32768,
              tags={"units": "m", "datum": "MOLA areoid", "source": URLS["hrsc_mola"], "zone": zone["id"]})


BUILDERS = {
    "elevation": build_elevation,
    "ti": build_ti,
    "ti_day": build_ti_day,
    "albedo": build_albedo,
    "dci": build_dci,
    "minerals": build_minerals,
    "geology": build_geology,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, default=get_settings().rasters_dir, help="output folder")
    p.add_argument("--only", default="all", help="comma list of: " + ",".join(BUILDERS) + " (default all)")
    p.add_argument("--zones", default="gale,jezero",
                   help="zone ids from map.yaml for 200 m DEM crops, 'all' or 'none' (default gale,jezero)")
    args = p.parse_args(argv)
    out: Path = args.out
    dl = out / "_downloads"

    default = [n for n in BUILDERS if n != "ti_day"]  # ti_day is optional (big)
    names = default if args.only == "all" else [n.strip() for n in args.only.split(",") if n.strip()]
    for n in names:
        if n not in BUILDERS:
            p.error(f"unknown dataset {n!r}")
        BUILDERS[n](dl, out)

    if args.zones != "none":
        zones = yaml.safe_load(get_settings().map_file.read_text())["zones"]
        wanted = None if args.zones == "all" else {z.strip() for z in args.zones.split(",")}
        for z in zones:
            if wanted is None or z["id"] in wanted:
                build_zone(z, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
