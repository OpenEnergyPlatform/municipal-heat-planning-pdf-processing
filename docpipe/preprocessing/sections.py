"""
sections.py: Stage 3. Assembles document sections deterministically
from pages that carry the layout labels Stage 2 attached.

Walks every block in reading order. A block labelled as a section
title opens a new Section; a table or figure block becomes a
TableRef or FigureRef plus a [block_id] placeholder in the section
content; plain text is appended as prose. Reading order across a
multi-column page is settled first, by columns.sort_pages.

Two passes run before assembly. strip_running_headers drops text
blocks whose page-number-normalized text recurs in the same header
or footer band on enough pages to be a running header or footer,
without touching a section title. drop_directory_sections removes
table-of-contents, list-of-figures and index sections by scoring how
much of a section's text is directory-listing entries, while keeping
a section that still references a real table or figure and routing a
bibliography title to the Stage 4 literature path instead of
dropping it.

A footnote at the foot of a page (a text block Stage 2 labelled
`footnote`) stands on a line of its own after the text of its page, a
text segment marked `"footnote": true`. Where the page's text breaks off
in a sentence that runs on to the next page, the footnote waits for the
end of that sentence, so no sentence is cut by it (owner decision
2026-11-17: "wir sollten die Fußnoten behalten").

A table's or figure's caption is settled during assembly, where the
section text and its placeholder are both available: resolve_title
(docpipe.captions) chooses between the caption block Stage 2 attached
by distance and a nearby sentence in the section text, for plans
whose tables carry a rounding footnote that would otherwise be read
as the caption.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .. import rules
from .config import (
    SECTIONS_JSON,
    caption_like,
    clean_data,
    dump_json_atomic,
)
from docpipe.artifacts import SECTIONS_VERSION
from docpipe.captions import resolve_title

from .columns import sort_pages
from .models import Block, FigureRef, PageData, Section, TableRef

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_is_title(block: Block) -> bool:
    """True when the block represents a section-title heading."""
    return block.layout_label in rules.get("heading_classes")


def _block_is_footnote(block: Block) -> bool:
    """True when the block is the text of a footnote at the foot of a page
    (Stage 2 keeps it, labelled, owner decision 2026-11-17)."""
    return block.layout_label in rules.get("footnote_classes")


def _sentence_end():
    """The end of a sentence: a mark of the rule `sentence_end_marks`, then
    only what closes it."""
    return rules.derived("stage_sections:sentence_end", lambda: re.compile(
        "[" + "".join(re.escape(mark) for mark
                      in rules.get("sentence_end_marks")) + "]"
        + r"[\"'”“»)\]]*$"))


def _ends_sentence(text: str) -> bool:
    """Does *text* end a sentence, so that a footnote may follow it?"""
    return bool(_sentence_end().search((text or "").rstrip()))


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

def _hdr_num_re():
    """Standalone numbers of up to the rule `running_header_number_digits`
    digits: normalised out so a header that only varies by its page number
    collapses to one key across pages."""
    return rules.derived("stage_sections:header_number", lambda: re.compile(
        r"\b\d{1,%d}\b" % rules.get("running_header_number_digits")))


def _norm_header(text: str) -> str:
    """Page-number-normalized, punctuation-stripped, lower-cased header key."""
    t = re.sub(r"\s+", " ", text).strip()
    t = _hdr_num_re().sub("", t)
    return re.sub(r"\s+", " ", t).strip(" |-–—•·.").lower()


def _header_zone(block: Block, height: float) -> Optional[str]:
    """'H' if the block sits in the header band, 'F' for the footer band, else None."""
    bbox = block.bbox
    if not bbox or len(bbox) < 4 or not height:
        return None
    y_center = (bbox[1] + bbox[3]) / 2.0
    band = rules.get("running_header_band")
    if y_center < band * height:
        return "H"
    if y_center > (1.0 - band) * height:
        return "F"
    return None


def _header_candidate(block: Block) -> bool:
    """A short, non-title text block can be a running header/footer."""
    if block.type != "text" or _block_is_title(block):
        return False
    txt = (block.content or "").strip()
    return bool(txt) and len(txt) <= rules.get("running_header_max_chars")


def title_page_of(pages: list[PageData]) -> Optional[int]:
    """The page the document title stands on: that of the first `doc_title`
    block with text, else the first page. None for no pages."""
    ordered = sorted(pages, key=lambda pg: pg.page_number)
    for pg in ordered:
        for b in pg.blocks:
            if (b.layout_label == "doc_title"
                    and _resolve_title_text(b) is not None):
                return pg.page_number
    return ordered[0].page_number if ordered else None


def strip_running_headers(pages: list[PageData]) -> int:
    """
    Drop text blocks whose page-number-normalized text recurs in the same
    header/footer zone on at least the share `running_header_page_share` of
    the pages.
    Section titles are never touched. The first page and the title page
    (`title_page_of`) keep their blocks: their copy of a running head is the
    document's citation line (journal, volume, year), though it still counts
    toward detecting the header on other pages. A cover before the title page
    and a title the layout detection found further in both leave the first
    page its own.
    Mutates *pages* in place; returns the number of blocks dropped.
    """
    if (not rules.get("strip_running_headers")
            or len(pages) < rules.get("running_header_min_pages")):
        return 0
    min_norm_chars = rules.get("running_header_min_chars")

    zone_pages: dict[tuple[str, str], set[int]] = defaultdict(set)
    for pg in pages:
        for b in pg.blocks:
            if not _header_candidate(b):
                continue
            zone = _header_zone(b, pg.height_pt)
            if zone is None:
                continue
            key = _norm_header(b.content or "")
            if len(key) < min_norm_chars:
                continue
            zone_pages[(zone, key)].add(pg.page_number)

    threshold = max(rules.get("running_header_min_repeats"),
                    int(rules.get("running_header_page_share") * len(pages)))
    headers = {k for k, pgs in zone_pages.items() if len(pgs) >= threshold}
    if not headers:
        return 0

    front = ({min(pg.page_number for pg in pages), title_page_of(pages)}
             if rules.get("keep_front_page_headers") else set())
    dropped = 0
    for pg in pages:
        if pg.page_number in front:
            continue
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
# The words are the rule `directory_figure_words`; an entry is at most
# `directory_entry_max_chars` long before its page number.
def _dir_figtab_re():
    return rules.derived("stage_sections:figtab", lambda: re.compile(
        r"(?:" + "|".join(rules.get("directory_figure_words"))
        + r")\s*\d+\s*[:.]?\s*.{2,"
        + str(rules.get("directory_entry_max_chars"))
        + r"}?\s\d{1,4}(?=\s|$)",
        re.IGNORECASE,
    ))


# A dot-leader entry ("Einleitung ............ 10").
def _dir_leader_re():
    return rules.derived("stage_sections:leader", lambda: re.compile(
        r".{2," + str(rules.get("directory_entry_max_chars"))
        + r"}?\.{2,}\s*\d{1,4}(?=\s|$)"))

# Real media placeholders — a section holding one references actual
# tables/figures, so it is not a directory listing.
_DIR_PLACEHOLDER_RE = re.compile(r"\[p\d+_(?:img|tbl)\d+\]")
# Bibliography titles → routed to the Stage-4 [LITERATURE] BibTeX path, not
# dropped. "References" did not match the German pattern, so an English
# bibliography was a directory listing and got thrown away.
def _dir_lit_title_re():
    return rules.derived("stage_sections:bibliography", lambda: re.compile(
        "|".join(rules.get("bibliography_title_words")), re.IGNORECASE))


# Titles that are themselves directory headings → drop at a lower score bar.
# Which words make one is the corpus language's business, like the two lists
# above: the profile says them (the rule `directory_title_words`), as
# fragments of a pattern found anywhere in the title.
def _dir_title_re():
    def build():
        words = rules.get("directory_title_words")
        # No words is a statement, not an empty alternative: joined it would
        # be the pattern that matches every title.
        return re.compile("|".join(words) if words else r"(?!)",
                          re.IGNORECASE)
    return rules.derived("stage_sections:directory_title", build)


def _directory_metrics(content: str) -> tuple[float, int, int]:
    """
    (listing_fraction, entry_count, non_listing_chars) for *content*. The
    fraction is the share of chars covered by directory-listing entries, with
    overlaps counted once.
    """
    if not content or len(content) < rules.get("directory_min_chars"):
        return 0.0, 0, len(content or "")
    matches = list(_dir_figtab_re().finditer(content)) + list(_dir_leader_re().finditer(content))
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
    if entries < rules.get("directory_min_entries"):
        return False
    # Explicit directory title (a table of contents, a list of figures, …).
    if (_dir_title_re().search(section.title or "")
            and score >= rules.get("directory_titled_listing_share")):
        return True
    # Otherwise drop only a section that is a listing FROM THE START and has
    # almost no prose left over — this protects content sections that merely
    # reference a few figures or carry a short trailing list.
    if (score >= rules.get("directory_listing_share")
            and residual <= rules.get("directory_max_other_chars")):
        head_score, _, _ = _directory_metrics(
            content[:rules.get("directory_head_chars")])
        if head_score >= rules.get("directory_head_share"):
            return True
    return False


def drop_directory_sections(sections: list[Section]) -> tuple[list[Section], int]:
    """Remove directory/index sections; returns (kept_sections, dropped_count)."""
    if not rules.get("strip_directory_sections"):
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

    A table's caption is settled here, where the section text and the
    placeholder are both in hand. Stage 2 links a caption block by distance,
    and in a plan whose tables carry a rounding footnote it links the
    footnote: 15 of Kassel's 89 tables were captioned "Hinweis: Wegen der
    Rundung von Zahlenwerten ..." while the sentence naming them stood in the
    text a few words before their own placeholder. `resolve_title` takes it
    from there and leaves a caption that already opens like one alone. The
    sentence stays in the section content: a quote of it has to remain
    findable where it was read.

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
    # The footnotes of a page, held until the sentence they interrupt ends
    # (a paragraph that runs on to the next page), then each set on a line
    # of its own; *new_line* says that what follows them begins a line.
    held: list[tuple[str, int, Optional[list[float]]]] = []
    new_line = False

    def _sep() -> str:
        """What joins the next text or placeholder to the section's content:
        a line break after a footnote, else a space."""
        nonlocal new_line
        if not current_section.content:
            new_line = False
            return ""
        sep = "\n" if new_line else " "
        new_line = False
        return sep

    def _emit_text_segment(page, parts: list[str], rects: list[list[float]]) -> None:
        """Append one page-tagged text segment. Rects stay per-block rather
        than unioned, for a finer coordinate highlight."""
        seg: dict = {"page": page, "kind": "text", "text": " ".join(parts)}
        if rects:
            seg["bbox"] = rects
        current_section.segments.append(seg)

    def _emit_footnotes() -> None:
        """Set the footnotes held on lines of their own, each a text segment
        marked as a footnote, so that a request of the harvest can read and
        quote it like any line (owner decision 2026-11-17)."""
        nonlocal held, new_line
        if current_section is None or not held:
            held = []
            return
        for text, page, rect in held:
            ts = text.strip()
            if not ts:
                continue
            current_section.content += \
                ("\n" if current_section.content else "") + ts
            seg: dict = {"page": page, "kind": "text", "text": ts,
                         "footnote": True}
            if rect is not None:
                seg["bbox"] = [rect]
            current_section.segments.append(seg)
            new_line = True
        held = []

    def _flush_text() -> None:
        """Flush pending fragments into the current section's content and
        segments; consecutive same-page fragments merge into one segment."""
        nonlocal pending
        if current_section is None or not pending:
            pending = []
            return
        joined = " ".join(t.strip() for (t, _p, _b) in pending if t.strip())
        if joined:
            current_section.content += _sep() + joined
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
        nonlocal current_section, new_line
        _flush_text()
        _emit_footnotes()
        new_line = False
        if current_section is not None:
            current_section.content = current_section.content.strip()
        new_section = Section(title=title, page_number=page_number)
        sections.append(new_section)
        current_section = new_section

    # What comes before the first heading. Its title is the profile's word:
    # it is stored, shown in a citation and read by the model.
    front = rules.get("front_section_title")
    # page_number=None, not 1: a leading cover/blank page can push real content
    # to page 2+, so the derivation step below sets it from the first segment.
    _open_section(front, page_number=None)

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
                _emit_footnotes()
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
                    current_section.content += _sep() + f"[{block.id}]"
                    ref.caption = resolve_title(ref.caption,
                                                current_section.content,
                                                block.id)
                    seg: dict = {"page": pg.page_number, "kind": "table", "ref": block.id}
                    if rect is not None:
                        seg["bbox"] = [rect]
                    current_section.segments.append(seg)
                continue

            if block.type == "image":
                _flush_text()
                _emit_footnotes()
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
                    current_section.content += _sep() + f"[{block.id}]"
                    ref.caption = resolve_title(ref.caption,
                                                current_section.content,
                                                block.id)
                    seg = {"page": pg.page_number, "kind": "figure", "ref": block.id}
                    if rect is not None:
                        seg["bbox"] = [rect]
                    current_section.segments.append(seg)
                continue

            if block.type == "text" and block.content and _block_is_footnote(block):
                # A footnote waits for the end of the sentence it stands
                # in, which a paragraph running on to the next page ends
                # there; at the end of a sentence it follows at once.
                held.append((block.content, pg.page_number, _rect(block.bbox)))
                if not pending or _ends_sentence(pending[-1][0]):
                    _flush_text()
                    _emit_footnotes()
                continue

            if block.type == "text" and block.content:
                pending.append((block.content, pg.page_number, _rect(block.bbox)))
                if held and _ends_sentence(block.content):
                    _flush_text()
                    _emit_footnotes()

    _flush_text()
    _emit_footnotes()
    if current_section is not None:
        current_section.content = current_section.content.strip()

    # Drop the synthetic front section when the document opened with a
    # real title and it stayed empty.
    if (
        sections
        and sections[0].title == front
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

def sections_to_dict(sections: list[Section],
                     title_page: Optional[int] = None) -> dict:
    """Serialises the section list into the final output JSON structure, which
    docpipe/schemas/sections.schema.json describes. *title_page* (see
    `title_page_of`) goes beside the sections for Stage 4, which does not read
    pages.json; readers that take `sections` alone ignore it."""
    out = {"version": SECTIONS_VERSION,
           "sections": [s.to_dict() for s in sections]}
    if title_page is not None:
        out["title_page"] = title_page
    return out



def save_output(sections: list[Section], output_dir: Path,
                title_page: Optional[int] = None) -> Path:
    """Writes the Stage 3 JSON under *output_dir* and returns its path."""
    out_path = output_dir / SECTIONS_JSON
    data     = clean_data(sections_to_dict(sections, title_page))
    dump_json_atomic(data, out_path)
    log.info(f"Stage 3: output written → {out_path}")
    return out_path