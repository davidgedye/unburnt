#!/usr/bin/env bash
# Fetch each year's CONUS thematic severity mosaic from ScienceBase, build that year's per-fire
# severity overlays, then delete the mosaic. One year at a time: the zips are small (2-9 MB) but
# each extracts to ~200 MB, and 41 of those at once is 8 GB of scratch for no reason.
#
# The MTBS mosaic parent is ScienceBase 5e91dee782ce172707f02cdd — 41 children, one per year,
# no gaps (verified 2026-07-28). Per-file download URLs come from each child's `files` array;
# they are content-addressed, so they have to be looked up rather than constructed.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/tools/envs/gis/bin:$PATH"
export PROJ_DATA="$HOME/tools/envs/gis/share/proj" GDAL_DATA="$HOME/tools/envs/gis/share/gdal"
export GDAL_CACHEMAX=512
URLS="$ROOT/pipeline/data/mosaic-urls.json"
cd "$ROOT"

for y in $(seq 1984 2024); do
  dir="pipeline/data/mosaic$y"
  tif="$dir/mtbs_CONUS_$y.tif"
  if [ ! -f "$tif" ]; then
    url=$(python3 -c "import json,sys; print(json.load(open('$URLS')).get('$y',''))")
    [ -z "$url" ] && { echo "$y: no URL"; continue; }
    mkdir -p "$dir"
    echo "== $y: downloading =="
    curl -sSL --max-time 900 --retry 3 -o "$dir/m.zip" "$url" || { echo "$y: download failed"; continue; }
    unzip -o -q -j "$dir/m.zip" -d "$dir" || { echo "$y: unzip failed"; continue; }
    rm -f "$dir/m.zip"
    [ -f "$tif" ] || { echo "$y: no CONUS tif after unzip"; ls "$dir"; continue; }
    KEEP=0
  else
    KEEP=1                       # 2023/2024 were already here; leave them
  fi
  python3 pipeline/build-severity.py "$y" 2>&1 | grep -vi deprecation
  [ "$KEEP" = 0 ] && rm -rf "$dir"
done
echo "ALL YEARS DONE"
du -sh app/data/severity; ls app/data/severity | wc -l
