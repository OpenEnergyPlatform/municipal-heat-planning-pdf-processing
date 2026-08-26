"""
kg.py – Harvested publication metadata to OEKG Turtle.

What the shapes ask of a scenario bundle and its study report, and nothing
else: ex:StudyShape and ex:PublicationShape are `sh:closed true`, so a triple
the shape does not name makes the node invalid. That has one consequence
worth stating out loud: the evidence for a value — the quote, its page, the
rectangles on that page — CANNOT hang off these nodes. It stays in the JSONL
harvest, which is where the licence argument for extracting metadata that the
crawl already knew is settled anyway.

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

# Paths, from the shapes file.
P_UUID = "OEO_00390095"            # has uuid
P_AUTHOR = "OEO_00000506"          # has author
P_PUBDATE = "OEO_00390096"         # has publication date
P_DOI = "OEO_00390098"             # has doi
P_ORGANISATION = "OEO_00000510"    # has organisation
P_FUNDER = "OEO_00000509"          # has funding source
P_HAS_PART = "BFO_0000051"         # has part

# What the shapes allow at most once. Everything else may repeat.
SINGLE = ("publication_title", "publication_date", "publication_doi",
          "publication_abstract", "study_project_name", "study_acronym")
# What the shapes demand at least once (sh:minCount 1). A document missing one
# of these produces a node that will fail validation, so it is reported.
REQUIRED = ("publication_title", "publication_date", "publication_author")

PREFIXES = """\
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix dc:   <http://purl.org/dc/terms/> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .
"""

_LEGAL = r"(gmbh|mbh|ag|kg|ohg|e\.?\s*v\.?|gbr|se|ug|inc|ltd|llc)"


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
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                _crosscheck(conn, name, chosen)
        except sqlite3.Error as exc:
            log.warning("kg: %s: no cross-check against the crawl (%s)", name, exc)

        title = chosen["publication_title"]
        report = mint("studyreport", title)
        bundle = mint("scenariobundle",
                      chosen.get("study_project_name") or title)

        def entities(key: str, collection: str, cls: str) -> tuple:
            seen: dict = {}
            for row in by_param.get(key, ()):
                seen.setdefault(normalise(row["value"]), row["value"])
            out = [(mint(collection, v), v) for v in seen.values()]
            return out, [f"<{iri}>\n    a oeo:{cls} ;\n"
                         f"    rdfs:label {literal(label)} .\n"
                         for iri, label in out]

        authors, author_nodes = entities("publication_author", "author", CLS_AUTHOR)
        orgs, org_nodes = entities("study_organisation", "organisation",
                                   CLS_ORGANISATION)
        funders, funder_nodes = entities("study_funder", "funder", CLS_FUNDER)

        pub: list = [f"<{report}>", f"    a oeo:{CLS_REPORT} ;",
                     f"    oeo:{P_UUID} {literal(uuid_of(report))} ;",
                     f"    rdfs:label {literal(title)} ;"]
        if authors:
            pub.append(f"    oeo:{P_AUTHOR} " +
                       " ,\n        ".join(f"<{iri}>" for iri, _ in authors) + " ;")
        if chosen.get("publication_date"):
            stamp = _publication_date(chosen["publication_date"])
            if stamp:
                pub.append(f'    oeo:{P_PUBDATE} "{stamp}"^^xsd:dateTime ;')
        if chosen.get("publication_doi"):
            pub.append(f"    oeo:{P_DOI} {literal(chosen['publication_doi'])} ;")
        pub[-1] = pub[-1].rstrip(" ;") + " ."

        std: list = [f"<{bundle}>", f"    a oeo:{CLS_BUNDLE} ;",
                     f"    oeo:{P_UUID} {literal(uuid_of(bundle))} ;",
                     f"    rdfs:label "
                     f"{literal(chosen.get('study_project_name') or title)} ;"]
        if chosen.get("study_acronym"):
            std.append(f"    dc:acronym {literal(chosen['study_acronym'])} ;")
        if chosen.get("publication_abstract"):
            std.append(f"    dc:abstract "
                       f"{literal(chosen['publication_abstract'])} ;")
        if orgs:
            std.append(f"    oeo:{P_ORGANISATION} " +
                       " ,\n        ".join(f"<{iri}>" for iri, _ in orgs) + " ;")
        if funders:
            std.append(f"    oeo:{P_FUNDER} " +
                       " ,\n        ".join(f"<{iri}>" for iri, _ in funders) + " ;")
        std.append(f"    obo:{P_HAS_PART} <{report}> .")

        log.info("kg: %s: 1 report, 1 bundle, %d author(s), %d organisation(s), "
                 "%d funder(s)%s%s", name, len(authors), len(orgs), len(funders),
                 f", contested {contested}" if contested else "",
                 f", MISSING REQUIRED {missing}" if missing else "")

        parts = ["\n".join(pub) + "\n", "\n".join(std) + "\n"]
        parts += author_nodes + org_nodes + funder_nodes
        body = "\n".join(parts)
        if header_pending[0]:
            header_pending[0] = False
            return PREFIXES + "\n" + body
        return body

    return serializer
