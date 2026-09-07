"""
vocabulary.py – The option lists, taken from the ontology instead of retyped.

Every closed list the model picks from names OEO or MHPO terms, and until now
each of those was a hand-typed identifier next to a hand-typed German label.
Nothing checked that the identifier exists, that the label is the term's own,
that the class is still there, or that a carrier is a carrier. The ontology
moves — "es sollen bzw. duerfen die Sachen dynamisch aus der aktuellen Version
gezogen werden" — and a spec that cannot be checked against it silently drifts
into describing a graph nobody has.

So this reads the pinned closure and writes `vocabulary.json`: per term its
label, its German alternative labels, its definition, its parents and whether
it is deprecated, plus the sets a list may draw from (what OEO calls an energy
carrier, a sector, an aggregation type, a quantity value, an energy unit, a
mass unit). The pin — version IRI and the file's own sha256 — rides along, so
"which ontology is this spec written against" has an answer.

The closure itself is not vendored: it is 3.9 MB, it belongs to the ontology
repository, and what this profile needs from it is two hundred terms. Rebuild
with the file in hand:

    python -m profiles.kwp.vocabulary --closure oeo-closure.owl \\
        --mhpo mhpo-edit.owl --write
    python -m profiles.kwp.vocabulary --check      # spec against the pin

rdflib and no reasoner. The carrier closure is asserted subClassOf plus the
conjuncts of an equivalentClass, which reaches 124 of the 125 terms a reasoner
finds — and the one it misses is not in any list here.

Author: Felix Vossel
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import io
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VOCABULARY_PATH = HERE / "vocabulary.json"
SPEC_PATH = HERE / "extraction_spec.json"

OEO = "https://openenergyplatform.org/ontology/oeo/"
OBO = "http://purl.obolibrary.org/obo/"
MHPO = "https://openenergyplatform.org/ontology/mhpo/"

# The roots each list draws from. A list is only checkable against a set, and
# a set is only honest if it is the ontology's own: "OEO_00000132 district
# heat is not an energy carrier" is a fact of the closure, not an opinion.
SETS = {
    "energy_carrier": ("class", OEO + "OEO_00020039"),
    "sector": ("class", OEO + "OEO_00000367"),
    "quantity_value": ("class", OEO + "OEO_00000350"),
    "energy_unit": ("class", OBO + "UO_0000111"),
    "mass_unit": ("class", OBO + "UO_0000002"),
    "aggregation_type": ("individual", OEO + "OEO_00140068"),
}


def _short(uri: str) -> str:
    """The identifier a spec writes: OEO_00050016, MHPO_00020007, UO_0000111."""
    return str(uri).rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _read(paths: list):
    from rdflib import Graph
    graph = Graph()
    for path in paths:
        graph.parse(str(path))
    return graph


def _index(graph) -> dict:
    """identifier -> {label, labels_de, definition, parents, deprecated}."""
    from rdflib import OWL, RDF, RDFS, URIRef
    definition = URIRef(OBO + "IAO_0000115")
    alternative = URIRef(OBO + "IAO_0000118")
    out: dict = {}
    subjects = set(graph.subjects(RDF.type, OWL.Class))
    subjects |= set(graph.subjects(RDF.type, OWL.NamedIndividual))
    for subject in subjects:
        if not isinstance(subject, URIRef):
            continue
        key = _short(subject)
        label = graph.value(subject, RDFS.label)
        if label is None:
            continue
        german = sorted(str(a) for a in graph.objects(subject, alternative)
                        if getattr(a, "language", None) == "de")
        if not german:
            # The closure labels most alternatives without a language tag.
            # Taking them all is worse than taking none: the English synonym
            # would be offered to the model as a German spelling.
            german = sorted(str(a) for a in graph.objects(subject, alternative)
                            if getattr(a, "language", None) is None)
        meaning = graph.value(subject, definition)
        out[key] = {
            "label": str(label),
            "alt_labels": german,
            "definition": str(meaning) if meaning else None,
            "parents": sorted(_short(p) for p in
                              graph.objects(subject, RDFS.subClassOf)
                              if isinstance(p, URIRef)),
            "deprecated": bool(graph.value(subject, OWL.deprecated)),
        }
    return out


def _closures(graph) -> dict:
    """Each set of SETS as a sorted list of identifiers."""
    from rdflib import OWL, RDF, RDFS, URIRef
    children = collections.defaultdict(set)
    for child, parent in graph.subject_objects(RDFS.subClassOf):
        if isinstance(child, URIRef) and isinstance(parent, URIRef):
            children[str(parent)].add(str(child))
    # An equivalentClass intersection is how OEO says "a biogenic solid fuel
    # is a solid fuel AND biogenic". Its conjuncts are parents in every sense
    # that matters here, and without them thirteen carriers the schema
    # already accepts fall outside their own root.
    for subject, expression in graph.subject_objects(OWL.equivalentClass):
        if not isinstance(subject, URIRef):
            continue
        for collection in graph.objects(expression, OWL.intersectionOf):
            from rdflib.collection import Collection
            for member in Collection(graph, collection):
                if isinstance(member, URIRef):
                    children[str(member)].add(str(subject))

    def under(root: str) -> set:
        seen, stack = set(), [root]
        while stack:
            node = stack.pop()
            for child in children.get(node, ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        return seen

    out: dict = {}
    for name, (kind, root) in SETS.items():
        if kind == "class":
            members = under(root)
        else:
            members = {str(x) for x in graph.subjects(RDF.type, URIRef(root))}
        out[name] = sorted(_short(m) for m in members)
    return out


def build(closure: Path, mhpo: Path = None) -> dict:
    """The vocabulary snapshot, from the ontology files as they stand."""
    from rdflib import OWL, RDF, RDFS
    paths = [closure] + ([mhpo] if mhpo else [])
    graph = _read(paths)
    sets = _closures(graph)
    # Only the terms a list can draw from, plus everything the spec already
    # names and the parents of both. The closure holds 1,834 labelled terms
    # and this profile can reach 270 of them; carrying the rest would be
    # half a megabyte of ontology nobody here reads, checked into a
    # repository that is not the ontology's.
    wanted = {uri for members in sets.values() for uri in members}
    wanted |= set(spec_terms(json.loads(
        SPEC_PATH.read_text(encoding="utf-8"))))
    full = _index(graph)
    wanted |= {parent for uri in wanted
               for parent in (full.get(uri) or {}).get("parents", ())}
    terms = {uri: full[uri] for uri in sorted(wanted) if uri in full}
    version = None
    for ontology in graph.subjects(RDF.type, OWL.Ontology):
        if str(ontology).startswith(OEO):
            version = graph.value(ontology, OWL.versionIRI)
    pin = {
        "oeo_version_iri": str(version) if version else None,
        "oeo_sha256": hashlib.sha256(closure.read_bytes()).hexdigest(),
        "oeo_file": closure.name,
    }
    if mhpo:
        pin["mhpo_sha256"] = hashlib.sha256(mhpo.read_bytes()).hexdigest()
        pin["mhpo_file"] = mhpo.name
    return {"pin": pin, "sets": sets, "terms": terms}


def serialize(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=1,
                      sort_keys=True) + "\n"


def load(path: Path = VOCABULARY_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def spec_terms(spec_raw: dict) -> dict:
    """Every ontology identifier the spec names, and where it names it.

    Only real identifiers: an entry beginning "out:" is a deliberate
    non-class and an axis key like "target" is a scenario the graph maps
    elsewhere. Both are the profile's own words and neither is the
    ontology's to confirm.
    """
    found: dict = collections.defaultdict(list)

    def note(uri, where):
        if isinstance(uri, str) and (uri.startswith("OEO_")
                                     or uri.startswith("MHPO_")
                                     or uri.startswith("UO_")):
            found[uri].append(where)

    for parameter in spec_raw.get("parameters", []):
        uri = parameter.get("uri")
        note(parameter.get("unit_target"), f"{uri}.unit_target")
        for name, axis in (parameter.get("axes") or {}).items():
            for key in (axis.get("vocabulary") or {}):
                note(key, f"{uri}.{name}")
            derive = axis.get("derive") or {}
            note(derive.get("value"), f"{uri}.{name}.derive")
    return dict(found)


def check(spec_raw: dict, snapshot: dict) -> list:
    """Every complaint the pinned ontology has about this spec."""
    terms, sets = snapshot["terms"], snapshot["sets"]
    problems: list = []
    for uri, wheres in sorted(spec_terms(spec_raw).items()):
        where = wheres[0]
        term = terms.get(uri)
        if term is None:
            problems.append(f"{where}: {uri} is not in the pinned ontology")
            continue
        if term["deprecated"]:
            problems.append(f"{where}: {uri} is deprecated")
    # A carrier the ontology does not call a carrier, and a sector it does
    # not call a sector. The profile is allowed to offer a heat source under
    # `carrier` -- district heat, geothermal, waste heat, which every plan
    # writes in that column -- but it has to declare it, and the serializer
    # drops the edge for exactly the declared ones. Undeclared is the drift
    # this exists to catch: a carrier that is not one and nobody decided.
    for parameter in spec_raw.get("parameters", []):
        carrier = (parameter.get("axes") or {}).get("carrier") or {}
        declared = set((carrier.get("kg") or {}).get("no_edge_for") or {})
        allowed = set(sets.get("energy_carrier") or ())
        for uri in (carrier.get("vocabulary") or {}):
            if uri.startswith("out:") or uri in allowed:
                if uri in declared:
                    problems.append(
                        f"{parameter.get('uri')}.carrier: {uri} IS an energy "
                        f"carrier and does not belong in no_edge_for")
                continue
            if uri not in declared:
                label = (terms.get(uri) or {}).get("label", "?")
                problems.append(
                    f"{parameter.get('uri')}.carrier: {uri} ({label}) is not "
                    f"an energy carrier and is not declared in kg.no_edge_for")
    for parameter in spec_raw.get("parameters", []):
        axes = parameter.get("axes") or {}
        for axis_name, set_name in (("sector", "sector"),
                                    ("aggregation", "aggregation_type"),
                                    ("quantity", "quantity_value")):
            axis = axes.get(axis_name) or {}
            allowed = set(sets.get(set_name) or ())
            for uri in (axis.get("vocabulary") or {}):
                if uri.startswith("out:") or uri in allowed:
                    continue
                if uri in terms:
                    problems.append(
                        f"{parameter.get('uri')}.{axis_name}: {uri} "
                        f"({terms[uri]['label']}) is not a {set_name}")
    return problems


def foreign_labels(spec_raw: dict, snapshot: dict) -> list:
    """Options whose first label is not one the ontology gives the term.

    Not an error. The first label is what the model is offered and it is
    meant to be the word the corpus writes: a heat plan says "Private
    Haushalte", OEO says "household sector", and offering the ontology's word
    would ask the model to translate before it reads.

    It is worth listing all the same, because the same shape hides a real
    defect: an option labelled with a specific German word whose class is a
    generic one. "Klaerschlamm" (sewage sludge) offered as OEO_00000439 waste
    fuel does not mean the model chose badly -- it means every sewage-sludge
    reading in the corpus becomes a generic waste fuel, and nobody looking at
    the graph can tell.
    """
    terms = snapshot["terms"]
    out: list = []
    for parameter in spec_raw.get("parameters", []):
        for name, axis in (parameter.get("axes") or {}).items():
            for uri, entry in (axis.get("vocabulary") or {}).items():
                term = terms.get(uri)
                # Either spec form: a list whose first item is the offered
                # label, or an object that names it.
                offered = (entry.get("label") if isinstance(entry, dict)
                           else (entry or [None])[0])
                if uri.startswith("out:") or term is None or not offered:
                    continue
                known = {term["label"].casefold()}
                known |= {a.casefold() for a in term["alt_labels"]}
                if offered.casefold() not in known:
                    out.append((f"{parameter.get('uri')}.{name}", uri,
                                offered, term["label"]))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--closure", type=Path,
                        help="the OEO closure (owl/ttl), for --write")
    parser.add_argument("--mhpo", type=Path, help="mhpo-edit.owl, for --write")
    parser.add_argument("--write", action="store_true",
                        help="rebuild vocabulary.json from those files")
    parser.add_argument("--check", action="store_true",
                        help="hold the spec against the checked-in snapshot")
    args = parser.parse_args(argv)

    if args.write:
        if not args.closure or not args.closure.is_file():
            print("--write needs --closure <file>")
            return 2
        snapshot = build(args.closure, args.mhpo)
        with io.open(VOCABULARY_PATH, "w", encoding="utf-8",
                     newline="\n") as handle:
            handle.write(serialize(snapshot))
        print(f"{VOCABULARY_PATH}: {len(snapshot['terms'])} terms, "
              f"{sum(len(v) for v in snapshot['sets'].values())} set members, "
              f"pin {snapshot['pin']['oeo_version_iri']}")
    if args.check or not args.write:
        if not VOCABULARY_PATH.is_file():
            print(f"no {VOCABULARY_PATH.name} — run --write first")
            return 1
        spec_raw = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
        problems = check(spec_raw, load())
        for problem in problems:
            print(problem)
        foreign = foreign_labels(spec_raw, load())
        seen = set()
        for where, uri, label, own in foreign:
            if uri in seen:
                continue
            seen.add(uri)
            print(f"  note {where}: offers {label!r} for {uri} {own!r}")
        print(f"{len(spec_terms(spec_raw))} identifier(s) checked, "
              f"{len(problems)} problem(s), {len(seen)} corpus label(s)")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
