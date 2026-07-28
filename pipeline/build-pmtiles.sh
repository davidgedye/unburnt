#!/usr/bin/env bash
# PROTOTYPE (milestone 7): one year of perimeters + severity as a vector tileset, to find out
# what moving off whole-file GeoJSON actually buys and costs.
#
# The problem it is testing: everything the app ships today is a single GeoJSON, downloaded and
# parsed before anything draws, so one simplification tolerance has to serve every zoom at once.
# At 0.002 deg that is right at z4 and ~15 screen pixels wrong at z13, which is where the
# disappointing outlines come from. Tiles generalise *per zoom*, so z4 gets the coarse version
# and z13 gets the full 30 m detail, and only the tiles on screen are fetched.
#
# So: feed tippecanoe the FULL-FIDELITY geometry — no -simplify on the perimeters, minimal sieve
# and no vector simplification on the severity — and let it do the generalising.
#
#   --detect-shared-borders  is the one that matters for severity: those polygons tile a
#                            coverage, and per-feature simplification pulls neighbours apart.
#                            That is the pale-band artifact the app currently paints over.
#   -Z4 -z13                 z13 is the honest limit of 30 m source data.
#
# Usage: pipeline/build-pmtiles.sh [year]        (default 2020 — peak year, has DOLAN and NORTH)
set -euo pipefail
YEAR="${1:-2020}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/tools/envs/gis/bin:$HOME/tools/bin:$PATH"
export PROJ_DATA="$HOME/tools/envs/gis/share/proj"
export GDAL_DATA="$HOME/tools/envs/gis/share/gdal"
export GDAL_CACHEMAX=512
# The 2020 NORTH fire carries 2,030,049 vertices for 6,827 acres and trips GDAL's default
# per-feature size cap. Raising it is the documented workaround; the alternative is losing the
# single most crenulated perimeter in the record, which is exactly the case worth testing.
export OGR_ORGANIZE_POLYGONS=SKIP
export SHAPE_2GB_LIMIT=YES

WORK="$ROOT/pipeline/data/pmtiles"
mkdir -p "$WORK"
WEST="'WA','OR','CA','ID','NV','UT','AZ','MT','WY','CO','NM'"

echo "== $YEAR: perimeters at full fidelity (no -simplify) =="
rm -f "$WORK/perims-$YEAR.geojson"
ogr2ogr -f GeoJSON "$WORK/perims-$YEAR.geojson" -t_srs EPSG:4326 \
  -lco COORDINATE_PRECISION=6 -lco RFC7946=NO \
  -sql "SELECT event_id AS id, incid_name AS name, incid_type AS type, ig_date,
               burnbndac AS acres FROM mtbs_perims_DD
        WHERE SUBSTR(event_id,1,2) IN ($WEST)
          AND ig_date >= '$YEAR-01-01' AND ig_date <= '$YEAR-12-31'" \
  "$ROOT/pipeline/data/perimeters/mtbs_perims_DD.shp"
python3 - "$WORK/perims-$YEAR.geojson" <<'PY'
import json, sys
fc = json.load(open(sys.argv[1]))
v = sum(len(r) for f in fc['features']
        for part in ([f['geometry']['coordinates']] if f['geometry']['type'] == 'Polygon'
                     else f['geometry']['coordinates']) for r in part)
print(f'   {len(fc["features"])} fires, {v:,} vertices')
PY

echo "== $YEAR: severity at full fidelity (sieve 4 px, no simplify) =="
python3 "$ROOT/pipeline/severity-full.py" "$YEAR" "$WORK/severity-$YEAR.geojson"

echo "== $YEAR: tiling =="
rm -f "$WORK/$YEAR.pmtiles"
/usr/bin/time -f '   tippecanoe: %e s, %M KB peak' \
tippecanoe -o "$WORK/$YEAR.pmtiles" -Z4 -z13 \
  --detect-shared-borders --coalesce-densest-as-needed --no-tile-size-limit \
  --named-layer=perimeters:"$WORK/perims-$YEAR.geojson" \
  --named-layer=severity:"$WORK/severity-$YEAR.geojson" \
  2>&1 | tail -4

echo
echo "== result =="
ls -l "$WORK/$YEAR.pmtiles" | awk '{printf "   tileset  %.2f MB\n", $5/1e6}'
pmtiles show "$WORK/$YEAR.pmtiles" 2>/dev/null | grep -iE "tile count|min zoom|max zoom|tile type" | sed 's/^/   /'
echo "   (compare: this year inside the shipped GeoJSON assets)"
python3 - "$YEAR" <<'PY'
import gzip, json, os, sys, glob
year = int(sys.argv[1])
fc = json.load(gzip.open('/home/david/unburnt/app/data/west_fires.geojson.gz'))
ids = {f['properties']['id'] for f in fc['features'] if f['properties']['ig_date'][:4] == str(year)}
sev = sum(os.path.getsize(p) for p in glob.glob('/home/david/unburnt/app/data/severity/*.gz')
          if os.path.basename(p)[:-len('.geojson.gz')] in ids)
print(f'   shipped severity for {year}: {sev/1e6:.2f} MB across {len(ids)} fires'
      f' (perimeters are inside the one 3.15 MB all-years file)')
PY
