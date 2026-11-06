"""
compute.py: What a heat plan leaves to be worked out from its printed numbers.

Two kinds of open question (`docpipe/extraction/compute.py` asks them):

- A share whose absolute number stands nowhere in its frame: "Heizöl 21 %"
  and "Wärmeverbrauch 185.200 MWh". Which total is the whole of the share is
  the model's reading, by what it means and not by its word, so all of them
  are offered, and where none is, the request may take one from the plan
  (`take_whole`).
- Parts of an amount without their sum: a sum closes exactly one axis, so the
  parts agree on everything but that axis and none of them says it is the
  total. Parts may stand in several passages.

On eight plans 71 percent of the shares had their absolute number printed, and
170 of 289 sets of parts in one passage printed their sum.

A sum over passages must not count one statement twice. `one_statement` holds
what can be told by machine: the same part, the same number within the graph's
rounding, in two passages or under one quote. Two rows of one passage with one
number are two rows. A set whose largest number is the sum of the others has
printed its sum under another word. The rest is reading and stays with the
model: a part contained in another, alternatives of one plant, a list of only
the largest parts.

What a question's numbers make is its own arithmetic, a share times its total
or the sum of the parts, and an answer has to be it (`makes`). Two questions
that come to the same number with the same coordinates are one statement, and
one row of it stays (`same`, owner decision 2026-11-03).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from docpipe.extraction import fields
from docpipe.extraction.compute import (Number, Question, inherited, keys_of,
                                        owner_of)
from docpipe.extraction.pipeline import answer_in_quote
from docpipe.extraction.verify import Refusal, verify_tuple
from profiles.kwp.kg import ROUNDING_TOLERANCE, _precision

SHARE = "share"
AREA = "spatial_scope"
SUBJECT = "subject"
# The axes a number can be split over, each with the entry that says it is not.
PARTS = {"carrier": "out:total", "sector": "out:total",
         "technology": "out:total", AREA: "municipality"}
SPLIT = ("carrier", "sector", "technology")
# How precisely a number holds, the word the plan prints with it ("ca.", "bis
# zu"), and the entry a worked-out number takes from parts that differ in it.
QUALIFIER = "qualifier"
APPROXIMATE = "out:approximate"


def qualified(row: dict, used: list) -> dict:
    """*row*, a number worked out from the rows *used*, with the qualifier
    they leave it (owner decision 2026-11-06: the compute step inherits it):
    theirs, with its evidence, where they all print the same word; none
    where none prints one; "ungefähr" where they differ, since a sum of
    approximate parts is approximate. A worked-out number is the end of no
    range."""
    out = {key: value for key, value in row.items()
           if key != fields.RANGE and key != QUALIFIER
           and not key.startswith(f"{QUALIFIER}_")}
    said = {one.get(QUALIFIER) if one.get(f"{QUALIFIER}_state") == fields.READ
            else None for one in used}
    if said == {None}:
        out[f"{QUALIFIER}_state"] = fields.SAID_UNSTATED
    elif len(said) == 1:
        first = next(one for one in used
                     if one.get(f"{QUALIFIER}_state") == fields.READ)
        out.update(keys_of(first, QUALIFIER))
    else:
        out[QUALIFIER] = APPROXIMATE
        out[f"{QUALIFIER}_state"] = fields.DERIVED
    return out


def entry(row: dict, axis: str) -> Optional[str]:
    """What this row says on this axis, None if it says nothing. A sub-area
    is told from another by its name."""
    if row.get(f"{axis}_state") not in (fields.READ, fields.DERIVED):
        return None
    value = row.get(axis)
    if axis == AREA and value != PARTS[AREA]:
        return row.get(f"{AREA}_raw") or value
    return value


def whole_on(row: dict, axis: str) -> Optional[str]:
    """As `entry`, and a row that says nothing on an axis is not split on it:
    the technology of most numbers is simply not asked for."""
    return entry(row, axis) or PARTS[axis]


def framed(row: dict) -> bool:
    return (row.get("year_state") == fields.READ
            and row.get("scenario_state") == fields.READ)


def additive(row: dict, spec) -> bool:
    """An amount over a span in the slice, with its year and scenario. A power
    is no amount: two peaks do not add up. An `out:` quantity has no class the
    graph takes: a specific value, a saving, a useful energy. Zero is a part of
    nothing and the whole of nothing, and rows of it fill plans' tables."""
    parameter = spec.by_uri.get(str(row.get("parameter") or ""))
    return (parameter is not None and parameter.is_numeric
            and parameter.integrated and framed(row)
            and bool(row.get("value_target"))
            and row.get("quantity_state") in (fields.READ, fields.DERIVED)
            and not str(row.get("quantity") or "").startswith("out:"))


def same_number(a: dict, b: dict) -> bool:
    low, high = sorted((a["value_target"], b["value_target"]))
    return low == high or (bool(high)
                           and (high - low) / abs(high) <= ROUNDING_TOLERANCE)


def one_statement(a: dict, b: dict, part) -> bool:
    """The same part with the same number, said twice: in two passages, or
    under one quote. In one passage under two quotes it is two rows."""
    return (part(a) == part(b) and same_number(a, b)
            and (owner_of(a) != owner_of(b)
                 or a.get("quote") == b.get("quote")))


def distinct(rows: list, part) -> list:
    """One row per statement, the most precisely printed of each."""
    kept: list = []
    for row in sorted(rows, key=_precision, reverse=True):
        if not any(one_statement(row, other, part) for other in kept):
            kept.append(row)
    return kept


def holds_its_sum(parts: list) -> bool:
    """Is the largest of three or more numbers the sum of the others?"""
    values = sorted(abs(part["value_target"]) for part in parts)
    if len(values) < 3:
        return False
    return (abs(values[-1] - sum(values[:-1]))
            <= ROUNDING_TOLERANCE * values[-1])


def known(row: dict, spec) -> dict:
    """What was read about this number, in the plan's words where it has
    them and in the list's where it does not."""
    parameter = spec.by_uri.get(str(row.get("parameter") or ""))
    said: dict = {}
    for slot in fields.axis_slots(parameter) if parameter is not None else ():
        if row.get(f"{slot.name}_state") != fields.READ:
            continue
        value = row.get(slot.name)
        named = next((option.label for option in slot.options
                      if option.uri == value), value)
        said[slot.name] = row.get(f"{slot.name}_raw") or named
    return said


def number(row: dict, spec, unit: Optional[str] = None) -> Number:
    """The row as a question shows it, in *unit* if it names one."""
    parameter = spec.by_uri[str(row.get("parameter"))]
    factor = parameter.unit_factor(unit) if unit else None
    value = (round(row["value_target"] / float(factor), 6) if factor
             else row.get("value"))
    return Number(row, value, unit or row.get("unit"), known(row, spec))


def label_of(row: dict, axis: str, spec) -> Optional[str]:
    return known(row, spec).get(axis)


def amounts(spec) -> list:
    """The parameters a whole can be one of: an amount over a span."""
    return [parameter for parameter in spec.parameters
            if parameter.is_numeric and parameter.integrated]


def quantity_slot(parameter):
    return next((slot for slot in fields.axis_slots(parameter)
                 if slot.name == "quantity"), None)


def choices(spec) -> dict:
    """What a whole the request takes may be, as the request shows it."""
    out = {}
    for parameter in amounts(spec):
        slot = quantity_slot(parameter)
        out[parameter.uri] = {
            "label": parameter.label, "units": list(parameter.units_accepted),
            "quantity": {option.uri: option.label
                         for option in (slot.options if slot else ())}}
    return out


def taking(spec) -> dict:
    """The schema of a whole the request takes."""
    every = amounts(spec)
    return {"type": "object",
            "properties": {
                "parameter": {"enum": [p.uri for p in every]},
                "value": {"type": "number"},
                "unit": {"enum": sorted({unit for p in every
                                         for unit in p.units_accepted})},
                "quantity": {"enum": sorted({
                    option.uri for p in every
                    for option in (quantity_slot(p).options
                                   if quantity_slot(p) else ())})},
                "quantity_raw": {"type": "string"},
                "quote": {"type": "string"}},
            "required": ["parameter", "value", "unit", "quote"],
            "additionalProperties": False}


def take_whole(share: dict, claim: dict, source, spec):
    """A whole the request found in a passage no row of it holds, as a
    Number, or why it is not one. *source* is the passage its quote stands
    in, of all the request showed. Read like any number (`verify_tuple`: its
    quote in the passage, its value in the quote, its unit one the parameter
    accepts), its quantity like any coordinate (`answer_in_quote`), and its
    year, scenario and area the share's, since a whole has to have them. It
    stands only in the request, as an input, and is no row of its own (owner
    decision 2026-11-05)."""
    parameter = spec.by_uri.get(str(claim.get("parameter") or ""))
    if parameter not in amounts(spec):
        return f"parameter {claim.get('parameter')!r} is no amount"
    raw = {**keys_of(share, "year", "scenario", AREA),
           "parameter": parameter.uri, "value": claim.get("value"),
           "unit": claim.get("unit"), "quote": claim.get("quote"),
           "quantity": claim.get("quantity")}
    outcome = verify_tuple(raw, parameter, source.text or "",
                           owner_kind=source.owner_kind)
    if isinstance(outcome, Refusal):
        return outcome.reason
    row = dict(outcome.tuple)
    slot = quantity_slot(parameter)
    if row.get("quantity") is not None and slot is not None and answer_in_quote(
            slot, row["quantity"], claim.get("quantity_raw"), row["quote"]):
        row["quantity_state"] = fields.READ
        row["quantity_quote"] = row["quote"]
        row["quantity_source"] = [source.owner_kind, source.owner_id]
    else:
        row["quantity"] = None
        row["quantity_state"] = fields.UNBACKED
    for each in fields.axis_slots(parameter):
        row.setdefault(f"{each.name}_state", fields.SAID_UNSTATED)
    row["provenance"] = {**(source.provenance or {}),
                         "owner_kind": source.owner_kind,
                         "owner_id": source.owner_id}
    return number(row, spec)


def share_question(share: dict, bases: list, spec) -> Question:
    def row(used: list) -> Optional[dict]:
        totals = [other for other in used if other is not share]
        if len(totals) != 1:
            return None         # no total named, or the answer is no share
        return qualified({**inherited(totals[0], *SPLIT, SUBJECT), **keys_of(
            share, *SPLIT, SUBJECT)}, used)

    def makes(used: list) -> Optional[float]:
        """The share of its one total, in the total's unit."""
        totals = [other for other in used if other.row is not share]
        if len(totals) != 1:
            return None
        return share["value_target"] / 100 * totals[0].value

    return Question(
        kind="share",
        wanted={"kind": "share", "share": "N1", "whole": share.get("whole"),
                "year": share.get("year"),
                "scenario": label_of(share, "scenario", spec),
                "take": choices(spec)},
        numbers=[number(share, spec), *(number(base, spec) for base in bases)],
        anchor=share, row=row, makes=makes, cites=True,
        take=lambda claim, source: take_whole(share, claim, source, spec),
        taking=taking(spec))


def split_of(row: dict) -> tuple:
    return tuple(whole_on(row, axis) for axis in SPLIT)


def open_shares(rows: list, spec) -> list:
    amounts = [row for row in rows if additive(row, spec)]
    questions = []
    for share in rows:
        if (share.get("parameter") != SHARE or not framed(share)
                or share.get("whole_state") != fields.READ
                or not share.get("value_target")):
            continue
        own = split_of(share)
        near = [row for row in amounts
                if (row.get("year"), row.get("scenario")) == (
                    share.get("year"), share.get("scenario"))
                and whole_on(row, AREA) == whole_on(share, AREA)]
        if any(split_of(row) == own for row in near):
            continue            # its absolute number stands in the plan
        bases = [row for row in near
                 if all(said in (part, PARTS[axis]) for axis, said, part
                        in zip(SPLIT, split_of(row), own))]
        # Asked with no total offered, too: the request may find its whole
        # in the plan and take it (owner decision 2026-11-05).
        questions.append(share_question(share, distinct(bases, split_of),
                                        spec))
    return questions


def sum_question(parts: list, axis: str, spec) -> Question:
    first = parts[0]

    def row(used: list) -> dict:
        return qualified({**inherited(first, axis, SUBJECT),
                          axis: PARTS[axis], f"{axis}_state": fields.DERIVED,
                          f"{SUBJECT}_state": fields.SAID_UNSTATED},
                         used or parts)

    def makes(used: list) -> float:
        """The parts it names added up, in the unit of the first."""
        return sum(part.value for part in used)

    unit = first.get("unit")
    return Question(
        kind="sum",
        wanted={"kind": "sum", "over": axis, "year": first.get("year"),
                "scenario": label_of(first, "scenario", spec),
                "quantity": label_of(first, "quantity", spec), "unit": unit},
        numbers=[number(part, spec, unit) for part in parts],
        anchor=first, row=row, makes=makes)


def open_sums(rows: list, spec) -> list:
    questions = []
    for axis in PARTS:
        groups: dict = defaultdict(list)
        for row in rows:
            if additive(row, spec) and entry(row, axis) is not None:
                groups[(row.get("parameter"), row.get("quantity"),
                        row.get("aggregation"), row.get("year"),
                        row.get("scenario"),
                        *(whole_on(row, other) for other in PARTS
                          if other != axis))].append(row)
        for members in groups.values():
            if any(entry(row, axis) == PARTS[axis] for row in members):
                continue        # its sum stands in the plan
            parts = distinct(members, lambda row: entry(row, axis))
            if (len({entry(part, axis) for part in parts}) > 1
                    and not holds_its_sum(parts)):
                questions.append(sum_question(parts, axis, spec))
    return questions


def questions(rows: list, spec) -> list:
    """Every number this document's verified rows leave open."""
    return [*open_shares(rows, spec), *open_sums(rows, spec)]


def same(a: dict, b: dict, spec) -> bool:
    """Two worked-out rows that are one statement: the same number with the
    same coordinates, whichever questions came to it. The subject is the
    plan's wording and tells only different numbers apart, as in the graph;
    the number is compared in its target unit, within the graph's rounding."""
    parameter = spec.by_uri.get(str(a.get("parameter") or ""))
    return (parameter is not None and a.get("parameter") == b.get("parameter")
            and all(entry(a, slot.name) == entry(b, slot.name)
                    for slot in fields.axis_slots(parameter)
                    if slot.name != SUBJECT)
            and same_number(a, b))
