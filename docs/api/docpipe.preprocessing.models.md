# docpipe.preprocessing.models

`docpipe/preprocessing/models.py`, read with `ast` by `scripts/build_docs.py`. The docstrings are the code's own: edit them there, not here.

models.py – Shared data structures of the pipeline.

Author: Felix Vossel

## Classes

### Block

```python
@dataclass
class Block
```

A single content block on a PDF page.

bbox:   [x0, y0, x1, y1] in PDF points, origin top-left.
layout_label:  PP-DocLayout class name; None for raw Stage-1 text blocks.

Fields:

- `id: str`
- `type: str`: "text" | "table" | "image"
- `bbox: list[float]`
- `content: Optional[str] = None`: text blocks
- `path: Optional[str] = None`: table / image crops
- `caption: Optional[str] = None`: resolved caption for tables/images
- `confidence: Optional[float] = None`
- `layout_label: Optional[str] = None`: raw PP-DocLayout class
- `source_text: Optional[str] = None`: native PDF text inside a table bbox (QA reference)
- `font_size: Optional[float] = None`: Dominant font of a Stage-1 text block. Transient: intentionally NOT serialised, so it is absent on blocks loaded from the pages cache.
- `font_bold: Optional[bool] = None`
- `bbox_approx: bool = False`: True when the box was not measured but stacked: a page with no text layer whose text came from the model. Serialised, unlike the font fields, because nothing downstream may present such a rectangle as a located line — it points at the right page and region and no further.

#### Block.to_dict

```python
def to_dict(self) -> dict
```

#### Block.from_dict

```python
@classmethod
def from_dict(cls, d: dict) -> "Block"
```

### PageData

```python
@dataclass
class PageData
```

All extracted data of a single PDF page.

Fields:

- `page_number: int`
- `width_pt: float`
- `height_pt: float`
- `blocks: list[Block] = field(default_factory=list)`

#### PageData.to_dict

```python
def to_dict(self) -> dict
```

#### PageData.from_dict

```python
@classmethod
def from_dict(cls, d: dict) -> "PageData"
```

### FigureRef

```python
@dataclass
class FigureRef
```

A reference to a saved figure/image crop.

Fields:

- `id: str`
- `path: str`
- `caption: Optional[str] = None`
- `page_number: Optional[int] = None`
- `bbox: Optional[list[list[float]]] = None`: A *list* of one [x0, y0, x1, y1] rect in PDF points (top-left origin), not a bare rect — the shape matches Segments.bbox.

#### FigureRef.to_dict

```python
def to_dict(self) -> dict
```

### TableRef

```python
@dataclass
class TableRef
```

A reference to a saved table crop.

Fields:

- `id: str`
- `path: str`
- `caption: Optional[str] = None`
- `page_number: Optional[int] = None`
- `source_text: Optional[str] = None`: native PDF text inside the table bbox (QA reference)
- `bbox: Optional[list[list[float]]] = None`: see FigureRef.bbox

#### TableRef.to_dict

```python
def to_dict(self) -> dict
```

### Section

```python
@dataclass
class Section
```

Fields:

- `title: str`
- `content: str = ""`
- `page_number: Optional[int] = None`
- `tables: list[TableRef] = field(default_factory=list)`
- `figures: list[FigureRef] = field(default_factory=list)`
- `segments: list[dict] = field(default_factory=list)`: Ordered content segments in reading order: {"page": int, "kind": "text"|"table"|"figure", "text": str (text only), "ref": block_id (table/figure only)}.
- `pages: list[int] = field(default_factory=list)`: Sorted distinct page numbers this section spans (derived from segments).

#### Section.to_dict

```python
def to_dict(self) -> dict
```

[Back to the index](../README.md)
