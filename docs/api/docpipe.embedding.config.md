# docpipe.embedding.config

`docpipe/embedding/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Where embeddings come from.

EMBEDDING_BACKEND picks one:

  local                 the model runs in this process and stays resident
                        (needs GPUs; this is what a batch run wants)
  api                   an OpenAI-compatible /v1/embeddings endpoint
  package.module:Klasse an implementation supplied by the deployment

The model name and the length/batch limits below are shared: an external
backend is free to read them, and should, so that one deployment does not
silently embed at a different length than the corpus was built with.

Author: Felix Vossel

[Back to the index](../README.md)
