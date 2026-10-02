"""
oekg_api.py – What the OEKG scenario-bundle API would be asked, and what it
would answer. A dry run: no request that writes is ever built into a call.

The platform takes a scenario bundle as one JSON body
(`POST /api/v0/scenario-bundles/`), mints every identifier itself and holds
the assembled bundle against the OEKG shapes before it writes anything. A
create is judged strictly, so one missing value refuses the whole bundle.
This module builds that body for every document of a harvest, from the same
reading kg.py writes its Turtle from, and holds it against the two things
the platform holds it against:

  the request schema   `ScenarioBundleCreate` in the platform's OpenAPI
                       description: the keys, their types, what is required.
  the shapes           `oekg_shapes.ttl`, over the bundle as the platform
                       would hold it after the create.

    python -m profiles.scenarios.oekg_api OUT DB --refresh
    python -m profiles.scenarios.oekg_api OUT DB --write bodies.jsonl
    python -m profiles.scenarios.oekg_api OUT DB --live

`--refresh` pulls SOURCES first; without it the files of the last refresh
are used, and `--openapi` / `--shapes` name local copies instead. `--live`
reads the platform's public bundle list, a GET, to say which acronyms are
taken: the acronym is unique over there and the only way to find a bundle
again, because no identifier of ours is accepted.

Two findings are about the harvest and not about one body. Documents that
name the same acronym cannot both be created. Documents whose bundle has
the same label are one node in the Turtle, which mints the bundle from its
label, and would be several bundles of one study as requests.

Exit 0 is a report, whatever it says. Exit 2 is a run that could not be
made: no harvest, no database, no API description or no shapes.

The shape verdict is a model of the server, built from its documentation
and not from its code. It assumes what that documentation says: the server
mints a uuid on every study report and every scenario, a contact,
organisation, funder or author sent with a label alone is minted with that
label, and a region or a scenario type sent as an IRI is a node that
already exists over there with its own type and label. Where the model is
wrong the verdict is, and only a real create settles it.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import io
import json
import logging
import re
from pathlib import Path
from typing import Optional

from docpipe import upstream
from docpipe.extraction.serialize import collect
from profiles.scenarios import kg

HERE = Path(__file__).resolve().parent
REGIONS_PATH = HERE / "regions.json"
VOCABULARY_PATH = HERE / "vocabulary.json"

SOURCES = {
    "oep_api": {"kind": "repo_files", "repo": "OpenEnergyPlatform/oeplatform",
                "ref": "master",
                "reviewed": "3432710bac7b6d91dc314bc240dbaeb99cd3d44c",
                "files": ["docs/oeplatform-code/web-api/openapi.yaml"]},
    # The head of the branch, which is what the next pin will be. `reviewed`
    # is the commit the platform pins its validator to today
    # (oeplatform/settings.py OEKG_SHAPES_PINNED_COMMIT): while the two are
    # the same file, the verdict here is the validator's. Every run prints
    # whether they still are.
    "oekg_shapes": {"kind": "repo_files", "repo": "OpenEnergyPlatform/oekg",
                    "ref": "production",
                    "reviewed": "b4604e02060624b381bdbe2f872df94cfd0f5630",
                    "files": ["oekg/shapes/oekg_shapes.ttl"]},
}
# The lock of these two sources. Its own, so a harvest run's
# `vocabulary --refresh` does not come to depend on the API description.
LOCK = "scenarios_oekg_api"

CREATE = "ScenarioBundleCreate"
PATH = "/api/v0/scenario-bundles/"
LIST_URL = "https://openenergyplatform.org" + PATH

# What `study_regions` becomes over there. The Turtle writes the parent
# property (kg.P_STUDY_REGION, see scenario_region in the spec); the API
# writes the one the closed scenario shape names, onto nodes of the class it
# requires.
API_STUDY_REGION = "OEO_00020220"       # has study region
API_CLS_STUDY_REGION = "OEO_00020032"   # study region

_PREFIX = dict(re.findall(r"@prefix (\w+):\s*<([^>]+)>", kg.PREFIXES))
SH = "http://www.w3.org/ns/shacl#"


# -- sources ------------------------------------------------------------------

def refresh(cache: Path = upstream.CACHE) -> dict:
    """Pull SOURCES and write their lock."""
    records = upstream.fetch(SOURCES, cache)
    upstream.write_lock(LOCK, records, cache)
    return records


def _records(cache: Path = upstream.CACHE) -> dict:
    return (upstream.load_lock(LOCK, cache) or {}).get("sources") or {}


def _locked(name: str, cache: Path = upstream.CACHE) -> Optional[Path]:
    paths = [path for path in upstream.files(_records(cache).get(name))
             if path.is_file()]
    return paths[0] if paths else None


def labels(cache: Path = upstream.CACHE) -> dict:
    """{IRI: label} for what a body references and a verdict names.

    The regions and the terms this profile's snapshot holds are checked in.
    The properties the shapes name are in neither, so the OEO closure of the
    last `vocabulary --refresh` is read where there is one; without it a
    path is named by its identifier alone.
    """
    out = {}
    regions = json.loads(REGIONS_PATH.read_text(encoding="utf-8"))
    for iri, names in regions.items():
        out[iri] = names[0]
    terms = json.loads(VOCABULARY_PATH.read_text(encoding="utf-8"))["terms"]
    for key, term in terms.items():
        if key.startswith("OEO_") and term.get("label"):
            out[kg.OEO_BASE + key] = term["label"]
    record = ((upstream.load_lock("scenarios", cache) or {}).get("sources")
              or {}).get("oeo")
    closure = [path for path in upstream.files(record, ".owl") if path.is_file()]
    if closure:
        from rdflib import Graph, RDFS, URIRef
        graph = Graph().parse(str(closure[0]), format="xml")
        for subject, label in graph.subject_objects(RDFS.label):
            if isinstance(subject, URIRef):
                out.setdefault(str(subject), str(label))
    return out


# -- the body -----------------------------------------------------------------

def _references(names: list) -> list:
    return [{"label": name} for name in names]


def body(study: dict, known: dict) -> dict:
    """The create body for one study, as kg.py read it.

    A value the harvest does not hold is a key the body does not carry. An
    empty string or an empty list would pass the schema and say something
    the document did not, and the refusal for the missing key is the finding.
    """
    bundle, report = study["bundle"], study["report"]
    out: dict = {"label": bundle["label"]}
    for key in ("acronym", "abstract"):
        if bundle.get(key):
            out[key] = bundle[key]
    for key in ("organisations", "funders"):
        if bundle.get(key):
            out[key] = _references(bundle[key])
    paper: dict = {"label": report["label"]}
    for key in ("doi", "publication_date"):
        if report.get(key):
            paper[key] = report[key]
    if report.get("authors"):
        paper["authors"] = _references(report["authors"])
    out["study_reports"] = [paper]
    scenarios = []
    for scenario in study["scenarios"]:
        item: dict = {"label": scenario["label"], "acronym": scenario["acronym"]}
        if scenario.get("abstract"):
            item["abstract"] = scenario["abstract"]
        if scenario.get("types"):
            item["scenario_types"] = list(scenario["types"])
        if scenario.get("regions"):
            item["study_regions"] = [{"iri": iri, "label": known.get(iri, iri)}
                                     for iri in scenario["regions"]]
        if scenario.get("years"):
            item["years"] = list(scenario["years"])
        scenarios.append(item)
    if scenarios:
        out["scenarios"] = scenarios
    return out


# -- the request schema -------------------------------------------------------

def _where(path) -> str:
    """`study_reports/0/authors` -> `study_reports[].authors`."""
    out = ""
    for part in path:
        out += "[]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out or "body"


def _resolve(schema: dict, components: dict) -> dict:
    while "$ref" in schema:
        schema = components["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def _unknown_keys(value, schema: dict, components: dict, path: tuple) -> list:
    """Keys the schema does not name. The platform refuses them, and the
    schema alone would not: it declares no additionalProperties."""
    schema = _resolve(schema, components)
    out = []
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for key, inner in value.items():
            if key not in properties:
                out.append({"check": "schema", "where": _where(path),
                            "what": f"{key!r} is not a key of the API"})
            else:
                out += _unknown_keys(inner, properties[key], components,
                                     path + (key,))
    elif isinstance(value, list):
        for index, inner in enumerate(value):
            out += _unknown_keys(inner, schema.get("items") or {}, components,
                                 path + (index,))
    return out


def _json_schema(node):
    """An OpenAPI 3.0 schema as JSON Schema.

    3.0 marks a value that may be null with `nullable: true`, a keyword JSON
    Schema does not have; read as written, every null the platform accepts
    would be reported as the wrong type.
    """
    if isinstance(node, list):
        return [_json_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    out = {key: _json_schema(value) for key, value in node.items()
           if not (key == "nullable" and isinstance(value, bool))}
    if node.get("nullable") is True:
        if isinstance(out.get("type"), str):
            out["type"] = [out["type"], "null"]
        else:
            out = {"anyOf": [out, {"type": "null"}]}
    return out


class RequestSchema:
    """`ScenarioBundleCreate` of one OpenAPI description, ready to ask."""

    def __init__(self, openapi: dict):
        from jsonschema import Draft202012Validator
        self.components = _json_schema(openapi["components"])
        self.validator = Draft202012Validator(
            {"$ref": f"#/components/schemas/{CREATE}",
             "components": self.components})

    def problems(self, payload: dict) -> list:
        out = [{"check": "schema", "where": _where(error.absolute_path),
                "what": error.message}
               for error in sorted(self.validator.iter_errors(payload),
                                   key=lambda e: [str(p) for p in e.absolute_path])]
        return out + _unknown_keys(payload, self.components["schemas"][CREATE],
                                   self.components, ())


def schema_problems(payload: dict, openapi: dict) -> list:
    """What the request schema says against one body."""
    return RequestSchema(openapi).problems(payload)


# -- the shapes ---------------------------------------------------------------

def _iri(name: str):
    """`oeo:OEO_00000506` -> the IRI, against the Turtle's own prefixes."""
    from rdflib import URIRef
    prefix, _, local = name.partition(":")
    return URIRef(_PREFIX[prefix] + local)


# The keys the model below turns into triples: the ones `body` writes. The
# API has more (descriptors, sectors, contacts, datasets, ...), and a body
# carrying one of those would be judged as if it did not.
MODELLED = {
    "body": ("label", "acronym", "abstract", "organisations", "funders",
             "study_reports", "scenarios"),
    "study_reports[]": ("label", "doi", "publication_date", "authors"),
    "scenarios[]": ("label", "acronym", "abstract", "scenario_types",
                    "study_regions", "years"),
}


def _modelled(item: dict, where: str) -> None:
    extra = sorted(set(item) - set(MODELLED[where]))
    if extra:
        raise ValueError(f"the server model does not cover {where} key(s) "
                         f"{', '.join(extra)}: the shapes cannot be asked "
                         f"about this body until graph() writes them")


def graph(payload: dict, known: dict):
    """The bundle as the platform would hold it after creating this body.

    The model the module docstring names. Local IRIs stand in for the ones
    the server mints; nothing here is written anywhere. A key the model does
    not cover raises: a verdict over half a body would read as a verdict.
    """
    from rdflib import RDF, RDFS, XSD, Graph, Literal, URIRef
    _modelled(payload, "body")
    for paper in payload.get("study_reports") or ():
        _modelled(paper, "study_reports[]")
    for item in payload.get("scenarios") or ():
        _modelled(item, "scenarios[]")
    out = Graph()
    counter = collections.Counter()

    def oeo(local: str):
        return URIRef(kg.OEO_BASE + local)

    def node(kind: str):
        counter[kind] += 1
        return URIRef(f"urn:dry-run:{kind}:{counter[kind]}")

    def text(subject, predicate: str, value) -> None:
        if value is not None:
            out.add((subject, _iri(predicate), Literal(str(value))))

    def stamp(subject, predicate: str, value) -> None:
        out.add((subject, _iri(predicate), Literal(str(value),
                                                    datatype=XSD.dateTime)))

    def named(subject, predicate: str, references: list, cls: str,
              kind: str) -> None:
        for reference in references or ():
            target = (URIRef(reference["iri"]) if reference.get("iri")
                      else node(kind))
            out.add((subject, _iri(predicate), target))
            out.add((target, RDF.type, oeo(cls)))
            out.add((target, RDFS.label, Literal(reference["label"])))

    bundle = node("bundle")
    out.add((bundle, RDF.type, oeo(kg.CLS_BUNDLE)))
    text(bundle, kg.P_LABEL, payload.get("label"))
    text(bundle, kg.P_ACRONYM, payload.get("acronym"))
    text(bundle, kg.P_ABSTRACT, payload.get("abstract"))
    named(bundle, kg.P_ORGANISATION, payload.get("organisations"),
          kg.CLS_ORGANISATION, "organisation")
    named(bundle, kg.P_FUNDER, payload.get("funders"), kg.CLS_FUNDER, "funder")

    for paper in payload.get("study_reports") or ():
        report = node("report")
        out.add((bundle, _iri(kg.P_HAS_PART), report))
        out.add((report, RDF.type, oeo(kg.CLS_REPORT)))
        text(report, kg.P_UUID, "minted by the server")
        text(report, kg.P_LABEL, paper.get("label"))
        text(report, kg.P_DOI, paper.get("doi"))
        if paper.get("publication_date"):
            stamp(report, kg.P_PUBDATE, paper["publication_date"])
        named(report, kg.P_AUTHOR, paper.get("authors"), kg.CLS_AUTHOR,
              "author")

    for item in payload.get("scenarios") or ():
        scenario = node("scenario")
        out.add((bundle, _iri(kg.P_HAS_PART), scenario))
        out.add((scenario, RDF.type, oeo(kg.CLS_SCENARIO)))
        text(scenario, kg.P_UUID, "minted by the server")
        text(scenario, kg.P_LABEL, item.get("label"))
        text(scenario, kg.P_SCENARIO_ACRONYM, item.get("acronym"))
        text(scenario, kg.P_SCENARIO_ABSTRACT, item.get("abstract"))
        for kind in item.get("scenario_types") or ():
            out.add((scenario, _iri(kg.P_SCENARIO_TYPE), URIRef(kind)))
            # A class of a released ontology carries its label over there.
            # One the release does not hold has none, and the shapes say so.
            if kind in known:
                out.add((URIRef(kind), RDFS.label, Literal(known[kind])))
        for region in item.get("study_regions") or ():
            target = URIRef(region["iri"])
            out.add((scenario, oeo(API_STUDY_REGION), target))
            out.add((target, RDF.type, oeo(API_CLS_STUDY_REGION)))
            out.add((target, RDFS.label, Literal(known.get(region["iri"],
                                                           region["label"]))))
        for year in item.get("years") or ():
            stamp(scenario, kg.P_SCENARIO_YEAR, year)
    return out


def _named(iri, known: dict) -> str:
    """`has author (OEO_00000506)`, or the identifier where no label is known."""
    if iri is None:
        return "-"
    local = re.split(r"[/#]", str(iri))[-1]
    label = known.get(str(iri))
    return f"{label} ({local})" if label else local


def shape_problems(data, shapes, known: dict) -> list:
    """What the shapes say against one bundle graph."""
    from pyshacl import validate
    from rdflib import RDF, URIRef
    _conforms, results, _text = validate(data, shacl_graph=shapes)
    out = []
    for report in results.subjects(RDF.type, URIRef(SH + "ValidationReport")):
        for result in results.objects(report, URIRef(SH + "result")):
            focus = results.value(result, URIRef(SH + "focusNode"))
            component = str(results.value(
                result, URIRef(SH + "sourceConstraintComponent")))
            value = results.value(result, URIRef(SH + "value"))
            problem = {
                "check": "shape",
                # The class of the node at fault. A node with none is one the
                # body only points at, an ontology class say, and is named
                # itself.
                "where": _named(data.value(focus, RDF.type) or focus, known),
                "what": (component.rsplit("#", 1)[-1]
                         .replace("ConstraintComponent", "") + " on "
                         + _named(results.value(result, URIRef(SH + "resultPath")),
                                  known))}
            if isinstance(value, URIRef):
                # Which entry a list refused. A literal is the document's own
                # text and would make every refusal its own kind.
                problem["what"] += f": {_named(value, known)}"
            out.append(problem)
    return sorted(out, key=lambda p: (p["where"], p["what"]))


# -- the acronyms -------------------------------------------------------------

def _fold(acronym) -> str:
    return str(acronym or "").strip().casefold()


def platform_acronyms(url: str = LIST_URL) -> dict:
    """{acronym: label} of the bundles the platform lists. Public, a GET.

    A bundle listed without an acronym has nothing to compare and is left
    out, so the size of this is a count of acronyms, not of bundles.
    """
    out: dict = {}
    page: Optional[str] = url + "?page_size=200"
    while page:
        try:
            data = json.loads(upstream._get(page))
            items = list(data["results"])
            for item in items:
                if item.get("acronym"):
                    out[item["acronym"]] = item.get("label")
            page = data.get("next")
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # A 200 that is not the list: a maintenance page, a proxy's own.
            raise upstream.UpstreamError(
                f"{page}: not a bundle list ({exc!r})") from exc
    return out


def acronym_problems(entries: list, taken: Optional[dict] = None) -> None:
    """Add to each entry what stands against its acronym.

    Compared without case and outer spaces. The platform's own rule may be
    narrower; two bundles that differ in case alone are one study either way.
    """
    used: dict = {}
    for entry in entries:
        acronym = entry["body"].get("acronym")
        if acronym:
            used.setdefault(_fold(acronym), []).append(entry["document"])
    there = {_fold(acronym): (acronym, label)
             for acronym, label in (taken or {}).items()}
    for entry in entries:
        key = _fold(entry["body"].get("acronym"))
        if not key:
            continue
        others = [name for name in used[key] if name != entry["document"]]
        if others:
            entry["problems"].append({
                "check": "acronym", "where": "body",
                "what": "acronym used by more than one document of this harvest",
                "message": ", ".join(sorted(others))})
        if key in there:
            entry["problems"].append({
                "check": "acronym", "where": "body",
                "what": "acronym already on the platform",
                "message": f"{there[key][0]!r}: {there[key][1]}"})


def shared_problems(entries: list) -> None:
    """Add to each entry which other documents make the same bundle.

    kg.py mints a bundle from its label, so in the Turtle two papers of one
    project are one bundle with two reports. A create is one body per
    document: sent as they are, they would be several bundles of one study.
    """
    used: dict = {}
    for entry in entries:
        used.setdefault(kg.normalise(entry["body"]["label"]),
                        []).append(entry["document"])
    for entry in entries:
        others = [name for name in used[kg.normalise(entry["body"]["label"])]
                  if name != entry["document"]]
        if others:
            entry["problems"].append({
                "check": "bundle", "where": "body",
                "what": "bundle label shared by more than one document of "
                        "this harvest",
                "message": ", ".join(sorted(others))})


# -- the run ------------------------------------------------------------------

def dry_run(harvest: Path, db: Path, openapi: dict, shapes,
            known: dict, taken: Optional[dict] = None) -> tuple:
    """(entries, documents without a study) for a harvest directory.

    An entry is one request as it would be sent, and every reason the
    platform would refuse it: {document, method, path, body, problems}.
    """
    reader = kg.make_study_reader(db)
    schema = RequestSchema(openapi)
    entries, without = [], []
    for name, rows in collect(harvest).items():
        study = reader(name, rows)
        if study is None:
            without.append(name)
            continue
        payload = body(study, known)
        problems = schema.problems(payload)
        problems += shape_problems(graph(payload, known), shapes, known)
        entries.append({"document": name, "method": "POST", "path": PATH,
                        "body": payload, "problems": problems})
    acronym_problems(entries, taken)
    shared_problems(entries)
    return entries, without


HEADINGS = (("schema", "refused by the request schema"),
            ("shape", "refused by the shapes"),
            ("acronym", "the acronym"),
            ("bundle", "one study, several documents"))


def report(entries: list, without: list,
           taken: Optional[dict] = None) -> str:
    """The run in English, one line per kind of refusal."""
    ready = [entry for entry in entries if not entry["problems"]]
    lines = ["OEKG scenario-bundle dry run: nothing was sent",
             f"  {len(entries)} document(s) carry a study, {len(without)} do "
             f"not (no title harvested)",
             f"  {len(ready)} would be created as they are, "
             f"{len(entries) - len(ready)} would be refused"]
    for check, heading in HEADINGS:
        # Documents, not nodes: thirty scenarios of one paper that miss the
        # same thing are one finding about that paper.
        counts: collections.Counter = collections.Counter()
        for entry in entries:
            counts.update({(p["where"], p["what"]) for p in entry["problems"]
                           if p["check"] == check})
        if not counts:
            continue
        lines += ["", f"  {heading} (documents)"]
        for (where, what), count in sorted(counts.items(),
                                           key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {count:6d}  {where}: {what}")
    lines += ["", "  acronyms were not compared with the platform's (--live "
                  "reads its public list)" if taken is None else
              f"  acronyms were compared with the {len(taken)} acronym(s) "
              f"the platform lists"]
    held: collections.Counter = collections.Counter()
    for entry in entries:
        payload = entry["body"]
        held["bundles"] += 1
        held["organisations"] += len(payload.get("organisations") or ())
        held["funders"] += len(payload.get("funders") or ())
        held["study reports"] += len(payload.get("study_reports") or ())
        held["authors"] += sum(len(paper.get("authors") or ())
                               for paper in payload.get("study_reports") or ())
        held["scenarios"] += len(payload.get("scenarios") or ())
        held["region references"] += sum(
            len(item.get("study_regions") or ())
            for item in payload.get("scenarios") or ())
    lines += ["", "  what the bodies hold: " +
              ", ".join(f"{count} {kind}" for kind, count in held.items())]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Dry run of the OEKG scenario-bundle API over a harvest. "
                    "Sends nothing.")
    parser.add_argument("out", type=Path,
                        help="harvest directory (JSONL per document)")
    parser.add_argument("db", type=Path, help="SQLite corpus database")
    parser.add_argument("--refresh", action="store_true",
                        help="pull the API description and the shapes first")
    parser.add_argument("--openapi", type=Path, default=None,
                        help="a local openapi.yaml instead of the last refresh")
    parser.add_argument("--shapes", type=Path, default=None,
                        help="a local shapes file instead of the last refresh")
    parser.add_argument("--live", action="store_true",
                        help="read the platform's public bundle list (GET) "
                             "and compare the acronyms")
    parser.add_argument("--write", type=Path, default=None, metavar="JSONL",
                        help="write one request per document, with its problems")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s [%(levelname)s] %(name)s %(message)s",
                        datefmt="%H:%M:%S")

    # The reading falls back to an empty AR6 list when the database cannot
    # be opened, and the bodies then name other scenarios. That is a
    # different run, not a degraded one.
    if not args.out.is_dir():
        print(f"{args.out}: not a harvest directory")
        return 2
    if not args.db.is_file():
        print(f"{args.db}: no such database")
        return 2
    try:
        if args.refresh:
            refresh()
        taken = platform_acronyms() if args.live else None
    except upstream.UpstreamError as exc:
        print(f"could not be read: {exc}")
        return 2
    openapi_path = args.openapi or _locked("oep_api")
    shapes_path = args.shapes or _locked("oekg_shapes")
    if openapi_path is None or shapes_path is None:
        print("no API description or no shapes: run with --refresh, or name "
              "local files with --openapi and --shapes")
        return 2
    for path in (openapi_path, shapes_path):
        if not Path(path).is_file():
            print(f"{path}: no such file")
            return 2
    # What the last refresh pulled and whether upstream moved since the
    # commit this module was reviewed against. On every run, because a
    # verdict against moved shapes is a verdict about another validator.
    for name, record in _records().items():
        if (name, None) in (("oep_api", args.openapi),
                            ("oekg_shapes", args.shapes)):
            print(upstream.summary(name, record))

    import yaml
    from rdflib import Graph
    openapi = yaml.safe_load(Path(openapi_path).read_text(encoding="utf-8"))
    shapes = Graph().parse(str(shapes_path), format="turtle")
    entries, without = dry_run(args.out, args.db, openapi, shapes, labels(),
                               taken)
    if not entries and not without:
        print(f"{args.out}: no harvest in it (*.jsonl)")
        return 2
    if args.write is not None:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        with io.open(args.write, "w", encoding="utf-8", newline="\n") as handle:
            for entry in entries:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(report(entries, without, taken))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
