#!/usr/bin/env python3
"""Capture Claude Code's main model request on loopback without credentials."""

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


def is_main_request(payload: dict) -> bool:
    model = payload.get("model", "")
    # Auxiliary calls can echo the probe. The interactive turn carries the Sonnet
    # model and its normal tools, even when the skill list is missing.
    return (
        model.startswith("claude-sonnet-")
        and any(tool.get("name") == "Read" for tool in payload.get("tools", []))
        and any(is_probe(message) for message in payload.get("messages", []))
    )


def local_reply(payload: dict) -> tuple[str, bytes]:
    """End each mock turn without asking Claude Code to execute any tools."""
    content = {"type": "text", "text": "OK"}
    stop = {"stop_reason": "end_turn", "stop_sequence": None}
    usage = {"input_tokens": 1, "output_tokens": 1}
    message = {
        "type": "message",
        "id": "msg_local_capture",
        "role": "assistant",
        "model": payload["model"],
        "content": [content],
        "usage": usage,
        **stop,
    }
    if not payload.get("stream"):
        return "application/json", json.dumps(message).encode()

    events = [
        {
            "type": "message_start",
            "message": {**message, "content": [], "stop_reason": None},
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": content["text"]},
        },
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": stop, "usage": {"output_tokens": 1}},
        {"type": "message_stop"},
    ]
    return "text/event-stream", "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()


def capture(home: Path) -> bytes:
    request = None

    class Handler(BaseHTTPRequestHandler):
        timeout = 5

        def do_POST(self):
            nonlocal request
            if urlsplit(self.path).path != "/v1/messages":
                self.send_error(404)
                return

            length = self.headers.get("Content-Length")
            if length is None:
                self.request_error(411, "Content-Length is required")
                return
            if not length.isascii() or not length.isdecimal():
                self.request_error(400, "Invalid Content-Length")
                return
            try:
                body_length = int(length)
                body = self.rfile.read(body_length)
            except (OverflowError, ValueError):
                self.request_error(400, "Invalid Content-Length")
                return
            except TimeoutError:
                self.request_error(408, "Timed out reading Messages request")
                return
            if len(body) != body_length:
                self.request_error(400, "Incomplete Messages request")
                return

            try:
                payload = json.loads(body)
                if not isinstance(payload, dict) or not isinstance(
                    payload.get("model"), str
                ):
                    raise ValueError
            except ValueError:
                self.request_error(400, "Invalid Messages request")
                return
            if request is None and is_main_request(payload):
                request = body
            content_type, reply = local_reply(payload)
            self.reply(200, content_type, reply)

        def request_error(self, status: int, message: str):
            error = {"type": "invalid_request_error", "message": message}
            self.reply(
                status,
                "application/json",
                json.dumps({"type": "error", "error": error}).encode(),
            )

        def reply(self, status: int, content_type: str, body: bytes):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

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
                    "DISABLE_AUTOUPDATER": "1",
                },
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            server.shutdown()
            worker.join()

    if result.returncode:
        raise ValueError(
            f"Claude Code failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    if request is None:
        raise ValueError(
            "Claude Code sent no Sonnet model request with the probe and tools"
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
