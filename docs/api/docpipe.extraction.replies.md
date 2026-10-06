# docpipe.extraction.replies

`docpipe/extraction/replies.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

replies.py: The reply each extraction request asks for, as a JSON schema.

The prompts state these shapes in words. Here they are once more as schemas,
for an API that generates inside one: a hosted model is asked for JSON in no
other way, and a server of one's own can be (LLM_SCHEMA=all). The field
request has had its schema since the grammar was introduced for it
(`runner.field_response_format`); these are the other five.

Nothing here is a check. A schema says which keys a reply can have and what
kind of thing stands under each, as the prompt does. Every key the prompt
leaves optional is optional, a closed list is not turned into an enum, and
what a reply says is verified afterwards exactly as before.

Author: Felix Vossel

## Functions

### anchors

```python
def anchors() -> dict
```

### phrase

```python
def phrase() -> dict
```

### frame

```python
def frame(slots) -> dict
```

One pair per row of the frame: each coordinate with its wording, its
quote and the passage the quote is from.

### review

```python
def review(slots) -> dict
```

The fields of one stored value, read again: each under its own name
with its wording and its quote; the value also with its unit.

### rows

```python
def rows(*, sandbox: bool = True) -> dict
```

The harvest reply: the values of the passages, or a sandbox action.

A row is a value with its wording, its unit's wording and its quote; the
coordinates are asked per field afterwards.

[Back to the index](../README.md)
