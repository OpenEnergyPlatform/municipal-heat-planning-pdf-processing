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

log = logging.getLogger(__name__)

BASE = "https://openenergyplatform.org/id/mhpkg/"
OEO = "https://openenergyplatform.org/ontology/oeo/"
NS_MHPKG = uuid.uuid5(uuid.NAMESPACE_URL, BASE)
AGGREGATION_INTEGRAL = "OEO_00140070"
LEGAL = r"(gmbh\s*&\s*co\.?\s*kg|gmbh|mbh|ag|kg|ohg|e\.?\s*v\.?|gbr|se|ug)"

_SPEC = json.loads(
    Path(__file__).with_name("extraction_spec.json").read_text(encoding="utf-8"))
INDICATOR_MAPPING = _SPEC.get("indicator_mapping", {})
UNIT_TARGET = {p["uri"]: p["unit_target"] for p in _SPEC["parameters"]}

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


def mint(collection: str, name: str) -> str:
    """Tier 3: UUIDv5 over the identifying name. Never v4 — v4 is random."""
    return f"{BASE}{collection}/{uuid.uuid5(ns(collection), name)}"


def accepted_indicator(parameter_uri: str, label_raw) -> bool:
    """The D6 mapping table: unclear beats accept, no match is unclear."""
    rules = INDICATOR_MAPPING.get(parameter_uri)
    label = (label_raw or "").casefold()
    if not rules or not label:
        return False
    if any(u in label for u in rules.get("unclear", ())):
        return False
    return any(a in label for a in rules.get("accept", ()))


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
    published = str(published or "")[:10]
    if not ags.isdigit() or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        return None
    return ags.zfill(8), published, (meta[1] if meta else None)


def _value_iri(heatplan: str, row: dict) -> str:
    # mint_slice.py's coordinate list plus the sector (see module docstring);
    # absent coordinates are empty segments so the arity never varies.
    coordinates = "|".join([
        heatplan,
        f"{OEO}{row['parameter']}",
        f"{OEO}{row['carrier']}" if row.get("carrier") else "",
        f"{OEO}{row['sector']}" if row.get("sector") else "",
        str(row["year"]),
        f"{OEO}{AGGREGATION_INTEGRAL}",
    ])
    return mint("value", coordinates)


def make_serializer(db_path: Path):
    """(document name, accepted tuple rows) -> TTL string or None."""
    header_pending = [True]

    def serializer(name: str, rows: list):
        skipped: dict = {}

        def skip(reason: str) -> None:
            skipped[reason] = skipped.get(reason, 0) + 1

        kept = []
        for row in rows:
            if row.get("scenario") != "target":
                skip("scenario")
            elif row.get("spatial_scope") != "municipality":
                skip("spatial_scope")
            elif not isinstance(row.get("year"), int):
                skip("year")
            elif not accepted_indicator(row.get("parameter"),
                                        row.get("indicator_label_raw")):
                skip("indicator")
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

        parts = []
        if header_pending[0]:
            header_pending[0] = False
            parts.append(PREFIXES)
        parts.append(f"""\
<{heatplan}>
    a mhpo:MHPO_00020003 ;
    rdfs:label "Kommunale Wärmeplanung {place} {published[:4]}" ;
    oeo:OEO_00390096 "{published}"^^xsd:date ;
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
            lines = [f"<{iri}>",
                     f"    a oeo:{row['parameter']} ;",
                     f"    oeo:OEO_00140178 \"{float(row['value_target'])!r}\"^^xsd:float ;",
                     f"    oeo:OEO_00040010 oeo:{UNIT_TARGET[row['parameter']]} ;"]
            if row.get("carrier"):
                lines.append(f"    oeo:OEO_00000523 oeo:{row['carrier']} ;")
            if row.get("sector"):
                lines.append(f"    oeo:OEO_00000505 oeo:{row['sector']} ;")
            lines.append(f"    oeo:OEO_00020440 \"{row['year']}\"^^xsd:integer ;")
            lines.append(f"    oeo:OEO_00390023 oeo:{AGGREGATION_INTEGRAL} .")
            parts.append("\n".join(lines) + "\n")
        parts.append(f"""\
<{municipality_iri}>
    a mhpo:MHPO_00020017 ;
    rdfs:label "Gemeindegebiet {place}" .
""")
        return "\n".join(parts)

    return serializer
