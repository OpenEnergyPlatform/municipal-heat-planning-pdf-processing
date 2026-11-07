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
wrong and neither should find that out in production. What the PDF does not
print of DOI and year the run looks up in OpenAlex with the title and the
authors it read (`completion.py`); such a value names its record.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from docpipe.extraction import graphkit
from docpipe.extraction.compute import owner_of
from docpipe.extraction.graphkit import NOT_IN_GRAPH, ttl_comment, ttl_literal
from docpipe.extraction.identity import tuple_ids
from docpipe.extraction.shapemodel import (XSD, Model, SchemaError,
                                           snapshot_ancestors)
from docpipe.extraction.spec import kg_name, load as load_spec
from docpipe.extraction.trust import check_prose, render, trust
from docpipe.store.schema import readonly_uri
from profiles.scenarios.front import FRONT_FIELDS, front_pages, in_order

log = logging.getLogger(__name__)

# Where individuals live. The shapes only fix the ontology prefixes, so this
# was read off the running graph instead (13700 triples over the SPARQL
# endpoint): every collection below is the one the OEKG already uses for that
# class. Still to confirm with Mirjam is the *local part* — the OEKG's own
# UUIDs are random, ours are UUIDv5 over the identifying name so that two runs
# over one document mint one IRI and a re-run does not duplicate the graph.
BASE = os.environ.get("OEKG_ID_BASE", "https://openenergyplatform.org/ontology/oekg/")
NS_OEKG = graphkit.base_namespace(BASE)

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
OEO_BASE = "https://openenergyplatform.org/ontology/oeo/"


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


# The classes of the nodes this graph mints, read from the parameter that
# mints each. The three a shape targets are held to it (`bind`); the class at
# the end of an author, organisation or funder edge is the shape's own where
# it names one, and these three are what the spec says otherwise.
CLS_BUNDLE = _class("study_project_name")      # scenario bundle (StudyShape)
CLS_REPORT = _class("publication_title")       # study report (PublicationShape)
CLS_AUTHOR = _class("publication_author")      # author
CLS_ORGANISATION = _class("study_organisation")
CLS_FUNDER = _class("study_funder")
CLS_SCENARIO = _class("scenario_label")        # factsheet (ScenarioShape)
# Not minted here: the class the shapes require at the end of the study
# region edge where they name one, else this.
CLS_STUDY_REGION = "OEO_00020032"              # study region

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

# Behind no harvested value, so behind no parameter: a node carries a uuid
# where its shape has the path, because the OEKG mints them that way.
P_UUID = "oeo:OEO_00390095"        # has uuid

PREFIX_IRI = dict(re.findall(r"@prefix (\w+):\s*<([^>]+)>", PREFIXES))

# Where the names of the nodes this graph points at without minting them are,
# as the last refresh wrote them (vocabulary.py).
REGION_NAMES_PATH = Path(__file__).with_name("region_names.json")
SNAPSHOT_PATH = Path(__file__).with_name("vocabulary.json")


def node_names(regions: Path = REGION_NAMES_PATH,
               snapshot: Path = SNAPSHOT_PATH) -> dict:
    """{IRI: name} of every node this graph may point at without minting it:
    a region by the English short name LCC gives it, an OEO term by its
    label in the release the snapshot is pinned to. A file no refresh has
    written names nothing."""
    names: dict = {}
    if regions.is_file():
        names.update(json.loads(regions.read_text(encoding="utf-8")))
    if snapshot.is_file():
        terms = json.loads(snapshot.read_text(encoding="utf-8")).get(
            "terms") or {}
        names.update({OEO_BASE + key: term["label"]
                      for key, term in terms.items()
                      if key.startswith("OEO_") and term.get("label")})
    return names


def _bare(name: str) -> str:
    return str(name).split(":")[-1]


def _iri(name: str) -> str:
    """A qualified name of this graph, or a bare OEO id, as its IRI."""
    prefix, colon, local = str(name).partition(":")
    if not colon:
        return OEO_BASE + name
    if prefix not in PREFIX_IRI:
        raise KeyError(f"{name!r} is bound to no prefix of PREFIXES")
    return PREFIX_IRI[prefix] + local


def default_model():
    """The OEKG shapes of the last refresh, or SchemaError without one.

    A graph written without them is one nobody can say anything about, so
    there is no fallback to the paths this module would otherwise assume.
    """
    from profiles.scenarios import vocabulary
    paths = [path for path in vocabulary.shapes() if path.is_file()]
    if not paths:
        raise SchemaError("no OEKG shapes from a refresh, so no path to "
                          "write: python -m profiles.scenarios.vocabulary "
                          "--refresh")
    return Model.load(paths, ancestors=snapshot_ancestors(
        vocabulary.load(), OEO_BASE))


def edges() -> list:
    """The triple shapes this serializer writes that no `kg` block carries.

    `ontology.edge_problems` holds the rest of the output to the pinned
    ontology through the spec; without this the writer's own literals are the
    part nobody checks, which is where three of kwp's defects lived. The
    uuid is written where the shapes have its path, so without shapes from a
    refresh nothing is said about it.
    """
    try:
        uuid_on = bind(default_model()).uuid_on
    except SchemaError:
        return []
    return [{"where": "kg.py uuid", "subject": _bare(cls),
             "predicate": _bare(P_UUID), "datatype": "xsd:string"}
            for node, cls in _SHAPED.items() if node in uuid_on]

# Mirjam: "all IAM scenarios get the annotation for now". In the OEO since
# release 2.14.0, in the shape's sh:in list with the OEKG's shape update
# (oekg#68).
IAM_SCENARIO = "OEO_00020517"

# Scenario-scope fields: everything carrying a `scenario` axis, which names
# in the document's own words which scenario the value belongs to. Read from
# the spec, because a fifteenth parameter added there would otherwise be
# missing from four loops here and reach no factsheet, silently.
SCENARIO_FIELDS = tuple(
    parameter["uri"] for parameter in _SPEC["parameters"]
    if "scenario" in (parameter.get("axes") or {}))
# The tags of a bundle: what the study is about, which sector division it
# follows, which sectors and technologies it covers. Each is
# an entry of a list the shapes fix, so the object is an IRI the model chose
# and never a string it wrote. Read from the spec, for the reason SCENARIO_FIELDS is.
BUNDLE_TAGS = tuple(
    parameter["uri"] for parameter in _SPEC["parameters"]
    if parameter.get("value_type") == "category"
    and (parameter.get("kg") or {}).get("node") == "scenariobundle")

# The nodes a shape targets, by the name the spec gives them.
_SHAPED = {"studyreport": CLS_REPORT, "scenariobundle": CLS_BUNDLE,
           "scenariofactsheet": CLS_SCENARIO}
# The two a document has exactly one of. Which of their fields may occur once
# and which must occur is the shapes' to say; that a document has one report
# and one bundle is this serializer's structure.
DOCUMENT_NODES = ("studyreport", "scenariobundle")
# A field filled from another where the document gives none: the bundle is
# labelled with the title where no project is named, so it is never missing.
FALLBACK = {"study_project_name": "publication_title"}
# Every path a node of each shaped class is written with.
WRITTEN = {
    "studyreport": (P_LABEL, P_AUTHOR, P_PUBDATE, P_DOI),
    "scenariobundle": (P_LABEL, P_ACRONYM, P_ABSTRACT, P_ORGANISATION,
                       P_FUNDER, P_HAS_PART) + tuple(
                           _property(key) for key in BUNDLE_TAGS),
    "scenariofactsheet": (P_LABEL, P_SCENARIO_ACRONYM, P_SCENARIO_TYPE,
                          P_SCENARIO_ABSTRACT, P_STUDY_REGION,
                          P_SCENARIO_YEAR),
}
XSD_DATETIME = XSD + "dateTime"


def bind(model) -> SimpleNamespace:
    """What the shapes say about the graph this module writes.

    Every path WRITTEN names has to be a property of the shape its node is
    held to, and the two dates have to be the xsd:dateTime this module
    writes: a shapes file that dropped or retyped one stops the serializer
    here rather than in a report after the run. What is read off them:

      single    the per-document fields whose path the shapes allow once,
                so the harvest's several readings are settled to one
      required  the per-document fields the shapes demand, so a document
                that misses one is reported
      uuid_on   the shaped nodes whose shape has the uuid path
      author, organisation, funder, region
                the class at the end of each edge, where the shape names
                exactly one
    """
    for node, cls in _SHAPED.items():
        if model.shaped(OEO_BASE + cls) is None:
            raise SchemaError(f"no shape targets {cls}, the class of the "
                              f"{node} this graph writes")

    def slot(node: str, name: str, **narrow):
        return model.slot(OEO_BASE + _SHAPED[node], path=_iri(name), **narrow)

    for node, paths in WRITTEN.items():
        for name in paths:
            slot(node, name)
    for node, name in (("studyreport", P_PUBDATE),
                       ("scenariofactsheet", P_SCENARIO_YEAR)):
        datatype = slot(node, name).datatype
        if datatype and datatype != XSD_DATETIME:
            raise SchemaError(f"the shapes type {name} on the {node} as "
                              f"{datatype}; this serializer writes "
                              f"xsd:dateTime")
    for cls in (CLS_REPORT, CLS_SCENARIO):
        slot("scenariobundle", P_HAS_PART, to_class=OEO_BASE + cls)

    def end(name: str, node: str, fallback: str) -> str:
        # Bare, as every class of this graph is written `a oeo:<id>`.
        classes = slot(node, name).classes
        if len(classes) == 1 and classes[0].startswith(OEO_BASE):
            return classes[0][len(OEO_BASE):]
        return fallback

    single, required = [], []
    for parameter in _SPEC["parameters"]:
        block = parameter.get("kg") or {}
        if block.get("node") in DOCUMENT_NODES and block.get("property"):
            found = slot(block["node"], _name(block["property"]))
            if found.single:
                single.append(parameter["uri"])
            if found.required:
                required.append(parameter["uri"])
        edge = block.get("edge_from") or {}
        if edge.get("node") in DOCUMENT_NODES \
                and slot(edge["node"], _name(edge)).required:
            required.append(parameter["uri"])
    return SimpleNamespace(
        single=tuple(single), required=tuple(required),
        uuid_on=frozenset(node for node, cls in _SHAPED.items()
                          if model.has(OEO_BASE + cls, _iri(P_UUID))),
        author=end(P_AUTHOR, "studyreport", CLS_AUTHOR),
        organisation=end(P_ORGANISATION, "scenariobundle", CLS_ORGANISATION),
        funder=end(P_FUNDER, "scenariobundle", CLS_FUNDER),
        region=end(P_STUDY_REGION, "scenariofactsheet", CLS_STUDY_REGION))


_LEGAL = r"(gmbh|mbh|ag|kg|ohg|e\.?\s*v\.?|gbr|se|ug|inc|ltd|llc)"
NL = "\n"


def normalise(label: str) -> str:
    """One spelling for a name, so two writings of it mint one IRI."""
    return graphkit.normalise(str(label), _LEGAL)


def mint(collection: str, name: str) -> str:
    """UUIDv5 over the identifying name, folded by `normalise`. Never v4: two
    runs over one document must mint the same IRI."""
    segment = COLLECTIONS.get(collection, collection)
    prefix = f"{BASE}{segment}/" if segment else BASE
    return (f"{prefix}"
            f"{graphkit.mint_uuid(NS_OEKG, collection, normalise(name))}")


def uuid_of(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]


def _squeeze(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


# The choice lists in extraction.py carry entries that are deliberately not a
# thing in the graph: several regions the groups do not carry, something that
# is not a country. They exist so the model can say so instead of picking
# the nearest entry that is almost right — which means every place where an
# answer turns into an IRI, a type or a link has to refuse them. One prefix
# (NOT_IN_GRAPH, graphkit.py), checked once here, so a new out: entry cannot
# quietly become a node.
def in_graph(value) -> bool:
    """Is this answer something the graph takes, or one of the out: entries?"""
    return bool(value) and not str(value).startswith(NOT_IN_GRAPH)


# A chosen group of countries: the world, a region of the IAM models, of the
# UN or of the World Bank (vocabulary.aggregates). The OEKG holds countries
# only.
AGGREGATE = "aggregate:"


def region_members(value, groups: dict) -> list:
    """The OEKG regions a scenario_region answer stands for: a country is
    itself, a group its members, an out: entry none."""
    if str(value or "").startswith(AGGREGATE):
        return list((groups.get(value) or {}).get("members") or ())
    return [value] if in_graph(value) else []


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


def _quoted(name, quote) -> bool:
    """Does the passage a name was read from actually contain it?

    A string the model presents as the document's own name for a scenario
    has to be findable in the quote it was read with. It used to mint a
    factsheet anyway, with a stable IRI and the invented string as its label.
    """
    if quote is None:
        # Nothing to check against. The verifier guarantees a quote on every
        # tuple that reaches here, so this is the unit-test shape, and a check
        # that cannot run must not reject.
        return True
    return _squeeze(name) in _squeeze(quote)


def scenario_names(row: dict) -> list:
    """The names of the scenarios a row belongs to.

    A scenario_label row names one by its value, any other row by its
    `scenario` coordinate, both as the publication prints them. Which of a
    publication's names mean the same scenario was asked once it was read
    (`value_means`, `scenario_means`, docpipe/extraction/naming.py): a name
    of one scenario means the name that scenario is called by, a name of
    several scenarios means each of theirs (owner decisions 2026-11-06). A
    row read before that was asked belongs to the scenario of its own name.
    """
    if row.get("parameter") == "scenario_label":
        name, quote, means = (row.get("value"), row.get("quote"),
                              row.get("value_means"))
    else:
        name, quote, means = (row.get("scenario"),
                              row.get("scenario_quote", row.get("quote")),
                              row.get("scenario_means"))
    # An out: entry, such as "status quo" for a value of a past or the
    # current year (owner decision 2026-11-07), belongs to no scenario.
    if not isinstance(name, str) or not name.strip() or not in_graph(name) \
            or not _quoted(name, quote):
        return []
    if isinstance(means, list):
        named = [one for one in means if isinstance(one, str) and one.strip()]
        if named:
            return list(dict.fromkeys(named))
    return [name.strip()]


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
    """Say it out loud when the graph's value and the crawl disagree."""
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
            log.warning("kg: %s: the graph's %s is %r, the crawl says %r",
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

# This corpus has no transcribed pages to declare: its Documents table carries
# no page_text_transcribed column, so `trust` is never told a page was itself
# a reading. Named here so the missing argument is a fact and not an
# oversight -- if that column ever arrives, this is where it is read.
PAGE_TRANSCRIBED = False


def _ttl_comment(text) -> str:
    """One comment line at the indent this graph's nodes carry."""
    return ttl_comment(text, indent="    ")


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
    elif row.get("reading"):
        # No text states the value: what was read off the figure stands
        # where the quote would (owner decision 2026-11-07).
        lines.append(_ttl_comment(f"Read off the figure: {row['reading']}"))
    lines.append(_ttl_comment(", ".join(where)))
    if row.get("flags"):
        lines.append(_ttl_comment("flags: " + ", ".join(row["flags"])))
    return lines


def _catalogue_text(record: dict) -> str:
    """The catalogue record a looked-up value stands on, as one line
    (`completion.py`)."""
    by = {"doi": " by the DOI it prints", "index_doi": " by the corpus index's DOI",
          "title": " by its title"}.get(record.get("key"), "")
    said = [f"looked up in {record.get('source')}{by}: {record.get('id')}"]
    if record.get("publication_date"):
        said.append(f"published {record['publication_date']}")
    if record.get("matched"):
        said.append("authors matched: " + ", ".join(record["matched"]))
    return ", ".join(said)


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
            f"    oekgprov:extractedValue {ttl_literal(shown)} ;",
            f"    oekgprov:quote {ttl_literal(row.get('quote') or '')} ;",
            f"    oekgprov:sourceDocument {ttl_literal(document)} ;",
            f"    oekgprov:evidenceTier {ttl_literal(row.get('tier') or '')} ;"]
    if provenance.get("page"):
        node.append(f'    oekgprov:page "{int(provenance["page"])}"^^xsd:integer ;')
    for rect in provenance.get("rects") or ():
        node.append("    oekgprov:region "
                    f"{ttl_literal(' '.join(str(round(v, 2)) for v in rect))} ;")
    node[-1] = node[-1].rstrip(" ;") + " ."
    return (f"    oekgprov:hasEvidence <{iri}> ;",
            NL.join(node) + NL)


def _make_builder(db_path: Path, model=None, groups: Optional[dict] = None,
                  names: Optional[dict] = None):
    """(document name, accepted tuple rows) -> (TTL body, study) or None.

    *model* is the shapes the graph is written to (`shapemodel.Model`),
    those of the last refresh when none is given; `bind` reads off them what
    the builder needs and refuses a shapes file it cannot write to. *groups*
    are the groups of countries a region answer may name, *names* the names
    of the nodes the graph points at without minting them (`node_names`),
    both those of the last refresh when none are given.

    One reading of a document's harvest and two things written from it: the
    Turtle, and `study`, the same decisions as plain data. The second is for
    a writer that is not Turtle (oekg_api.py builds the platform's request
    body from it). Both come out of one pass, so which title won, which
    spellings are one author and which rows are one scenario is decided once.
    """
    # A preprint and its journal version share a title, so they mint the same
    # study report and the same bundle. The single-valued triples are then
    # written twice into one file, with two dates and two abstracts on one
    # subject, and each document's own log says "1 report, 1 bundle".
    if groups is None:
        from profiles.scenarios.extraction import aggregates
        groups = aggregates()
    if names is None:
        names = node_names()
    # The nodes of others this file has described: once per file.
    told: set = set()
    minted: dict = {}
    # A node several documents describe is one node of the file. The value
    # the first of them gave a single-valued property is the node's, and a
    # later document's other reading goes unwritten with its evidence: an
    # author spelt "Sergey Paltsev" and "SERGEY PALTSEV", or one project's
    # bundle with two papers' abstracts, otherwise carried two labels or two
    # abstracts on a maxCount-1 path.
    settled: dict = {}

    def settles(subject: str, predicate: str, value) -> bool:
        """Whether *value* is what this file says for the single-valued
        *predicate* of *subject*: the first to say it, or the same again."""
        held = settled.setdefault((subject, predicate), value)
        if held != value:
            log.info("kg: <%s> %s stays %r, a later document read %r",
                     subject, predicate, held, value)
        return held == value

    bound = bind(model if model is not None else default_model())

    def build(name: str, rows: list, decided: Optional[dict] = None):
        # What people decided about this document's rows, by the name a row
        # has in its document (`gold.decisions_in`), kept by the row itself:
        # each goes above the value its row backs, and none changes it.
        asked: dict = {}
        recorded: set = set()
        if decided:
            for tuple_name, row in zip(tuple_ids(name, rows), rows):
                if tuple_name in decided:
                    asked[id(row)] = decided[tuple_name]
        by_param: dict = {}
        for row in rows:
            by_param.setdefault(row.get("parameter"), []).append(row)

        # What the model said does NOT belong in the graph. Counted once, here,
        # so the number is a measurement of the corpus rather than a side
        # effect of whichever loop happened to look at the row: a run of
        # publications that is 80% out:multiregion is telling us the groups
        # of countries are missing one, not that the harvest is failing.
        out_of_graph: Counter = Counter()
        for row in rows:
            for field in ("value_uri", "scenario"):
                if str(row.get(field) or "").startswith(NOT_IN_GRAPH):
                    out_of_graph[row[field]] += 1
        for key in ("scenario_label", "scenario_region",
                    "scenario_type") + BUNDLE_TAGS:
            for row in by_param.get(key, ()):
                if not row.get("value_uri"):
                    # Verified, quoted, located — and it reaches no triple,
                    # because the list held nothing for it and the model chose
                    # no out: entry either. Without this the gap on a field
                    # reads as zero after a corpus run.
                    out_of_graph[f"unmapped:{key}"] += 1

        chosen: dict = {}
        contested: dict = {}
        # What a publication says of itself: a reading on its front pages
        # goes first, then the catalogue's record, then any other reading,
        # however often that was read (owner decisions 2026-11-05,
        # `front.py`).
        front = front_pages(by_param.get("publication_title", ()))
        for key in bound.single:
            if by_param.get(key):
                offered = by_param[key]
                if key in FRONT_FIELDS:
                    offered = in_order(offered, front)
                chosen[key], others = _pick_one(offered)
                if others:
                    contested[key] = others

        missing = [k for k in bound.required
                   if not (chosen.get(k) or by_param.get(k)
                           or chosen.get(FALLBACK.get(k)))]
        if "publication_title" not in chosen:
            log.info("kg: %s: no title extracted — nothing to serialize", name)
            return None

        # A diagnostic, never a precondition: the graph does not depend on the
        # crawl, so an unreachable DocumentMeta must not stop the serialization.
        conn = None
        try:
            # `with sqlite3.connect(...)` commits a transaction, it does not
            # close the connection — one leaked handle per document, and on
            # Windows a file nobody can delete afterwards.
            conn = sqlite3.connect(readonly_uri(db_path), uri=True)
            _crosscheck(conn, name, chosen)
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
            Each line is marked confirmed where a second passage prints the
            value; one passage read twice is one statement, whatever its
            quotes (owner decision 2026-11-05, as kwp's settle).
            """
            lines = []
            confirmed = len({owner_of(row) for row in sources}) > 1
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
                                conflict=bool(contested.get(row.get("parameter"))),
                                corroborated=confirmed)
                lines.append(_ttl_comment(render(verdict, TRUST_PROSE,
                                                 join=TRUST_JOIN, row=row)))
                # A value looked up outside the document names its record on
                # both branches: its quote is the title it was looked up with.
                if isinstance(row.get("catalogue"), dict):
                    lines.append(_ttl_comment(_catalogue_text(
                        row["catalogue"])))
                for decision in asked.get(id(row), ()):
                    lines.append(_ttl_comment(decision_text(decision)))
                    recorded.add(id(row))
            return lines

        def rows_for(key: str, value=None, scenario=None) -> list:
            out = []
            for row in by_param.get(key, ()):
                if value is not None and row.get("value") != value:
                    continue
                if scenario is not None and scenario not in {
                        normalise(one) for one in scenario_names(
                            dict(row, parameter=key))}:
                    continue
                out.append(row)
            return out

        def entities(key: str, collection: str, cls: str,
                     taken: Optional[list] = None) -> tuple:
            """Distinct named things of one kind, each as its own node: the
            names of *taken* where given, else of every row of *key*."""
            # Group by the normalised name, but keep every row: "Oeko-Institut"
            # and "Oeko-Institut e.V." are one node, and filtering the evidence
            # by the winning spelling afterwards threw the other one's passage
            # away — the page where the second spelling stands vanished from
            # the file entirely. A name taken keeps every row that reads it
            # as its evidence, its spelling the first taken row's.
            every = by_param.get(key, ())
            taken = list(every) if taken is None else taken
            names = {normalise(row["value"]) for row in taken}
            groups: dict = {}
            for row in taken + [row for row in every
                                if not any(row is one for one in taken)
                                and normalise(row["value"]) in names]:
                groups.setdefault(normalise(row["value"]),
                                  (row["value"], []))[1].append(row)
            links, nodes, labels = [], [], []
            for label, sources in groups.values():
                iri = mint(collection, label)
                label = settled.setdefault((iri, P_LABEL), label)
                links.append(f"<{iri}>")
                labels.append(label)
                block = [f"<{iri}>", f"    a oeo:{cls} ;"]
                block += evidence_for(iri, P_LABEL, sources)
                block.append(f"    {P_LABEL} {ttl_literal(label)} .")
                nodes.append(NL.join(block) + NL)
            return links, nodes, labels

        # The authors the front pages name, else the catalogue's, else those
        # read anywhere: a chapter on other studies names their authors.
        author_links, author_nodes, author_labels = entities(
            "publication_author", "author", bound.author,
            in_order(by_param.get("publication_author", ()), front))
        org_links, org_nodes, org_labels = entities(
            "study_organisation", "organisation", bound.organisation)
        funder_links, funder_nodes, funder_labels = entities(
            "study_funder", "funder", bound.funder)

        # ---- the study report ---------------------------------------------
        pub: list = [f"<{report}>", f"    a oeo:{CLS_REPORT} ;"]
        if "studyreport" in bound.uuid_on:
            pub.append(f"    {P_UUID} {ttl_literal(uuid_of(report))} ;")
        if settles(report, P_LABEL, title):
            pub += evidence_for(report, P_LABEL,
                                rows_for("publication_title", value=title))
            pub.append(f"    {P_LABEL} {ttl_literal(title)} ;")
        if author_links:
            pub.append(f"    {P_AUTHOR} " +
                       " ,\n        ".join(author_links) + " ;")
        stamp = ""
        if chosen.get("publication_date"):
            stamp = _publication_date(chosen["publication_date"])
            if stamp and settles(report, P_PUBDATE, stamp):
                pub += evidence_for(
                    report, P_PUBDATE,
                    rows_for("publication_date",
                             value=chosen["publication_date"]))
                pub.append(f'    {P_PUBDATE} "{stamp}"^^xsd:dateTime ;')
        if chosen.get("publication_doi") \
                and settles(report, P_DOI, chosen["publication_doi"]):
            pub += evidence_for(report, P_DOI,
                                rows_for("publication_doi",
                                         value=chosen["publication_doi"]))
            pub.append(f"    {P_DOI} {ttl_literal(chosen['publication_doi'])} ;")
        pub[-1] = pub[-1].rstrip(" ;") + " ."

        # ---- the scenarios --------------------------------------------------
        # A scenario is named by scenario_label, or by any scenario-scope value
        # that says which scenario it belongs to, both in the publication's
        # own words, each by the name of the scenario it means
        # (`scenario_names`).
        # A scenario-scope value whose own `scenario` coordinate never came
        # back has nothing to hang on, and until this counter it left the file
        # without a triple, a comment or a number: the value itself resolved,
        # so `out_of_graph` cannot see it, and `rows_for` simply never matches
        # it. Measured over a 164-document harvest, 298 of 11.129
        # scenario-scope tuples -- 289 of them `exhausted`, which is a finding
        # about this run's window budget and not about the papers, and 9
        # `unstated`, which is the opposite. Thrown together they say nothing,
        # so the state is what the count is keyed on.
        unplaceable: Counter = Counter()
        wanted: dict = {}
        for key in ("scenario_label",) + SCENARIO_FIELDS:
            for row in by_param.get(key, ()):
                named = scenario_names(dict(row, parameter=key))
                for one in named:
                    wanted.setdefault(normalise(one), one)
                # One whose scenario is an out: entry belongs to none by
                # choice and is counted there (`out_of_graph`).
                if not named and key != "scenario_label" \
                        and not str(row.get("scenario") or "").startswith(
                            NOT_IN_GRAPH):
                    state = row.get("scenario_state") or "missing"
                    unplaceable[f"{key}:{state}"] += 1

        scenario_links: list = []
        scenario_nodes: list = []
        scenarios: list = []
        for norm, ident in wanted.items():
            iri = mint("scenariofactsheet", f"{title}|{ident}")
            scenario_links.append(f"<{iri}>")
            block = [f"<{iri}>", f"    a oeo:{CLS_SCENARIO} ;"]
            if "scenariofactsheet" in bound.uuid_on:
                block.append(f"    {P_UUID} {ttl_literal(uuid_of(iri))} ;")
            if settles(iri, P_LABEL, ident):
                block += evidence_for(iri, P_LABEL,
                                      rows_for("scenario_label", scenario=norm))
                # Mirjam: with no long name beside the acronym, both carry the
                # same string. That is the usual case in this corpus.
                block.append(f"    {P_LABEL} {ttl_literal(ident)} ;")
            if settles(iri, P_SCENARIO_ACRONYM, ident):
                block.append(f"    {P_SCENARIO_ACRONYM} {ttl_literal(ident)} ;")

            # The types the model chose from the shapes' own list, each with
            # the passage it read them in. On top of that Mirjam asks every IAM
            # scenario to carry OEO_00020517 (IAM_SCENARIO).
            types: dict = {}
            for row in rows_for("scenario_type", scenario=norm):
                if in_graph(row.get("value_uri")):
                    types.setdefault(row["value_uri"], []).append(row)
            for type_iri, sources in types.items():
                block += evidence_for(iri, P_SCENARIO_TYPE, sources)
                block.append(f"    {P_SCENARIO_TYPE} <{type_iri}> ;")
            block.append(f"    {P_SCENARIO_TYPE} oeo:{IAM_SCENARIO} ;")

            described = rows_for("scenario_abstract", scenario=norm)
            best = None
            if described:
                best, _ = _pick_one(described)
            if best is not None and settles(iri, P_SCENARIO_ABSTRACT, best):
                block += evidence_for(iri, P_SCENARIO_ABSTRACT,
                                      rows_for("scenario_abstract", value=best,
                                               scenario=norm))
                block.append(f"    {P_SCENARIO_ABSTRACT} {ttl_literal(best)} ;")

            # A region the model picked already exists in the OEKG under
            # its own IRI (oekg/region/Germany), so it is referenced, not
            # minted, and described below by the name LCC gives it, never by
            # the harvest's wording. Everything else — an out: entry, or a
            # wording the list did not hold — is counted and not minted.
            # Minting put a German gloss under oekg/region/ next to the 249
            # real ones. A group of countries is written as its members, and
            # its passage is cited once, above the first of them.
            regions: dict = {}
            for row in rows_for("scenario_region", scenario=norm):
                for region_iri in region_members(row.get("value_uri"),
                                                 groups):
                    regions.setdefault(region_iri, []).append(row)
            cited: set = set()
            for region_iri, sources in regions.items():
                new = [row for row in sources if id(row) not in cited]
                cited.update(id(row) for row in new)
                block += evidence_for(iri, P_STUDY_REGION, new)
                block.append(f"    {P_STUDY_REGION} <{region_iri}> ;")

            years = sorted({re.search(r"\d{4}", str(r["value"])).group(0)
                            for r in rows_for("scenario_year", scenario=norm)
                            if re.search(r"\d{4}", str(r["value"]))})
            for year in years:
                block.append(f'    {P_SCENARIO_YEAR} '
                             f'"{year}-01-01T00:00:00"^^xsd:dateTime ;')
            block[-1] = block[-1].rstrip(" ;") + " ."
            scenario_nodes.append(NL.join(block) + NL)
            scenarios.append({
                "label": ident, "acronym": ident,
                "abstract": best,
                "types": list(types) + [OEO_BASE + IAM_SCENARIO],
                "regions": list(regions),
                "years": [f"{year}-01-01T00:00:00" for year in years]})

        # ---- the bundle -----------------------------------------------------
        std: list = [f"<{bundle}>", f"    a oeo:{CLS_BUNDLE} ;"]
        if "scenariobundle" in bound.uuid_on:
            std.append(f"    {P_UUID} {ttl_literal(uuid_of(bundle))} ;")
        if settles(bundle, P_LABEL, chosen.get("study_project_name") or title):
            std.append(f"    {P_LABEL} "
                       f"{ttl_literal(chosen.get('study_project_name') or title)} ;")
        if chosen.get("study_acronym") \
                and settles(bundle, P_ACRONYM, chosen["study_acronym"]):
            std.append(f"    {P_ACRONYM} {ttl_literal(chosen['study_acronym'])} ;")
        if chosen.get("publication_abstract") and settles(
                bundle, P_ABSTRACT, chosen["publication_abstract"]):
            std += evidence_for(bundle, P_ABSTRACT,
                                rows_for("publication_abstract",
                                         value=chosen["publication_abstract"]))
            std.append(f"    {P_ABSTRACT} "
                       f"{ttl_literal(chosen['publication_abstract'])} ;")
        if org_links:
            std.append(f"    {P_ORGANISATION} " +
                       " ,\n        ".join(org_links) + " ;")
        if funder_links:
            std.append(f"    {P_FUNDER} " +
                       " ,\n        ".join(funder_links) + " ;")
        # Only an entry the model picked off the list is written, as with a
        # scenario type: an out: entry and a wording the list did not hold
        # are counted above and reach no triple.
        tags: dict = {}
        for key in BUNDLE_TAGS:
            picked: dict = {}
            for row in by_param.get(key, ()):
                if in_graph(row.get("value_uri")):
                    picked.setdefault(row["value_uri"], []).append(row)
            for tag_iri, sources in picked.items():
                std += evidence_for(bundle, _property(key), sources)
                std.append(f"    {_property(key)} <{tag_iri}> ;")
            tags[key] = list(picked)
        for part in [f"<{report}>"] + scenario_links:
            std.append(f"    {P_HAS_PART} {part} ;")
        std[-1] = std[-1].rstrip(" ;") + " ."

        log.info("kg: %s: 1 report, 1 bundle, %d scenario(s), %d author(s), "
                 "%d organisation(s), %d funder(s)%s%s%s%s", name,
                 len(scenario_links), len(author_links), len(org_links),
                 len(funder_links),
                 f", contested {contested}" if contested else "",
                 f", MISSING REQUIRED {missing}" if missing else "",
                 f", not in the graph by choice: {dict(out_of_graph)}"
                 if out_of_graph else "",
                 f", no scenario to hang them on: {dict(unplaceable)}"
                 if unplaceable else "")
        left = {key: found for key, found in asked.items()
                if key not in recorded}
        if left:
            # Decided, and the row backs no triple: it lost a single-valued
            # field to another reading, or its scenario is none.
            log.info("kg: %s: %d decision(s) on %d row(s) concern no value "
                     "of the graph", name,
                     sum(len(found) for found in left.values()), len(left))

        # The nodes the graph points at and does not mint, each described
        # once per file (OEKG team, 2026-11-04): a region by the class the
        # shapes require at the end of its edge and the name LCC gives it, an
        # OEO term by its label in the pinned release, without a language
        # tag. A node its source does not name gets no label of ours.
        pointed: dict = {}
        for scenario in scenarios:
            for region_iri in scenario["regions"]:
                pointed.setdefault(region_iri, bound.region)
            for type_iri in scenario["types"]:
                pointed.setdefault(type_iri, None)
        for found in tags.values():
            for tag_iri in found:
                pointed.setdefault(tag_iri, None)
        node_blocks, nameless = [], []
        for node, cls in pointed.items():
            if node in told:
                continue
            told.add(node)
            lines = [f"<{node}>"] + ([f"    a oeo:{cls} ;"] if cls else [])
            if names.get(node):
                lines.append(f"    {P_LABEL} {ttl_literal(names[node])} ;")
            else:
                nameless.append(node)
            if len(lines) > 1:
                lines[-1] = lines[-1].rstrip(" ;") + " ."
                node_blocks.append(NL.join(lines) + NL)
        if nameless:
            log.warning("kg: %s: %d node(s) the graph points at have no name "
                        "in their source and no label: %s", name,
                        len(nameless), nameless[:5])

        parts = [NL.join(pub) + NL, NL.join(std) + NL]
        parts += scenario_nodes + author_nodes + org_nodes + funder_nodes
        parts += node_blocks
        parts += evidence_nodes
        study = {
            "document": name,
            "bundle": {"label": chosen.get("study_project_name") or title,
                       "acronym": chosen.get("study_acronym"),
                       "abstract": chosen.get("publication_abstract"),
                       "organisations": org_labels, "funders": funder_labels,
                       "tags": tags},
            "report": {"label": title, "authors": author_labels,
                       "publication_date": stamp or None,
                       "doi": chosen.get("publication_doi")},
            "scenarios": scenarios,
        }
        return NL.join(parts), study

    return build


def make_serializer(db_path: Path, model=None, groups: Optional[dict] = None,
                    names: Optional[dict] = None):
    """(document name, accepted tuple rows) -> TTL string or None.

    Written to *model*, the shapes of the last refresh by default, with the
    *groups* and *names* of the last refresh by default (`_make_builder`).

    What people decided about the rows is left in `serializer.decisions` by
    `serialize.run`, {document: {tuple name: [decision]}}, and goes into the
    Turtle as comment lines above the value each concerns.
    """
    build = _make_builder(db_path, model, groups, names)
    header_pending = [True]

    def serializer(name: str, rows: list):
        built = build(name, rows, serializer.decisions.get(name))
        if built is None:
            return None
        if header_pending[0]:
            header_pending[0] = False
            return PREFIXES + "\n" + built[0]
        return built[0]

    serializer.decisions = {}
    return serializer


def make_study_reader(db_path: Path, model=None):
    """(document name, accepted tuple rows) -> study dict or None.

    What the serializer decided for one document, without the Turtle: the
    bundle, its one study report and its scenarios, each value as the graph
    carries it. A document with no title has no study, as it has no graph.
    """
    build = _make_builder(db_path, model)

    def reader(name: str, rows: list):
        built = build(name, rows)
        return built[1] if built else None

    return reader
