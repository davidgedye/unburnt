#!/usr/bin/env python3
"""Static server with HTTP Range support, so MapLibre's pmtiles:// protocol can read a single
.pmtiles file the way it would from R2 — byte ranges, no tile server. Python's stock
SimpleHTTPRequestHandler answers 200 to a Range request, which the protocol cannot use."""
import os, re, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = sys.argv[2] if len(sys.argv) > 2 else '.'

class RangeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw): super().__init__(*a, directory=ROOT, **kw)
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()
    def do_GET(self):
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().do_GET()
        m = re.match(r'bytes=(\d+)-(\d*)', rng)
        if not m: return super().do_GET()
        size = os.path.getsize(path)
        start = int(m.group(1)); end = int(m.group(2)) if m.group(2) else size - 1
        end = min(end, size - 1)
        with open(path, 'rb') as f:
            f.seek(start); body = f.read(end - start + 1)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass

ThreadingHTTPServer(('', int(sys.argv[1])), RangeHandler).serve_forever()
