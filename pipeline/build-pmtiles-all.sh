#!/usr/bin/env bash
# Build the whole 41-year record as one vector tileset (milestone 7).
#
# Measured on this laptop, from the 2020 prototype (pmtiles-prototype.md):
#   peak RAM   ~1.3 GB   — one year at a time; a single 41-year tippecanoe run over ~5.4 GB of
#                          input would want roughly 19 GB and will not fit in the 7 GB WSL2 cap
#   peak disk  ~3-4 GB   — intermediates are deleted as each year finishes
#   output     ~1.2 GB   — destined for R2, not git
#   time       ~4-5 h    — hence: resumable, and safe to leave running overnight
#
# Resumable by design. Every year that already has years/<year>.pmtiles is skipped, each year's
# tileset is written to .tmp and renamed only on success, and killing the script at any point
# loses at most the year in flight. Re-run it and it picks up.
#
# Usage:
#   pipeline/build-pmtiles-all.sh                 # all years, resuming
#   pipeline/build-pmtiles-all.sh 1988 1989 1990  # just these
#   pipeline/build-pmtiles-all.sh --merge         # skip building, just merge what is there
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/tools/envs/gis/bin:$HOME/tools/bin:$PATH"
export PROJ_DATA="$HOME/tools/envs/gis/share/proj"
export GDAL_DATA="$HOME/tools/envs/gis/share/gdal"
export GDAL_CACHEMAX=512
export SIEVE=8              # px, ~1.8 acres — the value pipeline-validation.md settled on

OUT="$ROOT/pipeline/data/pmtiles"
YEARS="$OUT/years"
WORK="$OUT/work"
URLS="$ROOT/pipeline/data/mosaic-urls.json"
mkdir -p "$YEARS" "$WORK"
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
  if [ -f "$YEARS/$y.pmtiles" ]; then
    log "$y  already built, skipping"
    return 0
  fi
  local t0=$SECONDS
  local dir="$ROOT/pipeline/data/mosaic$y" tif="$ROOT/pipeline/data/mosaic$y/mtbs_CONUS_$y.tif"
  local downloaded=0

  if [ ! -f "$tif" ]; then
    local url
    url=$(python3 -c "import json;print(json.load(open('$URLS')).get('$y',''))")
    [ -z "$url" ] && { log "$y  no mosaic URL — skipped"; return 1; }
    mkdir -p "$dir"
    log "$y  downloading mosaic"
    curl -sSL --max-time 1800 --retry 3 -o "$dir/m.zip" "$url" || { log "$y  download FAILED"; return 1; }
    if ! unzip -o -q -j "$dir/m.zip" -d "$dir"; then
      # A truncated or corrupt download inflates part-way and leaves a plausible .tif behind.
      log "$y  unzip FAILED (corrupt download) — discarding"
      rm -rf "$dir"; return 1
    fi
    rm -f "$dir/m.zip"
    [ -f "$tif" ] || { log "$y  no CONUS tif after unzip"; return 1; }
    downloaded=1
  fi

  # Perimeters at full fidelity — no -simplify. tippecanoe does the generalising, per zoom.
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

  log "$y  severity"
  rm -f "$WORK/s.geojson" "$WORK/stats.json"
  python3 "$ROOT/pipeline/severity-full.py" "$y" "$WORK/s.geojson" "$WORK/stats.json" \
    2>&1 | grep -viE 'deprecat|warnings.warn' || { log "$y  severity FAILED"; return 1; }

  # `sev_ok` and the class breakdown ride on the perimeter, exactly as they do today, so the
  # One-year outline still knows which fires have data without touching the severity layer.
  python3 "$ROOT/pipeline/attach-severity.py" --inplace "$WORK/p.geojson" "$WORK/stats.json" \
    || { log "$y  attach FAILED"; return 1; }

  # Two tilesets, because the layers want different minzooms and tippecanoe takes one per run:
  #  - perimeters from z2: the app's minzoom is 2.5, and a source has no tiles below its own
  #    minzoom, so fires would simply vanish on a small window. --no-tile-size-limit because
  #    dropping features to fit a tile would silently delete fires from the accumulated view,
  #    which is the one thing this map must not do.
  #  - severity from z9: below that it is far under a pixel. Not tiling it there is what stops
  #    a regional view pulling 1.6 MB of something invisible.
  log "$y  tiling"
  rm -f "$WORK/p.pmtiles" "$WORK/s.pmtiles"
  tippecanoe -q -o "$WORK/p.pmtiles" -Z2 -z13 --no-tile-size-limit \
    --detect-shared-borders --named-layer=perimeters:"$WORK/p.geojson" \
    || { log "$y  tippecanoe perimeters FAILED"; return 1; }
  # A cheap emptiness test. The previous version parsed the entire severity GeoJSON — up to
  # 372 MB — purely to count its features, which is slow and throws on a partial file.
  if [ -s "$WORK/s.geojson" ] && ! grep -q '"features":\[\]' "$WORK/s.geojson"; then
    tippecanoe -q -o "$WORK/s.pmtiles" -Z9 -z13 \
      --detect-shared-borders --coalesce-densest-as-needed \
      --named-layer=severity:"$WORK/s.geojson" \
      || { log "$y  tippecanoe severity FAILED"; return 1; }
  else
    log "$y  no severity polygons (expected for the newest season)"
  fi

  # Write to a temporary name and rename only on success, so a kill mid-write cannot leave a
  # half tileset that the resume logic would mistake for a finished year. The name has to keep
  # the .pmtiles extension: tile-join picks its output *format* from the extension, so a plain
  # ".tmp" silently produces an mbtiles that is then renamed into a file with the wrong magic
  # number — valid-looking, unreadable, and only discovered at merge time.
  local tmp="$YEARS/$y.building.pmtiles"
  rm -f "$tmp"
  if [ -f "$WORK/s.pmtiles" ]; then
    tile-join -o "$tmp" --no-tile-size-limit "$WORK/p.pmtiles" "$WORK/s.pmtiles" \
      || { log "$y  tile-join FAILED"; return 1; }
  else
    cp "$WORK/p.pmtiles" "$tmp"
  fi
  mv "$tmp" "$YEARS/$y.pmtiles"

  rm -f "$WORK"/*.geojson "$WORK"/*.pmtiles "$WORK"/stats.json
  [ "$downloaded" = 1 ] && rm -rf "$dir"
  log "$y  done in $((SECONDS - t0))s  ($(du -h "$YEARS/$y.pmtiles" | cut -f1))"
}

merge_all() {
  # Excludes any *.building.pmtiles left by an interrupted run.
  local files=()
  for f in "$YEARS"/*.pmtiles; do [[ "$f" == *.building.pmtiles ]] || files+=("$f"); done
  [ -e "${files[0]}" ] || { log "nothing to merge"; return 1; }
  log "merging ${#files[@]} year tilesets"
  # In batches rather than one 41-way join: tile-join held to 556 MB on two inputs, but this
  # laptop has 7 GB and nothing is gained by finding out where the ceiling is at 3 a.m.
  local batch=() n=0 parts=()
  for f in "${files[@]}"; do
    batch+=("$f"); n=$((n+1))
    if [ ${#batch[@]} -ge 8 ]; then
      local p="$WORK/part$n.pmtiles"
      tile-join -o "$p" --no-tile-size-limit "${batch[@]}" || return 1
      parts+=("$p"); batch=()
      log "  batch through $(basename "$f") -> $(du -h "$p" | cut -f1)"
    fi
  done
  if [ ${#batch[@]} -gt 0 ]; then
    local p="$WORK/partX.pmtiles"
    tile-join -o "$p" --no-tile-size-limit "${batch[@]}" || return 1
    parts+=("$p")
  fi
  rm -f "$OUT/west.building.pmtiles"
  tile-join -o "$OUT/west.building.pmtiles" --no-tile-size-limit "${parts[@]}" || return 1
  mv "$OUT/west.building.pmtiles" "$OUT/west.pmtiles"
  rm -f "$WORK"/part*.pmtiles
  log "wrote $OUT/west.pmtiles  ($(du -h "$OUT/west.pmtiles" | cut -f1))"
  pmtiles show "$OUT/west.pmtiles" 2>/dev/null | grep -iE 'min zoom|max zoom|tile entries' | sed 's/^/  /'
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
