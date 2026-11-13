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
from docpipe.extraction.spec import load as load_spec
from docpipe.extraction.trust import check_prose, render, trust
from docpipe.store.schema import readonly_uri
from profiles.kwp import mhpkg

log = logging.getLogger(__name__)

OEO = "https://openenergyplatform.org/ontology/oeo/"

# The MHPKG schema the last refresh pulled (mhpkg.py): the closed lists and
# the value classes of the strict graph are its.
SHAPE = mhpkg.load()
_SPEC = json.loads(
    Path(__file__).with_name("extraction_spec.json").read_text(
        encoding="utf-8"))


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
                     named: Optional[str] = None) -> list:
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
    lines.append(ttl_comment(render(verdict, prose, join=join, row=row)))
    return lines


def _class_iri(identifier) -> Optional[str]:
    if not identifier or not is_class(identifier):
        return None
    try:
        return expand(qualified(identifier))
    except KeyError:
        return None


# -- the bricks ------------------------------------------------------------------

def _register(call: Call):
    doc = call.doc
    identity = document_identity(doc.writer.db_path, doc.name)
    if identity is None:
        log.warning("graph: %s: no AGS or publication date -- %d tuple(s) "
                    "not written", doc.name,
                    sum(len(rows) for rows in doc.admitted.values()))
        return None
    return facts_of(identity)


def _quantity_listed(call: Call) -> Optional[str]:
    quantity = call.row.get("quantity")
    if quantity in QUANTITIES:
        return None
    return f"not_a_class:{quantity or call.row.get('quantity_raw') or '?'}"


def _part_known(call: Call) -> Optional[str]:
    table = call.doc.writer.drawing.box[call.settings.get("box", "part")] \
        .get("table") or {}
    scenario = call.row.get("scenario")
    if scenario in table:
        return None
    return "scenario_unread" if not scenario else f"scenario:{scenario}"


def _scope_listed(call: Call) -> Optional[str]:
    scope = call.row.get("spatial_scope")
    if scope is not None and scope not in (call.settings.get("entries")
                                           or ()):
        return "spatial_scope"
    return None


def _sub_area_named(call: Call) -> Optional[str]:
    if call.row.get("spatial_scope") == "sub_area" \
            and not (call.row.get("spatial_scope_raw") or "").strip():
        return "sub_area_unnamed"
    return None


def _year_read(call: Call) -> Optional[str]:
    return None if isinstance(call.row.get("year"), int) else "year"


def _unit_listed(call: Call) -> Optional[str]:
    if call.row.get("value_target") is None:
        return f"unit_unlisted:{call.row.get('unit_raw') or '?'}"
    return None


def _unit_in_ontology(call: Call) -> Optional[str]:
    if unit_of(call.row) is None:
        return f"unit_not_in_ontology:{target_of(call.row)}"
    return None


def _aggregation_listed(call: Call) -> Optional[str]:
    aggregation = call.row.get("aggregation")
    if aggregation and aggregation not in AGGREGATIONS:
        return f"aggregation:{aggregation}"
    return None


def _schema_admits(call: Call) -> Optional[str]:
    drawing = call.doc.writer.drawing
    part = call.settings.get("part", "part")
    why = strict_refusal(call.row, drawing.box[part].get("table") or {},
                         totals(drawing.raw, call.settings.get("box",
                                                               "value")))
    return f"mhpkg:{why}" if why else None


def _identity(call: Call) -> str:
    """mint_slice.py's coordinate list; absent coordinates are empty
    segments so the arity never varies. A carrier or sector names the node
    only where it gets an edge; the area only for a sub-area, where it is
    the identity; the technology only where one was read, so every value
    without one keeps the IRI it had before the axis existed; *label* only
    for a node split off by its wording."""
    doc, row = call.doc, call.row
    total = totals(doc.writer.drawing.raw, call.settings.get("box", "value"))
    part = doc.address_of_answer(call.settings.get("part", "part"),
                                 row["scenario"])
    area = (doc.fold(row.get("spatial_scope_raw") or "")
            if row.get("spatial_scope") == "sub_area" else "")
    carrier = written(row, "carrier", total)
    sector = written(row, "sector", total)
    technology = row.get("technology")
    coordinates = "|".join([
        part,
        f"{OEO}{row['quantity']}",
        f"{OEO}{carrier}" if is_class(carrier) else "",
        f"{OEO}{sector}" if is_class(sector) else "",
        str(row["year"]),
        f"{OEO}{row['aggregation']}" if row.get("aggregation") else "",
        area,
    ] + ([f"{OEO}{technology}"] if is_class(technology) else [])
      + ([call.label] if call.label else []))
    return doc.mint("value", "value", coordinates)


def _value_class(call: Call) -> str:
    row = call.node.row
    typed = qualified(row[call.settings.get("coordinate", "quantity")])
    if not call.doc.strict:
        return typed
    part = call.doc.writer.drawing.box[call.settings.get("part", "part")]
    schema = schema_class_of(row, part.get("table") or {})
    if schema and SHAPE.cls(schema) != typed:
        # A CO2-equivalent value IS a greenhouse gas emission value; a shape
        # without a reasoner only sees the class written.
        typed += f", {SHAPE.cls(schema)}"
    return typed


def _unit(call: Call) -> list:
    unit = unit_of(call.row)
    if unit is None:
        return []
    return [(qualified(unit), expand(qualified(unit)))]


def _passage(call: Call) -> list:
    node = call.node
    prose = call.settings.get("prose") or {}
    return evidence_comment(node.row, call.doc.name, prose,
                            call.settings.get("join") or " · ",
                            transcribed=call.doc.transcribed,
                            **(node.data.get("marks") or {}))


def _bodies(call: Call) -> dict:
    doc, row = call.doc, call.node.row
    said = call.settings
    total = totals(doc.writer.drawing.raw, said.get("box", "value"))
    whole = (doc.nodes.get(said.get("whole", "municipality")) or [None])[0]
    area = whole.iri if whole else None
    if row.get("spatial_scope") == "sub_area":
        node = doc.node_of(said.get("area", "area"),
                           doc.fold(row["spatial_scope_raw"]))
        area = node.iri if node else area
    found = {"quantity": _class_iri(row.get("quantity")),
             "carrier": _class_iri(written(row, "carrier", total)),
             "sector": _class_iri(written(row, "sector", total)),
             "technology": _class_iri(row.get("technology")),
             "aggregation": _class_iri(row.get("aggregation")),
             "scenario": doc.address_of_answer(said.get("part", "part"),
                                               row["scenario"]),
             "spatial_scope": area}
    return {axis: iri for axis, iri in found.items() if iri}


_CONDITION = ("a reading", "a reason")
BRICKS = (
    Brick("plan_register", "facts",
          "Looks the plan up in the register: its AGS, its publication "
          "date and its municipality ({ags}, {published}, {year}, "
          "{place}); a plan without AGS or date is not written.",
          "a document", "facts", _register),
    Brick("quantity_listed", "condition",
          "Takes a number only where its class is one of the classes the "
          "graph takes (no out: answer).", *_CONDITION, _quantity_listed),
    Brick("part_known", "condition",
          "Takes a number only where its scenario is an answer of the table "
          "of plan parts.", *_CONDITION, _part_known,
          (Setting("box", "text", "the box of the plan parts", "part"),)),
    Brick("scope_listed", "condition",
          "Takes a number only where its area, where one was read, is one "
          "of the entries.", *_CONDITION, _scope_listed,
          (Setting("entries", "texts", "the areas the graph takes"),)),
    Brick("sub_area_named", "condition",
          "Takes a number of a sub-area only where the plan names the "
          "sub-area.", *_CONDITION, _sub_area_named),
    Brick("year_read", "condition",
          "Takes a number only where its year was read.", *_CONDITION,
          _year_read),
    Brick("unit_listed", "condition",
          "Takes a number only where its unit is listed and it was "
          "converted.", *_CONDITION, _unit_listed),
    Brick("unit_in_ontology", "condition",
          "Takes a number only where the unit it was converted onto is an "
          "ontology term.", *_CONDITION, _unit_in_ontology),
    Brick("aggregation_listed", "condition",
          "Takes a number only where its aggregation, where one was read, "
          "is listed.", *_CONDITION, _aggregation_listed),
    Brick("schema_admits", "condition",
          "Takes a number only where the MHPKG schema's shapes take it: a "
          "value class its part holds, every required slot, every answer "
          "from the schema's closed lists.", *_CONDITION, _schema_admits,
          (Setting("part", "text", "the box of the plan parts", "part"),
           Setting("box", "text", "the box of the numbers", "value"))),
    Brick("value_identity", "address",
          "Makes a number's address from the IRI policy's dimensions: plan "
          "part, class, carrier, sector, year, aggregation, sub-area and "
          "technology, and the plan's words where they split it.",
          "a reading", "an address", _identity,
          (Setting("part", "text", "the box of the plan parts", "part"),
           Setting("box", "text", "the box of the numbers", "value"))),
    Brick("value_class", "class",
          "Writes a number as the class its quantity was read as, and in "
          "the strict graph also as the schema's value class above it.",
          "a number", "classes", _value_class,
          (Setting("part", "text", "the box of the plan parts", "part"),
           Setting("coordinate", "text", "the dimension whose answer is "
                   "the class", "quantity"))),
    Brick("value_unit", "object",
          "Writes the unit the number was converted onto.", "a number",
          "a unit", _unit, writes="key:unit_target"),
    Brick("value_passage", "evidence",
          "Writes above a number its dimensions in English, the passage, "
          "the page, how it was aggregated or computed and its trust "
          "level.", "a number", "comment lines", _passage,
          (Setting("prose", "prose", "the words of the trust line"),
           Setting("join", "text", "what joins its pieces", " · "))),
    Brick("value_bodies", "claims",
          "Records for the provenance file the node or class each "
          "dimension of a number became.", "a number", "dimensions",
          _bodies,
          (Setting("part", "text", "the box of the plan parts", "part"),
           Setting("area", "text", "the box of the sub-areas", "area"),
           Setting("whole", "text", "the box of the municipality",
                   "municipality"),
           Setting("box", "text", "the box of the numbers", "value"))),
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
