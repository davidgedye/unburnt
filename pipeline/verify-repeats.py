#!/usr/bin/env python3
"""Independent check that the repeat-burn counts are right.

The build (pipeline/build-repeats.sh) answers "how many fires have crossed this ground?" on a
raster. This script answers the same question a completely different way — exact point-in-polygon
against the original MTBS perimeters — and compares. Nothing here reuses the raster, the sieve
or the polygonizer, so an error in any of them shows up as disagreement.

Three tests:

  A. Sample points inside the shipped repeat polygons. For each, count how many perimeters
     actually contain it. That count must equal the polygon's `count`.
  B. Sample points inside the perimeters generally, including ground the repeat layer says is
     single-burn. Catches the opposite error — reburn the layer failed to find.
  C. Conservation. `-add` stamps every fire once per cell it covers, so summing count x area
     over the whole raster must reproduce the total area of all 11,377 perimeter polygons.
     This one is exact arithmetic, so it isolates rasterisation error from everything else.

Mismatches are bucketed by distance from the patch edge, because near an edge the two methods
*should* disagree: the grid is 90 m and the shipped geometry is simplified by another 90 m, so
within ~130 m of a boundary "which polygon is this point in" is genuinely ambiguous.

Usage: pipeline/verify-repeats.py [samples]      (default 600 per test)
Needs the build's working files in pipeline/data/repeats/ and the user-space GIS env.
"""
import gzip, json, math, random, sys, os
from osgeo import ogr, osr

ogr.UseExceptions()
random.seed(20260727)                      # reproducible

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHIPPED = os.path.join(ROOT, 'app/data/west_repeats.geojson.gz')
PERIMS = os.path.join(ROOT, 'pipeline/data/repeats/west-perims.gpkg')   # the 11,377, in Albers
SIEVED = os.path.join(ROOT, 'pipeline/data/repeats/west-sieved.tif')
RAW = os.path.join(ROOT, 'pipeline/data/repeats/west-count.tif')      # pre-sieve
N = int(sys.argv[1]) if len(sys.argv) > 1 else 600
RES, ACRE = 90, 4046.86

wgs = osr.SpatialReference(); wgs.ImportFromEPSG(4326)
alb = osr.SpatialReference(); alb.ImportFromEPSG(5070)
wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
alb.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
to_alb = osr.CoordinateTransformation(wgs, alb)

print(f'Loading {SHIPPED} …')
with gzip.open(SHIPPED) as f:
    fc = json.load(f)
feats = fc['features']
print(f'  {len(feats):,} repeat polygons')

perims_ds = ogr.Open(PERIMS)               # keep the handle: GDAL invalidates layers when the
perims = perims_ds.GetLayer(0)             # datasource is collected. GPKG has an RTree index.
print(f'  {perims.GetFeatureCount():,} source perimeters (EPSG:5070)\n')


def true_count(x, y):
    """How many perimeters actually contain this Albers point. The exact answer."""
    pt = ogr.Geometry(ogr.wkbPoint); pt.AddPoint_2D(x, y)
    perims.SetSpatialFilter(pt)
    n = 0
    for f in perims:
        if f.GetGeometryRef().Contains(pt):
            n += 1
    perims.SetSpatialFilter(None)
    return n


def random_point_in(geom, tries=60):
    """Rejection-sample a point inside a polygon, in the geometry's own CRS."""
    x0, x1, y0, y1 = geom.GetEnvelope()
    for _ in range(tries):
        pt = ogr.Geometry(ogr.wkbPoint)
        pt.AddPoint_2D(random.uniform(x0, x1), random.uniform(y0, y1))
        if geom.Contains(pt):
            return pt
    return None


def edge_dist_m(geom, pt):
    """Metres from the point to the patch boundary (geom in WGS84, so scale by latitude)."""
    d = geom.Boundary().Distance(pt)
    return d * 111_320 * math.cos(math.radians(pt.GetY()))


class Raster:
    """Point sampler for the build's intermediate rasters, so a mismatch can be blamed on the
    step that caused it rather than left as noise."""

    def __init__(self, path):
        from osgeo import gdal
        self.ds = gdal.Open(path)
        self.band = self.ds.GetRasterBand(1)
        gt = self.ds.GetGeoTransform()
        self.x0, self.px, self.y0, self.py = gt[0], gt[1], gt[3], gt[5]

    def at(self, x, y):                              # x, y in EPSG:5070
        c, r = int((x - self.x0) / self.px), int((y - self.y0) / self.py)
        if not (0 <= c < self.ds.RasterXSize and 0 <= r < self.ds.RasterYSize):
            return None
        return int(self.band.ReadAsArray(c, r, 1, 1)[0][0])


def attribute(rows, raw, sieved):
    """Every disagreement should be explained by one of the three lossy steps, in order.
    If any land in 'unexplained', something is actually wrong."""
    bad = [r for r in rows if not r['match']]
    if not bad:
        return
    tally = {}
    for r in bad:
        a, b = raw.at(*r['alb']), sieved.at(*r['alb'])
        if a != r['want']:
            why = 'rasterisation (pixel-centre rule at a perimeter edge)'
        elif b != r['want']:
            why = 'sieve (a reburn sliver under the 32-acre floor, removed by design)'
        elif b != r['got']:
            why = 'simplification (the 90 m boundary moved past this point)'
        else:
            why = 'UNEXPLAINED'
        tally[why] = tally.get(why, 0) + 1
    print('      cause of each disagreement:')
    for why, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f'        {n:3d}  {why}')


raw_r, sieved_r = Raster(RAW), Raster(SIEVED)      # for blaming mismatches on a build step


def bucket(rows, label):
    """Agreement overall and by distance from the patch edge."""
    ok = sum(1 for r in rows if r['match'])
    print(f'  {label}: {ok}/{len(rows)} agree ({ok / len(rows) * 100:.1f}%)')
    edges = [(0, 130, 'within 130 m of an edge (ambiguous by construction)'),
             (130, 500, '130-500 m from an edge'),
             (500, 1e12, 'more than 500 m from an edge')]
    for lo, hi, name in edges:
        sub = [r for r in rows if lo <= r['d'] < hi]
        if not sub:
            continue
        k = sum(1 for r in sub if r['match'])
        print(f'      {name}: {k}/{len(sub)} ({k / len(sub) * 100:.1f}%)')
    bad = [r for r in rows if not r['match']]
    if bad:
        off = {}
        for r in bad:
            off[r['got'] - r['want']] = off.get(r['got'] - r['want'], 0) + 1
        print('      mismatches by size: ' +
              ', '.join(f'{k:+d}: {v}' for k, v in sorted(off.items())))


# --- A. points inside the shipped repeat polygons ----------------------------
# Area-weighted, so the sample describes the ground a user is likely to click rather than
# over-representing the thousands of tiny patches.
print('A. Do the shipped polygons report the right count?')
weights = [f['properties']['acres'] or 1 for f in feats]
rows = []
while len(rows) < N:
    f = random.choices(feats, weights=weights)[0]
    g = ogr.CreateGeometryFromJson(json.dumps(f['geometry']))
    pt = random_point_in(g)
    if pt is None:
        continue
    d = edge_dist_m(g, pt)
    p = pt.Clone(); p.Transform(to_alb)
    got = true_count(p.GetX(), p.GetY())
    want = f['properties']['count']
    # `got` is the truth here and `want` is the claim, so they swap going into attribute(),
    # which always reads 'want' as truth and 'got' as what the layer said.
    rows.append({'match': got == want, 'got': want, 'want': got, 'd': d,
                 'alb': (p.GetX(), p.GetY())})
bucket(rows, 'claimed count vs. perimeters actually covering the point')
attribute(rows, raw_r, sieved_r)

# --- B. the opposite error: reburn the layer missed ---------------------------
# Sample anywhere inside the burned footprint, look the point up in the repeat layer (absent
# means the layer is claiming a single burn), and compare with the truth.
print('\nB. Is any reburn missing from the layer?')
idx = ogr.GetDriverByName('Memory').CreateDataSource('idx')
lyr = idx.CreateLayer('r', srs=wgs, geom_type=ogr.wkbMultiPolygon)
lyr.CreateField(ogr.FieldDefn('count', ogr.OFTInteger))
for f in feats:
    ft = ogr.Feature(lyr.GetLayerDefn())
    ft.SetField('count', f['properties']['count'])
    ft.SetGeometry(ogr.CreateGeometryFromJson(json.dumps(f['geometry'])))
    lyr.CreateFeature(ft)

to_wgs = osr.CoordinateTransformation(alb, wgs)


def nearest_patch_m(pt, reach=0.05):
    """Metres to the nearest repeat patch. For a point the layer calls single-burn, this is the
    distance that decides whether a disagreement is an edge effect or a real miss."""
    x, y = pt.GetX(), pt.GetY()
    box = ogr.CreateGeometryFromWkt(
        f'POLYGON(({x-reach} {y-reach},{x+reach} {y-reach},{x+reach} {y+reach},'
        f'{x-reach} {y+reach},{x-reach} {y-reach}))')
    lyr.SetSpatialFilter(box)
    best = float('inf')
    for f in lyr:
        best = min(best, f.GetGeometryRef().Distance(pt))
    lyr.SetSpatialFilter(None)
    return best * 111_320 * math.cos(math.radians(y)) if best < float('inf') else 1e12


rows = []
perims.ResetReading()
all_perims = [f.GetGeometryRef().Clone() for f in perims]
while len(rows) < N:
    g = random.choice(all_perims)
    pt = random_point_in(g)
    if pt is None:
        continue
    truth = true_count(pt.GetX(), pt.GetY())
    w = pt.Clone(); w.Transform(to_wgs)
    lyr.SetSpatialFilter(w)
    claimed, patch = 1, None                       # not in the layer == "burned once"
    for f in lyr:
        if f.GetGeometryRef().Contains(w):
            claimed, patch = f.GetField('count'), f.GetGeometryRef().Clone()
    lyr.SetSpatialFilter(None)
    # Inside a patch: distance to its own edge. Outside: distance to the nearest patch — a
    # miss 2 km from any reburn would be a real error, one 40 m away is the grid.
    d = edge_dist_m(patch, w) if patch is not None else nearest_patch_m(w)
    rows.append({'match': claimed == truth, 'got': claimed, 'want': truth, 'd': d,
                 'inside': patch is not None, 'alb': (pt.GetX(), pt.GetY())})
inside = [r for r in rows if r['inside']]
outside = [r for r in rows if not r['inside']]
bucket(rows, 'layer\'s answer vs. truth, sampled across the whole burned footprint')
print(f'      of those, {len(inside)} landed inside a repeat patch and {len(outside)} on ground '
      f'the layer calls single-burn')
if outside:
    k = sum(1 for r in outside if r['match'])
    print(f'      single-burn ground correct: {k}/{len(outside)} ({k / len(outside) * 100:.1f}%)')
attribute(rows, raw_r, sieved_r)

# --- C. conservation ---------------------------------------------------------
print('\nC. Does the raster conserve total burned area?')
from osgeo import gdal
gdal.UseExceptions()
ds = gdal.Open(SIEVED)
h = ds.GetRasterBand(1).GetHistogram(-0.5, 255.5, 256, 0, 0)
stamped = sum(v * c for v, c in enumerate(h)) * RES * RES / ACRE
perims.ResetReading()
truth = sum(f.GetGeometryRef().GetArea() for f in perims) / ACRE
print(f'  sum of count x cell area : {stamped:15,.0f} acres')
print(f'  sum of perimeter areas   : {truth:15,.0f} acres')
print(f'  difference               : {(stamped - truth) / truth * 100:+15.3f}%')
