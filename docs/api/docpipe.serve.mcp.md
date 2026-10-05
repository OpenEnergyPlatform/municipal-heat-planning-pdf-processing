# docpipe.serve.mcp

`docpipe/serve/mcp.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

mcp.py: The value store as a Model Context Protocol server.

An assistant that speaks MCP is given the eight questions of `tools.py` as
tools and gets the same answers the HTTP API gives. The server talks over
standard input and output, one JSON-RPC message per line, which is how an
assistant starts a tool on the machine it runs on:

    {"command": "docpipe", "args": ["serve", "HARVEST_DIR", "--mcp"]}

Only what a tool server needs is spoken: `initialize`, `ping`,
`tools/list` and `tools/call`. No message is written to standard output
that is not an answer; the log goes to standard error.

Author: Felix Vossel

## Functions

### respond

```python
def respond(store: Values, message) -> Optional[dict]
```

The answer to one message, or None where none is due.

### serve

```python
def serve(store: Values, source: Optional[IO] = None,
          sink: Optional[IO] = None) -> int
```

Answer messages line by line until the input ends.

[Back to the index](../README.md)
