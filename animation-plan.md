# Animation Plan — 40-Year Western Fire Visualization

## What this is

A visualization of **every Western US wildfire in the ~40-year MTBS record (1984–present)**.
On load, an animation steps through the record one year at a time: each year's fires appear at
full intensity, then fade with age without disappearing, so the run accumulates into one picture
of four decades of burning, which is where it stops. A click parks the animation on the year it
is showing, and panning and zooming work throughout.

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
| Animation granularity | **One state per year** — 41 discrete states, 0.75 s each (~31 s total). No within-year ignition timing |
| Animation fade model | **Accumulate & fade** — a year's fires stay on the map, dimming with age toward a still-visible ember floor; the final frame shows all 40 years at once |
| Interaction | **One control, two axes.** The rail scrubs years on the timeline and repeat levels in repeat mode; tapping its handle cycles the three views. A click (or a rail drag) parks the animation on the year it is showing; panning and zooming work at all times |
| Fire mark | **Filled perimeter polygon only.** No glow — see "Why the glow is gone" |
| Map stack | **MapLibre GL JS.** No account, token, or metered billing |
| Base map | Bland at overview zoom, progressively more detail as you zoom |
| Geometry detail | **~200 m simplification (`-simplify 0.002`)** — settled; finer variants were built but proved unnecessary in practice |

The base map is **decoupled** from the animation/data layers, so swapping it later (even to
Mapbox/MapTiler) touches only the base style — nothing in the animation engine.

## Interaction — one control

There is no animation/explore split. The map is always live:

- **Plays on load** — 41 yearly states, 0.75 s each ≈ 31 s.
- **A click parks it** on the year currently showing, and names the fire clicked (if any).
  Fires from years not yet reached are ignored by the hit test.
- **The year rail** down the right edge pauses and jumps to any year; it snaps to whole years.
  There is no play button — grabbing the rail *is* the pause.
- **Pan and zoom work throughout**, playing or paused — MapLibre never blocked them, which is
  why a separate "explore mode" turned out to be unnecessary.
- `?year=1995` parks on a given year, `?mode=year|repeat` opens a view, `?level=4` sets the
  repeat floor (a count, not an index — the two datasets number their levels differently).

**Three views, named in the title panel.** A segmented control under the stat row — *All years
/ One year / Repeats* — with the active one wearing `--hot`, the same brick as the handle and
the bar. It sits there because choosing *Repeats* rewrites the stat row directly above it, and
because the app's position is one panel and no on-map controls. Tapping the rail's handle still
cycles the same three (and `m` still works): the buttons teach that gesture rather than
replacing it. Every path goes through one `setMode()`, so none of them can leave the buttons
out of step with the map.

| Mode | What it shows | What the rail carries |
|---|---|---|
| `all` (default) | Every year up to the one on show, fading with age. Colour encodes **recency only** | Year, 1984 → 2024 |
| `year` | That season alone, at full flare | Year, 1984 → 2024 |
| `repeat` | Ground that has burned more than once, coloured by **how often** (#8) | Repeat level, 2× → 9× |

`repeat` steps outside the timeline — a burn count is a fact about all 41 years, not about a
year — so **the rail changes axis rather than freezing**: 2× at the bottom, 9× at the top, same
direction of travel (up = more). The level is a **floor, not a slice**: at 5+ the map shows
everything that has burned five times or more, so the picture stays graded instead of collapsing
to one shade, and pushing the handle up peels the commoner ground away rather than swapping one
map for another. What falls below the floor is not hidden — it drops back to the dim ember that
every burned acre already wears underneath, which is what a reburn has to be read against.

Discoverability was the reason the buttons exist: the handle tap alone was a gesture nobody
would guess, and it hid two thirds of the app.

The year and the level are **separate state** (`idx` and `lvl`), so leaving repeat mode puts you
back on the year you left. Everything that positions or reads the handle goes through
`railN()` / `railIdx()`, so the rail's mechanics — drag, keys, settle, aria — are written once
rather than branched on the mode in five places. Tapping the handle is still the only way in or
out, which is what freed the drag gesture up for this in the first place.

The `all` end state — all 41 years, 2024 hot, 1984 faint — is simply where the animation stops.

**Pace note:** the pace is *per year* (0.75 s/yr), so total duration grows as the record grows.
A fixed total duration was considered and rejected: constant per-year pace keeps "the speed of
time" legible.

**Future:** MTBS burn **severity** colouring, once the raster half of the pipeline is built.
That was the original reason to keep severity data; it is not wired up yet. It would most likely
arrive as a second colour table applied when the animation is parked, not as a new mode.

## Base map design

MapLibre GL JS, composed of independent, individually-styleable layers. Detail tiers in by zoom:

| Zoom | What appears |
|---|---|
| ≲ 4 (continental) | Dark ground, state boundaries, coastline, interstates — the animation backdrop |
| ~5–8 (state) | Cities and towns, major rivers |
| ~9–11 | Villages, hamlets, neighborhoods; forest/park shading; secondary roads |
| ~11–13 | Streams, canals; minor roads |
| 13+ | Buildings |

- **Source:** **OpenFreeMap** hosted vector tiles (free, no key). Upgrade path: a **Protomaps
  extract of the 11 Western states** on R2, same PMTiles-on-R2 serving as the fire data.
- **Coastline** is an explicit stroke, so the land/water edge reads as clearly as state lines.
- **No user-facing layer toggles** — these are styling decisions, not user choices.
- **Satellite removed.** It was wired up but never used; re-add as a raster source + layer when
  wanted (Esri World Imagery / USGS Imagery are both free and keyless).
- **Base tiles stop at z14.** Past that the base is stretched, not resampled — inherent to
  OpenFreeMap, and the reason the Protomaps extract is the eventual fix.

## Animation engine

### The whole design in one paragraph

The animation's entire state is **one integer**: `idx`, the index of the year on show. Two
lookup tables — `COLOR[age]` and `OPACITY[age]`, indexed by age *in years* — are built once at
startup from six anchor stops. There is **one fill layer per ignition year** with a static
filter, and showing a state is a single loop that assigns each layer a **constant** colour and
opacity by its age (`idx - k`), hiding years that haven't happened yet. Play is `setInterval`
at 750 ms; pause is `clearInterval`.

```
function show(i) {
  idx = clamp(i, 0, N - 1);
  for (let k = 0; k < N; k++) {
    const a = min(idx - k, AGES - 1);          // age of year k, in years
    setPaintProperty(layers[k], 'fill-opacity', a < 0 ? 0 : OPACITY[a]);
    if (a >= 0) setPaintProperty(layers[k], 'fill-color', COLOR[a]);
  }
}
```

### Why this shape

- **Every paint value is a constant scalar** — a GPU uniform. Nothing is *data-driven* (no
  paint property reads a feature attribute), so no per-vertex attribute buffers are ever
  recomputed or re-uploaded.
- **41 discrete states**, so the entire state space can be enumerated and asserted.
- **No continuous time**: no elapsed-time maths, no `requestAnimationFrame`, no quantisation,
  no change detection, no orphaned-loop guard. `clearInterval` cannot leave a loop running.
- **One colour model**, in JS, as tables — not duplicated as a GL expression, and not
  duplicated again for a second view mode.
- MapLibre's default 300 ms paint transition cross-fades between yearly steps **for free**.

### Palette

Anchors (age in years → colour, opacity), interpolated once into 41-entry tables:

```
0 yr   #fff2b0  0.95    this year — flare
1 yr   #ff9526  0.85
3 yr   #ff5f1a  0.75
8 yr   #e83c17  0.66
20 yr  #b23016  0.59
40 yr  #8f2a15  0.55    ember floor — never invisible
```

The floor matters: an earlier version faded old fires to near-black, which made them vanish
against the dark base and left the end frame nearly empty.

**Draw order:** layers are added oldest-year-first, so newer fires draw on top and reburns don't
turn to mud. No sort key needed.

### Why one layer per year (and not age bands)

A layer's colour depends only on its year, so it never needs a per-feature expression. Using
~6 *age bands* instead would require fires to migrate between layers as time advances — which
means changing filters, which forces re-layout. Far worse. 41 layers is the cheap option.

### Accepted tradeoffs
- **No within-year ignition timing.** A year's fires appear together. (Earlier builds animated
  exact ignition dates via a data-driven expression on the active season; that expression was
  the source of a long-running bug — see below.)
- **The scrubber snaps to whole years.**
- **Completed and current years share one model**, so the newest year sits at the brightest
  colour while at rest. That is intended: newest = hottest.

## Debugging history — mistakes worth not repeating

The engine went through several wrong turns. Each left a lesson in the code:

1. **Data-driven paint every frame (4.5 fps).** The first version set four data-driven paint
   properties (fill/line colour and opacity) per frame across ~87k vertices. Each change
   re-derives and re-uploads per-vertex attribute buffers for every feature in every tile.
   *Lesson: constant paint = uniform = free; data-driven paint = per-vertex work.*
2. **`setData` per step (the big one).** A "cheap" flare glow rebuilt its GeoJSON source ~24×/s
   to hold only currently-flaring fires. **Every `setData` re-tiles the whole source in the
   worker**, so a run queued hundreds of layout jobs that kept draining — and replaying stale
   blooms — for minutes after the clock stopped. This produced the "fires keep flashing long
   after the end" symptom. *Lesson: never mutate a source to animate; change paint instead —
   or better, don't animate that thing at all.*
3. **A layer added with `visibility: 'none'` is never laid out.** The old Explore layer was
   created hidden; MapLibre skips layout for hidden layers, and flipping visibility later does
   not re-run it. The layer was visible but held **zero features**, so clicking the map wiped
   all fires. *Lesson: don't gate a layer's existence on initial visibility.*
4. **An invalid paint expression silently drops the whole layer.** Multiplying two
   `interpolate`s for the glow radius (`['*', interpolate…, interpolate…]`) is invalid — `zoom`
   may only be the input to a *top-level* interpolate/step. The layer failed to load and
   nothing said so until `map.on('error')` was wired up. *`map.on('error')` is now always on.*
5. **Stale builds wasted real time.** Browser caching and leftover headless-browser processes
   (Chrome replays buffered console output on `Runtime.enable`) produced "verifications" of code
   that wasn't running. *Hence `serve.py` (sends `no-store`) and a `BUILD` number shown in the
   UI and stamped on every debug log line.*

**Why the glow is gone:** it caused (2), it caused (4), and it was the visible symptom of both.
Removed entirely rather than debugged further. Fires are now just their perimeters.

## Build pipeline

### Perimeters — ✅ built (drives the animation)

The MTBS perimeter shapefile is one national file, so no per-state download:

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
stops cleanly at state lines. `year` is derived client-side from `ig_date`.

Datasets ship **gzipped and are inflated in the browser** (`DecompressionStream`), so a static
host needs no content-encoding config; gzip magic-byte detection means it also works if the host
*does* send `Content-Encoding: gzip`.

### Simplification — why, how, and what it costs

**Why it's necessary.** MTBS derives perimeters from 30 m Landsat pixels, so boundaries trace
pixel edges in tiny stair-steps. The unsimplified 11-state extract is **476 MB / 17.8 M
vertices**. One fire is a pathological outlier: **NORTH (2020-08-02)**, only 6,827 acres,
carries **2,030,049 vertices** — a perimeter so crenulated it exceeds GDAL's default per-feature
read limit — while the 979,722-acre **Dixie** fire needs ~1,000.

**Two independent levers:**

1. **`-simplify 0.002`** — the big win. Douglas–Peucker: chord a line's endpoints, find the
   furthest vertex; if it exceeds the tolerance keep it and recurse, else discard every
   intermediate vertex.
2. **`-lco COORDINATE_PRECISION=4`** — trims bytes, not geometry. GDAL defaults to 7 decimals
   (~1 cm), absurd for 30 m source data; 4 decimals is ~11 m.

**Tolerance-units gotcha:** `0.002` is **degrees, not meters** (output is EPSG:4326). North–south
that's ~222 m everywhere; east–west it shrinks with latitude — ~190 m in southern AZ vs ~145 m
at the Canadian border. Simplifying in a projected CRS (the source's Albers) would give uniform
meters if this ever needs to be exact.

**Tolerance chosen: `0.002°` (~200 m).** Measured across the 11 states:

| `-simplify` | raw | gzipped | vertices |
|---|---|---|---|
| none | 476 MB | — | 17,848,142 |
| 0.0005 | 32.1 MB | 9.1 MB | 1,380,482 |
| 0.001 | 20.1 MB | 5.8 MB | 830,415 |
| **0.002** | **11.5 MB** | **2.9 MB** | **478,015** |
| 0.004 | 7.3 MB | 1.8 MB | 266,825 |

**Verified fidelity at 0.002** (raw vs. simplified, via OGR):

| | raw | simplify 0.002 |
|---|---|---|
| Features | 11,377 | **11,377** — none lost |
| Rings | 13,366 | 13,368 |
| Vertices | 17,848,142 | **478,015** (−97.3%) |
| Total area | 52.6074 deg² | 52.3763 deg² (**−0.44%**) |
| Invalid geometries | 34 | **7** |

**37× fewer vertices for 0.44% area distortion, with no fire dropped.** Web-Mercator resolution
at ~41°N makes this invisible where it matters: z4 ≈ 7,400 m/px (200 m is 1/37 of a pixel),
z8 ≈ 460 m/px (still sub-pixel), z12 ≈ 29 m/px (~7 px — visible softening). Finer datasets
(0.001, 0.0005) were built and measured but **not needed in practice**, so 0.002 ships.

**Two caveats:** plain `-simplify` is not topology-preserving (`-simplifyPreserveTopology` is
the safer, slower option) — here it was benign, and invalid geometries actually *fell* from 34
to 7, since simplification erased some self-intersecting stair-steps. Note the **source data
ships with 34 invalid geometries of its own**. And one global tolerance is inherently a
compromise; the PMTiles/tippecanoe step below generalizes *per zoom level* instead.

### Repeat burns — ✅ built (`pipeline/build-repeats.sh`)

Where has the same ground burned more than once? Pairwise polygon overlay over 11,377
perimeters is the obvious answer and the wrong one — it is O(fires²) of exact geometry, and
this engine deliberately does no runtime geometry at all. Counting on a raster is O(area) and
gets the whole answer in 40 seconds:

```
gdal_rasterize -burn 1 -add -tr 90 90   # each cell = how many perimeters cover it
gdal_sieve.py  -st 16 -nomask           # drop the sub-32-acre fringe between adjacent fires
gdal_calc.py   "255*(A>=2)"             # count 1 is just "burned" — the animation has that
gdal_polygonize.py -mask …              # 10,872 polygons carrying `count`
ogr2ogr -t_srs EPSG:4326 -simplify 90   # → app/data/west_repeats.geojson.gz, 1.8 MB gzipped
```

Grid is **EPSG:5070 (Conus Albers), 90 m cells** — equal-area, so a count means the same thing
in Arizona as at the Canadian border, and one cell is ~2 acres. Findings:

| burned | acres | share of footprint |
|---|---|---|
| once | 77.5 M | 80.3% |
| twice | 15.0 M | 15.5% |
| 3× | 3.0 M | 3.1% |
| 4× or more | 0.9 M | 0.9% |

Deepest is **9 fires, 1992–2016, on one hillside in the Santa Lucia Range** behind Big Sur.

**Prescribed fire is included, and checked rather than assumed** — burn units are re-burned on
purpose, so they could have made this a map of land management instead of fire. They don't:
only 4–7% of reburned acreage involves *any* prescribed fire, and ≤2.6% involves two or more.

**Two tunings worth keeping:**

1. **`-simplify` is per-feature, and these polygons tile a coverage**, so neighbours pull apart
   by up to the tolerance and leave a hairline crack that shows from ~z10 in. 150 m gets the
   file to 1.2 MB but the cracks are visible; 60 m is clean at 3.4 MB; **90 m — one cell — is
   clean enough at 1.8 MB**, and "no vertex moves further than the grid it came off" is a rule
   that explains itself. GDAL has no coverage-aware simplifier, so this is the lever available.
2. **The script deletes its outputs before it runs.** `gdal_rasterize` *updates* an existing
   target rather than replacing it — a second run would silently add its counts on top of the
   first's and double every number in the table above.

**In the browser** the asset is one fill layer per count (2…9) over the year layers, each with
a constant colour and a constant opacity — the same no-data-driven-paint rule as everything
else, and eight more uniforms rather than N. The rail sets which counts are lit. Each fill also
gets a **hairline ring**, sized in screen pixels and gone by z9: a patch smaller than a pixel
leaves a fill with nothing to draw, which reads as "this level is empty" when it is not, and at
z4 the ring recovers 25–50% more visible mark at levels 3–7.

It **cannot** rescue 8× and 9×, and nothing in the paint layer can — MapLibre's own tiling drops
rings under its simplification tolerance, so below **z6** those two counts have no geometry at
all. `tolerance: 0` on the source does make them draw, at **830 ms of blocked main thread per
retile against 225 ms**, to gain a single pixel. Not taken: at z6 and closer they render
normally, and zoomed out the acreage in the stat row is what carries them.

Each polygon also ships its `acres`, measured in Albers before simplification, which the app
sums per level. That is what the stat row reports — 18,909,948 acres at 2+ down to 144 at 9+ —
on the same bar the year stat uses, so the bar visibly collapses as the handle climbs.

The asset is **never fetched while the animation is running**:
1.8 MB inflates and parses in ~75 ms of blocked main thread, which is a dropped frame or two,
so the load waits for the run to end or for anything to pause it — including the tap that asks
for the view. Measured: fetch starts at 31.1 s on a plain load, 1.1 s when opened parked, and
4.6 s when the mode is tapped into 4 s in.

Only the counts are stored, not *which* years overlapped; that needs true polygon overlay
(shapely/PostGIS) and a much heavier job. Build it only if the popup ever needs to say more
than "burned 9 times".

### Verifying the counts — `pipeline/verify-repeats.py`

The counts are checked against the source by a method that shares no code with the build:
exact point-in-polygon against the 11,377 MTBS perimeters. Run 2026-07-27, 800 samples per test:

| Test | Result |
|---|---|
| **A.** Points inside shipped patches — does `count` match the perimeters actually covering them? | 97.2% overall; **100%** (581/581) for every point more than 130 m from a patch edge |
| **B.** Points anywhere in the burned footprint — is any reburn *missing*? | 97.8% overall; **100%** (260/260) more than 500 m from any patch |
| **C.** Conservation: Σ count × cell area vs. the summed area of all 11,377 perimeters | 120,451,471 vs. 120,749,138 acres, **−0.247%** |

Every one of the 40 disagreements is attributed to a known lossy step — 19 simplification,
12 rasterisation (pixel-centre rule), 9 sieve — with **none unexplained**. All of them sit within
a patch boundary's ~130 m ambiguity zone, which is what the 90 m grid plus 90 m simplification
buys. The script prints the attribution, so a real error would show up as `UNEXPLAINED`.

**The limit no sampling can test.** MTBS perimeters are mapped fire *boundaries*, and they
contain unburned ground: in the 2023 CONUS severity mosaic, **15.8% of the area inside mapped
perimeters is classed "unburned to low"**. So this layer strictly means *"inside N mapped fire
perimeters"*, not *"burned N times"* — the two diverge by roughly that much. Fixing it means
counting on the severity mosaics rather than the perimeters, which is the milestone below.

### Still to build

1. **Severity (drives at-rest colouring):** per-year CONUS thematic mosaics 1984–2024 from
   ScienceBase (confirmed: 41 child items, no gaps), clipped to the 11-state union,
   `gdal_sieve` → `gdal_polygonize` in native Albers → reproject → merge. The validation run
   extrapolates ~450 state-years to minutes of compute and a low-hundreds-of-MB archive.
2. **PMTiles** via tippecanoe: a `perimeters` layer (all years, with `year`) + a `severity`
   layer (complete years), maxzoom ~z12–13, on R2. Removes the GeoJSON size ceiling and
   generalizes per zoom.
3. **Base map:** Protomaps 11-state extract → R2 (replacing OpenFreeMap), which also lifts the
   z14 detail ceiling.

## Data caveats (still true)

- **Provisional tail (mosaic lag ~2 yr):** severity mosaics are complete only through ~2023;
  the newest 1–2 years have perimeters (so they animate fine) but little/no severity. Badge the
  provisional tail once severity is wired up.
- **"No pixels" ≠ "didn't burn"** for the newest mosaic year (mosaic extents are cropped to
  that year's mapped fires).
- Perimeters always come from the perimeter shapefile, never inferred from mosaics.
- **MTBS threshold:** ≥1,000 acres in the West, so this is "all significant fires," not
  literally all fires. WFIGS could supplement later.
- **2025 is started but unusably sparse** — the July 2026 perimeter release has 33 fires across
  8 states for 2025 (and 2 records dated 2026), vs. ~300/yr typical. WA has none. The build cuts
  at 2024-12-31; revisit when MTBS finalizes 2025.

## Milestones

1. ~~**Base map**~~ ✅ bland dark vector base, coastline, progressive detail tiers.
2. ~~**WA test slice**~~ ✅ 643 fires, 1984–2024.
3. ~~**Full-scope perimeter build**~~ ✅ 11 states × 41 years, 11,377 fires, 2.8 MB gzipped.
4. ~~**Animation performance**~~ ✅ 59–61 fps on real hardware.
5. ~~**Engine simplification**~~ ✅ integer-year states; engine 483 → 171 lines (−65%), no
   data-driven paint anywhere, and no view modes at that point. Fixed the long-standing "fires
   flashing after the end" bug.
6. ~~**Repeat-burn view**~~ ✅ (#8) a third mode on the same tap-the-handle gesture; 90 m burn
   counts precomputed offline, 10,872 polygons. The rail carries repeat level (2×–9×) in that
   mode instead of the year, so it still costs no new control.
7. **Severity layer** — build the raster half of the pipeline so a parked animation can colour by
   MTBS severity, with a plain-language legend (shade loss / deadfall / canopy loss). Move to
   PMTiles at the same time.
8. **Mobile** — the layout is desktop-first; panels are fixed-width and the popup needs a
   touch-friendly close target.
9. **Pick the new name.**
