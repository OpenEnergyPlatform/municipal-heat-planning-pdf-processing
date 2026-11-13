"""
bricks.py: The pieces a drawing of the graph puts on its arrows and boxes.

The drawing in a profile's graph file (`map`, read by `graph.py`) says which
box a field becomes, which property an arrow writes and which brick turns a
reading into the object of a triple. A brick is code: it takes one kind of
thing, gives one kind of thing back, and says in one sentence what it does.
The core's bricks are here; a profile adds the ones only it needs in
`profiles/<name>/kg.py` (`BRICKS`), and a drawing names a brick by its name.

The kinds, by where a drawing puts them:

  object     on an arrow: the object(s) of the triple from a reading, or
             from the node itself
  condition  in a box's or the document's list: None where a row is taken,
             else the reason it is not
  facts      on the document: what is known of it beyond its harvest
  nodes      on a box of one node per name: the names a row gives
  address    on a box of one node per number: the address of a number
  class      on a box: the class(es) a node is written as
  evidence   on a box: the comment lines above a node
  name       on a box: a node's name from its first reading
  check      on the document: a diagnostic over what was chosen
  claims     on a box: what the provenance file records of a node

Every brick is called with one `Call`; what it reads of it depends on its
kind. An object brick gives [(Turtle term, value)], the value being what
another writer (the OEKG API body) and a later document see.

Author: Felix Vossel
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from .graphkit import NOT_IN_GRAPH, ttl_literal, ttl_string

KINDS = ("object", "condition", "facts", "nodes", "address", "class",
         "evidence", "name", "check", "claims")

# What a setting holds, as `docpipe edit` shows it.
SETTING_KINDS = ("text", "texts", "number", "flag", "class", "rule", "table",
                 "labels", "fields", "prose")


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str
    help: str
    default: object = None


@dataclass(frozen=True)
class Brick:
    name: str
    kind: str
    does: str
    takes: str
    gives: str
    run: Callable
    settings: tuple = ()
    # An object brick reads one reading at a time ("row") or all the
    # readings of its node at once ("node").
    per: str = "row"
    # What an object brick writes, for the checks that hold every triple
    # shape to the ontology (`ontology.drawing_edges`): "answers" (a class
    # of the coordinate's list), "entries" (an entry of the field's list),
    # "key:<name>" (the identifier a key of the field holds), "xsd:<type>"
    # (a literal of that datatype), "setting:datatype" (the datatype its
    # settings name), "" (a plain literal or nothing known).
    writes: str = ""

    def describe(self) -> dict:
        """What `docpipe edit` shows of the brick."""
        return {"name": self.name, "kind": self.kind, "does": self.does,
                "takes": self.takes, "gives": self.gives, "per": self.per,
                "writes": self.writes,
                "settings": [{"key": one.key, "kind": one.kind,
                              "help": one.help, "default": one.default}
                             for one in self.settings]}


@dataclass
class Call:
    """What a brick is called with. `doc` is the document being written
    (`graph.Document`), `node` the node, `row` the reading, `value` what the
    arrow reads of it, `settings` the brick's settings in the drawing,
    `label` the words a number's address is split by, `source` the field
    or coordinate the arrow starts at, `rows` the readings a node-wide
    brick reads."""
    doc: object = None
    node: object = None
    row: Optional[dict] = None
    value: object = None
    settings: dict = field(default_factory=dict)
    label: str = ""
    source: Optional[str] = None
    rows: list = field(default_factory=list)


def literal(text, form: str = "long") -> str:
    """A text as a Turtle string literal: `long` may run over several lines
    (`ttl_literal`), `line` escapes every line break (`ttl_string`)."""
    return ttl_string(text) if form == "line" else ttl_literal(text)


def in_graph(value) -> bool:
    """Is this answer something the graph takes, or one of the out: entries
    of a list, which say what a row is when nothing fits?"""
    return bool(value) and not str(value).startswith(NOT_IN_GRAPH)


_CLASS = re.compile(r"[A-Za-z]+_\d+")
_YEAR = re.compile(r"\d{4}")


def is_class(value, family: str = "") -> bool:
    """True for a class identifier (OEO_00000128) of *family*, where one is
    given; false for every deliberate non-class answer."""
    text = str(value or "")
    if family:
        return bool(re.fullmatch(rf"{re.escape(family)}\d+", text))
    return bool(_CLASS.fullmatch(text))


# -- object bricks -----------------------------------------------------------

def _text(call: Call) -> list:
    if call.value is None or call.value == "":
        return []
    return [(literal(call.value, call.settings.get("form", "long")),
             call.value)]


def _node_name(call: Call) -> list:
    name = call.node.name
    if name is None:
        return []
    return [(literal(name, call.settings.get("form", "long")), name)]


def _datetime_of_year(call: Call) -> list:
    digits = _YEAR.search(str(call.value or ""))
    if not digits:
        return []
    stamp = f"{digits.group(0)}-01-01T00:00:00"
    return [(f'"{stamp}"^^xsd:dateTime', stamp)]


def _entry(call: Call) -> list:
    uri = (call.row or {}).get("value_uri")
    return [(f"<{uri}>", uri)] if in_graph(uri) else []


def _fixed(call: Call) -> list:
    rule = call.settings.get("rule")
    values = call.doc.rule(rule) if rule else call.settings.get("values")
    prefix = call.settings.get("prefix") or ""
    full = call.doc.prefixes.get(prefix, "")
    return [(f"{prefix}:{one}" if prefix else str(one), full + str(one))
            for one in values or ()]


def _template(call: Call) -> list:
    words = dict(call.doc.facts or {})
    words.update((call.node.data or {}) if call.node else {})
    text = str(call.settings.get("text") or "").format(**words)
    return [(ttl_string(text), text)]


def _fact(call: Call) -> list:
    value = (call.doc.facts or {}).get(call.settings.get("fact"))
    if value in (None, ""):
        return []
    datatype = call.settings.get("datatype")
    return [(f'"{value}"^^{datatype}' if datatype else ttl_string(value),
             value)]


def _decimal(call: Call) -> list:
    if call.value is None:
        return []
    number = float(call.value)
    return [(f'"{number!r}"^^xsd:float', number)]


def _whole(call: Call) -> list:
    if call.value is None:
        return []
    number = int(call.value)
    return [(f'"{number}"^^xsd:integer', number)]


def _answer_class(call: Call) -> list:
    answer = call.value
    total = call.settings.get("total_class")
    if answer == f"{NOT_IN_GRAPH}total" and total:
        answer = total
    family = call.settings.get("family") or ""
    if not answer or not is_class(answer, family):
        return []
    outside = call.settings.get("outside_root") or {}
    if answer in outside:
        # Counted, not dropped: the count is what argues for the axioms
        # that would let them be called what the property's range says.
        call.doc.count("outside_root", outside[answer])
    prefix = call.settings.get("prefix") or "oeo"
    return [(f"{prefix}:{answer}", call.doc.prefixes.get(prefix, "")
             + answer)]


# -- condition bricks ---------------------------------------------------------

def _kept_coordinates(call: Call) -> Optional[str]:
    from . import fields
    parameter = call.doc.spec.by_uri.get(call.row.get("parameter"))
    if parameter is None or fields.in_parameter(parameter, call.row):
        return None
    slot = next(slot for slot in fields.axis_slots(parameter)
                if slot.keep and not fields.kept(slot, call.row))
    return (f"{slot.name}:{call.row.get(slot.name) or call.row.get(f'{slot.name}_state')}")


def _answer_is(call: Call) -> Optional[str]:
    coordinate = call.settings.get("coordinate")
    answer = call.row.get(coordinate)
    if "is" in call.settings and answer != call.settings["is"]:
        return f"{coordinate}:{answer}"
    if "not" in call.settings and answer == call.settings["not"]:
        return f"{coordinate}:{answer}"
    return None


def _has_words(call: Call) -> Optional[str]:
    coordinate = call.settings.get("coordinate")
    if str(call.row.get(coordinate) or "").strip():
        return None
    return f"{coordinate}_unnamed"


def _named(call: Call) -> Optional[str]:
    value = call.row.get("value")
    if isinstance(value, str) and call.doc.fold(value):
        return None
    return "unnamed"


# -- name bricks --------------------------------------------------------------

def _trimmed(call: Call) -> str:
    return str(call.value).strip()


def _without_legal_form(call: Call) -> str:
    text = re.sub(r"\s+", " ", str(call.value)).strip()
    legal = call.doc.legal_forms
    if not legal:
        return text
    return re.sub(rf"[\s,]+{legal}\.?$", "", text, flags=re.I).strip(" ,")


CORE = {brick.name: brick for brick in (
    Brick("text", "object", "Writes the reading as it is, as a text.",
          "a reading", "a text", _text,
          (Setting("form", "text", "long (may run over lines) or line "
                   "(one line, breaks escaped)", "long"),)),
    Brick("node_name", "object",
          "Writes the name of the node: the first spelling of the readings "
          "that are this node.", "a node", "a text", _node_name,
          (Setting("form", "text", "long or line", "long"),), per="node"),
    Brick("year_to_datetime", "object",
          "Writes the four-digit year of the reading as the first of "
          "January of that year, midnight (xsd:dateTime); a reading without "
          "a year writes nothing.", "a reading", "a date and time",
          _datetime_of_year, writes="xsd:dateTime"),
    Brick("entry", "object",
          "Writes the entry of the list the reading was chosen as, by its "
          "address; an out: entry writes nothing.", "a reading of a list",
          "an address", _entry, writes="entries"),
    Brick("fixed", "object",
          "Writes the classes a rule of the graph file lists, on every node "
          "of the box.", "a node", "classes", _fixed,
          (Setting("rule", "rule", "the rule that lists them"),
           Setting("prefix", "text", "the prefix they are written with",
                   "oeo")), per="node"),
    Brick("template", "object",
          "Writes a text made of words and what is known of the document "
          "and the node ({place}, {year}, {label}).", "a node", "a text",
          _template, (Setting("text", "text", "the text, with {name} where "
                              "a fact goes"),), per="node"),
    Brick("fact", "object",
          "Writes one thing known of the document as a literal of a "
          "datatype.", "a document", "a literal", _fact,
          (Setting("fact", "text", "which fact"),
           Setting("datatype", "text", "its datatype")), per="node",
          writes="setting:datatype"),
    Brick("decimal", "object",
          "Writes the number as a decimal (xsd:float).", "a number",
          "a literal", _decimal, writes="xsd:float"),
    Brick("whole_number", "object",
          "Writes the number as a whole number (xsd:integer).", "a number",
          "a literal", _whole, writes="xsd:integer"),
    Brick("answer_class", "object",
          "Writes the class the answer names; out:total becomes the class "
          "set for a figure without this breakdown; any other answer that "
          "is no class writes nothing.", "an answer", "a class",
          _answer_class,
          (Setting("prefix", "text", "the prefix the class is written with",
                   "oeo"),
           Setting("family", "text", "only classes of this family "
                   "(OEO_)", ""),
           Setting("total_class", "class", "the class written for "
                   "out:total"),
           Setting("outside_root", "labels", "classes counted as outside "
                   "the property's range: class -> name")),
          writes="answers"),
    Brick("kept_coordinates", "condition",
          "Takes a reading only where every dimension with an entry it "
          "must have was read as that entry.", "a reading", "a reason",
          _kept_coordinates),
    Brick("answer_is", "condition",
          "Takes a reading only where a dimension is (or is not) one "
          "answer.", "a reading", "a reason", _answer_is,
          (Setting("coordinate", "text", "the dimension"),
           Setting("is", "text", "the answer it must be"),
           Setting("not", "text", "the answer it must not be"))),
    Brick("has_words", "condition",
          "Takes a reading only where a dimension holds words.",
          "a reading", "a reason", _has_words,
          (Setting("coordinate", "text", "the dimension"),)),
    Brick("named", "condition",
          "Takes a reading only where it is a text that names something.",
          "a reading", "a reason", _named),
    Brick("trimmed", "name",
          "Names the node as the document spells it, without spaces at its "
          "ends.", "a reading", "a name", _trimmed),
    Brick("without_legal_form", "name",
          "Names the node as the document spells it, without a legal form "
          "at its end.", "a reading", "a name", _without_legal_form),
)}


def registry(profile=None) -> dict:
    """{name: Brick}: the core's and *profile*'s own (`kg.BRICKS`)."""
    out = dict(CORE)
    own = profile.component("kg", "BRICKS") if profile is not None else None
    for brick in (own or ()):
        if brick.name in out:
            raise ValueError(f"brick {brick.name!r} of profile "
                             f"{getattr(profile, 'name', '')} is named like "
                             f"one of the core")
        out[brick.name] = brick
    return out
