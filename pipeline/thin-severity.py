#!/usr/bin/env python3
"""Thin the per-fire severity overlays down to a shippable size.

The raster pass (build-severity.py) writes faithful polygons; this decides how much of that
fidelity is worth carrying in the repo. It works on the GeoJSON rather than the rasters, so a
different budget costs seconds instead of re-downloading 200 MB of mosaics.

Two levers, both applied per fire and scaled to that fire's own size, because every fire is
looked at zoomed to fit — what matters is the detail *per screenful*, which is the same
argument the adaptive sieve makes upstream:

  drop   — a polygon smaller than a share of the fire's total severity area is a speck at the
           zoom this is ever seen at. Dropped specks fall back to the fire's own recency fill
           underneath, which is a graceful absence rather than a hole.
  simp   — Douglas-Peucker in degrees, on ground already quantised to a 30 m grid.

Usage: thin-severity.py [--drop 0.0004] [--simp 0.0006] [--apply]
Without --apply it only reports what the settings would cost, which is how they were chosen.
"""
import glob, gzip, json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAYS = os.path.join(ROOT, 'app/data/severity')


def ring_area(ring):
    """Shoelace, in square degrees — only ever used to compare rings with each other."""
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2


def simplify(ring, tol):
    """Douglas-Peucker. Keeps the first and last point, which for a ring are the same point."""
    if len(ring) <= 4 or tol <= 0:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        ax, ay = ring[i]
        bx, by = ring[j]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        worst, wi = -1.0, -1
        for k in range(i + 1, j):
            px, py = ring[k]
            d = (abs(dx * (ay - py) - (ax - px) * dy) / norm) if norm else math.hypot(px - ax, py - ay)
            if d > worst:
                worst, wi = d, k
        if worst > tol:
            keep[wi] = True
            stack.append((i, wi))
            stack.append((wi, j))
    out = [p for p, k in zip(ring, keep) if k]
    return out if len(out) >= 4 else ring


def thin_polygon(rings, min_area, tol):
    """Drop the whole polygon if its outer ring is a speck; drop hole rings that are."""
    if ring_area(rings[0]) < min_area:
        return None
    out = [simplify(rings[0], tol)]
    for hole in rings[1:]:
        if ring_area(hole) >= min_area:
            out.append(simplify(hole, tol))
    return out


def thin(fc, drop_frac, tol):
    # Total area first: the drop threshold is a fraction of this fire, not an absolute size.
    total = 0.0
    for f in fc['features']:
        g = f['geometry']
        parts = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        for rings in parts:
            total += ring_area(rings[0])
    min_area = total * drop_frac

    feats = []
    for f in fc['features']:
        g = f['geometry']
        parts = g['coordinates'] if g['type'] == 'MultiPolygon' else [g['coordinates']]
        kept = [p for p in (thin_polygon(rings, min_area, tol) for rings in parts) if p]
        if not kept:
            continue
        geom = ({'type': 'Polygon', 'coordinates': kept[0]} if len(kept) == 1
                else {'type': 'MultiPolygon', 'coordinates': kept})
        feats.append({'type': 'Feature', 'properties': f['properties'], 'geometry': geom})
    return {'type': 'FeatureCollection', 'features': feats}


def main():
    args = sys.argv[1:]
    drop = float(args[args.index('--drop') + 1]) if '--drop' in args else 0.0004
    tol = float(args[args.index('--simp') + 1]) if '--simp' in args else 0.0006
    apply_ = '--apply' in args

    files = sorted(glob.glob(os.path.join(OVERLAYS, '*.geojson.gz')))
    before = after = 0
    sizes = []
    polys_before = polys_after = 0
    for path in files:
        raw = os.path.getsize(path)
        before += raw
        with gzip.open(path, 'rt') as fh:
            fc = json.load(fh)
        polys_before += len(fc['features'])
        out = thin(fc, drop, tol)
        polys_after += len(out['features'])
        blob = json.dumps(out, separators=(',', ':')).encode()
        import io
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode='wb', compresslevel=9, mtime=0) as gz:
            gz.write(blob)
        packed = buf.getvalue()
        after += len(packed)
        sizes.append(len(packed))
        if apply_:
            with open(path, 'wb') as fh:
                fh.write(packed)

    sizes.sort()
    n = len(sizes) or 1
    print(f'drop={drop}  simp={tol}  {"APPLIED" if apply_ else "dry run"}')
    print(f'  {len(files):,} files   {before/1e6:.1f} MB -> {after/1e6:.1f} MB '
          f'({after/before*100:.0f}%)')
    print(f'  polygons {polys_before:,} -> {polys_after:,}')
    print(f'  median {sizes[n//2]/1024:.1f} KB   p99 {sizes[int(n*0.99)]/1024:.1f} KB   '
          f'max {sizes[-1]/1024:.1f} KB')


if __name__ == '__main__':
    main()
