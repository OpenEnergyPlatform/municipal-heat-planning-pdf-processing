"""
kg.py: The bricks only the scenarios profile's graph needs.

How the harvest of a publication becomes the OEKG graph is the drawing in
graph.json beside this file (`map`), written by the core's program
(`docpipe/extraction/graph.py`). Here are the pieces of it that only this
profile has: which scenarios a row names, the short name of a scenario, the
regions a region answer stands for, the names of the nodes the graph points
at without making them, the cross-check against the crawl, and `study`, the
same decisions as plain data for the OEKG API body (`oekg_api.py`).

The passages of every value are Turtle comments above the triple by default
(the shapes are sh:closed); the rule `evidence_as` of graph.json writes one
`oekgprov:ExtractionEvidence` node per value instead, linked with
`oekgprov:hasEvidence`, knowingly ahead of the shapes.

Author: Felix Vossel
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from docpipe import graphfile
from docpipe.extraction.addressed import SEVERAL
from docpipe.extraction.bricks import Brick, Call, Setting, in_graph, literal
from docpipe.extraction.graphkit import NOT_IN_GRAPH
from docpipe.extraction.shapemodel import Model, SchemaError, \
    snapshot_ancestors
from docpipe.store.schema import readonly_uri

log = logging.getLogger(__name__)

OEO_BASE = "https://openenergyplatform.org/ontology/oeo/"

# Where the names of the nodes this graph points at without making them
# are, as the last refresh wrote them (vocabulary.py).
REGION_NAMES_PATH = Path(__file__).with_name("region_names.json")
SNAPSHOT_PATH = Path(__file__).with_name("vocabulary.json")

# A chosen group of countries: the world, a region of the IAM models, of the
# UN or of the World Bank (vocabulary.aggregates). The OEKG holds countries
# only.
AGGREGATE = "aggregate:"

# The two entries a region answer takes where the list holds no class for
# the region the document names (`beside` of scenario_region in the spec): a
# group none of the groups carries, and any other region. Such a region is
# its own study region node, named as the document prints it (owner
# decision 2026-11-07).
UNLISTED_REGION = ("out:multiregion", "out:other")


def node_names(regions: Path = REGION_NAMES_PATH,
               snapshot: Path = SNAPSHOT_PATH) -> dict:
    """{IRI: name} of every node this graph may point at without making
    it: a region by the English short name LCC gives it, an OEO term by its
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


def default_model():
    """The OEKG shapes of the last refresh, or SchemaError without one."""
    from profiles.scenarios import vocabulary
    paths = [path for path in vocabulary.shapes() if path.is_file()]
    if not paths:
        raise SchemaError("no OEKG shapes from a refresh: python -m "
                          "profiles.scenarios.vocabulary --refresh")
    return Model.load(paths, ancestors=snapshot_ancestors(
        vocabulary.load(), OEO_BASE))


_MODEL: list = []


def has_property(klass: str, prop: str) -> Optional[bool]:
    """Whether the OEKG shapes give the class (a curie) the property (a
    curie); None where no shape targets the class, or there are no shapes
    from a refresh."""
    prefixes = graphfile.get_map("scenarios").get("prefixes") or {}

    def full(name: str) -> str:
        prefix, _, local = str(name).partition(":")
        return prefixes.get(prefix, prefix + ":") + local

    if not _MODEL:
        try:
            _MODEL.append(default_model())
        except SchemaError:
            _MODEL.append(None)
    model = _MODEL[0]
    if model is None or model.shaped(full(klass)) is None:
        return None
    return model.has(full(klass), full(prop))


def context(db_path=None) -> dict:
    """What the bricks of this profile share while a graph is written: the
    groups of countries a region answer may name and the names of the nodes
    the graph points at."""
    from profiles.scenarios.extraction import aggregates
    return {"groups": aggregates(), "names": node_names()}


def printed_region(row: dict) -> Optional[str]:
    """The name of a study region the list did not carry, as the row's
    document prints it (`value_raw`); None for any other row."""
    raw = str(row.get("value_raw") or "").strip()
    if row.get("value_uri") in UNLISTED_REGION and raw:
        return raw
    return None


def region_members(value, groups: dict) -> list:
    """The OEKG regions a region answer stands for: a country is itself, a
    group its members, an out: entry none."""
    if str(value or "").startswith(AGGREGATE):
        return list((groups.get(value) or {}).get("members") or ())
    return [value] if in_graph(value) else []


def _squeeze(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


def _quoted(name, quote) -> bool:
    """Does the passage a name was read from contain it?"""
    if quote is None:
        # Nothing to check against: the verifier guarantees a quote on
        # every tuple that reaches here, and a check that cannot run must
        # not reject.
        return True
    return _squeeze(name) in _squeeze(quote)


def scenario_names(row: dict, name_in_quote: bool = True) -> list:
    """The names of the scenarios a row belongs to.

    A scenario_label row names one by its value, any other row by its
    `scenario` coordinate, both as the publication prints them. Which entry
    of the publication's list of scenarios a name is was asked while it was
    read (`value_means`, `scenario_means`, owner decisions 2026-11-08): a
    name means the entry it is, the words of a group of scenarios each
    member, and words found to name no scenario (an empty list) none (owner
    decision 2026-11-09). With *name_in_quote* a name the publication's
    passage does not print names nothing.
    """
    if row.get("parameter") == "scenario_label":
        name, quote, means = (row.get("value"), row.get("quote"),
                              row.get("value_means"))
    else:
        name, quote, means = (row.get("scenario"),
                              row.get("scenario_quote", row.get("quote")),
                              row.get("scenario_means"))
    if name == SEVERAL:
        return list(dict.fromkeys(
            one for one in means if isinstance(one, str) and one.strip())) \
            if isinstance(means, list) else []
    if not isinstance(name, str) or not name.strip() or not in_graph(name) \
            or (name_in_quote and not _quoted(name, quote)):
        return []
    if isinstance(means, list):
        return list(dict.fromkeys(
            one for one in means if isinstance(one, str) and one.strip()))
    return [name.strip()]


# -- the bricks ----------------------------------------------------------------

def _names(call: Call) -> list:
    return scenario_names(call.row, bool(call.settings.get("name_in_quote",
                                                           True)))


def _short_name(call: Call) -> list:
    shorts = [row for row in call.rows if row.get("value_short")]
    acronym = shorts[0]["value"] if shorts else call.node.name
    return [(literal(acronym), acronym,
             [row for row in shorts if row["value"] == acronym])]


def _region(call: Call) -> list:
    names = call.doc.extra.setdefault("names", {})
    printed = printed_region(call.row)
    if printed:
        place = call.settings.get("unlisted") or {}
        iri = call.doc.mint(place.get("folder", "region"),
                            place.get("key", "studyregion"),
                            call.doc.fold(printed))
        names.setdefault(iri, printed)
        return [(f"<{iri}>", iri)]
    return [(f"<{iri}>", iri) for iri in region_members(
        call.row.get("value_uri"), call.doc.extra.get("groups") or {})]


def _known_name(call: Call) -> list:
    name = (call.doc.extra.get("names") or {}).get(call.node.iri)
    if not name:
        call.doc.count("nameless")
        return []
    return [(literal(name), name)]


def _crosscheck(call: Call) -> None:
    """Say it out loud when the graph's value and the crawl disagree. A
    diagnostic, never a precondition: an unreachable database stops
    nothing."""
    doc = call.doc
    db_path = doc.writer.db_path
    if db_path is None:
        return
    conn = None
    try:
        conn = sqlite3.connect(readonly_uri(db_path), uri=True)
        row = conn.execute(
            "SELECT m.title, m.year, m.doi FROM DocumentMeta m "
            "JOIN Documents d ON m.document = d.id "
            "WHERE d.filename LIKE ?", (f"{doc.name}.%",)).fetchone()
    except sqlite3.Error as exc:
        log.warning("graph: %s: no cross-check against the crawl (%s)",
                    doc.name, exc)
        return
    finally:
        if conn is not None:
            conn.close()
    if row is None:
        return
    for key, crawled in zip(call.settings.get("fields") or (), row):
        got = doc.picked(key)
        if got and crawled and doc.fold(got) != doc.fold(crawled):
            log.warning("graph: %s: the graph's %s is %r, the crawl says %r",
                        doc.name, key, got, crawled)


BRICKS = (
    Brick("scenario_names", "nodes",
          "Names the scenarios a row belongs to: a scenario's name by its "
          "value, any other row by its scenario dimension, in the words the "
          "publication prints; the words of several scenarios name each of "
          "them, an out: entry none.", "a reading", "names", _names,
          (Setting("name_in_quote", "flag", "a name counts only where the "
                   "passage it was read from prints it", True),)),
    Brick("short_name", "object",
          "Writes the short name the publication prints for the scenario, "
          "else its name.", "the readings of a scenario's name", "a text",
          _short_name, per="node"),
    Brick("region", "object",
          "Writes the regions a region answer stands for: a country itself, "
          "a group its members, a region the list does not carry a study "
          "region of its own named as the document prints it.",
          "a reading of a region", "addresses", _region,
          (Setting("unlisted", "table", "where a region the list does not "
                   "carry is made: folder and key"),)),
    Brick("known_name", "object",
          "Writes the name the last refresh gives a node the graph points "
          "at (a region by the name LCC gives it, an OEO term by its "
          "label); a node without one gets none.", "a node", "a text",
          _known_name, per="node"),
    Brick("crawl_crosscheck", "check",
          "Says in the log where the title, year or DOI the graph takes "
          "differs from the crawl's record of the document.", "a document",
          "nothing", _crosscheck,
          (Setting("fields", "fields", "the fields held to the crawl's "
                   "title, year and DOI"),)),
)


# -- the study, for the OEKG API body ------------------------------------------

def study_of(written) -> dict:
    """What the drawing decided for one document, as plain data: the bundle,
    its one study report and its scenarios, each value as the graph carries
    it (`oekg_api.py` builds the platform's request body from it)."""
    doc = written.doc
    report = written.nodes["report"][0]
    bundle = written.nodes["bundle"][0]

    def labels(box: str, field: str) -> list:
        return [value for node in written.nodes.get(box) or ()
                for value in written.values(node, field)]

    stamp = written.values(report, "publication_date")
    scenarios = []
    names = doc.extra.get("names") or {}
    for node in written.nodes.get("scenario") or ():
        regions = written.values(node, "scenario_region")
        abstract = written.values(node, "scenario_abstract")
        scenarios.append({
            "label": node.name,
            "acronym": (written.values(node, "scenario_label",
                                       prop="dc:acronym") or [None])[0],
            "abstract": abstract[0] if abstract else None,
            "types": written.values(node, "scenario_type")
            + written.values(node, "scenario"),
            "regions": regions,
            "region_names": {region: names[region] for region in regions
                             if names.get(region)},
            "years": written.values(node, "scenario_year")})
    return {
        "document": doc.name,
        "bundle": {"key": bundle.name,
                   "label": doc.picked("study_project_name"),
                   "acronym": doc.picked("study_acronym"),
                   "abstract": doc.picked("publication_abstract"),
                   "organisations": labels("organisation",
                                           "study_organisation"),
                   "funders": labels("funder", "study_funder"),
                   "tags": {key: written.values(bundle, key)
                            for key in ("study_descriptor",
                                        "study_sector_division",
                                        "study_sector", "study_technology")}},
        "report": {"label": report.name,
                   "authors": labels("author", "publication_author"),
                   "publication_date": stamp[0] if stamp else None,
                   "doi": doc.picked("publication_doi")},
        "scenarios": scenarios,
    }


# -- the drawing's names, for the OEKG API body --------------------------------
#
# The body of a create speaks the platform's paths and classes. They are the
# drawing's: what the Turtle writes for a field is what a body sends. Each is
# read when a body is made, from the drawing as the graph file has it then.

_SPEC = json.loads(Path(__file__).with_name("extraction_spec.json")
                   .read_text(encoding="utf-8"))


def drawing() -> dict:
    """The drawing, as the graph file of this profile has it now."""
    return graphfile.get_map("scenarios")


def prefix_iri() -> dict:
    """{prefix: IRI} of the header the drawing writes now."""
    return dict(drawing().get("prefixes") or {})


def always_types() -> tuple:
    """The scenario types every factsheet carries (graph rule
    `scenario_types_always`), as it stands now."""
    return tuple(graphfile.get("scenario_types_always", "scenarios"))


def _bare(name: str) -> str:
    return str(name).split(":")[-1]


def box_class(box_id: str) -> str:
    """The bare class of a box of the drawing."""
    return _bare(next(box for box in drawing()["boxes"]
                      if box["id"] == box_id).get("class") or "")


def property_of(source: str, to: str, brick: Optional[str] = None) -> str:
    """The property of the drawing's arrow from *source* to *to*."""
    return next(arrow["property"] for arrow in drawing()["arrows"]
                if arrow["from"] == source and arrow["to"] == to
                and (brick is None or arrow.get("brick") == brick))


def normalise(name: str) -> str:
    """One spelling for a name, as the drawing folds it."""
    from docpipe.extraction import graphkit
    return graphkit.normalise(str(name), drawing().get("legal_forms") or "")


def terms() -> SimpleNamespace:
    """The classes and properties a body names its nodes and edges with,
    as the drawing has them now."""
    return SimpleNamespace(
        CLS_REPORT=box_class("report"),
        CLS_BUNDLE=box_class("bundle"),
        CLS_SCENARIO=box_class("scenario"),
        CLS_AUTHOR=box_class("author"),
        CLS_ORGANISATION=box_class("organisation"),
        CLS_FUNDER=box_class("funder"),
        P_LABEL=property_of("publication_title", "report"),
        P_ACRONYM=property_of("study_acronym", "bundle"),
        P_ABSTRACT=property_of("publication_abstract", "bundle"),
        P_AUTHOR=property_of("report", "author"),
        P_PUBDATE=property_of("publication_date", "report"),
        P_DOI=property_of("publication_doi", "report"),
        P_ORGANISATION=property_of("bundle", "organisation"),
        P_FUNDER=property_of("bundle", "funder"),
        P_HAS_PART=property_of("bundle", "report"),
        P_SCENARIO_TYPE=property_of("scenario_type", "scenario"),
        P_STUDY_REGION=property_of("scenario_region", "scenario"),
        P_SCENARIO_YEAR=property_of("scenario_year", "scenario"),
        P_SCENARIO_ACRONYM=property_of("scenario_label", "scenario",
                                       "short_name"),
        P_SCENARIO_ABSTRACT=property_of("scenario_abstract", "scenario"),
        P_UUID=next(box.get("uuid") for box in drawing()["boxes"]
                    if box["id"] == "report"))


def tag_property(key: str) -> str:
    """The property a tag field of the bundle is written under."""
    return property_of(key, "bundle")


def make_study_reader(db_path: Path, extra: Optional[dict] = None):
    """(document name, accepted tuple rows) -> study dict or None: what the
    drawing decides for one document, without the Turtle. A document
    without a title has no study, as it has no graph."""
    from docpipe.extraction.graph import make_writer
    from docpipe.profile import load_profile
    writer = make_writer(load_profile("scenarios"), db_path, extra=extra)

    def reader(name: str, rows: list):
        written = writer.write(name, rows)
        return study_of(written) if written is not None else None

    return reader
