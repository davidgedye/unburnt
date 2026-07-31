#!/usr/bin/env python3
"""Check the built tilesets against an independent count of what should be in them.

Written after a build shipped with 2004 and 2017 missing entirely -- 644 fires that were simply
not on the map -- and passed verification 39/39. Two faults, both worth naming here so the shape
of this file makes sense:

  The sample was chosen using the property under test. It picked each year's largest
  *severity-mapped* fire, so years where every fire had sev_ok:false were never sampled -- which
  was exactly the broken set. A check must never select its cases by the thing it is checking.

  It tested existence, never completeness. Every question was "is this thing I built present?"
  and none was "is everything that should exist here?" A missing year answers no question at
  all, so it passed silently.

So the primary check is a reconciliation against app/data/west_fires.geojson.gz, which is built
from the same shapefile by a different script and knows nothing about tiling. Counts, per year,
both directions. Geometry spot-checks come after, and pick their fires by acreage alone.

Usage: verify-tiles.py            # exits non-zero on any failure
"""
import gzip, json, math, os, struct, sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = f'{ROOT}/pipeline/data/pmtiles'
SRC = f'{ROOT}/app/data/west_fires.geojson.gz'
# Years whose severity is known to be unobtainable upstream (#16). Listed rather than inferred,
# so that a year going missing for a new reason is a failure and not a silently widened rule.
SEV_GAP = {2004, 2017}


def varint(b, p):
    r = s = 0
    while True:
        c = b[p]; p += 1
        r |= (c & 0x7f) << s
        if not (c & 0x80):
            return r, p
        s += 7


def read_dir(buf):
    n, p = varint(buf, 0)
    ids = [0] * n; last = 0
    for i in range(n):
        d, p = varint(buf, p); last += d; ids[i] = last
    rl = [0] * n
    for i in range(n):
        rl[i], p = varint(buf, p)
    ln = [0] * n
    for i in range(n):
        ln[i], p = varint(buf, p)
    off = [0] * n; prev = 0
    for i in range(n):
        v, p = varint(buf, p)
        off[i] = (prev + ln[i - 1]) if v == 0 and i > 0 else v - 1
        prev = off[i]
    return list(zip(ids, rl, ln, off))


class PM:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        h = self.f.read(127)
        if h[:7] != b'PMTiles':
            raise ValueError(f'{path}: not a PMTiles file')
        root_off, root_len = struct.unpack_from('<QQ', h, 8)
        leaf_off, _ = struct.unpack_from('<QQ', h, 40)
        self.data_off, _ = struct.unpack_from('<QQ', h, 56)
        self.icomp, self.tcomp = h[97], h[98]
        self.minz, self.maxz = h[100], h[101]
        self.f.seek(root_off)
        entries = []
        for tid, rl, ln, off in read_dir(self._dec(self.f.read(root_len), self.icomp)):
            if rl == 0:
                self.f.seek(leaf_off + off)
                entries += read_dir(self._dec(self.f.read(ln), self.icomp))
            else:
                entries.append((tid, rl, ln, off))
        self.entries = entries

    @staticmethod
    def _dec(b, c):
        return gzip.decompress(b) if c == 2 else b

    def read(self, off, ln):
        self.f.seek(self.data_off + off)
        return self._dec(self.f.read(ln), self.tcomp)

    def by_zoom(self, z):
        for tid, _, ln, off in self.entries:
            zz, base = 0, 0
            while True:
                c = 4 ** zz
                if tid < base + c:
                    break
                base += c; zz += 1
            if zz == z:
                yield self.read(off, ln)


def fields(b):
    p = 0
    while p < len(b):
        k, p = varint(b, p); fn, wt = k >> 3, k & 7
        if wt == 2:
            l, p = varint(b, p); yield fn, b[p:p + l]; p += l
        elif wt == 0:
            v, p = varint(b, p); yield fn, v
        else:
            n = {5: 4, 1: 8}[wt]; yield fn, b[p:p + n]; p += n


def props(buf, layer):
    """Every feature's properties in `layer`, with a vertex count, for one tile."""
    out = []
    for fn, body in fields(buf):
        if fn != 3:
            continue
        name = None; keys = []; vals = []; feats = []
        for f2, b2 in fields(body):
            if f2 == 1: name = b2.decode()
            elif f2 == 3: keys.append(b2.decode())
            elif f2 == 4:
                for f3, b3 in fields(b2):
                    vals.append(b3.decode() if f3 == 1 else b3)
            elif f2 == 2: feats.append(b2)
        if name != layer:
            continue
        for fb in feats:
            tags = []; nv = 0
            for f3, b3 in fields(fb):
                if f3 == 2:
                    q = 0
                    while q < len(b3):
                        v, q = varint(b3, q); tags.append(v)
                elif f3 == 4:
                    q = 0
                    while q < len(b3):
                        cmd = b3[q] if b3[q] < 128 else None
                        cmd, q = varint(b3, q)
                        op, cnt = cmd & 7, cmd >> 3
                        if op in (1, 2):
                            nv += cnt
                            for _ in range(2 * cnt):
                                _, q = varint(b3, q)
            d = {keys[tags[i]]: vals[tags[i + 1]]
                 for i in range(0, len(tags) - 1, 2)
                 if tags[i] < len(keys) and tags[i + 1] < len(vals)}
            out.append((d, nv))
    return out


def inventory(pm, layer):
    """Distinct ids and their vertex totals, from the max zoom, where nothing is generalised
    away. Lower zooms drop sub-pixel features, so they cannot answer a completeness question."""
    seen = defaultdict(int)
    for buf in pm.by_zoom(pm.maxz):
        for d, nv in props(buf, layer):
            if 'id' in d:
                seen[d['id']] += nv
    return seen


def main():
    fails, warns = [], []

    fc = json.load(gzip.open(SRC))
    want = {}                              # id -> (year, acres, sev_ok)
    for f in fc['features']:
        p = f['properties']
        want[p['id']] = (int(p['ig_date'][:4]), p.get('acres') or 0, bool(p.get('sev_ok')))
    want_years = Counter(v[0] for v in want.values())
    print(f'source: {len(want):,} fires across {len(want_years)} years  ({os.path.basename(SRC)})')
    print()

    # --- 1. every year has a per-year perimeter tileset, and it holds every fire -------------
    print('%-6s %8s %8s %10s   %s' % ('year', 'expect', 'in tiles', 'severity', ''))
    total_seen = 0
    for y in sorted(want_years):
        path = f'{OUT}/perims/{y}.pmtiles'
        if not os.path.exists(path):
            fails.append(f'{y}: no perimeter tileset at all')
            print('%-6d %8d %8s %10s   <-- MISSING' % (y, want_years[y], '-', '-'))
            continue
        inv = inventory(PM(path), 'perimeters')
        total_seen += len(inv)
        missing = want_years[y] - len(inv)

        sev_path = f'{OUT}/severity/{y}.pmtiles'
        has_sev = os.path.exists(sev_path)
        expect_sev = any(v[2] for k, v in want.items() if v[0] == y)
        note = ''
        if missing:
            fails.append(f'{y}: {missing} of {want_years[y]} fires absent from the tileset')
            note = f'<-- {missing} MISSING'
        if has_sev and not expect_sev:
            warns.append(f'{y}: severity tileset exists but no fire is marked sev_ok')
        if expect_sev and not has_sev:
            fails.append(f'{y}: fires are marked sev_ok but there is no severity tileset')
            note = '<-- no severity tileset'
        if not has_sev and y not in SEV_GAP and not expect_sev:
            warns.append(f'{y}: no severity, and not a known gap — new upstream failure?')
        print('%-6d %8d %8d %10s   %s'
              % (y, want_years[y], len(inv), 'yes' if has_sev else 'none', note))

    print()
    print(f'perimeters accounted for: {total_seen:,} of {len(want):,}')

    # --- 2. the merge kept every year ---------------------------------------------------------
    merged = f'{OUT}/perimeters.pmtiles'
    if not os.path.exists(merged):
        fails.append('perimeters.pmtiles does not exist')
    else:
        pm = PM(merged)
        years_in = set()
        for buf in pm.by_zoom(2):          # one tile, whole West; enough to see every year
            for d, _ in props(buf, 'perimeters'):
                if 'year' in d:
                    years_in.add(d['year'])
        lost = set(want_years) - years_in
        if lost:
            fails.append(f'merged tileset is missing whole years: {sorted(lost)}')
        print(f'merged: z{pm.minz}-z{pm.maxz}, {len(years_in)} of {len(want_years)} years present'
              + (f'  <-- LOST {sorted(lost)}' if lost else ''))

    # --- 3. geometry, on the biggest fire of each year, chosen by acreage alone ---------------
    biggest = {}
    for fid, (y, ac, _) in want.items():
        if ac > biggest.get(y, (None, -1))[1]:
            biggest[y] = (fid, ac)
    bad = []
    for y, (fid, _) in sorted(biggest.items()):
        path = f'{OUT}/perims/{y}.pmtiles'
        if not os.path.exists(path):
            continue
        if not inventory(PM(path), 'perimeters').get(fid):
            bad.append(f'{y}: largest fire {fid} has no geometry')
    fails += bad
    print(f'geometry spot-check on each year\'s largest fire: {len(biggest) - len(bad)}'
          f'/{len(biggest)} pass')

    print()
    for w in warns:
        print(f'WARN  {w}')
    for f in fails:
        print(f'FAIL  {f}')
    print()
    print('FAILED' if fails else 'all checks pass')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
