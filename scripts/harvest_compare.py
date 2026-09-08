#!/usr/bin/env python3
"""harvest_compare.py – What a harvest is worth, without a GPU.

Two harvests of the same plans differ in ways a log line cannot show. This
reads the JSONL a run wrote, puts it through the profile's own serializer and
prints the numbers a decision is made on: how many tuples survived into the
graph, how many were lost to a contested identity, which coordinate is still
open how often, and what the run cost in requests. Run it on the old
directory and on the new one and the diff is the answer.

It never loads a model and never touches the index. The one thing it needs
besides the harvest is the document database, because value IRIs are minted
from a plan's AGS and publication date.

A truth file is optional and is how a claim about a plan gets checked:
{"_comment": "read off the plan by hand",
 "years":     {"87457": 2040, ...},
 "scenarios": {"87438": "status_quo", ...}}
Coordinate at the top, then owner id to the value the plan really states, and
the report says how often the harvest agrees. Keys are strings because JSON
has no int keys, and a key starting with an underscore is prose, not a
coordinate.

No document level: an owner id is a Tables row of the database and unique
across the corpus, so a claim about one plan matches nothing in another and
the file is checked against every harvest in the directory. This paragraph
used to show a document name around it, the caller believed the docstring
over the file, and the measurement it feeds printed "keine Ernte" on every
run from 1f609f8 until it was noticed on the M3 acceptance run.

    python scripts/harvest_compare.py data/extraction/corpus data/KWP.db
    python scripts/harvest_compare.py <dir> <db> --truth kassel_truth.json

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from docpipe.extraction import fields                       # noqa: E402
from docpipe.profile import load_profile                    # noqa: E402

log = logging.getLogger("harvest_compare")

# The states a coordinate can end in, in the order they are worth reading:
# what was settled, what the plan does not say, what the run ran out of.
STATE_ORDER = (fields.READ, fields.DERIVED, fields.SAID_UNSTATED,
               fields.UNBACKED, fields.EXHAUSTED, fields.UNANSWERED,
               fields.OUT_OF_SLICE)

# The four a parameter_state line can carry, worst last, so the eye finds the
# read ones first.
PARAMETER_STATE_ORDER = (fields.READ, fields.UNBACKED, fields.SAID_UNSTATED,
                         fields.EXHAUSTED)


def read_harvest(path: Path) -> tuple:
    """(tuples, refusals, summary, parameter_lines) of one document's JSONL.

    The summary is the file's own last line and is neither: counting it as a
    refusal would add one to every document's refusal count, and the ratio
    that is read off it is the one this whole report exists for. The same
    holds for the parameter_state lines, and there is one per parameter of
    the spec, so an `else` that swept them into the refusals would report
    fourteen model errors per ar6 document that nobody made.
    """
    tuples, refusals, summary = [], [], None
    parameter_lines: list = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = row.get("kind")
        if kind == "tuple":
            tuples.append(row)
        elif kind == "summary":
            summary = row
        elif kind == "parameter_state":
            parameter_lines.append(row)
        else:
            refusals.append(row)
    return tuples, refusals, summary, parameter_lines


def serialize_counts(serializer, name: str, tuples: list, records: list) -> dict:
    """Run the profile's serializer and pick the skip counts out of its log.

    The counts live in a closure and reach the outside only as a log line, so
    the line is captured rather than the function rewritten: the serializer
    stays the one the corpus run uses, which is the whole point of measuring
    with it.
    """
    before = len(records)
    ttl = serializer(name, tuples)
    skipped: dict = {}
    for record in records[before:]:
        message = record.getMessage()
        if "skipped" not in message:
            continue
        start = message.find("{")
        if start == -1:
            continue
        try:
            skipped = json.loads(message[start:].replace("'", '"'))
        except json.JSONDecodeError:
            pass
    nodes = ttl.count("\n    a oeo:OEO_") if ttl else 0
    return {"ttl": ttl, "nodes": nodes, "skipped": skipped}


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list = []

    def emit(self, record):
        self.records.append(record)


def trace_costs(directory: Path, name: str) -> dict:
    """Requests, milliseconds and windows of one document's trace."""
    out = {"rows": 0, "field": 0, "ms": 0, "unparsable": 0, "drops": 0}
    # Where a run writes it, and where a hand-copied set of files has it.
    path = next((p for p in (directory / "trace" / f"{name}.trace.jsonl",
                             directory / f"{name}.trace.jsonl")
                 if p.is_file()), None)
    if path is None:
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("t")
        if kind in ("rows", "field"):
            out[kind] += 1
            out["ms"] += event.get("ms") or 0
        elif kind == "drop":
            out["drops"] += 1
        elif kind == "error" and event.get("kind") == "unparsable":
            out["unparsable"] += 1
    return out


def agreement(tuples: list, truth: dict) -> dict:
    """How often a coordinate matches what the plan really states.

    Keyed by owner, so it says nothing about tuples from owners the truth file
    does not mention: a claim about twelve tables is checked on those twelve
    and the rest is reported as untested rather than counted as right.
    """
    out: dict = {}
    for coordinate, wanted in (truth or {}).items():
        hit = miss = 0
        wrong: collections.Counter = collections.Counter()
        field = coordinate.rstrip("s")          # "years" -> "year"
        for row in tuples:
            owner = str((row.get("provenance") or {}).get("owner_id"))
            if owner not in wanted:
                continue
            got = row.get(field)
            if got == wanted[owner]:
                hit += 1
            else:
                miss += 1
                wrong[f"{owner}: {got}"] += 1
        out[coordinate] = {"hit": hit, "miss": miss,
                           "worst": wrong.most_common(5)}
    return out


def truth_report(files: list, truth: dict) -> list:
    """The lines comparing a harvest against what the plan really states.

    Over EVERY harvest file, because a truth entry is keyed by owner id and
    those are Tables rows of the database, unique across the corpus: a claim
    about one plan matches nothing in another. The caller used to read the
    truth file's top level as DOCUMENT names -- it is coordinate names -- and
    looked for `years.jsonl` and `scenarios.jsonl`. So it printed "keine
    Ernte" on every run since 1f609f8 and the acceptance measurement it feeds
    has never once been made.

    Its own function rather than a block inside `main`, because that is what
    let it go unseen: `agreement` had a test and the glue calling it had none.
    """
    wanted = {k: v for k, v in (truth or {}).items()
              if not k.startswith("_") and isinstance(v, dict)}
    lines, checked = [], collections.Counter()
    for path in files:
        tuples, _refusals, _summary, _states = read_harvest(path)
        for coordinate, got in agreement(tuples, wanted).items():
            seen = got["hit"] + got["miss"]
            checked[coordinate] += seen
            if not seen:
                continue
            lines.append("  %s %-10s richtig %d von %d (%.0f%%)" % (
                path.stem, coordinate, got["hit"], seen,
                100.0 * got["hit"] / seen))
            for owner, count in got["worst"]:
                lines.append("      falsch: %s (%dx)" % (owner, count))
    for coordinate in sorted(wanted):
        if not checked[coordinate]:
            # Named rather than silent. A truth file matching no owner of any
            # harvest here is exactly the state the old code was permanently
            # in, and it read as an empty section rather than as a failure.
            lines.append("  %s: kein Tupel von einem Eigner, den die "
                         "Wahrheitsdatei nennt" % coordinate)
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("db", type=Path)
    parser.add_argument("--truth", type=Path)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--document", action="append",
                        help="only this document (repeatable)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    profile = load_profile(args.profile)
    factory = profile.component("kg", "make_serializer")
    if factory is None:
        print(f"profiles/{profile.name}/kg.py hat kein make_serializer")
        return 1
    serializer = factory(args.db)
    collector = _Collect()
    kg_log = logging.getLogger(f"profiles.{profile.name}.kg")
    kg_log.addHandler(collector)
    kg_log.setLevel(logging.INFO)

    truth = json.loads(args.truth.read_text(encoding="utf-8")) if args.truth \
        else {}
    # A trace sits next to its harvest in a hand-copied set, and it is not a
    # document: counting it as one halves every per-document average.
    files = sorted(p for p in args.directory.glob("*.jsonl")
                   if not p.name.endswith(".trace.jsonl"))
    if args.document:
        wanted = set(args.document)
        files = [f for f in files if f.stem in wanted]
    if not files:
        print(f"keine Ernte in {args.directory}")
        return 1

    totals: collections.Counter = collections.Counter()
    skipped: collections.Counter = collections.Counter()
    levels: collections.Counter = collections.Counter()
    reasons: collections.Counter = collections.Counter()
    summaries: list = []
    states: dict = collections.defaultdict(collections.Counter)
    # Keyed by parameter, not by coordinate: `states` above counts the seven
    # per-coordinate states of the rows that exist, and a parameter that
    # produced no row appears in neither.
    parameters: dict = collections.defaultdict(collections.Counter)
    per_document: list = []
    for path in files:
        name = path.stem
        tuples, refusals, summary, parameter_lines = read_harvest(path)
        if summary:
            summaries.append((name, summary))
            for level, count in (summary.get("levels") or {}).items():
                levels[level] += count
            for reason, count in (summary.get("reasons") or {}).items():
                reasons[reason] += count
        got = serialize_counts(serializer, name, tuples, collector.records)
        cost = trace_costs(args.directory, name)
        for row in tuples:
            for key in row:
                if key.endswith("_state"):
                    states[key[:-6]][row[key]] += 1
        for row in parameter_lines:
            parameters[row.get("parameter")][row.get("state")] += 1
        totals["documents"] += 1
        totals["tuples"] += len(tuples)
        totals["refusals"] += len(refusals)
        totals["nodes"] += got["nodes"]
        totals["rows_requests"] += cost["rows"]
        totals["field_requests"] += cost["field"]
        totals["ms"] += cost["ms"]
        totals["unparsable"] += cost["unparsable"]
        for reason, count in (got["skipped"] or {}).items():
            skipped[reason] += count
        per_document.append((name, len(tuples), got["nodes"],
                             cost["rows"] + cost["field"]))

    print(f"\n=== {args.directory} ===")
    print(f"Dokumente {totals['documents']}, Tupel {totals['tuples']}, "
          f"Ablehnungen {totals['refusals']}, Wertknoten {totals['nodes']}")
    if totals["tuples"]:
        print("  Knoten je Tupel: %.3f" % (totals["nodes"] / totals["tuples"]))
    print("  nicht serialisiert: " + (", ".join(
        f"{k}={v}" for k, v in skipped.most_common()) or "nichts"))
    print(f"  Anfragen: {totals['rows_requests']} Zeilen + "
          f"{totals['field_requests']} Felder = "
          f"{totals['rows_requests'] + totals['field_requests']}, "
          f"davon unlesbar {totals['unparsable']}")
    if totals["documents"]:
        print("  je Dokument: %.0f Anfragen, %.1f Minuten Modellzeit"
              % ((totals["rows_requests"] + totals["field_requests"])
                 / totals["documents"],
                 totals["ms"] / 60000.0 / totals["documents"]))

    print("\nZustaende je Koordinate")
    for axis in sorted(states):
        counts = states[axis]
        total = sum(counts.values()) or 1
        ordered = [(s, counts[s]) for s in STATE_ORDER if counts.get(s)]
        ordered += [(s, n) for s, n in counts.items() if s not in STATE_ORDER]
        print("  %-16s %6d  %s" % (
            axis, total, ", ".join(f"{s}={n} ({100.0 * n / total:.0f}%)"
                                   for s, n in ordered)))

    if parameters:
        print("\nZustaende je Parameter (ein Dokument, eine Zeile)")
        for parameter in sorted(parameters):
            counts = parameters[parameter]
            print("  %-24s %s" % (
                parameter, ", ".join(
                    f"{s}={counts[s]}" for s in PARAMETER_STATE_ORDER
                    if counts.get(s))))

    if truth:
        print("\nGegen die bekannte Wahrheit")
        for line in truth_report(files, truth):
            print(line)

    if summaries:
        total = sum(levels.values()) or 1
        print("\nVertrauen je Wert (Ernteblick, ohne Konflikt und Zweitlesung)")
        print("  " + ", ".join("%s=%d (%.0f%%)" % (level, levels[level],
                                                   100.0 * levels[level] / total)
                               for level in ("A", "B", "C")))
        print("  Gruende: " + (", ".join(f"{k}={v}" for k, v
                                         in reasons.most_common(8)) or "keine"))
        shares = sorted(
            ((s["levels"].get("C", 0) / (s["tuples"] or 1), name, s)
             for name, s in summaries), reverse=True)[:5]
        print("  Plaene mit dem hoechsten C-Anteil")
        for share, name, s in shares:
            print("      %s: %.0f%% von %d Tupeln" % (name, 100.0 * share,
                                                      s["tuples"]))
    else:
        print("\nVertrauen je Wert: keine Zusammenfassungszeile in dieser Ernte")

    worst = sorted(per_document, key=lambda r: r[2])[:5]
    print("\nSchwaechste Dokumente (Knoten)")
    for name, tuples, nodes, requests in worst:
        print(f"  {name}: {nodes} Knoten aus {tuples} Tupeln, {requests} Anfragen")
    return 0


if __name__ == "__main__":
    sys.exit(main())
