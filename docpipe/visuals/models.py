"""
models.py – Data structures for the imageprocessing module.

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Enriched references (extend the preprocessing TableRef / FigureRef)
# ---------------------------------------------------------------------------

@dataclass
class EnrichedTable:
    """A table reference enriched with extracted Markdown content."""
    id: str
    path: str
    page_number: Optional[int] = None
    caption: Optional[str] = None
    markdown: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "path": self.path}
        if self.page_number is not None:
            d["page_number"] = self.page_number
        if self.caption is not None:
            d["caption"] = self.caption
        if self.markdown is not None:
            d["markdown"] = self.markdown
        return d

    @classmethod
    def from_dict(cls, d: dict) -> EnrichedTable:
        return cls(
            id=d["id"],
            path=d["path"],
            page_number=d.get("page_number"),
            caption=d.get("caption"),
            markdown=d.get("markdown"),
        )


@dataclass
class EnrichedFigure:
    """A figure reference enriched with a textual description."""
    id: str
    path: str
    page_number: Optional[int] = None
    caption: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> dict:
        d: dict = {"id": self.id, "path": self.path}
        if self.page_number is not None:
            d["page_number"] = self.page_number
        if self.caption is not None:
            d["caption"] = self.caption
        if self.description is not None:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: dict) -> EnrichedFigure:
        return cls(
            id=d["id"],
            path=d["path"],
            page_number=d.get("page_number"),
            caption=d.get("caption"),
            description=d.get("description"),
        )


# ---------------------------------------------------------------------------
# Processing statistics
# ---------------------------------------------------------------------------

@dataclass
class ProcessingStats:
    """Tracks progress and outcomes of the enrichment run."""
    total_tables: int = 0
    total_figures: int = 0
    processed_tables: int = 0
    processed_figures: int = 0
    failed_tables: int = 0
    failed_figures: int = 0
    skipped_missing: int = 0
    captions_generated: int = 0
    qa_failed_tables: int = 0  # extracted but flagged low-quality by the QA gate

    def summary(self) -> str:
        sep = "=" * 60
        return (
            f"\n{sep}\n"
            f"Image Processing – Results\n"
            f"{sep}\n"
            f"Tables:  {self.processed_tables}/{self.total_tables} succeeded"
            f" ({self.failed_tables} failed, {self.qa_failed_tables} low-QA)\n"
            f"Figures: {self.processed_figures}/{self.total_figures} succeeded"
            f" ({self.failed_figures} failed)\n"
            f"Missing image files: {self.skipped_missing}\n"
            f"Captions generated:  {self.captions_generated}\n"
            f"{sep}"
        )