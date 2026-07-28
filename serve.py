#!/usr/bin/env python3
"""Dev server for the fire visualization (serves ./app).

Plain `python3 -m http.server` lets the browser cache index.html, which makes it easy to test
stale code without realizing it. This sends no-store on everything so a normal reload always
picks up the latest build (cross-check the `build N` stamp shown in the app's title panel).

Lives at the repo root, not inside app/, so that app/ contains only files fit to publish —
the whole directory is uploaded verbatim as Cloudflare Workers static assets.

**Range requests.** MapLibre's `pmtiles://` protocol reads a tileset by asking for byte ranges,
the same way it will read from R2. `SimpleHTTPRequestHandler` ignores a `Range` header and
answers 200 with the whole file, which the protocol cannot use — and because it is a perfectly
valid-looking 200, the failure surfaces as an unreadable tileset rather than as an HTTP error.
So ranges are handled here, and `/tiles/...` is mapped to the local tileset directory, which
lives outside `app/` precisely because a 1.2 GB tileset is never going to ship as a static
asset (it is far past the 25 MiB per-file cap; production reads it from R2).

Usage: python3 serve.py [port]     (default 8090)
       http://localhost:8090/index.html          the app
       http://localhost:8090/tiles/west.pmtiles  the local tileset, for testing before upload
"""
import os
import re
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Dev-only alias. Nothing under here is part of the deploy — app/ stays exactly what Cloudflare
# uploads, and this just lets the browser reach a tileset sitting elsewhere in the repo.
TILE_PREFIX = '/tiles/'
TILE_ROOT = os.path.abspath('pipeline/data/pmtiles')


class DevHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory='app', **kw)

    def translate_path(self, path):
        clean = urllib.parse.unquote(urllib.parse.urlparse(path).path)
        if clean.startswith(TILE_PREFIX):
            full = os.path.normpath(os.path.join(TILE_ROOT, clean[len(TILE_PREFIX):].lstrip('/')))
            # normpath first, then check: without this, /tiles/../../etc/passwd escapes the root.
            return full if full.startswith(TILE_ROOT + os.sep) else ''
        return super().translate_path(path)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    def do_GET(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().do_GET()

        # One range only. Multipart/byteranges is legal HTTP and nothing here asks for it.
        m = re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip())
        if not m or not (m.group(1) or m.group(2)):
            return super().do_GET()                  # not a form we handle; serve it whole

        size = os.path.getsize(path)
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:
            start, end = max(0, size - int(m.group(2))), size - 1   # bytes=-N, the last N bytes

        if start >= size:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.end_headers()
            return
        end = min(end, size - 1)

        with open(path, 'rb') as f:
            f.seek(start)
            body = f.read(end - start + 1)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):        # quieter: skip 200s and 206s, show problems
        if not str(args[1] if len(args) > 1 else '').startswith('2'):
            super().log_message(fmt, *args)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f'serving ./app on http://localhost:{port}/index.html (no-cache)')
    if os.path.isdir(TILE_ROOT):
        n = len([f for f in os.listdir(TILE_ROOT) if f.endswith('.pmtiles')])
        print(f'  ...and {n} tileset(s) from {TILE_ROOT} at {TILE_PREFIX} (byte ranges supported)')
    ThreadingHTTPServer(('', port), DevHandler).serve_forever()
