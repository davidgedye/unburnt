#!/usr/bin/env python3
"""Build per-fire burn-severity overlays from the MTBS annual thematic mosaics (#14).

One small gzipped GeoJSON per fire, fetched by the app only when that fire is clicked, plus a
per-fire class breakdown folded back into the main fires dataset. Severity is 30 m detail on a
single fire — meaningless at a whole-West zoom — so it is never a map-wide layer.

**Source: the annual CONUS mosaics, not per-fire rasters.** The plan in issue #14 called for
MTBS's per-fire severity rasters, on the grounds that they populate as each fire's own extended
assessment finishes rather than waiting on the mosaic release. They are not publicly
scriptable: the old `edcintl .../individual_fire_data/` tree is gone (404), directory listings
are 403, the mtbs.gov ETD API is a mapping-status tracker with no rasters, and a ScienceBase
search turns up no per-fire product. The annual mosaics are confirmed complete — 41 child items
under ScienceBase 5e91dee782ce172707f02cdd, no gaps — so they are what this builds from. The
cost is the documented ~2-year lag: the newest season or two is mostly unmapped. That is not
hidden, it is exactly what the `severity` flag on each fire is for, so the app can show which
fires have data before anyone clicks.

Per fire: window-read that fire's bbox out of the year's mosaic (a few ms — no clipping of the
full 137k x 89k raster), mask to the perimeter, sieve, polygonize by class, reproject, simplify,
gzip. Class 1 unburned/low, 2 low, 3 moderate, 4 high, 5 increased greenness, 6 masked.

Usage: pipeline/build-severity.py <year> [<year> ...]      or  --all
Needs the user-space GIS env and the year's mosaic under pipeline/data/mosaicYYYY/.
"""
import gzip, json, math, os, sys, time
import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERIMS = os.path.join(ROOT, 'pipeline/data/perimeters/mtbs_perims_DD.shp')
OUTDIR = os.path.join(ROOT, 'app/data/severity')
STATS = os.path.join(ROOT, 'pipeline/data/severity-stats.json')
WEST = ('WA', 'OR', 'CA', 'ID', 'NV', 'UT', 'AZ', 'MT', 'WY', 'CO', 'NM')

# Classes worth drawing. 6 (masked) and 0 (nodata) are absence, not a severity, and are counted
# in the stats rather than drawn. 5 (increased greenness) is ~0.2% of area but is real, so it
# is kept — leaving it out would silently turn it into a hole.
DRAW = (1, 2, 3, 4, 5)
SIMPLIFY_M = 45          # ~1.5 pixels: strips the rasterisation staircase and little else

# The sieve threshold scales with the fire, rather than being one number for all of them.
# Every fire is looked at zoomed to fit, so what matters is how much *visual* complexity each
# overlay carries, not how many acres a speck is. A fixed threshold gives a megafire a hundred
# times the polygons of a small burn for the same screenful, which is both unreadable and where
# almost all the bytes go. Scaling it holds each fire to roughly the same detail — and takes the
# 41-year build from ~104 MB to something shippable.
SIEVE_MIN, SIEVE_MAX, SIEVE_DIV = 30, 500, 1500


def sieve_for(area_px):
    return int(min(SIEVE_MAX, max(SIEVE_MIN, area_px / SIEVE_DIV)))


def mem_raster(arr, gt, srs_wkt):
    """Wrap a numpy array as an in-memory single-band raster GDAL can sieve and polygonize."""
    drv = gdal.GetDriverByName('MEM')
    ds = drv.Create('', arr.shape[1], arr.shape[0], 1, gdal.GDT_Byte)
    ds.SetGeoTransform(gt)
    ds.SetProjection(srs_wkt)
    ds.GetRasterBand(1).WriteArray(arr)
    return ds


def fire_severity(mosaic, gt, inv_gt, srs_wkt, geom, to_wgs):
    """Severity polygons (as GeoJSON) and class pixel counts for one perimeter.

    The GeoJSON is built in here rather than returned as a layer: GDAL invalidates a layer the
    moment its datasource is collected, and an in-memory datasource that only a local holds is
    collected the instant this returns.
    """
    x0, x1, y0, y1 = geom.GetEnvelope()
    # Pixel window for the bounding box, grown a pixel each way so nothing on the edge is lost.
    cols = [gdal.ApplyGeoTransform(inv_gt, x, y) for x in (x0, x1) for y in (y0, y1)]
    px = [int(math.floor(c[0])) for c in cols]
    py = [int(math.floor(c[1])) for c in cols]
    c0, c1 = max(0, min(px) - 1), min(mosaic.RasterXSize, max(px) + 2)
    r0, r1 = max(0, min(py) - 1), min(mosaic.RasterYSize, max(py) + 2)
    if c1 <= c0 or r1 <= r0:
        return None, None                     # the fire is outside the mosaic's extent entirely

    arr = mosaic.GetRasterBand(1).ReadAsArray(c0, r0, c1 - c0, r1 - r0)
    if arr is None or not arr.any():
        return None, None                     # nothing mapped here — the usual case for 2024

    win_gt = (gt[0] + c0 * gt[1], gt[1], 0, gt[3] + r0 * gt[5], 0, gt[5])

    # Burn the perimeter into a mask over the same window, so a neighbouring fire's pixels
    # bleeding into this bbox are not counted as this fire's.
    mask_ds = mem_raster(np.zeros(arr.shape, np.uint8), win_gt, srs_wkt)
    mem = ogr.GetDriverByName('Memory').CreateDataSource('m')
    srs = osr.SpatialReference(); srs.ImportFromWkt(srs_wkt)
    lyr = mem.CreateLayer('p', srs=srs, geom_type=ogr.wkbMultiPolygon)
    f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(geom); lyr.CreateFeature(f)
    gdal.RasterizeLayer(mask_ds, [1], lyr, burn_values=[1])
    inside = mask_ds.GetRasterBand(1).ReadAsArray() == 1

    arr = np.where(inside, arr, 0).astype(np.uint8)
    counts = {int(v): int(n) for v, n in zip(*np.unique(arr[arr > 0], return_counts=True))}
    if not counts:
        return None, None

    # Sieve, then polygonize only the classes worth drawing.
    src = mem_raster(arr, win_gt, srs_wkt)
    gdal.SieveFilter(src.GetRasterBand(1), None, src.GetRasterBand(1),
                     sieve_for(int(inside.sum())), 4)
    drawable = np.isin(src.GetRasterBand(1).ReadAsArray(), DRAW).astype(np.uint8) * 255
    if not drawable.any():
        return None, counts
    mask2 = mem_raster(drawable, win_gt, srs_wkt)

    out = ogr.GetDriverByName('Memory').CreateDataSource('o')
    olyr = out.CreateLayer('sev', srs=srs, geom_type=ogr.wkbPolygon)
    olyr.CreateField(ogr.FieldDefn('sev', ogr.OFTInteger))
    gdal.Polygonize(src.GetRasterBand(1), mask2.GetRasterBand(1), olyr, 0)
    return to_geojson(olyr, to_wgs), counts


def to_geojson(layer, to_wgs):
    """Reproject, simplify and round. Coordinates at 5 dp (~1 m) — the source is 30 m."""
    feats = []
    for f in layer:
        g = f.GetGeometryRef().Simplify(SIMPLIFY_M)
        if g is None or g.IsEmpty():
            continue
        g = g.Clone()
        g.Transform(to_wgs)
        gj = json.loads(g.ExportToJson())
        gj['coordinates'] = round_coords(gj['coordinates'])
        feats.append({'type': 'Feature', 'properties': {'sev': f.GetField('sev')},
                      'geometry': gj})
    return {'type': 'FeatureCollection', 'features': feats}


def round_coords(c):
    if isinstance(c[0], (int, float)):
        return [round(c[0], 4), round(c[1], 4)]
    return [round_coords(p) for p in c]


def build_year(year, perims, stats):
    path = os.path.join(ROOT, f'pipeline/data/mosaic{year}/mtbs_CONUS_{year}.tif')
    if not os.path.exists(path):
        print(f'{year}: no mosaic at {path} — skipped')
        return 0, 0
    mosaic = gdal.Open(path)
    gt = mosaic.GetGeoTransform()
    inv_gt = gdal.InvGeoTransform(gt)
    srs_wkt = mosaic.GetProjection()
    msrs = osr.SpatialReference(); msrs.ImportFromWkt(srs_wkt)
    msrs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    wgs = osr.SpatialReference(); wgs.ImportFromEPSG(4326)
    wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    to_mosaic = osr.CoordinateTransformation(perims.GetSpatialRef(), msrs)
    to_wgs = osr.CoordinateTransformation(msrs, wgs)

    perims.SetAttributeFilter(
        "SUBSTR(event_id,1,2) IN ('" + "','".join(WEST) + "') "
        f"AND ig_date >= '{year}-01-01' AND ig_date <= '{year}-12-31'")
    perims.ResetReading()

    built = total = 0
    t0 = time.time()
    for feat in perims:
        total += 1
        fid = feat.GetField('event_id')
        geom = feat.GetGeometryRef().Clone()
        geom.Transform(to_mosaic)
        fc, counts = fire_severity(mosaic, gt, inv_gt, srs_wkt, geom, to_wgs)
        if not counts:
            continue
        stats[fid] = counts
        if fc is None or not fc['features']:
            continue
        with gzip.open(os.path.join(OUTDIR, f'{fid}.geojson.gz'), 'wt') as fh:
            json.dump(fc, fh, separators=(',', ':'))
        built += 1
    print(f'{year}: {built}/{total} fires with severity  ({time.time() - t0:.0f}s)')
    return built, total


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__.strip().splitlines()[-3])
        return 2
    years = ([str(y) for y in range(1984, 2025)] if args[0] == '--all' else args)
    os.makedirs(OUTDIR, exist_ok=True)
    stats = {}
    if os.path.exists(STATS):
        stats = json.load(open(STATS))
    ds = ogr.Open(PERIMS)
    perims = ds.GetLayer(0)
    built = total = 0
    for y in years:
        b, t = build_year(y, perims, stats)
        built += b; total += t
    json.dump(stats, open(STATS, 'w'), separators=(',', ':'))
    print(f'\n{built} severity overlays for {total} fires; stats for {len(stats)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
