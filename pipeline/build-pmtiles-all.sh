#!/usr/bin/env bash
# Build the whole 41-year record as vector tilesets (milestone 7).
#
# Two products, because the app reads them differently:
#
#   perimeters.pmtiles       all years in one tileset, z2-z13, ~50 MB. The accumulated view
#                            lights every year at once off a single source, so perimeters have
#                            to share one.
#   severity/<year>.pmtiles  one tileset per year, z2-z13. Severity is drawn a season at a
#                            time, and merging all 41 put 32 fires from five decades into every
#                            tile in order to draw one: 1.6 MB where 160 KB does. Per year is
#                            ~10x leaner per view, and it is what lets severity go down to z2
#                            at all — the old z9 floor existed to cap the damage from merging.
#
# Measured on this laptop, from the 2020 prototype (pmtiles-prototype.md):
#   peak RAM   ~1.3 GB   — one year at a time; a single 41-year tippecanoe run over ~5.4 GB of
#                          input would want roughly 19 GB and will not fit in the 7 GB WSL2 cap
#   peak disk  ~3-4 GB   — intermediates are deleted as each year finishes
#   output     ~1.1 GB   — destined for R2, not git
#   time       ~4-5 h    — hence: resumable, and safe to leave running overnight
#
# Resumable by design. A year counts as finished when perims/<year>.pmtiles exists, and that is
# written last — after severity — so an interrupted run never looks complete. Each tileset is
# written under a .building name and renamed only on success, so killing the script at any point
# loses at most the year in flight. Re-run it and it picks up.
#
# Usage:
#   pipeline/build-pmtiles-all.sh                 # all years, resuming
#   pipeline/build-pmtiles-all.sh 1988 1989 1990  # just these
#   pipeline/build-pmtiles-all.sh --merge         # skip building, just merge the perimeters
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/tools/envs/gis/bin:$HOME/tools/bin:$PATH"
export PROJ_DATA="$HOME/tools/envs/gis/share/proj"
export GDAL_DATA="$HOME/tools/envs/gis/share/gdal"
export GDAL_CACHEMAX=512
export SIEVE=8              # px, ~1.8 acres — the value pipeline-validation.md settled on

OUT="$ROOT/pipeline/data/pmtiles"
PERIMS="$OUT/perims"          # per-year perimeters, merged at the end into perimeters.pmtiles
SEV="$OUT/severity"           # per-year severity, shipped as-is
WORK="$OUT/work"
URLS="$ROOT/pipeline/data/mosaic-urls.json"
mkdir -p "$PERIMS" "$SEV" "$WORK"
WEST="'WA','OR','CA','ID','NV','UT','AZ','MT','WY','CO','NM'"

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }

# Only one build at a time. Every year reuses the same scratch names in $WORK, so two runs
# silently overwrite each other's p.geojson / s.pmtiles and produce year tilesets containing
# another year's data — structurally valid, contentally wrong, and only findable by decoding a
# tile. That happened; this is the fix. flock releases on exit however the script dies.
exec 9>"$OUT/.build.lock"
if ! flock -n 9; then
  echo "another build is already running (holding $OUT/.build.lock) — refusing to start" >&2
  exit 1
fi

build_year() {
  local y="$1"
  if [ -f "$PERIMS/$y.pmtiles" ]; then
    log "$y  already built, skipping"
    return 0
  fi
  local t0=$SECONDS
  local dir="$ROOT/pipeline/data/mosaic$y" tif="$ROOT/pipeline/data/mosaic$y/mtbs_CONUS_$y.tif"
  local downloaded=0 have_sev=0

  # Perimeters first, and unconditionally. They come out of the shapefile and owe the mosaic
  # nothing, so a year whose mosaic cannot be downloaded still has all its fires. Doing this
  # after the download once cost 2004 and 2017 their perimeters entirely -- 644 fires that
  # simply were not on the map, which is far worse than the missing severity it was meant to
  # be about (#16).
  log "$y  perimeters"
  rm -f "$WORK/p.geojson"
  ogr2ogr -f GeoJSON "$WORK/p.geojson" -t_srs EPSG:4326 \
    -lco COORDINATE_PRECISION=6 -lco RFC7946=NO \
    -sql "SELECT event_id AS id, incid_name AS name, incid_type AS type, ig_date,
                 burnbndac AS acres, CAST(SUBSTR(ig_date,1,4) AS integer) AS year
          FROM mtbs_perims_DD
          WHERE SUBSTR(event_id,1,2) IN ($WEST)
            AND ig_date >= '$y-01-01' AND ig_date <= '$y-12-31'" \
    "$ROOT/pipeline/data/perimeters/mtbs_perims_DD.shp" 2>/dev/null || { log "$y  ogr2ogr FAILED"; return 1; }

  # Severity needs the mosaic, and only severity does. Every failure below is a `severity: no`
  # for the year, not a reason to abandon it.
  rm -f "$WORK/s.geojson" "$WORK/stats.json"
  if [ -f "$tif" ]; then
    have_sev=1
  else
    local url
    url=$(python3 -c "import json;print(json.load(open('$URLS')).get('$y',''))")
    if [ -z "$url" ]; then
      log "$y  no mosaic URL — perimeters only"
    else
      mkdir -p "$dir"
      log "$y  downloading mosaic"
      # --fail so an HTTP error is caught here rather than saved as a .zip and discovered at
      # unzip time. ScienceBase serves a 404 HTML page with a 200-shaped body otherwise.
      if ! curl -sSL --fail --max-time 1800 --retry 3 -o "$dir/m.zip" "$url"; then
        log "$y  download FAILED (HTTP error) — perimeters only"; rm -rf "$dir"
      # A zero-byte or absurdly small archive means ScienceBase has the file registered but
      # empty — which is genuinely the case for some years. Catch it with a clear reason.
      elif [ "$(stat -c%s "$dir/m.zip")" -lt 100000 ]; then
        log "$y  download FAILED (archive is $(stat -c%s "$dir/m.zip") bytes — upstream file is empty) — perimeters only"
        rm -rf "$dir"
      # A truncated or corrupt download inflates part-way and leaves a plausible .tif behind.
      elif ! unzip -o -q -j "$dir/m.zip" -d "$dir"; then
        log "$y  unzip FAILED (corrupt download) — perimeters only"; rm -rf "$dir"
      elif [ ! -f "$tif" ]; then
        log "$y  no CONUS tif after unzip — perimeters only"
      else
        rm -f "$dir/m.zip"; downloaded=1; have_sev=1
      fi
    fi
  fi

  if [ "$have_sev" = 1 ]; then
    log "$y  severity"
    python3 "$ROOT/pipeline/severity-full.py" "$y" "$WORK/s.geojson" "$WORK/stats.json" \
      2>&1 | grep -viE 'deprecat|warnings.warn' || { log "$y  severity FAILED"; return 1; }
  fi

  # `sev_ok` and the class breakdown ride on the perimeter, so the One-year outline knows which
  # fires have data without touching the severity layer. With no stats file every fire in the
  # year is tagged sev_ok:false, which is exactly right — the fires are there, the severity is
  # not, and the popup says so.
  python3 "$ROOT/pipeline/attach-severity.py" --inplace "$WORK/p.geojson" "$WORK/stats.json" \
    || { log "$y  attach FAILED"; return 1; }

  # Two tilesets, because the layers want different tile-size policies and tippecanoe takes one
  # set of flags per run. Both cover z2-z13: a source has no tiles below its own minzoom, and the
  # app's minzoom is 2.5, so anything tiled higher simply vanishes on a small window.
  #  - perimeters: --no-tile-size-limit, because dropping features to fit a tile would silently
  #    delete fires from the accumulated view, which is the one thing this map must not do.
  #  - severity: keeps the default 500 KB cap and coalesces to fit. Severity used to start at z9
  #    on the theory that lower zooms were paying for detail under a pixel. Measured on 2020, the
  #    worst year in the record, z2-z8 adds ~11.5 MB to a 97 MB year and the cap holds every tile
  #    under 500 KB — a fire's z6 tile is *smaller* than its z9 one, because simplification
  #    outruns the extra ground. The real cost was never the zoom, it was merging all 41 years
  #    into one tileset so a single tile carried 32 fires when the app draws one. Hence per-year.
  # Each tileset goes straight to its final directory under a .building name and is renamed only
  # on success. The temporary name has to keep the .pmtiles extension: tippecanoe picks its
  # output *format* from the extension, so a plain ".tmp" silently produces an mbtiles that is
  # then renamed into a file with the wrong magic number — valid-looking, unreadable, and only
  # discovered much later.
  #
  # Severity first, perimeters last, because the perimeter tileset is what marks the year
  # finished. Any interruption therefore leaves the year looking unbuilt, which is the safe way
  # round: re-running redoes work, where the reverse would skip a year with no severity.
  log "$y  tiling"
  rm -f "$SEV/$y.building.pmtiles" "$PERIMS/$y.building.pmtiles"
  # A cheap emptiness test. The previous version parsed the entire severity GeoJSON — up to
  # 372 MB — purely to count its features, which is slow and throws on a partial file.
  if [ -s "$WORK/s.geojson" ] && ! grep -q '"features":\[\]' "$WORK/s.geojson"; then
    tippecanoe -q -o "$SEV/$y.building.pmtiles" -Z2 -z13 \
      --detect-shared-borders --coalesce-densest-as-needed \
      --named-layer=severity:"$WORK/s.geojson" \
      || { log "$y  tippecanoe severity FAILED"; return 1; }
    mv "$SEV/$y.building.pmtiles" "$SEV/$y.pmtiles"
  else
    log "$y  no severity polygons (expected for the newest season)"
    rm -f "$SEV/$y.pmtiles"      # a rebuild must not leave last run's severity behind
  fi
  tippecanoe -q -o "$PERIMS/$y.building.pmtiles" -Z2 -z13 --no-tile-size-limit \
    --detect-shared-borders --named-layer=perimeters:"$WORK/p.geojson" \
    || { log "$y  tippecanoe perimeters FAILED"; return 1; }
  mv "$PERIMS/$y.building.pmtiles" "$PERIMS/$y.pmtiles"

  rm -f "$WORK"/*.geojson "$WORK"/*.pmtiles "$WORK"/stats.json
  [ "$downloaded" = 1 ] && rm -rf "$dir"
  local ssz="none"
  [ -f "$SEV/$y.pmtiles" ] && ssz=$(du -h "$SEV/$y.pmtiles" | cut -f1)
  log "$y  done in $((SECONDS - t0))s  (perimeters $(du -h "$PERIMS/$y.pmtiles" | cut -f1), severity $ssz)"
}

merge_all() {
  # Perimeters only. Merging severity is exactly what put 32 fires from five decades into a
  # single tile to draw one, so it stays per-year and ships as built.
  #
  # One join over all 41 rather than the batches the merged build needed: those existed because
  # each input carried a year of severity and ran to tens of MB. Perimeters are ~1 MB a year, so
  # the whole join is ~50 MB and there is nothing left to protect against.
  # Excludes any *.building.pmtiles left by an interrupted run.
  local files=()
  for f in "$PERIMS"/*.pmtiles; do [[ "$f" == *.building.pmtiles ]] || files+=("$f"); done
  [ -e "${files[0]}" ] || { log "nothing to merge"; return 1; }
  log "merging ${#files[@]} year perimeter tilesets"
  rm -f "$OUT/perimeters.building.pmtiles"
  tile-join -o "$OUT/perimeters.building.pmtiles" --no-tile-size-limit "${files[@]}" || return 1
  mv "$OUT/perimeters.building.pmtiles" "$OUT/perimeters.pmtiles"
  log "wrote $OUT/perimeters.pmtiles  ($(du -h "$OUT/perimeters.pmtiles" | cut -f1))"
  local n=0
  for f in "$SEV"/*.pmtiles; do [[ -f "$f" && "$f" != *.building.pmtiles ]] && n=$((n+1)); done
  log "severity: $n per-year tilesets in $SEV  ($(du -sh "$SEV" | cut -f1))"
}

main() {
  if [ "${1:-}" = "--merge" ]; then merge_all; return $?; fi
  local years=("$@")
  [ ${#years[@]} -eq 0 ] && years=($(seq 1984 2024))
  local failed=()
  for y in "${years[@]}"; do
    build_year "$y" || failed+=("$y")
    df -h "$OUT" | tail -1 | awk -v y="$y" '{print "          disk: " $4 " free"}'
  done
  [ ${#failed[@]} -gt 0 ] && log "FAILED years: ${failed[*]}  (re-run to retry — finished years are skipped)"
  merge_all
}

main "$@"
