#!/usr/bin/env python3
"""curation_list.py – The values a person should look at, and where to look.

Trust is per value and the summary line is per plan, and between the two sits
the question a curator actually has: which values, in which order, and on
which page. A corpus run produces tens of thousands of tuples and a share of
them carry a reason -- a passage that belongs to another row, a coordinate the
run gave up on, a repaired quote. Reading the JSONL for those is a filter
nobody should have to write twice.

So: one row per value the harvest cannot stand behind, newest doubt first,
with the page, the crop and the passage that was cited. It is the input to the
mini peer review and, until that runs, the review itself.

    python scripts/curation_list.py data/extraction/corpus
    python scripts/curation_list.py <dir> --level C --out kuration.csv
    python scripts/curation_list.py <dir> --reason nonlocal: --limit 200

No model, no database, no GPU: everything it prints was written by the run.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.extraction.trust import LEVEL_A, LEVEL_B, LEVEL_C, trust  # noqa: E402

# What a curator needs to find the value again, in the order they need it.
COLUMNS = ("document", "level", "reasons", "parameter", "value", "unit",
           "page", "owner", "title", "image", "quote", "coordinates")

# A cell has to fit a spreadsheet and a terminal; the harvest keeps the whole
# passage and this list is not the archive.
CELL = 300


def _cell(text) -> str:
    flat = " ".join(str(text if text is not None else "").split())
    return flat if len(flat) <= CELL else flat[:CELL].rstrip() + " …"


def coordinates(row: dict) -> str:
    """The row's coordinates as one readable cell: axis=value per state.

    The state is what makes the cell worth reading. "year=2040" says nothing
    about whether anyone should trust it; "year=2040(read)" next to
    "sector=(exhausted)" says where to look first.
    """
    parts = []
    for key in sorted(row):
        if not key.endswith("_state"):
            continue
        name = key[: -len("_state")]
        value = row.get(name)
        label = str(value) if value not in (None, "") else ""
        parts.append(f"{name}={label}({row[key]})")
    return " ".join(parts)


def rows_of(document: str, tuples: list, *, levels: set,
            reason: str = "") -> list:
    """The tuples of one document that a curator should see, worst first."""
    out = []
    for row in tuples:
        verdict = trust(row)
        if verdict["level"] not in levels:
            continue
        why = verdict["reasons"]
        if reason and not any(r.startswith(reason) for r in why):
            continue
        provenance = row.get("provenance") or {}
        out.append({
            "document": document,
            "level": verdict["level"],
            "reasons": ",".join(why),
            "parameter": (row.get("parameter") or "").rsplit("/", 1)[-1],
            "value": row.get("value"),
            "unit": row.get("unit_raw") or row.get("unit") or "",
            "page": provenance.get("page"),
            "owner": f"{provenance.get('owner_kind')} "
                     f"{provenance.get('owner_id')}".strip(),
            "title": _cell(provenance.get("title")),
            "image": provenance.get("image") or "",
            "quote": _cell(row.get("quote")),
            "coordinates": coordinates(row),
        })
    # Most reasons first: a value with three things wrong with it is where a
    # curator learns the most per minute.
    out.sort(key=lambda r: (-len(r["reasons"].split(",")), r["page"] or 0))
    return out


def read_tuples(path: Path) -> list:
    """The accepted tuples of one harvest file. Refusals and the summary are
    not values, so they are not curated."""
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("kind") == "tuple":
            out.append(row)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--level", default=LEVEL_C,
                        help=f"lowest level to list: {LEVEL_C} (default), "
                             f"{LEVEL_B} or {LEVEL_A} for everything")
    parser.add_argument("--reason", default="",
                        help="only values with a reason starting like this, "
                             "e.g. 'nonlocal:' or 'exhausted:year'")
    parser.add_argument("--document", action="append",
                        help="only this document (repeatable)")
    parser.add_argument("--limit", type=int, default=0,
                        help="print at most this many rows (0 = all)")
    parser.add_argument("--out", type=Path,
                        help="write the whole list as CSV here; without it "
                             "the first rows go to the terminal")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"kein Verzeichnis: {args.directory}", file=sys.stderr)
        return 1
    order = [LEVEL_A, LEVEL_B, LEVEL_C]
    if args.level not in order:
        print(f"unbekannte Stufe: {args.level}", file=sys.stderr)
        return 1
    levels = set(order[order.index(args.level):])

    files = sorted(p for p in args.directory.glob("*.jsonl")
                   if not p.name.endswith(".trace.jsonl"))
    if args.document:
        wanted = set(args.document)
        files = [f for f in files if f.stem in wanted]
    if not files:
        print(f"keine Ernte in {args.directory}", file=sys.stderr)
        return 1

    rows: list = []
    seen = 0
    for path in files:
        tuples = read_tuples(path)
        seen += len(tuples)
        rows.extend(rows_of(path.stem, tuples, levels=levels,
                            reason=args.reason))

    by_reason: collections.Counter = collections.Counter()
    for row in rows:
        for why in row["reasons"].split(","):
            if why:
                by_reason[why] += 1

    print(f"{len(rows)} von {seen} Werten aus {len(files)} Plaenen, "
          f"Stufe {args.level} und schlechter"
          + (f", Grund {args.reason!r}" if args.reason else ""))
    print("  Gruende: " + (", ".join(f"{k}={v}" for k, v
                                     in by_reason.most_common(10)) or "keine"))

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"  geschrieben: {args.out}")
        return 0

    for row in rows[: args.limit or 25]:
        print("\n  %s | %s | %s" % (row["document"], row["level"],
                                    row["reasons"]))
        print("    %s %s  S. %s  %s" % (row["value"], row["unit"], row["page"],
                                        row["owner"]))
        if row["title"]:
            print(f"    {row['title']}")
        print(f"    {row['coordinates']}")
        if row["image"]:
            print(f"    {row['image']}")
    if not args.limit and len(rows) > 25:
        print(f"\n  ... {len(rows) - 25} weitere, --out fuer die ganze Liste")
    return 0


if __name__ == "__main__":
    sys.exit(main())
