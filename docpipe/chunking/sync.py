"""
sync.py: Writes documents processed again into the database under the
numbers their entries already have, and takes out of every index the
vectors whose input changed.

A plan whose tables were transcribed again, or whose sections were refined
again, used to go back into the database with --force: its sections, tables
and figures were deleted and inserted under new numbers, and all its vectors
were embedded again. A harvest, its found places and an index built under
the database's ids then no longer fit it. Here (owner decision 2026-11-07,
"Nur Geändertes neu") an entry keeps its number:

- a section keeps its row where the new document has a section with the
  same title and text, in the order of the sections; where a stretch of
  sections changed, its new sections take the rows of the old ones of that
  stretch in their order, and the rest are new or gone;
- a table or a figure keeps its row by its block id, in order where one id
  stands more than once, and moves with it to the section it now stands in;
- a table part the merge joined to the table it continues is gone.

A vector stays where its input is unchanged: the text, and the picture, that
`chunking.build_embedding_inputs` makes of the entry, from the database
before and from the document now, each with the caption the database holds
(`captions.resolve_title`, which `enrich_caption` applies). Every other
vector goes: its Embeddings row is deleted and its id taken out of every
index named. The embed step then embeds each input that has no row, and a
re-embedding (chunking/reembed.py) fills each further index, built under the
same ids, with the ids it lacks.

The indexes are written first and the database after, document by document.
A run that dies in between leaves rows whose vector is gone, which the embed
step drops and embeds again; a second run finds the changes still to be
written and writes them.

Author: Felix Vossel
"""
from __future__ import annotations

import copy
import difflib
import json
import logging
import os
from collections import Counter, defaultdict, deque
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from docpipe.artifacts import document_dirs
from docpipe.captions import resolve_title

from .chunking import build_embedding_inputs
from .config import DOCUMENT_JSON
from .database import (_FIGURE_TYPES, _SECTION_TYPES, _TABLE_TYPES,
                       _ensure_bbox_columns, _ensure_caption_source_column,
                       _ensure_table_qa_column, _resolve_document_id, connect,
                       enrich_page_source, image_values, insert_provenance,
                       page_rows, section_content, segment_rows, table_values)
from .reembed import record_path

log = logging.getLogger(__name__)

TABLE_FIELDS = ("id", "section", "block_id", "path", "page_number", "caption",
                "markdown", "bbox", "qa", "caption_source")
IMAGE_FIELDS = ("id", "section", "block_id", "path", "page_number", "caption",
                "description", "bbox", "caption_source")

# The vectors of one document, by owner. CROSS JOIN drives from Sections,
# as in database.py.
_EMBEDDINGS_SQL = (
    "SELECT 'section', s.id, e.embedding_type, e.faiss_id "
    "FROM Sections s CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'section' AND e.owner_id = s.id WHERE s.document = ? "
    "UNION ALL "
    "SELECT 'table', t.id, e.embedding_type, e.faiss_id "
    "FROM Sections s CROSS JOIN Tables t ON t.section = s.id "
    "CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'table' AND e.owner_id = t.id WHERE s.document = ? "
    "UNION ALL "
    "SELECT 'figure', i.id, e.embedding_type, e.faiss_id "
    "FROM Sections s CROSS JOIN Images i ON i.section = s.id "
    "CROSS JOIN Embeddings e "
    "  ON e.owner_kind = 'figure' AND e.owner_id = i.id WHERE s.document = ?"
)

Resolve = Callable[[Optional[str], str, Optional[str]], Optional[str]]


def align(old: list, new: list) -> list:
    """For each entry of *new*, the index of the entry of *old* whose row it
    takes, or None: equal entries in order keep theirs, and in a stretch where
    the two differ the new ones take the old ones' rows in their order."""
    rows: list = [None] * len(new)
    matcher = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("equal", "replace"):
            for k in range(min(i2 - i1, j2 - j1)):
                rows[j1 + k] = i1 + k
    return rows


def pair(old_rows: list, new_items: list) -> tuple:
    """([(section index, item, old row or None)], [old rows no item takes]):
    each new item takes the next old row of its block id."""
    queue: dict = defaultdict(deque)
    for row in old_rows:
        queue[row["block_id"]].append(row)
    pairs = []
    for index, item in new_items:
        waiting = queue.get(item.get("id"))
        pairs.append((index, item, waiting.popleft() if waiting else None))
    return pairs, [row for waiting in queue.values() for row in waiting]


def _item_rows(conn, table: str, fields: tuple, doc_id: int) -> list:
    """One document's Tables or Images rows in reading order, as dicts; a
    column a database predates reads NULL."""
    have = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
    columns = ", ".join(f"t.{name}" if name in have else f"NULL AS {name}"
                        for name in fields)
    return [dict(zip(fields, row)) for row in conn.execute(
        f"SELECT {columns} FROM Sections s CROSS JOIN {table} t "
        "ON t.section = s.id WHERE s.document = ? "
        "ORDER BY s.section_number, t.id", (doc_id,))]


def _with_captions(document: dict, resolve: Resolve) -> dict:
    """A copy of a merged document whose tables and figures carry the
    caption the database holds for them, the stage's own kept beside it."""
    out = copy.deepcopy(document)
    for section in out.get("sections", []):
        content = section_content(section)
        for item in (section.get("tables") or []) + (section.get("figures") or []):
            stage = item.get("caption")
            item["stage_caption"] = stage
            item["caption"] = resolve(stage, content, item.get("id"))
    return out


def _source(item: dict) -> str:
    """What `enrich_caption` records for an item's caption."""
    return "stage" if item.get("caption") == item.get("stage_caption") else "section_text"


@dataclass
class Plan:
    """What writing one document again changes, before anything is written."""
    name: str
    doc_id: int
    new: dict
    rows: list                     # per new section: the row it keeps, or None
    gone_sections: list
    tables: list                   # [(section index, item, old row or None)]
    gone_tables: list
    figures: list
    gone_figures: list
    provenance: set                # new sections whose pages or segments are written
    renumbered: bool
    drop: dict                     # faiss id -> embedding type, of every vector that goes
    kept: int
    counts: dict

    @property
    def writes(self) -> bool:
        return bool(self.drop or self.gone_sections or self.gone_tables
                    or self.gone_figures or self.provenance or self.renumbered
                    or any(c["changed"] or c["new"] for c in self.counts.values()))


def _owner_inputs(document: dict, name: str, pdf_dir: Path, sections: list,
                  tables: dict, figures: dict) -> dict:
    """{(owner kind, row id, embedding type): (text, picture)} of a document's
    embedding inputs, for the entries that have a row: *sections* gives the
    row of each section index, *tables* and *figures* the row of each
    (section index, block id)."""
    out: dict = {}
    for inp in build_embedding_inputs(document, name, pdf_dir, log_counts=False):
        if inp.embedding_type in _SECTION_TYPES:
            kind, row = "section", sections[inp.section_index]
        elif inp.embedding_type in _TABLE_TYPES:
            kind, row = "table", tables.get((inp.section_index, inp.item_id))
        elif inp.embedding_type in _FIGURE_TYPES:
            kind, row = "figure", figures.get((inp.section_index, inp.item_id))
        else:
            continue
        if row is not None:
            out.setdefault((kind, row, inp.embedding_type), (inp.text, inp.image))
    return out


def plan_document(conn, doc_id: int, name: str, merged: dict, pdf_dir: Path,
                  resolve: Resolve = resolve_title) -> Plan:
    """What writing *merged* over the rows of document *doc_id* changes."""
    new = _with_captions(merged, resolve)
    sections = new.get("sections", [])
    old = conn.execute("SELECT id, title, content, page_number FROM Sections "
                       "WHERE document = ? ORDER BY section_number",
                       (doc_id,)).fetchall()
    old_ids = [row[0] for row in old]
    rows_at = align([(row[1] or "", row[2] or "") for row in old],
                    [(s.get("title") or "", section_content(s) or "")
                     for s in sections])
    rows = [old_ids[k] if k is not None else None for k in rows_at]
    kept_ids = {row for row in rows if row is not None}
    gone_sections = [row for row in old_ids if row not in kept_ids]
    by_id = {row[0]: row for row in old}

    pages: dict = defaultdict(list)
    for section, page in conn.execute(
            "SELECT sp.section, p.page_number FROM Sections s "
            "CROSS JOIN SectionPages sp ON sp.section = s.id "
            "JOIN Pages p ON p.id = sp.page WHERE s.document = ?", (doc_id,)):
        pages[section].append(page)
    segments: dict = defaultdict(list)
    for section, *rest in conn.execute(
            "SELECT sg.section, sg.ordinal, p.page_number, sg.kind, sg.ref, "
            "sg.text, sg.bbox FROM Sections s CROSS JOIN Segments sg "
            "ON sg.section = s.id JOIN Pages p ON p.id = sg.page "
            "WHERE s.document = ? ORDER BY sg.section, sg.ordinal", (doc_id,)):
        segments[section].append(tuple(rest))

    counts = {kind: Counter() for kind in ("sections", "tables", "figures")}
    provenance: set = set()
    for at, (section, row) in enumerate(zip(sections, rows)):
        if row is None:
            counts["sections"]["new"] += 1
            provenance.add(at)
            continue
        _id, title, content, page_number = by_id[row]
        same = (title == section.get("title")
                and (content or "") == (section_content(section) or "")
                and page_number == section.get("page_number"))
        counts["sections"]["same" if same else "changed"] += 1
        if (sorted(pages[row]) != page_rows(section)
                or segments[row] != segment_rows(section)):
            provenance.add(at)
    counts["sections"]["gone"] = len(gone_sections)
    renumbered = any(row is not None and rows_at[at] != at
                     for at, row in enumerate(rows))

    old_tables = _item_rows(conn, "Tables", TABLE_FIELDS, doc_id)
    old_figures = _item_rows(conn, "Images", IMAGE_FIELDS, doc_id)
    tables, gone_tables = pair(old_tables, [
        (at, t) for at, s in enumerate(sections) for t in s.get("tables") or []])
    figures, gone_figures = pair(old_figures, [
        (at, f) for at, s in enumerate(sections) for f in s.get("figures") or []])
    for kind, pairs, gone, values in (("tables", tables, gone_tables, table_values),
                                      ("figures", figures, gone_figures, image_values)):
        for at, item, row in pairs:
            if row is None:
                counts[kind]["new"] += 1
                continue
            now = values(rows[at], item) + (_source(item),)
            before = tuple(row[name] for name in (TABLE_FIELDS if kind == "tables"
                                                  else IMAGE_FIELDS)[1:])
            counts[kind]["same" if now == before else "changed"] += 1
        counts[kind]["gone"] = len(gone)

    # The inputs before, built from the rows as they stand, and now, with the
    # rows the new entries keep.
    held: dict = defaultdict(lambda: {"tables": [], "figures": []})
    for t in old_tables:
        held[t["section"]]["tables"].append(
            {"id": t["block_id"], "caption": t["caption"],
             "markdown": t["markdown"], "path": t["path"]})
    for f in old_figures:
        held[f["section"]]["figures"].append(
            {"id": f["block_id"], "caption": f["caption"],
             "description": f["description"], "path": f["path"]})
    old_doc = {"sections": [
        {"title": title, "content": content or "", **held[row_id]}
        for row_id, title, content, _page in old]}
    position = {row_id: at for at, row_id in enumerate(old_ids)}
    before = _owner_inputs(
        old_doc, name, pdf_dir, old_ids,
        {(position[t["section"]], t["block_id"]): t["id"] for t in reversed(old_tables)},
        {(position[f["section"]], f["block_id"]): f["id"] for f in reversed(old_figures)})
    now = _owner_inputs(
        new, name, pdf_dir, rows,
        {(at, item.get("id")): row["id"] for at, item, row in reversed(tables) if row},
        {(at, item.get("id")): row["id"] for at, item, row in reversed(figures) if row})
    drop: dict = {}
    kept = 0
    for kind, owner, etype, faiss_id in conn.execute(
            _EMBEDDINGS_SQL, (doc_id, doc_id, doc_id)):
        key = (kind, owner, etype)
        if key in before and before[key] == now.get(key):
            kept += 1
        else:
            drop[int(faiss_id)] = etype
    return Plan(name=name, doc_id=doc_id, new=new, rows=rows,
                gone_sections=gone_sections, tables=tables,
                gone_tables=[row["id"] for row in gone_tables], figures=figures,
                gone_figures=[row["id"] for row in gone_figures],
                provenance=provenance, renumbered=renumbered, drop=drop,
                kept=kept, counts=counts)


def apply_plan(conn, plan: Plan) -> None:
    """Write *plan* into the database; the caller commits."""
    doc_id = plan.doc_id
    sections = plan.new.get("sections", [])
    # Every section of the document out of the way of UNIQUE(document,
    # section_number), then each at its new number.
    conn.execute("UPDATE Sections SET section_number = -1 - id WHERE document = ?",
                 (doc_id,))
    ids: list = []
    for at, (section, row) in enumerate(zip(sections, plan.rows)):
        values = (section.get("title"), section_content(section),
                  section.get("page_number"))
        if row is None:
            row = conn.execute(
                "INSERT INTO Sections (document, section_number, title, "
                "content, page_number) VALUES (?, ?, ?, ?, ?)",
                (doc_id, at, *values)).lastrowid
        else:
            conn.execute("UPDATE Sections SET section_number = ?, title = ?, "
                         "content = ?, page_number = ? WHERE id = ?",
                         (at, *values, row))
        ids.append(row)
    for table, pairs, gone, values, columns in (
            ("Tables", plan.tables, plan.gone_tables, table_values,
             TABLE_FIELDS[1:]),
            ("Images", plan.figures, plan.gone_figures, image_values,
             IMAGE_FIELDS[1:])):
        for at, item, row in pairs:
            now = values(ids[at], item) + (_source(item),)
            if row is None:
                conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) "
                             f"VALUES ({', '.join('?' * len(columns))})", now)
            else:
                conn.execute(f"UPDATE {table} SET "
                             f"{', '.join(name + ' = ?' for name in columns)} "
                             "WHERE id = ?", (*now, row["id"]))
        conn.executemany(f"DELETE FROM {table} WHERE id = ?",
                         [(row,) for row in gone])
    # A gone section's tables and figures have moved or gone by now.
    conn.executemany("DELETE FROM Sections WHERE id = ?",
                     [(row,) for row in plan.gone_sections])
    page_cache: dict = {}
    for at in sorted(plan.provenance):
        conn.execute("DELETE FROM SectionPages WHERE section = ?", (ids[at],))
        conn.execute("DELETE FROM Segments WHERE section = ?", (ids[at],))
        insert_provenance(doc_id, ids[at], sections[at], conn, page_cache)
    conn.executemany("DELETE FROM Embeddings WHERE faiss_id = ?",
                     [(faiss_id,) for faiss_id in plan.drop])


def drop_from_index(path: Path, ids) -> int:
    """Take *ids* out of the index file *path*, written whole under a new name
    first; a re-embedding's record beside it then says it is incomplete.
    Returns how many vectors went."""
    import faiss
    path = Path(path)
    ids = sorted({int(i) for i in ids})
    if not ids:
        return 0
    index = faiss.read_index(str(path))
    removed = int(index.remove_ids(np.array(ids, dtype=np.int64)))
    part = path.with_name(path.name + ".part")
    faiss.write_index(index, str(part))
    os.replace(part, path)
    record = record_path(path)
    if record.exists():
        data = json.loads(record.read_text(encoding="utf-8"))
        data.update(complete=False, vectors=int(index.ntotal),
                    written=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        record.write_text(json.dumps(data, indent=1, sort_keys=True),
                          encoding="utf-8")
    log.info("%s: %d of %d vector(s) taken out, %d left", path, removed,
             len(ids), index.ntotal)
    return removed


@dataclass
class SyncReport:
    """What a sync found, counted over its documents."""
    documents: int = 0
    changed: list = field(default_factory=list)
    unregistered: list = field(default_factory=list)
    sections: Counter = field(default_factory=Counter)
    tables: Counter = field(default_factory=Counter)
    figures: Counter = field(default_factory=Counter)
    kept: int = 0
    dropped: Counter = field(default_factory=Counter)
    removed: dict = field(default_factory=dict)

    def add(self, plan: Plan) -> None:
        self.documents += 1
        if plan.writes:
            self.changed.append(plan.name)
        self.sections.update(plan.counts["sections"])
        self.tables.update(plan.counts["tables"])
        self.figures.update(plan.counts["figures"])
        self.kept += plan.kept
        self.dropped.update(plan.drop.values())

    def sentence(self) -> str:
        def said(counter: Counter) -> str:
            return "/".join(str(counter[k]) for k in ("same", "changed", "new", "gone"))
        return (f"{self.documents} document(s), {len(self.changed)} to write; "
                f"same/changed/new/gone: sections {said(self.sections)}, "
                f"tables {said(self.tables)}, figures {said(self.figures)}; "
                f"vectors kept {self.kept}, to embed again or gone "
                f"{sum(self.dropped.values())} ({dict(self.dropped) or 'none'}); "
                f"unregistered {len(self.unregistered)}")


def _read(pdf_dir: Path) -> dict:
    with open(pdf_dir / DOCUMENT_JSON, "r", encoding="utf-8") as fh:
        return json.load(fh)


def run_sync(data_dir: Path, db_path: Path, index_paths, *,
             dry_run: bool = False, resolve: Resolve = resolve_title) -> SyncReport:
    """Write every document under *data_dir* into *db_path* under the numbers
    its entries have, taking each vector whose input changed out of every
    file of *index_paths* first. *dry_run* counts and writes nothing."""
    data_dir, db_path = Path(data_dir), Path(db_path)
    paths = [Path(p) for p in index_paths]
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        raise FileNotFoundError(f"no index file: {', '.join(missing)}")
    report = SyncReport()
    drop: set = set()
    to_write: list = []
    with closing(connect(db_path)) as conn:
        for pdf_dir in document_dirs(data_dir, DOCUMENT_JSON):
            doc_id = _resolve_document_id(pdf_dir.name, conn)
            if doc_id is None:
                report.unregistered.append(pdf_dir.name)
                continue
            plan = plan_document(conn, doc_id, pdf_dir.name, _read(pdf_dir),
                                 pdf_dir, resolve)
            report.add(plan)
            if plan.writes:
                to_write.append((pdf_dir, doc_id))
                drop.update(plan.drop)
                log.info("%s: sections %s, tables %s, figures %s, vectors kept "
                         "%d, to embed again or gone %d", plan.name,
                         dict(plan.counts["sections"]), dict(plan.counts["tables"]),
                         dict(plan.counts["figures"]), plan.kept, len(plan.drop))
    log.info("sync%s: %s", " (dry run, nothing written)" if dry_run else "",
             report.sentence())
    if dry_run:
        return report
    for path in paths:
        report.removed[str(path)] = drop_from_index(path, drop)
    later: set = set()
    with closing(connect(db_path)) as conn:
        _ensure_bbox_columns(conn)
        _ensure_table_qa_column(conn)
        _ensure_caption_source_column(conn)
        for pdf_dir, doc_id in to_write:
            # Planned again on the rows as they stand now.
            plan = plan_document(conn, doc_id, pdf_dir.name, _read(pdf_dir),
                                 pdf_dir, resolve)
            apply_plan(conn, plan)
            conn.commit()
            later.update(set(plan.drop) - drop)
    if later:
        for path in paths:
            report.removed[str(path)] += drop_from_index(path, later)
    enrich_page_source(db_path, data_dir)
    log.info("sync: %d document(s) written; taken out of the indexes: %s",
             len(to_write), report.removed or "none")
    return report
