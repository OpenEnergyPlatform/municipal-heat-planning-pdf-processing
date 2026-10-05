"""
evaluate.py: Holds a harvest against what people decided about it.

    docpipe evaluate HARVEST_DIR --gold gold.jsonl
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --baseline OTHER_DIR
    docpipe evaluate HARVEST_DIR --gold gold.jsonl --min-precision 0.9
    docpipe evaluate HARVEST_DIR --diff OTHER_DIR
    docpipe evaluate HARVEST_DIR --diff OTHER_DIR --top 10 --max-gone 0.05

Precision is counted field by field over the rows somebody decided
(`gold.py`): of the values, units and coordinates a person looked at, how
many does the document say. Recall is counted only over the documents
somebody read whole for a parameter: of the values the document states,
how many does the harvest carry.

Every share comes with its 95 percent interval (Wilson). Forty decided
rows with two wrong are 95 percent, and anything between 84 and 99: a
change that moves precision inside that range has shown nothing, and the
interval is what says so. What nobody decided is counted as undecided and
is in no share.

The numbers are split by parameter, by the level the harvest gave a value
(`trust.py`) and by where it was read (text, table or figure), because
those are the splits a decision hangs on: whether level C may be left out
of a graph is a question about the precision of level C.

`--baseline` holds a second harvest of the same documents beside this one,
row by row: which rows both carry, which only one does, and what was
decided about those. That is the comparison a replayed run is made for.

`--diff` needs no decisions. It holds this harvest against another one of
the same documents, OTHER_DIR being the baseline, and says what changed:
per parameter and per field (the value, the unit, each coordinate) how
many rows are the same, read differently, gone (only the baseline has
them) and new (only this harvest has them); how the states of the
coordinates of the rows both carry moved (read to unbacked, counted in
coordinates); how their trust levels moved; and the largest changes, each
with its quote and both readings side by side. Rows are paired as
`--baseline` pairs them, by document, `identity.tuple_id` and parameter. It
exits with 0 whatever it finds; only a ceiling (`--max-changed`,
`--max-gone`, shares of the baseline's rows) makes it exit with 1. Levels
are counted as `evaluate` counts them: a document is transcribed only if a
database (`--db`, else the profile's) says so, and the report says how many
it took as transcribed.

Nothing here writes into a harvest or decides anything about a value.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Optional, Sequence

from ..profile import add_profile_argument, program, resolve_profile
from . import gold as golden
from . import trust

Z95 = 1.959963984540054


def wilson(hits: int, total: int, z: float = Z95) -> Optional[tuple]:
    """The interval the true share lies in, given *hits* of *total*."""
    if total <= 0:
        return None
    share = hits / total
    spread = z * z / total
    middle = share + spread / 2
    width = z * math.sqrt(share * (1 - share) / total
                          + spread / (4 * total))
    # The two ends are exact, not a rounding away from them.
    low = 0.0 if hits == 0 else max(0.0, (middle - width) / (1 + spread))
    high = 1.0 if hits == total else min(1.0, (middle + width) / (1 + spread))
    return low, high


class Count:
    """How many of something were decided correct, wrong, or not at all."""

    __slots__ = ("correct", "wrong", "undecided")

    def __init__(self):
        self.correct = self.wrong = self.undecided = 0

    def add(self, verdict: Optional[str]) -> None:
        if verdict == golden.CORRECT:
            self.correct += 1
        elif verdict == golden.WRONG:
            self.wrong += 1
        else:
            self.undecided += 1

    @property
    def decided(self) -> int:
        return self.correct + self.wrong

    @property
    def share(self) -> Optional[float]:
        return self.correct / self.decided if self.decided else None

    def as_dict(self) -> dict:
        interval = wilson(self.correct, self.decided)
        return {"correct": self.correct, "wrong": self.wrong,
                "undecided": self.undecided, "precision": self.share,
                "interval": list(interval) if interval else None}


def row_verdict(verdicts: dict) -> Optional[str]:
    """One row from its fields: wrong as soon as one field is, correct
    once every field was decided and none is wrong."""
    said = list(verdicts.values())
    if golden.WRONG in said:
        return golden.WRONG
    if said and all(verdict == golden.CORRECT for verdict in said):
        return golden.CORRECT
    return None


def _counts(table: dict, key) -> Count:
    if key not in table:
        table[key] = Count()
    return table[key]


def evaluate(rows_by_document: dict, gold: golden.Gold, *,
             transcribed: Sequence[str] = ()) -> dict:
    """The report of one harvest. *transcribed* names the documents whose
    pages a model transcribed: their values are level B at best."""
    fields: dict = {}
    parameters: dict = {}
    levels: dict = {}
    tiers: dict = {}
    rows_total = Count()
    recall: dict = {}

    for document, rows in sorted(rows_by_document.items()):
        covered: set = set()
        stated: set = set()         # what a found row says, each said once
        for row in rows:
            name = row.get("parameter")
            entry = parameters.setdefault(name, {
                "rows": Count(), "fields": {}})
            verdicts = {field: gold.verdict(document, row, field, rows)
                        for field in golden.fields_of(row)}
            for field, verdict in verdicts.items():
                _counts(fields, field).add(verdict)
                _counts(entry["fields"], field).add(verdict)
            whole = row_verdict(verdicts)
            entry["rows"].add(whole)
            rows_total.add(whole)
            level = trust.trust(
                row, transcribed=document in transcribed)["level"]
            _counts(levels, level).add(whole)
            _counts(tiers, row.get("tier")).add(whole)

            if not gold.is_checked(document, name):
                continue
            tally = recall.setdefault(name, {
                "documents": set(), "found": 0, "missed": 0,
                "undecided": 0})
            tally["documents"].add(document)
            facts = gold.missing_for(document, name)
            hit = [index for index, fact in enumerate(facts)
                   if golden.covers(fact, row)]
            # The whole row, as precision counts it: the right number
            # under the wrong year is not the value the document states.
            if whole == golden.WRONG:
                continue                # carried, and not what is stated
            if whole == golden.CORRECT or hit:
                # The document states a value once however often the
                # harvest read it: a second row that says the same thing
                # for the same coordinates is the same found value.
                said = (name, json.dumps(
                    [row.get(field) for field in golden.fields_of(row)],
                    sort_keys=True, default=str))
                if said not in stated:
                    stated.add(said)
                    tally["found"] += 1
                covered.update((name, index) for index in hit)
            else:
                tally["undecided"] += 1

        # What the document states and no row carries. Also for a
        # parameter the harvest has no row of at all in this document.
        for name in {fact["parameter"]
                     for fact in gold.missing if fact["document"] == document}:
            if not gold.is_checked(document, name):
                continue
            tally = recall.setdefault(name, {
                "documents": set(), "found": 0, "missed": 0,
                "undecided": 0})
            tally["documents"].add(document)
            tally["missed"] += sum(
                1 for index, _fact in enumerate(
                    gold.missing_for(document, name))
                if (name, index) not in covered)
    # A document read whole in which the harvest carries nothing and
    # nothing is missing still counts as read.
    for document, marks in gold.checked.items():
        if document not in rows_by_document:
            continue
        for name in marks:
            if name is not None and name not in recall:
                recall[name] = {"documents": {document}, "found": 0,
                                "missed": 0, "undecided": 0}
            elif name is not None:
                recall[name]["documents"].add(document)

    def recalled(tally: dict) -> dict:
        stated = tally["found"] + tally["missed"]
        interval = wilson(tally["found"], stated)
        return {"documents": len(tally["documents"]),
                "found": tally["found"], "missed": tally["missed"],
                "undecided": tally["undecided"],
                "recall": tally["found"] / stated if stated else None,
                "interval": list(interval) if interval else None}

    overall = {"documents": set(), "found": 0, "missed": 0, "undecided": 0}
    for tally in recall.values():
        overall["documents"] |= tally["documents"]
        for key in ("found", "missed", "undecided"):
            overall[key] += tally[key]

    return {
        "documents": len(rows_by_document),
        "rows": rows_total.as_dict(),
        "fields": {name: count.as_dict()
                   for name, count in sorted(fields.items())},
        "levels": {name: count.as_dict()
                   for name, count in sorted(levels.items())},
        "tiers": {str(name): count.as_dict() for name, count in sorted(
            tiers.items(), key=lambda item: str(item[0]))},
        "parameters": {
            str(name): {
                "rows": entry["rows"].as_dict(),
                "fields": {field: count.as_dict() for field, count
                           in sorted(entry["fields"].items())},
                "recall": recalled(recall[name]) if name in recall else None}
            for name, entry in sorted(parameters.items(),
                                      key=lambda item: str(item[0]))},
        "recall": recalled(overall),
        "recall_by_parameter": {str(name): recalled(tally) for name, tally
                                in sorted(recall.items(),
                                          key=lambda item: str(item[0]))},
    }


# What a row is, held against the other harvest's: it reads the same, it
# reads differently, only the baseline carries it, only this harvest does.
SAME, CHANGED, GONE, NEW = "same", "changed", "gone", "new"
KINDS = (SAME, CHANGED, GONE, NEW)


def _named(harvest: dict) -> dict:
    """{row_key: [rows]} of a harvest, the rows of one name in file order."""
    found: dict = {}
    for document, rows in harvest.items():
        for row in rows:
            found.setdefault(golden.row_key(document, row), []).append(row)
    return found


def _reads_the_same(left: dict, right: dict) -> bool:
    return golden.same(left.get(golden.VALUE), right.get(golden.VALUE)) \
        and golden.same_signature(golden.signature(left),
                                  golden.signature(right))


def pair_rows(rows_by_document: dict, baseline: dict):
    """(kind, key, row, other) for every row of two harvests.

    A row is the same row when its document, its name and its parameter
    are (`gold.row_key`). Where several rows of a document share a name,
    those that read the same in every field are paired first, and what is
    left on both sides is paired in file order as a row read differently.
    What one harvest carries and the other does not is `gone` (only the
    baseline has it: `other` is its row, `row` is None) or `new` (only this
    harvest has it: `row` is its row, `other` is None). The order is the
    same every time.
    """
    now, before = _named(rows_by_document), _named(baseline)
    for key in sorted(set(now) | set(before), key=str):
        mine, theirs = list(now.get(key, ())), list(before.get(key, ()))
        for row in list(mine):
            twin = next((index for index, other in enumerate(theirs)
                         if _reads_the_same(row, other)), None)
            if twin is not None:
                yield SAME, key, row, theirs.pop(twin)
                del mine[next(index for index, own in enumerate(mine)
                              if own is row)]
        paired = min(len(mine), len(theirs))
        for row, other in zip(mine[:paired], theirs[:paired]):
            yield CHANGED, key, row, other
        for row in mine[paired:]:
            yield NEW, key, row, None
        for other in theirs[paired:]:
            yield GONE, key, None, other


def compare(rows_by_document: dict, baseline: dict,
            gold: golden.Gold) -> dict:
    """This harvest beside another of the same documents, row by row.

    A row is the same row when its document, its name and its parameter
    are. Where several rows of a document share a name, those that read
    the same in every field are paired first, and what is left on both
    sides is a row read differently. What only one harvest carries is
    counted with what was decided about its value: a row that was correct
    and is gone is a loss, one that was wrong and is gone is not.
    """
    gained, lost, kept, changed = Count(), Count(), 0, 0
    for kind, key, row, other in pair_rows(rows_by_document, baseline):
        if kind in (SAME, CHANGED):
            kept += 1
            changed += kind == CHANGED
        elif kind == NEW:
            gained.add(gold.verdict(key[0], row, golden.VALUE,
                                    rows_by_document.get(key[0])))
        else:
            lost.add(gold.verdict(key[0], other, golden.VALUE,
                                  baseline.get(key[0])))
    return {"kept": kept, "changed": changed,
            "gained": gained.as_dict(), "lost": lost.as_dict()}


# --------------------------------------------------------- two harvests, bare

# The state of a coordinate that one side's row does not carry at all.
ABSENT = "(none)"
LEVELS = (trust.LEVEL_A, trust.LEVEL_B, trust.LEVEL_C)
DIFF_TOP = 20


def _tally() -> dict:
    return {kind: 0 for kind in KINDS}


def _field_names(*rows: dict) -> list:
    """The fields the rows carry between them: the value, the unit where
    there is one, then each coordinate by name."""
    seen: set = set()
    for row in rows:
        seen.update(golden.fields_of(row))
    return [name for name in (golden.VALUE, golden.UNIT) if name in seen] \
        + sorted(seen - {golden.VALUE, golden.UNIT})


def _state(row: dict, coordinate: str) -> str:
    return row.get(f"{coordinate}_state") or ABSENT


def _level(row: dict, document: str, transcribed: set) -> str:
    """The level the harvest gave a row, as `evaluate` counts it: a row of a
    document whose pages a model transcribed is a B at best."""
    return trust.trust(row, transcribed=document in transcribed)["level"]


def _reading(row: dict, level: str) -> dict:
    """What a row says, for putting two of them side by side."""
    return {"value": row.get(golden.VALUE), "unit": row.get(golden.UNIT),
            "coordinates": {name: {"answer": row.get(name),
                                   "state": row.get(f"{name}_state")}
                            for name in golden.coordinates(row)},
            "level": level}


def diff(rows_by_document: dict, baseline: dict, *,
         transcribed: Sequence[str] = (), top: int = DIFF_TOP) -> dict:
    """What changed between two harvests of the same documents, without a
    decision about either.

    Counted in rows, except where it says coordinates or documents.
    `rows` and `parameters` hold the rows that are the same, changed, gone
    and new (`pair_rows`); `fields` the same for every field a row carries
    (the value, the unit, each coordinate's answer), a row counted under
    each field it carries; `transitions` how the states of the coordinates
    of the rows both harvests carry moved; `levels` how the trust level of
    those rows moved, and the level of the rows gone and new; `largest` the
    *top* rows of both harvests that differ most, each with both readings.
    A document is changed when one of its rows reads differently, moved in
    a coordinate state or in its level, is gone or is new.

    A row whose quote or written value changed is not the same row any
    more: it is gone and another is new. A row that reads differently is
    one whose quote and written value stand and whose unit, parsed value or
    coordinates do not. One that reads the same can still have a coordinate
    that moved from read to unbacked or a level that moved, and those are
    counted under `transitions` and `levels`.
    """
    rows, parameters, fields = _tally(), {}, {}
    moves: dict = {}                    # (coordinate, from, to) -> coordinates
    kept_states = 0
    level_moves: dict = {}              # (from, to) -> rows
    kept_levels = 0
    gone_levels = {level: 0 for level in LEVELS}
    new_levels = {level: 0 for level in LEVELS}
    differing: list = []
    changed_documents: set = set()
    held = set(transcribed)

    for kind, key, row, other in pair_rows(rows_by_document, baseline):
        document, name, parameter = key
        entry = parameters.setdefault(str(parameter), {
            "rows": _tally(), "fields": {}})
        rows[kind] += 1
        entry["rows"][kind] += 1
        if kind != SAME:
            changed_documents.add(document)
        if kind in (GONE, NEW):
            only = other if kind == GONE else row
            # Each field once: a numeric row names its unit twice, as the
            # unit of the value and as the coordinate behind unit_state.
            for field in _field_names(only):
                for table in (fields, entry["fields"]):
                    table.setdefault(field, _tally())[kind] += 1
            by_level = gone_levels if kind == GONE else new_levels
            by_level[_level(only, document, held)] += 1
            continue

        changes = []
        for field in _field_names(row, other):
            said = SAME if golden.same(row.get(field), other.get(field)) \
                else CHANGED
            if said == CHANGED:
                changes.append(field)
            for table in (fields, entry["fields"]):
                table.setdefault(field, _tally())[said] += 1
        for coordinate in sorted(set(golden.coordinates(row))
                                 | set(golden.coordinates(other))):
            was, is_now = _state(other, coordinate), _state(row, coordinate)
            if was == is_now:
                kept_states += 1
                continue
            move = (coordinate, was, is_now)
            moves[move] = moves.get(move, 0) + 1
            changes.append(f"{coordinate}_state")
        was = _level(other, document, held)
        is_now = _level(row, document, held)
        if was == is_now:
            kept_levels += 1
        else:
            level_moves[(was, is_now)] = level_moves.get(
                (was, is_now), 0) + 1
            changes.append("level")
        if changes:
            # A document whose coordinates moved without a row changing is
            # a document that changed: a re-check moves nothing else.
            changed_documents.add(document)
            differing.append((len(changes), document, str(parameter), name,
                              parameter, changes, row, other, was, is_now))

    # Most differences first; a tie keeps the order the pairs came in.
    differing.sort(key=lambda found: (-found[0],) + found[1:4])
    largest = [{"document": document, "parameter": parameter,
                "tuple": name, "quote": row.get("quote"), "size": size,
                "changes": changes, "baseline": _reading(other, was),
                "harvest": _reading(row, is_now)}
               for size, document, _text, name, parameter, changes, row,
               other, was, is_now in differing[:top]]

    by_coordinate: dict = {}
    total_moves: dict = {}
    for (coordinate, was, is_now), count in sorted(moves.items()):
        said = f"{was}>{is_now}"
        by_coordinate.setdefault(coordinate, {})[said] = count
        total_moves[said] = total_moves.get(said, 0) + count
    moved_levels = sum(level_moves.values())

    return {
        "baseline": {"documents": len(baseline),
                     "rows": rows[SAME] + rows[CHANGED] + rows[GONE]},
        "harvest": {"documents": len(rows_by_document),
                    "rows": rows[SAME] + rows[CHANGED] + rows[NEW]},
        "documents": {
            "both": len(set(rows_by_document) & set(baseline)),
            "gone": len(set(baseline) - set(rows_by_document)),
            "new": len(set(rows_by_document) - set(baseline)),
            "changed": len(changed_documents & set(rows_by_document)
                           & set(baseline))},
        "rows": rows,
        "parameters": {name: {"rows": entry["rows"],
                              "fields": dict(sorted(entry["fields"].items()))}
                       for name, entry in sorted(parameters.items())},
        "fields": dict(sorted(fields.items())),
        "transitions": {
            "coordinates": kept_states + sum(moves.values()),
            "kept": kept_states, "moved": sum(moves.values()),
            "moves": dict(sorted(total_moves.items(),
                                 key=lambda item: (-item[1], item[0]))),
            "by_coordinate": by_coordinate},
        "levels": {
            "rows": kept_levels + moved_levels, "kept": kept_levels,
            "moved": moved_levels,
            "moves": {f"{was}>{is_now}": count for (was, is_now), count
                      in sorted(level_moves.items())},
            "gone": gone_levels, "new": new_levels,
            # In documents. Without a database none is known, and every
            # text-located row counts as an A: the report says so.
            "transcribed": len(held & (set(rows_by_document)
                                       | set(baseline)))},
        "differing": len(differing),
        "largest": largest,
    }


def _tail(text, width: int) -> str:
    """The end of a name too long for its column: what tells two
    parameters apart is the last part of their address."""
    text = str(text)
    return text if len(text) <= width else "..." + text[-(width - 3):]


def _head(text, width: int) -> str:
    """The start of a passage too long for a line: the row is named by its
    quote, and the first words are what find it again."""
    text = " ".join(str(text or "").split())
    return text if len(text) <= width else text[:width - 3] + "..."


def _tally_line(label, tally: dict) -> str:
    return (f"  {_tail(label, 44):<44} {tally[SAME]:>6} same "
            f"{tally[CHANGED]:>6} changed {tally[GONE]:>6} gone "
            f"{tally[NEW]:>6} new")


def _said(reading: dict) -> str:
    unit = f" {reading['unit']}" if reading.get("unit") else ""
    parts = [f"{reading['value']}{unit}"]
    parts += [f"{name}={entry['answer']} ({entry['state']})"
              for name, entry in reading["coordinates"].items()]
    parts.append(f"level {reading['level']}")
    return "   ".join(parts)


def render_diff(report: dict) -> str:
    base, now, documents = (report["baseline"], report["harvest"],
                            report["documents"])
    lines = [f"baseline  {base['documents']} document(s), "
             f"{base['rows']} row(s)",
             f"harvest   {now['documents']} document(s), "
             f"{now['rows']} row(s)",
             f"{documents['both']} document(s) in both, "
             f"{documents['changed']} of them with a row that reads "
             f"differently, moved in a state or a level, is gone or is "
             f"new; {documents['gone']} only in the baseline, "
             f"{documents['new']} only in the harvest"]
    lines += ["", "rows: same, read differently (changed), only in the "
                  "baseline (gone), only in the harvest (new)",
              _tally_line("all", report["rows"])]
    lines += ["", "rows by parameter, and under each the fields that are "
                  "not the same in every row (a row counts under each "
                  "field it carries)"]
    for name, entry in report["parameters"].items():
        lines.append(_tally_line(name, entry["rows"]))
        for field, tally in entry["fields"].items():
            if tally[SAME] != sum(tally.values()):
                lines.append(_tally_line(f"    {field}", tally))
    lines += ["", "rows by field, over all parameters"]
    lines += [_tally_line(field, tally)
              for field, tally in report["fields"].items()]

    moves = report["transitions"]
    lines += ["", f"coordinate states, over the {moves['coordinates']} "
                  f"coordinate(s) of the rows both harvests carry",
              f"  {moves['kept']} coordinate(s) kept their state, "
              f"{moves['moved']} moved"]
    for coordinate, said in moves["by_coordinate"].items():
        lines.append(f"  {coordinate}: " + ", ".join(
            f"{move.replace('>', ' > ')} {count}" for move, count
            in sorted(said.items(), key=lambda item: (-item[1], item[0]))))

    levels = report["levels"]
    lines += ["", f"trust levels, over the {levels['rows']} row(s) both "
                  f"harvests carry",
              f"  {levels['kept']} row(s) kept their level, "
              f"{levels['moved']} moved"
              + (": " + ", ".join(
                  f"{move.replace('>', ' > ')} {count}"
                  for move, count in levels["moves"].items())
                 if levels["moves"] else "")]
    for label in ("gone", "new"):
        lines.append(f"  {label} row(s) by level: " + ", ".join(
            f"{level} {levels[label][level]}" for level in LEVELS))
    if levels["transcribed"]:
        lines.append(f"  {levels['transcribed']} document(s) of the two "
                     f"harvests were transcribed by a model: their rows are "
                     f"level B at best")
    else:
        lines.append("  no document of the two harvests is known as "
                     "transcribed by a model (--db names them): every "
                     "text-located row counts as level A")

    shown, differing = len(report["largest"]), report["differing"]
    lines.append("")
    if differing:
        lines.append(f"largest changes: {shown} of the {differing} row(s) "
                     f"both harvests carry that differ in a reading, a "
                     f"state or a level")
    else:
        lines.append("largest changes: no row both harvests carry differs "
                     "in a reading, a state or a level")
    for number, found in enumerate(report["largest"], 1):
        lines += [f"  {number}. {found['document']}  "
                  f"{_tail(found['parameter'], 40)}  {found['tuple']}  "
                  f"({found['size']} difference(s): "
                  f"{', '.join(found['changes'])})",
                  f"       quote     {_head(found['quote'], 100)}",
                  f"       baseline  {_said(found['baseline'])}",
                  f"       harvest   {_said(found['harvest'])}"]
    return "\n".join(lines)


def moved_too_far(report: dict, max_changed: Optional[float],
                  max_gone: Optional[float]) -> list:
    """What the comparison exceeds, as shares of the baseline's rows. A
    share nobody can count (the baseline has no row) exceeds a ceiling that
    was asked for: a ceiling that passes on no evidence is not one."""
    held = report["baseline"]["rows"]
    over = []
    for kind, ceiling in ((CHANGED, max_changed), (GONE, max_gone)):
        if ceiling is None:
            continue
        count = report["rows"][kind]
        if not held:
            over.append(f"the share of baseline rows that are {kind} is not "
                        f"known (the baseline has no row), the ceiling is "
                        f"{ceiling}")
        elif count / held > ceiling:
            over.append(f"{count} of the baseline's {held} row(s) are "
                        f"{kind} ({count / held:.3f}), the ceiling is "
                        f"{ceiling}")
    return over


# ---------------------------------------------------------------- the command

def _share(entry: dict, key: str = "precision") -> str:
    share = entry.get(key)
    if share is None:
        return "    -          "
    low, high = entry["interval"]
    return f"{share:6.1%} [{low:4.0%},{high:5.0%}]"


def render(report: dict, comparison: Optional[dict] = None) -> str:
    lines = [f"{report['documents']} document(s)"]

    def line(label: str, entry: dict) -> str:
        return (f"  {label:<44.44} {_share(entry)}  "
                f"{entry['correct']:>5} correct {entry['wrong']:>5} wrong "
                f"{entry['undecided']:>6} undecided")

    lines += ["", "precision, whole rows", line("all", report["rows"])]
    for title, key in (("by level", "levels"), ("by origin", "tiers"),
                       ("by field", "fields")):
        lines += ["", f"precision {title}"]
        lines += [line(name, entry) for name, entry in report[key].items()]
    lines += ["", "precision by parameter (whole rows)"]
    lines += [line(name, entry["rows"])
              for name, entry in report["parameters"].items()]

    lines += ["", "recall, over the documents read whole"]
    overall = report["recall"]
    if not overall["documents"]:
        lines.append("  no document is marked as read whole: nothing is "
                     "known about what the harvest lacks")
    else:
        def recall_line(label: str, entry: dict) -> str:
            return (f"  {label:<44.44} {_share(entry, 'recall')}  "
                    f"{entry['found']:>5} found {entry['missed']:>5} missed "
                    f"in {entry['documents']} document(s)")
        lines.append(recall_line("all", overall))
        lines += [recall_line(name, entry) for name, entry
                  in report["recall_by_parameter"].items()]

    if comparison is not None:
        gained, lost = comparison["gained"], comparison["lost"]
        lines += ["", "against the baseline",
                  f"  {comparison['kept']} row(s) in both, "
                  f"{comparison['changed']} of them with another content",
                  f"  gained {gained['correct'] + gained['wrong'] + gained['undecided']}: "
                  f"{gained['correct']} correct, {gained['wrong']} wrong, "
                  f"{gained['undecided']} undecided",
                  f"  lost   {lost['correct'] + lost['wrong'] + lost['undecided']}: "
                  f"{lost['correct']} correct, {lost['wrong']} wrong, "
                  f"{lost['undecided']} undecided"]
    return "\n".join(lines)


def below(report: dict, min_precision: Optional[float],
          min_recall: Optional[float]) -> list:
    """What the report falls short of. A share nobody can count (nothing
    decided, nothing read whole) falls short of a floor that was asked
    for: a floor that passes on no evidence is not one."""
    short = []
    if min_precision is not None:
        got = report["rows"]["precision"]
        if got is None or got < min_precision:
            short.append(f"precision is "
                         f"{'not known' if got is None else format(got, '.3f')}"
                         f", the floor is {min_precision}")
    if min_recall is not None:
        got = report["recall"]["recall"]
        if got is None or got < min_recall:
            short.append(f"recall is "
                         f"{'not known' if got is None else format(got, '.3f')}"
                         f", the floor is {min_recall}")
    return short


def _ceiling(text: str) -> float:
    try:
        ceiling = float(text)
    except ValueError:
        ceiling = math.nan
    if not 0.0 <= ceiling <= 1.0:       # nan is in neither
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a share between 0 and 1")
    return ceiling


def _limit(text: str) -> int:
    try:
        limit = int(text)
    except ValueError:
        limit = -1
    if limit < 0:
        raise argparse.ArgumentTypeError(
            f"{text!r} is not a number of rows, 0 or more")
    return limit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=program("docpipe.extraction.evaluate"),
        description="Precision and recall of a harvest, counted against "
                    "the decisions people made about it; or, with --diff, "
                    "what changed between two harvests.")
    add_profile_argument(parser)
    parser.add_argument("harvest", type=Path, help="harvest directory")
    parser.add_argument("--gold", type=Path,
                        help=f"decisions file (default: {golden.FILE_NAME} "
                             f"beside the harvest directory)")
    parser.add_argument("--baseline", type=Path,
                        help="another harvest of the same documents to "
                             "hold this one against")
    parser.add_argument("--db", type=Path,
                        help="corpus database, for the documents whose "
                             "pages were transcribed (default: the "
                             "profile's, when it is there)")
    parser.add_argument("--json", type=Path, dest="json_out",
                        help="also write the report as JSON")
    parser.add_argument("--min-precision", type=float,
                        help="exit with 1 when the precision of whole rows "
                             "is below this share")
    parser.add_argument("--min-recall", type=float,
                        help="exit with 1 when recall is below this share")
    parser.add_argument("--diff", type=Path, metavar="OTHER_DIR",
                        help="no decisions: compare this harvest with "
                             "another of the same documents, the baseline, "
                             "per parameter and coordinate (rows, states, "
                             "trust levels, the largest changes)")
    parser.add_argument("--top", type=_limit,
                        help=f"with --diff: how many of the largest "
                             f"changes to list (default: {DIFF_TOP})")
    parser.add_argument("--max-changed", type=_ceiling, metavar="SHARE",
                        help="with --diff: exit with 1 when more than this "
                             "share of the baseline's rows read differently "
                             "now")
    parser.add_argument("--max-gone", type=_ceiling, metavar="SHARE",
                        help="with --diff: exit with 1 when more than this "
                             "share of the baseline's rows is gone")
    return parser


def _database(args, profile) -> Optional[Path]:
    """The corpus database named, else the profile's when it is there."""
    db = args.db
    if db is None and profile is not None and Path(profile.db_path).is_file():
        db = Path(profile.db_path)
    return db


def _harvest_of(directory: Path) -> dict:
    """{document: rows} of a directory that holds a harvest."""
    if not directory.is_dir():
        raise SystemExit(f"{directory} is not a directory")
    # A trace copied beside its harvest is no document.
    found = {name: rows for name, rows in golden.harvest(directory).items()
             if not name.endswith(".trace")}
    if not found:
        raise SystemExit(f"{directory} holds no harvest file (*.jsonl): "
                         f"there is nothing to compare")
    return found


def _diff_command(args, harvest_dir: Path, db) -> int:
    baseline = _harvest_of(args.diff)
    report = diff(_harvest_of(harvest_dir), baseline,
                  transcribed=trust.transcribed_documents(db),
                  top=DIFF_TOP if args.top is None else args.top)
    print(render_diff(report))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    over = moved_too_far(report, args.max_changed, args.max_gone)
    for line in over:
        print(line, file=sys.stderr)
    return 1 if over else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    # Refused by name: a flag that has nothing to count is not ignored.
    if args.diff is not None:
        for flag, given in (("--gold", args.gold),
                            ("--baseline", args.baseline),
                            ("--min-precision", args.min_precision),
                            ("--min-recall", args.min_recall)):
            if given is not None:
                raise SystemExit(
                    f"{flag} counts against decisions and cannot be given "
                    f"with --diff, which compares two harvests without them")
    else:
        for flag, given in (("--top", args.top),
                            ("--max-changed", args.max_changed),
                            ("--max-gone", args.max_gone)):
            if given is not None:
                raise SystemExit(f"{flag} belongs to --diff, which compares "
                                 f"two harvests")
    profile = resolve_profile(args)
    harvest_dir = Path(args.harvest)
    if not harvest_dir.is_dir():
        raise SystemExit(f"{harvest_dir} is not a directory")
    if args.diff is not None:
        return _diff_command(args, harvest_dir, _database(args, profile))
    gold_path = args.gold or golden.path_beside(harvest_dir)
    if not Path(gold_path).is_file():
        raise SystemExit(
            f"{gold_path} is not a file: without decisions there is "
            f"nothing to count a harvest against. The review page of the "
            f"chat app writes them.")
    db = _database(args, profile)

    rows = golden.harvest(harvest_dir)
    gold = golden.Gold.load(gold_path)
    report = evaluate(rows, gold, transcribed=trust.transcribed_documents(db))
    comparison = None
    if args.baseline:
        if not args.baseline.is_dir():
            raise SystemExit(f"{args.baseline} is not a directory")
        comparison = compare(rows, golden.harvest(args.baseline), gold)
        report["baseline"] = comparison
    print(render(report, comparison))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
    short = below(report, args.min_precision, args.min_recall)
    for line in short:
        print(line, file=sys.stderr)
    return 1 if short else 0


if __name__ == "__main__":
    from docpipe.profile import bind_command_line
    bind_command_line()
    sys.exit(main())
