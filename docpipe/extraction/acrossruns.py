"""Disagreement across runs in the graph (owner decision 2026-11-17, from the
literature on run-to-run noise, Ilves et al. 2026): the rows of further
harvests of the same plans take part in a comparison and in nothing else.
The graph stays this run's: a row of another run never becomes a node or a
node's row, and no model is asked.

A row of another run is read like one of this run (`serialize.collect`, the
same admission in `graph.Writer._numbers`) and marked with its run, the name
of its directory, in the key `run`; this run's rows carry no such key.

Place of a row, the key that decides "the same place in the document": the
passage (`readings.place`) and, where the row carries `at` with a line, that
line and cell; else the passage and the quote. A row without a passage has no
place and is compared by its node only.
"""
from collections import Counter
from pathlib import Path
from typing import Callable, Optional

from .readings import place, rounds_together, wording_key


def read_runs(dirs) -> dict:
    """{run name: {document: [rows marked with `run`]}} of the harvest
    directories *dirs*; the name is the directory's, made unique with a
    number where two directories share one."""
    from .serialize import collect
    out: dict = {}
    for one in dirs or ():
        name = base = Path(one).name or str(one)
        number = 1
        while name in out:
            number += 1
            name = f"{base}#{number}"
        out[name] = {doc: [dict(row, run=name) for row in rows]
                     for doc, rows in collect(Path(one)).items()}
    return out


def place_key(row: dict) -> Optional[tuple]:
    owner = place(row)
    if owner == (None, None):
        return None
    at = row.get("at")
    if isinstance(at, dict) and at.get("line") is not None:
        return owner, at.get("line"), at.get("cell")
    return owner, " ".join(str(row.get("quote") or "").split())


def differing(here: dict, other: dict, extra: tuple = ()) -> list:
    """The coordinates two rows of one place give differently: each key
    that has a `<key>_state` on either row, and the *extra* keys (the
    wording fields of the box); "other" where only the address differs."""
    keys = {key[:-len("_state")] for row in (here, other) for key in row
            if key.endswith("_state")} | set(extra)
    found = sorted(key for key in keys if here.get(key) != other.get(key))
    return found or ["other"]


def compare(*, rows: list, kept: dict, others: list, address: Callable,
            fold: Callable, wording: tuple, tolerance: float,
            drawn_tolerance: Optional[float]) -> tuple:
    """(contested, seen, counts) for the nodes {address: row} a document
    keeps for one box of numbers, against the rows of other runs.

    *rows* are this run's admitted rows, *others* [(run, rows)].
    contested {address: {"number": [(run, number)], "coordinates": [(run,
    [keys], number)]}}: "number" where a row of another run sits at the node
    with a number beyond the rounding rule (`readings.rounds_together`, the
    comparison `settle` makes); "coordinates" where a row of another run at
    the place of one of this run's rows, with its number, sits at another
    node. *seen* are the nodes some row of another run reached; *counts*
    counts the rows of other runs that reach no node and no place (rows).
    """
    def candidates(row: dict) -> set:
        found = {address(row)}
        label = wording_key(row, wording)
        if label:
            found.add(address(row, fold(label)))
        found.discard(None)
        return found

    here: dict = {}
    for row in rows:
        iri = next((one for one in candidates(row) if one in kept), None)
        key = place_key(row)
        if iri is not None and key is not None:
            here.setdefault((row.get("parameter"), key,
                             row.get("value_target")), []).append((iri, row))
    contested: dict = {}
    seen: set = set()
    counts: Counter = Counter()
    for run, rows_of_run in others:
        for other in rows_of_run:
            found = candidates(other)
            reached = False
            for iri in found:
                if iri not in kept:
                    continue
                reached = True
                seen.add(iri)
                a, b = kept[iri].get("value_target"), other.get("value_target")
                if a is None or b is None or a == b:
                    continue
                if not rounds_together(
                        min(a, b), max(a, b), tolerance=tolerance,
                        drawn_tolerance=drawn_tolerance,
                        drawn=bool(kept[iri].get("drawn")
                                   or other.get("drawn"))):
                    contested.setdefault(iri, {}).setdefault(
                        "number", []).append((run, b))
            key = place_key(other)
            pairs = here.get((other.get("parameter"), key,
                              other.get("value_target"))) if key else None
            for iri, row in pairs or ():
                reached = True
                seen.add(iri)
                if iri in found:
                    continue
                contested.setdefault(iri, {}).setdefault(
                    "coordinates", []).append(
                    (run, differing(row, other, wording),
                     other.get("value_target")))
            if not reached:
                counts["rows without counterpart"] += 1
    return contested, seen, counts


def mark_lines(found: dict) -> list:
    """The lines a node's mark says about its disagreement, English."""
    def shown(number):
        return f"{number:g}" if isinstance(number, (int, float)) else number

    lines = []
    for run, number in found.get("number") or ():
        lines.append(f"run {run} reads {shown(number)} at this node")
    for run, keys, number in found.get("coordinates") or ():
        lines.append(f"run {run} reads {shown(number)} at this place with "
                     f"another {', '.join(keys)}")
    return lines
