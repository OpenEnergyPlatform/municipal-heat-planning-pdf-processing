# docpipe.serve

`docpipe/serve/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

serve: The harvested values, handed on.

`values.py` reads a harvest once; everything else here answers from that
reading: a table (`export.py`), an HTTP API (`http.py`) and an MCP server
(`mcp.py`). The chat asks the same store (docpipe/inference/values_route.py).

Author: Felix Vossel

[Back to the index](../README.md)
