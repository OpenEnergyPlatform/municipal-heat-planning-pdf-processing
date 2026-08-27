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
OEKG_EVIDENCE=0 to emit the shape-conformant graph instead, which keeps the
same passages as Turtle comments above the triples they belong to.

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
from collections import Counter
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Where individuals live. The shapes only fix the ontology prefixes, so this
# was read off the running graph instead (13700 triples over the SPARQL
# endpoint): every collection below is the one the OEKG already uses for that
# class. Still to confirm with Mirjam is the *local part* — the OEKG's own
# UUIDs are random, ours are UUIDv5 over the identifying name so that two runs
# over one document mint one IRI and a re-run does not duplicate the graph.
BASE = os.environ.get("OEKG_ID_BASE", "https://openenergyplatform.org/ontology/oekg/")
NS_OEKG = uuid.uuid5(uuid.NAMESPACE_URL, BASE)

# Class -> path segment, as the live OEKG has them. A study report sits under
# publication/, a factsheet under scenario/, and a bundle, author, organisation
# or funder directly under the base with no segment at all.
COLLECTIONS = {
    "studyreport": "publication",
    "scenariofactsheet": "scenario",
    "scenariobundle": "",
    "author": "",
    "organisation": "",
    "funder": "",
    "studyregion": "region",
}

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
SCENARIO_FIELDS = ("scenario_type", "scenario_abstract",
                   "scenario_region", "scenario_year")
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
    segment = COLLECTIONS.get(collection, collection)
    prefix = f"{BASE}{segment}/" if segment else BASE
    return f"{prefix}{uuid.uuid5(ns(collection), normalise(name))}"


def uuid_of(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]


def _squeeze(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


# The choice lists in extraction.py carry entries that are deliberately not a
# thing in the graph: a scenario family instead of a run, a global scope
# instead of a country. They exist so the model can say so instead of picking
# the nearest entry that is almost right — which means every place where an
# answer turns into an IRI, a type or a link has to refuse them. One prefix,
# checked once here, so a new out: entry cannot quietly become a node.
NOT_IN_GRAPH = "out:"


def in_graph(value) -> bool:
    """Is this answer something the graph takes, or one of the out: entries?"""
    return bool(value) and not str(value).startswith(NOT_IN_GRAPH)


def graph_value(row: dict):
    """What this row actually put in the graph.

    For an out: entry the model's `value` is that entry's own label — a
    description of why nothing fitted, not a reading of the document. The
    graph carries the wording instead, so the evidence has to name the wording
    too, or it would cite a passage for a string that is nowhere in it.
    """
    uri = row.get("value_uri")
    if uri and not in_graph(uri):
        return row.get("value_raw") or ""
    return row.get("value")


def ambiguous(wording, known: dict) -> bool:
    """Does this wording fit more than one AR6 run of this publication?

    Measured on the 146-scenario pilot document: the paper writes "NPi" and
    "NDC", and the database has EN_NPi2020_300f, EN_NPi2020_400 and
    EN_NPi2020_3000. Those are three runs, and "NPi" names the family, not one
    of them. A model handed the list picks one anyway, which is a guess
    dressed as a link — so a wording that fits several is treated as fitting
    none, and the wording alone survives.
    """
    needle = _squeeze(wording)
    if not needle:
        return False
    hits = [name for name in known.values() if needle in _squeeze(name)]
    if len(hits) < 2:
        return False
    return not any(_squeeze(name) == needle for name in hits)


def scenario_key(row: dict, known: Optional[dict] = None) -> tuple:
    """(identity, label) for the scenario a row belongs to.

    The model picks the AR6 run from this publication's own list and keeps the
    document's wording beside it. The run identifier is the identity whenever
    there is one, because that is what links to the AR6 database; the wording
    is what a reader recognises. With no match, and with a wording that fits
    several runs equally, the wording is both.
    """
    if row.get("parameter") == "scenario_label":
        resolved, wording = row.get("value_uri"), row.get("value_raw")
        fallback = row.get("value")
    else:
        resolved, wording = row.get("scenario"), row.get("scenario_raw")
        fallback = row.get("scenario")
    if not in_graph(resolved) and resolved:
        # An out: entry. The model said the wording names no single run, so
        # there is no identity — and no fallback either, because `value` is
        # then the out: entry's own label ("eine Szenario-Familie, kein
        # einzelner Lauf"), which is a description and not a name.
        resolved, fallback = None, None
    wording = wording or fallback
    if resolved and known and ambiguous(wording, known):
        resolved = None
    return (resolved or wording or None), (wording or resolved or None)


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


def _ttl_comment(text) -> str:
    """One Turtle comment line, flattened so a quote cannot break the file."""
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    return "    # " + flat[:400]


def _evidence_comment(row: dict, document: str) -> list:
    """The same passage as comment lines, for a run against the closed shapes.

    OEKG_EVIDENCE=0 used to mean the graph simply forgot where a value came
    from, which gives up the reason the metadata is read out of the PDF at all
    instead of taken from the crawl. A comment is not a triple: it survives
    sh:closed, it survives a diff, and a reader looking at the node sees the
    sentence the value was read in.
    """
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
        lines.append(_ttl_comment(f"“{row['quote']}”"))
    lines.append(_ttl_comment(", ".join(where)))
    if row.get("flags"):
        lines.append(_ttl_comment("flags: " + ", ".join(row["flags"])))
    return lines


def _evidence(subject: str, predicate: str, row: dict, document: str) -> tuple:
    """(link line, node block) for one value's passage.

    The quote is what makes the value citable, and the page and rectangles are
    what let a reader see it on the page. All three come from the harvest, none
    from the model's word alone: the quote was checked against the source and
    located in the PDF before it ever got here.
    """
    provenance = row.get("provenance") or {}
    shown = graph_value(row)
    iri = mint("evidence", f"{subject}|{predicate}|{shown}|"
                           f"{provenance.get('owner_kind')}|"
                           f"{provenance.get('owner_id')}")
    node = [f"<{iri}>", "    a oekgprov:ExtractionEvidence ;",
            f"    oekgprov:aboutProperty {predicate} ;",
            f"    oekgprov:extractedValue {literal(shown)} ;",
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

        # What the model said does NOT belong in the graph. Counted once, here,
        # so the number is a measurement of the corpus rather than a side
        # effect of whichever loop happened to look at the row: a run of
        # publications that is 80% out:global is telling us the OEKG's region
        # list is missing its aggregates, not that the harvest is failing.
        out_of_graph: Counter = Counter()
        for row in rows:
            for field in ("value_uri", "scenario"):
                if str(row.get(field) or "").startswith(NOT_IN_GRAPH):
                    out_of_graph[row[field]] += 1

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
            """Lines to put above the triple this evidence belongs to.

            With EVIDENCE on those are links into oekgprov: nodes; with it off
            they are comments. Either way the passage stays in the file, and
            either way the caller appends the triple itself afterwards, so the
            block never ends on one of these lines.
            """
            if not EVIDENCE:
                return [line for row in sources
                        for line in _evidence_comment(row, name)]
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
                        normalise(scenario_key(row, known)[0] or "") != scenario:
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
        for key in ("scenario_label",) + SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                ident, label = scenario_key(dict(row, parameter=key), known)
                if ident:
                    wanted.setdefault(normalise(ident), (ident, label))

        scenario_links: list = []
        scenario_nodes: list = []
        unplaced: list = []
        for norm, (ident, label) in wanted.items():
            if known and norm not in known:
                unplaced.append(label)
            iri = mint("scenariofactsheet", f"{title}|{ident}")
            scenario_links.append(f"<{iri}>")
            block = [f"<{iri}>", f"    a oeo:{CLS_SCENARIO} ;",
                     f"    oeo:{P_UUID} {literal(uuid_of(iri))} ;"]
            block += evidence_for(iri, "rdfs:label",
                                  rows_for("scenario_label", scenario=norm))
            # Mirjam: with no long name beside the acronym, both carry the same
            # string. That is the usual case in this corpus.
            block.append(f"    rdfs:label {literal(known.get(norm, ident))} ;")
            block.append(f"    dc:acronym {literal(label or ident)} ;")

            # The types the model chose from the shapes' own list, each with
            # the passage it read them in. On top of that Mirjam asks every IAM
            # scenario to carry OEO_00020517, which the release does not have
            # yet — see the note on IAM_SCENARIO.
            types: dict = {}
            for row in rows_for("scenario_type", scenario=norm):
                if row.get("value_uri"):
                    types.setdefault(row["value_uri"], []).append(row)
            for type_iri, sources in types.items():
                block += evidence_for(iri, f"oeo:{P_SCENARIO_TYPE}", sources)
                block.append(f"    oeo:{P_SCENARIO_TYPE} <{type_iri}> ;")
            block.append(f"    oeo:{P_SCENARIO_TYPE} oeo:{IAM_SCENARIO} ;")

            described = rows_for("scenario_abstract", scenario=norm)
            if described:
                best, _ = _pick_one(described)
                block += evidence_for(iri, "dc:abstract",
                                      rows_for("scenario_abstract", value=best,
                                               scenario=norm))
                block.append(f"    dc:abstract {literal(best)} ;")

            # A region the model picked already exists in the OEKG under
            # its own IRI (oekg/region/Germany), so it is referenced, not
            # minted. Only a wording that matched nothing gets an IRI of ours,
            # and that one is a finding to review rather than a node to trust.
            regions: dict = {}
            for row in rows_for("scenario_region", scenario=norm):
                if not in_graph(row.get("value_uri")) and row.get("value_uri"):
                    # "global", "mehrere Laender": a true answer and not a
                    # study region. The OEKG holds 249 countries and no
                    # aggregate, so there is nothing to point at — minting one
                    # would invent a region that the OEKG then has twice.
                    continue
                region_iri = row.get("value_uri") or mint("studyregion",
                                                          row["value"])
                regions.setdefault(region_iri, (row["value"], []))[1].append(row)
            for region_iri, (canonical, sources) in regions.items():
                block += evidence_for(iri, f"oeo:{P_STUDY_REGION}", sources)
                block.append(f"    oeo:{P_STUDY_REGION} <{region_iri}> ;")
                scenario_nodes.append(
                    f"<{region_iri}>{NL}    a oeo:{CLS_REGION} ;{NL}"
                    f"    rdfs:label {literal(canonical)} .{NL}")

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
                 "%d organisation(s), %d funder(s)%s%s%s%s", name,
                 len(scenario_links), len(author_links), len(org_links),
                 len(funder_links),
                 f", contested {contested}" if contested else "",
                 f", MISSING REQUIRED {missing}" if missing else "",
                 f", {len(unplaced)} scenario name(s) not in the AR6 list "
                 f"{unplaced[:5]}" if unplaced else "",
                 f", not in the graph by choice: {dict(out_of_graph)}"
                 if out_of_graph else "")

        parts = [NL.join(pub) + NL, NL.join(std) + NL]
        parts += scenario_nodes + author_nodes + org_nodes + funder_nodes
        parts += evidence_nodes
        body = NL.join(parts)
        if header_pending[0]:
            header_pending[0] = False
            return PREFIXES + "\n" + body
        return body

    return serializer
