"""
stage3_structure.py – Deterministic section assembly from layout-annotated pages.

Replaces the old Stage 3 (chunking) and Stage 4 (LLM) with a purely
rule-based structuring pass that is both fast and reproducible.

Algorithm
---------
1.  Iterate over all blocks of all pages in reading order (top-to-bottom,
    left-to-right).
2.  A block whose layout_label is in SECTION_TITLE_CLASSES opens a new
    Section.  Exception: paragraph_title blocks that sit on the same row as
    another detected element are already converted to plain text in Stage 2
    and do NOT carry layout_label, so they naturally fall into the text path.
3.  For every table / image block:
      - A [block_id] placeholder is appended to the running text content of
        the current section.
      - The corresponding TableRef / FigureRef (with path and caption) is
        added to the section.
4.  For every plain text block the content is appended to the running prose
    of the current section.
5.  Adjacent text pieces within a section are joined with a single space;
    trailing / leading whitespace is stripped.

The result is a list of Section objects ready for serialisation.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from .config import (
    STRUCTURED_OUTPUT_JSON,
    SECTION_TITLE_CLASSES,
    clean_data
)
from .models import Block, FigureRef, PageData, Section, TableRef

log = logging.getLogger(__name__)


def _block_is_title(block: Block) -> bool:
    """True when the block represents a section-title heading."""
    return block.layout_label in SECTION_TITLE_CLASSES


def _resolve_title_text(block: Block) -> Optional[str]:
    """
    Returns the display text for a title block, or None if no text was
    extracted (so the caller can treat the block as plain text instead of
    opening an empty section).
    """
    text = (block.content or "").strip()
    return text if text else None


def build_sections(pages: list[PageData]) -> list[Section]:
    """
    Assembles a flat list of Section objects from the annotated pages.

    A Section is opened by the *first* title block encountered (or, if the
    document starts without a title, a synthetic "Dokument" section is
    created so that leading content is not lost).

    The content field of each section uses [block_id] markers at the
    positions where a table or figure appears in the reading order.
    """
    sections:        list[Section]  = []
    current_section: Optional[Section] = None
    # (text, page) fragments accumulated for the current section before flushing.
    pending: list[tuple[str, int]] = []

    def _flush_text() -> None:
        """
        Flush accumulated text fragments into the current section's content and
        its page-tagged segments (consecutive same-page fragments are merged
        into one text segment).
        """
        nonlocal pending
        if current_section is None or not pending:
            pending = []
            return
        joined = " ".join(t.strip() for (t, _p) in pending if t.strip())
        if joined:
            sep = " " if current_section.content else ""
            current_section.content += sep + joined
        group_page: Optional[int] = None
        group_parts: list[str] = []
        for (t, p) in pending:
            ts = t.strip()
            if not ts:
                continue
            if group_parts and p != group_page:
                current_section.segments.append(
                    {"page": group_page, "kind": "text",
                     "text": " ".join(group_parts)}
                )
                group_parts = []
            group_page = p
            group_parts.append(ts)
        if group_parts:
            current_section.segments.append(
                {"page": group_page, "kind": "text", "text": " ".join(group_parts)}
            )
        pending = []

    def _open_section(title: str, page_number: Optional[int] = None) -> None:
        nonlocal current_section
        _flush_text()
        if current_section is not None:
            current_section.content = current_section.content.strip()
        new_section = Section(title=title, page_number=page_number)
        sections.append(new_section)
        current_section = new_section

    # Open with page_number=None so the derivation step below sets it from the
    # first real content page (a leading cover/blank page may push real content
    # to page 2+); hardcoding 1 would mis-attribute the primary page.
    _open_section("Dokument", page_number=None)

    for pg in pages:
        for block in pg.blocks:

            if _block_is_title(block):
                title_text = _resolve_title_text(block)
                if title_text is None:
                    log.debug(
                        f"  Page {pg.page_number}: title block (label="
                        f"{block.layout_label}) has no text → treated as text"
                    )
                    if block.content:
                        pending.append((block.content, pg.page_number))
                    continue
                log.debug(
                    f"  Page {pg.page_number}: new section '{title_text}' "
                    f"(label={block.layout_label})"
                )
                _open_section(title_text, page_number=pg.page_number)
                continue

            if block.type == "table":
                _flush_text()
                if current_section is not None:
                    ref = TableRef(
                        id=block.id,
                        path=block.path or "",
                        caption=block.caption,
                        page_number=pg.page_number,
                    )
                    current_section.tables.append(ref)
                    sep = " " if current_section.content else ""
                    current_section.content += sep + f"[{block.id}]"
                    current_section.segments.append(
                        {"page": pg.page_number, "kind": "table", "ref": block.id}
                    )
                continue

            if block.type == "image":
                _flush_text()
                if current_section is not None:
                    ref = FigureRef(
                        id=block.id,
                        path=block.path or "",
                        caption=block.caption,
                        page_number=pg.page_number,
                    )
                    current_section.figures.append(ref)
                    sep = " " if current_section.content else ""
                    current_section.content += sep + f"[{block.id}]"
                    current_section.segments.append(
                        {"page": pg.page_number, "kind": "figure", "ref": block.id}
                    )
                continue

            if block.type == "text" and block.content:
                pending.append((block.content, pg.page_number))

    # Flush any remaining text after the last page.
    _flush_text()
    if current_section is not None:
        current_section.content = current_section.content.strip()

    # Drop a leading empty "Dokument" section if the document starts with a
    # real title on the very first block.
    if (
        sections
        and sections[0].title == "Dokument"
        and not sections[0].content
        and not sections[0].tables
        and not sections[0].figures
    ):
        sections.pop(0)

    # Derive each section's page span from its segments.
    for s in sections:
        s.pages = sorted({
            seg["page"] for seg in s.segments if seg.get("page") is not None
        })
        if s.page_number is None and s.pages:
            s.page_number = s.pages[0]

    log.info(f"Stage 3: {len(sections)} sections assembled")
    for s in sections:
        n_t = len(s.tables)
        n_f = len(s.figures)
        preview = (s.content[:60] + "…") if len(s.content) > 60 else s.content
        log.debug(f"  [{s.title}] tables={n_t} figures={n_f} | {preview!r}")

    return sections


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def sections_to_dict(sections: list[Section]) -> dict:
    """Serialises the section list into the final output JSON structure."""
    return {"sections": [s.to_dict() for s in sections]}



def save_output(sections: list[Section], output_dir: Path) -> Path:
    """
    Writes the Stage 3 JSON to *output_dir / STRUCTURED_OUTPUT_JSON* and
    returns the path.
    """
    out_path = output_dir / STRUCTURED_OUTPUT_JSON
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data     = clean_data(sections_to_dict(sections))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info(f"Stage 3: output written → {out_path}")
    return out_path