# scripts.inference_app_smoketest

`scripts/inference_app_smoketest.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

inference_app_smoketest.py – Check that the configured embedding backend
produces usable vectors. Run it on the machine that will serve the app.

    python scripts/inference_app_smoketest.py [--image /path/to/a/table_or_figure.png]
    EMBEDDING_BACKEND=api python scripts/inference_app_smoketest.py

What it asserts is what docpipe.embedding promises and the corpus depends on:
the right dimension, L2-normalized vectors, image and image+text queries that
go through, and a batch that agrees with the same items embedded singly. How
the backend gets there — quantized, resident, over HTTP — is none of this
test's business; whether a particular one gives its VRAM back is checked next
to that implementation.

Exit code 0 = all checks passed; non-zero = a check failed (see printed VERDICT).

Author: Felix Vossel

## Functions

### main

```python
def main() -> int
```

[Back to the index](../README.md)
