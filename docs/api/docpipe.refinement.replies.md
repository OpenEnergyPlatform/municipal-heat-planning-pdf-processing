# docpipe.refinement.replies

`docpipe/refinement/replies.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

replies.py: The reply each refinement request asks for, as a JSON schema.

For an API that generates inside a schema (see `docpipe.providers`). The
prompts state the same shapes in words; nothing here is a check.

The corrections reply is small and fixed. The full reply hands every section
back, with the keys the request carried, so its schema is built from the
window that is sent: what a section or one of its tables carried under a key
decides what may come back under it.

Author: Felix Vossel

## Functions

### window

```python
def window(sections: list) -> dict
```

The full reply to one window: its sections, handed back.

[Back to the index](../README.md)
