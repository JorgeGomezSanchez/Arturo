# Numeric rasters for point queries (`GET /api/point`)

These GeoTIFFs hold **real numbers** (metres, J m⁻² K⁻¹ s⁻½, albedo…),
unlike the map tiles, which are coloured pictures. They are built by
[`scripts/build_rasters.py`](../../scripts/build_rasters.py) and read by
the backend with rasterio windowed reads (only a few pixels per query).

All files: geographic lat/lon on the Mars 2000 sphere (R = 3,396,190 m),
planetocentric latitude, east-positive longitude −180…180, north-up,
256×256 tiles, DEFLATE. Integer files carry a scale (and offset) that the
backend applies; it is listed in `app/catalog/rasters.yaml`.

## Committed (≈ 61 MB, works offline out of the box)

| File | Content | Grid | Values | Source |
|---|---|---|---|---|
| `mola_megdr_16ppd_elevation.tif` | Elevation above the MOLA areoid | 16 px/° (~3.7 km) | int16, m | [MGS MOLA MEGDR, PDS Geosciences](https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/) (Smith et al. 2003) |
| `zones/gale_hrsc_mola_200m.tif`, `zones/jezero_hrsc_mola_200m.tif` | Elevation, detail zones | 200 m | int16, m (−32768 = no data) | [HRSC+MOLA blended DEM v2, USGS](https://astrogeology.usgs.gov/search/map/mars_mgs_mola_mex_hrsc_blended_dem_global_200m) (Fergason et al. 2018) |
| `tes_ti_night_2007_20ppd.tif` | Thermal inertia (nightside) | 20 px/° (~3 km) | int16, J m⁻² K⁻¹ s⁻½ (0 = no data) | [MGS-M-TES-5-TIMAP-V1.0, PDS](https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html) (Putzig & Mellon 2007) |
| `tes_albedo_8ppd.tif` | Lambert albedo | 8 px/° (~7.4 km) | uint16 × 1e-4 (65535 = no data) | [TES albedo mosaic, USGS Astropedia](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif) (Christensen et al. 2001) |
| `tes_dci_16ppd.tif` | Dust cover index | 16 px/° (~3.7 km) | uint8 × 0.0006 + 0.85 (255 = no data) | [ASU, S. Ruff](https://mars.asu.edu/~ruff/DCI/dci.html) (Ruff & Christensen 2002) |
| `tes_minerals_4ppd.tif` | 5 bands: plagioclase, high-Ca pyroxene, hematite, sheet silicates/high-Si glass, surface dust | 4 px/° (~15 km) | uint16 × 1e-4, areal fraction | [ASU TES mineral maps](https://tes.mars.asu.edu/products/index.html) (Bandfield 2002) |
| `sim3292_units_16ppd.tif` + `.json` | Geologic unit index + legend (44 units) | 16 px/° | uint8 (0 = none) | [USGS SIM 3292](https://pubs.usgs.gov/sim/3292/) (Tanaka et al. 2014) |

## Optional (built locally, git-ignored)

| File | How | Size |
|---|---|---|
| `tes_ti_day_2007_20ppd.tif` | `python -m scripts.build_rasters --only ti_day --zones none` | 29 MB |
| `zones/<zone>_hrsc_mola_200m.tif` for other zones | `python -m scripts.build_rasters --only elevation --zones arcadia,deuteronilus` | 5–15 MB each (hundreds of MB of HTTP range transfer) |

In Earth mode (`DATA_SOURCE=remote`), points outside the local 200 m
crops read the same 200 m DEM live from USGS (a few hundred kB per
query), unless `POINT_REMOTE_DEM=false`. In Mars mode only these local
files are used.

## Notes on the mineral bands

The original TES cube has 13 bands without band names in its header.
Only the five bands whose identity could be verified against well-known
places were kept: hematite peaks only at Meridiani Planum; plagioclase
and high-Ca pyroxene are highest in Syrtis Major; sheet silicates/high-Si
glass is highest in Acidalia; surface dust is ≈0.85 on Tharsis.
