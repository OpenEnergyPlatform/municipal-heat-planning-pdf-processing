"""
models.py – Shared data structures of the pipeline.

Author: Felix Vossel
"""
from __future__ import annotations

import numpy as np
import fitz
from dataclasses import dataclass, field
from typing import Optional
from PIL import Image
from pathlib import Path


@dataclass
class Block:
    """
    Represents a single content block on a PDF page.

    type:   "text"  – Text block from PyMuPDF rawdict
            "table" – Detected table (layout model)
            "image" – Detected image/figure (layout model)
    bbox:   [x0, y0, x1, y1] in PDF points (pt), origin top-left.
    layout_label:  original PP-DocLayout class name (e.g. "paragraph_title",
                   "header", "footer", …) – set during Stage 2 for layout
                   blocks; None for raw text blocks from Stage 1.
    """
    id: str
    type: str                         # "text" | "table" | "image"
    bbox: list[float]
    content: Optional[str] = None     # text blocks
    path: Optional[str] = None        # table / image crops
    caption: Optional[str] = None     # resolved caption for tables/images
    confidence: Optional[float] = None
    layout_label: Optional[str] = None  # raw PP-DocLayout class

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "type": self.type, "bbox": self.bbox}
        if self.content     is not None: d["content"]      = self.content
        if self.path        is not None: d["path"]         = self.path
        if self.caption     is not None: d["caption"]      = self.caption
        if self.confidence  is not None: d["confidence"]   = round(self.confidence, 3)
        if self.layout_label is not None: d["layout_label"] = self.layout_label
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
        )



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

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "path": self.path}
        if self.caption is not None:
            d["caption"] = self.caption
        if self.page_number is not None:
            d["page_number"] = self.page_number
        return d


@dataclass
class TableRef:
    """A reference to a saved table crop."""
    id: str
    path: str
    caption: Optional[str] = None
    page_number: Optional[int] = None

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "path": self.path}
        if self.caption is not None:
            d["caption"] = self.caption
        if self.page_number is not None:
            d["page_number"] = self.page_number
        return d


@dataclass
class Section:
    title: str
    content: str = ""
    page_number: Optional[int] = None
    tables: list[TableRef] = field(default_factory=list)
    figures: list[FigureRef] = field(default_factory=list)
    # Fine-grained page provenance: ordered content segments, each tagged with
    # the source page. A segment is either a run of text or a table/figure
    # reference: {"page": int, "kind": "text"|"table"|"figure",
    #             "text": str (text only), "ref": block_id (table/figure only)}.
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


@dataclass
class PageImage:
    """Pairs a PageData record with its PIL image and the originating fitz page."""
    page_data: PageData
    pil_image: Image.Image
    fitz_page: fitz.Page


@dataclass
class CropJob:
    """Everything needed to encode and write one detected region as PNG."""
    block_id: str
    out_path: Path
    crop_rgb: np.ndarray


@dataclass
class Detection:
    """A single post-processed detection box for one page."""
    label: str
    label_id: int
    score: float
    bbox_px: list[float]