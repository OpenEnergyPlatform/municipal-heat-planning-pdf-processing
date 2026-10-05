#!/usr/bin/env python3
"""table_numbers_in_pdf.py: How much of a stored table the PDF itself prints.

Stage 5 has a vision model read every table off its picture, and the Markdown
it wrote is what the database stores and what a harvest quotes. A PDF with a
text layer prints the same numbers as text, inside the same frame. This sets
the two side by side and counts. It reads a corpus database, the PDFs and,
when it is given one, a harvest directory:

  (a) per table: how many of the distinct numbers of the stored transcription
      stand in the PDF text at the table's place;
  (b) per parameter: of the values the harvest read out of a table, how many
      have their digits in that text.

It judges nothing and changes nothing. No trust level, reason or flag reads
what it prints, the database is opened for reading only, and a table it
cannot judge is listed with the reason and left out of every share, never
counted as a miss.

    python scripts/table_numbers_in_pdf.py data/KWP.db data/pdf
    python scripts/table_numbers_in_pdf.py <db> <pdf root> --harvest data/extraction/corpus
    python scripts/table_numbers_in_pdf.py <db> <pdf root> --document 12 --json counts.json

What the numbers are. A number is compared the way the harvest compares one:
1.234,5 and 1234.5 are one number, and how a point or comma is read is the
profile's decimal mark (--profile or DOCPIPE_PROFILE; with neither the comma,
as everywhere else the harvest reads a number). Each table counts
its DISTINCT numbers, so a number that stands in six cells is one. The table's
place is its stored bbox, which stage 2 widens by a few points on each side:
a number printed just beside a table can stand in its text. The PDF text is
the text layer. A page without one (a plan a model transcribed) cannot be
judged, and neither can a table whose frame holds no text, and both are said
so.

What (b) compares: the value of a numeric parameter, as the harvest wrote it,
against the numbers in the frame text of the table the value was read from.
A value the sandbox computed is not read off a page and is counted apart. A
harvest names its table by Tables.id, which a rebuilt database renews, so a
tuple whose id is not a table of this database, or is one of another document
or block, is counted apart too.

Needs PyMuPDF. No model, no GPU.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe import jsonl                                    # noqa: E402
from docpipe.extraction.verify import (                      # noqa: E402
    canonical_number, decimal_mark, numbers_in)
from docpipe.profile import bind_command_line, resolve_profile  # noqa: E402
from docpipe.store import schema                             # noqa: E402

log = logging.getLogger("table_numbers_in_pdf")

# Why a table's numbers could not be set against a frame of the PDF. Each is a
# count of tables in the report, in the order a reader should look at them.
NO_TRANSCRIPTION = "no_transcription"
NO_NUMBERS = "no_numbers_in_transcription"
NO_BBOX = "no_bbox"
NO_PAGE = "no_page_number"
NO_PDF = "pdf_not_found"
UNREADABLE = "pdf_unreadable"
PAGE_NOT_IN_PDF = "page_not_in_pdf"
NO_TEXT_LAYER = "page_without_text_layer"
NO_TEXT_IN_FRAME = "no_text_in_frame"

REASONS = {
    NO_TRANSCRIPTION: "the table has no stored transcription",
    NO_NUMBERS: "its transcription holds no number",
    NO_BBOX: "no stored place for the table (no bbox)",
    NO_PAGE: "no stored page for the table",
    NO_PDF: "the document's PDF is not under the PDF root",
    UNREADABLE: "the PDF could not be read",
    PAGE_NOT_IN_PDF: "the stored page is not a page of the PDF",
    NO_TEXT_LAYER: "the page has no text layer",
    NO_TEXT_IN_FRAME: "the page has text, the table's frame has none",
}

# What a harvested value can be besides "digits in the text" and "digits not
# in the text": it was not compared, and why.
COMPUTED = "computed"
NOT_A_NUMBER = "not_a_number"
TABLE_NOT_JUDGED = "table_frame_unreadable"
NOT_IN_DATABASE = "table_not_in_database"
OTHER_TABLE = "id_is_another_table"

VALUE_REASONS = {
    COMPUTED: "computed by the sandbox, not read off the page",
    NOT_A_NUMBER: "a category or a wording, which has no digits",
    TABLE_NOT_JUDGED: "the frame of its table could not be read (see the "
                      "reasons for tables)",
    NOT_IN_DATABASE: "its table id is not a table of this database",
    OTHER_TABLE: "its table id is a table of another document or block "
                 "(the database was rebuilt after the harvest)",
}

# How many missing numbers a table row carries, so a row stays a line.
MISSING_SHOWN = 10

# The share of a table's numbers found in its frame, as the classes the report
# prints, best first.
SHARE_CLASSES = ("every number", "90 % to under 100 %", "50 % to under 90 %",
                 "under 50 %, some", "none")


def share_class(found: int, numbers: int) -> str:
    """Which class a table with *found* of *numbers* distinct numbers is in."""
    if found >= numbers:
        return SHARE_CLASSES[0]
    if found == 0:
        return SHARE_CLASSES[4]
    share = found / numbers
    if share >= 0.9:
        return SHARE_CLASSES[1]
    if share >= 0.5:
        return SHARE_CLASSES[2]
    return SHARE_CLASSES[3]


def numbers_of(text: str) -> set:
    """The distinct numbers of *text*, each in its one canonical spelling."""
    return {n for n in numbers_in(text) if n}


def frame_of(bbox_json) -> Optional[tuple]:
    """The one rectangle a table's stored bbox spans, or None.

    Tables.bbox is a JSON list holding one [x0, y0, x1, y1]. More than one is
    joined into the box that holds them all, and a rect that is not four
    numbers or has no area is not used.
    """
    try:
        rects = json.loads(bbox_json) if bbox_json else None
    except (TypeError, ValueError):
        return None
    if not isinstance(rects, list):
        return None
    good = []
    for rect in rects:
        if (isinstance(rect, list) and len(rect) == 4
                and all(isinstance(v, (int, float))
                        and not isinstance(v, bool) for v in rect)
                and rect[2] > rect[0] and rect[3] > rect[1]):
            good.append(rect)
    if not good:
        return None
    return (min(r[0] for r in good), min(r[1] for r in good),
            max(r[2] for r in good), max(r[3] for r in good))


class PdfFrames:
    """The text a PDF carries inside a rectangle of a page.

    One document is held open at a time: the tables are read in document
    order. MuPDF is entered from this one thread only, which is why nothing
    here takes a lock.
    """

    def __init__(self, root):
        self.root = Path(root)
        self._path: Optional[Path] = None
        self._document = None
        self._why: Optional[str] = None

    def close(self) -> None:
        if self._document is not None:
            self._document.close()
        self._path = self._document = self._why = None

    def _open(self, filename: str):
        path = self.root / filename
        if path == self._path:
            return self._document, self._why
        self.close()
        self._path = path
        if not path.is_file():
            self._why = NO_PDF
            return None, self._why
        import fitz
        try:
            self._document = fitz.open(str(path))
        except Exception as exc:
            log.warning("%s: cannot be read: %s", path.name, exc)
            self._why = UNREADABLE
        return self._document, self._why

    def text(self, filename: Optional[str], page: int, rect: tuple):
        """(text, None) for the text inside *rect* of 1-based *page*, or
        (None, reason) when the frame cannot be read."""
        if not filename:
            return None, NO_PDF
        document, why = self._open(filename)
        if document is None:
            return None, why
        import fitz
        try:
            if not 1 <= page <= document.page_count:
                return None, PAGE_NOT_IN_PDF
            leaf = document.load_page(page - 1)
            inside = leaf.get_text("text", clip=fitz.Rect(*rect))
            if inside.strip():
                return inside, None
            whole = leaf.get_text("text")
        except Exception as exc:
            log.warning("%s page %s: cannot be read: %s", filename, page, exc)
            return None, UNREADABLE
        return None, (NO_TEXT_IN_FRAME if whole.strip() else NO_TEXT_LAYER)


def frame_numbers(frames, table: dict):
    """(numbers of the frame text, None), or (None, why it cannot be read)."""
    if table["page"] is None:
        return None, NO_PAGE
    rect = frame_of(table["bbox"])
    if rect is None:
        return None, NO_BBOX
    text, why = frames.text(table["filename"], int(table["page"]), rect)
    if text is None:
        return None, why
    return numbers_of(text), None


def table_rows(connection: sqlite3.Connection, documents=None):
    """Every table of the database, in document and page order, as dicts.

    A database that predates Tables.bbox has no such column and every one of
    its tables is then without a place.
    """
    bbox = ('t."bbox"' if "bbox" in schema.columns(connection, "Tables")
            else "NULL")
    where, args = "", ()
    if documents:
        where = f"WHERE s.document IN ({','.join('?' * len(documents))}) "
        args = tuple(documents)
    cursor = connection.execute(
        f'SELECT t."id", t."block_id", t."page_number", t."markdown", {bbox}, '
        f's.document, d."filename" FROM "Tables" t '
        f'JOIN "Sections" s ON t."section" = s."id" '
        f'LEFT JOIN "Documents" d ON s.document = d."id" {where}'
        f'ORDER BY s.document, t."page_number", t."id"', args)
    for (table_id, block_id, page, markdown, box, document,
         filename) in cursor:
        yield {"id": table_id, "block_id": block_id, "page": page,
               "markdown": markdown, "bbox": box, "document": document,
               "filename": filename}


def read_harvest(directory: Path, documents=None) -> dict:
    """What (b) needs of a harvest: the tuples read out of a table.

    {"files", "tuples" (all), "by_owner" (tuples per owner kind), "wanted"
    (table id -> the tuples read from it)}. A line that is not JSON is
    skipped: one torn line must not lose a plan. With *documents* only the
    tuples of those documents are looked at.
    """
    out = {"files": 0, "tuples": 0, "by_owner": collections.Counter(),
           "wanted": collections.defaultdict(list)}
    for path in sorted(p for p in directory.glob("*.jsonl")
                       if not p.name.endswith(".trace.jsonl")):
        out["files"] += 1
        for line in jsonl.read(path):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("kind") != "tuple":
                continue
            where = row.get("provenance")
            where = where if isinstance(where, dict) else {}
            if documents and where.get("document_id") not in documents:
                continue
            out["tuples"] += 1
            kind = where.get("owner_kind")
            out["by_owner"][kind] += 1
            owner = where.get("owner_id")
            if kind != "table" or not isinstance(owner, int):
                continue
            value = row.get("value")
            number = (None if isinstance(value, bool)
                      or not isinstance(value, (int, float))
                      else canonical_number(value))
            out["wanted"][owner].append({
                "parameter": row.get("parameter"), "number": number,
                "computed": row.get("computed") is True,
                "document": where.get("document_id"),
                "block_id": where.get("block_id")})
    return out


def judge_values(table: dict, frame: Optional[set], wanted: list,
                 counts: dict) -> None:
    """Book the harvested values of one table into *counts*, per parameter."""
    for entry in wanted:
        book = counts[entry["parameter"]]
        book["tuples"] += 1
        if (entry["document"] is not None
                and entry["document"] != table["document"]) or (
                entry["block_id"] and entry["block_id"] != table["block_id"]):
            book[OTHER_TABLE] += 1
        elif entry["computed"]:
            book[COMPUTED] += 1
        elif entry["number"] is None:
            book[NOT_A_NUMBER] += 1
        elif frame is None:
            book[TABLE_NOT_JUDGED] += 1
        elif entry["number"] in frame:
            book["digits_in_pdf_text"] += 1
        else:
            book["digits_not_in_pdf_text"] += 1


def measure(connection: sqlite3.Connection, frames, harvest: Optional[dict],
            documents=None) -> dict:
    """Run (a) over the tables and, with a harvest, (b) over its tuples."""
    rows: list = []
    not_judged: collections.Counter = collections.Counter()
    classes: collections.Counter = collections.Counter()
    seen_documents: set = set()
    seen_tables: set = set()
    numbers = found = 0
    counts: dict = collections.defaultdict(collections.Counter)
    wanted = harvest["wanted"] if harvest else {}

    for table in table_rows(connection, documents):
        seen_documents.add(table["document"])
        seen_tables.add(table["id"])
        stored = numbers_of(table["markdown"] or "")
        harvested = wanted.get(table["id"], ())
        row = {"table_id": table["id"], "document": table["document"],
               "filename": table["filename"], "block_id": table["block_id"],
               "page": table["page"]}
        # The frame is read for a table whose transcription cannot be counted
        # too, when a harvested value stands on it.
        frame, why = None, None
        if stored or harvested:
            frame, why = frame_numbers(frames, table)
        if harvested:
            judge_values(table, frame, harvested, counts)
        if not (table["markdown"] or "").strip():
            why = NO_TRANSCRIPTION
        elif not stored:
            why = NO_NUMBERS
        if why is not None:
            row["not_judged"] = why
            not_judged[why] += 1
        else:
            hit = stored & frame
            row.update({"numbers_in_transcription": len(stored),
                        "numbers_in_pdf_text": len(hit),
                        "missing": sorted(stored - hit)[:MISSING_SHOWN]})
            numbers += len(stored)
            found += len(hit)
            classes[share_class(len(hit), len(stored))] += 1
        rows.append(row)

    judged = sum(classes.values())
    report = {
        "decimal_mark": decimal_mark(),
        "tables": {"in_database": len(rows), "documents": len(seen_documents),
                   "judged": judged,
                   "not_judged": dict(not_judged),
                   "numbers_in_transcriptions": numbers,
                   "numbers_in_pdf_text": found,
                   "by_share": {name: classes[name] for name in SHARE_CLASSES}},
        "rows": rows,
    }
    if harvest is not None:
        # Tuples whose table never came up: not a table of this database.
        for table_id, entries in wanted.items():
            if table_id in seen_tables:
                continue
            for entry in entries:
                counts[entry["parameter"]]["tuples"] += 1
                counts[entry["parameter"]][NOT_IN_DATABASE] += 1
        report["harvest"] = {
            "plans": harvest["files"], "tuples": harvest["tuples"],
            "tuples_by_owner": {str(k): v
                                for k, v in harvest["by_owner"].items()},
            "parameters": {str(p): dict(c) for p, c in sorted(
                counts.items(), key=lambda item: str(item[0]))}}
    return report


def worst(report: dict, limit: int) -> list:
    """The judged tables with the lowest share of their numbers found."""
    judged = [r for r in report["rows"] if "not_judged" not in r]
    judged.sort(key=lambda r: (r["numbers_in_pdf_text"]
                               / r["numbers_in_transcription"],
                               -r["numbers_in_transcription"],
                               r["table_id"]))
    return judged[:limit]


def _percent(part: int, whole: int) -> str:
    return f"{100.0 * part / whole:.1f} %" if whole else "n/a"


def render(report: dict, limit: int) -> list:
    """The lines the report prints. Every count says what it counts."""
    t = report["tables"]
    lines = [f"decimal mark of the documents: {report['decimal_mark']!r}", ""]
    lines.append("(a) the numbers of each stored transcription against the "
                 "PDF text in the table's frame")
    lines.append(f"    tables in the database: {t['in_database']:,} "
                 f"({t['documents']:,} documents)")
    lines.append(f"    judged: {t['judged']:,} tables; not judged: "
                 f"{sum(t['not_judged'].values()):,} tables")
    for why, count in sorted(t["not_judged"].items(),
                             key=lambda item: -item[1]):
        lines.append(f"        {count:7,} tables: {REASONS[why]}")
    # A number that stands in two tables is counted in both: the sum is of
    # per-table counts, and the line says so.
    lines.append(f"    in the judged tables: {t['numbers_in_transcriptions']:,}"
                 f" numbers in the transcriptions (each counted once per "
                 f"table), {t['numbers_in_pdf_text']:,} of them in the PDF "
                 f"text of the frame "
                 f"({_percent(t['numbers_in_pdf_text'], t['numbers_in_transcriptions'])})")
    if t["judged"]:
        lines.append("    judged tables by the share of their numbers found:")
        for name in SHARE_CLASSES:
            lines.append(f"        {t['by_share'][name]:7,} tables: {name}")
        lines.append(f"    the {min(limit, t['judged'])} judged tables with "
                     f"the lowest share:")
        for r in worst(report, limit):
            lines.append(
                f"        {r['filename']} {r['block_id']} p.{r['page']}: "
                f"{r['numbers_in_pdf_text']} of "
                f"{r['numbers_in_transcription']} numbers; not in the PDF "
                f"text: {', '.join(r['missing'])}")
    harvest = report.get("harvest")
    if harvest is None:
        return lines
    owners = ", ".join(f"{k} {v:,}" for k, v in
                       sorted(harvest["tuples_by_owner"].items()))
    lines += ["", "(b) the digits of the values read out of a table against "
                  "the PDF text in that table's frame",
              f"    harvest: {harvest['plans']:,} plans, "
              f"{harvest['tuples']:,} tuples ({owners})"]
    for parameter, c in harvest["parameters"].items():
        compared = c.get("digits_in_pdf_text", 0) \
            + c.get("digits_not_in_pdf_text", 0)
        lines.append(f"    {parameter.rsplit('/', 1)[-1]}: {c['tuples']:,} "
                     f"tuples from tables; {c.get('digits_in_pdf_text', 0):,} "
                     f"have their digits in the PDF text, "
                     f"{c.get('digits_not_in_pdf_text', 0):,} do not "
                     f"({_percent(c.get('digits_in_pdf_text', 0), compared)} "
                     f"of the {compared:,} compared)")
        for why, text in VALUE_REASONS.items():
            if c.get(why):
                lines.append(f"        {c[why]:7,} tuples not compared: "
                             f"{text}")
    return lines


def main(argv=None) -> int:
    bind_command_line(argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("db", type=Path, help="the corpus database")
    parser.add_argument("pdf_root", type=Path,
                        help="the directory holding the PDFs the Documents "
                             "table names")
    parser.add_argument("--harvest", type=Path, default=None,
                        help="a harvest directory (one <plan>.jsonl each): "
                             "adds the per-parameter counts")
    parser.add_argument("--document", type=int, action="append", default=None,
                        metavar="ID",
                        help="only this document id (repeatable)")
    parser.add_argument("--worst", type=int, default=15, metavar="N",
                        help="how many tables with the lowest share to list "
                             "(default 15)")
    parser.add_argument("--json", type=Path, default=None, metavar="FILE",
                        help="write the counts, with one row per table, here")
    parser.add_argument("--profile", default=None,
                        help="the profile whose decimal mark reads the "
                             "numbers (default: DOCPIPE_PROFILE, else the "
                             "comma)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.db.is_file():
        print(f"no database at {args.db}", file=sys.stderr)
        return 1
    if not args.pdf_root.is_dir():
        print(f"not a directory: {args.pdf_root}", file=sys.stderr)
        return 1
    if args.harvest is not None and not any(
            p for p in args.harvest.glob("*.jsonl")
            if not p.name.endswith(".trace.jsonl")):
        print(f"no harvest in {args.harvest}", file=sys.stderr)
        return 1
    try:
        import fitz     # noqa: F401
    except ImportError:
        print("PyMuPDF is not installed (pip install pymupdf)",
              file=sys.stderr)
        return 1
    try:
        resolve_profile(args)
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1

    documents = set(args.document) if args.document else None
    harvest = (read_harvest(args.harvest, documents)
               if args.harvest is not None else None)
    frames = PdfFrames(args.pdf_root)
    try:
        with closing(sqlite3.connect(schema.readonly_uri(args.db),
                                     uri=True)) as connection:
            report = measure(connection, frames, harvest, documents)
    except sqlite3.DatabaseError as exc:
        print(f"{args.db} is not a corpus database: {exc}", file=sys.stderr)
        return 1
    finally:
        frames.close()

    print("\n".join(render(report, args.worst)))
    if args.json is not None:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                             encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
