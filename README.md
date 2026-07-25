# unburnt

A web visualization of **40 years of wildfire in the Western US** — an animation that plays the
entire MTBS record (1984–present) as its opening act, then lets you explore the accumulated
result on a zoomable map.

Each fire flares on its real ignition date, then fades with age but never disappears, so the
run builds toward a single picture of four decades of burning. Burn **severity** data is kept
and surfaced in a separate at-rest view.

> The repo name is a holdover from the project's earlier framing as a hike-planning tool. A
> rename is deferred until the visualization settles.

## Status (2026-07-25)

Working WA test slice, running locally — see `app/`:

- **Data:** all 643 WA fires, 1984–2024, from the MTBS perimeter shapefile with real ignition
  dates, acreage, and assessment type (`app/data/wa_fires.geojson`, 2.2 MB).
- **Base map:** bland dark vector base (OpenFreeMap tiles) that scales — state boundaries and
  coastline at overview zoom; cities, then villages/hamlets, rivers, then streams, forest/park
  shading, road tiers and buildings as you zoom in. Toggles for Cities / Rivers / Roads /
  Satellite.
- **Animation:** ~31 s for 41 seasons (0.75 s per year), play/pause, replay, scrubber, live
  season clock.
- **Explore mode:** static all-fires view with click-to-inspect popups. Currently colored by
  **year** — severity coloring needs the raster half of the pipeline (not yet built).

Run it: `cd app && python3 -m http.server 8090` → `http://localhost:8090/index.html`
(URL params: `?lng=&lat=&z=`, `?mode=explore`, `?t=0.75` to freeze a frame).

**Open issue:** fires were observed trailing behind the timeline slider during playback, with
fires continuing to appear after the clock finished. The animation engine has been rewritten
to remove the cause (see "Performance architecture" below), but the fix is **not yet confirmed
on real hardware** — the dev sandbox has no GPU, so its frame-rate numbers can't distinguish
the two designs.

## Key decisions

- **Time window: the full ~40-year MTBS record, 1984–present.** Currently 1984–2024; the July
  2026 perimeter release has not yet mapped 2025.
- **Scope:** all 11 Western states (WA, OR, CA, ID, NV, UT, AZ, MT, WY, CO, NM). WA is the
  test slice. Alaska deferred (separate MTBS distribution + projection).
- **Fade model — accumulate & fade:** a fire stays on the map after its season, dimming with
  age toward a still-visible ember floor. The final frame shows all 40 years at once.
- **Two modes, one toggle:** Animation (colored by recency) and Explore/at-rest (colored by
  severity, once the raster build lands). Severity is never shown during the animation.
- **Fire mark:** the real perimeter polygon, plus a centroid glow that blooms at ignition so
  small fires register at multi-state zoom.
- **Map library:** MapLibre GL JS — no account, no token, no per-load billing. Satellite comes
  from free public raster (Esri World Imagery / USGS Imagery), so Mapbox isn't needed. The base
  is decoupled from the fire layers, so swapping it later is a base-style-only change.
- **Efficiency is a requirement, not a polish item:** the animation must run on phones while
  showing every fire in the 11 Western states (~15–25k perimeters).
- **Platform:** Cloudflare — Pages/Workers static assets for the frontend, R2 for PMTiles.
  Fire metadata as static build-time JSON; D1 deferred.
- **Tile format:** vector PMTiles on R2, read directly by MapLibre via HTTP range requests —
  no tile server. Maxzoom ~z12–13 (the honest limit of 30 m source data).

## Performance architecture (why the animation is built the way it is)

The expensive operation in MapLibre is changing a **data-driven** paint property — one that
reads a feature attribute. Each change re-derives and re-uploads per-vertex attribute buffers
for every feature in every tile. The first implementation did that for four properties across
~87k vertices every frame, which measured **4.5 fps** and made the canvas fall far behind the
clock.

The current design instead:

- splits fires into **one fill layer per ignition year**, each painted with **constant scalar
  values** (GPU uniforms — zero per-vertex work), so advancing time is a handful of scalar
  updates;
- **skips updates that wouldn't change the frame** (change detection per layer);
- uses data-driven paint for the **active season only**, so exact per-fire ignition timing is
  preserved where it matters, bounded to one year of geometry;
- **quantizes GL updates** to ~20 simulated days (the clock text still updates every frame);
- drives the flare glow by swapping a **tiny source** holding only currently-flaring fires,
  instead of repainting all fires;
- drops per-fire outlines during the animation (they doubled vertex cost for little gain).

This scales with the number of *years*, not the number of fires — which is what makes the
11-state target viable. Tradeoffs are documented in `animation-plan.md`.

## Files

- `animation-plan.md` — **the current plan.** Modes, animation engine, color model, base-map
  design, pipeline changes, milestones, and the accepted tradeoffs.
- `recommendation.md` — data-source stack, Cloudflare architecture, why MapLibre, what PMTiles
  is. Still accurate on data/architecture; its *framing* (hike planning) and basemap choice are
  superseded by `animation-plan.md`.
- `data-sources.md` — survey of every wildfire/smoke/AQI source investigated (MTBS, WFIGS,
  CAL FIRE FRAP, NASA FIRMS, AirNow, NOAA HMS, PurpleAir) and prior art.
- `basemap.md` — basemap research. Its v1 recommendation (USGS Topo raster) is superseded: the
  visualization needs a bland *vector* base, which is Option B/C in that doc.
- `pipeline/pipeline-validation.md` — the 2026-07-23 end-to-end vectorization run (WA × 2023/24)
  that proved the severity pipeline, with timings and the mosaic-lag finding.
- `app/` — the working WA test slice (single HTML file + GeoJSON).
