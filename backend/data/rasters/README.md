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
| `mola_megdr_16ppd_elevation.tif` | Elevation above the MOLA areoid | 16 px/° (~3.7 km) | int16, m | [MGS MOLA MEGDR `megt90n000eb.img`, PDS Geosciences](https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/mgsl_300x/meg016/megt90n000eb.img) (Smith et al. 2003) |
| `zones/gale_hrsc_mola_200m.tif`, `zones/jezero_hrsc_mola_200m.tif` | Elevation, detail zones | 200 m | int16, m (−32768 = no data) | [HRSC+MOLA blended DEM v2, USGS](https://planetarymaps.usgs.gov/mosaic/Mars/HRSC_MOLA_Blend/Mars_HRSC_MOLA_BlendDEM_Global_200mp_v2.tif) (11 GB GeoTIFF; only the zone windows are fetched) (Fergason et al. 2018) |
| `tes_ti_night_2007_20ppd.tif` | Thermal inertia (nightside) | 20 px/° (~3 km) | int16, J m⁻² K⁻¹ s⁻½ (0 = no data) | [MGS-M-TES-5-TIMAP-V1.0 `mgst_9001.zip`, PDS](https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001.zip) (Putzig & Mellon 2007) |
| `tes_albedo_8ppd.tif` | Lambert albedo | 8 px/° (~7.4 km) | uint16 × 1e-4 (65535 = no data, incl. the 0.06 fill poleward of ~87°; 0.32 is the mosaic's ceiling) | [TES albedo mosaic, USGS Astropedia](https://planetarymaps.usgs.gov/mosaic/Mars_MGS_TES_Albedo_mosaic_global_7410m.tif) (Christensen et al. 2001) |
| `tes_dci_16ppd.tif` | Dust cover index | 16 px/° (~3.7 km) | uint8 × 0.0006 + 0.85 (255 = no data) | [ASU, S. Ruff `dci_lo_ice_dust_16ppd_shifted.pds`](https://mars.asu.edu/~ruff/DCI/dci_lo_ice_dust_16ppd_shifted.pds) (Ruff & Christensen 2002) |
| `tes_minerals_4ppd.tif` | 5 bands: plagioclase, high-Ca pyroxene, hematite, sheet silicates/high-Si glass, surface dust | 4 px/° (~15 km) | uint16 × 1e-4, areal fraction | [ASU TES mineral maps `TES_mineral_maps_4_ppd.envi`](https://tes.mars.asu.edu/mineral_map/TES_mineral_maps_4_ppd.envi) (Bandfield 2002) |
| `sim3292_units_16ppd.tif` + `.json` (0.4 MB) | Geologic unit index + legend (44 units) | 16 px/° | uint8 (0 = none) | [USGS SIM 3292 database](https://pubs.usgs.gov/sim/3292/downloads/sim3292_database.zip) (only the shapefile members are range-read from the 800 MB zip) (Tanaka et al. 2014) |

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

## Sizes

| File | Size | In git |
|---|---|---|
| `mola_megdr_16ppd_elevation.tif` | 18 MB | yes |
| `tes_ti_night_2007_20ppd.tif` | 25 MB | yes |
| `tes_dci_16ppd.tif` | 8.9 MB | yes |
| `tes_minerals_4ppd.tif` | 5.5 MB | yes |
| `tes_albedo_8ppd.tif` | 2.9 MB | yes |
| `zones/gale_hrsc_mola_200m.tif` / `zones/jezero_hrsc_mola_200m.tif` | 0.73 / 0.08 MB | yes |
| `sim3292_units_16ppd.tif` + `.json` | 0.37 MB | yes |
| `tes_ti_day_2007_20ppd.tif` | 29 MB | no (optional) |
| `_downloads/` (original files) | ~290 MB | no (cache of the build script) |

No Git LFS: everything committed is a plain file under 25 MB.
