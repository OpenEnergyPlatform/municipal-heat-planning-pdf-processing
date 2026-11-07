"""
compute.py: The numbers a plan does not print and its printed numbers yield.

The rows request copies what stands in a passage, and from where it stands
nothing is ever missing: of six cases its prompt took the sandbox in none, a
request of its own naming the number wanted in four. A tool is used where a
question stands open. So once a document is folded, its verified rows are gone
through for what they leave open, each open question gets a request of its
own, and the model works the number out in the sandbox with the tables handed
over, as in the chat (owner decision 2026-11-02).

Which questions stand open is the profile's (`compute.py` of the profile,
`questions`), because the core names no coordinate. This module holds what
every such question has: what the request shows, what the sandbox is handed,
and the row that comes of the answer. That row is a claim like any other: it
goes through `verify_tuple` under the quote of one of its numbers, and a number
that is not in the code's output is refused (`computed_in_output`), as is one
its inputs do not make (`computed_from_inputs`, owner decision 2026-11-03).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .verify import quote_in

COMPUTE_PROMPT_ID = "extraction/compute"
# The fields of the message that brings what a question fetched of the plan,
# after the answer that asked for it (owner decisions 2026-11-07).
FOLLOWS = ("more", "hits", "not_found")
# What a row has as a reading and a row worked out from it does not.
ITS_OWN = ("tier", "flags", "provenance", "value_target", "value_raw", "head",
           "compute", "computed")


@dataclass
class Number:
    """A verified row as a question shows it, in the unit the question works
    in. *known* is what was read about it, in the plan's words."""
    row: dict
    value: float
    unit: str
    known: dict


@dataclass
class Question:
    """One number a document leaves open.

    *wanted* says what is asked, in the request. *numbers* are what it may be
    worked out from, named N1, N2, ... in this order. *anchor* is the number
    whose quote and passage the new row stands under. *row* makes the new
    row's coordinates from the rows the answer used, None where they do not
    yield one. *makes* is what the numbers the answer used make, in the new
    row's unit: the number the answer has to be, None where they make none.

    *cites*: the answer quotes, from the passage of a number it chose besides
    the anchor, what that number is (owner decision 2026-11-04, the model
    chooses with evidence). *take* is what the request may add a number with
    that no row holds, from a passage it was shown: (claim, source) -> a
    Number, or why not; *taking* is the schema of such a claim.
    """
    kind: str
    wanted: dict
    numbers: list
    anchor: dict
    row: Callable
    makes: Callable
    cites: bool = False
    take: Optional[Callable] = None
    taking: Optional[dict] = None


def label(index: int) -> str:
    return f"N{index + 1}"


def labels(question: Question) -> list:
    return [label(index) for index in range(len(question.numbers))]


def owner_of(row: dict) -> tuple:
    provenance = row.get("provenance") or {}
    return provenance.get("owner_kind"), provenance.get("owner_id")


def item_of(items: dict, row: dict):
    """The work item this row stands in: a long passage is read in pieces,
    and the row's quote says which."""
    held = items.get(owner_of(row)) or []
    quote = row.get("quote") or ""
    return next((item for item in held
                 if quote_in(item.source.text or "", quote)),
                held[0] if held else None)


def passages(question: Question, items: dict) -> list:
    """The passages the numbers stand in, each once, in the numbers' order."""
    shown: dict = {}
    for number in question.numbers:
        item = item_of(items, number.row)
        if item is not None:
            source = item.source
            shown.setdefault((source.owner_kind, source.owner_id, source.text),
                             source)
    return list(shown.values())


def ids_of(shown: list, fetched: list = ()) -> dict:
    """owner -> the id a request names a passage by: Q1, Q2, ... for the
    passages of its numbers, M1, M2, ... for those it asked for (`Gathered`
    names them so)."""
    ids = {(source.owner_kind, source.owner_id): f"Q{index + 1}"
           for index, source in enumerate(shown)}
    for index, source in enumerate(fetched):
        ids.setdefault((source.owner_kind, source.owner_id), f"M{index + 1}")
    return ids


def payload(question: Question, shown: list, fetched: list = ()) -> dict:
    """The request: what is wanted, the numbers and their passages."""
    ids = ids_of(shown, fetched)
    numbers = []
    for index, number in enumerate(question.numbers):
        entry = {"id": label(index), "value": number.value,
                 "unit": number.unit, "quote": number.row.get("quote")}
        if number.known:
            entry["known"] = number.known
        here = ids.get(owner_of(number.row))
        if here:
            entry["source"] = here
        numbers.append(entry)
    return {"wanted": question.wanted, "numbers": numbers,
            "sources": [{"id": f"Q{index + 1}", "kind": source.owner_kind,
                         "title": source.provenance.get("title"),
                         "text": source.text}
                        for index, source in enumerate(shown)]}


def context(question: Question, shown: list, fetched: list = ()) -> dict:
    """What the sandbox is handed: the numbers, every passage as the rows
    request hands them, and the tables as the chat hands them."""
    ids = ids_of(shown, fetched)
    every = [*shown, *fetched]
    return {"numbers": {label(index): {"value": number.value,
                                       "unit": number.unit}
                        for index, number in enumerate(question.numbers)},
            "sources": {ids[(source.owner_kind, source.owner_id)]:
                        source.text for source in every},
            "tables": [{"caption": source.provenance.get("title") or "",
                        "markdown": source.body or source.text}
                       for source in every if source.owner_kind == "table"]}


def unquoted(question: Question, answer: dict, used: list,
             passage_of: Callable) -> Optional[str]:
    """The label of the chosen number whose passage the answer's quote does
    not stand in, or None where it stands in one of them, or the question
    asks no quote. *passage_of(number)* is the text the number stands in."""
    if not question.cites:
        return None
    chosen = [number for number in used if number.row is not question.anchor]
    quote = answer.get("quote")
    if isinstance(quote, str) and any(quote_in(passage_of(number) or "", quote)
                                      for number in chosen):
        return None
    by_number = {id(number): name
                 for name, number in zip(labels(question), question.numbers)}
    return by_number.get(id(chosen[0])) if chosen else None


def used_numbers(question: Question, answer: dict) -> list:
    """The numbers the answer says it used, all of them if it names none."""
    named = answer.get("used")
    by_label = dict(zip(labels(question), question.numbers))
    chosen = [by_label[name] for name in named or () if name in by_label]
    return chosen or list(question.numbers)


def claim_of(question: Question, value, used: list, runs: list,
             cited: Optional[str] = None) -> Optional[dict]:
    """The new row: coordinates from its numbers, the code and its output as
    evidence, and the numbers it was worked out from with their passages and
    what they make. The last run is the one the answer stands on, and holds
    the quote that says what the chosen number is (*cited*)."""
    coordinates = question.row([number.row for number in used])
    if coordinates is None:
        return None
    inputs = [{"value": number.value, "unit": number.unit,
               "quote": number.row.get("quote"),
               "source": list(owner_of(number.row))} for number in used]
    last = {**runs[-1], "inputs": inputs, "expected": question.makes(used)}
    if cited:
        last["cited"] = cited
    return {**coordinates, "value": value,
            "quote": question.anchor.get("quote"),
            "source": question.anchor.get("source"), "computed": True,
            "compute": [*runs[:-1], last]}


def keys_of(row: dict, *axes: str) -> dict:
    """These coordinates of a row with all their evidence."""
    return {key: value for key, value in row.items()
            if any(key == axis or key.startswith(f"{axis}_") for axis in axes)}


def inherited(row: dict, *leaving: str) -> dict:
    """The coordinates a row worked out from this one takes, *leaving* out
    these axes."""
    gone = keys_of(row, *leaving)
    return {key: value for key, value in row.items()
            if key not in gone and key not in ITS_OWN}
