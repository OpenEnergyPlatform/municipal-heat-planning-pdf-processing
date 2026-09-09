# docpipe.refinement.split

`docpipe/refinement/split.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

split.py: Cuts a section too long to be one retrieval chunk into
several, each a self-contained citation unit.

A section is one chunk and one vector. Past a certain length that
vector stops meaning anything in particular, and past the embedding
model's token limit the tail is not indexed at all, so an oversized
section has to become several.

The model is asked only where it would cut and what to call the
parts, never to reproduce the text. The cut itself happens
mechanically at segment boundaries, which is what makes it safe:
nothing is rephrased, dropped or invented, and each part keeps
exactly the pages, tables and figures that belong to its own text.
Asking only for an outline also keeps the call small, since a section
long enough to need splitting is by definition too long to echo.
When no cut is asked for, or the reply is unusable, a mechanical
fallback cuts at even word-count intervals instead, dropping a cut
that would leave a sliver under about 100 words.

A part still over the configured word limit after this pass is cut
again against a lower target; a single segment carrying the whole
overflow is first divided into smaller ones so that a boundary exists
to cut at. A section whose segments no longer reproduce its own
content, because refinement rewrote it, is left oversized rather than
cut at a guessed position.

Author: Felix Vossel

## Functions

### word_count

```python
def word_count(text: str) -> int
```

### content_from_segments

```python
def content_from_segments(segments: list) -> str
```

Rebuild a section's content from its segments — the inverse of how Stage 3
assembled it (text run by text run, a [block_id] marker where a table or
figure sits).

### needs_split

```python
def needs_split(section: dict, max_words: int = SECTION_MAX_WORDS) -> bool
```

### outline

```python
def outline(section: dict, sample_words: int = SECTION_OUTLINE_WORDS) -> str
```

One numbered line per segment: its size and how it starts.

### apply_cuts

```python
def apply_cuts(section: dict, cuts: list, first_title: Optional[str] = None) -> list
```

Cut *section* at the given segment indices. Returns the parts in order; the
original is returned untouched (as a single-element list) when there is
nothing to cut.

### split_section

```python
def split_section(section: dict, ask: Optional[Callable] = None,
                  reply=_UNASKED) -> list
```

Split one oversized section. *ask* takes the rendered prompt and returns the
model's raw reply; without it (or when the reply is unusable) the section is
cut mechanically at even intervals. *reply* hands in an answer fetched
earlier (see split_oversized); then *ask* is not called at all.

### split_oversized

```python
def split_oversized(sections: list, ask: Optional[Callable] = None,
                    max_words: int = SECTION_MAX_WORDS) -> list
```

Split every section longer than *max_words*; returns the new list.

[Back to the index](../README.md)
