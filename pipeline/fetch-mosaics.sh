#!/usr/bin/env bash
# Hold a local copy of every MTBS annual severity mosaic.
#
# Not part of any build — build-pmtiles-all.sh downloads what it needs. This exists because the
# mosaics are the one input that cannot be recomputed and has already proved perishable: 2004
# and 2017 are advertised in ScienceBase's metadata and 404 on fetch (#16), so their severity
# can never be rebuilt from source. Whatever is on this disk is the only hedge against that
# happening to another year.
#
# Which matters because re-tiling is not hypothetical. Moving severity to z2 and splitting it
# per year meant rebuilding all 41 years, and the 23 whose mosaics had been deleted had to be
# fetched again. Two could not be.
#
# Deliberately does not delete anything afterwards, which is the whole point and the opposite
# of what build-pmtiles-all.sh does with a mosaic it downloaded itself.
#
# Usage:
#   pipeline/fetch-mosaics.sh              # every year not already held
#   pipeline/fetch-mosaics.sh 2004 2017    # just these, e.g. to retry the known gaps
#   pipeline/fetch-mosaics.sh --check      # report what is held and what is reachable, fetch nothing
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA="$ROOT/pipeline/data"
URLS="$DATA/mosaic-urls.json"
CHECK=0
[ "${1:-}" = "--check" ] && { CHECK=1; shift; }

log() { printf '%s  %s\n' "$(date +%H:%M:%S)" "$*"; }

years=("$@")
if [ ${#years[@]} -eq 0 ]; then
  years=()
  for y in $(seq 1984 2024); do
    [ -f "$DATA/mosaic$y/mtbs_CONUS_$y.tif" ] || years+=("$y")
  done
fi

held=0
for y in $(seq 1984 2024); do
  [ -f "$DATA/mosaic$y/mtbs_CONUS_$y.tif" ] && held=$((held + 1))
done
log "$held of 41 mosaics held; ${#years[@]} to fetch"

ok=0; gone=()
for y in "${years[@]}"; do
  dir="$DATA/mosaic$y" tif="$DATA/mosaic$y/mtbs_CONUS_$y.tif"
  if [ -f "$tif" ]; then
    log "$y  already held"
    ok=$((ok + 1)); continue
  fi
  url=$(python3 -c "import json;print(json.load(open('$URLS')).get('$y',''))")
  if [ -z "$url" ]; then
    log "$y  no URL in mosaic-urls.json"; gone+=("$y"); continue
  fi
  if [ "$CHECK" = 1 ]; then
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 60 -r 0-0 "$url")
    log "$y  HTTP $code"
    [ "$code" = "200" ] || [ "$code" = "206" ] && ok=$((ok + 1)) || gone+=("$y")
    continue
  fi
  log "$y  downloading"
  # Same guards as the build: --fail so an HTTP error is caught here, and a size floor because
  # ScienceBase serves a registered-but-empty object for some years rather than a 404 on the zip.
  if ! curl -sSL --fail --max-time 1800 --retry 3 -o "$dir.zip" "$url" 2>/dev/null; then
    log "$y  FAILED (HTTP error) — upstream gone"; rm -f "$dir.zip"; gone+=("$y"); continue
  fi
  if [ "$(stat -c%s "$dir.zip")" -lt 100000 ]; then
    log "$y  FAILED (archive is $(stat -c%s "$dir.zip") bytes — upstream file is empty)"
    rm -f "$dir.zip"; gone+=("$y"); continue
  fi
  mkdir -p "$dir"
  if ! unzip -o -q -j "$dir.zip" -d "$dir"; then
    log "$y  FAILED (corrupt archive)"; rm -rf "$dir" "$dir.zip"; gone+=("$y"); continue
  fi
  rm -f "$dir.zip"
  if [ ! -f "$tif" ]; then
    log "$y  FAILED (no CONUS tif after unzip)"; rm -rf "$dir"; gone+=("$y"); continue
  fi
  log "$y  held ($(du -h "$tif" | cut -f1))"
  ok=$((ok + 1))
done

echo
log "$ok fetched or already held"
if [ ${#gone[@]} -gt 0 ]; then
  log "UNOBTAINABLE: ${gone[*]}"
  log "  these years cannot be re-tiled from source. 2004 and 2017 are known (#16);"
  log "  anything else here is new and worth raising."
fi
log "total held: $(ls -d "$DATA"/mosaic[0-9]* 2>/dev/null | wc -l) of 41  ($(du -sh --exclude=pmtiles "$DATA" | cut -f1) in pipeline/data)"
