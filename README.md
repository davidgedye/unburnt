# unburnt

A hiking-planning web tool that overlays historical wildfire burn **severity** (not just
recency) on a zoomable map, with active fire and smoke/AQI data planned for a later phase.

The gap this fills: existing hiker-facing tools (CalTopo, Gaia GPS) show *when* an area burned
(color-coded by year) but not *how badly* — MTBS's severity data exists and is public, but
nobody's surfaced it in a hiking-oriented tool. See `data-sources.md` for the full survey.

## Status

Planning complete; pipeline validated end-to-end on a WA × 2024 slice (2026-07-23) — see
`pipeline/pipeline-validation.md` for the run, screenshots, and findings (headline: MTBS
annual mosaics lag ~2 years, so the newest severity year is partial). See
`recommendation.md` "Next steps" for where to pick up; scaffolding and the full
11-state × 30-year build are next.

## Key decisions (see recommendation.md for full detail/rationale)

- **Scope:** all 11 Western states (WA, OR, CA, ID, NV, UT, AZ, MT, WY, CO, NM), last ~30
  years of burn data (deadfall/shade-loss hazards persist for decades, and the marginal cost
  over 10 years is small once severity is vector). Alaska deferred past v1 (separate MTBS distribution + projection;
  roughly doubles the pipeline for uncertain personal use).
- **v1 layer:** MTBS burn severity + perimeters only. No trails, no live fire/smoke/AQI,
  no offline — those are v1.1/v2.
- **Use case:** personal tool initially.
- **Platform:** Cloudflare end-to-end — Pages (frontend), Workers (live-data proxy for
  v1.1+), R2 (tile storage). Fire metadata ships as a static build-time JSON (~2k fires);
  D1 deferred until scale demands it. Matches the existing `booked` project's setup.
- **Map library:** MapLibre GL JS (open-source, free, native vector rendering + data-driven
  styling, native PMTiles support).
- **Tile format:** all vector, one PMTiles archive — severity-class polygons (vectorized from
  the MTBS classified raster) + fire perimeters as two layers, served straight from R2 with
  no tile server. Maxzoom capped at ~z12–13 (the honest limit of 30m source data); MapLibre
  overzooms vector tiles natively beyond that.
- **Mobile:** not required for v1, important for v2 — avoid decisions that would make
  responsive polish costly to retrofit later.

## Files

- `data-sources.md` — survey of every wildfire/smoke/AQI data source investigated (MTBS,
  WFIGS, CAL FIRE FRAP, NASA FIRMS, AirNow, NOAA HMS, PurpleAir), plus the competitive
  landscape (CalTopo, Gaia GPS, etc.).
- `recommendation.md` — which sources to use for which layer, the Cloudflare architecture,
  why MapLibre GL JS, what PMTiles is and why it fits, the locked-in v1 scope decisions, an
  ordered "next steps" list for when building starts, and the remaining open questions.
- `basemap.md` — basemap research and decision: USGS Topo raster tiles for v1 (public
  domain, no key, real contours/relief), with a documented vector upgrade path (Protomaps
  extract on R2 + AWS terrain hillshade + client-side contours) for v1.1+.
