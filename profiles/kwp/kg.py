"""
kg.py: Serializes harvested tuples into MHPKG Turtle.

The IRI policy is rebuilt from the schema repo's mint_slice.py and must stay
a pure function of the data: two runs over the same plan mint byte-identical
IRIs (tested against their published reference UUIDs). One deliberate
deviation: the value coordinates include the sector, because our tables carry
several sectors per carrier/year and the published coordinate list would
collide them into one node, which was flagged to the schema side.

Serialized is what the graph can hold: a value whose scenario names one of
the three plan parts of PARTS, whose scope is the municipality, whose
indicator label is accepted and whose year is read. Everything else stays in
the JSONL harvest and is counted here, not lost.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path
from typing import Optional

from docpipe.extraction.fields import DERIVED
from docpipe.extraction.spec import kg_name, load as load_spec
from docpipe.extraction.trust import check_prose, render, trust

log = logging.getLogger(__name__)

BASE = "https://openenergyplatform.org/id/mhpkg/"
OEO = "https://openenergyplatform.org/ontology/oeo/"
NS_MHPKG = uuid.uuid5(uuid.NAMESPACE_URL, BASE)

# Up here because every identifier below is qualified against it as it is
# read, and a prefix this header does not bind writes Turtle nobody can load.
PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix obo:   <http://purl.obolibrary.org/obo/> .
@prefix mhpo:  <https://purl.org/mhpo/ontology/> .
@prefix oeo:   <https://openenergyplatform.org/ontology/oeo/> .
"""
# The same header as a dict, so a qualified name can be expanded to the IRI
# the graph holds it under. Parsed out of PREFIXES rather than typed twice.
PREFIX_IRI = dict(re.findall(r"@prefix\s+(\w+):\s+<([^>]+)>", PREFIXES))


def expand(name: str) -> str:
    """`mhpo:MHPO_00020007` -> the full IRI, from the header this graph writes.

    Two of the three plan parts are mhpo: and one is oeo:, so a query that
    assumed one namespace would bind IRIs no graph holds and return nothing,
    silently. An unbound prefix raises rather than defaults.
    """
    prefix, _, local = str(name).partition(":")
    if not local or prefix not in PREFIX_IRI:
        raise KeyError(f"{name!r} is bound to no prefix of PREFIXES")
    return PREFIX_IRI[prefix] + local

# Nine classes the plans name in their carrier column are NOT under
# `energy carrier` (OEO_00020039) in OEO -- district heating is a grid-bound
# heat transfer, electrical energy sits under energy and commodity, solar
# thermal energy under thermal energy, and the ambient heat sources under
# thermal energy too. They used to lose their carrier edge, because
# `covers energy carrier` ranges over energy carrier and asserting them would
# have contradicted the TBox. That predicate is gone: its DOMAIN was
# `OEO_00020011` study, an occurrent, and every value node is a continuant,
# which made the whole graph unsatisfiable. The edge is `is about`
# (IAO_0000136) now, it declares no range, and the nine keep it.
#
# WHICH nine is still the spec's to declare (`kg.outside_root` on the carrier
# axis) and the pinned closure's to confirm: profiles/kwp/vocabulary.py
# refuses a carrier that is neither under the root nor declared, so a tenth
# cannot be added here by forgetting to mention it. The count stays in the
# log as the argument for the carrier axioms the ontology side is adding.
LEGAL = r"(gmbh\s*&\s*co\.?\s*kg|gmbh|mbh|ag|kg|ohg|e\.?\s*v\.?|gbr|se|ug)"

_SPEC = json.loads(
    Path(__file__).with_name("extraction_spec.json").read_text(encoding="utf-8"))
# The target quantity is per OEO class, not per parameter: which class a
# value is gets decided by the model on the `quantity` axis, and the unit
# hangs off the class.
# The classes the graph takes. The remaining entries of the list start with
# `out:` and are deliberately choosable non-classes: a cumulative sum, an
# avoided or captured amount, a potential. They stand in the selection so
# the model can CHOOSE them, instead of reaching for the nearest real class.
NOT_IN_GRAPH = "out:"


def is_class(value) -> bool:
    """True for a real OEO class, false for every deliberate non-class.

    The axes hold entries that say what a row IS when no class fits — a sum,
    a residual, a sector the source calls unknown. They are answers, not
    classes, and writing one as `oeo:out:total` mints an IRI that does not
    exist. Checked by shape rather than by prefix so a new entry cannot slip
    past by being spelled differently.
    """
    return bool(_OEO_CLASS.fullmatch(str(value or "")))


_OEO_CLASS = re.compile(r"OEO_\d+")
UNIT_TARGET = {uri: par["unit_target"]
               for par in _SPEC["parameters"]
               if par.get("unit_target")
               for uri in par["axes"]["quantity"]["vocabulary"]
               if not uri.startswith(NOT_IN_GRAPH)}
# How a value is aggregated over time or space is chosen by the model from
# the five classes OEO carries under `aggregation type`. It used to always
# say `integral` here, so a peak load was asserted as a year's sum.
AGGREGATIONS = {uri for par in _SPEC["parameters"]
                if "aggregation" in par.get("axes", {})
                for uri in par["axes"]["aggregation"]["vocabulary"]}
def _predicate(name: str) -> str:
    """The predicate the spec's `kg` block gives this axis, qualified.

    Written down once. The predicate used to stand as a literal here and be
    described a second time wherever the graph was documented, and a change
    in one place left the other describing a graph nobody was writing. The
    JSON schema publishes the same block, so what a reader is told and what
    is emitted are one string.

    Qualified, because the prefix was the half that stayed behind: the
    identifier came from the spec and `oeo:` from an f-string here, and this
    graph writes five namespaces.
    """
    for par in _SPEC["parameters"]:
        axis = (par.get("axes") or {}).get(name) or {}
        block = axis.get("kg") or {}
        if block.get("role") == "edge" and block.get("predicate"):
            return kg_name(block, PREFIXES)
    raise KeyError(f"no kg edge predicate for axis {name!r} in the spec")


def _value_predicate(key: str) -> str:
    """The predicate carrying a value's number or its unit, qualified."""
    for par in _SPEC["parameters"]:
        block = (par.get("kg") or {}).get(key) or {}
        if block.get("predicate"):
            return kg_name(block, PREFIXES)
    raise KeyError(f"no kg {key} predicate in the spec")


# Which prefix an identifier belongs to, by its family. A class is written as
# a bare id in the spec -- one spelling in both profiles -- so the prefix is
# recovered here rather than repeated beside every one of them. Unknown
# family is an error and not a default: defaulting to oeo: would mint
# oeo:UO_0000111, an IRI that does not exist, and say nothing.
_NAMESPACE = {"OEO_": "oeo", "MHPO_": "mhpo", "BFO_": "obo"}
_IDENTIFIER = re.compile(r"[A-Za-z]+_[0-9]+")


def qualified(identifier: str) -> str:
    """A bare ontology id as this graph writes it."""
    if not _IDENTIFIER.fullmatch(str(identifier)):
        raise KeyError(f"{identifier!r} is no bare identifier -- a class is "
                       f"an id like OEO_00030022, and a family test alone "
                       f"would qualify a glossed one silently")
    for family, prefix in _NAMESPACE.items():
        if identifier.startswith(family):
            return f"{prefix}:{identifier}"
    raise KeyError(f"no prefix is bound for the family of {identifier!r}")


def _parameter(uri: str) -> dict:
    for par in _SPEC["parameters"]:
        if par["uri"] == uri:
            return par
    raise KeyError(f"no parameter {uri!r} in the spec")


def _class(uri: str) -> str:
    """The class of the node this parameter mints, qualified."""
    block = (_parameter(uri).get("kg") or {})
    if "class" not in block:
        raise KeyError(f"parameter {uri!r} mints no node of its own")
    return qualified(block["class"])


def _edge_from_plan(uri: str) -> str:
    """The predicate hanging this parameter's node off the plan."""
    block = (_parameter(uri).get("kg") or {})
    if "edge_from_plan" not in block:
        raise KeyError(f"parameter {uri!r} hangs off no plan")
    return kg_name(block["edge_from_plan"], PREFIXES)


def _parent(axis: str) -> dict:
    for par in _SPEC["parameters"]:
        block = ((par.get("axes") or {}).get(axis) or {}).get("kg") or {}
        if block.get("role") == "parent":
            return block
    raise KeyError(f"axis {axis!r} names no parent node in the spec")


def _parent_class(axis: str, key: str) -> str:
    """The bare class one answer of a parent axis puts on its container."""
    entry = (_parent(axis).get("map") or {}).get(key)
    if not isinstance(entry, dict) or "class" not in entry:
        raise KeyError(f"{axis}={key!r} names no class, so it mints no node")
    return entry["class"]


def _parent_link(axis: str, key: str) -> str:
    """The predicate hanging one answer's node off the node above it."""
    entry = (_parent(axis).get("map") or {}).get(key)
    if not isinstance(entry, dict) or "linked_by" not in entry:
        raise KeyError(f"{axis}={key!r} hangs off nothing")
    return kg_name(entry["linked_by"], PREFIXES)


def _linked_by(axis: str) -> str:
    """The predicate hanging every container of this axis off the plan."""
    block = _parent(axis)
    if "linked_by" not in block:
        raise KeyError(f"axis {axis!r} says nothing about its edge upward")
    return kg_name(block["linked_by"], PREFIXES)


P_NUMBER = _value_predicate("number")           # oeo: has number
P_UNIT = _value_predicate("unit")               # oeo: has unit
# All three are `obo:IAO_0000136 is about`: see the note at the top. The year
# points at a node, the other two at a class.
P_CARRIER = _predicate("carrier")
P_SECTOR = _predicate("sector")
P_YEAR = _predicate("year")
P_AGGREGATION = _predicate("aggregation")       # oeo: has aggregation type

# The spec as the extraction stage loads it. The answer app's graph route
# reads its lists off it (`docpipe.inference.kg_route`).
SPEC = load_spec(_SPEC)

# Which part of a heat plan a value hangs under, by the scenario it belongs
# to. The law names three of them and MHPO asserts the has-part edges for
# them (mhpo-edit.owl L123-125), so this is a table and not a judgement.
#
# Only the target scenario was ever written. Everything else the harvest read
# was collected, verified and then dropped at the gate: measured on Kassel,
# 45 tuples for the scenario alone, 25 of them a stock take that the plan
# states as its own starting point. The Waermeplanungsgesetz asks for the
# inventory in §15 and the graph had no node for it.
# The class is ontology and comes from the spec. The path segment mints node
# identity (`mint`, below) and the German word is what a reader sees, and
# neither is a graph identifier -- moving them into the file that is free to
# edit would make an IRI free to change, which it is not.
_PART_MINT = {
    "status_quo": ("inventory", "Bestandsanalyse"),
    "trend": ("referencescenario", "Trendszenario"),
    "target": ("targetscenario", "Zielszenario"),
}
PARTS = {key: (qualified(_parent_class("scenario", key)), segment, label)
         for key, (segment, label) in _PART_MINT.items()}

def _outside_root() -> dict:
    """The carrier classes OEO does not place under `energy carrier`.

    Declared in the spec's kg block and read from there, not listed twice.
    The plans write these in the carrier column constantly -- district heat,
    electricity, solar thermal, the ambient heat sources -- and offering them
    at all is the point: without the classes the model mapped 36 of them onto
    solar thermal energy, which is a wrong triple rather than a missing one.
    """
    out: dict = {}
    for par in _SPEC["parameters"]:
        block = ((par.get("axes") or {}).get("carrier") or {}).get("kg") or {}
        out.update(block.get("outside_root") or {})
    return out


def _object_class(axis: str) -> str:
    """The class of the node an axis' edge points at, when it mints one."""
    for par in _SPEC["parameters"]:
        block = ((par.get("axes") or {}).get(axis) or {}).get("kg") or {}
        if block.get("object_class"):
            return qualified(block["object_class"])
    raise KeyError(f"axis {axis!r} names no class for the node it points at")


CARRIER_OUTSIDE_ROOT = _outside_root()
CLS_YEAR = _object_class("year")

ORGANISATION = "planning_organisation"
CLS_ORGANISATION = _class(ORGANISATION)                    # oeo: organisation
CLS_PLAN_AREA = qualified(_parent_class("spatial_scope", "sub_area"))
P_ORGANISATION = _edge_from_plan(ORGANISATION)             # oeo: has organisation
P_PART_OF = _parent_link("spatial_scope", "sub_area")      # obo: part of
P_HAS_PART = _linked_by("scenario")                        # obo: has part

# Behind no harvested value, so behind no parameter, so not in the spec: the
# plan node and the municipality node exist for every plan whatever the model
# answers, the publication date is a column of Documents and not a reading,
# and the hop from a container down to a value has no key in the kg grammar.
CLS_HEATPLAN = "mhpo:MHPO_00020003"
CLS_MUNICIPALITY = "mhpo:MHPO_00020017"
P_PUBLICATION_DATE = "oeo:OEO_00390096"
P_HAS_QUANTITY_VALUE = "oeo:OEO_00140002"


def _bare(name: str) -> str:
    """The identifier out of a qualified one, for the table below."""
    return str(name).split(":")[-1]


# Every triple shape this serializer writes that no `kg` block carries, so
# that `ontology.edge_problems` can hold ALL of them to the pinned ontology
# and not most of them. Built from the constants above rather than typed out
# again, and held against the rendered Turtle by a test, so it can drift from
# neither. The check this feeds is not academic: three edges named a domain
# (`study`, an occurrent) that every value node is disjoint from, so the
# graph asserted something no reasoner can satisfy, and every check we had
# passed it.
EDGES = tuple(
    [{"where": "kg.py plan", "subject": _bare(CLS_HEATPLAN),
      "predicate": _bare(P_PUBLICATION_DATE), "datatype": "xsd:date"},
     {"where": "kg.py plan", "subject": _bare(CLS_HEATPLAN),
      "predicate": _bare(P_ORGANISATION), "object": _bare(CLS_ORGANISATION)},
     {"where": "kg.py area", "subject": _bare(CLS_PLAN_AREA),
      "predicate": _bare(P_PART_OF), "object": _bare(CLS_MUNICIPALITY)}]
    + [{"where": "kg.py plan", "subject": _bare(CLS_HEATPLAN),
        "predicate": _bare(P_HAS_PART), "object": _bare(cls)}
       for cls, _segment, _label in PARTS.values()]
    + [{"where": "kg.py part", "subject": _bare(cls),
        "predicate": _bare(P_HAS_QUANTITY_VALUE), "object": quantity}
       for cls, _segment, _label in PARTS.values()
       for quantity in sorted(UNIT_TARGET)]
)


def year_iri(year) -> str:
    """The node a value points at for its year.

    One node per calendar year for the whole graph, keyed by the year itself
    rather than minted from a uuid: two plans naming 2030 mean the same 2030,
    and a year is the one coordinate with no document in it.
    """
    return f"{BASE}year/{int(year)}"


def ns(collection: str) -> uuid.UUID:
    return uuid.uuid5(NS_MHPKG, collection)


def normalise(label: str) -> str:
    """The umlaut rule from the policy, applied in order."""
    s = unicodedata.normalize("NFC", label)
    s = s.casefold()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.U)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(rf"\s+{LEGAL}$", "", s)
    return s.strip()


def display_name(label: str) -> str:
    """The name as the graph shows it: the document's own spelling, minus the
    legal form. `normalise` decides identity and casefolds for that; a label a
    reader sees must keep its capitals, and kassel_valid.ttl shows the
    stripped form."""
    s = re.sub(r"\s+", " ", str(label)).strip()
    return re.sub(rf"[\s,]+{LEGAL}\.?$", "", s, flags=re.I).strip(" ,")


def mint(collection: str, name: str) -> str:
    """Tier 3: UUIDv5 over the identifying name. Never v4 — v4 is random."""
    return f"{BASE}{collection}/{uuid.uuid5(ns(collection), name)}"


def _iso_date(raw) -> str:
    """`published` as the IRI policy spells it: YYYY-MM-DD.

    Ingest writes it as YYYYMMDD (source.py, strftime("%Y%m%d")), the same way
    the corpus writes it into file names. mint_slice.py and therefore every
    minted IRI speak the dashed form. One place converts, and it takes both so
    that a corpus written either way serializes.

    Without this the serializer produced an empty graph for the whole corpus
    while its tests passed: the fixture wrote the dashed form the DB never has.
    """
    text = str(raw or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def _document_identity(db_path: Path, name: str):
    """(ags, published, municipality name, transcribed page count) or None."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT id, published FROM Documents "
            "WHERE filename IN (?, ?)", (f"{name}.pdf", name)).fetchone()
        if row is None:
            return None
        document_id, published = row
        try:
            # How many of this plan's pages a MODEL read rather than the PDF.
            # Eleven plans of the corpus have no text layer at all, and their
            # section text is itself a reading -- a value from one of them
            # cannot be an A no matter how local its passages are. NULL where
            # nobody looked, which is not the same as zero.
            transcribed = conn.execute(
                "SELECT page_text_transcribed FROM Documents WHERE id = ?",
                (document_id,)).fetchone()[0]
        except sqlite3.OperationalError:      # a database predating WP11
            transcribed = None
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
    return ags.zfill(8), published, (meta[1] if meta else None), transcribed


def plan_iri(ags: str, published: str) -> str:
    """Tier 2: the plan's register key and its full publication date."""
    return f"{BASE}heatplan/AGS_{ags}_{published}"


def heatplan_iri(db_path: Path, name: str) -> Optional[str]:
    """The plan node the serializer mints for this document, or None.

    One minting site for the graph and for whoever asks it. The app was one
    f-string away from building its own, and `_iso_date` is exactly where a
    second copy diverges: ingest stores YYYYMMDD, the policy wants
    YYYY-MM-DD, and that mismatch once produced an empty graph with every
    test green.
    """
    identity = _document_identity(db_path, name)
    if identity is None:
        return None
    ags, published, _municipality, _transcribed = identity
    return plan_iri(ags, published)


def _value_iri(heatplan: str, row: dict) -> str:
    # mint_slice.py's coordinate list plus the sector and the sub-area (see
    # module docstring); absent coordinates are empty segments so the arity
    # never varies. The area has to be in here: one plan carries four separate
    # gas tables, one per heat-network area, and without it they collide onto
    # one node and the conflict guard drops all four.
    # The area names the node only where it IS the identity. For a sub-area
    # it is: one plan carries four separate gas tables, one per heat-network
    # area, and without the name they collide onto one node and the conflict
    # guard drops all four. For the whole plan area it is not, and putting it
    # in there splits one fact into as many nodes as the document has words
    # for the place. Measured over 20 plans: Bad Segeberg states its 2,272 t
    # of 2040 on pages 71, 72 and 73 as "Waermesektor", "Projektgebiet" and
    # "Stadtgebiet", and became three indistinguishable nodes. 129 of 1,294
    # nodes were repeats of that shape.
    area = (normalise(row.get("spatial_scope_raw") or "")
            if row.get("spatial_scope") == "sub_area" else "")
    coordinates = "|".join([
        heatplan,
        f"{OEO}{row['quantity']}",
        f"{OEO}{row['carrier']}" if row.get("carrier") else "",
        f"{OEO}{row['sector']}" if row.get("sector") else "",
        str(row["year"]),
        f"{OEO}{row['aggregation']}",
        area,
    ])
    return mint("value", coordinates)


# The words of the trust line; the marks and their order are the core's
# (docpipe.extraction.trust.MARKS). English, the project's own language: the
# corpus the graph is read from is German, but German stays only in what the
# model reads or writes, and a Turtle comment is neither.
TRUST_PROSE = check_prose({
    "level": "Trust: {level}",
    "image_origin": "from an image",
    "image_origin_named": "from an image ({image})",
    "corroborated": "confirmed by a second reading",
    "reasons": "{reasons}",
    "review": "review recommended",
}, "profiles/kwp/kg.py TRUST_PROSE")
TRUST_JOIN = " · "


def _ttl_comment(text) -> str:
    """One Turtle comment line, flattened so a quote cannot break the file."""
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    return "# " + flat[:400]


# Short English labels for the two coordinates that mint no OEO class of
# their own -- the scenario part and the whole-municipality scope -- and for
# an axis' `out:` entries, which are deliberate non-classes and so hold no
# vocabulary.json label either. The spec's own label for each of these is
# worded for the model's prompt and stays German on purpose (`extraction_spec
# .json`'s own `label`); this is the short table for the one place a reader
# of the GRAPH sees them.
SCENARIO_LABEL_EN = {"status_quo": "baseline inventory",
                     "trend": "trend scenario", "target": "target scenario"}
OUT_LABEL_EN = {
    "out:potential": "potential", "out:generation": "generation/supply",
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
    """A coordinate's value in English: the pinned vocabulary's own label for
    a real OEO class, the short label above for a deliberate non-class, or
    the bare identifier when neither table holds it.

    Not `label_of`, below: that one gives a reader of the ANSWER APP the
    spec's own first spelling, German, because the corpus is German and so
    is that reader. This is for a Turtle comment, whose reader reads the
    project's other language.
    """
    if not uri:
        return ""
    if is_class(uri):
        from profiles.kwp import vocabulary
        term = vocabulary.load()["terms"].get(_bare(uri)) or {}
        return term.get("label") or _bare(uri)
    return OUT_LABEL_EN.get(uri, _bare(uri))


def evidence_comment(row: dict, document: str, *,
                     transcribed: bool = False,
                     conflict: bool = False) -> list:
    """Where this value was read, as comment lines above its node.

    The prototype's evidence: the wording the document used, the passage it
    was read in, and the page it stands on. A comment rather than triples
    because the shapes are sh:closed and an extra triple on a value node
    invalidates it.
    """
    # How much of this value the run can stand behind, in the one place a
    # reader of the graph looks. Every accepted tuple is verified, and that
    # is a floor and not a grade: the level adds what else is known, an
    # image origin, a repaired quote, a contested identity.
    verdict = trust(row, transcribed=transcribed, conflict=conflict)
    prov = row.get("provenance") or {}
    where = [f"{document}.pdf"]
    if prov.get("page"):
        where.append(f"page {prov['page']}")
    kind = {"section": "section", "table": "table",
            "figure": "figure"}.get(prov.get("owner_kind"))
    if kind:
        where.append(kind + (f' "{prov["title"]}"' if prov.get("title") else ""))
    # The row's own coordinates, in English: the class the model chose, not
    # the document's raw wording, which stays German because the plan does.
    # A named sub-area is the one exception -- its own name is the reading,
    # not a spec label, and it stays exactly as the plan spells it.
    scope = ("whole municipality" if row.get("spatial_scope") == "municipality"
             else (row.get("spatial_scope_raw") or "").strip() or "sub-area")
    what = [_english_label(row.get("quantity")),
           SCENARIO_LABEL_EN.get(row.get("scenario"), row.get("scenario") or ""),
           scope,
           _english_label(row.get("carrier")),
           _english_label(row.get("sector"))]
    lines = [_ttl_comment(" · ".join(x for x in what if x))] if any(what) else []
    if row.get("quote"):
        lines.append(_ttl_comment(f'"{row["quote"]}"'))
    lines.append(_ttl_comment(", ".join(where)))
    aggregation = row.get("aggregation")
    if aggregation:
        # How this coordinate was arrived at, in the one place a reader of the
        # graph looks. `derived` is not a weaker reading than `read`, it is a
        # different one: the spec decided it from the unit the value request
        # had already quoted, and saying so is the difference between a fact
        # and a default.
        raw = (row.get("aggregation_raw") or "").strip()
        if row.get("aggregation_state") == DERIVED:
            note = f"Aggregation: {aggregation}"
            lines.append(_ttl_comment(
                note + (f" (from the unit {raw})" if raw else "")))
        elif raw:
            lines.append(_ttl_comment(f'Aggregation: {aggregation} "{raw}"'))
    if row.get("compute"):
        # A value the sandbox computed carries the code and its inputs, so the
        # arithmetic is checkable without re-running anything.
        lines.append(_ttl_comment(f"computed: {row['compute']}"))
    if row.get("flags"):
        lines.append(_ttl_comment("Flags: " + ", ".join(row["flags"])))
    lines.append(_ttl_comment(render(verdict, TRUST_PROSE,
                                     join=TRUST_JOIN, row=row)))
    return lines


def make_serializer(db_path: Path):
    """(document name, accepted tuple rows) -> TTL string or None."""
    header_pending = [True]
    # (ags, published) -> document name. Value IRIs are pure functions of
    # these coordinates, so two documents claiming one identity would merge
    # their numbers onto shared nodes — e.g. a stale JSONL left behind by a
    # register-link rename. The first claimant wins, the rest are refused
    # whole, loudly.
    claimed: dict = {}

    def serializer(name: str, rows: list):
        skipped: dict = {}
        outside_root: dict = {}

        def skip(reason: str, n: int = 1) -> None:
            skipped[reason] = skipped.get(reason, 0) + n

        offices: dict = {}
        kept = []
        for row in rows:
            if row.get("parameter") == ORGANISATION:
                label = row.get("value")
                if isinstance(label, str) and normalise(label):
                    offices.setdefault(normalise(label), display_name(label))
                continue
            # Which OEO class this number is, the model chose from the class
            # list with the ontology's own definitions in front of it. What it
            # could not place keeps its wording and is counted, instead of
            # being guessed at from a table of German spellings.
            quantity = row.get("quantity")
            scope = row.get("spatial_scope")
            area = (row.get("spatial_scope_raw") or "").strip()
            if row.get("scenario") not in PARTS:
                # A scenario nobody read is not the same finding as one the
                # graph has no node for, and counting them together hid the
                # first: a row with no scenario at all is a coordinate the
                # sweep never closed, and it is the sweep that has to answer
                # for it.
                skip("scenario_unread" if not row.get("scenario")
                     else f"scenario:{row['scenario']}")
            elif scope not in ("municipality", "sub_area"):
                skip("spatial_scope")
            elif scope == "sub_area" and not area:
                # Two unnamed sub-areas are one node and one is silently lost.
                skip("sub_area_unnamed")
            elif not isinstance(row.get("year"), int):
                skip("year")
            elif quantity not in UNIT_TARGET:
                # The model chose one of the classes the graph does not take —
                # a potential, a cumulative sum, a captured amount. Counted by
                # what it chose, which is the useful thing to read.
                skip(f"not_a_class:{quantity or row.get('quantity_raw') or '?'}")
            elif not row.get("aggregation"):
                # No aggregation, no node. It used to become a year's sum by
                # default, which is a claim about the value that nothing in
                # the document made: a peak load written down as an annual
                # total is wrong in a way no reader can see. The two amount
                # parameters derive `integral` from the unit, so a miss there
                # is the row the derivation could not reach. `heat_load` asks
                # instead -- a watt is not integrated over a span -- so this
                # counter is dominated by power rows whose source never
                # worded the aggregation.
                skip("aggregation_missing")
            elif row["aggregation"] not in AGGREGATIONS:
                skip(f"aggregation:{row['aggregation']}")
            else:
                kept.append(row)
        if not kept:
            if skipped:
                log.info("kg: %s: nothing serializable (skipped %s)", name, skipped)
            return None

        identity = _document_identity(db_path, name)
        if identity is None:
            log.warning("kg: %s: no AGS or publication date — %d tuple(s) "
                        "not serialized", name, len(kept))
            return None
        ags, published, municipality, transcribed = identity
        owner = claimed.setdefault((ags, published), name)
        if owner != name:
            log.error("kg: %s claims AGS %s / %s already serialized for %s — "
                      "%d tuple(s) refused (stale duplicate harvest?)",
                      name, ags, published, owner, len(kept))
            return None
        heatplan = plan_iri(ags, published)
        part_iri = {key: f"{BASE}{segment}/AGS_{ags}_{published}"
                    for key, (_cls, segment, _label) in PARTS.items()}
        municipality_iri = f"{BASE}municipality/AGS_{ags}"
        place = municipality or f"AGS {ags}"

        values: dict = {}
        conflicted: set = set()
        for row in kept:
            iri = _value_iri(part_iri[row["scenario"]], row)
            if iri in conflicted:
                skip("conflict")
                continue
            other = values.get(iri)
            if other is None:
                values[iri] = row
            elif other["value_target"] != row["value_target"]:
                # Same coordinates, different magnitude: a human question,
                # not a coin toss. Drop both, loudly.
                #
                # BOTH, so the number is the number of tuples that left the
                # graph. Counting only the second claimant made every report
                # short by one per contested identity: measured over Kassel,
                # 217 counted where 317 tuples were lost across 100
                # identities, and every estimate built on that log line was
                # optimistic by the same 100.
                skip("conflict", 2)
                values.pop(iri)
                conflicted.add(iri)
            else:
                # The same number a second time, from another passage. One
                # node either way, so this is not a loss — but it is not
                # nothing, and a repeat absorbed in silence is
                # indistinguishable from a reading that never happened.
                skip("duplicate")
        if not values:
            log.info("kg: %s: nothing serializable (skipped %s)", name, skipped)
            return None
        if skipped:
            log.info("kg: %s: %d value(s) serialized, skipped %s",
                     name, len(values), dict(skipped))

        # The commissioned planning office, minted over the normalised name:
        # "Kassel Wärme Ingenieurbüro GmbH" and the same spelling without its
        # legal form mint one node, not two.
        office_iris = {mint("organisation", key): label
                       for key, label in offices.items()}
        areas = {normalise(r["spatial_scope_raw"]): r["spatial_scope_raw"].strip()
                 for r in values.values()
                 if r.get("spatial_scope") == "sub_area"
                 and (r.get("spatial_scope_raw") or "").strip()}
        # Which parts this plan really has. A node for a part with no
        # value in it would be an empty claim, and a has-part edge to it
        # a wrong one: the plan does not stop having an inventory because
        # we could not read one, but the graph must not say we read it.
        years: set = set()
        by_part: dict = {}
        for iri, row in values.items():
            by_part.setdefault(row["scenario"], {})[iri] = row
        part_refs = " ,\n        ".join(
            f"<{part_iri[key]}>" for key in PARTS if key in by_part)

        office_edge = ""
        if office_iris:
            refs = " ,\n        ".join(f"<{i}>" for i in office_iris)
            office_edge = f"\n    {P_ORGANISATION} {refs} ;"

        parts = []
        if header_pending[0]:
            header_pending[0] = False
            parts.append(PREFIXES)
        parts.append(f"""\
<{heatplan}>
    a {CLS_HEATPLAN} ;
    rdfs:label "Kommunale Wärmeplanung {place} {published[:4]}" ;
    {P_PUBLICATION_DATE} "{published}"^^xsd:date ;{office_edge}
    {P_HAS_PART} {part_refs} .
""")
        for key in PARTS:
            if key not in by_part:
                continue
            cls, _segment, label = PARTS[key]
            value_refs = " ,\n        ".join(
                f"<{iri}>" for iri in by_part[key])
            parts.append(f"""\
<{part_iri[key]}>
    a {cls} ;
    rdfs:label "{label} {place} {published[:4]}" ;
    {P_HAS_QUANTITY_VALUE} {value_refs} .
""")
        for iri, row in values.items():
            lines = evidence_comment(row, name,
                                     transcribed=bool(transcribed))
            lines += [f"<{iri}>",
                      f"    a oeo:{row['quantity']} ;",
                     f"    {P_NUMBER} \"{float(row['value_target'])!r}\"^^xsd:float ;",
                     f"    {P_UNIT} oeo:{UNIT_TARGET[row['quantity']]} ;"]
            carrier = row.get("carrier")
            if carrier and is_class(carrier):
                if carrier in CARRIER_OUTSIDE_ROOT:
                    # Counted, not dropped. `is about` declares no range, so
                    # the nine OEO does not call carriers keep this edge; the
                    # count is what argues for the axioms that would let them
                    # be called carriers.
                    label = CARRIER_OUTSIDE_ROOT[carrier]
                    outside_root[label] = outside_root.get(label, 0) + 1
                lines.append(f"    {P_CARRIER} oeo:{carrier} ;")
            if row.get("sector") and is_class(row["sector"]):
                lines.append(f"    {P_SECTOR} oeo:{row['sector']} ;")
            years.add(int(row["year"]))
            lines.append(f"    {P_YEAR} <{year_iri(row['year'])}> ;")
            lines.append(f"    {P_AGGREGATION} oeo:{row['aggregation']} .")
            parts.append("\n".join(lines) + "\n")
        if outside_root:
            log.info("kg: %s: %d value(s) keep a carrier OEO does not call a "
                     "carrier, serialized and counted: %s", name,
                     sum(outside_root.values()), dict(outside_root))
        for year in sorted(years):
            parts.append(f"<{year_iri(year)}>\n"
                         f"    a {CLS_YEAR} ;\n"
                         f"    rdfs:label \"{year}\" .\n")
        for iri, label in office_iris.items():
            parts.append(f"<{iri}>\n"
                         f"    a {CLS_ORGANISATION} ;\n"
                         f"    rdfs:label \"{label}\" .\n")
        # Sub-areas exist as nodes and are part of the municipality area. What
        # is missing is the edge from a VALUE to the area it holds for: MHPO
        # has `heat plan area` and BFO `part of`, and nothing that relates a
        # value or a plan to an area (TERM REQUEST 1 in their own schema). So
        # the area is in the value's identity and in its comment, and the
        # relation is the term request.
        for key, label in sorted(areas.items()):
            parts.append(f"<{mint('heatplanarea', f'{ags}|{key}')}>\n"
                         f"    a {CLS_PLAN_AREA} ;\n"
                         f"    rdfs:label \"{label}\" ;\n"
                         f"    {P_PART_OF} <{municipality_iri}> .\n")
        parts.append(f"""\
<{municipality_iri}>
    a {CLS_MUNICIPALITY} ;
    rdfs:label "Gemeindegebiet {place}" .
""")
        return "\n".join(parts)

    return serializer


# --- Asking the graph -------------------------------------------------------
#
# The coordinates a question can fix, in the order the spec asks them. Two
# real axes are deliberately absent. `spatial_scope` enters a value's identity,
# but the graph has no edge from a value to its area (TERM REQUEST 1 in the
# schema), so there is nothing to filter on: a sub-area value and the
# municipality's come back in one list. `aggregation` is returned rather than
# constrained, so a peak load and an annual total sit in one list with the
# label telling them apart.
COORDINATE_AXES = ("scenario", "quantity", "carrier", "sector", "year")

# The query, over the same constants the serializer writes with, so the two
# cannot drift. Carrier, sector and year all ride `is about`; the year is told
# apart by the class of the node it points at, and without that exclusion the
# year node comes back as a carrier. Measured: it does.
VALUE_QUERY = "\n".join(
    [f"PREFIX {prefix}: <{iri}>" for prefix, iri in PREFIX_IRI.items()]
    + [f"""
SELECT ?value ?quantity ?number ?unit ?year ?aggregation ?part ?partLabel
       (GROUP_CONCAT(DISTINCT STR(?about); separator=" ") AS ?abouts)
WHERE {{
  ?plan  {P_HAS_PART} ?part .
  ?part  a ?partClass ;
         rdfs:label ?partLabel ;
         {P_HAS_QUANTITY_VALUE} ?value .
  ?value a ?quantity ;
         {P_NUMBER} ?number ;
         {P_UNIT} ?unit ;
         {P_AGGREGATION} ?aggregation ;
         {P_YEAR} ?yearNode .
  ?yearNode a {CLS_YEAR} ;
            rdfs:label ?year .
  OPTIONAL {{ ?value {P_CARRIER} ?about .
             FILTER NOT EXISTS {{ ?about a {CLS_YEAR} }} }}
  FILTER (?plan = ?PLAN)
##CONSTRAINTS##
}}
GROUP BY ?value ?quantity ?number ?unit ?year ?aggregation ?part ?partLabel
ORDER BY ?year ?number"""])


def value_bindings(coordinates: dict) -> tuple:
    """(constraint lines for ##CONSTRAINTS##, {variable: (kind, value)}).

    An unbound axis adds no line, which is why the constraints are text and
    not initBindings alone. The kinds are plain strings ("iri", "literal") so
    this module stays rdflib-free; the core wraps them. Gates: a quantity the
    graph does not hold and any `out:` entry are dropped here, because
    `oeo:out:potential` is an IRI that does not exist.
    """
    lines, bindings = [], {}
    scenario = coordinates.get("scenario")
    if scenario in PARTS:
        lines.append("  FILTER (?partClass = ?PART)")
        bindings["PART"] = ("iri", expand(PARTS[scenario][0]))
    quantity = coordinates.get("quantity")
    if quantity in UNIT_TARGET:
        lines.append("  FILTER (?quantity = ?QUANTITY)")
        bindings["QUANTITY"] = ("iri", OEO + quantity)
    year = coordinates.get("year")
    if isinstance(year, int):
        # Untyped: the year node's label is written as a plain string.
        lines.append("  FILTER (?year = ?YEAR)")
        bindings["YEAR"] = ("literal", str(year))
    for axis, variable in (("carrier", "CARRIER"), ("sector", "SECTOR")):
        uri = coordinates.get(axis)
        if uri and is_class(uri):
            lines.append(f"  ?value {P_CARRIER} ?{variable} .")
            bindings[variable] = ("iri", OEO + uri)
    return "\n".join(lines), bindings


def _first_spelling(entry) -> Optional[str]:
    if isinstance(entry, dict):
        return entry.get("label") or next(iter(entry.get("spellings") or []), None)
    if isinstance(entry, (list, tuple)) and entry:
        return entry[0]
    return None


def label_of(identifier: str) -> str:
    """What a reader calls a class: the spec's first spelling for it, else
    the pinned vocabulary's label, else the identifier itself.

    Takes the full IRI the query returns, a qualified name or a bare id, so
    the display never carries a second table of German words.
    """
    text = str(identifier or "")
    bare = text[len(OEO):] if text.startswith(OEO) else _bare(text)
    for par in _SPEC["parameters"]:
        for axis in (par.get("axes") or {}).values():
            spelling = _first_spelling((axis.get("vocabulary") or {}).get(bare))
            if spelling:
                return spelling
    from profiles.kwp import vocabulary
    term = vocabulary.load()["terms"].get(bare) or {}
    return term.get("label") or bare

