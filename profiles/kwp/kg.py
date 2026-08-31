"""
kg.py – Harvested tuples to MHPKG Turtle (the target-scenario slice).

The IRI policy is rebuilt from the schema repo's mint_slice.py and must stay
a pure function of the data: two runs over the same plan mint byte-identical
IRIs (tested against their published reference UUIDs). One deliberate
deviation: the value coordinates include the sector, because our tables carry
several sectors per carrier/year and the published coordinate list would
collide them into one node — flagged to the schema side.

Serialized is what the target-scenario schema can hold today: scenario ==
"target", municipality scope, an accepted indicator label, a year. Everything
else stays in the JSONL harvest and is counted here, not lost.
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

log = logging.getLogger(__name__)

BASE = "https://openenergyplatform.org/id/mhpkg/"
OEO = "https://openenergyplatform.org/ontology/oeo/"
NS_MHPKG = uuid.uuid5(uuid.NAMESPACE_URL, BASE)
AGGREGATION_INTEGRAL = "OEO_00140070"

# `covers energy carrier` (OEO_00000523) has range `energy carrier`
# (OEO_00020039), checked in oeo-closure.owl. Three classes the plans name in
# their carrier column are NOT under it: district heating is a grid-bound heat
# transfer, electrical energy sits under energy and commodity, solar thermal
# energy under thermal energy. Asserting them as carriers would contradict the
# TBox, so those rows are counted out of the TTL instead of quietly widening a
# range. They stay in the JSONL harvest, and the count is the argument for the
# carrier axioms the ontology side is currently adding.
NOT_AN_ENERGY_CARRIER = {
    "OEO_00000132": "district heating",
    "OEO_00000139": "electrical energy",
    "OEO_00000388": "solar thermal energy",
    # Ambient and waste heat. The plans name these in the carrier column
    # constantly and OEO does not place them under `energy carrier` either,
    # so the value keeps its node and loses only the edge. Naming them at all
    # is the point: without the classes the model mapped 36 of these onto
    # solar thermal energy, which is a wrong triple rather than a missing one.
    "OEO_00000191": "geothermal energy",
    "OEO_00010114": "waste heat",
    "OEO_00310004": "industrial waste heat",
    "OEO_00000056": "ambient heat",
    "OEO_00140105": "waste water heat",
    "OEO_00140104": "surface water heat",
}
LEGAL = r"(gmbh\s*&\s*co\.?\s*kg|gmbh|mbh|ag|kg|ohg|e\.?\s*v\.?|gbr|se|ug)"

_SPEC = json.loads(
    Path(__file__).with_name("extraction_spec.json").read_text(encoding="utf-8"))
# Zielgroesse je OEO-Klasse, nicht je Parameter: welche Klasse ein Wert ist,
# entscheidet das Modell auf der Achse `quantity`, und die Einheit haengt an
# der Klasse.
# Die Klassen, die der Graph aufnimmt. Die uebrigen Eintraege der Liste
# beginnen mit `out:` und sind ausdruecklich waehlbare Nicht-Klassen: eine
# kumulierte Summe, eine vermiedene oder abgeschiedene Menge, ein Potenzial.
# Sie stehen in der Auswahl, damit das Modell sie WAEHLEN kann, statt die
# naechstbeste echte Klasse zu nehmen.
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
# Wie ein Wert ueber Zeit oder Raum zusammengefasst ist, waehlt das Modell aus
# den fuenf Klassen, die OEO unter `aggregation type` fuehrt. Frueher stand hier
# immer `integral`, also wurde eine Spitzenlast als Jahressumme behauptet.
AGGREGATIONS = {uri for par in _SPEC["parameters"]
                if "aggregation" in par.get("axes", {})
                for uri in par["axes"]["aggregation"]["vocabulary"]}
ORGANISATION = "planning_organisation"
CLS_ORGANISATION = "OEO_00030022"        # organisation
CLS_PLAN_AREA = "MHPO_00020018"          # heat plan area
P_ORGANISATION = "OEO_00000510"          # has organisation
P_PART_OF = "BFO_0000050"                # part of

PREFIXES = """\
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .
@prefix obo:   <http://purl.obolibrary.org/obo/> .
@prefix mhpo:  <https://purl.org/mhpo/ontology/> .
@prefix oeo:   <https://openenergyplatform.org/ontology/oeo/> .
"""


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
    """(ags 8-digit, published YYYY-MM-DD, municipality name) or None."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
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
        f"{OEO}{row.get('aggregation') or AGGREGATION_INTEGRAL}",
        area,
    ])
    return mint("value", coordinates)


def _ttl_comment(text) -> str:
    """One Turtle comment line, flattened so a quote cannot break the file."""
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    return "# " + flat[:400]


def evidence_comment(row: dict, document: str) -> list:
    """Where this value was read, as comment lines above its node.

    The prototype's evidence: the wording the document used, the passage it
    was read in, and the page it stands on. A comment rather than triples
    because the shapes are sh:closed and an extra triple on a value node
    invalidates it.
    """
    prov = row.get("provenance") or {}
    where = [f"{document}.pdf"]
    if prov.get("page"):
        where.append(f"Seite {prov['page']}")
    kind = {"section": "Abschnitt", "table": "Tabelle",
            "figure": "Abbildung"}.get(prov.get("owner_kind"))
    if kind:
        where.append(kind + (f" „{prov['title']}“" if prov.get("title") else ""))
    what = [row.get("quantity_raw") or "", row.get("scenario_raw") or "",
            row.get("spatial_scope_raw") or "", row.get("carrier_raw") or "",
            row.get("sector_raw") or ""]
    lines = [_ttl_comment(" · ".join(x for x in what if x))] if any(what) else []
    if row.get("quote"):
        lines.append(_ttl_comment(f"„{row['quote']}“"))
    lines.append(_ttl_comment(", ".join(where)))
    if row.get("compute"):
        # A value the sandbox computed carries the code and its inputs, so the
        # arithmetic is checkable without re-running anything.
        lines.append(_ttl_comment(f"berechnet: {row['compute']}"))
    if row.get("flags"):
        lines.append(_ttl_comment("Flags: " + ", ".join(row["flags"])))
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

        def skip(reason: str) -> None:
            skipped[reason] = skipped.get(reason, 0) + 1

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
            if row.get("scenario") != "target":
                skip("scenario")
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
            elif row.get("aggregation") and row["aggregation"] not in AGGREGATIONS:
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
        ags, published, municipality = identity
        owner = claimed.setdefault((ags, published), name)
        if owner != name:
            log.error("kg: %s claims AGS %s / %s already serialized for %s — "
                      "%d tuple(s) refused (stale duplicate harvest?)",
                      name, ags, published, owner, len(kept))
            return None
        heatplan = f"{BASE}heatplan/AGS_{ags}_{published}"
        scenario_iri = f"{BASE}targetscenario/AGS_{ags}_{published}"
        municipality_iri = f"{BASE}municipality/AGS_{ags}"
        place = municipality or f"AGS {ags}"

        values: dict = {}
        conflicted: set = set()
        for row in kept:
            iri = _value_iri(heatplan, row)
            if iri in conflicted:
                skip("conflict")
                continue
            other = values.get(iri)
            if other is None:
                values[iri] = row
            elif other["value_target"] != row["value_target"]:
                # Same coordinates, different magnitude: a human question,
                # not a coin toss. Drop both, loudly.
                skip("conflict")
                values.pop(iri)
                conflicted.add(iri)
        if not values:
            log.info("kg: %s: nothing serializable (skipped %s)", name, skipped)
            return None
        if skipped:
            log.info("kg: %s: %d value(s) serialized, skipped %s",
                     name, len(values), skipped)

        # Das beauftragte Planungsbuero, ueber den normalisierten Namen
        # gepraegt: "Kassel Wärme Ingenieurbüro GmbH" und dieselbe Schreibweise
        # ohne Rechtsform ergeben einen Knoten, nicht zwei.
        office_iris = {mint("organisation", key): label
                       for key, label in offices.items()}
        areas = {normalise(r["spatial_scope_raw"]): r["spatial_scope_raw"].strip()
                 for r in values.values()
                 if r.get("spatial_scope") == "sub_area"
                 and (r.get("spatial_scope_raw") or "").strip()}
        office_edge = ""
        if office_iris:
            refs = " ,\n        ".join(f"<{i}>" for i in office_iris)
            office_edge = f"\n    oeo:{P_ORGANISATION} {refs} ;"

        parts = []
        if header_pending[0]:
            header_pending[0] = False
            parts.append(PREFIXES)
        parts.append(f"""\
<{heatplan}>
    a mhpo:MHPO_00020003 ;
    rdfs:label "Kommunale Wärmeplanung {place} {published[:4]}" ;
    oeo:OEO_00390096 "{published}"^^xsd:date ;{office_edge}
    obo:BFO_0000051 <{scenario_iri}> .
""")
        value_refs = " ,\n        ".join(f"<{iri}>" for iri in values)
        parts.append(f"""\
<{scenario_iri}>
    a mhpo:MHPO_00020007 ;
    rdfs:label "Zielszenario {place} {published[:4]}" ;
    oeo:OEO_00140002 {value_refs} .
""")
        for iri, row in values.items():
            lines = evidence_comment(row, name)
            lines += [f"<{iri}>",
                      f"    a oeo:{row['quantity']} ;",
                     f"    oeo:OEO_00140178 \"{float(row['value_target'])!r}\"^^xsd:float ;",
                     f"    oeo:OEO_00040010 oeo:{UNIT_TARGET[row['quantity']]} ;"]
            carrier = row.get("carrier")
            if carrier and is_class(carrier):
                if carrier in NOT_AN_ENERGY_CARRIER:
                    # The value stands, the edge does not. Dropping the whole
                    # row over this cost 51 of 244 value nodes in the pilot,
                    # every one of them a properly evidenced consumption or
                    # emission with its year, unit, sector and aggregation.
                    # What is missing is one relation the TBox does not allow
                    # yet, and a value without its carrier is a smaller loss
                    # than no value at all.
                    skip(f"carrier_not_in_oeo:{NOT_AN_ENERGY_CARRIER[carrier]}")
                else:
                    lines.append(f"    oeo:OEO_00000523 oeo:{carrier} ;")
            if row.get("sector") and is_class(row["sector"]):
                lines.append(f"    oeo:OEO_00000505 oeo:{row['sector']} ;")
            lines.append(f"    oeo:OEO_00020440 \"{row['year']}\"^^xsd:integer ;")
            lines.append(f"    oeo:OEO_00390023 "
                         f"oeo:{row.get('aggregation') or AGGREGATION_INTEGRAL} .")
            parts.append("\n".join(lines) + "\n")
        for iri, label in office_iris.items():
            parts.append(f"<{iri}>\n"
                         f"    a oeo:{CLS_ORGANISATION} ;\n"
                         f"    rdfs:label \"{label}\" .\n")
        # Sub-areas exist as nodes and are part of the municipality area. What
        # is missing is the edge from a VALUE to the area it holds for: MHPO
        # has `heat plan area` and BFO `part of`, and nothing that relates a
        # value or a plan to an area (TERM REQUEST 1 in their own schema). So
        # the area is in the value's identity and in its comment, and the
        # relation is the term request.
        for key, label in sorted(areas.items()):
            parts.append(f"<{mint('heatplanarea', f'{ags}|{key}')}>\n"
                         f"    a mhpo:{CLS_PLAN_AREA} ;\n"
                         f"    rdfs:label \"{label}\" ;\n"
                         f"    obo:{P_PART_OF} <{municipality_iri}> .\n")
        parts.append(f"""\
<{municipality_iri}>
    a mhpo:MHPO_00020017 ;
    rdfs:label "Gemeindegebiet {place}" .
""")
        return "\n".join(parts)

    return serializer
