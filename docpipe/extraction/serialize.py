"""
serialize.py: Turns a document harvest into the profile's target graph.

The module walks the JSONL harvest directory and keeps only the rows
a run accepted (kind is "tuple"), grouped by document name (collect).
run() hands each document's rows to a serializer, and the runner's
--serialize flag chooses it: profiles/<name>/kg.py exposes
make_serializer(db_path) where the profile writes its graph itself,
and a profile without one gets the generic writer of graph.py, which
writes what the `graph` block of the spec describes. What a profile's
own serializer emits (Turtle with project IRI rules, LinkML YAML, or
another format) is the profile's decision; the module guarantees only
the walk, the per-document grouping, and that a refusal row never
reaches the serializer.

A serializer may leave, per document, which values it wrote
(`claims`). run() then hands them to the provenance writer it was
given (provenance.py), and the provenance of the written values goes
to a file of its own beside the graph.

What people decided about the rows of the harvest (gold.py) is read
here, after the harvest is, and kept beside the value each decision
concerns: the provenance writer records it with the value's provenance,
and a serializer that declares a `decisions` dict gets it as
{document: {tuple name: [decision]}} to write itself. No row changes and
none is left out because of it. A decision about a row the harvest does
not hold is counted and named in the log.

run() concatenates the output of every document whose serializer
returned something and writes it to the output path. It raises
ValueError and leaves that path untouched when no document produced
anything. The check runs unconditionally at the end of a GPU job, so
a run that ended in a counted exception still yields a graph; without
the check, an empty or unreadable harvest directory would overwrite a
valid graph from an earlier run with nothing.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

from .. import jsonl
from . import gold as golden

log = logging.getLogger(__name__)

# How many rows a log line names before it says how many more.
NAMED = 10


def collect(jsonl_dir: Path) -> dict:
    """{document name: [accepted tuple rows]} from a harvest directory."""
    out: dict = {}
    for path in sorted(Path(jsonl_dir).glob("*.jsonl")):
        rows = []
        for line in jsonl.read(path):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                log.warning("serialize: %s carries an unreadable line — skipped",
                            path.name)
                continue
            if row.get("kind") == "tuple":
                rows.append(row)
        out[path.stem] = rows
    return out


def count_decisions(decided: dict) -> int:
    """How many field decisions {document: {tuple name: [decision]}} holds."""
    return sum(len(found) for rows in decided.values()
               for found in rows.values())


def read_decisions(held, harvest: dict, source=None) -> dict:
    """What *held* decided about the rows of *harvest*, counted in the log.

    {document: {tuple name: [decision]}}. A decision about a row the harvest
    does not hold is named, up to `NAMED` of them, and applied to nothing.
    """
    decided, strays = golden.decisions_in(held, harvest)
    given = count_decisions(decided)
    where = f" from {source}" if source else ""
    log.info("serialize: %d decision(s) on %d row(s) of %d document(s) "
             "read%s", given,
             sum(len(rows) for rows in decided.values()), len(decided), where)
    if strays:
        named = [f"{document}/{name}/{parameter}"
                 for document, name, parameter in sorted(
                     strays, key=lambda key: tuple(map(str, key)))]
        more = len(named) - NAMED
        log.warning("serialize: %d decision(s) on %d row(s) are about rows "
                    "the harvest does not hold, recorded nowhere: %s%s",
                    sum(strays.values()), len(strays),
                    ", ".join(named[:NAMED]),
                    f" and {more} more" if more > 0 else "")
    return decided


def run(jsonl_dir: Path, out_path: Path,
        serializer: Callable[[str, list], Optional[str]],
        provenance=None, gold=None, gold_source=None) -> dict:
    """Serialize every document's harvest; returns {name: tuple count}.

    A serializer returning None skips its document (nothing to say is a
    normal outcome, e.g. a plan without a single accepted tuple).

    *provenance* is a `provenance.Writer`. A serializer that leaves what it
    wrote per document in its `claims` gets the provenance of those values
    written beside the graph; one that leaves nothing gets none.

    *gold* is the decisions of people (`gold.Gold`); *gold_source* says
    where they were read from, for the log. They are looked up after the
    harvest is collected and not in `collect`, which the review page and
    `evaluate` read their rows from: counting a decision against a harvest
    that already held it would hide the row it was made on.
    """
    harvest = collect(jsonl_dir)
    decided = (read_decisions(gold, harvest, gold_source)
               if gold is not None else {})
    given = count_decisions(decided)
    takes = isinstance(getattr(serializer, "decisions", None), dict)
    if takes:
        # Always set, so a serializer used for a second run holds none of
        # the first run's decisions.
        serializer.decisions = decided
    elif given and provenance is None:
        log.warning("serialize: %d decision(s) read and recorded nowhere: "
                    "this run writes no provenance file and its serializer "
                    "takes none", given)
    parts: list = []
    counts: dict = {}
    for name, rows in harvest.items():
        rendered = serializer(name, rows)
        claimed = getattr(serializer, "claims", None)
        entry = claimed.pop(name, None) if isinstance(claimed, dict) else None
        if rendered:
            parts.append(rendered)
            counts[name] = len(rows)
            if provenance is not None and entry:
                from .provenance import read_stamp
                provenance.add(name, entry, read_stamp(jsonl_dir, name),
                               transcribed=bool(entry.get("transcribed")),
                               decisions=decided.get(name))
    out_path = Path(out_path)
    if not parts:
        # Refusing to write is the point. This runs unconditionally at the end
        # of a GPU job so that a run with a counted exception still yields its
        # graph, and the same unconditional call would otherwise truncate a
        # good TTL to nothing whenever the harvest directory was empty or
        # unreadable.
        raise ValueError(f"nothing to serialize from {jsonl_dir} — "
                         f"{out_path} left as it was")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(parts), encoding="utf-8")
    log.info("serialize: %d document(s) with tuples -> %s",
             len(counts), out_path)
    from .provenance import path_for
    beside = path_for(out_path)
    written = provenance.write(beside) if provenance is not None else None
    if written is not None:
        log.info("serialize: provenance of %d value(s) from %d document(s) "
                 "-> %s", provenance.values, provenance.documents, written)
    elif beside.exists():
        # Not removed: it may be wanted. But it is not this graph's.
        log.warning("serialize: %s was not written by this run and "
                    "describes an earlier graph", beside)
    if provenance is not None and given:
        # Counted against what was read, so a decision on a document the
        # serializer wrote nothing for is among those left out.
        log.info("serialize: %d of %d decision(s) recorded beside their "
                 "value in the provenance file; %d decision(s) are about "
                 "rows the writer left out of the graph",
                 provenance.decisions, given, given - provenance.decisions)
    return counts


def validate(out_path: Path, shapes: list, top: int = 12) -> dict:
    """Hold the written graph against the profile's SHACL shapes.

    A report, not a gate: the full text goes next to the graph as
    `<name>.shacl.txt` and the most frequent kinds of violation go to the
    log. The graph stays written either way. The harvest is the durable
    artifact and a graph the shapes reject is still the one to look at.
    """
    from docpipe import ontology
    out_path = Path(out_path)
    report = ontology.shacl_report(out_path, shapes)
    text_path = out_path.with_name(out_path.name + ".shacl.txt")
    text_path.write_text(report["text"], encoding="utf-8")
    log.info("shacl: %s against %d shapes file(s): conforms=%s, %d "
             "violation(s) -> %s", out_path.name, len(shapes),
             report["conforms"], report["violations"], text_path)
    for (component, path, node), count in report["counts"][:top]:
        log.info("shacl:   %6d  %s  path %s  on %s", count, component, path,
                 node)
    return report
