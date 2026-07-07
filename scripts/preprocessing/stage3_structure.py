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

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .config import (
    STRUCTURED_OUTPUT_JSON,
    SECTION_TITLE_CLASSES,
    HEADER_FOOTER_STRIP_ENABLE,
    HEADER_FOOTER_ZONE_FRAC,
    HEADER_FOOTER_MAX_LEN,
    HEADER_FOOTER_MIN_NORM_LEN,
    HEADER_FOOTER_MIN_PAGE_FRAC,
    DIRECTORY_STRIP_ENABLE,
    DIRECTORY_MIN_ENTRIES,
    DIRECTORY_SCORE_THRESHOLD,
    DIRECTORY_TITLE_SCORE_THRESHOLD,
    DIRECTORY_HEAD_LEN,
    DIRECTORY_HEAD_SCORE_THRESHOLD,
    DIRECTORY_MAX_RESIDUAL_CHARS,
    clean_data,
    dump_json_atomic,
)
from .models import Block, FigureRef, PageData, Section, TableRef

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_is_title(block: Block) -> bool:
    """True when the block represents a section-title heading."""
    return block.layout_label in SECTION_TITLE_CLASSES


def _rect(bbox) -> Optional[list[float]]:
    """A block bbox as a clean [x0, y0, x1, y1] rect (PDF points), or None.

    Rounds to 2 decimals; drops degenerate/short boxes so a segment's stored
    geometry never carries a malformed rectangle.
    """
    if not bbox or len(bbox) < 4:
        return None
    try:
        r = [round(float(v), 2) for v in bbox[:4]]
    except (TypeError, ValueError):
        return None
    if r[2] <= r[0] or r[3] <= r[1]:
        return None
    return r


def _resolve_title_text(block: Block) -> Optional[str]:
    """
    Returns the display text for a title block, or None if no text was
    extracted (so the caller can treat the block as plain text instead of
    opening an empty section).
    """
    text = (block.content or "").strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Deterministic running-header / footer stripping
# ---------------------------------------------------------------------------

# Standalone numbers (page numbers) are normalised out so a header that only
# varies by its page number collapses to one key across pages.
_HDR_NUM_RE = re.compile(r"\b\d{1,4}\b")


def _norm_header(text: str) -> str:
    """Page-number-normalized, punctuation-stripped, lower-cased header key."""
    t = re.sub(r"\s+", " ", text).strip()
    t = _HDR_NUM_RE.sub("", t)
    return re.sub(r"\s+", " ", t).strip(" |-–—•·.").lower()


def _header_zone(block: Block, height: float) -> Optional[str]:
    """'H' if the block sits in the header band, 'F' for the footer band, else None."""
    bbox = block.bbox
    if not bbox or len(bbox) < 4 or not height:
        return None
    y_center = (bbox[1] + bbox[3]) / 2.0
    if y_center < HEADER_FOOTER_ZONE_FRAC * height:
        return "H"
    if y_center > (1.0 - HEADER_FOOTER_ZONE_FRAC) * height:
        return "F"
    return None


def _header_candidate(block: Block) -> bool:
    """A short, non-title text block can be a running header/footer."""
    if block.type != "text" or _block_is_title(block):
        return False
    txt = (block.content or "").strip()
    return bool(txt) and len(txt) <= HEADER_FOOTER_MAX_LEN


def strip_running_headers(pages: list[PageData]) -> int:
    """
    Drop running-header/footer text blocks that PP-DocLayout mislabelled as
    plain text (so SUPPRESS_CLASSES missed them). A block is removed when its
    page-number-normalized text recurs in the same (header/footer) zone on at
    least HEADER_FOOTER_MIN_PAGE_FRAC of the pages. Section-title blocks are
    never considered. Mutates *pages* in place; returns the number of blocks
    dropped.
    """
    if not HEADER_FOOTER_STRIP_ENABLE or len(pages) < 4:
        return 0

    zone_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
    for pg in pages:
        for b in pg.blocks:
            if not _header_candidate(b):
                continue
            zone = _header_zone(b, pg.height_pt)
            if zone is None:
                continue
            key = _norm_header(b.content or "")
            if len(key) < HEADER_FOOTER_MIN_NORM_LEN:
                continue
            zone_pages[(zone, key)].add(pg.page_number)

    threshold = max(3, int(HEADER_FOOTER_MIN_PAGE_FRAC * len(pages)))
    headers = {k for k, pgs in zone_pages.items() if len(pgs) >= threshold}
    if not headers:
        return 0

    dropped = 0
    for pg in pages:
        kept: list[Block] = []
        for b in pg.blocks:
            if _header_candidate(b):
                zone = _header_zone(b, pg.height_pt)
                if zone and (zone, _norm_header(b.content or "")) in headers:
                    dropped += 1
                    continue
            kept.append(b)
        pg.blocks = kept
    return dropped


# ---------------------------------------------------------------------------
# Deterministic directory / index section removal
# ---------------------------------------------------------------------------

# A figure/table list entry ("Abbildung 3: … 27") ending in a page number.
_DIR_FIGTAB_RE = re.compile(
    r"(?:Abbildung|Tabelle|Abb\.|Tab\.)\s*\d+\s*[:.]?\s*.{2,90}?\s\d{1,4}(?=\s|$)",
    re.IGNORECASE,
)
# A dot-leader entry ("Einleitung ............ 10").
_DIR_LEADER_RE = re.compile(r".{2,90}?\.{2,}\s*\d{1,4}(?=\s|$)")
# Real media placeholders — their presence means the section references actual
# tables/figures (e.g. an appendix of maps), so it is NOT a directory listing.
_DIR_PLACEHOLDER_RE = re.compile(r"\[p\d+_(?:img|tbl)\d+\]")
# Bibliography titles → routed to the Stage-4 [LITERATURE] BibTeX path, not dropped.
_DIR_LIT_TITLE_RE = re.compile(r"literatur|quellen|referenz|bibliograf", re.IGNORECASE)
# Titles that are themselves directory headings → drop at a lower score bar.
_DIR_TITLE_RE = re.compile(r"inhalt|verzeichnis|contents|directory", re.IGNORECASE)


def _directory_metrics(content: str) -> tuple[float, int, int]:
    """
    (listing_fraction, entry_count, non_listing_chars) for *content*. The
    fraction is the share of characters covered by directory-listing entries
    (overlaps counted once via a covered-char map); non_listing_chars is the
    remainder (a proxy for how much real prose is left).
    """
    if not content or len(content) < 40:
        return 0.0, 0, len(content or "")
    matches = list(_DIR_FIGTAB_RE.finditer(content)) + list(_DIR_LEADER_RE.finditer(content))
    if not matches:
        return 0.0, 0, len(content)
    covered = bytearray(len(content))
    for m in matches:
        covered[m.start():m.end()] = b"\x01" * (m.end() - m.start())
    cov = sum(covered)
    return cov / len(content), len(matches), len(content) - cov


def _is_directory_section(section: Section) -> bool:
    """True when a section is a table-of-contents / list-of-figures / index."""
    content = section.content or ""
    if _DIR_PLACEHOLDER_RE.search(content):        # references real media → keep
        return False
    if _DIR_LIT_TITLE_RE.search(section.title or ""):   # bibliography → Stage-4 BibTeX
        return False
    score, entries, residual = _directory_metrics(content)
    if entries < DIRECTORY_MIN_ENTRIES:
        return False
    # Explicit directory title (Inhaltsverzeichnis, Abbildungsverzeichnis, …).
    if _DIR_TITLE_RE.search(section.title or "") and score >= DIRECTORY_TITLE_SCORE_THRESHOLD:
        return True
    # Otherwise drop only a section that is a listing FROM THE START and has
    # almost no prose left over — this protects real content sections that
    # merely reference a few figures or carry a short trailing list, and ones
    # that open with a prose sentence before a measure/figure listing.
    if score >= DIRECTORY_SCORE_THRESHOLD and residual <= DIRECTORY_MAX_RESIDUAL_CHARS:
        head_score, _, _ = _directory_metrics(content[:DIRECTORY_HEAD_LEN])
        if head_score >= DIRECTORY_HEAD_SCORE_THRESHOLD:
            return True
    return False


def drop_directory_sections(sections: list[Section]) -> tuple[list[Section], int]:
    """Remove directory/index sections; returns (kept_sections, dropped_count)."""
    if not DIRECTORY_STRIP_ENABLE:
        return sections, 0
    kept = [s for s in sections if not _is_directory_section(s)]
    return kept, len(sections) - len(kept)


# ---------------------------------------------------------------------------
# Core assembly
# ---------------------------------------------------------------------------

def build_sections(pages: list[PageData]) -> list[Section]:
    """
    Assembles a flat list of Section objects from the annotated pages.

    A Section is opened by the *first* title block encountered (or, if the
    document starts without a title, a synthetic "Dokument" section is
    created so that leading content is not lost).

    The content field of each section uses [block_id] markers at the
    positions where a table or figure appears in the reading order.
    """
    # Drop running headers/footers PP-DocLayout mislabelled as text, before they
    # get merged into section segments.
    n_hdr = strip_running_headers(pages)
    if n_hdr:
        log.info(f"Stage 3: stripped {n_hdr} running header/footer block(s)")

    sections:        list[Section]  = []
    current_section: Optional[Section] = None
    # (text, page, rect) fragments accumulated for the current section before
    # flushing; rect is the block's [x0,y0,x1,y1] in PDF points (or None).
    pending: list[tuple[str, int, Optional[list[float]]]] = []

    def _emit_text_segment(page, parts: list[str], rects: list[list[float]]) -> None:
        """Append one page-tagged text segment; attach the constituent block
        rects (kept per-block for a finer coordinate highlight than a union)."""
        seg: dict = {"page": page, "kind": "text", "text": " ".join(parts)}
        if rects:
            seg["bbox"] = rects
        current_section.segments.append(seg)

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
        joined = " ".join(t.strip() for (t, _p, _b) in pending if t.strip())
        if joined:
            sep = " " if current_section.content else ""
            current_section.content += sep + joined
        group_page: Optional[int] = None
        group_parts: list[str] = []
        group_rects: list[list[float]] = []
        for (t, p, b) in pending:
            ts = t.strip()
            if not ts:
                continue
            if group_parts and p != group_page:
                _emit_text_segment(group_page, group_parts, group_rects)
                group_parts = []
                group_rects = []
            group_page = p
            group_parts.append(ts)
            if b is not None:
                group_rects.append(b)
        if group_parts:
            _emit_text_segment(group_page, group_parts, group_rects)
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
                        pending.append((block.content, pg.page_number, _rect(block.bbox)))
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
                    rect = _rect(block.bbox)
                    ref = TableRef(
                        id=block.id,
                        path=block.path or "",
                        caption=block.caption,
                        page_number=pg.page_number,
                        source_text=block.source_text,
                        bbox=[rect] if rect is not None else None,
                    )
                    current_section.tables.append(ref)
                    sep = " " if current_section.content else ""
                    current_section.content += sep + f"[{block.id}]"
                    seg: dict = {"page": pg.page_number, "kind": "table", "ref": block.id}
                    if rect is not None:
                        seg["bbox"] = [rect]
                    current_section.segments.append(seg)
                continue

            if block.type == "image":
                _flush_text()
                if current_section is not None:
                    rect = _rect(block.bbox)
                    ref = FigureRef(
                        id=block.id,
                        path=block.path or "",
                        caption=block.caption,
                        page_number=pg.page_number,
                        bbox=[rect] if rect is not None else None,
                    )
                    current_section.figures.append(ref)
                    sep = " " if current_section.content else ""
                    current_section.content += sep + f"[{block.id}]"
                    seg = {"page": pg.page_number, "kind": "figure", "ref": block.id}
                    if rect is not None:
                        seg["bbox"] = [rect]
                    current_section.segments.append(seg)
                continue

            if block.type == "text" and block.content:
                pending.append((block.content, pg.page_number, _rect(block.bbox)))

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

    # Drop table-of-contents / list-of-figures / index sections (low-value
    # listing noise). Literature and real-media sections are guarded.
    sections, n_dir = drop_directory_sections(sections)
    if n_dir:
        log.info(f"Stage 3: dropped {n_dir} directory/index section(s)")

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
    data     = clean_data(sections_to_dict(sections))
    dump_json_atomic(data, out_path)
    log.info(f"Stage 3: output written → {out_path}")
    return out_path