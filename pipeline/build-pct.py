#!/usr/bin/env python3
"""The Pacific Crest Trail, from OpenStreetMap, as GPX per section and one bundle for the app.

Replaces the ~40 hand-typed waypoints that used to stand in for the trail (#15). Those came out
at 1,336 miles against the real 2,650, because straight lines between remembered landmarks cut
every switchback -- it crossed real fires more by luck of passing through the right corridors
than by following the tread.

Source is OSM relation 1225378, the PCT superroute. Two reasons over the published per-section
downloads: it is already cut on the official guidebook boundaries -- California A-R, Oregon B-G,
Washington H-L -- so no reconciling is needed, and it is ODbL, which is the licence the About
panel already credits OpenStreetMap under. Redistributing anyone else's files would need their
terms checked first.

Nothing is stitched. Each OSM way becomes its own GPX <trkseg> / MultiLineString member: the app
parses every trkseg of a trk into one MultiLineString and draws no line across a break, so
orientation never has to be worked out and no join can be invented that is not in the data.
Measured identical to the stitched version at 2,622.8 miles.

Two outputs, both under app/ so both deploy:
  app/pct/<section>.gpx    full resolution, 258,096 points, ~13 MB across 29 files, served at
                           /pct/<section>.gpx -- for carrying, or for dropping back into the map.
  app/data/pct.geojson.gz  the same trail simplified to ~10 m, ~300 KB, one feature per section.
                           What the 'p' easter egg fetches.

Usage: build-pct.py            # uses cached OSM responses if present, else fetches
       build-pct.py --refresh  # re-fetch from OSM
"""
import gzip, json, math, os, sys, html, urllib.request, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'pipeline', 'data', 'pct')
GPX_DIR = os.path.join(ROOT, 'app', 'pct')
BUNDLE = os.path.join(ROOT, 'app', 'data', 'pct.geojson.gz')
REL = 1225378
UA = 'unburnt/1.0 (https://github.com/davidgedye/unburnt)'
SIMPLIFY_DEG = 0.00009          # ~10 m; keeps 2,566.8 of 2,622.8 miles at a twentieth the size
R_MI = 3958.7613


def get(url, dest, refresh):
    if os.path.exists(dest) and not refresh:
        return json.load(open(dest))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            json.dump(data, open(dest, 'w'))
            return data
        except Exception as e:                      # Overpass rate-limits; the OSM API 503s
            if attempt == 3:
                raise
            print(f'  {type(e).__name__}, retrying in {20 * (attempt + 1)}s')
            time.sleep(20 * (attempt + 1))


def miles(a, b):
    """a, b are (lon, lat)."""
    p1, p2 = math.radians(a[1]), math.radians(b[1])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[0] - a[0]) / 2) ** 2)
    return 2 * R_MI * math.asin(min(1, math.sqrt(h)))


def rdp(pts, eps):
    """Ramer-Douglas-Peucker, iterative -- the trail has runs long enough to blow a recursive one."""
    if len(pts) < 3:
        return pts
    def dist(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == dy == 0:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
        return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        k, dmax = -1, 0.0
        for m in range(i + 1, j):
            d = dist(pts[m], pts[i], pts[j])
            if d > dmax:
                k, dmax = m, d
        if dmax > eps:
            keep.add(k)
            stack += [(i, k), (k, j)]
    return [pts[i] for i in sorted(keep)]


def main(refresh=False):
    print('fetching relation structure')
    top = get(f'https://api.openstreetmap.org/api/0.6/relation/{REL}.json',
              f'{CACHE}/top.json', refresh)['elements'][0]
    sub_ids = [m['ref'] for m in top['members'] if m['type'] == 'relation']
    subs = {r['id']: r for r in get(
        'https://api.openstreetmap.org/api/0.6/relations.json?relations='
        + ','.join(map(str, sub_ids)), f'{CACHE}/subs.json', refresh)['elements']}

    print('fetching way geometry')
    # Overpass rather than the OSM API: one request for every way in the tree, with coordinates
    # inlined, instead of ~1,000 way fetches plus their nodes.
    q = f'[out:json][timeout:900];rel({REL});>>->.all;way.all;out geom;'
    ways = {w['id']: w for w in get(
        'https://overpass-api.de/api/interpreter?data=' + urllib.parse.quote(q),
        f'{CACHE}/ways.json', refresh)['elements'] if w['type'] == 'way'}

    os.makedirs(GPX_DIR, exist_ok=True)
    feats, total, simple_total, rows = [], 0.0, 0.0, []

    for m in top['members']:
        if m['type'] != 'relation' or m['ref'] not in subs:
            continue
        sub = subs[m['ref']]
        name = sub['tags'].get('name', str(m['ref']))
        segs = [[(p['lon'], p['lat']) for p in ways[w['ref']]['geometry']]
                for w in sub['members']
                if w['type'] == 'way' and w['ref'] in ways and ways[w['ref']].get('geometry')]
        if not segs:
            continue

        esc = html.escape(name)
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<gpx version="1.1" creator="unburnt" '
               'xmlns="http://www.topografix.com/GPX/1/1">',
               f'  <metadata><name>{esc}</name>'
               '<copyright author="OpenStreetMap contributors">'
               '<license>https://opendatacommons.org/licenses/odbl/</license></copyright>'
               '</metadata>',
               f'  <trk><name>{esc}</name>']
        for s in segs:
            out.append('    <trkseg>')
            out += [f'      <trkpt lat="{la:.6f}" lon="{lo:.6f}"/>' for lo, la in s]
            out.append('    </trkseg>')
        out += ['  </trk>', '</gpx>', '']
        slug = name.lower().replace('pct - ', '').replace(' section ', '-').replace(' ', '-')
        with open(os.path.join(GPX_DIR, f'{slug}.gpx'), 'w') as fh:
            fh.write('\n'.join(out))

        small = [t for t in (rdp(s, SIMPLIFY_DEG) for s in segs) if len(t) > 1]
        # The GPX keeps OSM's own name; the bundle carries a shorter one, because these become
        # 29 rows in the track panel and "PCT - California Section A" is mostly punctuation.
        feats.append({
            'type': 'Feature',
            'properties': {'name': name.replace('PCT - ', 'PCT — ').replace(' Section ', ' ')},
            'geometry': {'type': 'MultiLineString',
                         'coordinates': [[[round(x, 5), round(y, 5)] for x, y in s]
                                         for s in small]},
        })
        d = sum(miles(s[i], s[i + 1]) for s in segs for i in range(len(s) - 1))
        ds = sum(miles(s[i], s[i + 1]) for s in small for i in range(len(s) - 1))
        total += d
        simple_total += ds
        rows.append((name, sum(len(s) for s in segs), sum(len(s) for s in small), d, ds))

    raw = json.dumps({'type': 'FeatureCollection', 'features': feats},
                     separators=(',', ':')).encode()
    os.makedirs(os.path.dirname(BUNDLE), exist_ok=True)
    with gzip.open(BUNDLE, 'wb', compresslevel=9) as fh:
        fh.write(raw)

    print()
    print('%-34s %8s %8s %9s %9s' % ('section', 'points', 'simple', 'miles', 'simple'))
    for n, p, sp, d, ds in rows:
        print('%-34s %8d %8d %9.1f %9.1f' % (n, p, sp, d, ds))
    print('%-34s %8d %8d %9.1f %9.1f' % ('TOTAL', sum(r[1] for r in rows),
                                         sum(r[2] for r in rows), total, simple_total))
    print()
    print(f'{len(rows)} GPX files in {GPX_DIR}')
    print(f'{BUNDLE}: {os.path.getsize(BUNDLE) / 1e3:.1f} KB gzipped '
          f'({len(raw) / 1e3:.1f} KB raw)')


if __name__ == '__main__':
    import urllib.parse
    main('--refresh' in sys.argv)
