#!/usr/bin/env python3
"""Per-year fire counts and acreage, as a standalone file.

The app derives these by summing the whole fires dataset at load. That works because the whole
dataset is in memory — which is exactly what the tiled data path stops being true. A vector
tile source only ever holds what is on screen, so nothing can aggregate 41 years out of it, and
the year rail, the stat bar and the animation's own state (`years`, `N`) all need those totals
before the first frame.

So they are precomputed. The result is a few hundred bytes against the 3.15 MB it replaces.

Usage: build-year-summary.py            # both scopes, from the shipped fires datasets
"""
import gzip, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def build(scope):
    src = os.path.join(ROOT, f'app/data/{scope}_fires.geojson.gz')
    with gzip.open(src) as fh:
        fc = json.load(fh)

    acres, count, sev = {}, {}, {}
    for f in fc['features']:
        p = f['properties']
        y = int(p['ig_date'][:4])
        acres[y] = acres.get(y, 0) + (p.get('acres') or 0)
        count[y] = count.get(y, 0) + 1          # counted even when its acreage is missing
        sev[y] = sev.get(y, 0) + (1 if p.get('sev_ok') else 0)

    years = sorted(count)
    out = {
        'years': years,
        'fires': [count[y] for y in years],
        # Whole acres: the stat bar rounds to integers anyway, and this halves the file.
        'acres': [round(acres[y]) for y in years],
        # Fires with mapped severity, per year. Carried so the app can tell an upstream gap
        # apart from the assessment lag: MTBS runs a season or two behind, so a *recent* year
        # with little or no severity is simply waiting, while an *old* year with none of it at
        # all means the source mosaic could not be had (#16). Same number either way; only the
        # app can say which, because only it knows which year is the newest on show.
        'sev': [sev[y] for y in years],
    }
    dst = os.path.join(ROOT, f'app/data/{scope}_years.json')
    with open(dst, 'w') as fh:
        json.dump(out, fh, separators=(',', ':'))
    print(f'  {scope}: {len(years)} years, {sum(out["fires"]):,} fires, '
          f'{sum(out["acres"]):,} acres -> {os.path.getsize(dst)} bytes')


if __name__ == '__main__':
    for scope in (sys.argv[1:] or ['west', 'wa']):
        build(scope)
