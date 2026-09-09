# docpipe.preprocessing.stage2_layout

`docpipe/preprocessing/stage2_layout.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

stage2_layout.py: Detects page layout with PP-DocLayoutV3 and turns
detections into tables, images, section titles and text suppressions
for Stage 3.

Renders the open fitz pages from Stage 1 in batches and runs object
detection. Each surviving box becomes a text suppression, a saved
table or image crop, or a title or caption Block; classes outside
those sets are ignored, since the Stage 1 PyMuPDF text blocks already
cover that content. A detection passes a global confidence filter,
then a per-class threshold, then per-class non-maximum suppression
and cross-class suppression among table and image boxes, so one
region never yields two crops.

Two passes run over the whole document afterward. Font-based heading
promotion turns a plain text block into a section title when the
layout model missed it, using the document's dominant body font size
as the reference. Caption resolution attaches the nearest
caption-like block to each table or image, first among the blocks
the layout model labelled as captions, then, within a fixed distance,
among plain text; the claimed block is removed from the page so it
is not also read as section prose.

A batch whose pages never reached the detection model is reported as
LayoutDetectionFailed rather than left with text and no layout, so
the caller drops the document for the next run to retry.

Author: Felix Vossel

## Classes

### LayoutDetectionFailed

```python
class LayoutDetectionFailed(RuntimeError)
```

Raised when a batch never reached the model, so pages have no layout.

## Functions

### load_model

```python
def load_model()
```

Returns (processor, model, device), downloading the weights on first run.
Call once and pass the tuple to detect_layout_all_pages() — reloading per
PDF re-reads the weights.

### promote_headings_by_font

```python
def promote_headings_by_font(pages: list[PageData]) -> list[PageData]
```

Promotes heading-looking plain text blocks to "paragraph_title" so Stage 3
opens a section there. Only blocks the layout model left unclassified
(layout_label is None) are considered. Mutates *pages* in place.

### resolve_captions

```python
def resolve_captions(pages: list[PageData]) -> list[PageData]
```

Attaches captions to table/image blocks: nearest CAPTION_CLASSES block (no
distance limit), else nearest plain text block within CAPTION_MAX_DIST_PT.

The winning block's content goes into Block.caption and the block itself is
removed from the page, so it never reaches section content. Each caption is
claimed by at most one media block. Mutates *pages* in place.

### detect_layout_all_pages

```python
def detect_layout_all_pages(
    pages: list[PageData],
    fitz_pages: list[fitz.Page],
    output_dir: Path,
    model_tuple,
) -> list[PageData]
```

Runs layout detection over *pages*, writing crop PNGs into
output_dir/DIR_IMAGES and returning the updated PageData list (suppressed
text blocks removed, table/image/title blocks added).

*fitz_pages* must be in the same order as *pages* and still open;
*model_tuple* is (processor, model, device) from load_model(). Pages are
rendered and freed per batch, so the whole document is never resident.

[Back to the index](../README.md)
