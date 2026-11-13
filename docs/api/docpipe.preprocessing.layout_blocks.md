# docpipe.preprocessing.layout_blocks

`docpipe/preprocessing/layout_blocks.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

layout_blocks.py: Turns the detections of one page into blocks.

Each surviving box becomes a text suppression, a saved table or image crop,
or a title or caption Block; classes outside those sets are ignored, since
the Stage 1 PyMuPDF text blocks already cover that content. The text in a
footnote box leaves the page like a page number does, and the document's log
says how many text blocks and characters that was.

Author: Felix Vossel

## Classes

### FootnoteTally

```python
@dataclass
class FootnoteTally
```

What the footnote class took off the pages of one document.

Fields:

- `blocks: int = 0`
- `chars: int = 0`

#### FootnoteTally.add

```python
def add(self, removed: list[Block]) -> None
```

#### FootnoteTally.line

```python
def line(self) -> str
```

## Functions

### vertical_overlap_fraction

```python
def vertical_overlap_fraction(bbox_a: list[float], bbox_b: list[float]) -> float
```

Vertical overlap fraction, relative to the shorter of the two boxes.

### process_page

```python
def process_page(
    pg: PageData,
    fp: fitz.Page,
    det_w: int,
    det_h: int,
    crop_image: Image.Image,
    detections: list[Detection],
    images_dir: Path,
    footnotes: Optional[FootnoteTally] = None,
) -> tuple[PageData, list[CropJob]]
```

Processes one page through all detection-type branches; returns the updated
PageData and the crop jobs still to be written.

*detections* are in detection-image pixel space (det_w x det_h), while
crops come from *crop_image*, which may be rendered at a different DPI.
*footnotes*, when given, is told which text blocks the footnote class took
off this page.

[Back to the index](../README.md)
