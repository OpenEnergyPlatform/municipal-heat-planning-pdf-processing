# docpipe.preprocessing.layout_captions

`docpipe/preprocessing/layout_captions.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

layout_captions.py: Caption resolution, a pass over the whole document after
Stage 2's batches. It attaches the nearest caption-like block to each table
or image, first among the blocks the layout model labelled as captions,
then, within a fixed distance, among plain text; the claimed block is removed
from the page so it is not also read as section prose. What a caption looks
like is `docpipe/captions.py`.

Author: Felix Vossel

## Functions

### resolve_captions

```python
def resolve_captions(pages: list[PageData]) -> list[PageData]
```

Attaches captions to table/image blocks: nearest CAPTION_CLASSES block (no
distance limit), else nearest plain text block within CAPTION_MAX_DIST_PT.

The winning block's content goes into Block.caption and the block itself is
removed from the page, so it never reaches section content. Each caption is
claimed by at most one media block. Mutates *pages* in place.

[Back to the index](../README.md)
