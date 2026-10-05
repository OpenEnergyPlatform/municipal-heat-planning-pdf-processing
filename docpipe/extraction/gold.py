"""
gold.py: What a person decided about harvested values, kept beside the
harvest and never in it.

A harvest says what the run read. Whether that is right is not something
the run can say, and a second model reading the same page cannot say it
either. A person can: with the value, its quote and the page in front of
them they decide, field by field, whether the document says that. Those
decisions are the gold, and the only thing precision and recall are counted
against (`evaluate.py`).

They are one JSON line each in a file of their own, appended and never
rewritten, so two people can decide at once and a decision that was changed
is still there. The last line about one thing is the one that counts.

    verdict   one field of one harvested row is `correct` or `wrong`. The
              field is "value", "unit" or the name of a coordinate; `shown`
              is what the harvest said there when it was decided, and
              `expected` what is right, where the person gave it.
    missing   the document states a value of a parameter that the harvest
              does not carry.
    checked   somebody read the whole document for one parameter (or for
              every one): only then is what the harvest lacks there known,
              and only over such documents is recall counted.

A row is named by its document, `identity.tuple_id` (the quote and the
value as written) and its parameter. Those survive a new harvest and a new
build of the database, so a decision made once is found again by the next
run that reads the same thing.

Two rows of one document can share that name: a table row that prints the
same number under two years is one quote and one value, read twice. So a
decision also notes what the row said in its other fields when it was made
(`row`), and it is about that row. A row that reads the same finds it. A
row that reads differently takes it over only when it is the one row the
decision can be about: the same value read again with another year, and
not the row beside it.

Nothing here judges a value, drops one or writes into a harvest.

Author: Felix Vossel
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from .. import jsonl
from . import identity

VERDICT, MISSING, CHECKED = "verdict", "missing", "checked"
CORRECT, WRONG = "correct", "wrong"
VALUE, UNIT = "value", "unit"
FILE_NAME = "gold.jsonl"

_lock = threading.Lock()


def _squash(text) -> str:
    return " ".join(str(text).split())


def same(left, right) -> bool:
    """Whether two field contents say the same: a number as a number, a
    text without regard to its spacing, and a number typed into a form as
    the number it spells."""
    number = (int, float)
    if isinstance(left, bool) or isinstance(right, bool):
        return left is right
    if isinstance(left, number) and isinstance(right, number):
        return float(left) == float(right)
    if left is None or right is None:
        return left is right
    if isinstance(left, (list, tuple, dict)) or isinstance(
            right, (list, tuple, dict)):
        return json.dumps(left, sort_keys=True, default=str) == json.dumps(
            right, sort_keys=True, default=str)
    return _squash(left) == _squash(right)


def coordinates(row: dict) -> list:
    """The names of the coordinates a row carries, in a fixed order."""
    return sorted(key[:-len("_state")] for key in row
                  if key.endswith("_state"))


def fields_of(row: dict) -> list:
    """Every field of a row a person can decide: the value, its unit where
    it has one, and each coordinate."""
    found = [VALUE]
    if row.get(UNIT) not in (None, ""):
        found.append(UNIT)
    return found + coordinates(row)


def row_key(document: str, row: dict) -> tuple:
    """What names a harvested row for a decision."""
    return (document, identity.tuple_id(document, row), row.get("parameter"))


def signature(row: dict) -> dict:
    """What a row says beside its value: its unit and each coordinate. Two
    rows of one name are told apart by it."""
    return {name: row.get(name) for name in fields_of(row) if name != VALUE}


def same_signature(left, right) -> bool:
    if not isinstance(left, dict) or not isinstance(right, dict):
        return False
    return set(left) == set(right) and all(
        same(left[name], right[name]) for name in left)


def row_name(document: str, row: dict) -> str:
    """One text per row as it reads now: its name and what it says beside
    its value. For an order, a key on a page, a set of rows put aside."""
    said = json.dumps(signature(row), sort_keys=True, default=str,
                      ensure_ascii=False)
    return "/".join(str(part) for part in row_key(document, row)) + "/" \
        + hashlib.sha256(said.encode("utf-8")).hexdigest()[:8]


def read(path) -> list:
    """Every decision in a file, in the order they were made. A file that
    is not there holds none."""
    path = Path(path)
    if not path.is_file():
        return []
    found = []
    for number, line in enumerate(jsonl.read(path), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: not JSON ({exc})") from exc
        problem = _problem(record)
        if problem:
            raise ValueError(f"{path}:{number}: {problem}")
        found.append(record)
    return found


def _problem(record) -> Optional[str]:
    if not isinstance(record, dict):
        return "a decision is an object"
    kind = record.get("kind")
    if kind not in (VERDICT, MISSING, CHECKED):
        return f"kind is {kind!r}, not one of verdict, missing, checked"
    if not record.get("document"):
        return "no document"
    if kind == VERDICT:
        if not record.get("tuple") or not record.get("field"):
            return "a verdict names a tuple and a field"
        if record.get("verdict") not in (CORRECT, WRONG):
            return (f"verdict is {record.get('verdict')!r}, not one of "
                    f"correct, wrong")
    if kind == MISSING and (not record.get("parameter")
                            or "value" not in record):
        return "a missing value names its parameter and the value"
    return None


def _append(path, record: dict) -> dict:
    problem = _problem(record)
    if problem:
        raise ValueError(problem)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with _lock:
        # One write call of one line: two people deciding at once append
        # whole lines, in whichever order.
        handle = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT
                         | getattr(os, "O_BINARY", 0))
        try:
            os.write(handle, line.encode("utf-8"))
        finally:
            os.close(handle)
    return record


def _signed(record: dict, by: Optional[str], note: Optional[str],
            at: Optional[str]) -> dict:
    record["by"] = by
    record["at"] = at or datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    if note:
        record["note"] = note
    return record


def decide(path, document: str, row: dict, field: str, verdict: str, *,
           expected=None, by: Optional[str] = None,
           note: Optional[str] = None, at: Optional[str] = None) -> dict:
    """Write down that *field* of *row* is correct or wrong."""
    if field not in fields_of(row):
        raise ValueError(f"the row has no field {field!r} "
                         f"(it has {', '.join(fields_of(row))})")
    _document, name, parameter = row_key(document, row)
    record = {"kind": VERDICT, "document": document, "tuple": name,
              "parameter": parameter, "field": field,
              "shown": row.get(field), "verdict": verdict,
              "row": signature(row)}
    if expected is not None:
        record["expected"] = expected
    return _append(path, _signed(record, by, note, at))


def add_missing(path, document: str, parameter: str, value, *,
                unit=None, quote: Optional[str] = None,
                coordinates: Optional[dict] = None, page=None,
                by: Optional[str] = None, note: Optional[str] = None,
                at: Optional[str] = None) -> dict:
    """Write down a value the document states and the harvest lacks."""
    record = {"kind": MISSING, "document": document, "parameter": parameter,
              "value": value, "unit": unit, "quote": quote,
              "coordinates": dict(coordinates or {}), "page": page}
    return _append(path, _signed(record, by, note, at))


def mark_checked(path, document: str, parameter: Optional[str] = None, *,
                 by: Optional[str] = None, note: Optional[str] = None,
                 at: Optional[str] = None) -> dict:
    """Write down that the whole document was read for *parameter* (None:
    for every one)."""
    record = {"kind": CHECKED, "document": document, "parameter": parameter}
    return _append(path, _signed(record, by, note, at))


class Gold:
    """The decisions of a file, as the questions an evaluation asks."""

    def __init__(self, records: Iterable[dict] = ()):
        self.verdicts: dict = {}        # (document, tuple, parameter, field)
        self.decided: dict = {}         # (document, tuple, parameter) -> rows
        self.missing: list = []
        self.checked: dict = {}         # document -> {parameter or None}
        for record in records:
            kind = record["kind"]
            if kind == VERDICT:
                name = (record["document"], record["tuple"],
                        record.get("parameter"))
                key = name + (record["field"],)
                # A later decision about the same content of the same row
                # replaces the earlier one; one about other content, or
                # about the row beside it, stands beside it.
                held = [old for old in self.verdicts.get(key, [])
                        if not (same(old.get("shown"), record.get("shown"))
                                and _same_row(old, record))]
                self.verdicts[key] = held + [record]
                if isinstance(record.get("row"), dict):
                    self.decided.setdefault(name, []).append(record["row"])
            elif kind == MISSING:
                # The same stated value written down twice is one value.
                self.missing = [old for old in self.missing
                                if not _same_fact(old, record)]
                self.missing.append(record)
            else:
                self.checked.setdefault(record["document"], set()).add(
                    record.get("parameter"))

    @classmethod
    def load(cls, path) -> "Gold":
        return cls(read(path))

    def _about(self, document: str, row: dict, field: str,
               rows: Optional[Iterable[dict]]) -> list:
        """The decisions on *field* that are about *row*, oldest first."""
        name = row_key(document, row)
        held = self.verdicts.get(name + (field,)) or []
        if not held:
            return held
        decided = self.decided.get(name) or []
        mine = signature(row)
        if any(same_signature(known, mine) for known in decided):
            # Somebody decided this row as it reads now: those decisions
            # and no others, whatever stands beside it.
            return [record for record in held
                    if same_signature(record.get("row"), mine)]
        # Nobody did. A decision made on a row that is gone is about this
        # one read again, where this is the only row it can be about.
        beside = [other for other in (rows or ())
                  if other is not row and row_key(document, other) == name]
        standing = [signature(other) for other in beside]
        if any(not any(same_signature(known, said) for known in decided)
               for said in standing):
            return []           # two rows nobody decided: a guess between
        return [record for record in held
                if not any(same_signature(record.get("row"), said)
                           for said in standing)]

    def verdict(self, document: str, row: dict, field: str,
                rows: Optional[Iterable[dict]] = None) -> Optional[str]:
        """`correct`, `wrong` or None (nobody decided) for what *row* says
        in *field* now. *rows* are the rows of its document, where other
        rows of the same name may stand; without them the row stands alone.

        A field holds one thing. So where somebody found other content
        correct there, or named what is right, that settles this content
        too; where the only decisions are about other content found wrong,
        nothing is known about this one. What was said last counts.
        """
        held = self._about(document, row, field, rows)
        now = row.get(field)
        for record in reversed(held):
            if same(record.get("shown"), now):
                return record["verdict"]
        for record in reversed(held):
            if "expected" in record:
                return CORRECT if same(record["expected"], now) else WRONG
        if any(record["verdict"] == CORRECT for record in held):
            return WRONG
        return None

    def is_checked(self, document: str, parameter: str) -> bool:
        marks = self.checked.get(document) or ()
        return None in marks or parameter in marks

    def missing_for(self, document: str, parameter: str) -> list:
        return [record for record in self.missing
                if record["document"] == document
                and record["parameter"] == parameter]


def _same_row(left: dict, right: dict) -> bool:
    """Whether two verdicts are about the same row. One that does not say
    which row it was made on is about any."""
    if left.get("row") is None or right.get("row") is None:
        return True
    return same_signature(left["row"], right["row"])


def _same_fact(left: dict, right: dict) -> bool:
    """Whether two `missing` records name the same stated value."""
    return (left["document"] == right["document"]
            and left["parameter"] == right["parameter"]
            and same(left.get("value"), right.get("value"))
            and same(left.get("unit"), right.get("unit"))
            and same_signature(left.get("coordinates") or {},
                               right.get("coordinates") or {}))


def covers(fact: dict, row: dict) -> bool:
    """Whether a harvested row is the value a `missing` record names: the
    same parameter and value, and every coordinate and the unit the record
    gives."""
    if row.get("parameter") != fact.get("parameter"):
        return False
    if not same(row.get("value"), fact.get("value")):
        return False
    if fact.get("unit") not in (None, "") and not same(
            row.get("unit"), fact.get("unit")):
        return False
    return all(same(row.get(name), content)
               for name, content in (fact.get("coordinates") or {}).items())


def harvest(directory) -> dict:
    """{document name: [accepted rows]} of a harvest directory."""
    from .serialize import collect
    return collect(Path(directory))


def queue(rows_by_document: dict, gold: Gold, *,
          parameters: Optional[Iterable[str]] = None,
          limit: Optional[int] = None) -> list:
    """The rows nobody has decided yet, as (document, row), in an order
    that is the same every time and has nothing to do with the document or
    the parameter.

    The order is by a hash of the row's name. Whoever decides the first
    hundred has decided a sample of the whole harvest, not the first three
    documents of it, and precision counted over them holds for the rest.
    """
    wanted = set(parameters) if parameters is not None else None
    open_rows = []
    for document, rows in rows_by_document.items():
        for row in rows:
            if wanted is not None and row.get("parameter") not in wanted:
                continue
            if all(gold.verdict(document, row, name, rows) is not None
                   for name in fields_of(row)):
                continue
            order = hashlib.sha256(
                row_name(document, row).encode("utf-8")).hexdigest()
            open_rows.append((order, document, row))
    open_rows.sort(key=lambda entry: entry[0])
    picked = [(document, row) for _order, document, row in open_rows]
    return picked if limit is None else picked[:limit]
