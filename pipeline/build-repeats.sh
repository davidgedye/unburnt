#!/usr/bin/env bash
# Build the repeat-burn layer: where has the same ground burned more than once since 1984?
#
# Answering that by intersecting ~11k perimeters pairwise is a geometry job the browser has no
# business doing, and it is not what this app's engine is shaped like (precomputed states, GPU
# uniforms, no runtime geometry). So it is answered offline, on a raster: stamp every perimeter
# onto a common grid with `-add`, and each cell holds how many fires have crossed it. Counting
# on a grid is O(area), not O(fires²), and the answer comes back as a few thousand polygons.
#
# Output: app/data/<scope>_repeats.geojson.gz — polygons carrying `count` (2..9).
#
# Usage: pipeline/build-repeats.sh [west|wa]        (default: both)
# Needs the user-space GIS env; see pipeline-validation.md.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/tools/envs/gis/bin:$HOME/tools/bin:$PATH"
export PROJ_DATA="$HOME/tools/envs/gis/share/proj"
export GDAL_DATA="$HOME/tools/envs/gis/share/gdal"
export GDAL_CACHEMAX=1024

PERIMS="$ROOT/pipeline/data/perimeters/mtbs_perims_DD.shp"
WORK="$ROOT/pipeline/data/repeats"
mkdir -p "$WORK"

# 90 m cells. Deliberately coarser than MTBS's 30 m source: this layer answers "how often",
# not "exactly where" — 30 m would cost 9× the pixels and buy detail that is thrown away by
# the simplification step anyway. One cell is ~2 acres.
RES=90
# Speckle floor, in cells (16 ≈ 32 acres). Two perimeters drawn from different Landsat scenes
# disagree along their shared edge by a pixel or two, which would otherwise fringe every
# neighbouring pair of fires with a thread of false "burned twice".
SIEVE=16
# Simplification tolerance in metres (source CRS is Albers, so this is uniform — unlike the
# degrees-based tolerance the perimeter build uses). One cell: no vertex can move further than
# the grid it came off, which strips the rasterisation staircase and nothing beyond it.
#
# These polygons tile a coverage, and `-simplify` is per-feature, so neighbours sharing an edge
# pull apart by up to the tolerance and leave a hairline crack. That is what sets the floor
# here: 150 m halves the file (1.2 MB vs 1.8 MB gzipped) but the cracks show as dark threads
# from about z10 in. 60 m is visually clean but 3.4 MB, for detail below the cell size.
SIMPLIFY=90

# EPSG:5070, NAD83 / Conus Albers — equal-area, so a cell is the same ground everywhere and a
# count is comparable between Arizona and the Canadian border.
CRS=EPSG:5070

build() {
  local scope="$1" states="$2"
  local w="$WORK/$scope"

  # Every step here writes to a fixed name, and several of these tools *update* an existing
  # target rather than replacing it — a second run of gdal_rasterize would add its counts on
  # top of the last run's, silently doubling them. So the run starts from nothing.
  rm -f "$w-perims.gpkg" "$w-count.tif" "$w-sieved.tif" "$w-mask.tif" "$w-repeats.gpkg" "$w.geojson"

  echo "== $scope: extracting perimeters =="
  ogr2ogr -f GPKG "$w-perims.gpkg" -t_srs "$CRS" -nlt PROMOTE_TO_MULTI -nln perims \
    -sql "SELECT ig_date FROM mtbs_perims_DD
          WHERE SUBSTR(event_id,1,2) IN ($states)
            AND ig_date >= '1984-01-01' AND ig_date <= '2024-12-31'" \
    "$PERIMS"

  # Snap the grid out to whole cells around the data, so the raster covers every perimeter
  # and the cell edges land on round numbers.
  local te
  te=$(python3 - "$w-perims.gpkg" "$RES" <<'PY'
import sys
from osgeo import ogr
ds = ogr.Open(sys.argv[1]); r = int(sys.argv[2])
x0, x1, y0, y1 = ds.GetLayer(0).GetExtent()
import math
print(math.floor(x0/r)*r, math.floor(y0/r)*r, math.ceil(x1/r)*r, math.ceil(y1/r)*r)
PY
)
  echo "   grid extent: $te"

  echo "== $scope: rasterising burn counts =="
  # -add -burn 1: every feature adds one to each cell its interior covers. Cell-centre rule
  # (not -at), so a fire's area is counted the same way the grid measures it.
  gdal_rasterize -l perims -burn 1 -add -ot Byte -init 0 \
    -te $te -tr $RES $RES \
    -co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=YES \
    "$w-perims.gpkg" "$w-count.tif"

  echo "== $scope: sieving speckle =="
  # -nomask so specks stranded in the middle of nowhere are swept up too. Each surviving speck
  # takes the value of its largest neighbour, so a false "2" fringe falls back to the 1 around it.
  gdal_sieve.py -st $SIEVE -of GTiff "$w-count.tif" -nomask "$w-sieved.tif"

  echo "== $scope: polygonising count >= 2 =="
  # count == 1 is just "burned", which the main animation already draws; only the overlaps are
  # this layer's subject. Masking before polygonising rather than filtering after keeps the
  # single-burn footprint — 80% of the area — out of the vectoriser entirely.
  gdal_calc.py -A "$w-sieved.tif" --outfile="$w-mask.tif" --calc="255*(A>=2)" \
    --type=Byte --NoDataValue=0 --co TILED=YES --co COMPRESS=DEFLATE --co BIGTIFF=YES --quiet
  gdal_polygonize.py "$w-sieved.tif" -mask "$w-mask.tif" -f GPKG "$w-repeats.gpkg" repeats count

  echo "== $scope: writing app asset =="
  # 4 decimals ≈ 11 m, well under the 90 m cell. Simplification runs in the source CRS, i.e.
  # in metres, before the reprojection to WGS84.
  #
  # `acres` is measured here rather than in the browser: this CRS is equal-area, so it is a
  # sum in the raster's own units, and it is measured *before* simplification moves any vertex.
  # The app sums it per level to say what a level covers. Nothing is below an acre — the sieve
  # floor puts the smallest possible patch at 16 cells, ~32 acres.
  ogr2ogr -f GeoJSON "$w.geojson" -t_srs EPSG:4326 -simplify $SIMPLIFY \
    -lco COORDINATE_PRECISION=4 -lco RFC7946=NO -dialect SQLite -nln repeats \
    -sql "SELECT geom, count, CAST(ROUND(ST_Area(geom)/4046.86) AS INTEGER) AS acres FROM repeats" \
    "$w-repeats.gpkg"
  gzip -9c "$w.geojson" > "$ROOT/app/data/${scope}_repeats.geojson.gz"

  ogrinfo -dialect SQLite -q \
    -sql "SELECT count, COUNT(*) AS polygons, CAST(ROUND(SUM(ST_Area(geom))/4046.86) AS INTEGER) AS acres
          FROM repeats GROUP BY count ORDER BY count" "$w-repeats.gpkg"
  ls -l "$ROOT/app/data/${scope}_repeats.geojson.gz"
}

WEST="'WA','OR','CA','ID','NV','UT','AZ','MT','WY','CO','NM'"
case "${1:-both}" in
  west) build west "$WEST" ;;
  wa)   build wa   "'WA'" ;;
  both) build west "$WEST"; build wa "'WA'" ;;
  *) echo "usage: $0 [west|wa]" >&2; exit 2 ;;
esac
