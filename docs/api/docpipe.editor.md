# docpipe.editor

`docpipe/editor/__init__.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

docpipe.editor: `docpipe edit`, a profile's extraction spec, prompts,
sentences and the numbers of its flow in the browser.

Author: Felix Vossel

## Functions

### main

```python
def main(rest: Sequence[str]) -> int
```

`docpipe edit` (start.py). The server is imported only by the process
that serves, so the logic beside it can be used without it, and the
command that starts the server again after a switch of the profile
holds no profile of its own.

[Back to the index](../README.md)
