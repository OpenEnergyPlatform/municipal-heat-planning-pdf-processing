# docpipe.inference.config

`docpipe/inference/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Inference settings the core needs: the LLM endpoint, the retrieval
budget and the scopes.

Nothing here is domain knowledge, and nothing names a particular deployment:
the LLM is whatever OpenAI-compatible endpoint LLM_BASE_URL points at — a local
vLLM server, an institutional gateway or a hosted API.

Author: Felix Vossel

[Back to the index](../README.md)
