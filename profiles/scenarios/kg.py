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
By default every passage is a Turtle comment above the triple it belongs to,
which survives sh:closed; OEKG_EVIDENCE=1 emits one `oekgprov:ExtractionEvidence`
node per value instead, linked with `oekgprov:hasEvidence` — the same content as
triples, and knowingly ahead of the shapes.

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

import json
import logging
import os
import re
import sqlite3
import unicodedata
import uuid
from collections import Counter
from pathlib import Path
from typing import Optional

from docpipe.extraction.spec import kg_name, load as load_spec
from docpipe.extraction.trust import check_prose, render, trust

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

# The namespaces the Turtle header declares. Up here because the
# predicates below are checked against it as they are read.
PREFIXES = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .
@prefix dc:   <http://purl.org/dc/terms/> .
@prefix obo:  <http://purl.obolibrary.org/obo/> .
@prefix oeo:  <https://openenergyplatform.org/ontology/oeo/> .
@prefix oekgprov: <https://openenergyplatform.org/ontology/oekg/provenance/> .
"""


_SPEC = json.loads(
    Path(__file__).with_name("extraction_spec.json").read_text(encoding="utf-8"))


def _kg(uri: str) -> dict:
    """The `kg` block of one parameter of this profile's spec."""
    for parameter in _SPEC["parameters"]:
        if parameter["uri"] == uri:
            block = parameter.get("kg")
            if not block:
                raise KeyError(f"parameter {uri!r} says nothing about the "
                               f"graph; add a kg block to the spec")
            return block
    raise KeyError(f"no parameter {uri!r} in the spec")


def _name(block: dict) -> str:
    """`{"prefix": "oeo", "predicate": "OEO_00000506"}` -> "oeo:OEO_00000506".

    Against THIS profile's header: scenarios binds dc: and kwp does not, so
    the same block is legal in one graph and unwritable in the other. The rule
    itself is the core's, or there would be two live copies of it.
    """
    return kg_name(block, PREFIXES)


def _property(uri: str, key: str = "property") -> str:
    """The predicate a parameter's own value becomes on its node."""
    return _name(_kg(uri)[key])


def _edge(uri: str) -> str:
    """The predicate hanging a parameter's own node off another one."""
    return _name(_kg(uri)["edge_from"])


def _class(uri: str) -> str:
    """The OEO class of the node a parameter mints. Bare: every class of this
    graph is an OEO class, and it is only ever written as `a oeo:<id>`."""
    block = _kg(uri)
    if "class" not in block:
        raise KeyError(f"parameter {uri!r} mints no node of its own")
    return block["class"]


def _linked_by(axis: str = "scenario") -> str:
    """The predicate that hangs the node an axis names off its parent."""
    for parameter in _SPEC["parameters"]:
        block = ((parameter.get("axes") or {}).get(axis) or {}).get("kg") or {}
        if block.get("role") == "parent" and block.get("linked_by"):
            return _name(block["linked_by"])
    raise KeyError(f"no kg parent link for axis {axis!r} in the spec")


# Classes the shapes require at the end of each path, read from the parameter
# that mints each node. Written down twice, they drifted: the test that says
# the graph holds no predicate the shapes do not name carried a third copy.
CLS_BUNDLE = _class("study_project_name")      # scenario bundle (StudyShape)
CLS_REPORT = _class("publication_title")       # study report (PublicationShape)
CLS_AUTHOR = _class("publication_author")      # author
CLS_ORGANISATION = _class("study_organisation")
CLS_FUNDER = _class("study_funder")
CLS_SCENARIO = _class("scenario_label")        # factsheet (ScenarioShape)

# Paths, from the spec, which is what the published JSON schema shows a reader
# as `x-kg`. What a reader is told and what is written are one string.
P_LABEL = _property("publication_title")       # rdfs:label
P_ACRONYM = _property("study_acronym")         # dc:acronym
P_ABSTRACT = _property("publication_abstract")  # dc:abstract
P_AUTHOR = _edge("publication_author")         # has author
P_PUBDATE = _property("publication_date")      # has publication date
P_DOI = _property("publication_doi")           # has doi
P_ORGANISATION = _edge("study_organisation")   # has organisation
P_FUNDER = _edge("study_funder")               # has funding source
P_HAS_PART = _linked_by()                      # has part
P_SCENARIO_TYPE = _property("scenario_type")   # has scenario type
P_STUDY_REGION = _property("scenario_region")  # has study region
P_SCENARIO_YEAR = _property("scenario_year")   # has scenario year value

# The two a factsheet writes. They spell the same as the bundle's, and they
# are a different parameter's promise: the bundle's abstract is the study's,
# the factsheet's is one scenario's.
P_SCENARIO_ACRONYM = _property("scenario_label", "also")   # dc:acronym
P_SCENARIO_ABSTRACT = _property("scenario_abstract")       # dc:abstract

# Behind no harvested value, so behind no parameter: every node carries a uuid
# because the OEKG mints them that way.
P_UUID = "oeo:OEO_00390095"        # has uuid


def _bare(name: str) -> str:
    return str(name).split(":")[-1]


def edges() -> list:
    """The triple shapes this serializer writes that no `kg` block carries.

    `ontology.edge_problems` holds the rest of the output to the pinned
    ontology through the spec; without this the writer's own literals are the
    part nobody checks, which is where three of kwp's defects lived.
    """
    return [
        {"where": "kg.py uuid", "subject": _bare(cls),
         "predicate": _bare(P_UUID), "datatype": "xsd:string",
         # `has uuid` is domained on `report or factsheet`. The report and
         # the factsheet are both; the BUNDLE is neither, and the OEKG mints
         # a uuid on every node it holds. Written anyway, and named here: the
         # fix is a wider domain and that is the ontology side's.
         "accepted": ("the OEKG mints a uuid on every node and a scenario "
                      "bundle is neither a report nor a factsheet")
                     if cls == CLS_BUNDLE else None}
        for cls in (CLS_BUNDLE, CLS_REPORT, CLS_SCENARIO)]

# Mirjam: "all IAM scenarios get the annotation for now". JH notes it is
# not in the release nor in the shape's sh:in list yet, so a graph written
# today will fail that constraint until it is.
IAM_SCENARIO = "OEO_00020517"

# What the shapes allow at most once. Everything else may repeat.
SINGLE = ("publication_title", "publication_date", "publication_doi",
          "publication_abstract", "study_project_name", "study_acronym")
# Scenario-scope fields: everything carrying a `scenario` axis, which names
# in the document's own words which scenario the value belongs to. Read from
# the spec, because a fifteenth parameter added there would otherwise be
# missing from four loops here and reach no factsheet, silently.
SCENARIO_FIELDS = tuple(
    parameter["uri"] for parameter in _SPEC["parameters"]
    if "scenario" in (parameter.get("axes") or {}))
# What the shapes demand at least once (sh:minCount 1). A document missing one
# of these produces a node that will fail validation, so it is reported.
REQUIRED = ("publication_title", "publication_date", "publication_author")


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


def _quoted(wording, row: dict) -> bool:
    """Does the document's own passage actually contain this wording?

    Only asked of a wording that is about to become an identity. A resolved run
    identifier does not have to stand in the text — the model maps a
    description onto it, which is the whole job — but a string the model
    presents as the document's own name for something has to be findable in
    the passage the same tuple quotes.
    """
    if "quote" not in row:
        # Nothing to check against. The verifier guarantees a quote on every
        # tuple that reaches here, so this is the unit-test shape, and a check
        # that cannot run must not reject.
        return True
    return _squeeze(wording) in _squeeze(row.get("quote"))


def resolve_wording(wording, known: Optional[dict] = None) -> Optional[str]:
    """The run this wording names, when the list settles it without a guess.

    The mirror of `ambiguous()`. That one refuses the link where several runs
    fit and none matches exactly; this one MAKES the link where exactly one
    does. Both read the same list, and between them the model's own choice is
    only consulted where the list is genuinely undecided.

    Measured on the corpus run: the model answered with an out: entry 1171
    times for a wording its own list resolved unambiguously — 347 of them a
    character-for-character match of a run name, one document refusing "BaU"
    against a list whose single entry is "BaU".

    Short wordings are exact-match only. "NPi" is three characters and sits
    inside a dozen run names; a containment hit that short is a coincidence,
    not a reading.
    """
    needle = _squeeze(wording)
    if not needle or not known:
        return None
    for name in known.values():
        if _squeeze(name) == needle:
            return name
    if len(needle) < 4:
        return None
    hits = [name for name in known.values() if needle in _squeeze(name)]
    return hits[0] if len(hits) == 1 else None


def scenario_key(row: dict, known: Optional[dict] = None,
                 synonyms: Optional[dict] = None) -> tuple:
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
        # then the out: entry's own label ("Szenario-Familie"), which is a
        # description and not a name.
        resolved, fallback = None, None
    wording = wording or fallback
    if not resolved and wording and synonyms:
        # The document's own name for a run, learned from the rows that DID
        # resolve it. The prompt tells the model to leave `scenario` empty when
        # it is unsure, and it is unsure on a table caption and certain on the
        # sentence that introduced the scenario — so one scenario arrived as
        # two, the linked one holding nothing and the unlinked one holding all
        # the values.
        resolved = synonyms.get(normalise(wording))
    if not resolved and wording:
        # And if the list itself settles it, the model's refusal does not
        # stand: an out: entry says "no single run fits", which is a claim
        # about the list, and the list is right here to be read.
        resolved = resolve_wording(wording, known)
    if resolved and known and ambiguous(wording, known):
        # The wording names a family, so the link is dropped and the wording is
        # the identity. Rows the model assigned to DIFFERENT runs then merge
        # onto one factsheet — which is a conflation, but the alternative is
        # worse: splitting them would take the identity from the very guess
        # this guard just refused to trust. The merge is reported instead, in
        # the serializer, where the whole document's rows are visible.
        resolved = None
    if not resolved and wording and not _quoted(wording, row):
        # A wording that is nowhere in the passage it claims to come from
        # cannot be a name the document uses. It used to mint a factsheet
        # anyway, with a stable IRI and the invented string as its label.
        return None, None
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
    # A running header is a prefix of the title and is harvested from every
    # page it stands on, so it outvotes the one reading that was located on the
    # title page — and the truncation then becomes the document's IRI, stably,
    # on every re-run. A candidate contained in another candidate is that
    # truncation, and it never wins.
    contained = [value for value in by_value
                 if any(value != other and value in other
                        for other in by_value)]
    if len(contained) < len(by_value):
        for value in contained:
            del by_value[value]
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


# The passages are written as Turtle comments by default, which is what kwp
# does and for the same reason: the shapes are sh:closed, so oekgprov:hasEvidence
# on a study report or a factsheet invalidates the very node it documents.
# OEKG_EVIDENCE=1 emits the provenance nodes instead — same content, queryable,
# and knowingly ahead of the shapes.
EVIDENCE = os.environ.get("OEKG_EVIDENCE", "0") != "0"

# The words of the trust line; the marks and their order are the core's
# (docpipe.extraction.trust.MARKS). English, because this corpus is English
# and so is the graph its values go into.
TRUST_PROSE = check_prose({
    "level": "confidence: {level}",
    "image_origin": "read off an image, not the running text",
    "image_origin_named": "read off an image, not the running text ({image})",
    "corroborated": "a second passage says the same",
    "reasons": "{reasons}",
    "review": "worth checking",
}, "profiles/scenarios/kg.py TRUST_PROSE")
TRUST_JOIN = ", "

# Through the core's loader once, at import, for what that loader refuses:
# a spec broken that way stops the serializer before a single document is
# written, not partway through a run.
load_spec(_SPEC)

# This corpus has no transcribed pages to declare: ar6.db Documents carries
# no page_text_transcribed column, so `trust` is never told a page was itself
# a reading. Named here so the missing argument is a fact and not an
# oversight -- if that column ever arrives, this is where it is read.
PAGE_TRANSCRIBED = False


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
    # The passage belongs in the identity. Two windows of one long section
    # overlap by 400 characters, so one value arrives twice from one owner
    # with two different quotes — and without the quote in the key they merge
    # into a single node asserting both, which is a citation of neither.
    iri = mint("evidence", f"{subject}|{predicate}|{shown}|"
                           f"{provenance.get('owner_kind')}|"
                           f"{provenance.get('owner_id')}|{row.get('quote')}")
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
    # A preprint and its journal version share a title, so they mint the same
    # study report and the same bundle. The single-valued triples are then
    # written twice into one file, with two dates and two abstracts on one
    # subject, and each document's own log says "1 report, 1 bundle".
    minted: dict = {}

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
        for key in ("scenario_label", "scenario_region", "scenario_type"):
            for row in by_param.get(key, ()):
                if not row.get("value_uri"):
                    # Verified, quoted, located — and it reaches no triple,
                    # because the list held nothing for it and the model chose
                    # no out: entry either. Without this the gap on a field
                    # reads as zero after a corpus run.
                    out_of_graph[f"unmapped:{key}"] += 1

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
        for kind, iri in (("study report", report), ("bundle", bundle)):
            first = minted.setdefault(iri, name)
            if first != name:
                log.warning("kg: %s: the %s <%s> was already written for %r — "
                            "one subject, two documents, and the shapes allow "
                            "one label and one date on it", name, kind, iri,
                            first)

        evidence_nodes: list = []

        def evidence_for(subject: str, predicate: str, sources: list) -> list:
            """Lines to put above the triple this evidence belongs to.

            With EVIDENCE on those are links into oekgprov: nodes; with it off
            they are comments. Either way the passage stays in the file, and
            either way the caller appends the triple itself afterwards, so the
            block never ends on one of these lines.

            The trust line rides on both branches, not inside
            `_evidence_comment`: that one is skipped whole under
            OEKG_EVIDENCE=1, so a level written there would be in the file
            nobody publishes and missing from the one they do. A Turtle
            comment is legal between the link line and the triple, and the
            level is the one thing the closed shapes have no property for.

            One line per source, like the passage above it. A value three
            passages agree on is three readings and each has its own level.
            """
            lines = []
            for row in sources:
                if EVIDENCE:
                    link, node = _evidence(subject, predicate, row, name)
                    lines.append(link)
                    evidence_nodes.append(node)
                else:
                    lines.extend(_evidence_comment(row, name))
                # A single-valued field the harvest read two ways is a doubt
                # about THIS value, the same doubt kwp reports when two tuples
                # mint one IRI. `_pick_one` already decided and counted the
                # rivals; without this the winner is graded as if it had been
                # the only reading.
                verdict = trust(row, transcribed=PAGE_TRANSCRIBED,
                                conflict=bool(contested.get(row.get("parameter"))))
                lines.append(_ttl_comment(render(verdict, TRUST_PROSE,
                                                 join=TRUST_JOIN, row=row)))
            return lines

        # What this document calls each run, learned from the rows that DID
        # resolve one. The prompt tells the model to leave the link empty when
        # it is unsure, and it is sure on the sentence that introduces a
        # scenario and unsure on the table caption three pages later — so the
        # same scenario arrived twice, once linked and empty, once unlinked
        # and carrying every value.
        # What the list settled that the model had given up on. Counted, not
        # silently absorbed: a number that stays high says the prompt is
        # teaching the escape hatch too well.
        rescued = 0
        for key in ("scenario_label",) + SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                proposed = (row.get("value_uri") if key == "scenario_label"
                            else row.get("scenario"))
                wording = (row.get("value_raw") if key == "scenario_label"
                           else row.get("scenario_raw"))
                if str(proposed or "").startswith(NOT_IN_GRAPH)                         and resolve_wording(wording, known):
                    rescued += 1

        synonyms: dict = {}
        for key in ("scenario_label",) + SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                proposed = (row.get("value_uri") if key == "scenario_label"
                            else row.get("scenario"))
                wording = (row.get("value_raw") if key == "scenario_label"
                           else row.get("scenario_raw"))
                if in_graph(proposed) and wording \
                        and normalise(proposed) in known \
                        and not ambiguous(wording, known):
                    synonyms.setdefault(normalise(wording), proposed)

        def rows_for(key: str, value=None, scenario=None) -> list:
            out = []
            for row in by_param.get(key, ()):
                if value is not None and row.get("value") != value:
                    continue
                if scenario is not None and \
                        normalise(scenario_key(row, known, synonyms)[0] or "") \
                        != scenario:
                    continue
                out.append(row)
            return out

        def entities(key: str, collection: str, cls: str) -> tuple:
            """Distinct named things of one kind, each as its own node."""
            # Group by the normalised name, but keep every row: "Oeko-Institut"
            # and "Oeko-Institut e.V." are one node, and filtering the evidence
            # by the winning spelling afterwards threw the other one's passage
            # away — the page where the second spelling stands vanished from
            # the file entirely.
            groups: dict = {}
            for row in by_param.get(key, ()):
                groups.setdefault(normalise(row["value"]),
                                  (row["value"], []))[1].append(row)
            links, nodes = [], []
            for label, sources in groups.values():
                iri = mint(collection, label)
                links.append(f"<{iri}>")
                block = [f"<{iri}>", f"    a oeo:{cls} ;"]
                block += evidence_for(iri, P_LABEL, sources)
                block.append(f"    {P_LABEL} {literal(label)} .")
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
                     f"    {P_UUID} {literal(uuid_of(report))} ;"]
        pub += evidence_for(report, P_LABEL,
                            rows_for("publication_title", value=title))
        pub.append(f"    {P_LABEL} {literal(title)} ;")
        if author_links:
            pub.append(f"    {P_AUTHOR} " +
                       " ,\n        ".join(author_links) + " ;")
        if chosen.get("publication_date"):
            stamp = _publication_date(chosen["publication_date"])
            if stamp:
                pub += evidence_for(
                    report, P_PUBDATE,
                    rows_for("publication_date",
                             value=chosen["publication_date"]))
                pub.append(f'    {P_PUBDATE} "{stamp}"^^xsd:dateTime ;')
        if chosen.get("publication_doi"):
            pub += evidence_for(report, P_DOI,
                                rows_for("publication_doi",
                                         value=chosen["publication_doi"]))
            pub.append(f"    {P_DOI} {literal(chosen['publication_doi'])} ;")
        pub[-1] = pub[-1].rstrip(" ;") + " ."

        # ---- the scenarios --------------------------------------------------
        # A scenario is named by scenario_label, or by any scenario-scope value
        # that says which scenario it belongs to. Both are the document's own
        # wording; `known` is the AR6 list it is matched against.
        # A scenario-scope value whose own `scenario` coordinate never came
        # back has nothing to hang on, and until this counter it left the file
        # without a triple, a comment or a number: the value itself resolved,
        # so `out_of_graph` cannot see it, and `rows_for` simply never matches
        # it. Measured over the 164-document ar6 harvest, 298 of 11.129
        # scenario-scope tuples -- 289 of them `exhausted`, which is a finding
        # about this run's window budget and not about the papers, and 9
        # `unstated`, which is the opposite. Thrown together they say nothing,
        # so the state is what the count is keyed on.
        unplaceable: Counter = Counter()
        wanted: dict = {}
        for key in ("scenario_label",) + SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                ident, label = scenario_key(dict(row, parameter=key),
                                            known, synonyms)
                if ident:
                    wanted.setdefault(normalise(ident), (ident, label))
                elif key != "scenario_label":
                    state = row.get("scenario_state") or "missing"
                    unplaceable[f"{key}:{state}"] += 1

        # One wording, several runs the model proposed for it: the guard drops
        # every one of those links, so the rows land on one factsheet. Whether
        # the paper describes one scenario or three cannot be decided from the
        # wording, and the graph should not pretend either way — but nobody
        # should find this out from the triple count.
        merged: dict = {}
        for key in ("scenario_label",) + SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                proposed = (row.get("value_uri") if key == "scenario_label"
                            else row.get("scenario"))
                wording = (row.get("value_raw") if key == "scenario_label"
                           else row.get("scenario_raw"))
                if in_graph(proposed) and wording and ambiguous(wording, known):
                    merged.setdefault(wording, set()).add(proposed)
        for wording, runs in merged.items():
            if len(runs) > 1:
                log.warning("kg: %s: %r is the document's name for %d different "
                            "AR6 runs (%s) — they share one factsheet, because "
                            "the wording links to none of them", name, wording,
                            len(runs), ", ".join(sorted(runs)))

        scenario_links: list = []
        scenario_nodes: list = []
        unplaced: list = []
        for norm, (ident, label) in wanted.items():
            if known and norm not in known:
                unplaced.append(label)
            iri = mint("scenariofactsheet", f"{title}|{ident}")
            scenario_links.append(f"<{iri}>")
            block = [f"<{iri}>", f"    a oeo:{CLS_SCENARIO} ;",
                     f"    {P_UUID} {literal(uuid_of(iri))} ;"]
            block += evidence_for(iri, P_LABEL,
                                  rows_for("scenario_label", scenario=norm))
            # Mirjam: with no long name beside the acronym, both carry the same
            # string. That is the usual case in this corpus.
            block.append(f"    {P_LABEL} {literal(known.get(norm, ident))} ;")
            block.append(f"    {P_SCENARIO_ACRONYM} {literal(label or ident)} ;")

            # The types the model chose from the shapes' own list, each with
            # the passage it read them in. On top of that Mirjam asks every IAM
            # scenario to carry OEO_00020517, which the release does not have
            # yet — see the note on IAM_SCENARIO.
            types: dict = {}
            for row in rows_for("scenario_type", scenario=norm):
                if in_graph(row.get("value_uri")):
                    types.setdefault(row["value_uri"], []).append(row)
            for type_iri, sources in types.items():
                block += evidence_for(iri, P_SCENARIO_TYPE, sources)
                block.append(f"    {P_SCENARIO_TYPE} <{type_iri}> ;")
            block.append(f"    {P_SCENARIO_TYPE} oeo:{IAM_SCENARIO} ;")

            described = rows_for("scenario_abstract", scenario=norm)
            if described:
                best, _ = _pick_one(described)
                block += evidence_for(iri, P_SCENARIO_ABSTRACT,
                                      rows_for("scenario_abstract", value=best,
                                               scenario=norm))
                block.append(f"    {P_SCENARIO_ABSTRACT} {literal(best)} ;")

            # A region the model picked already exists in the OEKG under
            # its own IRI (oekg/region/Germany), so it is referenced, not
            # minted. Only a wording that matched nothing gets an IRI of ours,
            # and that one is a finding to review rather than a node to trust.
            # Only a region the model actually chose off the OEKG's list is
            # referenced, and it is ONLY referenced: the individual already
            # exists over there with its own type and its own label, so
            # asserting them again from a harvest writes our wording onto
            # somebody else's node — a second label on a maxCount-1 property,
            # caused on data this profile did not create.
            # Everything else — an out: entry, or a wording the list did not
            # hold — is counted and not minted. Minting put a German gloss
            # under oekg/region/ next to the 249 real ones.
            regions: dict = {}
            for row in rows_for("scenario_region", scenario=norm):
                if in_graph(row.get("value_uri")):
                    regions.setdefault(row["value_uri"], []).append(row)
            for region_iri, sources in regions.items():
                block += evidence_for(iri, P_STUDY_REGION, sources)
                block.append(f"    {P_STUDY_REGION} <{region_iri}> ;")

            years = sorted({re.search(r"\d{4}", str(r["value"])).group(0)
                            for r in rows_for("scenario_year", scenario=norm)
                            if re.search(r"\d{4}", str(r["value"]))})
            for year in years:
                block.append(f'    {P_SCENARIO_YEAR} '
                             f'"{year}-01-01T00:00:00"^^xsd:dateTime ;')
            block[-1] = block[-1].rstrip(" ;") + " ."
            scenario_nodes.append(NL.join(block) + NL)

        # ---- the bundle -----------------------------------------------------
        std: list = [f"<{bundle}>", f"    a oeo:{CLS_BUNDLE} ;",
                     f"    {P_UUID} {literal(uuid_of(bundle))} ;",
                     f"    {P_LABEL} "
                     f"{literal(chosen.get('study_project_name') or title)} ;"]
        if chosen.get("study_acronym"):
            std.append(f"    {P_ACRONYM} {literal(chosen['study_acronym'])} ;")
        if chosen.get("publication_abstract"):
            std += evidence_for(bundle, P_ABSTRACT,
                                rows_for("publication_abstract",
                                         value=chosen["publication_abstract"]))
            std.append(f"    {P_ABSTRACT} "
                       f"{literal(chosen['publication_abstract'])} ;")
        if org_links:
            std.append(f"    {P_ORGANISATION} " +
                       " ,\n        ".join(org_links) + " ;")
        if funder_links:
            std.append(f"    {P_FUNDER} " +
                       " ,\n        ".join(funder_links) + " ;")
        for part in [f"<{report}>"] + scenario_links:
            std.append(f"    {P_HAS_PART} {part} ;")
        std[-1] = std[-1].rstrip(" ;") + " ."

        log.info("kg: %s: 1 report, 1 bundle, %d scenario(s), %d author(s), "
                 "%d organisation(s), %d funder(s)%s%s%s%s%s%s", name,
                 len(scenario_links), len(author_links), len(org_links),
                 len(funder_links),
                 f", contested {contested}" if contested else "",
                 f", MISSING REQUIRED {missing}" if missing else "",
                 f", {len(unplaced)} scenario name(s) not in the AR6 list "
                 f"{unplaced[:5]}" if unplaced else "",
                 f", not in the graph by choice: {dict(out_of_graph)}"
                 if out_of_graph else "",
                 f", no scenario to hang them on: {dict(unplaceable)}"
                 if unplaceable else "",
                 f", {rescued} link(s) the list settled after the model gave up"
                 if rescued else "")

        parts = [NL.join(pub) + NL, NL.join(std) + NL]
        parts += scenario_nodes + author_nodes + org_nodes + funder_nodes
        parts += evidence_nodes
        body = NL.join(parts)
        if header_pending[0]:
            header_pending[0] = False
            return PREFIXES + "\n" + body
        return body

    return serializer
