"""
status.py: `docpipe status`, which stage left what for each document.

    docpipe status

One line per document and one column per stage `docpipe run` starts, an x
where that stage's output for the document is there, then how many documents
each stage has output for. A document is every name the corpus knows: a row
of the database, a PDF in the profile's folder, a directory in its processed
folder.

"There" is what the stage itself calls done, asked of the stage's own code
where it has a function for it and of its own file names where the rule is
the file:

  ingest      a Documents row for the file (what ingest skips)
  preprocess  pages.json and sections.json (what preprocessing resumes on)
  refine      sections_refined.json, and no unfinished pass beside it
  visuals     visuals.json, and every table and figure of its input in it
              with the markdown or description the stage looks for
  chunk       document.json not older than its inputs, and an embedding
              recorded in the database for a section, table or figure of it
              (which takes its Sections rows)
  lexical     a word index that is current and holds a passage of it

Nothing here writes. The database and the word index are opened for reading
only, and a stage that has not run (no database, no processed folder) is a
column of dashes, not an error.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from .artifacts import (PAGES_JSON, REFINEMENT_PARTIAL_JSON, SECTIONS_JSON,
                        SECTIONS_REFINED_JSON, VISUALS_JSON)
from .profile import require_profile
from .run import STAGES

PDF_GLOB = "*.pdf"           # what preprocessing takes from a folder
PDF_SUFFIX = ".pdf"
# What the checks below ask the database; one without them has no rows.
CORE_TABLES = {"Documents", "Sections", "Tables", "Images", "Embeddings"}


@dataclass
class Report:
    profile: str
    root: Path
    database: Path
    documents: list = field(default_factory=list)
    # stage -> the documents it has output for
    there: dict = field(default_factory=dict)
    # current, stale or missing: the word index belongs to the corpus
    word_index: str = "missing"

    def count(self, stage: str) -> int:
        return len(self.there[stage])


def key_of(filename: str) -> str:
    """The name a document's processed directory has: its file name without
    the suffix, as chunking looks a directory up in the database."""
    if filename.lower().endswith(PDF_SUFFIX):
        return filename[:-len(PDF_SUFFIX)]
    return filename


def _open(path: Path) -> Optional[sqlite3.Connection]:
    """The database for reading only, or None where there is none (a stage
    that has not run is not an error, and opening would create the file)."""
    from .store import schema
    if not Path(path).is_file():
        return None
    return sqlite3.connect(schema.readonly_uri(path), uri=True)


def _documents(profile, connection, tables: set) -> dict:
    """Every document of the corpus: its key, and the file names it is known
    by (a row's name, a PDF's name), which ingest looks a row up by."""
    named: dict = {}
    if connection is not None and "Documents" in tables:
        for (filename,) in connection.execute(
                'SELECT "filename" FROM "Documents"'):
            named.setdefault(key_of(filename), set()).add(filename)
    pdfs = Path(profile.pdf_dir)
    if pdfs.is_dir():
        for path in pdfs.glob(PDF_GLOB):
            if path.is_file():
                named.setdefault(key_of(path.name), set()).add(path.name)
    processed = Path(profile.processed_dir)
    if processed.is_dir():
        for path in processed.iterdir():
            if path.is_dir():
                named.setdefault(path.name, set())
    return named


def _visuals_there(folder: Path, visuals) -> bool:
    """visuals.json is there and every table and figure of the input the
    stage would read has what the stage looks for before it asks again."""
    output = folder / VISUALS_JSON
    source = visuals._resolve_input(folder)
    if not output.exists() or source is None:
        return False
    try:
        cached: dict = {}
        with open(output, encoding="utf-8") as handle:
            visuals.collect_cached(json.load(handle), cached)
        with open(source, encoding="utf-8") as handle:
            data = json.load(handle)
        return all(item["id"] in cached
                   for section in data["sections"]
                   for kind in ("tables", "figures")
                   for item in section.get(kind, []))
    except (OSError, ValueError, KeyError, AttributeError, TypeError):
        return False


def _indexed_documents(db: Path):
    """(state of the word index, the document ids it holds a passage of)."""
    from .inference import lexical
    state = lexical.state(db) if Path(db).is_file() else "missing"
    if state != "current":
        return state, set()
    from .store import schema
    index = sqlite3.connect(schema.readonly_uri(lexical.path_for(db)),
                            uri=True)
    try:
        return state, {row[0] for row in index.execute(
            'SELECT DISTINCT "document" FROM "passages"')}
    finally:
        index.close()


def collect(profile) -> Report:
    """What each stage has left for each document of *profile*."""
    # The stages bind what the profile says when they are imported, so after it
    # is settled and not before.
    from .chunking import database, merge
    from .refinement import refine
    from .store import documents as registry
    from .store import schema
    from .visuals import pipeline as visuals

    processed = Path(profile.processed_dir)
    report = Report(profile=profile.name, root=Path(profile.root),
                    database=Path(profile.db_path),
                    there={stage: set() for stage in STAGES})
    connection = _open(report.database)
    try:
        tables = schema.tables(connection) if connection is not None else set()
        # A database that only ingest has touched has the rows of the
        # documents and no more, and that is ingest's output.
        registered = connection is not None and "Documents" in tables
        built = connection is not None and CORE_TABLES <= tables
        named = _documents(profile, connection, tables)
        report.documents = sorted(named)
        report.word_index, indexed = _indexed_documents(report.database)
        for key in report.documents:
            folder = processed / key
            row = (database._resolve_document_id(key, connection)
                   if registered else None)
            there = {
                # by the name a file or a row has, not only by the key plus
                # ".pdf": ingest skips a row registered as "Plan.PDF" too
                "ingest": registered and any(
                    registry.document_exists(name, connection)
                    for name in (*sorted(named[key]), key + PDF_SUFFIX, key)),
                "preprocess": ((folder / PAGES_JSON).exists()
                               and (folder / SECTIONS_JSON).exists()),
                "refine": ((folder / SECTIONS_REFINED_JSON).exists()
                           and refine._read_partial(
                               folder / REFINEMENT_PARTIAL_JSON) is None),
                "visuals": _visuals_there(folder, visuals),
                "chunk": (built and row is not None
                          and merge._is_cached(folder)
                          and any(connection.execute(sql, (row,)).fetchone()
                                  for sql in (database._EXISTING_SECTION_SQL,
                                              database._EXISTING_TABLE_SQL,
                                              database._EXISTING_FIGURE_SQL))),
                "lexical": row is not None and row in indexed,
            }
            for stage in STAGES:
                if there[stage]:
                    report.there[stage].add(key)
    finally:
        if connection is not None:
            connection.close()
    return report


def render(report: Report) -> str:
    total = len(report.documents)
    lines = [f"profile {report.profile}, data in {report.root}"]
    if not total:
        lines.append(f"no document found in {report.database}, nor in the "
                     f"PDF folder or the processed folder beside it")
    else:
        width = max(len("document"), *(len(key) for key in report.documents))
        lines.append("  ".join(["document".ljust(width), *STAGES]))
        for key in report.documents:
            marks = ["x" if key in report.there[stage] else "-"
                     for stage in STAGES]
            lines.append("  ".join([key.ljust(width), *(
                mark.ljust(len(stage)) for mark, stage in zip(marks, STAGES))]
            ).rstrip())
    lines.append("")
    width = max(len(stage) for stage in STAGES)
    for stage in STAGES:
        lines.append(f"{stage.ljust(width)}  {report.count(stage)} of "
                     f"{total} document(s) have its output")
    lines.append(f"word index: {report.word_index}")
    lines.append("x: the stage's output for the document is there; "
                 "-: it is not")
    return "\n".join(lines)


def main(rest: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="docpipe status",
        description="For the profile in effect: one line per document, one "
                    "column per stage of `docpipe run`, an x where the "
                    "stage's output for the document is there, and how many "
                    "documents each stage has output for. Changes nothing.")
    parser.parse_args(list(rest))
    profile = require_profile()
    try:
        report = collect(profile)
    except sqlite3.DatabaseError as exc:
        raise SystemExit(f"{profile.db_path} cannot be read: {exc}")
    print(render(report))
    return 0
