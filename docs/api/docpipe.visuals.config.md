# docpipe.visuals.config

`docpipe/visuals/config.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

config.py – Central configuration for the imageprocessing module.

Author: Felix Vossel

## Functions

### dump_json_atomic

```python
def dump_json_atomic(data, path) -> None
```

Serialise *data* as UTF-8 JSON to *path* atomically (temp file +
os.replace). Atomic only within one filesystem.

### max_request_tokens

```python
def max_request_tokens() -> int
```

Worst case for one vision request: the longer of the two system
prompts + one page image + the reply we ask for.

[Back to the index](../README.md)
