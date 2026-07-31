#!/usr/bin/env python3
"""Fold each fire's severity summary into the main fires dataset.

Two fields per fire:

  sev_ok  — did this fire produce drawable severity polygons? The app uses it twice: to give
            those fires an outline in Single Year, so nobody clicks and hopes, and to decide
            whether a click has anything to show.
  sev     — percent of the fire's mapped area in each class, 1 through 5, as whole numbers, so
            the popup can report the breakdown the instant it opens.

Both modes now decide sev_ok the same way. It used to mean "a per-fire overlay file exists in
app/data/severity", which was true of the GeoJSON path and is meaningless now that severity
lives in per-year tilesets and those 10,505 files are gone. Left alone it would have quietly
marked every fire as having no severity the next time the dataset was rebuilt.

The stats come from severity-full.py, accumulated across years by build-pmtiles-all.sh, so
there is one source of truth for what burned how hard rather than a tiled one and a shipped one.

Two modes:
  attach-severity.py <in.geojson> <out.geojson.gz>
      the whole record at once, from pipeline/data/severity-stats.json — used by build-fires.sh
      to write the dataset the app still loads for GPX burn history.
  attach-severity.py --inplace <perims.geojson> <stats.json>
      one year, with that year's stats, rewritten in place before tippecanoe.
"""
import gzip, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS = os.path.join(ROOT, 'pipeline/data/severity-stats.json')
CLASSES = (1, 2, 3, 4, 5)


def tag(fc, stats):
    """Stamp sev_ok and the class breakdown onto a FeatureCollection, in place.

    One rule for both callers. `sev_ok` means "this fire produced drawable severity polygons",
    which is what decides whether it gets an outline and whether a click has anything to show.
    It used to mean "a per-fire overlay file exists on disk" — those files are gone, and with
    them the only reason the two modes differed.

    Percentages are of *mapped* pixels: class 6 (non-processing mask) and unmapped ground are
    left out of the denominator, so "62% high" means 62% of what MTBS actually assessed.
    """
    n_ok = 0
    for feat in fc['features']:
        p = feat['properties']
        counts = stats.get(p.get('id'))
        mapped = sum(v for k, v in (counts or {}).items() if int(k) in CLASSES)
        p['sev_ok'] = bool(mapped)
        if mapped:
            n_ok += 1
            p['sev'] = [round(counts.get(str(c), counts.get(c, 0)) * 100 / mapped)
                        for c in CLASSES]
    return n_ok


def main(src, dst):
    stats = json.load(open(STATS)) if os.path.exists(STATS) else {}
    print(f'  {len(stats):,} fires with severity stats')
    fc = json.load(open(src))
    n_ok = tag(fc, stats)
    print(f'  {n_ok:,} of {len(fc["features"]):,} fires have severity')
    with gzip.open(dst, 'wt') as fh:
        json.dump(fc, fh, separators=(',', ':'))
    print(f'  wrote {dst} ({os.path.getsize(dst) / 1e6:.2f} MB)')


def inplace(perims_path, stats_path):
    """One year's perimeters, tagged from that year's severity stats, rewritten in place."""
    stats = json.load(open(stats_path)) if os.path.exists(stats_path) else {}
    fc = json.load(open(perims_path))
    n_ok = tag(fc, stats)
    with open(perims_path, 'w') as fh:
        json.dump(fc, fh, separators=(',', ':'))
    print(f'   {n_ok}/{len(fc["features"])} fires tagged with severity')


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--inplace':
        inplace(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 3:
        main(sys.argv[1], sys.argv[2])
    else:
        print(__doc__.strip())
        sys.exit(2)
