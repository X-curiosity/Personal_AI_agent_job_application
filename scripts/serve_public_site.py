#!/usr/bin/env python3
"""Local-only static preview with the same security headers as Vercel."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import argparse

ROOT = Path(__file__).resolve().parents[1] / "vercel-site"

class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        for rule in json.loads((ROOT / "vercel.json").read_text())["headers"]:
            for header in rule["headers"]:
                self.send_header(header["key"], header["value"])
        super().end_headers()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=str(ROOT))).serve_forever()
