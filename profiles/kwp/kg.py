"""
kg.py: The bricks only the kwp profile's graph needs, and how the answer
app asks that graph.

How the harvest of a heat plan becomes the MHPKG graph is the drawing in
graph.json beside this file (`map`), written by the core's program
(`docpipe/extraction/graph.py`). Here are the pieces only this profile has:
what the register knows of a plan (its AGS, publication date and
municipality), which numbers the graph takes and why the others stay in the
harvest, the address of a number (the coordinate list of the IRI policy,
mint_slice.py), its class and unit, the comment lines above it, and what the
provenance file records of it.

The IRI policy must stay a pure function of the data: two runs over the
same plan mint byte-identical IRIs.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from docpipe import graphfile, rules
from docpipe.extraction.bricks import Brick, Call, Setting
from docpipe.extraction.fields import DERIVED
from docpipe.extraction.graphkit import NOT_IN_GRAPH, ttl_comment
from docpipe.extraction.spec import expanded, load as load_spec
from docpipe.extraction.trust import check_prose, render, trust
from docpipe.store.schema import readonly_uri
from profiles.kwp import mhpkg

log = logging.getLogger(__name__)

OEO = "https://openenergyplatform.org/ontology/oeo/"

# The MHPKG schema the last refresh pulled (mhpkg.py): the closed lists and
# the value classes of the strict graph are its.
SHAPE = mhpkg.load()
# Each field with its shared dimensions in place (`spec.expanded`).
_SPEC = expanded(json.loads(
    Path(__file__).with_name("extraction_spec.json").read_text(
        encoding="utf-8")))


def spec():
    """The spec as the extraction stage loads it with the rules in effect
    now. The answer app's graph route reads its lists off it
    (`docpipe.inference.kg_route`)."""
    return rules.derived("kwp.kg.spec", lambda: load_spec(_SPEC))


def drawing() -> dict:
    """The drawing, as the graph file of this profile has it now."""
    return graphfile.get_map("kwp")


def prefix_iri() -> dict:
    """{prefix: IRI} of the header the drawing writes now."""
    return dict(drawing().get("prefixes") or {})


# The vocabulary the provenance of this graph's values is written in
# (docpipe/extraction/provenance.py), under the graph rule `base`, which the
# run reads where it writes. The terms are the ones proposed to the
# ontology; until they are published there they resolve nowhere, which is
# why the provenance is a file of its own.
PROVENANCE = {"prefix": "mhpx", "iri": "https://purl.org/mhpo/prov/"}


def expand(name: str) -> str:
    """`mhpo:MHPO_00020007` -> the full IRI, from the header this graph
    writes. An unbound prefix raises rather than defaults."""
    prefix, _, local = str(name).partition(":")
    bound = prefix_iri()
    if not local or prefix not in bound:
        raise KeyError(f"{name!r} is bound to no prefix of the drawing")
    return bound[prefix] + local


_OEO_CLASS = re.compile(r"OEO_\d+")
_IDENTIFIER = re.compile(r"[A-Za-z]+_[0-9]+")
# Which prefix an identifier belongs to, by its family. Unknown family is an
# error and not a default: defaulting to oeo: would mint oeo:UO_0000111, an
# IRI that does not exist, and say nothing.
_NAMESPACE = {"OEO_": "oeo", "MHPO_": "mhpo", "BFO_": "obo", "UO_": "obo"}


def is_class(value) -> bool:
    """True for a real OEO class, false for every deliberate non-class: the
    axes hold entries that say what a row IS when no class fits."""
    return bool(_OEO_CLASS.fullmatch(str(value or "")))


def qualified(identifier: str) -> str:
    """A bare ontology id as this graph writes it."""
    if not _IDENTIFIER.fullmatch(str(identifier)):
        raise KeyError(f"{identifier!r} is no bare identifier")
    for family, prefix in _NAMESPACE.items():
        if identifier.startswith(family):
            return f"{prefix}:{identifier}"
    raise KeyError(f"no prefix is bound for the family of {identifier!r}")


def _bare(name: str) -> str:
    return str(name).split(":")[-1]


def has_property(klass: str, prop: str) -> Optional[bool]:
    """Whether the MHPKG schema gives the class (a curie) the property (a
    curie); None where the schema has no such class."""
    name = SHAPE.class_named(klass)
    if name is None:
        return None
    return any(SHAPE.has_slot(name, slot)
               for slot, block in SHAPE.slots.items()
               if (block or {}).get("slot_uri") == prop)


# The classes the graph takes: the entries of the class list that are no
# `out:` answer. A cumulative sum, an avoided or captured amount stand in the
# list so the model can choose them instead of the nearest real class.
QUANTITIES = frozenset(uri for par in _SPEC["parameters"]
                       if par.get("unit_target")
                       for uri in par["axes"]["quantity"]["vocabulary"]
                       if not uri.startswith(NOT_IN_GRAPH))
# The unit a value is written in is its parameter's; an entry of
# units_accepted may convert onto a unit of its own ("target").
UNIT_TARGET = {par["uri"]: par["unit_target"] for par in _SPEC["parameters"]
               if par.get("unit_target")}
ENTRY_TARGET = {(par["uri"], unit): entry["target"]
                for par in _SPEC["parameters"]
                for unit, entry in (par.get("units_accepted") or {}).items()
                if isinstance(entry, dict) and entry.get("target")}
AGGREGATIONS = {uri for par in _SPEC["parameters"]
                if "aggregation" in par.get("axes", {})
                for uri in par["axes"]["aggregation"]["vocabulary"]}


def target_of(row: dict) -> Optional[str]:
    """The unit this value's number was converted onto."""
    return ENTRY_TARGET.get((row.get("parameter"), row.get("unit")),
                            UNIT_TARGET.get(row.get("parameter")))


def unit_of(row: dict) -> Optional[str]:
    """The unit the graph writes this value in, None outside the graph: the
    unit its number was converted onto, where that is an ontology term."""
    if row.get("quantity") not in QUANTITIES:
        return None
    target = target_of(row)
    return target if target and _IDENTIFIER.fullmatch(target) else None


# The plan parts the schema holds values in, and the slot that holds them.
CONTAINERS = ("TargetScenario", "AggregatedInventoryAnalysis")
CONTAINER_SLOT = "covers_parameter"


def _box(box_id: str) -> dict:
    return next(box for box in drawing().get("boxes") or ()
                if box.get("id") == box_id)


def _arrow(source: str, to: str) -> dict:
    return next(arrow for arrow in drawing().get("arrows") or ()
                if arrow.get("from") == source and arrow.get("to") == to)


def _property(source: str, to: str) -> str:
    """The property of the drawing's arrow from *source* to *to*."""
    return _arrow(source, to)["property"]


def totals(drawing: dict, box_id: str) -> dict:
    """{coordinate: class} the arrows of *box_id* write for out:total."""
    return {arrow["from"]: (arrow.get("settings") or {}).get("total_class")
            for arrow in drawing.get("arrows") or ()
            if arrow.get("to") == box_id}


def written(row: dict, axis: str, total: dict):
    """What the graph writes for this coordinate: the class read, or for a
    number the plan does not split by this axis (`out:total`) the class the
    drawing names for it, or nothing."""
    value = row.get(axis)
    if value == "out:total":
        return total.get(axis)
    return value


def schema_class_of(row: dict, table: dict) -> Optional[str]:
    """The schema class this value is in its part: the class the model
    chose, or the schema's value class it falls under, or None."""
    container = (table.get(row.get("scenario")) or {}).get("schema_class")
    if container not in CONTAINERS:
        return None
    quantity = row.get("quantity")
    from profiles.kwp import vocabulary
    sets = vocabulary.load()["sets"]
    for name in SHAPE.value_classes(container, CONTAINER_SLOT):
        if quantity == _bare(SHAPE.cls(name)) \
                or quantity in (sets.get(f"mhpkg:{name}") or ()):
            return name
    return None


def strict_refusal(row: dict, table: dict, total: dict) -> Optional[str]:
    """Why this value has no place in the strict graph, or None: the strict
    graph holds what the schema's shapes take, a value class the part
    holds, every required slot, and every slot's answer from the schema's
    own closed list."""
    name = schema_class_of(row, table)
    if name is None:
        return "class"
    if row.get("spatial_scope") != "municipality":
        return "area"           # the schema relates no value to an area
    given = {"has_unit": unit_of(row),
             "refers_to_energy_carrier": written(row, "carrier", total),
             "refers_to_sector": written(row, "sector", total),
             "refers_to_technology": row.get("technology"),
             "has_aggregation_type": row.get("aggregation")}
    required = SHAPE.required(name)
    for slot, value in given.items():
        value = value if is_class(value) or _IDENTIFIER.fullmatch(
            str(value or "")) else None
        if not SHAPE.has_slot(name, slot):
            if value:
                return f"no_slot:{slot}"
            continue
        if not value:
            if slot in required:
                return f"missing:{slot}"
            continue
        if not SHAPE.admits(name, slot, qualified(value)):
            return f"off_list:{slot}"
    return None


def _iso_date(raw) -> str:
    """`published` as the IRI policy spells it: YYYY-MM-DD. Ingest writes
    YYYYMMDD; one place converts, and it takes both."""
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def document_identity(db_path: Path, name: str):
    """(ags, published, municipality name) or None."""
    conn = sqlite3.connect(readonly_uri(db_path), uri=True)
    try:
        row = conn.execute(
            "SELECT id, published FROM Documents "
            "WHERE filename IN (?, ?)", (f"{name}.pdf", name)).fetchone()
        if row is None:
            return None
        document_id, published = row
        try:
            meta = conn.execute(
                "SELECT dm.municipality_ags, m.name FROM DocumentMeta dm "
                "LEFT JOIN Municipalities m ON m.ags = dm.municipality_ags "
                "WHERE dm.document = ?", (document_id,)).fetchone()
        except sqlite3.OperationalError:      # legacy schema: inline column
            meta = conn.execute(
                "SELECT municipality_ags, NULL FROM Documents WHERE id = ?",
                (document_id,)).fetchone()
    finally:
        conn.close()
    ags = str(meta[0]).strip() if meta and meta[0] is not None else ""
    published = _iso_date(published)
    if not ags.isdigit() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        return None
    return ags.zfill(8), published, (meta[1] if meta else None)


def facts_of(identity) -> dict:
    ags, published, municipality = identity
    return {"ags": ags, "published": published, "year": published[:4],
            "municipality": municipality,
            "place": municipality or f"AGS {ags}"}


def heatplan_iri(db_path: Path, name: str) -> Optional[str]:
    """The plan node the drawing makes for this document, or None: one
    making for the graph and for whoever asks it."""
    identity = document_identity(db_path, name)
    if identity is None:
        return None
    plan = _box("plan")
    folder = (plan.get("address") or {}).get("folder")
    words = (plan.get("address") or {}).get("name") or ""
    base = graphfile.get("base", "kwp")
    return f"{base}{folder}/{words.format(**facts_of(identity))}"


# -- the words above a number ----------------------------------------------------

# Short English labels for the two coordinates that make no OEO class of
# their own -- the plan part and the whole municipality -- and for an axis'
# `out:` entries, which hold no vocabulary label either. The spec's own
# labels are worded for the model's prompt and stay German on purpose.
SCENARIO_LABEL_EN = {"status_quo": "baseline inventory",
                     "trend": "trend scenario", "target": "target scenario"}
OUT_LABEL_EN = {
    "out:generation": "generation/supply",
    "out:useful_energy": "useful energy", "out:saving": "saving",
    "out:share": "share",
    "out:specific": "specific value (per area, head or building)",
    "out:other": "other", "out:cumulative": "cumulative amount",
    "out:avoided": "avoided amount", "out:captured": "captured amount",
    "out:factor": "emission factor", "out:electric": "electrical power",
    "out:seasonal": "seasonal power", "out:total": "sum",
    "out:variant": "variant",
}


def _english_label(uri) -> str:
    """A coordinate's value in English: the pinned vocabulary's label for a
    real OEO class, the short label above for a deliberate non-class."""
    if not uri:
        return ""
    if is_class(uri):
        from profiles.kwp import vocabulary
        term = vocabulary.load()["terms"].get(_bare(uri)) or {}
        return term.get("label") or _bare(uri)
    return OUT_LABEL_EN.get(uri, _bare(uri))


def evidence_comment(row: dict, document: str, prose: dict, join: str, *,
                     transcribed: bool = False, conflict: bool = False,
                     corroborated: bool = False,
                     resolved: Optional[str] = None,
                     named: Optional[str] = None,
                     across_runs: Optional[list] = None) -> list:
    """Where this value was read, as comment lines above its node: the
    coordinates in English, the passage, the page, how it was aggregated,
    what was computed, and how far the run stands behind it."""
    verdict = trust(row, transcribed=transcribed, conflict=conflict,
                    corroborated=corroborated)
    prov = row.get("provenance") or {}
    where = [f"{document}.pdf"]
    if prov.get("page"):
        where.append(f"page {prov['page']}")
    kind = {"section": "section", "table": "table",
            "figure": "figure"}.get(prov.get("owner_kind"))
    if kind:
        where.append(kind + (f' "{prov["title"]}"' if prov.get("title")
                             else ""))
    scope = ("whole municipality"
             if row.get("spatial_scope") == "municipality"
             else (row.get("spatial_scope_raw") or "").strip() or "sub-area")
    what = [_english_label(row.get("quantity")),
            SCENARIO_LABEL_EN.get(row.get("scenario"),
                                  row.get("scenario") or ""),
            scope,
            _english_label(row.get("carrier")),
            _english_label(row.get("sector"))]
    lines = [ttl_comment(" · ".join(x for x in what if x))] if any(what) \
        else []
    if row.get("quote"):
        lines.append(ttl_comment(f'"{row["quote"]}"'))
    elif row.get("reading"):
        # No text states the number: what was read off the figure stands
        # where the quote would (owner decision 2026-11-07).
        lines.append(ttl_comment(f"Read off the figure: {row['reading']}"))
    lines.append(ttl_comment(", ".join(where)))
    aggregation = row.get("aggregation")
    if aggregation:
        raw = (row.get("aggregation_raw") or "").strip()
        if row.get("aggregation_state") == DERIVED:
            note = f"Aggregation: {aggregation}"
            lines.append(ttl_comment(
                note + (f" (from the unit {raw})" if raw else "")))
        elif raw:
            lines.append(ttl_comment(f'Aggregation: {aggregation} "{raw}"'))
    if row.get("compute"):
        lines.append(ttl_comment(f"computed: {row['compute']}"))
    if row.get("flags"):
        lines.append(ttl_comment("Flags: " + ", ".join(row["flags"])))
    if named:
        lines.append(ttl_comment(f'Named by the plan\'s wording: "{named}"'))
    if resolved:
        lines.append(ttl_comment(
            {"rounding": "Kept over a rounded reading of the same number",
             "trust": "Kept over a reading of the same coordinates with a "
                      "lower trust level"}[resolved]))
    if across_runs:
        # the other harvests disagree (owner decision 2026-11-17)
        lines.append(ttl_comment("Contested across runs: "
                                 + "; ".join(across_runs)))
    lines.append(ttl_comment(render(verdict, prose, join=join, row=row)))
    return lines


def class_iri(identifier) -> Optional[str]:
    """The full IRI of an OEO class, None for anything else."""
    if not identifier or not is_class(identifier):
        return None
    try:
        return expand(qualified(identifier))
    except KeyError:
        return None


# -- the blocks ------------------------------------------------------------------
#
# What the drawing of this graph does beyond the core's bricks is written in
# it as blocks (`docpipe/extraction/graphblocks.py`, owner request
# 2026-11-14, wish 4): conditions about the reading, an address made of
# parts, steps, and Python that calls the functions above. `PRESETS` holds
# each as the shipped drawing has it, so the Graph tab can put it in again;
# one check, whether the MHPKG schema's shapes take a value, stays a brick
# with settings, since no condition says it.

def _schema_admits(call: Call) -> Optional[str]:
    drawing = call.doc.writer.drawing
    part = call.settings.get("part", "part")
    why = strict_refusal(call.row, drawing.box[part].get("table") or {},
                         totals(drawing.raw, call.settings.get("box",
                                                               "value")))
    return f"mhpkg:{why}" if why else None


BRICKS = (
    Brick("schema_admits", "condition",
          "Takes a number only where the MHPKG schema's shapes take it: a "
          "value class its part holds, every required slot, every answer "
          "from the schema's closed lists.", "a reading", "a reason",
          _schema_admits,
          (Setting("part", "text", "the box of the plan parts", "part",
                   title="Box of the plan parts"),
           Setting("box", "text", "the box of the numbers", "value",
                   title="Box of the numbers"))),
)


def _if(rows: list, reason: str, joined: str = "all") -> dict:
    return {"if": {joined: rows}, "reason": reason}


def _row(path: str, op: Optional[str] = None, value=None,
         no: bool = False) -> dict:
    row: dict = {"of": "reading", "is": path}
    if op is not None:
        row["op"] = op
    if value is not None:
        row["value"] = value
    if no:
        row["not"] = True
    return row


_REGISTER = '''def run(call):
    """The plan in the register: its AGS, its publication date and its
    municipality ({ags}, {published}, {year}, {place}); a plan without AGS
    or date is not written."""
    doc = call.doc
    identity = kg.document_identity(doc.writer.db_path, doc.name)
    if identity is None:
        log.warning("graph: %s: no AGS or publication date -- %d tuple(s) "
                    "not written", doc.name,
                    sum(len(rows) for rows in doc.admitted.values()))
        return None
    return kg.facts_of(identity)
'''

_VALUE_CLASS = '''def run(call):
    """The class the quantity was read as, and in the strict graph also the
    schema's value class above it."""
    row = call.node.row
    typed = kg.qualified(row[call.settings.get("coordinate", "quantity")])
    if not call.doc.strict:
        return typed
    part = call.doc.writer.drawing.box[call.settings.get("part", "part")]
    schema = kg.schema_class_of(row, part.get("table") or {})
    if schema and kg.SHAPE.cls(schema) != typed:
        # A CO2-equivalent value IS a greenhouse gas emission value; a shape
        # without a reasoner only sees the class written.
        typed += f", {kg.SHAPE.cls(schema)}"
    return typed
'''

_PASSAGE = '''def run(call):
    """Above a number its dimensions in English, the passage, the page, how
    it was aggregated or computed and its trust level."""
    node = call.node
    return kg.evidence_comment(node.row, call.doc.name,
                               call.settings.get("prose") or {},
                               call.settings.get("join") or " · ",
                               transcribed=call.doc.transcribed,
                               **(node.data.get("marks") or {}))
'''

_BODIES = '''def run(call):
    """For the provenance file, the node or class each dimension of a
    number became."""
    doc, row = call.doc, call.node.row
    said = call.settings
    total = kg.totals(doc.writer.drawing.raw, said.get("box", "value"))
    whole = (doc.nodes.get(said.get("whole", "municipality")) or [None])[0]
    area = whole.iri if whole else None
    if row.get("spatial_scope") == "sub_area":
        node = doc.node_of(said.get("area", "area"),
                           doc.fold(row["spatial_scope_raw"]))
        area = node.iri if node else area
    found = {"quantity": kg.class_iri(row.get("quantity")),
             "carrier": kg.class_iri(kg.written(row, "carrier", total)),
             "sector": kg.class_iri(kg.written(row, "sector", total)),
             "technology": kg.class_iri(row.get("technology")),
             "aggregation": kg.class_iri(row.get("aggregation")),
             "scenario": doc.address_of_answer(said.get("part", "part"),
                                               row["scenario"]),
             "spatial_scope": area}
    return {axis: iri for axis, iri in found.items() if iri}
'''

_SUB_AREA = {"all": [_row("spatial_scope", "is", "sub_area")]}

PRESETS = (
    {"name": "plan_register", "kind": "facts",
     "does": "Looks the plan up in the register: its AGS, its publication "
             "date and its municipality; a plan without AGS or date is not "
             "written.",
     "block": {"python": _REGISTER}},
    {"name": "quantity_listed", "kind": "condition",
     "does": "Takes a number only where its class is one of the classes the "
             "graph takes (no out: answer).",
     "block": _if([_row("quantity", "listed")],
                  "not_a_class:{quantity|quantity_raw|'?'}")},
    {"name": "scenario_read", "kind": "condition",
     "does": "Takes a number only where its scenario was read.",
     "block": _if([_row("scenario", "empty", no=True)], "scenario_unread")},
    {"name": "part_known", "kind": "condition",
     "does": "Takes a number only where its scenario is an answer of the "
             "table of plan parts.",
     "block": _if([_row("scenario", "answer_of", "part")],
                  "scenario:{scenario}")},
    {"name": "scope_listed", "kind": "condition",
     "does": "Takes a number only where its area, where one was read, is one "
             "of the entries.",
     "block": _if([_row("spatial_scope", "empty"),
                   _row("spatial_scope", "one_of",
                        ["municipality", "sub_area"])], "spatial_scope",
                  "any")},
    {"name": "sub_area_named", "kind": "condition",
     "does": "Takes a number of a sub-area only where the plan names the "
             "sub-area.",
     "block": _if([_row("spatial_scope", "is", "sub_area", no=True),
                   _row("spatial_scope_raw", "empty", no=True)],
                  "sub_area_unnamed", "any")},
    {"name": "year_read", "kind": "condition",
     "does": "Takes a number only where its year was read.",
     "block": _if([_row("year", "whole")], "year")},
    {"name": "unit_listed", "kind": "condition",
     "does": "Takes a number only where its unit is listed and it was "
             "converted.",
     "block": _if([_row("value_target", "empty", no=True)],
                  "unit_unlisted:{unit_raw|'?'}")},
    {"name": "unit_in_ontology", "kind": "condition",
     "does": "Takes a number only where the unit it was converted onto is an "
             "ontology term.",
     "block": _if([_row("quantity", "listed"), _row("unit_target", "term")],
                  "unit_not_in_ontology:{unit_target}")},
    {"name": "aggregation_listed", "kind": "condition",
     "does": "Takes a number only where its aggregation, where one was read, "
             "is listed.",
     "block": _if([_row("aggregation", "empty"),
                   _row("aggregation", "listed")],
                  "aggregation:{aggregation}", "any")},
    {"name": "value_identity", "kind": "address",
     "does": "A number's address from the IRI policy's dimensions: plan "
             "part, class, carrier, sector, year, aggregation, sub-area and "
             "technology, and the plan's words where they split it.",
     "block": {"folder": "value", "key": "value", "from": [
         {"from": "answer_address", "box": "part", "of": "scenario",
          "absent": "empty"},
         {"of": "quantity", "form": "iri", "prefix": "oeo"},
         {"of": "carrier", "total": True, "form": "class", "prefix": "oeo",
          "family": "OEO_", "absent": "empty"},
         {"of": "sector", "total": True, "form": "class", "prefix": "oeo",
          "family": "OEO_", "absent": "empty"},
         {"of": "year", "form": "text", "absent": "empty"},
         {"of": "aggregation", "form": "iri", "prefix": "oeo",
          "absent": "empty"},
         {"of": "spatial_scope_raw", "when": _SUB_AREA, "form": "fold",
          "absent": "empty"},
         {"of": "technology", "form": "class", "prefix": "oeo",
          "family": "OEO_", "absent": "omit"},
         {"from": "wording", "absent": "omit"}]}},
    {"name": "value_class", "kind": "class",
     "does": "Writes a number as the class its quantity was read as, and in "
             "the strict graph also as the schema's value class above it.",
     "block": {"python": _VALUE_CLASS,
               "settings": {"part": "part", "coordinate": "quantity"}}},
    {"name": "value_unit", "kind": "object",
     "does": "Writes the unit the number was converted onto, with the prefix "
             "of its family.",
     "block": {"steps": [{"brick": "answer_class", "settings": {
         "prefix_by_family": {"OEO_": "oeo", "MHPO_": "mhpo", "BFO_": "obo",
                              "UO_": "obo"}}}],
         "writes": "key:unit_target"}},
    {"name": "value_passage", "kind": "evidence",
     "does": "Writes above a number its dimensions in English, the passage, "
             "the page, how it was aggregated or computed and its trust "
             "level.",
     "block": {"python": _PASSAGE}},
    {"name": "value_bodies", "kind": "claims",
     "does": "Records for the provenance file the node or class each "
             "dimension of a number became.",
     "block": {"python": _BODIES}},
)


# -- asking the graph ------------------------------------------------------------
#
# The coordinates a question can fix, in the order the spec asks them. Two
# real axes are deliberately absent: `spatial_scope` has no edge from a
# value (the schema has no slot for one), and `aggregation` is returned
# rather than constrained.
COORDINATE_AXES = ("scenario", "quantity", "carrier", "sector", "year")

def trust_prose() -> dict:
    """The trust words of the comment above a number, for the answer app,
    as the drawing's value box has them now."""
    value = _box("value")
    return check_prose(dict((value.get("evidence") or {}).get(
        "settings", {}).get("prose") or {}), "graph.json map, value evidence")


def parts() -> dict:
    """{scenario: (class, folder, label)} of the plan parts the drawing's
    part box lists now."""
    return {key: (entry.get("class"), entry.get("folder"), entry.get("label"))
            for key, entry in (_box("part").get("table") or {}).items()}


def value_query() -> str:
    """The query, over the drawing the graph is written from now, so the
    two cannot drift."""
    has_part = _property("plan", "part")
    has_quantity_value = _property("part", "value")
    number = _property("value_target", "value")
    unit = _property("unit_target", "value")
    carrier = _property("carrier", "value")
    sector = _property("sector", "value")
    technology = _property("technology", "value")
    year = _property("year", "value")
    aggregation = _property("aggregation", "value")
    return "\n".join(
        [f"PREFIX {prefix}: <{iri}>" for prefix, iri in prefix_iri().items()]
        + [f"""
SELECT ?value ?quantity ?number ?unit ?year ?aggregation ?part ?partLabel
       (GROUP_CONCAT(DISTINCT STR(?about); separator=" ") AS ?abouts)
WHERE {{
  ?plan  {has_part} ?part .
  ?part  a ?partClass ;
         rdfs:label ?partLabel ;
         {has_quantity_value} ?value .
  ?value a ?quantity ;
         {number} ?number ;
         {unit} ?unit ;
         {year} ?year .
  OPTIONAL {{ ?value {aggregation} ?aggregation }}
  OPTIONAL {{ ?value {carrier}|{sector}|{technology} ?about }}
  FILTER (?plan = ?PLAN)
##CONSTRAINTS##
}}
GROUP BY ?value ?quantity ?number ?unit ?year ?aggregation ?part ?partLabel
ORDER BY ?year ?number"""])


def value_bindings(coordinates: dict) -> tuple:
    """(constraint lines for ##CONSTRAINTS##, {variable: (kind, value)}).

    An unbound axis adds no line. A quantity the graph does not hold and any
    `out:` entry are dropped here, because `oeo:out:share` is an IRI that
    does not exist.
    """
    lines, bindings = [], {}
    scenario = coordinates.get("scenario")
    table = parts()
    if scenario in table:
        lines.append("  FILTER (?partClass = ?PART)")
        bindings["PART"] = ("iri", expand(table[scenario][0]))
    quantity = coordinates.get("quantity")
    if quantity in QUANTITIES:
        lines.append("  FILTER (?quantity = ?QUANTITY)")
        bindings["QUANTITY"] = ("iri", expand(qualified(quantity)))
    year = coordinates.get("year")
    if isinstance(year, int):
        lines.append("  FILTER (STR(?year) = ?YEAR)")
        bindings["YEAR"] = ("literal", str(year))
    for axis, variable, predicate in (
            ("carrier", "CARRIER", _property("carrier", "value")),
            ("sector", "SECTOR", _property("sector", "value"))):
        uri = coordinates.get(axis)
        if uri and is_class(uri):
            lines.append(f"  ?value {predicate} ?{variable} .")
            bindings[variable] = ("iri", OEO + uri)
    return "\n".join(lines), bindings


def _first_spelling(entry) -> Optional[str]:
    if isinstance(entry, dict):
        return entry.get("label") or next(iter(entry.get("spellings") or []),
                                          None)
    if isinstance(entry, (list, tuple)) and entry:
        return entry[0]
    return None


def label_of(identifier: str) -> str:
    """What a reader calls a class: the spec's first spelling for it, else
    the pinned vocabulary's label, else the identifier itself."""
    text = str(identifier or "")
    bare = text[len(OEO):] if text.startswith(OEO) else _bare(text)
    for par in _SPEC["parameters"]:
        for axis in (par.get("axes") or {}).values():
            spelling = _first_spelling((axis.get("vocabulary") or {}).get(
                bare))
            if spelling:
                return spelling
    from profiles.kwp import vocabulary
    term = vocabulary.load()["terms"].get(bare) or {}
    return term.get("label") or bare
