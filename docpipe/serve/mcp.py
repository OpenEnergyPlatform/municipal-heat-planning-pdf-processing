"""
mcp.py: The value store as a Model Context Protocol server.

An assistant that speaks MCP is given the four questions of `tools.py` as
tools and gets the same answers the HTTP API gives. The server talks over
standard input and output, one JSON-RPC message per line, which is how an
assistant starts a tool on the machine it runs on:

    {"command": "docpipe", "args": ["serve", "HARVEST_DIR", "--mcp"]}

Only what a tool server needs is spoken: `initialize`, `ping`,
`tools/list` and `tools/call`. No message is written to standard output
that is not an answer; the log goes to standard error.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import sys
from typing import IO, Optional

from .. import __version__
from . import tools
from .values import Values

log = logging.getLogger(__name__)

# Newest first. A client that asks for one of these gets it; one that asks
# for another gets the newest, and decides for itself whether to go on.
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR, INVALID_REQUEST = -32700, -32600
METHOD_NOT_FOUND, INVALID_PARAMS = -32601, -32602

INSTRUCTIONS = (
    "Values read from a corpus of documents, each with the quote it stands "
    "in, its page and a trust level. Call list_parameters first: it shows "
    "what can be asked for. Quote the document and the page with every "
    "value you pass on, and say so when a value is of level C.")


def _result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id,
            "error": {"code": code, "message": message}}


def respond(store: Values, message) -> Optional[dict]:
    """The answer to one message, or None where none is due."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" \
            or not isinstance(message.get("method"), str):
        request_id = message.get("id") if isinstance(message, dict) else None
        return _error(request_id, INVALID_REQUEST,
                      "not a JSON-RPC 2.0 request")
    method = message["method"]
    params = message.get("params") or {}
    if "id" not in message:
        return None                     # a notification is not answered
    request_id = message["id"]
    if not isinstance(params, dict):
        return _error(request_id, INVALID_PARAMS, "params must be an object")

    if method == "initialize":
        asked = params.get("protocolVersion")
        return _result(request_id, {
            "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "docpipe", "version": __version__},
            "instructions": INSTRUCTIONS})
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [
            {"name": name, **described}
            for name, described in tools.DESCRIPTIONS.items()]})
    if method == "tools/call":
        name = params.get("name")
        if name not in tools.DESCRIPTIONS:
            return _error(request_id, INVALID_PARAMS,
                          f"unknown tool: {name!r}")
        # What a tool cannot answer is an answer the assistant can read
        # and act on, not a failure of the protocol.
        try:
            found = tools.call(store, name, params.get("arguments"))
        except tools.BadRequest as exc:
            return _result(request_id, {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True})
        except KeyError as exc:
            return _result(request_id, {
                "content": [{"type": "text",
                             "text": f"no value {exc.args[0]!r}"}],
                "isError": True})
        return _result(request_id, {
            "content": [{"type": "text",
                         "text": json.dumps(found, ensure_ascii=False)}],
            "structuredContent": found, "isError": False})
    return _error(request_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def _utf8(stream: IO) -> IO:
    """A standard stream read and written as UTF-8, which is what the
    protocol says, and not in the code page of the terminal."""
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")
    return stream


def serve(store: Values, source: Optional[IO] = None,
          sink: Optional[IO] = None) -> int:
    """Answer messages line by line until the input ends."""
    source = source if source is not None else _utf8(sys.stdin)
    sink = sink if sink is not None else _utf8(sys.stdout)
    for line in source:
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except ValueError:
            answer = _error(None, PARSE_ERROR, "not JSON")
        else:
            try:
                answer = respond(store, message)
            except Exception:           # the server outlives one bad call
                log.exception("mcp: a request failed")
                request_id = message.get("id") \
                    if isinstance(message, dict) else None
                answer = _error(request_id, -32603, "internal error")
        if answer is not None:
            sink.write(json.dumps(answer, ensure_ascii=False) + "\n")
            sink.flush()
    return 0
