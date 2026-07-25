# Basemap Research — Options & Recommendation

> **Outcome (2026-07-25): Option A was NOT adopted.** This doc was written for the project's
> hike-planning framing, where the base needed hiking-grade terrain context. The project is now
> a **40-year fire visualization** (`animation-plan.md`), which inverts the requirement: the
> base must be **bland and dark** so fire flares dominate, **vector** so it can be dimmed and
> restyled, and **progressively detailed** so it still works as a real map when exploring.
> A raster topo base can't be dimmed or re-ordered, so the shipped choice is the *vector* path
> — **Option C (OpenFreeMap) now, Option B (Protomaps extract on R2) as the upgrade** — with a
> free satellite raster as an optional toggle (Esri World Imagery / USGS Imagery). The research
> below stands; only the recommendation at the bottom is superseded.

Original requirements (hike-planning era): hiking-grade terrain context (hillshade, contours,
place names, ideally trails), works in MapLibre GL JS, free/unmetered (project principle — no
keys, no bills that scale with usage), Western US coverage only. Verified July 2026.

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

### Superseded (hike-planning era)

> ~~**v1: Option A (USGS Topo raster) as the shipping base**, with Option B's hillshade wired in
> where useful — full hiking context for one line of style JSON and zero pipeline, with Option B
> as the v1.1+ upgrade if the raster base chafed.~~
>
> Why it was dropped: the visualization needs the base *out of the way* during the animation.
> A raster topo base can't be dimmed, can't put labels above the fire fills, and its baked
> contours/relief compete with the flares — exactly the pains this doc predicted, now
> load-bearing rather than hypothetical.

### Current (40-year visualization)

**Shipping now: Option C — OpenFreeMap hosted vector tiles.** Free, no key, no registration, no
request limits; OpenMapTiles schema, so the named source-layers (boundary, water, waterway,
place, transportation, landcover, park, building) can each be styled and zoom-gated
independently. That's what makes the base both bland at continental zoom and a genuine scalable
map as you zoom in. Styled dark and low-contrast, with an explicit **coastline stroke** so the
land/water edge reads as clearly as state boundaries.

**Upgrade path: Option B piece 1 — a Protomaps 11-state extract on R2**, same PMTiles-on-R2
serving as the fire data, when self-hosting is worth it (no third-party runtime dependency,
full control). Layer definitions barely change; it's a source swap.

**Satellite toggle:** a raster layer, off by default — **Esri World Imagery** (free with
attribution) or **USGS Imagery** (public domain). This is what makes Mapbox unnecessary: the
one capability that seemed to require it is available as free public raster.

**Terrain (Option B pieces 2–3 — terrarium hillshade + `maplibre-contour`)** is deferred, not
rejected. It's additive whenever it's wanted, and would matter more if severity-over-terrain
ever becomes a focus again.
