# unburnt

A web visualization of **40 years of wildfire in the Western US** — an animation that plays the
entire MTBS record (1984–present) as its opening act, then lets you explore the accumulated
result on a zoomable map.

The animation steps through the record one year at a time: each year's fires appear at full
intensity, then fade with age without disappearing, so the run builds toward a single picture of
four decades of burning. Burn **severity** data is kept for a future at-rest view.

> The repo name is a holdover from the project's earlier framing as a hike-planning tool. A
> rename is deferred until the visualization settles.

## Status (2026-07-27)

Working app covering **all 11 Western states, 1984–2024** — see `app/`:

- **Data:** **11,377 fires** (`app/data/west_fires.geojson.gz`, 2.8 MB gzipped / 11.5 MB raw),
  from the MTBS perimeter shapefile with ignition dates, acreage, and assessment type. The
  643-fire WA slice is kept as a lighter dataset (`?data=wa`). Datasets ship gzipped and are
  inflated in the browser, so no server config is needed. Geometry is simplified to ~200 m —
  **17.8 M vertices → 478 k (−97.3%) for 0.44% area distortion**, sub-pixel at the zooms the
  animation plays at. See `animation-plan.md` → "Simplification".
- **Repeat burns:** **10,872 polygons** (`app/data/west_repeats.geojson.gz`, 1.9 MB gzipped),
  the same perimeters counted onto a 90 m grid so each patch of ground carries how many fires
  have crossed it since 1984, and its acreage. Built offline by `pipeline/build-repeats.sh`, and
  never fetched while the animation is running — inflating it blocks the main thread for ~75 ms,
  so it waits for the run to end or for anything to pause it (including the tap that asks for
  the view).
- **Base map:** bland dark vector base (OpenFreeMap) that scales — state boundaries, coastline
  and interstates at overview zoom; cities, then villages/hamlets, rivers, streams, forest and
  park shading, road tiers and buildings as you zoom in. No user-facing toggles: these are
  styling decisions.
- **Animation:** **41 yearly states, 0.75 s each (~31 s)**, playing on load. The year rail down
  the right edge scrubs and snaps to whole years; grabbing it is the pause.
- **Three views, one control:** tapping the handle cycles *accumulate* (every year up to the
  one on show, fading with age) → *single year* (that season alone) → *repeat burns*. In the
  third view the rail stops carrying years and carries **repeat level** instead: 2× at the
  bottom up to 9× at the top, each stop showing every patch that has burned that many times
  *or more*. A click parks the animation on the year it is showing and names the fire you
  clicked; pan and zoom work at all times, playing or paused.

Run it locally: `npm run dev` (or `python3 serve.py`) → `http://localhost:8090/index.html`
(URL params: `?data=west|wa`, `?lng=&lat=&z=`, `?year=1995`, `?mode=year|repeat`, `?level=4`,
`?debug=1`).
Use `serve.py` rather than `python3 -m http.server`: it sends `no-store`, so a reload always
picks up the latest build. Cross-check the `build N` stamp in the title panel.

**Deploy:** automatic — every push to `main` triggers `.github/workflows/deploy.yml`, which
deploys to Cloudflare. Manual runs are available from the Actions tab. `npm run deploy` still
works locally (needs `npx wrangler login`), and `npm run check` validates the config without
deploying or authenticating. Hosting is **Cloudflare Workers static assets** — see "Hosting" below.

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
- **Modes cost no new controls.** The three views are cycled by tapping the handle, which is
  already there and already under the thumb — no menu, no toolbar. Because the tap is the only
  way in or out, the *drag* is free to mean something different in each view: on the timeline it
  scrubs years, in repeat mode it scrubs burn counts. Year and level are separate state, so
  leaving repeat mode returns you to the year you left. A click or rail drag parks the animation
  where it is; panning and zooming always work. Severity colouring still awaits the raster
  build.
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

## Hosting

**Cloudflare Workers static assets**, configured in `wrangler.jsonc`. Assets-only: there is no
Worker script, so `wrangler.jsonc` has no `main`. The whole of `app/` is uploaded verbatim, which
is why `serve.py` lives at the repo root rather than inside it.

- **Why Workers rather than Pages:** Cloudflare froze Pages feature development in 2025 and
  steers new projects to Workers static assets. Adding a Worker later (an R2-backed tile route,
  or a proxy for live fire/smoke data) means adding `main` and an `assets.binding` — no migration.
- **Why not GitHub Pages:** fine today, but git rejects files over 100 MB (and Pages serves LFS
  pointers, not content), so the eventual severity PMTiles archive — estimated at low hundreds of
  MB — could never live there. Response headers also aren't configurable.
- **CI:** GitHub Actions (`cloudflare/wrangler-action`) deploys on push to `main`. The only
  secret required is `CLOUDFLARE_API_TOKEN`; no build step and no `npm ci` are needed.
- **Caching:** Workers static assets default to `Cache-Control: public, max-age=0,
  must-revalidate`, so browsers revalidate before use. That's what this project wants, so there
  is no `_headers` file.
- **Asset limits to remember:** 20,000 files and **25 MiB per file**. The current datasets
  (2.8 MB + 672 KB) are fine; a large PMTiles archive is not, which is what R2 is for.

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
- `app/` — the deployed site: one HTML file plus gzipped GeoJSON datasets (11-state and WA).
  Everything here is published as-is.
- `serve.py` — no-cache local dev server (serves `./app`); `wrangler.jsonc`, `package.json` —
  Cloudflare deploy config.
