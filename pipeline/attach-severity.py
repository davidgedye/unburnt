#!/usr/bin/env python3
"""Fold each fire's severity summary into the main fires dataset, and gzip it.

Two fields per fire, both small enough to ride on the dataset the app already loads:

  sev_ok  — is there a severity overlay to fetch for this fire? The app uses it twice: to give
            those fires an outline in one-year mode, so nobody clicks and hopes, and to decide
            whether a click should fetch anything at all.
  sev     — percent of the fire's mapped area in each class, 1 through 5, as whole numbers.
            Carried here rather than inside the overlay file so the popup can report the
            breakdown the instant it opens, without waiting on a fetch it may not even make.

Percentages are of *mapped* pixels: class 6 (non-processing mask) and unmapped ground are left
out of the denominator, so "62% high" means 62% of what MTBS actually assessed.

Two modes:
  attach-severity.py <in.geojson> <out.geojson.gz>
      the shipped path — reads the global stats file and the per-fire overlay directory, and
      writes a gzipped dataset for the app.
  attach-severity.py --inplace <perims.geojson> <stats.json>
      the tiling path (build-pmtiles-all.sh) — one year at a time, with that year's stats, and
      "has an overlay" means "this fire produced severity polygons" because in a tileset there
      are no per-fire files to look for. Rewrites the GeoJSON in place, before tippecanoe.
"""
import gzip, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATS = os.path.join(ROOT, 'pipeline/data/severity-stats.json')
OVERLAYS = os.path.join(ROOT, 'app/data/severity')
CLASSES = (1, 2, 3, 4, 5)


def main(src, dst):
    stats = json.load(open(STATS)) if os.path.exists(STATS) else {}
    have = set()
    if os.path.isdir(OVERLAYS):
        have = {f[:-len('.geojson.gz')] for f in os.listdir(OVERLAYS)
                if f.endswith('.geojson.gz')}
    print(f'  {len(stats):,} fires with severity stats, {len(have):,} with an overlay file')

    fc = json.load(open(src))
    n_ok = 0
    for feat in fc['features']:
        p = feat['properties']
        fid = p.get('id')
        counts = stats.get(fid)
        # An overlay file is what the app actually fetches, so that — not the stats — is what
        # sev_ok promises. A fire can have counts but no drawable polygons (everything sieved
        # away, or all of it class 6); claiming otherwise would send the app after a 404.
        p['sev_ok'] = fid in have
        if p['sev_ok']:
            n_ok += 1
        if counts:
            mapped = sum(v for k, v in counts.items() if int(k) in CLASSES)
            if mapped:
                p['sev'] = [round(counts.get(str(c), counts.get(c, 0)) * 100 / mapped)
                            for c in CLASSES]
    print(f'  {n_ok:,} of {len(fc["features"]):,} fires carry an overlay')

    with gzip.open(dst, 'wt') as fh:
        json.dump(fc, fh, separators=(',', ':'))
    print(f'  wrote {dst} ({os.path.getsize(dst) / 1e6:.2f} MB)')


def inplace(perims_path, stats_path):
    """One year's perimeters, tagged from that year's severity stats, rewritten in place."""
    stats = json.load(open(stats_path)) if os.path.exists(stats_path) else {}
    fc = json.load(open(perims_path))
    n_ok = 0
    for feat in fc['features']:
        p = feat['properties']
        counts = stats.get(p.get('id'))
        # In a tileset there is no per-fire file to check for, so "has severity" is decided by
        # whether any drawable class came back for this fire — which is the same question.
        mapped = sum(v for k, v in (counts or {}).items() if int(k) in CLASSES)
        p['sev_ok'] = bool(mapped)
        if mapped:
            n_ok += 1
            p['sev'] = [round(counts.get(str(c), counts.get(c, 0)) * 100 / mapped)
                        for c in CLASSES]
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
