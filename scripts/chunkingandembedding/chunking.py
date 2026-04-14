"""
chunking.py – Build embedding inputs from merged section data.

Transforms sections into embedding-ready text chunks and VL inputs
by replacing placeholders with enriched content.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import (
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
    """
    A single item to be embedded.

    For text-only embeddings only ``text`` is set.
    For VL embeddings both ``text`` and ``image`` are set.
    """
    embedding_type: str
    pdf_name: str
    section_index: int
    item_id: Optional[str]
    text: str
    image: Optional[str] = None


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
    Replace [p13_tbl0]-style placeholders in section content with
    the caption + markdown/description of the referenced item.
    """
    def _replacer(match: re.Match) -> str:
        item_id = match.group(1)
        item = lookup.get(item_id)
        if item is None:
            return match.group(0)

        parts = []
        caption = item.get("caption", "")
        if caption:
            parts.append(caption)

        markdown = item.get("markdown", "")
        description = item.get("description", "")
        if markdown:
            parts.append(markdown)
        elif description:
            parts.append(description)

        return "\n".join(parts) if parts else match.group(0)

    return _PLACEHOLDER_RE.sub(_replacer, content)


def build_embedding_inputs(
    merged_data: dict,
    pdf_name: str,
    output_dir: Path,
) -> list[EmbeddingInput]:
    """
    Build all embedding inputs for one PDF from its merged data.

    Produces 6 types of embeddings per applicable item:
      1. section_text:   title + content (placeholders replaced)
      2. section_title:  title alone
      3. table_text:     caption + markdown
      4. table_vl:       image + caption + markdown
      5. figure_text:    caption + description
      6. figure_vl:      image + caption + description

    Args:
        merged_data: The merged output.json data.
        pdf_name:    PDF identifier (directory name).
        output_dir:  Base path for resolving image file paths.

    Returns:
        List of EmbeddingInput objects ready for the embedding model.
    """
    inputs: list[EmbeddingInput] = []

    for sec_idx, section in enumerate(merged_data.get("sections", [])):
        title = section.get("title", "") or ""
        content = section.get("content", "") or ""
        if isinstance(content, list):
            content = "\n".join(str(c) for c in content)
        item_lookup = _build_item_lookup(section)

        enriched_content = _replace_placeholders(content, item_lookup)
        section_text = (title + "\n" + enriched_content).strip()

        if section_text:
            inputs.append(EmbeddingInput(
                embedding_type=EMBEDDING_TYPE_SECTION_TEXT,
                pdf_name=pdf_name,
                section_index=sec_idx,
                item_id=None,
                text=section_text,
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

            image_path = output_dir / t.get("path", "")
            if image_path.exists():
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

            image_path = output_dir / fig.get("path", "")
            if image_path.exists():
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