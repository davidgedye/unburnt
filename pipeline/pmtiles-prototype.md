# PMTiles prototype — 2020 (run 2026-07-28)

Milestone 7, prototyped on one year to find out what moving off whole-file GeoJSON actually
buys and costs, before committing to a 41-year migration.

**Verdict: it works, it is dramatically better to look at, and it makes the app download *less*,
not more. The catch is storage — the full-record tileset is ~3.5 GB, which means R2 rather than
git.** Recommended, with one tuning change (see "z9" below) before the real build.

## Why

Everything the app ships today is a single GeoJSON, downloaded and parsed before anything
draws, so one simplification tolerance has to serve every zoom at once. At `-simplify 0.002`
that is right at z4 and **~15 screen pixels wrong at z13**:

| zoom | m/px | perimeter error (0.002°) | severity error (0.0015°) |
|---|---|---|---|
| z10 | 117 | 1.9 px | 1.4 px |
| z12 | 29 | 7.6 px | 5.7 px |
| **z13** | **14.6** | **15.2 px** | **11.3 px** |
| z14 | 7.3 | 30.3 px | 22.7 px |

One 30 m source pixel is one screen pixel at **z12**, so the data supports about four more zoom
levels than the app shows. Tiles generalise *per zoom*: coarse at z4, full 30 m at z13.

## What was built

`pipeline/build-pmtiles.sh 2020` — 2020 is the peak year (366 western fires, 9.2 M acres),
contains DOLAN, and contains **NORTH**, the 2,030,049-vertex perimeter that trips GDAL's
per-feature limit. Deliberately the hard case.

Perimeters extracted with **no** `-simplify`; severity extracted with a minimal sieve and **no**
vector simplification (`pipeline/severity-full.py`). tippecanoe does all the generalising:

```
tippecanoe -Z4 -z13 --detect-shared-borders --coalesce-densest-as-needed \
  --named-layer=perimeters:perims-2020.geojson \
  --named-layer=severity:severity-2020-s8.geojson
```

`--detect-shared-borders` is the one that matters for severity: those polygons tile a coverage,
and per-feature simplification pulls neighbours apart. That is exactly the pale-band artifact
the shipped app has to paint over with `sel-unmapped`.

## Numbers

Full-fidelity input, one year:

| | polygons | vertices | raw GeoJSON |
|---|---|---|---|
| perimeters | 366 | — | 66 MB |
| severity, sieve 4 px | 493,265 | 17.6 M | 478 MB |
| severity, sieve 8 px | 257,284 | 14.4 M | 372 MB |

Sieving from 4 px to 8 px halves the polygon count but cuts only 22% of the bytes — **the cost
is vertices, i.e. the 30 m pixel staircase itself**, not speckle.

Tilesets:

| config | tileset (1 year) | build |
|---|---|---|
| sieve 4, `--no-tile-size-limit` | 131.9 MB | 127 s, 1.31 GB peak |
| sieve 8, default limits | **93.3 MB** | 235 s, 1.29 GB peak |

10,097 tiles, z4–z13, mvt, gzip-compressed internally.

**Extrapolated to 41 years: ~3.5–3.8 GB.** That is the honest price of true 30 m fidelity.

## The number that decides it

A multi-GB tileset is irrelevant to the user, because only viewport tiles are fetched. Measured
against the prototype, by byte range, exactly as it would read from R2:

| view | range requests | transferred |
|---|---|---|
| z13, one fire close up | 10 | **89 KB** |
| z10, a fire in its landscape | 9 | 330 KB |
| z6, northern California | 11 | 1,589 KB |
| z4.2, the whole West | 8 | 296 KB |

Compare with today: **3.15 MB of perimeters downloaded and parsed up front**, before anything
draws, plus per-fire severity on click. The tiled version shows *more* detail for *less*
traffic, and spreads it over the session instead of paying it all at load.

### z9 — the one tuning change to make first

z6 pulling 1.6 MB is waste: severity at that zoom is far below a pixel and cannot be seen.
Rebuilt with the severity layer as `-Z9 -z13`, measured:

| | tileset | tiles | min zoom |
|---|---|---|---|
| severity z4–13 + perimeters z4–13 | 93.3 MB | 10,097 | 4 |
| **severity z9–13 only** | 75.1 MB | 9,820 | 9 |

So severity below z9 was only ~8 MB of storage — **the saving is not really in bytes stored, it
is in bytes fetched**. Those tiles simply do not exist any more, so the 1.6 MB regional fetch
becomes zero and the severity layer cannot be requested where it is invisible. Worth doing for
that reason alone, and it also cuts ~60% off the tiling time (90 s vs 235 s).

## What it looks like

`pipeline/pmtiles-proto.html` renders the tileset in the app's own palette and type, so a
screenshot from it sits directly next to one from the app. At z13 over DOLAN's coastal edge:

- **shipped**: large angular blobs, the perimeter cutting straight chords across the coastline,
  wide dark gaps where simplification pulled polygons apart
- **tiled**: individual 30 m severity pixels, the perimeter following the actual coast

## Running it

```
pipeline/build-pmtiles.sh 2020                       # ~8 min incl. severity extraction
python3 rangeserve.py 8082 pipeline                  # Range-capable static server
open http://localhost:8082/pmtiles-proto.html
```

A Range-capable server is required and is the point: MapLibre's `pmtiles://` protocol reads the
single file by byte range, which is how it would read from R2 — **no tile server, and still no
Worker script**. Python's stock `http.server` answers 200 to a Range request and will not work.

## What this does not fix

- **The basemap still stops at z14** (OpenFreeMap stretches past it). Zooming far enough to
  enjoy 30 m detail gives a blurry base. Same R2 move fixes it — a Protomaps extract — so the
  two belong in one piece of work.
- **Below ~30 m there is nothing real to show.** The staircase is quantisation, not geography.
  z13 is the honest ceiling; the app's `maxzoom: 17` is already optimistic.
- **Build cost**: ~4 min of tiling per year plus severity extraction, ~1.3 GB peak RAM, and the
  mosaics have to be re-downloaded (~200 MB) since the severity build deletes them.

## The full build — `pipeline/build-pmtiles-all.sh`

Written and tested end to end on 2023 + 2024 (resume, per-year build, multi-year merge, and
rendering the merged tileset). Per year: fetch the mosaic → perimeters at full fidelity →
severity at full fidelity → tag the perimeters with `sev_ok`/`sev` → two tippecanoe runs →
`tile-join` into one year tileset → delete everything transient. Then merge all years in
batches of eight.

Two tilesets per year because the layers want different minzooms and tippecanoe takes one per
run:

- **perimeters from z2**, because the app's `minzoom` is 2.5 and a source has no tiles below its
  own minzoom — fires would simply vanish on a small window. With `--no-tile-size-limit`:
  dropping features to fit a tile would silently delete fires from the accumulated view, which
  is the one thing this map must not do.
- **severity from z9**, so a regional view cannot fetch something that is far below a pixel.

Resumable: a finished year is skipped, each tileset is written under a temporary name and
renamed only on success, and a kill loses at most the year in flight.

### Two bugs the end-to-end test caught

1. **`tile-join` has no `-q`.** It is not in the usage string, and the unrecognised flag gets
   taken as an input filename — which surfaces as `pmtiles_magic_number_exception`, pointing at
   the data rather than the flag.
2. **`tile-join` picks its output format from the file extension.** The write-to-temp-then-rename
   safety pattern used `2024.tmp`, which produced an *mbtiles* that was then renamed to
   `.pmtiles`: a plausible-looking file with the wrong magic number, and the failure only shows
   up much later at merge time. The temporary name has to keep the `.pmtiles` extension.

Measured on 2024 (89 of 299 fires have severity) and 2023 (259 of 272): **~60 s per year** with
the mosaic already local, 14–16 MB per year tileset.

## Migration notes

- The animation engine survives unchanged: one layer per year with a **static** filter works the
  same on a vector-tile source, so no data-driven paint creeps back in.
- Worth checking ~130 layers against a tiled source before committing.
- Severity would stop being per-fire files fetched on click and become part of the tileset.
  That loses "only pay for the fire you clicked", but tiles only fetch the viewport anyway, and
  at 89 KB for a close-up it is cheaper regardless. `sev_ok` and the popup breakdown stay on the
  fire, so the outline affordance is unaffected.
- `app/data/severity/` (10,505 files, 20.6 MB) would leave the repo entirely.
