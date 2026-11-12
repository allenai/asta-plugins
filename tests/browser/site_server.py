"""Isolated local site server for browser checks only."""

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

FONT_SUFFIXES = (".woff2", ".woff", ".ttf", ".otf")


def _serve(root):
    root = os.path.realpath(root)

    class Quiet(SimpleHTTPRequestHandler):
        serves_font = False
        response_code = 0

        def send_head(self):
            self.serves_font = False
            target = os.path.realpath(self.translate_path(self.path))
            if os.path.commonpath([root, target]) != root:
                self.send_error(403, "Path outside site")
                return None
            # Decided from the file actually served, symlinks resolved, as
            # `asta workspace preview` does.
            self.serves_font = os.path.isfile(target) and target.lower().endswith(
                FONT_SUFFIXES
            )
            return super().send_head()

        def send_response(self, code, message=None):
            self.response_code = code
            super().send_response(code, message)

        def end_headers(self):
            # Sandboxed slide frames (Origin: null) fetch font files in CORS mode.
            # Allow that for a successful font-file response only.
            if self.serves_font and self.response_code in (200, 304):
                self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=root))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
