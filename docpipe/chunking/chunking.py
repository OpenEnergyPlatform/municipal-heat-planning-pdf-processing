"""
chunking.py: Builds embedding inputs from merged section data.

For each section, produces a text input and, when the section has a
title, a title input; for each table and figure, a text input and,
when its image file exists on disk, a vision-language input. Table
and figure placeholders inside a section's text are replaced by the
referenced item's caption before the section is embedded. A section
longer than the configured word budget is truncated, and the cut is
logged rather than left silent.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import (
    SECTION_EMBED_MAX_WORDS,
    EMBEDDING_TYPE_SECTION_TEXT,
    EMBEDDING_TYPE_SECTION_TITLE,
    EMBEDDING_TYPE_TABLE_TEXT,
    EMBEDDING_TYPE_TABLE_VL,
    EMBEDDING_TYPE_FIGURE_TEXT,
    EMBEDDING_TYPE_FIGURE_VL,
)

log = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\[([a-z0-9_]+)\]")


@dataclass
class EmbeddingInput:
    """A single item to be embedded; ``image`` is set only for VL inputs."""
    embedding_type: str
    pdf_name: str
    section_index: int
    item_id: Optional[str]
    text: str
    image: Optional[str] = None


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


def _capped(text: str, pdf_name: str, sec_idx: int) -> str:
    """
    Last line of defence against a section that is too long to embed.

    Refinement splits oversized sections (docpipe.refinement.split), so this
    should not trigger. When it does, the cut is reported rather than silent —
    a quietly truncated vector is a section whose tail is simply not searchable.
    """
    words = text.split()
    if len(words) <= SECTION_EMBED_MAX_WORDS:
        return text
    log.warning(
        "%s section %d: %d words exceeds the embedding budget of %d — truncated. "
        "Refinement should have split this section.",
        pdf_name, sec_idx, len(words), SECTION_EMBED_MAX_WORDS,
    )
    return " ".join(words[:SECTION_EMBED_MAX_WORDS])


def _build_item_lookup(section: dict) -> dict[str, dict]:
    """Build a placeholder-id to item dict from a section's tables and figures."""
    lookup: dict[str, dict] = {}
    for t in section.get("tables", []):
        lookup[t["id"]] = t
    for f in section.get("figures", []):
        lookup[f["id"]] = f
    return lookup


def _replace_placeholders(content: str, lookup: dict[str, dict]) -> str:
    """
    Replace [p13_tbl0]-style placeholders in section content with the CAPTION of
    the referenced item — what the section says about it, not the item itself.

    The table's rows and the figure's description are embedded separately, as
    table_text/table_vl and figure_text/figure_vl, and are retrieved as their
    own sources. Pulling them in here as well used to make up 46% of the whole
    section-text corpus: it diluted every section vector, pushed the longest
    sections past the model's token limit, and promised content the section
    itself cannot deliver — what the answering LLM later reads is the stored
    content, where the placeholder is still a placeholder.
    """
    def _replacer(match: re.Match) -> str:
        item = lookup.get(match.group(1))
        if item is None:
            return match.group(0)
        return (item.get("caption") or "").strip() or match.group(0)

    return _PLACEHOLDER_RE.sub(_replacer, content)


def build_embedding_inputs(
    merged_data: dict,
    pdf_name: str,
    output_dir: Path,
) -> list[EmbeddingInput]:
    """
    Build the section/table/figure embedding inputs (text + VL) for one PDF.

    `output_dir` is the base for resolving each item's image path; VL inputs are
    only emitted for images that exist on disk. Returns [] if nothing qualifies.
    """
    inputs: list[EmbeddingInput] = []
    # One directory listing per crop directory instead of a stat() per crop: the
    # corpus holds ~85k crops and metadata calls dominate on a parallel filesystem.
    listings: dict[Path, set[str]] = {}

    for sec_idx, section in enumerate(merged_data.get("sections", [])):
        title = section.get("title", "") or ""
        content = section.get("content", "") or ""
        if isinstance(content, list):
            content = "\n".join(str(c) for c in content)
        item_lookup = _build_item_lookup(section)

        labelled_content = _replace_placeholders(content, item_lookup)
        section_text = (title + "\n" + labelled_content).strip()

        # A section whose text is nothing but its title would only duplicate the
        # section_title vector below.
        if section_text and section_text != title.strip():
            inputs.append(EmbeddingInput(
                embedding_type=EMBEDDING_TYPE_SECTION_TEXT,
                pdf_name=pdf_name,
                section_index=sec_idx,
                item_id=None,
                text=_capped(section_text, pdf_name, sec_idx),
            ))

        if title:
            inputs.append(EmbeddingInput(
                embedding_type=EMBEDDING_TYPE_SECTION_TITLE,
                pdf_name=pdf_name,
                section_index=sec_idx,
                item_id=None,
                text=title,
            ))

        for t in section.get("tables", []):
            caption = t.get("caption", "") or ""
            markdown = t.get("markdown", "") or ""
            table_text = (caption + "\n" + markdown).strip()

            if table_text:
                inputs.append(EmbeddingInput(
                    embedding_type=EMBEDDING_TYPE_TABLE_TEXT,
                    pdf_name=pdf_name,
                    section_index=sec_idx,
                    item_id=t["id"],
                    text=table_text,
                ))

            # An item without a path would make output_dir / "" == output_dir,
            # whose .name is the document folder — which then gets embedded as
            # if it were the table image. Stage 4 re-emits tables and can drop
            # the field, so this is reachable, not defensive.
            rel_path = t.get("path") or ""
            if not rel_path:
                log.warning("table %s in %s has no image path — no VL vector",
                            t.get("id"), pdf_name)
                continue
            image_path = output_dir / rel_path
            if image_path.name in _dir_names(image_path.parent, listings):
                inputs.append(EmbeddingInput(
                    embedding_type=EMBEDDING_TYPE_TABLE_VL,
                    pdf_name=pdf_name,
                    section_index=sec_idx,
                    item_id=t["id"],
                    text=table_text or caption,
                    image=str(image_path),
                ))

        for fig in section.get("figures", []):
            caption = fig.get("caption", "") or ""
            description = fig.get("description", "") or ""
            figure_text = (caption + "\n" + description).strip()

            if figure_text:
                inputs.append(EmbeddingInput(
                    embedding_type=EMBEDDING_TYPE_FIGURE_TEXT,
                    pdf_name=pdf_name,
                    section_index=sec_idx,
                    item_id=fig["id"],
                    text=figure_text,
                ))

            rel_path = fig.get("path") or ""      # same trap as tables above
            if not rel_path:
                log.warning("figure %s in %s has no image path — no VL vector",
                            fig.get("id"), pdf_name)
                continue
            image_path = output_dir / rel_path
            if image_path.name in _dir_names(image_path.parent, listings):
                inputs.append(EmbeddingInput(
                    embedding_type=EMBEDDING_TYPE_FIGURE_VL,
                    pdf_name=pdf_name,
                    section_index=sec_idx,
                    item_id=fig["id"],
                    text=figure_text or caption,
                    image=str(image_path),
                ))

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