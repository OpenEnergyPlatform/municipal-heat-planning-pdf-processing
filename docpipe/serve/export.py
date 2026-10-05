"""
export.py: The harvested values as a table.

One line per value. A CSV for a spreadsheet, JSON lines for a program; both
carry the same columns, and both carry the quote and the page, because a
number handed on without what backs it is no longer a verified one.

A coordinate is three columns: what was read (`<name>`), its label where
the spec has one (`<name>_label`) and how the reading ended
(`<name>_state`). The columns of a file are the coordinates its values
have, in alphabetical order after the fixed ones.

Author: Felix Vossel
"""
from __future__ import annotations

import csv
import io
import json
from typing import Iterable

FIXED = ("id", "document", "parameter", "label", "value", "unit",
         "value_raw", "unit_raw", "value_target", "unit_target",
         "value_label", "level", "reasons", "from_image", "page", "quote",
         "source_kind", "source_title")


def flat(value: dict) -> dict:
    """One value as one line."""
    source = value.get("source") or {}
    line = {name: value.get(name) for name in FIXED
            if not name.startswith("source_")}
    line["reasons"] = ", ".join(value.get("reasons") or [])
    line["source_kind"] = source.get("owner_kind")
    line["source_title"] = source.get("title") or source.get("section_title")
    for name, coordinate in sorted((value.get("coordinates") or {}).items()):
        line[name] = coordinate.get("value")
        line[f"{name}_label"] = coordinate.get("label")
        line[f"{name}_state"] = coordinate.get("state")
    return line


def columns(lines: Iterable[dict]) -> list:
    extra = sorted({name for line in lines for name in line} - set(FIXED),
                   key=lambda name: (name.split("_label")[0]
                                     .split("_state")[0], name))
    return list(FIXED) + extra


def _cell(content):
    """A cell a spreadsheet does not take for a formula: text that begins
    like one is written with a leading apostrophe, as spreadsheets show
    text."""
    if isinstance(content, str) and content[:1] in ("=", "+", "-", "@",
                                                    "\t", "\r"):
        return "'" + content
    if isinstance(content, (list, dict)):
        return json.dumps(content, ensure_ascii=False)
    return content


def to_csv(values: Iterable[dict]) -> str:
    lines = [flat(value) for value in values]
    out = io.StringIO()
    # Lines end as the format says (CR LF). Both characters are then
    # quoted where a cell holds one: a lone CR in a quote would otherwise
    # be written bare by some versions of the csv module, and end the row.
    writer = csv.DictWriter(out, fieldnames=columns(lines),
                            lineterminator="\r\n")
    writer.writeheader()
    for line in lines:
        writer.writerow({name: _cell(content)
                         for name, content in line.items()})
    return out.getvalue()


def to_jsonl(values: Iterable[dict]) -> str:
    return "".join(json.dumps(value, ensure_ascii=False) + "\n"
                   for value in values)


FORMATS = {"csv": to_csv, "jsonl": to_jsonl}


if __name__ == "__main__":
    import sys

    from docpipe.profile import bind_command_line
    bind_command_line()
    from docpipe.serve.cli import export_main
    sys.exit(export_main())
