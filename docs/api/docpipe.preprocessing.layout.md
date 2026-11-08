# docpipe.preprocessing.layout

`docpipe/preprocessing/layout.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

layout.py: Stage 2. Detects the layout of every page with PP-DocLayoutV3 and
turns it into tables, images, section titles and text suppressions for
Stage 3.

The open fitz pages from Stage 1 are rendered in batches, by the prefetch
thread or by worker processes (`rendering.py`), and the model's inputs of a
batch are built in that thread too, while the batch before it runs through
the model. Each page then goes through `layout_blocks.process_page`, and its
crops are encoded and written by a thread of their own (`crops.py`). Once
every batch has run, `headings.py` and `layout_captions.py` pass over the
whole document.

A batch whose pages never reached the detection model is reported as
LayoutDetectionFailed rather than left with text and no layout, so the
caller drops the document for the next run to retry.

Author: Felix Vossel

## Classes

### LayoutDetectionFailed

```python
class LayoutDetectionFailed(RuntimeError)
```

Raised when a batch never reached the model, so pages have no layout.

## Functions

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
