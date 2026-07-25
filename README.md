# unburnt

A web visualization of **40 years of wildfire in the Western US** — an animation that plays the
entire MTBS record (1984–present) as its opening act, then lets you explore the accumulated
result on a zoomable map.

The animation steps through the record one year at a time: each year's fires appear at full
intensity, then fade with age without disappearing, so the run builds toward a single picture of
four decades of burning. Burn **severity** data is kept for a future at-rest view.

> The repo name is a holdover from the project's earlier framing as a hike-planning tool. A
> rename is deferred until the visualization settles.

## Status (2026-07-25)

Working app covering **all 11 Western states, 1984–2024** — see `app/`:

- **Data:** **11,377 fires** (`app/data/west_fires.geojson.gz`, 2.8 MB gzipped / 11.5 MB raw),
  from the MTBS perimeter shapefile with ignition dates, acreage, and assessment type. The
  643-fire WA slice is kept as a lighter dataset (`?data=wa`). Datasets ship gzipped and are
  inflated in the browser, so no server config is needed. Geometry is simplified to ~200 m —
  **17.8 M vertices → 478 k (−97.3%) for 0.44% area distortion**, sub-pixel at the zooms the
  animation plays at. See `animation-plan.md` → "Simplification".
- **Base map:** bland dark vector base (OpenFreeMap) that scales — state boundaries, coastline
  and interstates at overview zoom; cities, then villages/hamlets, rivers, streams, forest and
  park shading, road tiers and buildings as you zoom in. No user-facing toggles: these are
  styling decisions.
- **Animation:** **41 yearly states, 0.75 s each (~31 s)**. Play/pause/replay from one button,
  plus a scrubber that snaps to whole years.
- **No modes:** a click parks the animation on the year it is showing and names the fire you
  clicked; pan and zoom work at all times, playing or paused.

Run it: `cd app && python3 serve.py` → `http://localhost:8090/index.html`
(URL params: `?data=west|wa`, `?lng=&lat=&z=`, `?year=1995`, `?debug=1`).
Use `serve.py` rather than `python3 -m http.server`: it sends `no-store`, so a reload always
picks up the latest build. Cross-check the `build N` stamp in the title panel.

**Data coverage** (verified 2026-07-25 against the July 2026 MTBS perimeter release):
perimeters are complete for **41 years × all 11 states** — CA 1,956 · ID 1,623 · AZ 1,435 ·
OR 1,091 · NM 1,076 · NV 1,003 · MT 963 · UT 720 · WA 643 · WY 466 · CO 436. Severity mosaics
exist for all 41 years on ScienceBase, but the newest 1–2 are substantively incomplete (the
2024 mosaic held 2 of 17 WA fires), so severity is solid only through ~2023.

## Key decisions

- **Time window: the full ~40-year MTBS record, 1984–present.** Currently **1984–2024**.
  MTBS has *begun* 2025 (33 fires across 8 states, none in WA) but it's far too sparse to show
  as a season, so the animation ends at 2024 and extends forward as MTBS finalizes each year.
- **Scope:** all 11 Western states (WA, OR, CA, ID, NV, UT, AZ, MT, WY, CO, NM). WA is the
  test slice. Alaska deferred (separate MTBS distribution + projection).
- **Granularity: one state per year** — 41 discrete states, no within-year ignition timing.
  This is what keeps the engine small and verifiable.
- **Fade model — accumulate & fade:** a year's fires stay on the map, dimming one step per
  subsequent year toward a still-visible ember floor. The final state shows all 41 years at once.
- **No view modes:** one always-live map. A click or scrubber drag parks the animation where it
  is; panning and zooming always work. Severity colouring awaits the raster build.
- **Fire mark:** the real perimeter polygon. **No glow** — it caused two separate bugs and was
  removed rather than debugged further (see `animation-plan.md` → "Debugging history").
- **Map library:** MapLibre GL JS — no account, no token, no per-load billing. (A satellite
  layer is easy to add from free public raster — Esri World Imagery or USGS Imagery — so Mapbox
  isn't needed; it was wired up, unused, and removed.) The base is decoupled from the fire
  layers, so swapping it later is a base-style-only change.
- **Efficiency is a requirement, not a polish item:** the animation must run on phones while
  showing every fire in the 11 Western states (11,377 perimeters, 1984–2024).
- **Platform:** Cloudflare — Pages/Workers static assets for the frontend, R2 for PMTiles.
  Fire metadata as static build-time JSON; D1 deferred.
- **Tile format:** vector PMTiles on R2, read directly by MapLibre via HTTP range requests —
  no tile server. Maxzoom ~z12–13 (the honest limit of 30 m source data).

## How the animation works

The entire animation state is **one integer**: the index of the year on show. Two lookup tables
(`COLOR[age]`, `OPACITY[age]`, indexed by age in *years*) are built once at startup. There is one
fill layer per ignition year with a static filter, and showing a state assigns each layer a
**constant** colour and opacity by its age. Play is `setInterval`; pause is `clearInterval`.

Consequences that matter:

- **No data-driven paint anywhere.** Every paint value is a constant scalar — a GPU uniform — so
  no per-vertex attribute buffers are ever recomputed or re-uploaded. An earlier version set four
  data-driven properties per frame across ~87k vertices and measured **4.5 fps**; the current one
  holds **59–61 fps** with 11,377 fires.
- **41 discrete states**, so the whole state space can be enumerated and asserted.
- **No source mutation.** Animating by calling `setData` re-tiles the source in the worker and
  was the cause of a long-standing "fires keep flashing after the end" bug.
- Engine size: **483 → 171 lines (−65%)** across the simplification passes.

`animation-plan.md` carries the full rationale, the accepted tradeoffs, and a "Debugging history"
section listing the wrong turns (and the MapLibre traps behind them) so they aren't repeated.

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
- `app/` — the working app: one HTML file, gzipped GeoJSON datasets (11-state and WA),
  and `serve.py`, a no-cache dev server.
