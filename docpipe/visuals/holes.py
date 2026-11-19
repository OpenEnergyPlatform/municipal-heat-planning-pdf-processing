"""
holes.py: The tables and figures of a document that have no content after
Stage 5, and why (owner request 2026-11-19).

What Stage 5 could not read stood only in its own file and in one line of the
merge's log: the document went into the database, the index and the harvest
as if it were whole, and a value only such a table holds ended "not stated in
the document". Now the merge writes them into the document (document.json,
"holes"), the database keeps them beside it (Documents.holes), the harvest
reads them (a value still open in such a document is no finding about the
document, rule `state_rules`) and its stamp records them, so that a hole
filled later makes the document work again. A job counts them (`count`, the
command line's `--count-holes`) to know whether another pass of Stage 5
filled any.

Author: Felix Vossel
"""
from __future__ import annotations

import json
from pathlib import Path

# The cause of a hole where Stage 5 sent no request for the item: there is no
# visuals.json, it has no entry for the item, or the item's image is missing.
NOT_ASKED = "not_asked"

# What holds an item's content, by kind.
CONTENT = {"table": "markdown", "figure": "description"}


def of(sections: list, enriched: dict) -> list:
    """[{"id", "kind", "page", "why"}] of the tables and figures of
    *sections* (what Stage 5 and the merge read) that have no content in
    *enriched* (visuals.json as read; {} where there is none): a table
    without markdown, a figure without description, in reading order. "why"
    is the cause Stage 5 gave the item (`vlm_why`), else NOT_ASKED."""
    written: dict = {}
    for section in (enriched or {}).get("sections") or []:
        for key in ("tables", "figures"):
            for item in section.get(key) or []:
                if isinstance(item, dict):
                    written[item.get("id")] = item
    out: list = []
    for section in sections or []:
        for kind, key in (("table", "tables"), ("figure", "figures")):
            for item in section.get(key) or []:
                if not isinstance(item, dict):
                    continue
                got = written.get(item.get("id")) or {}
                if got.get(CONTENT[kind]):
                    continue
                out.append({"id": item.get("id"), "kind": kind,
                            "page": item.get("page_number",
                                             section.get("page_number")),
                            "why": got.get("vlm_why") or NOT_ASKED})
    return out


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def of_document(output_dir) -> list:
    """`of` for one document folder: the input Stage 5 reads there (the
    refined sections, else the sections) against its visuals.json; [] where
    it has neither input."""
    from docpipe.artifacts import (SECTIONS_JSON, SECTIONS_REFINED_JSON,
                                   VISUALS_JSON)
    output_dir = Path(output_dir)
    for name in (SECTIONS_REFINED_JSON, SECTIONS_JSON):
        data = _read(output_dir / name)
        if isinstance(data, dict):
            break
    else:
        return []
    enriched = _read(output_dir / VISUALS_JSON)
    return of(data.get("sections") or [],
              enriched if isinstance(enriched, dict) else {})


def count(root) -> tuple:
    """(tables, figures, documents) without content under *root*, a document
    folder or a folder of them, by `of_document`."""
    from docpipe.artifacts import (SECTIONS_JSON, SECTIONS_REFINED_JSON,
                                   document_dirs)
    root = Path(root)
    own = any((root / name).exists()
              for name in (SECTIONS_REFINED_JSON, SECTIONS_JSON))
    folders = [root] if own else document_dirs(
        root, SECTIONS_REFINED_JSON, SECTIONS_JSON)
    tables = figures = documents = 0
    for folder in folders:
        found = of_document(folder)
        tables += sum(1 for h in found if h["kind"] == "table")
        figures += sum(1 for h in found if h["kind"] == "figure")
        documents += bool(found)
    return tables, figures, documents
