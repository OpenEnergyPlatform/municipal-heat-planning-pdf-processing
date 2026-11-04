# docpipe.extraction.lookup

`docpipe/extraction/lookup.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

lookup.py: What the model may ask of the rest of one document, resolved by
code. Pure functions over the document's passages in reading order, no model
call and no judgement of a value.

The model names what it wants (the next section, a table by its placeholder,
a pattern); these functions find it or say why they cannot. A name that fits
nothing, or fits two passages, is None, never a guess.

Author: Felix Vossel

## Classes

### Matches

```python
@dataclass
class Matches
```

`hits` are the passages that fit in `room`, `total` how many passages
matched at all (so the caller can say the list is cut). `fault` is None,
"invalid_pattern" or "timeout"; `detail` is the reason to pass back.

Fields:

- `hits: list[dict]`
- `total: int = 0`
- `fault: Optional[str] = None`
- `detail: str = ""`

## Functions

### following

```python
def following(passages: list[Source], owner: tuple[str, int],
              step: int = 1) -> Optional[Source]
```

The `step`-th section after `owner` in reading order (before it for a
negative step), tables and figures skipped. A table or figure counts from
its own position. None past either end, for step 0, and when `owner` is
not in `passages`.

### item

```python
def item(passages: list[Source], block_id: str) -> Optional[Source]
```

The table or figure whose placeholder is `block_id`, in any form the
text prints it. None when no passage carries it and when two do: a block
id is unique within a document only by convention.

### title_of

```python
def title_of(p: Source) -> str
```

### matching

```python
def matching(passages: list[Source], pattern: str, room: int) -> Matches
```

The passages whose text matches `pattern` (case-insensitive), each as
{"owner": [kind, id], "title", "line"}, in reading order, as many as fit
in `room` characters of JSON; `total` counts every matching passage. An
invalid pattern and a pattern that times out come back as `fault` with
no hits, never as an exception.

[Back to the index](../README.md)
