# Basemap Research — Options & Recommendation

Research for the open question flagged in `recommendation.md`: what base layer goes under the
burn-severity overlay. Requirements: hiking-grade terrain context (hillshade, contours, place
names, ideally trails), works in MapLibre GL JS, free/unmetered (project principle — no keys,
no bills that scale with usage), Western US coverage only. Verified July 2026.

## Option A — USGS "The National Map" tile services (raster)

- **URL:** `https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}`
  (note ArcGIS `{z}/{y}/{x}` order). Sibling services at the same root: `USGSImageryOnly`,
  `USGSImageryTopo`, `USGSShadedReliefOnly`, `USGSHydroCached`.
- **What it is:** USGS's multi-scale topographic reference map — contours, shaded relief,
  hydrography, boundaries, geographic names, transportation, land cover. Public domain,
  no key, no stated usage limits. Cached tile service, max zoom ~16.
- **Pros:** Zero pipeline work — one raster source line in the MapLibre style. Instant
  hiking credibility (real contours + relief + names). Public domain. US-only coverage is
  exactly this project's scope.
- **Cons:** Raster — no restyling: can't dim it, can't move labels above the severity fills,
  can't adjust contour density. Baked-in labels can get muddy under translucent overlays.
  Government service: no SLA, occasionally slow. Overzooming past z16 goes blurry (fine —
  severity data tops out at z12–13 anyway).

## Option B — Self-hosted composite stack (vector, matches the project architecture)

Three free, unmetered pieces that MapLibre composes natively:

1. **Protomaps basemap extract, self-hosted on R2.** Protomaps publishes free daily planet
   builds (z0–15, ~120 GB) at `build.protomaps.com`; `pmtiles extract --bbox=<western US>`
   pulls a regional extract (planet Europe ≈ 30–50 GB, so the 11 Western states likely land
   in the ~5–15 GB range — verify during the validation slice). Same PMTiles-on-R2 serving
   path as the severity layer. OSM-derived (ODbL attribution required). Streets-style
   schema: roads, water, labels, landcover — **no terrain**, which is what pieces 2–3 add.
   (Fully deliberate custom styling: dim the base so severity fills pop.)
2. **Hillshade from AWS Terrain Tiles.** Terrarium-encoded elevation PNGs on the AWS Open
   Data program: `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png` —
   free, no key, no auth. MapLibre consumes it directly as a `raster-dem` source
   (`"encoding": "terrarium"`) and renders hillshade client-side (US elevation derives from
   ~10m USGS NED/3DEP). Also unlocks MapLibre 3D terrain later, from the same source.
3. **Contours via `maplibre-contour`.** The onthegomap plugin (same author as Planetiler)
   generates vector contour lines client-side from the *same* terrarium DEM tiles —
   marching squares in a worker, styled/filtered like any vector layer. No contour tile
   pipeline to build.

- **Pros:** No keys, no metering, no third-party runtime dependency except AWS open data;
  base lives on R2 next to the severity archive; full styling control (dimmed base, labels
  *above* severity fills, contour density per zoom) — the severity overlay will read far
  better than over any baked raster.
- **Cons:** Real work — a custom MapLibre style is a design task (start from a Protomaps
  "light/grayscale" theme and dim it, but still). ~5–15 GB on R2 exceeds the 10 GB free tier
  when combined with severity data (storage is $0.015/GB-month — cents, but nonzero).
  Quarterly-ish basemap refreshes are manual re-extracts. OSM trails exist in the data but
  styling them well is its own project.

## Option C — Hosted free-tier services (rejected for v1 core, fine as fallbacks)

- **OpenFreeMap** — free hosted OSM vector tiles + ready styles, explicitly no key, no
  registration, no request limits (public instance at `tiles.openfreemap.org`, MIT, actively
  maintained). The zero-effort vector-base variant of Option B piece 1 — same no-terrain
  caveat. Legitimate shortcut: swap it in for the Protomaps extract until self-hosting is
  worth it; the hillshade/contour pieces are identical.
- **Stadia Maps Outdoors** — polished outdoor style, free non-commercial tier, but keyed +
  credit-metered. Violates the no-metered-services principle.
- **MapTiler Outdoor** — the best-looking hosted outdoor style; free tier is 100k
  requests/month, keyed, non-commercial, hard-stops when exhausted. Same objection.
- **OpenTopoMap** — free raster topo, but CC-BY-SA, fair-use policy discourages app usage,
  and it's served from Germany (slow from the US West). Prototyping only.

## Recommendation

**v1: Option A (USGS Topo raster) as the shipping base, with Option B's hillshade wired in
from day one where useful.** Rationale: v1's job is validating that severity-over-terrain is
useful for hike planning; USGS Topo delivers full hiking context (contours, relief, names) for
one line of style JSON and zero pipeline, honoring the "personal tool, don't over-engineer"
principle. CalTopo renders its fire-history layer over exactly this kind of topo raster, so
overlay readability is proven, not hypothetical — use mostly-opaque severity fills.

**v1.1+ upgrade path: Option B** (Protomaps extract on R2 + terrarium hillshade +
`maplibre-contour`), *if* v1 surfaces the predictable raster-base pains: labels buried under
fills, no way to dim the base, USGS service slowness. Swapping the base is additive — the
severity PMTiles layer and all MapLibre overlay code are unchanged — so nothing in v1 needs
to anticipate it beyond keeping overlay style code separate from base style JSON. OpenFreeMap
is the low-effort intermediate if self-hosting the extract isn't yet justified.

Base-layer toggle (Topo / Imagery via `USGSImageryTopo`) is cheap with two raster sources and
genuinely useful for hikers — worth including in v1.
