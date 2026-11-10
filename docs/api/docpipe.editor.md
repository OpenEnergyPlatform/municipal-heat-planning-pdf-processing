# docpipe.editor

`docpipe/editor/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

docpipe.editor: `docpipe edit`, a profile's extraction spec in the browser.

Author: Felix Vossel

## Functions

### main

```python
def main(rest: Sequence[str]) -> int
```

`docpipe edit`. The server is imported here and not above, so the
logic in `specs` can be used without it.

[Back to the index](../README.md)
