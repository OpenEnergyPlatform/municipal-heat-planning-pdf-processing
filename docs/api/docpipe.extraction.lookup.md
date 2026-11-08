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

### sections_up_to

```python
def sections_up_to(passages: list[Source], owner: tuple[str, int],
                   count: int) -> list[Source]
```

The last `count` sections in reading order up to `owner`, its own
included where it is a section, the earliest first; a table or figure
counts from its own position, so its own section is the last. [] when
`owner` is not in `passages`.

### page_of

```python
def page_of(passage: Source) -> Optional[int]
```

The page a passage starts on, None where it names none.

### head_of

```python
def head_of(text: str) -> str
```

A transcribed table's title and head: its lines down to the rule that
closes the head, the rule included; "" where it has no head.

### continued

```python
def continued(passages: list[Source]) -> list[Source]
```

*passages*, a document's in reading order, each table that may
continue the table right before it marked with that table's title and
head (provenance "table_before": {"owner", "text"}). Owner decisions
2026-11-06 and 2026-11-07: a table the layout cut in parts, at a page
break or within a page, loses its title, head and unit in its later
parts, and whether it is the same table is the model's reading. A table
may continue the table right before it when that table stands on its
page or the page before and has a transcribed head; what stands between
them, a heading included, does not part them. The transcription asks
and joins by the same rule (`docpipe.visuals.continuation`).

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
