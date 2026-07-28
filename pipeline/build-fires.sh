#!/usr/bin/env bash
# Build the main fire datasets the animation runs on.
#
# This used to live only as a command block in animation-plan.md. It needs to be runnable now
# that #14 adds fields to it: `id` (the MTBS event_id, which names each fire's severity file),
# `sev_ok` (does that file exist), and `sev` (the class breakdown, so the popup can report it
# without waiting on a fetch). Run pipeline/build-severity.py first — this reads its stats.
#
# Usage: pipeline/build-fires.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/tools/envs/gis/bin:$HOME/tools/bin:$PATH"
export PROJ_DATA="$HOME/tools/envs/gis/share/proj"
export GDAL_DATA="$HOME/tools/envs/gis/share/gdal"

PERIMS="$ROOT/pipeline/data/perimeters/mtbs_perims_DD.shp"
WORK="$ROOT/pipeline/data/fires"
mkdir -p "$WORK"

WEST="'WA','OR','CA','ID','NV','UT','AZ','MT','WY','CO','NM'"

# COORDINATE_PRECISION=4 is ~11 m. The simplify tolerance differs by scope, which is not an
# oversight: the 11-state build ships at 0.002 (~200 m) — 37x fewer vertices for 0.44% area
# distortion, with no fire dropped — while the WA slice has always shipped at 0.0005, four
# times finer. It is the light dataset you test detail against, so coarsening it to match the
# West would quietly throw away the thing it is for. Rebuilding at 0.002 was measured against
# the shipped file and cost WA two thirds of its vertices (86,642 -> 29,713); at 0.0005 it
# reproduces. See animation-plan.md for the table and the degrees-not-metres gotcha.
build() {
  local scope="$1" states="$2" simplify="$3"
  echo "== $scope: extracting perimeters (simplify $simplify) =="
  rm -f "$WORK/$scope.geojson"
  ogr2ogr -f GeoJSON "$WORK/$scope.geojson" -t_srs EPSG:4326 \
    -simplify "$simplify" -lco COORDINATE_PRECISION=4 \
    -sql "SELECT event_id AS id, incid_name AS name, incid_type AS type, ig_date,
                 burnbndac AS acres, asmnt_type AS asmnt FROM mtbs_perims_DD
          WHERE SUBSTR(event_id,1,2) IN ($states)
            AND ig_date >= '1984-01-01' AND ig_date <= '2024-12-31'" \
    "$PERIMS"

  echo "== $scope: attaching severity =="
  python3 "$ROOT/pipeline/attach-severity.py" "$WORK/$scope.geojson" \
    "$ROOT/app/data/${scope}_fires.geojson.gz"
}

build west "$WEST" 0.002
build wa   "'WA'" 0.0005
ls -l "$ROOT/app/data/"*_fires.geojson.gz
