"""
variables.py: What the steps of a flow pass on to each other (owner
decision 2026-11-12, plan of the general blocks, points 2 and 9).

Every step of a flow takes named inputs and gives named outputs. An input
is a variable a step before it gave, or one the run starts with (the
document and the fields of the Spec); what may stand where follows from
this alone (`flow.problems`). Each variable has a JSON schema, which the
page shows and a step that asks the model fills (`ask`), and says whether
it lasts for the whole document (a list of values, the document's facts)
or only for the item it was made for (the answer to one question, the
search hits of one dimension).

A frame gives its item: "for each field" the field, "for each chunk" the
chunk, and so on (`ITEMS`). A variable a step of the page makes itself
(the output of an own question, of a Python step, of "set") is named by
that step; it lasts where the step says so ("for the whole document").

Author: Felix Vossel
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Var:
    """One variable: its *name* in the flow, what the page calls it, what
    it holds (*says*), its JSON *schema*, and whether it lasts for the whole
    document after the step that made it (*lasting*)."""
    name: str
    label: str
    says: str
    schema: dict = field(default_factory=dict)
    lasting: bool = False


_LINE = {"type": "object", "properties": {
    "number": {"type": "integer"}, "text": {"type": "string"}}}
_CHUNK = {"type": "object", "properties": {
    "kind": {"enum": ["section", "table", "figure"]},
    "headings": {"type": "array", "items": {"type": "string"}},
    "lines": {"type": "array", "items": _LINE}}}
_FIELD = {"type": "object", "properties": {
    "name": {"type": "string"}, "means": {"type": "string"},
    "unit": {"type": "string"},
    "list": {"type": "array", "items": {"type": "string"}}}}
_VALUE = {"type": "object", "properties": {
    "field": {"type": "string"}, "value": {}, "words": {"type": "string"},
    "line": {"type": "string"}, "quote": {"type": "string"},
    "dimensions": {"type": "object"}}}
_ANSWER = {"type": "object", "properties": {
    "answered": {"type": "boolean"}, "finds": {"type": "integer"},
    "words": {"type": "string"}, "quote": {"type": "string"}}}


VARIABLES = {var.name: var for var in (
    Var("document", "the document",
        "The PDF as the preprocessing left it: its pages, its lines of "
        "text, its tables and its figures, and as its title page the first "
        "lines of its first page. A run starts with it.",
        {"type": "object", "properties": {
            "pages": {"type": "integer"},
            "title_page": {"type": "array", "items": _LINE}}},
        lasting=True),
    Var("figure_lines", "the lines of the figures",
        "What the model wrote out of each figure's picture: its caption "
        "(title, axes, legend) and its numbers, line by line.",
        {"type": "array", "items": _LINE}, lasting=True),
    Var("chunks", "the chunks",
        "The document split into short chunks of numbered lines. A request "
        "shows chunks, and an answer names the number of a line.",
        {"type": "array", "items": _CHUNK}, lasting=True),
    Var("chunk", "the chunk", "One chunk of the document.", _CHUNK),
    Var("fields", "the fields of the Spec",
        "What the Spec asks of a document. A run starts with them.",
        {"type": "array", "items": _FIELD}, lasting=True),
    Var("field", "the field", "One field of the Spec.", _FIELD),
    Var("facts", "the facts of the document",
        "Answers that hold for the whole document, such as its base year, "
        "kept so that every later request can show them.",
        {"type": "array", "items": _VALUE}, lasting=True),
    Var("fact", "the fact", "One field that holds for the whole document, "
        "asked once.", _FIELD),
    Var("lists", "the lists of the document",
        "The names the document uses for its scenarios and for the works "
        "it cites, one entry each, kept while it is read.",
        {"type": "object"}, lasting=True),
    Var("order", "the chunks in order for each field",
        "For each field, the document's chunks best first for a sentence "
        "as the document would print a value of the field.",
        {"type": "object"}, lasting=True),
    Var("hits", "the search hits",
        "The chunks a search found for one field or dimension, best first, "
        "shown a few at a time.",
        {"type": "array", "items": _CHUNK}),
    Var("answer", "the answer",
        "What the last question of this item came to: whether it was "
        "answered, how many values it found, and its words and line.",
        _ANSWER),
    Var("values", "the values read",
        "Every value read so far, each with its field, its words, the line "
        "it stands in and its dimensions.",
        {"type": "array", "items": _VALUE}, lasting=True),
    Var("value", "the value", "One value read.", _VALUE),
    Var("dimensions", "the dimensions of the value",
        "What the Spec asks about a value besides itself, such as its year, "
        "its scenario or its energy carrier.",
        {"type": "array", "items": {"type": "string"}}),
    Var("dimension", "the dimension", "One dimension of a value.",
        {"type": "string"}),
    Var("sentence", "the search sentence",
        "A sentence as the document would print the missing answer; the "
        "search looks for chunks like it.", {"type": "string"}),
    Var("rows", "the harvest",
        "The rows the run wrote: each value with the states of its "
        "dimensions.", {"type": "array", "items": _VALUE}, lasting=True),
    Var("round", "the round", "The number of the turn of a round.",
        {"type": "integer"}),
)}

# What a run starts with.
START = ("document", "fields")

# What each kind of frame gives its steps, and what it iterates.
ITEMS = {"settled": ("fact", None), "field": ("field", "fields"),
         "piece": ("chunk", "chunks"), "value": ("value", "values"),
         "coordinate": ("dimension", "value"),
         # A loop over any list names its entry itself ("as").
         "list": ("item", None)}


def var(name: str) -> Optional[Var]:
    return VARIABLES.get(name)


def label(name: str) -> str:
    one = VARIABLES.get(name)
    return one.label if one is not None else name


def lasting(name: str, made: Optional[dict] = None) -> bool:
    """Does *name* last for the whole document once a step made it? A
    variable of the page lasts where its step says so (*made*: name ->
    lasting)."""
    if made and name in made:
        return bool(made[name])
    one = VARIABLES.get(name)
    return bool(one and one.lasting)


def wanted(spec: str) -> tuple:
    """(names, optional) of an input written as "a|b" (one of them) with
    "?" at its end where the step does without it."""
    optional = spec.endswith("?")
    return tuple(spec.rstrip("?").split("|")), optional


def catalogue() -> dict:
    """The variables as the page shows them."""
    return {name: {"label": one.label, "says": one.says,
                   "schema": one.schema, "lasting": one.lasting}
            for name, one in VARIABLES.items()}
