"""
chunking.py: Builds embedding inputs from merged section data.

The entries of the index are the pieces the harvest reads (owner decisions
2026-11-17, `pieces.py`): for each section its title, and its pieces, each
its heading and its lines; for each table and figure its pieces, each a text
input and, when its picture exists on disk, a vision-language input of the
picture and the same text. A table or figure placeholder inside a section's
text is named by the item's caption, as the harvest shows it.

Every input knows which piece of its owner it is, its own first and last
line and its page. Nothing is cut: an input that does not fit the
embedder's window is split into parts, each with the lines its piece
carries (`fit_inputs`, `docpipe.window`).

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from .config import (
    EMBEDDING_TYPE_SECTION_TEXT,
    EMBEDDING_TYPE_SECTION_TITLE,
    EMBEDDING_TYPE_TABLE_TEXT,
    EMBEDDING_TYPE_TABLE_VL,
    EMBEDDING_TYPE_FIGURE_TEXT,
    EMBEDDING_TYPE_FIGURE_VL,
)

log = logging.getLogger(__name__)


@dataclass
class EmbeddingInput:
    """A single item to be embedded; ``image`` is set only for VL inputs.

    *piece* is which piece of its owner it is, as the harvest counts them
    (0 for a section's title), *part* which part of that piece where the
    piece did not fit the embedder's window; *page* the page its first own
    line stands on, *first_line* and *last_line* its own lines as the
    harvest numbers its passage (None for a title, or a piece of carried
    lines only). *unit* is the piece it was made of, for splitting it."""
    embedding_type: str
    pdf_name: str
    section_index: int
    item_id: Optional[str]
    text: str
    image: Optional[str] = None
    piece: Optional[int] = None
    part: int = 0
    page: Optional[int] = None
    first_line: Optional[int] = None
    last_line: Optional[int] = None
    unit: object = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> tuple:
        """What names it among a document's inputs."""
        return (self.embedding_type, self.section_index, self.item_id,
                self.piece, self.part)


def _dir_names(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    """Entry names of `path`; each directory is read at most once per `cache`."""
    names = cache.get(path)
    if names is None:
        try:
            names = set(os.listdir(path))
        # Only a genuinely absent directory is "no crops". A permission or I/O
        # error must still raise: swallowing it would drop every VL input of the
        # document without a trace, which is what Path.exists() also refused to do.
        except (FileNotFoundError, NotADirectoryError):
            names = set()
        cache[path] = names
    return names


def _picture(item: dict, kind: str, pdf_name: str, output_dir: Path,
             listings: dict) -> Optional[str]:
    """The path of the picture of a table or figure where it is on disk,
    else None."""
    # An item without a path would make output_dir / "" == output_dir,
    # whose .name is the document folder — which then gets embedded as
    # if it were the table image. Stage 4 re-emits tables and can drop
    # the field, so this is reachable, not defensive.
    rel_path = item.get("path") or ""
    if not rel_path:
        log.warning("%s %s in %s has no image path — no VL vector", kind,
                    item.get("id"), pdf_name)
        return None
    image_path = output_dir / rel_path
    if image_path.name in _dir_names(image_path.parent, listings):
        return str(image_path)
    return None


def _of_piece(piece, embedding_type: str, pdf_name: str, sec_idx: int,
              item_id: Optional[str], image: Optional[str] = None
              ) -> EmbeddingInput:
    first, last = piece.first_last()
    return EmbeddingInput(
        embedding_type=embedding_type, pdf_name=pdf_name,
        section_index=sec_idx, item_id=item_id, text=piece.text(),
        image=image, piece=piece.index, part=0, page=piece.page_of(),
        first_line=first, last_line=last, unit=piece)


def build_embedding_inputs(
    merged_data: dict,
    pdf_name: str,
    output_dir: Path,
    *,
    log_counts: bool = True,
    size: Optional[int] = None,
    resolve: Optional[Callable] = None,
) -> list[EmbeddingInput]:
    """
    Build the section/table/figure embedding inputs (text + VL), one per
    piece, for one PDF; each whole, before any split (`fit_inputs`).

    `output_dir` is the base for resolving each item's image path; VL inputs are
    only emitted for images that exist on disk. Returns [] if nothing qualifies.
    `log_counts` False leaves out the line that counts them, for a caller that
    builds them only to compare (chunking/sync.py). *size* is the lines of a
    piece, the flow's `piece_lines` where not given. *resolve* gives a table's
    or figure's caption as the database holds it (`pieces.captions_of`); a
    caller whose document already holds those passes `pieces.as_held`.
    """
    from docpipe import rules
    from .context import lead_of
    from .pieces import (captions_of, item_pieces, piece_lines,
                         section_pieces)
    size = piece_lines() if size is None else int(size)
    # What of a document the index holds (the rules embed_section_titles,
    # embed_item_texts, embed_item_pictures).
    with_titles = bool(rules.get("embed_section_titles"))
    texts_of = set(rules.get("embed_item_texts"))
    pictures_of = set(rules.get("embed_item_pictures"))
    inputs: list[EmbeddingInput] = []
    # One directory listing per crop directory instead of a stat() per crop: the
    # corpus holds ~85k crops and metadata calls dominate on a parallel filesystem.
    listings: dict[Path, set[str]] = {}

    for sec_idx, section in enumerate(merged_data.get("sections", [])):
        title = (section.get("title", "") or "").strip()
        captions = captions_of(section, resolve)

        for piece in section_pieces(section, captions, size):
            inputs.append(_of_piece(piece, EMBEDDING_TYPE_SECTION_TEXT,
                                    pdf_name, sec_idx, None))

        if title and with_titles:
            inputs.append(EmbeddingInput(
                embedding_type=EMBEDDING_TYPE_SECTION_TITLE,
                pdf_name=pdf_name, section_index=sec_idx, item_id=None,
                text=title, piece=0, page=section.get("page_number")))

        for kind, items, text_type, vl_type in (
                ("table", section.get("tables") or [],
                 EMBEDDING_TYPE_TABLE_TEXT, EMBEDDING_TYPE_TABLE_VL),
                ("figure", section.get("figures") or [],
                 EMBEDDING_TYPE_FIGURE_TEXT, EMBEDDING_TYPE_FIGURE_VL)):
            for item in items:
                pieces = item_pieces(kind, section, item, captions, size,
                                     lead_of)
                if kind in texts_of:
                    for piece in pieces:
                        inputs.append(_of_piece(piece, text_type, pdf_name,
                                                sec_idx, item["id"]))
                if kind not in pictures_of:
                    continue
                image = _picture(item, kind, pdf_name, output_dir, listings)
                if image is None:
                    continue
                if not pieces:
                    # A picture with neither caption nor text is its picture
                    # alone, as it always was.
                    inputs.append(EmbeddingInput(
                        embedding_type=vl_type, pdf_name=pdf_name,
                        section_index=sec_idx, item_id=item["id"], text="",
                        image=image, piece=0, page=item.get("page_number")))
                    continue
                for piece in pieces:
                    inputs.append(_of_piece(piece, vl_type, pdf_name,
                                            sec_idx, item["id"], image))

    if not log_counts:
        return inputs
    log.info(
        "Built %d embedding inputs for '%s' "
        "(sections: %d text + %d title, "
        "tables: %d text + %d vl, "
        "figures: %d text + %d vl)",
        len(inputs), pdf_name,
        sum(1 for i in inputs if i.embedding_type == EMBEDDING_TYPE_SECTION_TEXT),
        sum(1 for i in inputs if i.embedding_type == EMBEDDING_TYPE_SECTION_TITLE),
        sum(1 for i in inputs if i.embedding_type == EMBEDDING_TYPE_TABLE_TEXT),
        sum(1 for i in inputs if i.embedding_type == EMBEDDING_TYPE_TABLE_VL),
        sum(1 for i in inputs if i.embedding_type == EMBEDDING_TYPE_FIGURE_TEXT),
        sum(1 for i in inputs if i.embedding_type == EMBEDDING_TYPE_FIGURE_VL),
    )

    return inputs


def fit_inputs(inputs: list, fits: Callable[[str, Optional[str]], bool],
               unfit: Optional[Callable] = None) -> list:
    """*inputs* each split into the parts that fit the embedder's window:
    *fits(text, picture)* says whether a text with its picture fits. An
    input that fits is kept as it is (part 0); one that does not is split
    by its piece (`pieces.IndexPiece.parts`), each part with every line its
    piece carries, the parts numbered from 0 with their own lines and the
    page of their first line. An input without a piece to split by, or
    whose carried lines alone do not fit (`window.TooLong`), is handed to
    *unfit(input, reason)* and left out: it is never cut."""
    from docpipe.window import TooLong
    out: list = []
    for inp in inputs:
        if fits(inp.text, inp.image):
            out.append(inp)
            continue
        piece = inp.unit
        name = (f"{inp.pdf_name} {inp.embedding_type} section "
                f"{inp.section_index} {inp.item_id or ''} piece {inp.piece}")
        if piece is None or not hasattr(piece, "parts"):
            reason = f"{name}: does not fit the window and is no piece to split"
            if unfit is not None:
                unfit(inp, reason)
            continue
        try:
            parts = piece.parts(lambda text: fits(text, inp.image), name)
        except TooLong as exc:
            if unfit is not None:
                unfit(inp, str(exc))
            continue
        for at, part in enumerate(parts):
            numbers = part.numbers
            out.append(replace(
                inp, text=part.text, part=at,
                page=piece.page_of(numbers) if numbers else inp.page,
                first_line=part.first, last_line=part.last))
        log.info("%s: split into %d parts to fit the window", name,
                 len(parts))
    return out
