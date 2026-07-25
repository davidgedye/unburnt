#!/usr/bin/env python3
"""Dev server for the fire visualization.

Plain `python3 -m http.server` lets the browser cache index.html, which makes it easy to test
stale code without realizing it. This sends no-store on everything so a normal reload always
picks up the latest build (cross-check the `build N` stamp shown in the app's title panel).

Usage: python3 serve.py [port]     (default 8090)
"""
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def log_message(self, fmt, *args):        # quieter: skip 200s, show problems
        if not str(args[1] if len(args) > 1 else '').startswith('2'):
            super().log_message(fmt, *args)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8090
    print(f'serving {__file__.rsplit("/", 1)[0]} on http://localhost:{port}/index.html (no-cache)')
    ThreadingHTTPServer(('', port), NoCacheHandler).serve_forever()
