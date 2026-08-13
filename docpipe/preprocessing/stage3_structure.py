"""
stage3_structure.py – Deterministic section assembly from layout-annotated pages.

Walks all blocks in reading order: SECTION_TITLE_CLASSES blocks open a new
Section, tables/figures become a TableRef/FigureRef plus a [block_id]
placeholder in the section content, and plain text is appended as prose.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .config import (
    SECTIONS_JSON,
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
    caption_like,
    clean_data,
    dump_json_atomic,
)
from docpipe.profile import active_profile, profile_value

from .columns import sort_pages
from .models import Block, FigureRef, PageData, Section, TableRef

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_is_title(block: Block) -> bool:
    """True when the block represents a section-title heading."""
    return block.layout_label in SECTION_TITLE_CLASSES


def _rect(bbox) -> Optional[list[float]]:
    """A block bbox as a clean [x0, y0, x1, y1] rect (PDF points), or None when
    it is malformed or degenerate."""
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
    """Display text of a title block, or None if it has none — the caller then
    treats the block as plain text rather than opening an empty section."""
    text = (block.content or "").strip()
    return text if text else None


# ---------------------------------------------------------------------------
# Deterministic running-header / footer stripping
# ---------------------------------------------------------------------------

# Standalone numbers are normalised out so a header that only varies by its
# page number collapses to one key across pages.
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
    Drop text blocks whose page-number-normalized text recurs in the same
    header/footer zone on at least HEADER_FOOTER_MIN_PAGE_FRAC of the pages.
    Section titles are never touched. Mutates *pages* in place; returns the
    number of blocks dropped.
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
# Which words open one is the corpus language's business: the German pattern
# matched nothing in an English corpus, so its lists of figures were never
# recognised and landed in the index as sections.
_dir_figtab: dict = {}


def _dir_figtab_re():
    profile = active_profile()
    name = profile.name if profile else None
    if name not in _dir_figtab:
        words = profile_value("preprocessing", "DIRECTORY_FIGTAB_WORDS")
        _dir_figtab[name] = re.compile(
            r"(?:" + "|".join(words) + r")\s*\d+\s*[:.]?\s*.{2,90}?\s\d{1,4}(?=\s|$)",
            re.IGNORECASE,
        )
    return _dir_figtab[name]


# A dot-leader entry ("Einleitung ............ 10").
_DIR_LEADER_RE = re.compile(r".{2,90}?\.{2,}\s*\d{1,4}(?=\s|$)")
# Real media placeholders — a section holding one references actual
# tables/figures, so it is not a directory listing.
_DIR_PLACEHOLDER_RE = re.compile(r"\[p\d+_(?:img|tbl)\d+\]")
# Bibliography titles → routed to the Stage-4 [LITERATURE] BibTeX path, not
# dropped. "References" did not match the German pattern, so an English
# bibliography was a directory listing and got thrown away.
_dir_lit: dict = {}


def _dir_lit_title_re():
    profile = active_profile()
    name = profile.name if profile else None
    if name not in _dir_lit:
        words = profile_value("preprocessing", "BIBLIOGRAPHY_TITLE_WORDS")
        _dir_lit[name] = re.compile("|".join(words), re.IGNORECASE)
    return _dir_lit[name]


# Titles that are themselves directory headings → drop at a lower score bar.
_DIR_TITLE_RE = re.compile(r"inhalt|verzeichnis|contents|directory", re.IGNORECASE)


def _directory_metrics(content: str) -> tuple[float, int, int]:
    """
    (listing_fraction, entry_count, non_listing_chars) for *content*. The
    fraction is the share of chars covered by directory-listing entries, with
    overlaps counted once.
    """
    if not content or len(content) < 40:
        return 0.0, 0, len(content or "")
    matches = list(_dir_figtab_re().finditer(content)) + list(_DIR_LEADER_RE.finditer(content))
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
    if _dir_lit_title_re().search(section.title or ""):   # bibliography → Stage-4 BibTeX
        return False
    score, entries, residual = _directory_metrics(content)
    if entries < DIRECTORY_MIN_ENTRIES:
        return False
    # Explicit directory title (Inhaltsverzeichnis, Abbildungsverzeichnis, …).
    if _DIR_TITLE_RE.search(section.title or "") and score >= DIRECTORY_TITLE_SCORE_THRESHOLD:
        return True
    # Otherwise drop only a section that is a listing FROM THE START and has
    # almost no prose left over — this protects content sections that merely
    # reference a few figures or carry a short trailing list.
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

def build_sections(pages: list[PageData], column_layout: str = "auto") -> list[Section]:
    """
    Assembles a flat list of Section objects from the annotated pages.

    Each title block opens a Section; a synthetic "Dokument" section catches
    content before the first title. Section.content carries [block_id] markers
    where a table or figure appears in the reading order.

    *column_layout* (from the profile: auto | single | double) decides whether a
    page is read as one column or column by column.

    Note: mutates *pages* (blocks are put in reading order and running
    headers/footers are stripped, both in place).
    """
    # Reading order first: everything below walks the blocks in sequence.
    sort_pages(pages, column_layout)

    # Must happen before blocks get merged into section segments.
    n_hdr = strip_running_headers(pages)
    if n_hdr:
        log.info(f"Stage 3: stripped {n_hdr} running header/footer block(s)")

    sections:        list[Section]  = []
    current_section: Optional[Section] = None
    # (text, page, rect) fragments accumulated for the current section before
    # flushing; rect is the block's [x0,y0,x1,y1] in PDF points (or None).
    pending: list[tuple[str, int, Optional[list[float]]]] = []

    def _emit_text_segment(page, parts: list[str], rects: list[list[float]]) -> None:
        """Append one page-tagged text segment. Rects stay per-block rather
        than unioned, for a finer coordinate highlight."""
        seg: dict = {"page": page, "kind": "text", "text": " ".join(parts)}
        if rects:
            seg["bbox"] = rects
        current_section.segments.append(seg)

    def _flush_text() -> None:
        """Flush pending fragments into the current section's content and
        segments; consecutive same-page fragments merge into one segment."""
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

    # page_number=None, not 1: a leading cover/blank page can push real content
    # to page 2+, so the derivation step below sets it from the first segment.
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
                        caption=block.caption if caption_like(block.caption) else None,
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
                        caption=block.caption if caption_like(block.caption) else None,
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

    _flush_text()
    if current_section is not None:
        current_section.content = current_section.content.strip()

    # Drop the synthetic "Dokument" section when the document opened with a
    # real title and it stayed empty.
    if (
        sections
        and sections[0].title == "Dokument"
        and not sections[0].content
        and not sections[0].tables
        and not sections[0].figures
    ):
        sections.pop(0)

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
    """Writes the Stage 3 JSON under *output_dir* and returns its path."""
    out_path = output_dir / SECTIONS_JSON
    data     = clean_data(sections_to_dict(sections))
    dump_json_atomic(data, out_path)
    log.info(f"Stage 3: output written → {out_path}")
    return out_path