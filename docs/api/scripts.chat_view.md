# scripts.chat_view

`scripts/chat_view.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

Show every model request of an extraction trace as a small chat, in one HTML page.

usage: python scripts/chat_view.py TRACE OUT.html [--kind K ...] [--field F ...]
                                   [--owner N ...] [--value V ...]
                                   [--contains TEXT ...] [--limit N]

TRACE is a *.jsonl or *.jsonl.gz file; one still being written is read up to
where it ends. Each request shows its instruction (folded), its message with
the numbered lines, the addresses its answer names highlighted, the answer,
and what became of it (taken, asked again with reasons, no answer,
unreadable). The chain of one value (find, readings, follow-ups, list
entries) is a second view.

## Functions

### requests_of

```python
def requests_of(events: list) -> list
```

One dict per `*_ask` event, in trace order.

### chain_of

```python
def chain_of(requests: list, index: int) -> list
```

Indexes of the requests of one value: the find of its parameter and
passage, the readings and follow-ups, and the list entries asked for its words.

### render

```python
def render(requests: list) -> str
```

### main

```python
def main(argv=None) -> None
```

[Back to the index](../README.md)
