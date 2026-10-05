# docpipe.inference.replies

`docpipe/inference/replies.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

replies.py: The reply each chat request asks for, as a JSON schema.

For an API that generates inside a schema (see `docpipe.providers`). The
prompts state the same shapes in words; nothing here is a check.

One request has no schema: the answer reformatted into a JSON shape the user
wrote into the task. That shape is the user's and only exists as prose.

Author: Felix Vossel

## Functions

### answer

```python
def answer(actions: bool = True) -> tuple
```

The answer envelope, and with *actions* the two things the model may
ask for instead: a calculation, or a crop it was only pointed at.

[Back to the index](../README.md)
