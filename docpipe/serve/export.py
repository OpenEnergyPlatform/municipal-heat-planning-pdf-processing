"""
export.py: What a harvest holds, as a table.

Three tables, each as a CSV for a spreadsheet or as JSON lines for a
program:

    values    one line per accepted value, with its quote and its page,
              because a number handed on without what backs it is no
              longer a verified one
    states    one line per document and parameter: what the harvest says
              about it, so "the plan does not say it" (unstated) leaves the
              harvest as a line and not as an absence
    refusals  one line per claim the harvest refused, with the reason

A coordinate of a value is three columns: what was read (`<name>`), its
label where the spec has one (`<name>_label`) and how the reading ended
(`<name>_state`). The columns of a file are the coordinates its values
have, in alphabetical order after the fixed ones. After all of those come
the passages the coordinates were read from (`<name>_quote`), appended so
that a table written before they existed keeps its columns where they were.

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
STATE_COLUMNS = ("document", "parameter", "label", "state", "tuples",
                 "refusals")
REFUSAL_COLUMNS = ("document", "parameter", "reason", "failed", "owner_kind",
                   "owner_id", "claim")
QUOTE = "_quote"


def flat(value: dict) -> dict:
    """One value as one line."""
    source = value.get("source") or {}
    line = {name: value.get(name) for name in FIXED
            if not name.startswith("source_")}
    line["reasons"] = ", ".join(value.get("reasons") or [])
    line["source_kind"] = source.get("owner_kind")
    line["source_title"] = source.get("title") or source.get("section_title")
    coordinates = sorted((value.get("coordinates") or {}).items())
    for name, coordinate in coordinates:
        line[name] = coordinate.get("value")
        line[f"{name}_label"] = coordinate.get("label")
        line[f"{name}_state"] = coordinate.get("state")
    for name, coordinate in coordinates:
        line[name + QUOTE] = coordinate.get("quote")
    return line


def columns(lines: Iterable[dict]) -> list:
    lines = list(lines)
    named = {name for line in lines for name in line} - set(FIXED)
    # The quotes of the coordinates come last; `quote` itself is fixed.
    quotes = {name for name in named if name.endswith(QUOTE)}
    extra = sorted(named - quotes,
                   key=lambda name: (name.split("_label")[0]
                                     .split("_state")[0], name))
    return list(FIXED) + extra + sorted(quotes)


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


def _table(names: Iterable[str], lines: list) -> str:
    out = io.StringIO()
    # Lines end as the format says (CR LF). Both characters are then
    # quoted where a cell holds one: a lone CR in a quote would otherwise
    # be written bare by some versions of the csv module, and end the row.
    writer = csv.DictWriter(out, fieldnames=list(names),
                            lineterminator="\r\n")
    writer.writeheader()
    for line in lines:
        writer.writerow({name: _cell(content)
                         for name, content in line.items()})
    return out.getvalue()


def to_csv(values: Iterable[dict]) -> str:
    lines = [flat(value) for value in values]
    return _table(columns(lines), lines)


def states_to_csv(cells: Iterable[dict]) -> str:
    return _table(STATE_COLUMNS, [{name: cell.get(name)
                                   for name in STATE_COLUMNS}
                                  for cell in cells])


def refusals_to_csv(refusals: Iterable[dict]) -> str:
    lines = []
    for refusal in refusals:
        source = refusal.get("source") or {}
        line = {name: refusal.get(name) for name in REFUSAL_COLUMNS}
        line["owner_kind"] = source.get("owner_kind")
        line["owner_id"] = source.get("owner_id")
        lines.append(line)
    return _table(REFUSAL_COLUMNS, lines)


def to_jsonl(values: Iterable[dict]) -> str:
    return "".join(json.dumps(value, ensure_ascii=False) + "\n"
                   for value in values)


FORMATS = {"csv": to_csv, "jsonl": to_jsonl}
# {what: (writer per format, what one line counts)}
TABLES = {
    "values": ({"csv": to_csv, "jsonl": to_jsonl}, "value"),
    "states": ({"csv": states_to_csv, "jsonl": to_jsonl}, "state"),
    "refusals": ({"csv": refusals_to_csv, "jsonl": to_jsonl}, "refusal"),
}


if __name__ == "__main__":
    import sys

    from docpipe.profile import bind_command_line
    bind_command_line()
    from docpipe.serve.cli import export_main
    sys.exit(export_main())
