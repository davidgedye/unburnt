# Pipeline Validation Slice — WA × 2024 (run 2026-07-23)

End-to-end validation of the vectorize-severity pipeline on one state × one year, per
`recommendation.md` next-steps §3. **Verdict: pipeline works, is fast, and the rendered
result matches the product vision** (see `screenshots/wa_retreat_z11.png`). One major data
finding changes the v1 plan — see "Findings" below.

## What ran (all local, WSL2 laptop, no sudo)

Toolchain (user-space): micromamba env at `~/tools/envs/gis` (GDAL 3.13.1, tippecanoe
v2.79.0 from conda-forge), `pmtiles` 1.31.2 static binary at `~/tools/bin`. Note: the env
isn't "activated" — set `PROJ_DATA=~/tools/envs/gis/share/proj` and
`GDAL_DATA=~/tools/envs/gis/share/gdal` or PROJ dies cryptically.

Data (in `pipeline/data/`, ~1.4 GB total):
- `mtbs_CONUS_2024.zip` (4.2 MB!) / `mtbs_CONUS_2023.zip` — annual thematic severity
  mosaics via **ScienceBase API** (parent item `5e91dee782ce172707f02cdd`, "ver. 12.0,
  April 2025"; one child item per year 1984–2024 with the zip as an attached file). The
  old `edcintl.cr.usgs.gov/...MTBS_BSmosaics/...` URL pattern is dead; the direct-download
  UI moved to burnseverity.cr.usgs.gov. ScienceBase JSON API is the scriptable path.
- `mtbs_perimeter_data.zip` (390 MB, 30,929 fires, updated **July 2026**) — the old
  edcintl URL still works for this one.
- `cb_2023_us_state_500k.zip` — Census state boundaries for the WA cutline.

Pipeline steps and timings (WA clip = 19,739 × 14,611 px):
1. `gdalwarp -cutline (STUSPS='WA') -crop_to_cutline` → `wa_2024.tif` — seconds.
2. `gdal_sieve.py -nomask -st 8` (drops speckles <8 px ≈ 1.8 ac; `-nomask` so isolated
   speckles surrounded by nodata are removed too) — **3.5 s**.
3. `gdal_polygonize.py` masked to nonzero, run in native Albers (ESRI:102039) — **3.8 s**,
   2,022 polygons (classes 1–6, attribute `severity`).
4. `ogr2ogr -t_srs EPSG:4326` → GeoJSON (4.5 MB severity, 1.8 MB perimeters).
5. `tippecanoe -Z4 -z13 --detect-shared-borders --coalesce-densest-as-needed` with two
   layers (`severity`, `perimeters`) → **`wa2024.pmtiles`, 983 KB, 394 tiles, 1.6 s**.
6. `wa_2024_fires.json` — 17 fires with name/date/acres/assessment/bbox (4.4 KB).
7. Rendered in MapLibre over the USGS Topo base (`viewer.html`), served via
   `pmtiles serve` (port 8080) + `python3 -m http.server` (port 8081, in `pipeline/`);
   screenshots captured headless via playwright chromium.

Addendum (same day): after the mosaic-lag finding, the pipeline was re-run for **WA × 2023**
(the newest complete year) — `wa2023.pmtiles`, 1.7 MB, 3,755 severity polygons, 17/17 fires
filled. The viewer now loads both years with checkbox toggles (2023 solid outlines, 2024
dashed); all 2023 fires render with severity fills, confirming the empty-fill appearance of
most 2024 fires is missing source data, not a pipeline or rendering bug.

To view: with both servers running, open `http://localhost:8081/viewer.html`
(`?lng=&lat=&z=` params supported). Restart:
`cd ~/unburnt/pipeline/data && ~/tools/bin/pmtiles serve . --cors=\* --port 8080 &` and
`cd ~/unburnt/pipeline && python3 -m http.server 8081 &`.

## Findings

1. **THE BIG ONE — the annual mosaics lag ~2 years, not ~1.** The newest mosaic year is
   2024 (published April 2025), but for WA it contains only **2 of 17 fires** (Big Horn,
   Retreat — 43% of the year's 220k acres). The other 15, including the largest (Swawilla,
   53,784 ac), had no MTBS assessment when the mosaic was cut. The **2023** mosaic is
   **17/17 complete** for WA. Meanwhile the *perimeter* shapefile (updated continuously;
   ours is July 2026) has all 17 × 2024 fires, all marked "Initial" assessment.
   **Implications for v1:** (a) treat the latest mosaic year as provisional/partial or end
   the severity layer at the newest *complete* year (currently 2023); (b) always render
   perimeters from the perimeter shapefile, not the mosaic, so recent fires at least show
   extent — exactly what the two-layer design already does; (c) longer term, recent-season
   severity could be filled from per-fire severity rasters (direct download) as MTBS
   assesses them, ahead of the next mosaic release.
2. **Mosaic rasters are cropped to that year's mapped fires, not a fixed CONUS grid.** The
   2024 mosaic's extent doesn't even reach Swawilla's latitude. Never assume full-CONUS
   coverage; also means "no pixels here" ≠ "didn't burn" for the newest year.
3. **Scaling looks trivial.** WA×2024 (a light year) vectorized in <10 s and 983 KB. Even
   ~300 state-years for 11 states × 30 yr extrapolates to minutes of compute; the PMTiles
   for the full scope will likely land in the low hundreds of MB. The 7.7 GB WSL2 RAM cap
   never mattered.
4. **Mosaic values confirmed:** byte raster, NoData=0, 1=unburned/low, 2=low, 3=moderate,
   4=high, 5=increased greenness, 6=masked, palette embedded. WA 2024 polygon counts after
   sieve: 657/150/996/212/1/6 for classes 1–6.
5. **Rendering over USGS Topo works** as hoped: severity fills at 0.65 opacity read
   clearly over contours/hydro (`wa_retreat_z11.png`); class 1/5 dimmed to 0.25 reads as
   context. Perimeter-only fires (missing severity) still show as outlines
   (`wa_swawilla_z11.png`).
6. Minor: parallel `curl ... & curl ... &` after `cd` — only the first job inherits the
   `cd`; keep absolute paths in pipeline scripts.

## Next-step tweaks suggested by this run

- Fetch mosaics year-by-year from ScienceBase programmatically (child-item lookup by
  title year, then the CONUS zip file URL).
- Decide the "provisional tail" policy (finding 1) before the full build.
- Per-fire severity-class acreage breakdown for the metadata JSON (zonal stats) was
  skipped in this slice; cheap to add with numpy over the clipped raster per fire bbox.
