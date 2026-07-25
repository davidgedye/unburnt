# Wildfire & Smoke Data Sources — Survey

Research compiled for the "unburnt" project: a **40-year visualization of Western US wildfire**
(1984–present) — an animation of the full MTBS record over a zoomable map, with burn severity
in an at-rest view. See `animation-plan.md` for the current plan.

**What this means for sources below:** MTBS is the backbone — its *perimeter* shapefile drives
the animation (it carries per-fire ignition dates, which is what makes within-season flare
timing possible), and its *severity* rasters drive the at-rest view. The active-fire, smoke, and
AQI sources were surveyed for the project's earlier hike-planning framing; they're now
out-of-scope extras rather than planned layers, kept here because the research is done and a
"current season" layer may still be worth adding.

## Historical burn severity & perimeters

### MTBS — Monitoring Trends in Burn Severity (USFS / USGS)
- **URL:** https://www.mtbs.gov/, REST: `https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_MTBS_01/MapServer/63`
- **What it has:** The only source with burn *severity* (low/moderate/high, via dNBR/RdNBR),
  plus fire perimeter polygons (shapefile).
- **Format:** Perimeters = vector polygon shapefile/GeoJSON. Severity = raster GeoTIFF
  (continuous dNBR and classified "thematic" severity), 30m resolution, also offered as
  pre-mosaicked-by-year rasters.
- **Coverage:** CONUS + Alaska, Hawaii, Puerto Rico. 1984–present.
- **Threshold:** ≥1,000 acres in the Western US, ≥500 acres in the Eastern US (~95% of total
  burned acreage captured).
- **Freshness:** Released roughly quarterly. Each fire is "Initial Assessment" (fast, imagery
  right after the fire — used for grass/shrub) or "Extended Assessment" (waits for the next
  growing season to capture delayed effects — used for most forest fires). Most recent season
  is typically still "provisional" until extended assessment completes — effectively a ~1 year
  lag before a season is fully finalized.
- **Pros:** Consistent 40+ year methodology, only severity data available, full Western US coverage.
- **Cons:** Misses sub-threshold fires, raster needs GIS preprocessing before it's web-map-ready,
  current season often incomplete.

### NIFC / WFIGS — Interagency Fire Perimeter History
- **URL:** https://data-nifc.opendata.arcgis.com/datasets/nifc::interagencyfireperimeterhistory-all-years-view/about
- **What it has:** Conglomerated historical fire perimeters from USFS, BLM, BIA, FWS, NPS,
  Alaska Interagency Fire Center, and CAL FIRE.
- **Format:** Vector polygons. GeoJSON export and ArcGIS REST FeatureServer (max 2,000
  records/page, paginate via `resultOffset`).
- **Coverage:** Nationwide, perimeters through the 2024 season (updated as seasons finalize).
- **Pros:** Broadest perimeter coverage (catches fires below MTBS's threshold), live REST API,
  good for "what burned recently."
- **Cons:** No severity data — perimeters only. Mapping precision varies by contributing agency
  (inconsistent methodology vs. MTBS).

### WFIGS — Current Interagency Fire Perimeters (active fires)
- **URL:** https://data-nifc.opendata.arcgis.com/datasets/nifc::wfigs-current-interagency-fire-perimeters/about
- **What it has:** Live perimeters for *currently active* fire incidents.
- **Format:** Vector polygons, GeoJSON + ArcGIS REST, no API key required.
- **Freshness:** Refreshed every 5 minutes; perimeter source changes may take up to 15 minutes
  to propagate.
- **Pros:** Best source for "here's the actual shape of the fire right now."
- **Cons:** Only exists for currently-active incidents (not a historical record).

### CAL FIRE FRAP — California Historical Fire Perimeters
- **URL:** https://data.ca.gov/dataset/california-fire-perimeters-all
- **What it has:** California-specific historical fire perimeters, annually maintained.
- **Format:** GeoJSON, Shapefile, KML, file geodatabase — all directly downloadable.
- **Coverage:** California only. Back to 1878 (high-confidence/complete data generally
  from ~1950 onward). Latest release `firep25_1` (April 2026) added 516 fires from 2025.
- **Pros:** Deepest historical record for CA, clean ready-to-use exports, includes
  containment/acreage attributes.
- **Cons:** California-only — doesn't generalize to the rest of the Western US. Largely
  redundant with WFIGS for CA, which already folds CAL FIRE data in.

## Active fire detection (points, not perimeters)

### NASA FIRMS — Fire Information for Resource Management System
- **URL:** https://firms.modaps.eosdis.nasa.gov/, API: https://firms.modaps.eosdis.nasa.gov/api/area/
- **What it has:** Satellite-detected thermal anomalies ("hotspots") from VIIRS (375m
  resolution, ~12hr latency in US/Canada) and MODIS (1km resolution, ~1-2 day latency).
- **Format:** SHP, KML, TXT, WMS, REST API.
- **Access:** Free `MAP_KEY` registration, rate limit 5,000 transactions/10min.
- **Pros:** Catches brand-new ignitions before any official perimeter has been drawn; fills
  gaps for small/remote fires.
- **Cons:** Points, not polygons — no shape/extent information, just detection locations.

## Smoke & air quality (live)

### AirNow (EPA + USFS) — Fire and Smoke Map
- **URL:** https://fire.airnow.gov/ (public map), API docs: https://docs.airnowapi.org/
- **What it has:** Real-time PM2.5/AQI readings from ~2,500+ official monitoring stations plus
  crowdsourced low-cost sensors.
- **Format:** REST API, queryable by bounding box or zip code.
- **Access:** Free registration, API key issued after approval (fast, no cost).
- **Freshness:** Updates roughly hourly.
- **Pros:** The actual data backing the public fire.airnow.gov map; simple, free, reliable.
- **Cons:** Point readings, not shaded plume regions — needs interpolation/styling to read as
  an "area" overlay.

### NOAA HMS — Hazard Mapping System Smoke Product
- **URL:** https://www.ospo.noaa.gov/products/land/hms.html
- **What it has:** Satellite-derived smoke *plume polygons*, classified light/medium/heavy,
  manually traced daily by NOAA analysts since 2005.
- **Format:** KML, shapefile, WFS, smoke text products.
- **Access:** Free, public, no API key.
- **Freshness:** Daily, initial product created/updated ~8–10am Eastern.
- **Pros:** Real shaded-region polygons (matches the visual style of the burn-severity layer),
  no key required.
- **Cons:** Daily cadence (not continuously live), human-traced (some lag/manual judgment
  involved), no forecast — current/past detection only.

### PurpleAir
- **URL:** https://www2.purpleair.com/, API: https://api.purpleair.com/
- **What it has:** Dense crowdsourced PM2.5 sensor network — far higher spatial resolution
  than AirNow's official network, ~2 min update interval.
- **Format:** REST API.
- **Access:** Free developer API key (linked to Google account) for light use; bulk/commercial
  use is metered on a points-based billing system.
- **Pros:** Much finer-grained coverage than AirNow alone.
- **Cons:** Billing risk at scale; adds complexity. Lower priority than AirNow + HMS.

### NOAA HRRR-Smoke / BlueSky (not yet researched in depth)
- Smoke *forecast* models (vs. the detection-only products above) — relevant if "near future"
  trip planning means tomorrow/this weekend rather than right now. Flagged as a follow-up
  research item, not yet investigated in detail.

## Existing prior art (competitive landscape)

- **CalTopo** — Fire History layer: perimeters colored by age (yellow=oldest, red=newest),
  ~20 years back, sourced from NIFC/GeoMAC. Hiking/trip-planning audience, but no severity data.
- **Gaia GPS** — "US Wildfire – Historic" overlay, tap for name/date/acreage. Similar
  recency-only coloring, no severity.
- **CAL FIRE Living Atlas map** — symbol-by-decade historical perimeters + burn-frequency
  analysis, CA only.
- **CAP Radio California Wildfire History Map** — historical CA perimeters back to 1878.

**Gap in the market:** the existing tools are all *reference maps* — static layers you inspect,
typically color-coded by recency, ~20 years deep, with no severity. None of them play the fire
record as a **time animation** over the full 40-year MTBS archive, which is this project's
angle; surfacing MTBS *severity* at rest remains a secondary differentiator.

## Licensing

All sources above are US federal/state government data or free-tier developer APIs — public
domain or otherwise free for personal/commercial use. PurpleAir is the one exception to watch
at scale (metered billing for heavy API use).
