"""
graph.py: Writes a harvest as the graph the drawing of its profile says.

How the harvest becomes the graph is a drawing in the profile's graph file
(`map` in graph.json, `docpipe.graphfile`), drawn in the Graph tab of
`docpipe edit`. This program writes the graph from that drawing alone,
without a model and without a new harvest:

    a box       a class of the graph; how many nodes it has in a document
                (one per document, per name, per distinct reading, per
                answer of a table, per number, per object another arrow
                wrote) and how a node's address is made
    an arrow    from a field or a coordinate of the harvest to a property
                of a box, from a box to itself (what a brick knows of the
                node), or from a box to a box over a property
    a brick     on an arrow or a box: the code that turns a reading into
                the object of a triple (`bricks.py`, and a profile's own in
                `profiles/<name>/kg.py`)

What the program does for every drawing, with the rules of the graph file
it reads (`readings.py`): one reading where the drawing says the shapes
allow one (rule `front_first_fields` for the fields a publication states on
its front pages), the numbers of one address settled (`rounding_tolerance`,
`contested_in_full`), the first value a file gives a property of a node
kept for later documents, and every triple's passages as comment lines
above it or as evidence nodes (`evidence_as`). The full and the strict
graph are one drawing: a condition or a requirement marked `strict` holds
only for the strict one.

Author: Felix Vossel
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import graphkit
from .bricks import Call, literal, registry
from .fields import COORDINATE_KEYS
from .graphkit import NOT_IN_GRAPH, ttl_comment, ttl_literal
from .identity import tuple_ids
from .readings import front_pages, in_order, pick_one, settle
from .trust import check_prose, render, transcribed_documents, trust

log = logging.getLogger(__name__)

COUNTS = ("per_document", "per_name", "per_distinct", "per_answer",
          "per_value", "per_object")
# The keys of a harvest row an arrow may read beside the coordinates of the
# parameters of its box.
ROW_KEYS = ("value", "value_raw", "value_uri", "value_short", "value_target",
            "unit", "unit_raw", "unit_target")
NL = "\n"


class GraphError(ValueError):
    """A drawing the program cannot write from. It names the entry."""


# -- the drawing --------------------------------------------------------------

def arrow_key(arrow: dict) -> str:
    """How an arrow is named where a drawing or a writer refers to it."""
    return f"{arrow['from']}>{arrow['to']} {arrow['property']}"


@dataclass
class Drawing:
    raw: dict

    def __post_init__(self):
        raw = self.raw
        self.prefixes = dict(raw.get("prefixes") or {})
        self.prefix_width = int(raw.get("prefix_width") or 0)
        self.legal_forms = raw.get("legal_forms") or ""
        self.document = raw.get("document") or {}
        self.evidence = raw.get("evidence") or {}
        self.boxes = list(raw.get("boxes") or ())
        self.arrows = list(raw.get("arrows") or ())
        self.box = {box["id"]: box for box in self.boxes}

    def header(self) -> str:
        return "".join(
            f"@prefix {(name + ':').ljust(self.prefix_width)} <{iri}> .\n"
            for name, iri in self.prefixes.items())

    def subject_of(self, arrow: dict) -> str:
        """The box whose nodes an arrow writes on: the box it points at,
        unless it runs from one box to another, then the one it starts
        at."""
        if arrow["from"] in self.box and arrow["from"] != arrow["to"]:
            return arrow["from"]
        return arrow["to"]

    def kind_of(self, arrow: dict) -> str:
        """`link` from a box to a box, `node` from a box to itself, `field`
        from a reading."""
        if arrow["from"] in self.box:
            return "node" if arrow["from"] == arrow["to"] else "link"
        return "field"

    def written(self, box_id: str) -> bool:
        return self.box[box_id].get("written", True)

    def fields_of(self, box: dict) -> tuple:
        of = box.get("of")
        if isinstance(of, str):
            return (of,)
        if isinstance(of, list) and all(isinstance(one, str) for one in of):
            return tuple(of)
        return ()

    def serves(self, box: dict, uri: str, seen: tuple = ()) -> bool:
        """Whether the nodes of *box* are written from the readings of the
        field *uri*: it is one the box is of, or one of the box it takes its
        answers from (`among`)."""
        if uri in self.fields_of(box):
            return True
        among = box.get("among")
        return among in self.box and among not in seen and self.serves(
            self.box[among], uri, seen + (among,))

    def readers(self, uri: str, coordinate: Optional[str] = None) -> list:
        """The arrows that read the field *uri*, or its coordinate
        *coordinate*: an arrow that starts at the field, at a key of its
        reading into a box written from it, or at the coordinate (bare or
        as its wording, `<coordinate>_raw`) into such a box; for a field,
        also the arrow that links to the box of its readings (one node per
        distinct reading); for a coordinate, the arrows that link to the
        box that is of it (one node per answer)."""
        names = {coordinate, f"{coordinate}_raw"} if coordinate else set()
        out = []
        for arrow in self.arrows:
            box = self.box.get(arrow["to"])
            if box is None:
                continue
            kind = self.kind_of(arrow)
            source = arrow["from"]
            if coordinate is None:
                hit = (kind == "field" and (source == uri or (
                    source in ROW_KEYS and self.serves(box, uri)))) or (
                    kind == "link" and box.get("count") == "per_distinct"
                    and box.get("of") == uri)
            else:
                hit = (kind == "field" and source in names
                       and self.serves(box, uri)) or (
                    kind == "link" and box.get("count") == "per_answer"
                    and box.get("of") == coordinate
                    and self.serves(box, uri))
            if hit:
                out.append(arrow)
        return out

    def says(self) -> set:
        """Every name of the spec the drawing names as a source: where an
        arrow starts, what a box is of, takes its value, name or address
        from, and the strings of the settings of a brick and of a box's
        `settle`."""
        names: set = set()

        def strings(value) -> None:
            if isinstance(value, str):
                names.add(value)
            elif isinstance(value, dict):
                for one in value.values():
                    strings(one)
            elif isinstance(value, (list, tuple)):
                for one in value:
                    strings(one)

        for arrow in self.arrows:
            names.add(arrow["from"])
            strings(arrow.get("settings"))
        for box in self.boxes:
            for key in ("of", "value", "name", "among", "settle"):
                strings(box.get(key))
            strings((box.get("address") or {}).get("from"))
            for key in ("names", "class_brick", "evidence", "name_brick",
                        "address"):
                said = box.get(key)
                if isinstance(said, dict):
                    strings(said.get("settings"))
            for ref in (box.get("admit") or []) + (box.get("when") or []):
                if isinstance(ref, dict):
                    strings(ref.get("settings"))
        return names


# -- what is kept across the documents of one file ----------------------------

@dataclass
class Memory:
    header: bool = True
    # (node, property) -> (value, term)
    settled: dict = field(default_factory=dict)
    told: set = field(default_factory=set)        # nodes written once per file
    minted: dict = field(default_factory=dict)    # (box, node) -> document


@dataclass
class Node:
    box: str
    iri: str
    key: object = None
    name: object = None
    rows: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    values: dict = field(default_factory=dict)    # arrow key -> [value]

    @property
    def row(self) -> Optional[dict]:
        return self.rows[0] if self.rows else None


@dataclass
class Entry:
    predicate: str
    objects: list
    comments: list = field(default_factory=list)
    joined: bool = False


# -- one document -------------------------------------------------------------

class Document:
    """One document being written: its rows, its facts, its nodes, and
    what a brick asks of the writer."""

    def __init__(self, writer: "Writer", name: str, rows: list,
                 decided: Optional[dict]):
        self.writer = writer
        self.name = name
        self.all_rows = rows
        self.decided = decided or {}
        self.facts: dict = {}
        self.rows: list = []
        self.by_field: dict = {}
        self.front: set = {1}
        self.nodes: dict = {}
        self.admitted: dict = {}
        self.contested: dict = {}
        self.counts: Counter = Counter()
        self.held: Counter = Counter()
        self.held_rows: set = set()
        self.asked: dict = {}
        self.recorded: set = set()
        self.evidence_nodes: list = []
        self._chosen: dict = {}
        self._names: dict = {}
        self.ids = dict(zip(map(id, rows), tuple_ids(name, rows)))
        self.transcribed = name in writer.transcribed

    # what bricks ask
    @property
    def spec(self):
        return self.writer.spec

    @property
    def strict(self) -> bool:
        return self.writer.strict

    @property
    def prefixes(self) -> dict:
        return self.writer.drawing.prefixes

    @property
    def legal_forms(self) -> str:
        return self.writer.drawing.legal_forms

    @property
    def extra(self) -> dict:
        return self.writer.extra

    @property
    def base(self) -> str:
        return self.writer.base

    def rule(self, name: str):
        return self.writer.rules.get(name)

    def fold(self, text) -> str:
        return graphkit.normalise(str(text), self.legal_forms)

    def mint(self, folder: str, key: str, name: str) -> str:
        prefix = f"{self.base}{folder}/" if folder else self.base
        return prefix + graphkit.mint_uuid(self.writer.namespace, key, name)

    def count(self, what: str, name: str = "") -> None:
        self.counts[f"{what}:{name}" if name else what] += 1

    def chosen(self, field_: str):
        """The one reading of *field_* the document gives (`pick_one`), the
        front pages first where the rule names the field; the others are
        counted as contested."""
        if field_ in self._chosen:
            return self._chosen[field_]
        offered = self.by_field.get(field_) or []
        value = None
        if offered and field_ in (self.rule("front_first_fields") or ()):
            offered = in_order(offered, self.front, self.rule("front_order"))
        if offered:
            value, others = pick_one(offered, self.rule("pick_one_order"))
            if others:
                self.contested[field_] = others
        self._chosen[field_] = value
        return value

    def picked(self, field_: str):
        """The one reading of *field_* already chosen, None where none
        was."""
        return self._chosen.get(field_)

    def address_of_answer(self, box_id: str, answer) -> Optional[str]:
        box = self.writer.drawing.box[box_id]
        entry = (box.get("table") or {}).get(answer)
        if not isinstance(entry, dict):
            return None
        return self.writer.named_address(self, box, entry)

    def node_of(self, box_id: str, key) -> Optional[Node]:
        return next((node for node in self.nodes.get(box_id) or ()
                     if node.key == key), None)


def _bare(name) -> str:
    """A name without its prefix or namespace: `oeo:OEO_1` and the IRI it
    stands for are the same one."""
    return re.split(r"[/#:]", str(name))[-1]


def _answer_of(key: str, value) -> bool:
    """Is *value* an out: answer of the coordinate *key*, not its wording,
    its quote or what the model saw (`COORDINATE_KEYS`)?"""
    return (isinstance(value, str) and value.startswith(NOT_IN_GRAPH)
            and not any(key.endswith(one)
                        for one in COORDINATE_KEYS if one))


def required_by_class(profile) -> dict:
    """{class: {property}} the shapes of *profile* demand (min count 1 or
    more), taken as the Graph tab takes them; {} for a profile without
    shapes, or without the library that reads them."""
    from ..editor import sourcespage
    files = sourcespage.shape_files(profile)
    if not files:
        return {}
    try:
        from ..compile import shapes
        found, _prefixes = shapes.read(files)
    except ImportError:
        return {}
    out: dict = {}
    for shape in found:
        if not shape.target_class:
            continue
        for prop in shape.properties:
            if (prop.min_count or 0) >= 1:
                out.setdefault(_bare(shape.target_class), set()).add(
                    _bare(prop.path))
    return out


# -- the writer ---------------------------------------------------------------

class Writer:
    def __init__(self, drawing: Drawing, *, spec, rules: dict, bricks: dict,
                 db_path=None, strict: bool = False,
                 extra: Optional[dict] = None,
                 required: Optional[dict] = None):
        self.drawing = drawing
        # {class: {property}} the shapes demand (min count 1 or more),
        # names without prefix or namespace; read once, not per document.
        self.required = required or {}
        self.spec = spec
        self.rules = rules
        self.bricks = bricks
        self.db_path = db_path
        self.strict = strict
        self.extra = extra if extra is not None else {}
        self.base = rules.get("base") or ""
        self.namespace = graphkit.base_namespace(self.base)
        # A database that cannot be opened stops the writer: read as "no
        # document was transcribed" it would raise every transcribed value.
        self.transcribed = transcribed_documents(db_path)
        self.memory = Memory()
        prose = drawing.evidence.get("prose")
        if prose:
            check_prose(prose, "graph.json map.evidence.prose")

    # -- bricks
    def brick(self, ref, kind: str):
        name = ref.get("brick") if isinstance(ref, dict) else ref
        found = self.bricks.get(name)
        if found is None or found.kind != kind:
            raise GraphError(f"no {kind} brick {name!r}")
        return found

    def call(self, ref, kind: str, **given):
        found = self.brick(ref, kind)
        settings = dict(ref.get("settings") or {}) \
            if isinstance(ref, dict) else {}
        return found.run(Call(settings=settings, **given))

    def _applies(self, ref) -> bool:
        graph = ref.get("graph", "both") if isinstance(ref, dict) else "both"
        return graph == "both" or (graph == "strict") == self.strict

    def condition(self, refs, doc: Document, row: dict) -> Optional[str]:
        for ref in refs or ():
            if not self._applies(ref):
                continue
            why = self.call(ref, "condition", doc=doc, row=row)
            if why:
                doc.held_rows.add(id(row))
                return why
        return None

    # -- addresses
    def named_address(self, doc: Document, box: dict, entry=None) -> str:
        address = box.get("address") or {}
        folder = address.get("folder")
        if folder is None and entry is not None:
            folder = entry.get("folder")
        name = str(address.get("name") or "").format(**doc.facts)
        return f"{self.base}{folder}/{name}" if folder else \
            f"{self.base}{name}"

    def minted_address(self, doc: Document, box: dict,
                       node: Optional[Node]) -> tuple:
        """(address, the name it was made from) or (None, None)."""
        address = box.get("address") or {}
        parts = []
        for token in address.get("from") or ():
            if token == "@name":
                parts.append(None if node is None else node.name)
            elif token == "@key":
                parts.append(None if node is None else node.key)
            elif token.startswith("@fact:"):
                parts.append(doc.facts.get(token[len("@fact:"):]))
            else:
                parts.append(doc.chosen(token))
        if address.get("first_present"):
            parts = [next((one for one in parts if one), None)]
        if any(one in (None, "") for one in parts):
            return None, None
        name = "|".join(str(one) for one in parts)
        if address.get("fold"):
            name = doc.fold(name)
        return (doc.mint(address.get("folder") or "", address.get("key")
                         or box["id"], name), parts[0])

    # -- one document
    def write(self, name: str, rows: list,
              decided: Optional[dict] = None) -> Optional["Written"]:
        drawing = self.drawing
        doc = Document(self, name, rows, decided)
        # The document last written, kept for what measures a harvest.
        self.last = doc
        if decided:
            for row in rows:
                tuple_name = doc.ids.get(id(row))
                if tuple_name in decided:
                    doc.asked[id(row)] = decided[tuple_name]
        # 1. the rows the document takes
        for row in rows:
            why = self.condition(drawing.document.get("admit"), doc, row)
            if why is None:
                doc.rows.append(row)
            else:
                doc.held[why] += 1
        for row in doc.rows:
            doc.by_field.setdefault(row.get("parameter"), []).append(row)
        front = drawing.document.get("front_pages")
        if front:
            doc.front = front_pages(
                doc.by_field.get(front, ()),
                which=self.rules.get("front_pages_rule"),
                extra=self.rules.get("front_pages_extra"))
        # 2. the rows of a box of numbers
        for box in drawing.boxes:
            if box["count"] != "per_value":
                continue
            fields_ = drawing.fields_of(box)
            taken = []
            for row in doc.rows:
                if row.get("parameter") not in fields_:
                    continue
                why = self.condition(box.get("admit"), doc, row)
                if why is None:
                    taken.append(row)
                else:
                    doc.held[why] += 1
            doc.admitted[box["id"]] = taken
            if box.get("required") and not taken:
                if doc.held:
                    log.info("graph: %s: nothing written (left out %s)",
                             name, dict(doc.held))
                return None
        # 3. what is known of the document beyond its harvest
        facts = drawing.document.get("facts")
        if facts:
            found = self.call(facts, "facts", doc=doc)
            if found is None:
                return None
            doc.facts = found
        # 4. the readings the shapes allow once
        for arrow in drawing.arrows:
            if arrow.get("single") and drawing.kind_of(arrow) == "field" \
                    and drawing.box[arrow["to"]]["count"] == "per_document":
                doc.chosen(arrow["from"])
        # 5. the nodes of the document
        for box in drawing.boxes:
            if box["count"] != "per_document":
                continue
            address = box.get("address") or {}
            if "name" in address:
                iri, label = self.named_address(doc, box), None
            else:
                iri, label = self.minted_address(doc, box, None)
            if iri is None:
                if box.get("required"):
                    log.info("graph: %s: no %s -- nothing written", name,
                             box["id"])
                    return None
                doc.nodes[box["id"]] = []
                continue
            doc.nodes[box["id"]] = [Node(box["id"], iri, key=iri, name=label,
                                         rows=list(doc.rows))]
        for check in drawing.document.get("check") or ():
            self.call(check, "check", doc=doc)
        # 6. one node, two documents
        for box in drawing.boxes:
            if box["count"] != "per_document" or not box.get("same_node"):
                continue
            for node in doc.nodes.get(box["id"]) or ():
                first = self.memory.minted.setdefault((box["id"], node.iri),
                                                      name)
                if first == name:
                    continue
                if box["same_node"] == "refuse":
                    log.error("graph: %s: the %s <%s> was already written for "
                              "%s -- the document is refused whole (a stale "
                              "duplicate harvest?)", name, box["id"],
                              node.iri, first)
                    return None
                log.warning("graph: %s: the %s <%s> was already written for "
                            "%r -- one node, two documents", name, box["id"],
                            node.iri, first)
        # 7. the numbers
        for box in drawing.boxes:
            if box["count"] == "per_value":
                doc.nodes[box["id"]] = self._numbers(doc, box)
                if box.get("required") and not doc.nodes[box["id"]]:
                    log.info("graph: %s: nothing written (left out %s)",
                             name, dict(doc.held))
                    return None
        # 8. the nodes of a table of answers
        for box in drawing.boxes:
            if box["count"] == "per_answer":
                doc.nodes[box["id"]] = self._answers(doc, box)
                needed = (box.get("strict") or {}).get("requires") \
                    if self.strict else None
                present = {node.key for node in doc.nodes[box["id"]]}
                if needed and not set(needed) <= present:
                    log.info("graph: %s: no %s of %s -- the document is left "
                             "out of the strict graph", name, box["id"],
                             ", ".join(sorted(set(needed) - present)))
                    return None
        # 9. the nodes of names and of readings
        for box in drawing.boxes:
            if box["count"] == "per_name":
                doc.nodes[box["id"]] = self._names_box(doc, box)
            elif box["count"] == "per_distinct":
                doc.nodes[box["id"]] = self._distinct(doc, box)
        # 10. what every node says
        entries: dict = {}
        for box in drawing.boxes:
            if box["count"] == "per_object":
                continue
            for node in doc.nodes.get(box["id"]) or ():
                entries[id(node)] = self._entries(doc, box, node)
        # 11. the nodes other arrows point at
        for box in drawing.boxes:
            if box["count"] == "per_object":
                doc.nodes[box["id"]] = self._objects(doc, box)
                for node in doc.nodes[box["id"]]:
                    entries[id(node)] = self._entries(doc, box, node)
        self._log(doc, entries)
        left = {key: found for key, found in doc.asked.items()
                if key not in doc.recorded}
        if left:
            log.info("graph: %s: %d decision(s) on %d row(s) concern no "
                     "value of the graph", name,
                     sum(len(found) for found in left.values()), len(left))
        return Written(self, doc, entries)

    # -- the line a document leaves in the log
    def _class_of(self, doc: Document, box: dict, node: Node):
        klass = node.data.get("class") or box.get("class")
        if box.get("class_brick"):
            klass = self.call(box["class_brick"], "class", doc=doc,
                              node=node)
        return klass

    def lacking(self, doc: Document, entries: dict) -> dict:
        """{box id: [property]} the shapes demand of the class of a node
        written for the box and some node of it does not say."""
        out: dict = {}
        for box in self.drawing.boxes:
            if not self.drawing.written(box["id"]):
                continue
            for node in doc.nodes.get(box["id"]) or ():
                klass = self._class_of(doc, box, node)
                needed = self.required.get(_bare(klass)) if klass else None
                if not needed:
                    continue
                said = {_bare(one.predicate)
                        for one in entries.get(id(node)) or ()}
                if box.get("uuid"):
                    said.add(_bare(box["uuid"]))
                for one in sorted(needed - said):
                    if one not in out.setdefault(box["id"], []):
                        out[box["id"]].append(one)
        return out

    def by_choice(self, doc: Document) -> Counter:
        """The answers the drawing leaves out on purpose, per answer: an
        out: entry of a list, on a row the document took that no node of
        its own (not one of the document) carries."""
        out: Counter = Counter()
        hung = {id(row) for box in self.drawing.boxes
                if box["count"] != "per_document"
                for node in doc.nodes.get(box["id"]) or ()
                for row in node.rows}
        for row in doc.rows:
            if id(row) in doc.held_rows or id(row) in hung:
                continue
            for key, value in row.items():
                if _answer_of(key, value):
                    out[value] += 1
        return out

    def unhung(self, doc: Document) -> Counter:
        """The readings of a box of names or of readings that no node of the
        box carries, per field and state; an out: entry is counted by
        choice instead."""
        out: Counter = Counter()
        for box in self.drawing.boxes:
            if box["count"] not in ("per_name", "per_distinct"):
                continue
            hung = {id(row) for node in doc.nodes.get(box["id"]) or ()
                    for row in node.rows}
            for field_ in self.drawing.fields_of(box):
                for row in doc.by_field.get(field_, ()):
                    if id(row) in hung or id(row) in doc.held_rows or any(
                            _answer_of(key, one)
                            for key, one in row.items()):
                        continue
                    state = "+".join(sorted({
                        str(one) for key, one in row.items()
                        if key.endswith("_state") and one
                        and one != "read"})) or "missing"
                    out[f"{field_}:{state}"] += 1
        return out

    def _log(self, doc: Document, entries: dict) -> None:
        """One line per document: what it wrote per box, what it lacks that
        the shapes require, and what it left out."""
        wrote = {box["id"]: len(doc.nodes[box["id"]])
                 for box in self.drawing.boxes
                 if doc.nodes.get(box["id"]) and box["count"] != "per_object"
                 and self.drawing.written(box["id"])}
        parts = [f"wrote {wrote}"]
        for label, found in (
                ("contested", {key: len(one) if isinstance(one, list)
                               else one
                               for key, one in doc.contested.items()}),
                ("missing required", self.lacking(doc, entries)),
                ("not in the graph by choice", dict(self.by_choice(doc))),
                ("no node to hang them on", dict(self.unhung(doc))),
                ("counted", dict(doc.counts))):
            if found:
                parts.append(f"{label} {found}")
        log.info("graph: %s: %s, left out %s", doc.name, ", ".join(parts),
                 dict(doc.held))

    # -- nodes
    def _numbers(self, doc: Document, box: dict) -> list:
        ref = box.get("address") or {}

        def address(row: dict, label: str = "") -> str:
            return self.call(ref, "address", doc=doc, row=row, label=label)

        claims: dict = {}
        for row in doc.admitted.get(box["id"]) or ():
            claims.setdefault(address(row), []).append(row)
        settings = box.get("settle") or {}
        values, marks = {}, {}
        for iri, group in claims.items():
            got, lost, named = settle(
                iri, group, address, fold=doc.fold,
                wording=tuple(settings.get("wording") or ()),
                tolerance=float(self.rules.get("rounding_tolerance") or 0),
                order=self.rules.get("settle_order"),
                corroborate=bool(self.rules.get("corroborated_by_place")),
                transcribed=doc.transcribed,
                keep_open=(not self.strict
                           and bool(self.rules.get("contested_in_full"))))
            values.update(got)
            marks.update(named)
            for reason, n in lost.items():
                doc.held[reason] += n
        return [Node(box["id"], iri, key=iri, rows=[row],
                     data={"marks": marks.get(iri, {})})
                for iri, row in values.items()]

    def _answers(self, doc: Document, box: dict) -> list:
        among = doc.nodes.get(box.get("among")) or []
        coordinate = box.get("of")
        present: dict = {}
        for node in among:
            present.setdefault((node.row or {}).get(coordinate), []).extend(
                node.rows)
        out = []
        for answer, entry in (box.get("table") or {}).items():
            if answer in present:
                out.append(Node(box["id"],
                                self.named_address(doc, box, entry),
                                key=answer, name=entry.get("label"),
                                rows=present[answer], data=dict(entry)))
        return out

    def names_of(self, doc: Document, box: dict, row: dict,
                 field_: str) -> list:
        """The names a row of *field_* gives the nodes of *box*, folded."""
        key = (box["id"], id(row), field_)
        if key not in doc._names:
            named = self.call(box.get("names") or {}, "nodes", doc=doc,
                              row=dict(row, parameter=field_), source=field_)
            doc._names[key] = named
        return doc._names[key]

    def _names_box(self, doc: Document, box: dict) -> list:
        wanted: dict = {}
        for field_ in self.drawing.fields_of(box):
            for row in doc.by_field.get(field_, ()):
                for one in self.names_of(doc, box, row, field_):
                    wanted.setdefault(doc.fold(one), one)
        out = []
        for key, name in wanted.items():
            node = Node(box["id"], "", key=key, name=name)
            for field_ in self.drawing.fields_of(box):
                for row in doc.by_field.get(field_, ()):
                    if key in {doc.fold(one) for one in
                               self.names_of(doc, box, row, field_)}:
                        node.rows.append(row)
            node.iri, _ = self.minted_address(doc, box, node)
            if node.iri:
                out.append(node)
        return out

    def _distinct(self, doc: Document, box: dict) -> list:
        reads = box.get("value") or "value"
        if box.get("among"):
            every = [row for node in doc.nodes.get(box["among"]) or ()
                     for row in node.rows]
        else:
            every = list(doc.by_field.get(box.get("of"), ()))
        every = [row for row in every
                 if self.condition(box.get("when"), doc, row) is None]
        taken = every
        if box.get("of") in (self.rules.get("front_first_fields") or ()):
            taken = in_order(every, doc.front,
                             self.rules.get("front_order"))
        keys = {doc.fold(row[reads]) for row in taken}
        groups: dict = {}
        for row in taken + [row for row in every
                            if not any(row is one for one in taken)
                            and doc.fold(row[reads]) in keys]:
            key = doc.fold(row[reads])
            if key not in groups:
                groups[key] = [row[reads], []]
            elif box.get("name") == "last":
                groups[key][0] = row[reads]
            groups[key][1].append(row)
        items = list(groups.items())
        if box.get("order") == "sorted":
            items.sort(key=lambda item: item[0])
        out = []
        for key, (spelling, rows) in items:
            name = spelling
            if box.get("name_brick"):
                name = self.call(box["name_brick"], "name", doc=doc,
                                 value=spelling)
            node = Node(box["id"], "", key=key, name=name, rows=rows)
            node.iri, _ = self.minted_address(doc, box, node)
            if node.iri:
                out.append(node)
        return out

    def _objects(self, doc: Document, box: dict) -> list:
        pointed: dict = {}
        classes = box.get("class_by") or {}
        for part in box.get("of") or ():
            wanted = [a for a in self.drawing.arrows
                      if self.drawing.subject_of(a) == part.get("box")]
            for node in doc.nodes.get(part.get("box")) or ():
                for source in part.get("from") or ():
                    for arrow in wanted:
                        if arrow["from"] != source:
                            continue
                        for value in node.values.get(arrow_key(arrow)) or ():
                            pointed.setdefault(str(value),
                                               classes.get(source))
        out = []
        for iri, klass in pointed.items():
            out.append(Node(box["id"], iri, key=iri, data={"class": klass}))
        return out

    # -- what a node says
    def rows_of(self, doc: Document, node: Node, box: dict,
                source: str) -> list:
        if source in doc.writer.spec.by_uri:
            if box["count"] == "per_distinct" \
                    and source in self.drawing.fields_of(box):
                return list(node.rows)
            if box["count"] == "per_document":
                return list(doc.by_field.get(source, ()))
            if box["count"] == "per_name":
                return [row for row in doc.by_field.get(source, ())
                        if node.key in {doc.fold(one) for one in self.names_of(
                            doc, box, row, source)}]
            held = {id(row) for row in node.rows}
            return [row for row in doc.by_field.get(source, ())
                    if id(row) in held]
        return list(node.rows)

    def related(self, doc: Document, node: Node, box: dict,
                target: dict) -> list:
        targets = doc.nodes.get(target["id"]) or []
        if box["count"] == "per_document" or target["count"] == "per_document":
            return list(targets)
        held = {id(row) for row in node.rows}
        return [one for one in targets
                if any(id(row) in held for row in one.rows)]

    def _holds(self, doc: Document, when: Optional[dict]) -> bool:
        if not when:
            return True
        return any(row.get(when.get("coordinate")) == when.get("is")
                   for row in doc.by_field.get(when.get("field"), ()))

    def _entries(self, doc: Document, box: dict, node: Node) -> list:
        out: list = []
        for arrow in self.drawing.arrows:
            if self.drawing.subject_of(arrow) != box["id"]:
                continue
            kind = self.drawing.kind_of(arrow)
            predicate = arrow["property"]
            joined = arrow.get("objects") == "joined"
            if kind == "link":
                target = self.drawing.box[arrow["to"]]
                if not self.drawing.written(target["id"]) \
                        or not self._holds(doc, arrow.get("when")):
                    continue
                found = [(f"<{one.iri}>", one.iri, [])
                         for one in self.related(doc, node, box, target)]
            elif kind == "node":
                found = [(term, value, [])
                         for term, value, *_ in self.call(
                             arrow, "object", doc=doc, node=node)]
            else:
                found = self._readings(doc, box, node, arrow)
            node.values.setdefault(arrow_key(arrow), [])
            kept = []
            for term, value, rows in found:
                how = arrow.get("first_in_file")
                if how == "keep_first":
                    value, term = self.memory.settled.setdefault(
                        (node.iri, predicate), (value, term))
                node.values[arrow_key(arrow)].append(value)
                if how == "skip_other":
                    held = self.memory.settled.setdefault(
                        (node.iri, predicate), (value, term))
                    if held[0] != value:
                        log.info("graph: <%s> %s stays %r, a later document "
                                 "read %r", node.iri, predicate, held[0],
                                 value)
                        continue
                kept.append((term, rows))
            if not kept:
                continue
            if joined:
                out.append(Entry(predicate, [term for term, _ in kept],
                                 joined=True))
                continue
            for term, rows in kept:
                comments = self._evidence(doc, node, predicate, rows) \
                    if arrow.get("evidence") else []
                out.append(Entry(predicate, [term], comments))
        return out

    def _readings(self, doc: Document, box: dict, node: Node,
                  arrow: dict) -> list:
        """[(term, value, evidence rows)] an arrow from a reading writes."""
        source = arrow["from"]
        rows = self.rows_of(doc, node, box, source)
        brick = self.brick(arrow.get("brick") or "text", "object")
        settings = dict(arrow.get("settings") or {})
        reads = "value" if source in self.spec.by_uri else source
        if arrow.get("pick") == "one_reading":
            if box["count"] == "per_document":
                value = doc.chosen(source)
            else:
                value = (pick_one(rows, self.rules.get("pick_one_order"))[0]
                         if rows else None)
            if value is None:
                return []
            backing = [row for row in rows if row.get("value") == value]
            return [(term, made, backing) for term, made, *_ in brick.run(
                Call(doc=doc, node=node, value=value, settings=settings,
                     source=source))]
        if brick.per == "node":
            out = []
            for term, made, *given in brick.run(Call(
                    doc=doc, node=node, rows=rows, settings=settings,
                    source=source)):
                out.append((term, made, given[0] if given else rows))
            return out
        grouped: dict = {}
        for row in rows:
            for term, made, *_ in brick.run(Call(
                    doc=doc, node=node, row=row, value=row.get(reads),
                    settings=settings, source=source)):
                if term not in grouped:
                    grouped[term] = [made, []]
                grouped[term][1].append(row)
        items = list(grouped.items())
        if arrow.get("order") == "sorted":
            items.sort(key=lambda item: item[0])
        if arrow.get("cite_once"):
            cited: set = set()
            out = []
            for term, (made, backing) in items:
                new = [row for row in backing if id(row) not in cited]
                cited.update(id(row) for row in new)
                out.append((term, made, new))
            return out
        return [(term, made, backing) for term, (made, backing) in items]

    # -- passages
    def _evidence(self, doc: Document, node: Node, predicate: str,
                  sources: list) -> list:
        """The lines above a triple: per passage it was read in, the passage,
        where it stands and how far the run stands behind it."""
        said = self.drawing.evidence
        as_node = self.rules.get("evidence_as") == "node"
        prose, join = said.get("prose") or {}, said.get("join") or ", "
        lines = []
        # The same decision as the node's mark (rule corroborated_by_place).
        confirmed = bool(self.rules.get("corroborated_by_place")) and len(
            {_owner(row) for row in sources}) > 1
        for row in sources:
            if as_node:
                link, block = self._evidence_node(doc, node.iri, predicate,
                                                  row)
                lines.append(link)
                doc.evidence_nodes.append(block)
            else:
                lines.extend(_passage(row, doc.name))
            verdict = trust(row, transcribed=doc.transcribed,
                            conflict=bool(doc.contested.get(
                                row.get("parameter"))),
                            corroborated=confirmed)
            lines.append(_comment(render(verdict, prose, join=join,
                                         row=row)))
            if isinstance(row.get("catalogue"), dict):
                lines.append(_comment(_catalogue_text(row["catalogue"])))
            for decision in doc.asked.get(id(row), ()):
                lines.append(_comment(decision_text(decision)))
                doc.recorded.add(id(row))
        return lines

    def _evidence_node(self, doc: Document, subject: str, predicate: str,
                       row: dict) -> tuple:
        provenance = row.get("provenance") or {}
        shown = shown_value(row)
        place = self.drawing.evidence.get("nodes") or {}
        iri = doc.mint(place.get("folder", "evidence"),
                       place.get("key", "evidence"),
                       doc.fold(f"{subject}|{predicate}|{shown}|"
                                f"{provenance.get('owner_kind')}|"
                                f"{provenance.get('owner_id')}|"
                                f"{row.get('quote')}"))
        block = [f"<{iri}>", "    a oekgprov:ExtractionEvidence ;",
                 f"    oekgprov:aboutProperty {predicate} ;",
                 f"    oekgprov:extractedValue {ttl_literal(shown)} ;",
                 f"    oekgprov:quote {ttl_literal(row.get('quote') or '')} ;",
                 f"    oekgprov:sourceDocument {ttl_literal(doc.name)} ;",
                 f"    oekgprov:evidenceTier "
                 f"{ttl_literal(row.get('tier') or '')} ;"]
        if provenance.get("page"):
            block.append(f'    oekgprov:page "{int(provenance["page"])}"'
                         f'^^xsd:integer ;')
        for rect in provenance.get("rects") or ():
            block.append("    oekgprov:region " + ttl_literal(
                " ".join(str(round(v, 2)) for v in rect)) + " ;")
        block[-1] = block[-1].rstrip(" ;") + " ."
        return f"    oekgprov:hasEvidence <{iri}> ;", NL.join(block) + NL


def _owner(row: dict) -> tuple:
    provenance = row.get("provenance") or {}
    return provenance.get("owner_kind"), provenance.get("owner_id")


def _comment(text) -> str:
    return ttl_comment(text, indent="    ")


def shown_value(row: dict):
    """What a row put in the graph: for an out: entry the document's
    wording, not the entry's own label."""
    uri = row.get("value_uri")
    if uri and str(uri).startswith(NOT_IN_GRAPH):
        return row.get("value_raw") or ""
    return row.get("value")


def _passage(row: dict, document: str) -> list:
    provenance = row.get("provenance") or {}
    where = [f"{document}.pdf"]
    if provenance.get("page"):
        where.append(f"p. {provenance['page']}")
    if provenance.get("owner_kind"):
        where.append(str(provenance["owner_kind"]))
    if row.get("tier"):
        where.append(str(row["tier"]))
    lines = []
    if row.get("quote"):
        lines.append(_comment(f"“{row['quote']}”"))
    elif row.get("reading"):
        # No text states the value: what was read off the figure stands
        # where the quote would (owner decision 2026-11-07).
        lines.append(_comment(f"Read off the figure: {row['reading']}"))
    lines.append(_comment(", ".join(where)))
    if row.get("flags"):
        lines.append(_comment("flags: " + ", ".join(row["flags"])))
    return lines


def _catalogue_text(record: dict) -> str:
    by = {"doi": " by the DOI it prints",
          "index_doi": " by the corpus index's DOI",
          "title": " by its title"}.get(record.get("key"), "")
    said = [f"looked up in {record.get('source')}{by}: {record.get('id')}"]
    if record.get("publication_date"):
        said.append(f"published {record['publication_date']}")
    if record.get("matched"):
        said.append("authors matched: " + ", ".join(record["matched"]))
    return ", ".join(said)


def decision_text(decision: dict) -> str:
    """What a person decided about one field of a value, as a comment line:
    the verdict, who made it and when, and the note."""
    said = [f"decision: {decision['field']} {decision['verdict']}"]
    if decision.get("by"):
        said.append(f"by {decision['by']}")
    if decision.get("at"):
        said.append(str(decision["at"]))
    if decision.get("note"):
        said.append(f"note: {decision['note']}")
    return ", ".join(said)


# -- what was written ---------------------------------------------------------

class Written:
    """One document as the drawing wrote it: its nodes, their triples, the
    text, and what the provenance file records of it."""

    def __init__(self, writer: Writer, doc: Document, entries: dict):
        self.writer = writer
        self.doc = doc
        self.entries = entries

    @property
    def nodes(self) -> dict:
        return self.doc.nodes

    def values(self, node: Node, source: str, to: Optional[str] = None,
               prop: Optional[str] = None) -> list:
        """What the arrow from *source* wrote on *node*, as values."""
        out = []
        for arrow in self.writer.drawing.arrows:
            if arrow["from"] == source and (to is None or arrow["to"] == to) \
                    and (prop is None or arrow["property"] == prop) \
                    and arrow_key(arrow) in node.values:
                out += node.values[arrow_key(arrow)]
        return out

    def text(self) -> str:
        writer, doc, drawing = self.writer, self.doc, self.writer.drawing
        parts = []
        for box in drawing.boxes:
            if not drawing.written(box["id"]):
                continue
            once = box.get("once") == "per_file"
            for node in doc.nodes.get(box["id"]) or ():
                if once:
                    if node.iri in writer.memory.told:
                        continue
                    writer.memory.told.add(node.iri)
                block = self._block(box, node)
                if block:
                    parts.append(block)
        parts += doc.evidence_nodes
        return NL.join(parts)

    def _block(self, box: dict, node: Node) -> Optional[str]:
        writer = self.writer
        lines = []
        if box.get("evidence"):
            lines += writer.call(box["evidence"], "evidence", doc=self.doc,
                                 node=node)
        lines.append(f"<{node.iri}>")
        klass = node.data.get("class") or box.get("class")
        if box.get("class_brick"):
            klass = writer.call(box["class_brick"], "class", doc=self.doc,
                                node=node)
        if klass:
            lines.append(f"    a {klass} ;")
        if box.get("uuid"):
            lines.append(f"    {box['uuid']} "
                         f"{ttl_literal(node.iri.rsplit('/', 1)[-1])} ;")
        merged: list = []
        for entry in self.entries.get(id(node)) or ():
            if entry.joined and merged and merged[-1].joined \
                    and merged[-1].predicate == entry.predicate:
                merged[-1].objects = merged[-1].objects + entry.objects
                continue
            merged.append(Entry(entry.predicate, list(entry.objects),
                                list(entry.comments), entry.joined))
        for entry in merged:
            lines += entry.comments
            if entry.joined:
                lines.append(f"    {entry.predicate} "
                             + " ,\n        ".join(entry.objects) + " ;")
            else:
                lines += [f"    {entry.predicate} {one} ;"
                          for one in entry.objects]
        if lines[-1] == f"<{node.iri}>":
            return None
        lines[-1] = lines[-1].rstrip(" ;") + " ."
        return NL.join(lines) + NL

    def claims(self) -> Optional[dict]:
        said = self.writer.drawing.document.get("claims")
        if not said:
            return None
        doc = self.doc
        owner = (doc.nodes.get(said.get("document")) or [None])[0]
        values = []
        for node in doc.nodes.get(said.get("box")) or ():
            values.append({
                "about": node.iri, "row": node.row,
                "id": doc.ids.get(id(node.row)),
                "bodies": self.writer.call(said, "claims", doc=doc,
                                           node=node)})
        return {"document": owner.iri if owner else None,
                "transcribed": doc.transcribed, "values": values}


# -- what a drawing may name --------------------------------------------------

_SPECIAL = ("@name", "@key")


def check(drawing: Drawing, profile, spec=None, bricks=None) -> list:
    """What *drawing* names that the spec, the shapes or the bricks of
    *profile* do not have, one sentence each: a field the spec does not
    ask, a brick no code has or of another kind, a property the shapes do
    not give the class of the node it is written on. A property the shapes
    demand and no arrow writes is no problem here: the Graph tab shows it
    red."""
    from .spec import load as load_spec
    if spec is None:
        spec = load_spec(profile.component("extraction", "SPEC_PATH"))
    bricks = registry(profile) if bricks is None else bricks
    has_property = profile.component("kg", "has_property") \
        if profile is not None else None
    fields = set(spec.by_uri)
    axes = {name for parameter in spec.by_uri.values()
            for name in (getattr(parameter, "axes", None) or {})}
    axes |= {f"{name}_raw" for name in axes}
    boxes = set(drawing.box)
    problems: list = []

    def brick(ref, kind: str, where: str) -> None:
        if ref is None:
            return
        name = ref.get("brick") if isinstance(ref, dict) else ref
        found = bricks.get(name)
        if found is None:
            problems.append(f"{where}: no brick {name!r}"
                            + _close(name, bricks))
        elif found.kind != kind:
            problems.append(f"{where}: brick {name!r} is a {found.kind} "
                            f"brick, not a {kind} brick")

    def field(name, where: str, coordinates: bool = False) -> None:
        if name in fields or (coordinates and (name in axes
                                               or name in ROW_KEYS)):
            return
        problems.append(f"{where}: {name!r} is no field of the spec"
                        + _close(name, fields | (axes if coordinates
                                                 else set())))

    document = drawing.document
    brick(document.get("facts"), "facts", "document")
    for ref in document.get("admit") or ():
        brick(ref, "condition", "document")
    for ref in document.get("check") or ():
        brick(ref, "check", "document")
    if document.get("claims"):
        brick(document["claims"], "claims", "document")
    if document.get("front_pages"):
        field(document["front_pages"], "document")
    for box in drawing.boxes:
        where = f"box {box['id']}"
        count = box["count"]
        if count in ("per_name", "per_distinct", "per_value"):
            for name in drawing.fields_of(box):
                field(name, where)
        if count == "per_answer":
            field(box.get("of"), where, coordinates=True)
        if box.get("among") is not None and box["among"] not in boxes:
            problems.append(f"{where}: among {box['among']!r}, which is no "
                            f"box")
        if box.get("value"):
            field(box["value"], where, coordinates=True)
        brick(box.get("names"), "nodes", where)
        brick(box.get("class_brick"), "class", where)
        brick(box.get("evidence"), "evidence", where)
        brick(box.get("name_brick"), "name", where)
        for ref in (box.get("admit") or []) + (box.get("when") or []):
            brick(ref, "condition", where)
        address = box.get("address") or {}
        if "brick" in address:
            brick(address, "address", where)
        for token in address.get("from") or ():
            if token in _SPECIAL or str(token).startswith("@fact:"):
                continue
            field(token, where)
        for part in (box.get("of") or []) if count == "per_object" else ():
            if part.get("box") not in boxes:
                problems.append(f"{where}: it describes the objects of "
                                f"{part.get('box')!r}, which is no box")
    for number, arrow in enumerate(drawing.arrows, 1):
        where = (f"arrow {number} ({arrow['from']} -> {arrow['to']} "
                 f"{arrow['property']})")
        if drawing.kind_of(arrow) == "field":
            field(arrow["from"], where, coordinates=True)
        if arrow.get("brick"):
            brick(arrow["brick"], "object", where)
        if has_property is None:
            continue
        subject = drawing.box[drawing.subject_of(arrow)]
        klass = subject.get("class")
        if not klass:
            continue
        said = has_property(klass, arrow["property"])
        if said is False:
            problems.append(f"{where}: the shapes give {klass} no "
                            f"{arrow['property']}")
    return problems


def _close(name, known) -> str:
    import difflib
    close = difflib.get_close_matches(str(name), [str(k) for k in known],
                                      n=3, cutoff=0.6)
    return f" (did you mean {', '.join(close)}?)" if close else ""


# -- the serializer -----------------------------------------------------------

def load_drawing(profile, environ=None) -> Drawing:
    """The drawing of *profile*'s graph file, or GraphError without one."""
    from .. import graphfile
    made = graphfile.load(profile, environ)
    if not made.map:
        raise GraphError(f"the graph file of {getattr(profile, 'name', '')} "
                         f"has no drawing (map): nothing says how its harvest "
                         f"becomes a graph")
    return Drawing(made.map)


def make_writer(profile, db_path=None, *, strict: bool = False,
                extra: Optional[dict] = None,
                drawing: Optional[Drawing] = None,
                environ=None) -> Writer:
    from .. import graphfile
    from .spec import load as load_spec
    made = graphfile.load(profile, environ)
    drawing = drawing or (Drawing(made.map) if made.map else None)
    if drawing is None:
        raise GraphError(f"the graph file of {getattr(profile, 'name', '')} "
                         f"has no drawing (map)")
    spec = load_spec(profile.component("extraction", "SPEC_PATH"))
    bricks = registry(profile)
    context = profile.component("kg", "context")
    if extra is None:
        extra = context(db_path) if context else {}
    elif context:
        extra = {**context(db_path), **extra}
    return Writer(drawing, spec=spec, rules=dict(made.rules), bricks=bricks,
                  db_path=db_path, strict=strict, extra=extra,
                  required=required_by_class(profile))


def make_serializer(profile, db_path=None, *, strict: bool = False,
                    extra: Optional[dict] = None,
                    drawing: Optional[Drawing] = None) -> Callable:
    """(document name, accepted rows) -> Turtle or None, written from the
    drawing of *profile*. `claims` holds per document what the provenance
    file records."""
    writer = make_writer(profile, db_path, strict=strict, extra=extra,
                         drawing=drawing)

    def serializer(name: str, rows: list):
        written = writer.write(name, rows, (serializer.decisions or {}).get(
            name) if hasattr(serializer, "decisions") else None)
        if written is None:
            return None
        text = written.text()
        claims = written.claims()
        if claims is not None:
            serializer.claims[name] = claims
        if writer.memory.header:
            writer.memory.header = False
            return writer.drawing.header() + NL + text
        return text

    serializer.claims = {}
    serializer.writer = writer
    if writer.drawing.document.get("decisions"):
        serializer.decisions = {}
    return serializer
