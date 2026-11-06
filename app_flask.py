"""Retired legacy teaching proxy. No Google, OpenAI or Qdrant clients."""
import json
import os
from wsgiref.simple_server import make_server

NOTICE = {
    "status": "retired",
    "retired_on": "2026-11-06",
    "message": "This legacy teaching proxy is retired. Use My Teaching Plugin with native Google connections.",
}


def app(environ, start_response):
    # A liveness response lets hosting complete a deployment of the retirement
    # notice. It does not indicate document access or an active teaching API.
    health = environ.get("PATH_INFO") == "/health" and environ.get("REQUEST_METHOD") in ("GET", "HEAD")
    status = "200 OK" if health else "410 Gone"
    body = json.dumps(NOTICE).encode("utf-8")
    start_response(status, [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ])
    return [b"" if environ.get("REQUEST_METHOD") == "HEAD" else body]


def run():
    with make_server("0.0.0.0", int(os.environ.get("PORT", "5000")), app) as server:
        server.serve_forever()


if __name__ == "__main__":
    run()
