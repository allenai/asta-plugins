#!/usr/bin/env python3
"""Capture Claude Code's first model request on loopback without credentials."""

import argparse
import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

PROMPT = "Check the installed Asta skill listing."
STOP_RESPONSE = b'{"type":"error","error":{"type":"invalid_request_error","message":"Local prompt capture complete"}}'


def is_probe(message: dict) -> bool:
    if message.get("role") != "user":
        return False
    content = message.get("content")
    if isinstance(content, list):
        return any(
            block.get("type") == "text" and block.get("text") == PROMPT
            for block in content
        )
    return content == PROMPT


def capture(home: Path) -> bytes:
    request = None

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            nonlocal request
            if urlsplit(self.path).path != "/v1/messages":
                self.send_error(404)
                return

            body = self.rfile.read(int(self.headers["Content-Length"]))
            payload = json.loads(body)
            if request is None and any(
                is_probe(message) for message in payload["messages"]
            ):
                request = body
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(STOP_RESPONSE)

        def log_message(self, *_args):
            pass

    with HTTPServer(("127.0.0.1", 0), Handler) as server:
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--model",
                    "sonnet",
                    "--setting-sources",
                    "user",
                    "--settings",
                    '{"disableAllHooks":true}',
                    "--",
                    PROMPT,
                ],
                cwd=home,
                env={
                    "PATH": os.environ["PATH"],
                    "HOME": str(home),
                    "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                    "ANTHROPIC_API_KEY": "local-test-placeholder",
                    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                },
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            server.shutdown()
            worker.join()

    if request is None:
        raise ValueError(
            f"Claude Code sent no model request (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("home", type=Path)
    args = parser.parse_args()
    try:
        sys.stdout.buffer.write(capture(args.home.resolve()))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"  ✗ {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
