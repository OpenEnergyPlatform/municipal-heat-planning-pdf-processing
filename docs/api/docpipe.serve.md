# docpipe.serve

`docpipe/serve/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

serve: The harvested values, handed on.

`values.py` reads a harvest once: its values, what it says of the parameters
that have none (their states) and its refusals. Everything else here answers
from that reading: a table (`export.py`), an HTTP API (`http.py`) and an MCP
server (`mcp.py`), over the questions `tools.py` describes once. The chat
asks the same store (docpipe/inference/values_route.py). `passages.py` is
the one part that reads something else, the corpus database and its word
index, for the passage search.

Author: Felix Vossel

[Back to the index](../README.md)
