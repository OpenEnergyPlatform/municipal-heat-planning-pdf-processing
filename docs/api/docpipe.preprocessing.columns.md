# docpipe.preprocessing.columns

`docpipe/preprocessing/columns.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

columns.py: Determines reading order on a page with more than one
text column.

Sorting blocks top-to-bottom, then left-to-right is correct for a
single column and wrong for two: it reads across the gutter and
interleaves the columns line by line, which scrambles the text
beyond repair downstream.

Gutters, the vertical strips that text stays out of, are found
first; the page is then read column by column. A block that crosses
a gutter (a full-width heading, a wide table) is a spanning block: it
ends the columns above it and starts new ones below it, matching how
such a page is read.

The number of columns is not assumed. Two is the common case in a
report, but slide-style pages run to three or four columns, and a
wrong split is as bad as no split at all.

Author: Felix Vossel

## Functions

### find_gutters

```python
def find_gutters(blocks: Sequence, page_width: float) -> list
```

The x positions of the gutters between text columns, left to right. Empty
for a single-column page.

### order_blocks

```python
def order_blocks(blocks: Sequence, gutters: Sequence) -> list
```

Blocks in reading order. Without gutters that is top-to-bottom,
left-to-right; with them it is column by column, band by band.

### sort_page

```python
def sort_page(page, column_layout: str = "auto") -> list
```

Put one page's blocks into reading order, in place. Returns the gutters
used — empty when the page was read as a single column.

    single   never look for columns
    double   look, and fall back to a centre split if nothing is found
    auto     look, and accept one column as the answer

### sort_pages

```python
def sort_pages(pages: Sequence, column_layout: str = "auto") -> int
```

Reading order for every page; returns how many were read as multi-column.

### count_multi_column_pages

```python
def count_multi_column_pages(pages: Sequence) -> tuple
```

(pages with columns, the widest column count seen) without touching a thing.

For deciding whether a corpus needs column_layout: auto at all — the answer
costs a pass over the cached pages, not a re-run.

[Back to the index](../README.md)
