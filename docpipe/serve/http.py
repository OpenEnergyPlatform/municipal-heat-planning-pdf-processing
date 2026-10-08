"""
http.py: The value store over HTTP, read only.

    GET /                 what this server answers
    GET /documents        the documents with values
    GET /parameters       the parameters, their units and coordinates
    GET /values           the values that match the query
                          ?document= &parameter= &level= &text=
                          &limit= &offset= &coordinate.<name>=<value>
    GET /values/<id>      one value with everything that backs it
    GET /states           what the harvest says of a parameter in a document
                          (unstated, exhausted, ... never asked)
                          ?document= &parameter= &state= &limit= &offset=
    GET /coverage         documents by parameters, each cell its state
                          ?document= &parameter= &limit= &offset=
    GET /refusals         the claims that were refused, and why
                          ?document= &parameter= &limit= &offset=
    GET /search           passages by word: ?text= &document= &limit=
                          (503 with the reason where there is no corpus
                          database or word index)

Answers are JSON. Nothing can be written through it. A document or a
parameter the harvest does not have is a 404, not an empty answer.

It listens on this machine only unless told otherwise, and it does not
listen anywhere else without a token: with DOCPIPE_API_TOKEN set every
request has to carry `Authorization: Bearer <token>`. The standard
library's server is used as it is: fine behind a reverse proxy or for a
group, not something to put on the open internet by itself.

Author: Felix Vossel
"""
from __future__ import annotations

import hmac
import json
import logging
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlsplit

from .. import __version__
from . import tools
from .values import Values

log = logging.getLogger(__name__)

TOKEN_ENV = "DOCPIPE_API_TOKEN"
LOCAL = ("127.0.0.1", "localhost", "::1")
DEFAULT_PORT = 8750
COORDINATE = "coordinate."
# The questions that are asked by their query string alone.
ROUTES = {"states": tools.get_states, "coverage": tools.get_coverage,
          "refusals": tools.find_refusals, "search": tools.search}


def token() -> Optional[str]:
    return (os.environ.get(TOKEN_ENV) or "").strip() or None


def arguments_of(query: str) -> dict:
    """The query string as the arguments of `find_values`."""
    arguments: dict = {}
    coordinates: dict = {}
    for name, content in parse_qsl(query, keep_blank_values=False):
        if name.startswith(COORDINATE) and len(name) > len(COORDINATE):
            if name[len(COORDINATE):] in coordinates:
                raise tools.BadRequest(f"{name} is given twice")
            coordinates[name[len(COORDINATE):]] = content
        elif name in arguments:
            raise tools.BadRequest(f"{name} is given twice")
        else:
            arguments[name] = content
    if coordinates:
        arguments["coordinates"] = coordinates
    return arguments


def answer(store: Values, path: str, query: str = "") -> tuple:
    """(status, body) for one GET."""
    parts = [unquote(part) for part in path.split("/") if part]
    try:
        if not parts:
            return 200, {
                "name": "docpipe", "version": __version__,
                "values": len(store), "documents": len(store.harvested),
                "unreadable_lines": store.unreadable,
                "endpoints": {
                    "/documents": tools.DESCRIPTIONS[
                        "list_documents"]["description"],
                    "/parameters": tools.DESCRIPTIONS[
                        "list_parameters"]["description"],
                    "/values": tools.DESCRIPTIONS[
                        "find_values"]["description"],
                    "/values/<id>": tools.DESCRIPTIONS[
                        "get_value"]["description"],
                    "/states": tools.DESCRIPTIONS[
                        "get_states"]["description"],
                    "/coverage": tools.DESCRIPTIONS[
                        "get_coverage"]["description"],
                    "/refusals": tools.DESCRIPTIONS[
                        "find_refusals"]["description"],
                    "/search": tools.described(store)[
                        "search"]["description"]}}
        if parts == ["documents"]:
            return 200, tools.list_documents(store)
        if parts == ["parameters"]:
            return 200, tools.list_parameters(store)
        if parts == ["values"]:
            return 200, tools.find_values(store, arguments_of(query))
        if len(parts) == 2 and parts[0] == "values":
            return 200, tools.get_value(store, parts[1])
        for route, ask in ROUTES.items():
            if parts == [route]:
                return 200, ask(store, arguments_of(query))
    except tools.BadRequest as exc:
        return 400, {"error": str(exc)}
    except tools.NotFound as exc:
        return 404, {"error": str(exc)}
    except tools.Unavailable as exc:
        return 503, {"error": str(exc)}
    except KeyError:
        return 404, {"error": f"no value {parts[-1]!r}"}
    return 404, {"error": f"no such path: {path}"}


def handler(store: Values, secret: Optional[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"docpipe/{__version__}"

        def _send(self, status: int, body: dict, head: bool = False) -> None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type",
                             "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            if status == 401:
                self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            if not head:
                self.wfile.write(data)

        def _allowed(self) -> bool:
            if secret is None:
                return True
            # The scheme in any case. The token as the bytes that were
            # sent: a header is read as Latin-1, and a token that is not
            # ASCII arrives as its UTF-8 bytes.
            scheme, _, sent = (self.headers.get("Authorization")
                               or "").partition(" ")
            return scheme.lower() == "bearer" and hmac.compare_digest(
                sent.strip().encode("latin-1", "replace"),
                secret.encode("utf-8"))

        def _get(self, head: bool) -> None:
            if not self._allowed():
                self._send(401, {"error": "a bearer token is required"},
                           head)
                return
            split = urlsplit(self.path)
            status, body = answer(store, split.path, split.query)
            self._send(status, body, head)

        def do_GET(self) -> None:            # noqa: N802 (the base's name)
            self._get(False)

        def do_HEAD(self) -> None:           # noqa: N802
            self._get(True)

        def _refuse(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "GET, HEAD")
            self.send_header("Content-Length", "0")
            self.end_headers()

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuse   # noqa: N815

        def log_message(self, format, *args) -> None:   # noqa: A002
            log.info("%s %s", self.address_string(), format % args)

    return Handler


def make_server(store: Values, host: str = "127.0.0.1",
                port: int = DEFAULT_PORT) -> ThreadingHTTPServer:
    secret = token()
    if host not in LOCAL and secret is None:
        raise SystemExit(
            f"--host {host} makes the values reachable from other "
            f"machines, and {TOKEN_ENV} is not set. Set a token (every "
            f"request then carries it as `Authorization: Bearer ...`), or "
            f"stay on 127.0.0.1.")
    class Server(ThreadingHTTPServer):
        address_family = socket.AF_INET6 if ":" in host else socket.AF_INET

    return Server((host, port), handler(store, secret))


def serve(store: Values, host: str = "127.0.0.1",
          port: int = DEFAULT_PORT) -> int:
    server = make_server(store, host, port)
    log.info("serving %d value(s) on http://%s:%d/%s", len(store), host,
             server.server_address[1],
             " (token required)" if token() else "")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
