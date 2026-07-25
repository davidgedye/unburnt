# Animation Plan — 40-Year Western Fire Visualization

## What this is

A visualization of **every Western US wildfire in the ~40-year MTBS record (1984–present)**.
On load, an animation plays the whole record: each fire flares on its real ignition date, then
fades with age without disappearing, so the run accumulates into one picture of four decades of
burning. Afterward the user explores the result, with burn **severity** available in a separate
at-rest view.

This supersedes the project's original framing as a hike-planning tool. The
data/pipeline/architecture decisions in `recommendation.md` still hold (MTBS + WFIGS →
vectorized PMTiles on R2, MapLibre GL JS, Cloudflare); this doc supersedes its *framing*, its
*frontend behavior*, and its *basemap choice*.

**Name:** deferred. "unburnt" fit the hike-planning framing; a viz-first name comes later.

## Locked decisions

| Decision | Choice |
|---|---|
| Time window | **The full MTBS record, ~40 years.** Currently **1984–2024**; extends forward as MTBS finalizes each season. 2025 exists but is far too sparse to include (see caveats) |
| Geographic scope | **11 Western states** (WA, OR, CA, ID, NV, UT, AZ, MT, WY, CO, NM) — **built**, 11,377 fires. WA (643) kept as a lighter dataset |
| Animation fade model | **Accumulate & fade** — a fire stays on the map after its season, dimming with age toward a still-visible ember floor; the final frame shows all 40 years at once |
| At-rest view | **Severity, manual toggle** — the animation ends on its final frame and holds; a control switches to a static severity view |
| Fire mark | **Filled perimeter + glow** — the real perimeter polygon, plus a centroid bloom at ignition so small fires register at multi-state zoom |
| Map stack | **MapLibre GL JS.** No account, token, or metered billing. Satellite from free public raster (Esri World Imagery / USGS Imagery) — Mapbox not needed |
| Base map | Bland at overview zoom, but **a true scalable map**: progressively more detail as you zoom, plus layer toggles |
| Efficiency | **A requirement, not polish.** Must run on phones while showing all 11 states (**11,377** perimeters, 1984–2024) |

The base map is **decoupled** from the animation/data layers, so swapping it later (even to
Mapbox/MapTiler) touches only the base style — nothing in the animation engine.

## Two view modes

### Mode 1 — Animation (recency), the default on startup
- **~0.75 s per year** — about **31 s** for the current 41 seasons. Plays on load,
  re-triggerable via Replay, with pause and a draggable scrubber.
- A time cursor sweeps `Y0 → Y1`. Each fire **flares** at its actual ignition date, in an
  intense hot color, then **fades with age** toward a dim ember floor but never vanishes.
- Color encodes **recency only** — severity is not shown here.
- The base map is at its blandest: dark ground, state boundaries, coastline.
- Ends on the final frame — all 40 years visible, recent fires hot, 1984 fires faint — and
  holds there.

**Pace note:** the pace is *per year* (0.75 s/yr), so total duration grows as the record grows
(~31 s now, ~45 s if the window were ~60 years). The alternative — a fixed 45 s total — was
considered and rejected for now: constant per-year pace keeps "the speed of time" legible.

### Mode 2 — At-rest (severity), reached by toggle
- The static all-fires picture colored by **MTBS burn severity** (low / moderate / high).
- Full zoom/pan, progressive base-map detail, optional **satellite** raster.
- Click a fire → name, date, acreage, assessment type (severity breakdown once available).
- A control returns to Mode 1 and replays.

**Current state:** Explore mode colors fires **by year**, not severity — severity requires the
raster half of the pipeline, which isn't built yet. The legend says so in the app.

## Base map design

MapLibre GL JS, composed of independent, individually-styleable layers so "bland" and "rich"
are visibility/opacity settings rather than different maps. Detail tiers in by zoom:

| Zoom | What appears |
|---|---|
| ≲ 5 (continental) | Dark ground, state boundaries, **coastline/shoreline** — the animation backdrop |
| ~5–8 (state) | Cities and towns, major rivers |
| ~9–11 | Villages, hamlets, neighborhoods; forest/park shading; secondary roads |
| ~11–13 | Streams, canals; minor roads |
| 13+ | Buildings |

- **Source:** currently **OpenFreeMap** hosted vector tiles (free, no key — the low-effort
  path). Upgrade path: a **Protomaps extract of the 11 Western states** on R2, same
  PMTiles-on-R2 serving as the fire data. Swap is additive; layer definitions barely change.
- **Coastline** is drawn as an explicit stroke, not implied by a fill contrast — at overview
  zoom the land/water edge must read as clearly as the state lines.
- **Toggles:** Cities / Rivers / Roads / Satellite, each switching a whole tier group.
- **Satellite** is a raster layer, off by default (Esri World Imagery; USGS Imagery is the
  public-domain alternative). Boundaries brighten when it's on.
- Max zoom 17, so the deep detail has room to exist.

## Animation engine

### Timeline
- `Y0` = Jan 1 of the earliest fire year, `Y1` = Dec 31 of the latest; both derived **from the
  data**, not hardcoded — the window extends automatically as MTBS publishes new seasons.
- Animation clock maps linearly to `currentDays` (days since `Y0`). Linear calendar time; each
  year gets the same on-screen duration.

### Per-fire data
Each perimeter feature carries `event_days` (ignition date as days since `Y0`, from MTBS
`ig_date`), `year`, `acres`, `name`, `type`, `asmnt`, and — for Mode 2 — severity attributes.

### Color / intensity model (Mode 1)
`age = currentDays − event_days`; `age < 0` → hidden. The ramp (hot flare → still-visible
ember floor):

```
age      fill color   fill opacity
0d       #fff2b0      0.95
30d      #ffcf40
120d     #ff9526      0.85
1yr      #ff5f1a      0.75
3yr      #e83c17      0.65
8yr      #b23016      0.58
40yr+    #8f2a15      0.55   (ember floor — never invisible)
```

The floor matters: an earlier version faded old fires to near-black, which made them vanish
against the dark base and left the end frame nearly empty.

**Draw order:** newest-on-top, so reburned areas don't turn to mud. This falls out of adding
the per-year layers in ascending year order (no sort key needed).

### Performance architecture (the load-bearing part)

The expensive operation in MapLibre is changing a **data-driven** paint property — one that
reads a feature attribute. Each change re-derives and re-uploads per-vertex attribute buffers
for every feature in every loaded tile. The first implementation set four such properties
(fill color/opacity, line color/opacity) across **~87k vertices every frame**: measured
**4.5 fps**, with the canvas falling far behind the clock and fires still arriving long after
the timeline finished.

The current design:

1. **One fill layer per ignition year**, each with a **static** filter (`year == Y`) and
   **constant scalar** paint values — GPU uniforms, zero per-vertex work. Advancing time is a
   handful of scalar `setPaintProperty` calls.
2. **Change detection** — a layer is only touched when its computed color/opacity would
   actually differ from what's applied.
3. **Data-driven paint for the active season only**, so each fire in the current year still
   appears on its exact ignition date at full flare heat. Cost is bounded to one year of
   geometry.
4. **Quantized GL updates** — ~20 simulated days per update (≈40 ms at 0.75 s/yr, below
   perception). The clock/scrubber DOM still updates every frame.
5. **Glow via a tiny source** — the glow layer's source holds *only* currently-flaring fires,
   rebuilt per step; its paint is a static expression (`['get','glow']`) that never changes.
   Scales to any dataset size, since only a handful of fires flare at once.
6. **No per-fire outlines during the animation** — they doubled vertex cost for little visual
   gain. Explore mode keeps them (static, so they cost nothing per frame).
7. **A single generation token** guards the play loop, so only the newest run can drive frames
   (an earlier version could leave orphaned loops running, stacking extra sweeps).

This scales with the number of **years** (~40 layers), not the number of fires — which is what
makes the 11-state, 11,377-perimeter target viable on a phone.

### Accepted tradeoffs
- **Completed seasons fade per-year, not per-fire.** All fires in a finished season share one
  color/opacity, aged from a **mid-season reference (Aug 1)** — the typical Western ignition
  window. Error is at most a few months on a ramp spanning decades; invisible in practice. The
  *active* season is exact.
- **Time advances in ~20-day quanta** for GL updates (clock text stays smooth).
- **~40 fill layers** instead of one. More layers means more draw calls per frame, but each is
  cheap and unchanging — a far better trade than per-vertex re-uploads.

### Verification status
The rewrite is in place but **unconfirmed on real hardware**: the dev sandbox renders in
software with no GPU, where measurements (4.5 → 6.5 fps) can't distinguish the designs. Needs
a look on the actual machine, and eventually a phone. If fires still trail the clock there, the
next suspect is the **base-map layer count** (forest fills, buildings, streams, label layers)
rather than the fire layers.

## Build pipeline

### Perimeters — ✅ built (drives the animation)

The MTBS perimeter shapefile is one national file, so no per-state download. One `ogr2ogr`
command filters to the 11 states × 1984–2024 and reprojects:

```
ogr2ogr -f GeoJSON west_fires.geojson -t_srs EPSG:4326 \
  -simplify 0.002 -lco COORDINATE_PRECISION=4 \
  -sql "SELECT incid_name AS name, incid_type AS type, ig_date, burnbndac AS acres,
        asmnt_type AS asmnt FROM mtbs_perims_DD
        WHERE SUBSTR(event_id,1,2) IN ('WA','OR','CA','ID','NV','UT','AZ','MT','WY','CO','NM')
          AND ig_date >= '1984-01-01' AND ig_date <= '2024-12-31'" \
  pipeline/data/perimeters/mtbs_perims_DD.shp
```

State attribution uses the `event_id` prefix (where the fire started), which is why the data
stops cleanly at state lines. `event_days`/`year` are derived client-side from `ig_date`.

**Simplification chosen: `0.002°` (~200 m).** Measured tradeoff across the 11 states:

| `-simplify` | raw | gzipped | vertices |
|---|---|---|---|
| 0.001 | 18.5 MB | — | 830k |
| **0.002** | **11.5 MB** | **2.9 MB** | **478k** |
| 0.004 | 7.3 MB | 1.8 MB | 267k |

0.002 keeps enough fidelity for Explore at high zoom while staying phone-friendly. Datasets
ship **gzipped and are inflated in the browser** (`DecompressionStream`), so a static host
needs no content-encoding config; gzip magic-byte detection means it also works if the host
*does* send `Content-Encoding: gzip`.

### Still to build

1. **Severity (drives at-rest fills):** per-year CONUS thematic mosaics 1984–2024 from
   ScienceBase (confirmed: 41 child items, no gaps), clipped to the 11-state union,
   `gdal_sieve` → `gdal_polygonize` in native Albers → reproject → merge. The validation run
   extrapolates ~450 state-years to minutes of compute and a low-hundreds-of-MB archive.
2. **PMTiles** via tippecanoe: a `perimeters` layer (all years, with `event_days` and `year`) +
   a `severity` layer (complete years), maxzoom ~z12–13, on R2. This replaces the GeoJSON fetch
   and removes the size ceiling entirely — worth doing when severity lands, since severity
   polygons are far bulkier than perimeters.
3. **Two geometry detail levels**, if needed: coarse for the animation, full for Explore. The
   0.002 compromise defers this; PMTiles solves it properly via per-zoom generalization.
4. **Base map:** Protomaps 11-state extract → R2 (replacing OpenFreeMap).

## Data caveats (carried over, still true)

- **Provisional tail (mosaic lag ~2 yr):** severity mosaics are complete only through ~2023;
  the newest 1–2 years have perimeters (with dates, so they animate fine) but little/no
  severity. **Mode 1 runs through the newest perimeter year; Mode 2 fills only through the
  newest complete mosaic year**, with recent fires as outlines. Badge the provisional tail.
- **"No pixels" ≠ "didn't burn"** for the newest mosaic year (mosaic extents are cropped to
  that year's mapped fires).
- Perimeters always come from the perimeter shapefile, never inferred from mosaics.
- **MTBS threshold:** ≥1,000 acres in the West, so this is "all significant fires," not
  literally all fires. WFIGS could supplement later (see `recommendation.md`).
- **2025 is started but unusably sparse** — the July 2026 perimeter release has 33 fires
  across 8 states for 2025 (and 2 records dated 2026), vs. ~300/yr typical. WA has none. The
  build therefore cuts at 2024-12-31; revisit when MTBS finalizes 2025.

## Milestones

1. ~~**Base map**~~ ✅ bland dark vector base, coastline, progressive detail tiers, toggles,
   satellite. (OpenFreeMap; Protomaps extract deferred.)
2. ~~**WA test slice**~~ ✅ 643 fires, 1984–2024, animating with real ignition dates.
3. ~~**Full-scope perimeter build**~~ ✅ 11 states × 41 years, 11,377 fires, 2.8 MB gzipped.
4. **Confirm animation performance on real hardware** (desktop, then a phone) — the open item,
   now more pressing at 11,377 fires / 478k vertices.
5. **Severity layer** — build the raster half of the pipeline so Explore colors by MTBS
   severity instead of year, with the plain-language legend (shade loss / deadfall / canopy).
   Move to PMTiles on R2 at the same time.
6. **Explore polish** — mobile-responsive layout, then pick the new name.
