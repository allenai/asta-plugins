"""Isolated local site server for browser checks only."""

import os
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


def _serve(root):
    root = os.path.realpath(root)

    class Quiet(SimpleHTTPRequestHandler):
        def send_head(self):
            target = os.path.realpath(self.translate_path(self.path))
            if os.path.commonpath([root, target]) != root:
                self.send_error(403, "Path outside site")
                return None
            return super().send_head()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=root))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
