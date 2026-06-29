#!/usr/bin/env python3
"""Serve The Extraction Range over http so storage/fetch/header specimens work.
    python3 serve.py    then open  http://localhost:8000/index.html
"""
import http.server
import json
import os
from http.server import ThreadingHTTPServer

PORT = 8000
ROOT = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(ROOT, "manifest.json")) as f:
    M = {s["slug"]: s for s in json.load(f)["specimens"]}
HEADER_FLAG = M.get("http-header", {}).get("flag", "")


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=ROOT, **k)

    def end_headers(self):
        if self.path.split("?")[0].endswith("/pages/http-header.html"):
            self.send_header("X-Access-Token", HEADER_FLAG)
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    # Clients (the Docker healthcheck, browsers that cancel a request) often drop
    # the connection mid-response. That is harmless here, so swallow the noise
    # instead of dumping a traceback for every disconnect.
    def copyfile(self, source, outputfile):
        try:
            super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


if __name__ == "__main__":
    # ThreadingHTTPServer => one slow/aborted request can't block the others.
    httpd = ThreadingHTTPServer(("", PORT), H)
    httpd.daemon_threads = True
    print("Serving The Extraction Range at http://localhost:%d/index.html" % PORT)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping.")
