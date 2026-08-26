"""
kg.py – Harvested publication metadata to OEKG Turtle.

What the shapes ask of a scenario bundle, its study report and its scenario
factsheets — plus the evidence for every value.

That last part is PROVISIONAL. The shapes are `sh:closed true` today, which
would make an evidence triple invalidate the node; whether they stay closed
is being decided on the ontology side, and this is written as if they will
not. The whole point of reading metadata out of the PDF rather than taking
the crawl's copy is that each value can name the passage it came from, so a
graph that drops the passage gives up the reason it was built this way. One
evidence node per value, linked with `oekgprov:hasEvidence`; set
OEKG_EVIDENCE=0 to emit the bare shape-conformant graph instead.

Cardinality is enforced here rather than in the verifier, because the
verifier sees one claim at a time and `exactly one title` is a property of a
document's whole harvest. Where the shape says maxCount 1 and the harvest
offers several, the one the most sources agree on wins; the rest are counted,
not dropped silently.

The crawl's DocumentMeta (title, year, doi) is not the source here — it comes
with the crawl's licence. It is the cross-check: a disagreement between what
the PDF says and what the crawl said is logged, because one of the two is
wrong and neither should find that out in production.
"""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import unicodedata
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

# OPEN QUESTION for Mirjam and JH: the instance IRI base for the OEKG. The
# shapes only fix the ontology prefixes, not where individuals live. This is a
# placeholder that must be confirmed before anything is pushed to staging.
BASE = os.environ.get("OEKG_ID_BASE", "https://openenergyplatform.org/id/oekg/")
NS_OEKG = uuid.uuid5(uuid.NAMESPACE_URL, BASE)

# Classes the shapes require at the end of each path.
CLS_BUNDLE = "OEO_00020227"        # scenario bundle (StudyShape target)
CLS_REPORT = "OEO_00020012"        # study report (PublicationShape target)
CLS_AUTHOR = "OEO_00000064"        # author
CLS_ORGANISATION = "OEO_00030022"  # organisation
CLS_FUNDER = "OEO_00090001"        # funder
CLS_SCENARIO = "OEO_00000365"      # scenario factsheet (ScenarioShape target)
CLS_REGION = "OEO_00020032"        # study region

# Paths, from the shapes file.
P_UUID = "OEO_00390095"            # has uuid
P_AUTHOR = "OEO_00000506"          # has author
P_PUBDATE = "OEO_00390096"         # has publication date
P_DOI = "OEO_00390098"             # has doi
P_ORGANISATION = "OEO_00000510"    # has organisation
P_FUNDER = "OEO_00000509"          # has funding source
P_HAS_PART = "BFO_0000051"         # has part
P_SCENARIO_TYPE = "OEO_00390073"   # has scenario type
P_STUDY_REGION = "OEO_00020220"    # has study region
P_SCENARIO_YEAR = "OEO_00020440"   # has scenario year value

# Mirjam: "alle IAM scenarios bekommen erst mal die Annotation". JH notes it is
# not in the release nor in the shape's sh:in list yet, so a graph written
# today will fail that constraint until it is.
IAM_SCENARIO = "OEO_00020517"

# What the shapes allow at most once. Everything else may repeat.
SINGLE = ("publication_title", "publication_date", "publication_doi",
          "publication_abstract", "study_project_name", "study_acronym")
# Scenario-scope fields. Everything but the label carries a `scenario` axis
# naming, in the document's own words, which scenario it belongs to.
SCENARIO_FIELDS = ("scenario_abstract", "scenario_region", "scenario_year")
# What the shapes demand at least once (sh:minCount 1). A document missing one
# of these produces a node that will fail validation, so it is reported.
REQUIRED = ("publication_title", "publication_date", "publication_author")

PREFIXES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix dc:   <http://purl.org/dc/terms/> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .
@prefix oekgprov: <https://openenergyplatform.org/ontology/oekg/provenance/> .
"""

_LEGAL = r"(gmbh|mbh|ag|kg|ohg|e\.?\s*v\.?|gbr|se|ug|inc|ltd|llc)"
NL = "\n"


def normalise(label: str) -> str:
    """One spelling for a name, so two writings of it mint one IRI."""
    s = unicodedata.normalize("NFC", str(label)).casefold()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.U)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(rf"\s+{_LEGAL}$", "", s)
    return s.strip()


def ns(collection: str) -> uuid.UUID:
    return uuid.uuid5(NS_OEKG, collection)


def mint(collection: str, name: str) -> str:
    """UUIDv5 over the identifying name. Never v4 — v4 is random, and two runs
    over one document must mint the same IRI."""
    return f"{BASE}{collection}/{uuid.uuid5(ns(collection), normalise(name))}"


def uuid_of(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]


def literal(text: str) -> str:
    """A Turtle string literal. Abstracts run over several lines, so the long
    form is used whenever the text is not a single clean line."""
    s = str(text)
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    if "\n" in s or "\r" in s:
        return '"""' + escaped.replace("\r", "") + '"""'
    return f'"{escaped}"'


def _pick_one(rows: list) -> tuple:
    """(value, how many other spellings were offered) for a maxCount 1 field.

    The reading the most sources agree on wins. A tie goes to the one that
    could be located on its PDF page, then to the longer text: a truncated
    title is a common failure and the full one is never the shorter reading of
    the same passage.
    """
    by_value: dict = {}
    for row in rows:
        by_value.setdefault(row["value"], []).append(row)
    ranked = sorted(
        by_value.items(),
        key=lambda kv: (len(kv[1]),
                        any(r.get("provenance", {}).get("rects") for r in kv[1]),
                        len(kv[0])),
        reverse=True)
    return ranked[0][0], len(ranked) - 1


def _publication_date(year_text: str) -> str:
    """The shape asks for xsd:dateTime; a PDF gives a year.

    OPEN QUESTION for Mirjam: midnight on the first of January is a fact the
    document does not state. Either the shape wants xsd:gYear here, or the
    graph should carry the made-up part visibly.
    """
    digits = re.search(r"\d{4}", str(year_text))
    return f"{digits.group(0)}-01-01T00:00:00" if digits else ""


def _crosscheck(conn, name: str, chosen: dict) -> None:
    """Say it out loud when the PDF and the crawl disagree."""
    row = conn.execute(
        "SELECT m.title, m.year, m.doi FROM DocumentMeta m "
        "JOIN Documents d ON m.document = d.id "
        "WHERE d.filename LIKE ?", (f"{name}.%",)).fetchone()
    if row is None:
        return
    pairs = (("publication_title", row[0]), ("publication_date", row[1]),
             ("publication_doi", row[2]))
    for key, crawled in pairs:
        got = chosen.get(key)
        if not got or not crawled:
            continue
        if normalise(got) != normalise(crawled):
            log.warning("kg: %s: %s from the PDF is %r, the crawl says %r",
                        name, key, got, crawled)


# Provisional, see the module docstring: emitting the evidence assumes the
# shapes will not stay closed. Off gives a graph that validates today.
EVIDENCE = os.environ.get("OEKG_EVIDENCE", "1") != "0"


def _known_scenarios(conn, name: str) -> dict:
    """{normalised AR6 scenario name: name as the AR6 database writes it}."""
    rows = conn.execute(
        "SELECT s.name FROM Scenarios s "
        "JOIN DocumentScenarios ds ON ds.scenario = s.id "
        "JOIN Documents d ON ds.document = d.id "
        "WHERE d.filename LIKE ?", (f"{name}.%",)).fetchall()
    return {normalise(r[0]): r[0] for r in rows}


def _evidence(subject: str, predicate: str, row: dict, document: str) -> tuple:
    """(link line, node block) for one value's passage.

    The quote is what makes the value citable, and the page and rectangles are
    what let a reader see it on the page. All three come from the harvest, none
    from the model's word alone: the quote was checked against the source and
    located in the PDF before it ever got here.
    """
    provenance = row.get("provenance") or {}
    iri = mint("evidence", f"{subject}|{predicate}|{row.get('value')}|"
                           f"{provenance.get('owner_kind')}|"
                           f"{provenance.get('owner_id')}")
    node = [f"<{iri}>", "    a oekgprov:ExtractionEvidence ;",
            f"    oekgprov:aboutProperty {predicate} ;",
            f"    oekgprov:extractedValue {literal(row.get('value'))} ;",
            f"    oekgprov:quote {literal(row.get('quote') or '')} ;",
            f"    oekgprov:sourceDocument {literal(document)} ;",
            f"    oekgprov:evidenceTier {literal(row.get('tier') or '')} ;"]
    if provenance.get("page"):
        node.append(f'    oekgprov:page "{int(provenance["page"])}"^^xsd:integer ;')
    for rect in provenance.get("rects") or ():
        node.append("    oekgprov:region "
                    f"{literal(' '.join(str(round(v, 2)) for v in rect))} ;")
    node[-1] = node[-1].rstrip(" ;") + " ."
    return (f"    oekgprov:hasEvidence <{iri}> ;",
            NL.join(node) + NL)


def make_serializer(db_path: Path):
    """(document name, accepted tuple rows) -> TTL string or None."""
    header_pending = [True]

    def serializer(name: str, rows: list):
        by_param: dict = {}
        for row in rows:
            by_param.setdefault(row.get("parameter"), []).append(row)

        chosen: dict = {}
        contested: dict = {}
        for key in SINGLE:
            if by_param.get(key):
                chosen[key], others = _pick_one(by_param[key])
                if others:
                    contested[key] = others

        missing = [k for k in REQUIRED
                   if not (chosen.get(k) or by_param.get(k))]
        if "publication_title" not in chosen:
            log.info("kg: %s: no title extracted — nothing to serialize", name)
            return None

        # A diagnostic, never a precondition: the graph does not depend on the
        # crawl, so an unreachable DocumentMeta must not stop the serialization.
        # The AR6 scenario list is read in the same breath — it is not a source
        # either, it is what a scenario name extracted from the PDF is matched
        # against, and an empty list simply means nothing can be matched.
        known: dict = {}
        conn = None
        try:
            # `with sqlite3.connect(...)` commits a transaction, it does not
            # close the connection — one leaked handle per document, and on
            # Windows a file nobody can delete afterwards.
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            _crosscheck(conn, name, chosen)
            known = _known_scenarios(conn, name)
        except sqlite3.Error as exc:
            log.warning("kg: %s: no cross-check against the crawl (%s)", name, exc)
        finally:
            if conn is not None:
                conn.close()

        title = chosen["publication_title"]
        report = mint("studyreport", title)
        bundle = mint("scenariobundle",
                      chosen.get("study_project_name") or title)

        evidence_nodes: list = []

        def evidence_for(subject: str, predicate: str, sources: list) -> list:
            """Link lines for one value's passages; the nodes are collected."""
            if not EVIDENCE:
                return []
            links = []
            for row in sources:
                link, node = _evidence(subject, predicate, row, name)
                links.append(link)
                evidence_nodes.append(node)
            return links

        def rows_for(key: str, value=None, scenario=None) -> list:
            out = []
            for row in by_param.get(key, ()):
                if value is not None and row.get("value") != value:
                    continue
                if scenario is not None and \
                        normalise(row.get("scenario") or "") != scenario:
                    continue
                out.append(row)
            return out

        def entities(key: str, collection: str, cls: str) -> tuple:
            """Distinct named things of one kind, each as its own node."""
            seen: dict = {}
            for row in by_param.get(key, ()):
                seen.setdefault(normalise(row["value"]), row["value"])
            links, nodes = [], []
            for label in seen.values():
                iri = mint(collection, label)
                links.append(f"<{iri}>")
                block = [f"<{iri}>", f"    a oeo:{cls} ;"]
                block += evidence_for(iri, "rdfs:label",
                                      rows_for(key, value=label))
                block.append(f"    rdfs:label {literal(label)} .")
                nodes.append(NL.join(block) + NL)
            return links, nodes

        author_links, author_nodes = entities("publication_author", "author",
                                              CLS_AUTHOR)
        org_links, org_nodes = entities("study_organisation", "organisation",
                                        CLS_ORGANISATION)
        funder_links, funder_nodes = entities("study_funder", "funder",
                                              CLS_FUNDER)

        # ---- the study report ---------------------------------------------
        pub: list = [f"<{report}>", f"    a oeo:{CLS_REPORT} ;",
                     f"    oeo:{P_UUID} {literal(uuid_of(report))} ;"]
        pub += evidence_for(report, "rdfs:label",
                            rows_for("publication_title", value=title))
        pub.append(f"    rdfs:label {literal(title)} ;")
        if author_links:
            pub.append(f"    oeo:{P_AUTHOR} " +
                       " ,\n        ".join(author_links) + " ;")
        if chosen.get("publication_date"):
            stamp = _publication_date(chosen["publication_date"])
            if stamp:
                pub += evidence_for(
                    report, f"oeo:{P_PUBDATE}",
                    rows_for("publication_date",
                             value=chosen["publication_date"]))
                pub.append(f'    oeo:{P_PUBDATE} "{stamp}"^^xsd:dateTime ;')
        if chosen.get("publication_doi"):
            pub += evidence_for(report, f"oeo:{P_DOI}",
                                rows_for("publication_doi",
                                         value=chosen["publication_doi"]))
            pub.append(f"    oeo:{P_DOI} {literal(chosen['publication_doi'])} ;")
        pub[-1] = pub[-1].rstrip(" ;") + " ."

        # ---- the scenarios --------------------------------------------------
        # A scenario is named by scenario_label, or by any scenario-scope value
        # that says which scenario it belongs to. Both are the document's own
        # wording; `known` is the AR6 list it is matched against.
        wanted: dict = {}
        for row in by_param.get("scenario_label", ()):
            wanted.setdefault(normalise(row["value"]), row["value"])
        for key in SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                if row.get("scenario"):
                    wanted.setdefault(normalise(row["scenario"]), row["scenario"])

        scenario_links: list = []
        scenario_nodes: list = []
        unplaced: list = []
        for norm, label in wanted.items():
            if known and norm not in known:
                unplaced.append(label)
            iri = mint("scenariofactsheet", f"{title}|{label}")
            scenario_links.append(f"<{iri}>")
            block = [f"<{iri}>", f"    a oeo:{CLS_SCENARIO} ;",
                     f"    oeo:{P_UUID} {literal(uuid_of(iri))} ;"]
            block += evidence_for(iri, "rdfs:label",
                                  rows_for("scenario_label", value=label))
            # Mirjam: with no long name beside the acronym, both carry the same
            # string. That is the usual case in this corpus.
            block.append(f"    rdfs:label {literal(known.get(norm, label))} ;")
            block.append(f"    dc:acronym {literal(label)} ;")
            block.append(f"    oeo:{P_SCENARIO_TYPE} oeo:{IAM_SCENARIO} ;")

            described = rows_for("scenario_abstract", scenario=norm)
            if described:
                best, _ = _pick_one(described)
                block += evidence_for(iri, "dc:abstract",
                                      rows_for("scenario_abstract", value=best,
                                               scenario=norm))
                block.append(f"    dc:abstract {literal(best)} ;")

            regions: dict = {}
            for row in rows_for("scenario_region", scenario=norm):
                regions.setdefault(normalise(row["value"]), row["value"])
            for region in regions.values():
                region_iri = mint("studyregion", region)
                block.append(f"    oeo:{P_STUDY_REGION} <{region_iri}> ;")
                scenario_nodes.append(
                    f"<{region_iri}>{NL}    a oeo:{CLS_REGION} ;{NL}"
                    f"    rdfs:label {literal(region)} .{NL}")

            years = sorted({re.search(r"\d{4}", str(r["value"])).group(0)
                            for r in rows_for("scenario_year", scenario=norm)
                            if re.search(r"\d{4}", str(r["value"]))})
            for year in years:
                block.append(f'    oeo:{P_SCENARIO_YEAR} '
                             f'"{year}-01-01T00:00:00"^^xsd:dateTime ;')
            block[-1] = block[-1].rstrip(" ;") + " ."
            scenario_nodes.append(NL.join(block) + NL)

        # ---- the bundle -----------------------------------------------------
        std: list = [f"<{bundle}>", f"    a oeo:{CLS_BUNDLE} ;",
                     f"    oeo:{P_UUID} {literal(uuid_of(bundle))} ;",
                     f"    rdfs:label "
                     f"{literal(chosen.get('study_project_name') or title)} ;"]
        if chosen.get("study_acronym"):
            std.append(f"    dc:acronym {literal(chosen['study_acronym'])} ;")
        if chosen.get("publication_abstract"):
            std += evidence_for(bundle, "dc:abstract",
                                rows_for("publication_abstract",
                                         value=chosen["publication_abstract"]))
            std.append(f"    dc:abstract "
                       f"{literal(chosen['publication_abstract'])} ;")
        if org_links:
            std.append(f"    oeo:{P_ORGANISATION} " +
                       " ,\n        ".join(org_links) + " ;")
        if funder_links:
            std.append(f"    oeo:{P_FUNDER} " +
                       " ,\n        ".join(funder_links) + " ;")
        for part in [f"<{report}>"] + scenario_links:
            std.append(f"    obo:{P_HAS_PART} {part} ;")
        std[-1] = std[-1].rstrip(" ;") + " ."

        log.info("kg: %s: 1 report, 1 bundle, %d scenario(s), %d author(s), "
                 "%d organisation(s), %d funder(s)%s%s%s", name,
                 len(scenario_links), len(author_links), len(org_links),
                 len(funder_links),
                 f", contested {contested}" if contested else "",
                 f", MISSING REQUIRED {missing}" if missing else "",
                 f", {len(unplaced)} scenario name(s) not in the AR6 list "
                 f"{unplaced[:5]}" if unplaced else "")

        parts = [NL.join(pub) + NL, NL.join(std) + NL]
        parts += scenario_nodes + author_nodes + org_nodes + funder_nodes
        parts += evidence_nodes
        body = NL.join(parts)
        if header_pending[0]:
            header_pending[0] = False
            return PREFIXES + "\n" + body
        return body

    return serializer
