"""
models.py – Shared data structures of the pipeline.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional



# ---------------------------------------------------------------------------
# Low-level block
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """
    A single content block on a PDF page.

    bbox:   [x0, y0, x1, y1] in PDF points, origin top-left.
    layout_label:  PP-DocLayout class name; None for raw Stage-1 text blocks.
    """
    id: str
    type: str                         # "text" | "table" | "image"
    bbox: list[float]
    content: Optional[str] = None     # text blocks
    path: Optional[str] = None        # table / image crops
    caption: Optional[str] = None     # resolved caption for tables/images
    confidence: Optional[float] = None
    layout_label: Optional[str] = None  # raw PP-DocLayout class
    source_text: Optional[str] = None   # native PDF text inside a table bbox (QA reference)
    # Dominant font of a Stage-1 text block. Transient: intentionally NOT
    # serialised, so it is absent on blocks loaded from the pages cache.
    font_size: Optional[float] = None
    font_bold: Optional[bool] = None
    # True when the box was not measured but stacked: a page with no text layer
    # whose text came from the model. Serialised, unlike the font fields,
    # because nothing downstream may present such a rectangle as a located
    # line — it points at the right page and region and no further.
    bbox_approx: bool = False

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "type": self.type, "bbox": self.bbox}
        if self.content     is not None: d["content"]      = self.content
        if self.path        is not None: d["path"]         = self.path
        if self.caption     is not None: d["caption"]      = self.caption
        if self.confidence  is not None: d["confidence"]   = round(self.confidence, 3)
        if self.layout_label is not None: d["layout_label"] = self.layout_label
        if self.source_text is not None: d["source_text"]  = self.source_text
        if self.bbox_approx:             d["bbox_approx"]   = True
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Block":
        return cls(
            id=d["id"],
            type=d["type"],
            bbox=d["bbox"],
            content=d.get("content"),
            path=d.get("path"),
            caption=d.get("caption"),
            confidence=d.get("confidence"),
            layout_label=d.get("layout_label"),
            source_text=d.get("source_text"),
            bbox_approx=bool(d.get("bbox_approx", False)),
        )


# ---------------------------------------------------------------------------
# Per-page container
# ---------------------------------------------------------------------------

@dataclass
class PageData:
    """All extracted data of a single PDF page."""
    page_number: int
    width_pt: float
    height_pt: float
    blocks: list[Block] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "width_pt":    self.width_pt,
            "height_pt":   self.height_pt,
            "blocks":      [b.to_dict() for b in self.blocks],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PageData":
        pg = cls(
            page_number=d["page_number"],
            width_pt=d["width_pt"],
            height_pt=d["height_pt"],
        )
        for bd in d.get("blocks", []):
            pg.blocks.append(Block.from_dict(bd))
        return pg


# ---------------------------------------------------------------------------
# Document-level section (built in Stage 3)
# ---------------------------------------------------------------------------

@dataclass
class FigureRef:
    """A reference to a saved figure/image crop."""
    id: str
    path: str
    caption: Optional[str] = None
    page_number: Optional[int] = None
    # A *list* of one [x0, y0, x1, y1] rect in PDF points (top-left origin),
    # not a bare rect — the shape matches Segments.bbox.
    bbox: Optional[list[list[float]]] = None

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "path": self.path}
        if self.caption is not None:
            d["caption"] = self.caption
        if self.page_number is not None:
            d["page_number"] = self.page_number
        if self.bbox is not None:
            d["bbox"] = self.bbox
        return d


@dataclass
class TableRef:
    """A reference to a saved table crop."""
    id: str
    path: str
    caption: Optional[str] = None
    page_number: Optional[int] = None
    source_text: Optional[str] = None   # native PDF text inside the table bbox (QA reference)
    bbox: Optional[list[list[float]]] = None   # see FigureRef.bbox

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "path": self.path}
        if self.caption is not None:
            d["caption"] = self.caption
        if self.page_number is not None:
            d["page_number"] = self.page_number
        if self.source_text is not None:
            d["source_text"] = self.source_text
        if self.bbox is not None:
            d["bbox"] = self.bbox
        return d


@dataclass
class Section:
    title: str
    content: str = ""
    page_number: Optional[int] = None
    tables: list[TableRef] = field(default_factory=list)
    figures: list[FigureRef] = field(default_factory=list)
    # Ordered content segments in reading order:
    # {"page": int, "kind": "text"|"table"|"figure",
    #  "text": str (text only), "ref": block_id (table/figure only)}.
    segments: list[dict] = field(default_factory=list)
    # Sorted distinct page numbers this section spans (derived from segments).
    pages: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title":       self.title,
            "page_number": self.page_number,
            "pages":       self.pages,
            "content":     self.content,
            "segments":    self.segments,
            "tables":      [t.to_dict() for t in self.tables],
            "figures":     [f.to_dict() for f in self.figures],
        }