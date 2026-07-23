# Recommendation — Data Sources, Architecture, and Open Questions

## Recommended data source stack

| Layer | Source | Why |
|---|---|---|
| Historical burn severity (the core feature) | **MTBS** | Only source with severity (low/mod/high), consistent 40-year methodology, full Western US coverage. This is the differentiator vs. CalTopo/Gaia, which only show recency. |
| Historical perimeter supplement | **WFIGS Interagency Fire Perimeter History** | Catches fires below MTBS's 1,000-acre threshold and the most recent season before MTBS finalizes it. |
| Active fires | **WFIGS Current Interagency Fire Perimeters** | Live perimeter polygons, 5-minute refresh, no key needed. |
| New-ignition detection | **NASA FIRMS** (optional, phase 2) | Fills the gap between "fire starts" and "WFIGS has drawn a perimeter." Adds a hotspot-point layer for very fresh fires. |
| Smoke (visual plume) | **NOAA HMS** | Real shaded-region polygons (light/medium/heavy), matches the visual style of the burn layer. |
| Smoke/air quality (point readings) | **AirNow** | Free API, simple bbox queries, backs the official fire.airnow.gov map. Skip PurpleAir initially — adds density but also billing risk at scale. |

## Architecture recommendation

Given you're comfortable running a Cloudflare backend (per booked and other projects), the
plan splits into a **build-time pipeline** for the heavy historical data and a **live Worker
proxy layer** for anything that changes minute-to-minute.

### Build-time (run periodically — e.g. quarterly, matching MTBS's release cadence)
1. Pull MTBS **thematic (classified)** severity rasters + perimeter shapefiles for the last
   ~30 years, clipped to the 11 Western states. (The thematic product is already binned into
   discrete classes — there is no extra fidelity in tiling it as raster; continuous dNBR
   isn't comparable across fires without MTBS's per-fire thresholds anyway.)
2. **Vectorize** the classified severity raster: `gdal_sieve` to drop speckle patches below a
   few pixels (~1–2 acres), `gdal_polygonize` **in the native Albers CRS** (never resample a
   categorical raster), reproject the resulting polygons, then tippecanoe → a single PMTiles
   archive with two layers (severity classes + fire perimeters). Cap maxzoom at ~z12–13 —
   the honest limit of the 30m source; MapLibre overzooms vector tiles natively beyond that.
   Expect pixel-staircase edges when overzoomed — faithful to the data, not an artifact.
3. Upload the PMTiles archive to **R2** — one file, one multipart PUT per rebuild, with a
   **versioned filename** for cache-busting (vs. mass re-uploading a loose tile tree at
   ~$4.50/million R2 Class A ops).
4. Generate a **static fire-metadata JSON** (name, year, acreage, severity-class breakdown):
   ~2k fires ≈ a few hundred KB, filtered client-side. Per-feature attributes also ride in
   the PMTiles layers for click popups. D1 deferred until fire count/scale demands it.

### Live (served at request time via Workers)
- The PMTiles archive + metadata JSON are served straight from R2 (public bucket on a custom
  domain gets CDN caching and range-request support with zero code; a thin Worker in front is
  optional, not required, for v1).
- In v1.1+, a Worker **proxies and caches** WFIGS Current Perimeters, NOAA HMS smoke, AirNow,
  and (if added) FIRMS — using KV or the Cache API with a short TTL (minutes, matching each
  source's own refresh cadence). The real justifications are key-hiding (AirNow) and caching;
  most of these endpoints already send permissive CORS headers.
- Viewport queries ("fires here, 1996–2026, severity ≥ moderate") are client-side filters
  over the static metadata JSON — at ~2k fires there's no server-side query layer to build.

### Map rendering: MapLibre GL JS

**Choice:** MapLibre GL JS, rendering a single vector tile source (severity-class polygons +
perimeters, via PMTiles) over a basemap.

**Why, vs. the realistic alternatives:**
- **vs. Mapbox GL JS (proper):** MapLibre is the open-source fork of Mapbox GL JS v1, created
  when Mapbox went proprietary (account + usage-based billing per map load required from v2
  onward). MapLibre kept the same engine/API but stayed free/BSD-licensed — no account, no
  key, no bill that scales with traffic. Consistent with avoiding metered services elsewhere
  in this project (e.g. skipping PurpleAir's billed tier).
- **vs. Leaflet:** Leaflet is lighter/simpler but vector tiles are a third-party plugin
  (Leaflet.VectorGrid) bolted onto a fundamentally raster/DOM-tile library, not native. We
  need vector layers with data-driven styling (recolor/filter fires by year or severity
  without re-fetching) — MapLibre does this natively via GPU rendering and a built-in
  expression system; Leaflet needs more plugin glue to match it.
- **vs. OpenLayers:** Capable of the same things, but a much heavier, more general-purpose GIS
  library with a steeper API than this project needs.
- **Deciding factor:** MapLibre has an official `pmtiles` protocol plugin that reads PMTiles
  archives directly via HTTP range requests from a static host — no tile server. That's
  exactly the "Workers just serves files from R2" architecture below.

### What PMTiles actually is

A single-file archive format (vector or raster tiles) built so a client fetches only the
bytes it needs via HTTP range requests, instead of needing a live tile-serving backend or a
directory tree of millions of small tile files. The archive has an internal index; the client
computes the byte range for a given `{z}/{x}/{y}` tile and issues one ranged `GET`. Any static
host that supports range requests — R2, S3, GitHub Pages, Cloudflare — can serve it with zero
backend logic.

This is what makes "just serve files from R2" work for the whole historical layer stack:
build the PMTiles archive once (severity polygons + perimeters as two layers, via
`tippecanoe`), upload the one file to R2, and MapLibre's `pmtiles` plugin reads it
range-request by range-request as the user pans/zooms. Everything in v1 is vector — there is
no raster pyramid, no per-tile object management, and one artifact to version per rebuild.

It's a good fit specifically for the **historical/static** layers because it's a build-once
artifact — updating means regenerating and re-uploading the whole file, fine for "rebuild
quarterly when MTBS releases new data," a poor fit for live/active-fire data (hence those
staying on the separate live Worker-proxy path, not PMTiles).

### Why not pure static (no backend)?
A pure static/GitHub-Pages approach (as used in your other projects) would work for the
*historical* layers, but the active-fire/smoke/AQI layers are inherently live data — serving
them well either means client-side calls straight to NIFC/NOAA/AirNow (CORS and rate-limit
exposure, no caching control) or a thin server-side proxy. Since you're already comfortable
with Workers, the proxy approach is the better tradeoff here.

## Decisions

- **Geographic scope:** all 11 Western states (WA, OR, CA, ID, NV, UT, AZ, MT, WY, CO, NM).
  Alaska deferred past v1 — MTBS distributes it separately in a different projection (Alaska
  Albers vs. CONUS Albers), roughly doubling the acquisition/reprojection pipeline.
- **Time window:** last ~30 years. Deadfall in high-severity burns peaks 10–20 years
  post-fire and shade loss persists for decades, so 10 years would cut the data exactly
  where severity is most useful; with vector severity the marginal cost is small.
- **Severity representation:** vectorized from the MTBS *thematic* (classified) raster —
  the source is already discrete classes, so vector loses nothing, and it buys year
  filtering, click-to-query, and a single-format PMTiles pipeline. Maxzoom ~z12–13 to match
  the 30m source resolution; MapLibre overzooms beyond that.
- **Trails:** out of scope for v1. Fire/smoke/severity layers on a base map only.
- **Primary use case:** personal tool initially — no need to over-engineer for public-scale
  rate limits, uptime, or abuse exposure yet, but keep the Worker proxy layer in place anyway
  since it's needed regardless (CORS, key-hiding, caching).
- **Mobile:** not required for v1, but important for v2 — worth keeping the UI responsive-ish
  from the start so v2 isn't a rewrite, without spending real effort on it now.
- **Offline:** not a requirement.
- **Hosting:** all Cloudflare — Pages for the frontend (or Workers static assets, see open
  questions), R2 for tile storage, Workers for the v1.1+ live-data proxy. Fire metadata is a
  static build-time JSON; **D1 deferred** until fire count/scale demands a real query layer.
- **MVP scope:** ship the historical burn severity layer alone first (MTBS severity +
  perimeters, last ~30 years, 11 Western states). Validate that the core idea is useful
  before adding active fire perimeters, smoke, and AQI in a later phase.

## Revised v1 scope (given the decisions above)

v1 is deliberately narrow: a zoomable MapLibre GL map of the 11 Western states, with MTBS
burn severity polygons (and perimeters) for the last ~30 years, color/shade-coded, servable
from Cloudflare Pages/Workers + R2. No trails, no live fire/smoke/AQI, no offline, desktop-first.
Active fire perimeters (WFIGS Current), smoke (NOAA HMS), and AQI (AirNow) become a v1.1/v2
addition once the core severity view is validated. Mobile-responsive polish is also deferred
to v2, but the build shouldn't actively work against it (e.g. avoid desktop-only layout
assumptions where they'd be costly to unwind later).

## Next steps (when ready to start building)

Not started yet — captured here so a future session can pick this up without re-deriving the
plan. Roughly in order:

1. **Basemap research** — ✅ done, see `basemap.md`. v1: USGS Topo raster service (+
   Imagery toggle); v1.1 upgrade path: Protomaps extract + terrarium hillshade + contours.
2. **Cloudflare project scaffolding** — frontend project (Pages or Workers static assets),
   R2 bucket, wired up with wrangler, matching the booked project's setup pattern.
3. **Pipeline validation slice** — ✅ done (WA × 2024, 2026-07-23), see
   `pipeline/pipeline-validation.md`. Pipeline works end-to-end locally in seconds; key
   finding: annual mosaics lag ~2 years (2024 mosaic has 2/17 WA fires; 2023 is complete),
   so the severity layer's newest year must be treated as partial — perimeters carry
   recent-fire extent (which the two-layer design already does).
4. **MTBS data acquisition** — thematic severity rasters (annual mosaics are the likely easy
   path) + perimeter shapefiles, ~30 years, clipped to the 11 Western states. Confirm exact
   download mechanism and check format details haven't changed since this research
   (mtbs.gov, ~mid-2026).
5. **Vectorization pipeline** — script the sieve → polygonize (native Albers CRS) →
   reproject → tippecanoe steps into a repeatable quarterly build producing one PMTiles
   archive (severity + perimeter layers) and the fire-metadata JSON.
6. **Upload to R2** — versioned PMTiles filename + metadata JSON; public bucket or thin
   Worker, either works.
7. **Frontend** — MapLibre GL JS + `pmtiles` protocol plugin: severity fill layer, perimeter
   outline layer, year filtering via expressions, newest-fire-on-top sort order for reburns.
8. **Validate** — use it for actual personal hike planning before deciding on v1.1 scope
   (active fires, smoke, AQI, Alaska, WFIGS supplement, mobile polish).

## Open questions (resolve before or during the build)

- **Basemap** — ~~undecided~~ **resolved, see `basemap.md`**: v1 uses the USGS Topo raster
  tile service (public domain, no key, contours/relief/names for one style-JSON line), with
  a Topo/Imagery toggle. Upgrade path if the raster base chafes: Protomaps Western-US
  extract on R2 + AWS terrarium hillshade + `maplibre-contour` — additive swap, no overlay
  code changes. Keep overlay style code separate from base style JSON to preserve that.
- **Which severity classes to render** — MTBS thematic has ~6 classes (unburned/low, low,
  moderate, high, increased greenness, masked). Rendering class 1 (unburned-to-low) inside
  perimeters mostly adds noise; likely render low/moderate/high fills and let the perimeter
  outline carry extent. Also pick the `gdal_sieve` speckle threshold during the validation
  slice.
- **Reburn styling** — areas burned more than once in 30 years will have overlapping
  severity polygons from different years. Newest-on-top with opaque fills is the likely
  answer (translucent stacking reads as mud); needs a MapLibre sort key on year.
- **WFIGS historical supplement** — out of v1 (MTBS-only scope), revisit in v1.1: it catches
  sub-1,000-acre fires and the not-yet-finalized current season.
- **Pages vs. Workers static assets** — Cloudflare froze Pages feature development (2025)
  and steers new projects toward Workers static assets. Decide at scaffolding time; either
  serves a static MapLibre frontend fine.
- **Legend honesty** — MTBS classes are analyst-thresholded per fire, and the most recent
  seasons mix Initial and Extended assessments. Translate classes into hiker terms (shade
  loss, deadfall risk, canopy loss) rather than presenting raw remote-sensing bins.
- **Provisional-tail policy** (new, from the validation slice) — the annual severity
  mosaics lag ~2 years (the 2024 mosaic, published April 2025, holds only 2 of 17 WA-2024
  fires; 2023 is complete). Options: end the severity layer at the newest complete mosaic
  year; or include the partial year with a "provisional" badge; or fill recent fires from
  per-fire severity rasters as MTBS assesses them. Perimeters (updated continuously) must
  come from the perimeter shapefile regardless, so recent fires always show extent.
- **Mosaic extents are data-driven** — each year's mosaic raster is cropped to that year's
  mapped fires, not a fixed CONUS grid; the pipeline must not assume coverage, and "no
  pixels" ≠ "didn't burn" in the newest year.
