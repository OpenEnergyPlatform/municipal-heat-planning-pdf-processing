# docpipe.preprocessing.headings

`docpipe/preprocessing/headings.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

headings.py: Font-based heading promotion, a pass over the whole document
after Stage 2's batches. A plain text block becomes a section title when the
layout model missed it, using the document's dominant body font size as the
reference.

Author: Felix Vossel

## Functions

### promote_headings_by_font

```python
def promote_headings_by_font(pages: list[PageData]) -> list[PageData]
```

Promotes heading-looking plain text blocks to "paragraph_title" so Stage 3
opens a section there. Only blocks the layout model left unclassified
(layout_label is None) are considered. Mutates *pages* in place.

[Back to the index](../README.md)
