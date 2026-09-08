"""
ontology.py – The ontology a spec is written against, read once and pinned.

Every closed list a profile offers names terms of an ontology, and a spec that
cannot be checked against one drifts into describing a graph nobody has. This
reads an ontology file and writes a snapshot: per term its label, its foreign
alternative labels, its definition, its parents, whether it is deprecated, and
WHAT KIND of thing it is — a class, an individual or a property. Plus the sets
a list may draw from, and the pin (version IRI and the file's own sha256), so
"which ontology is this spec written against" has an answer.

Profile-free by design. What a profile keeps is its own: which roots its sets
draw from, where its closure lives, and the rules that are about its own axes.
The builder, the index, the identifier walk and the two generic complaints
("the ontology does not have this" and "the ontology deprecated this") are the
same question in every profile and live here.

The kind matters more than it looks. A `kg` block names PREDICATES, and a
predicate is an owl:ObjectProperty; an index over classes and individuals
alone reports every one of them as missing. That is why the scenarios profile
had no snapshot: its seventeen identifiers are mostly predicates.

rdflib is imported inside the functions that need it. The check runs against
the checked-in snapshot and needs no ontology file and no rdflib, which is
what lets it run on the cluster.

Author: Felix Vossel
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path
from typing import Optional

OBO = "http://purl.obolibrary.org/obo/"

# An ontology identifier as every one of these ontologies writes it: a short
# family, an underscore, digits. Matched at the end of a string so a bare id
# and a full IRI are the same term -- kwp writes `OEO_00000510`, scenarios
# writes the IRI, and holding one of them to the ontology and not the other is
# how a profile ends up with nothing checked at all.
IDENTIFIER = re.compile(r"(?:^|[/#])([A-Za-z]{2,8}_[0-9]{4,})$")

def short(uri) -> str:
    """The identifier at the end of an IRI, or the string as it stands."""
    text = str(uri)
    return text.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def identifier(value) -> Optional[str]:
    """`OEO_00000510` out of either spelling, or None if it is not one.

    A profile's own word is never one: `out:not_in_list` and `status_quo`
    fail the shape, and so does an identifier inside a sentence, because the
    match has to run to the end of the string.
    """
    if not isinstance(value, str):
        return None
    match = IDENTIFIER.search(value.strip())
    return match.group(1) if match else None


def read(paths: list):
    from rdflib import Graph
    graph = Graph()
    for path in paths:
        graph.parse(str(path))
    return graph


def index(graph) -> dict:
    """identifier -> {kind, label, alt_labels, definition, parents, deprecated}.

    Properties as well as classes and individuals. Without them a spec's `kg`
    blocks -- which name predicates and nothing else -- read as a list of
    terms the ontology does not have.
    """
    from rdflib import OWL, RDF, RDFS, URIRef
    definition = URIRef(OBO + "IAO_0000115")
    alternative = URIRef(OBO + "IAO_0000118")
    kinds = (("class", OWL.Class), ("individual", OWL.NamedIndividual),
             ("object_property", OWL.ObjectProperty),
             ("data_property", OWL.DatatypeProperty),
             ("annotation_property", OWL.AnnotationProperty))
    out: dict = {}
    for kind, rdf_type in kinds:
        for subject in graph.subjects(RDF.type, rdf_type):
            if not isinstance(subject, URIRef):
                continue
            key = short(subject)
            label = graph.value(subject, RDFS.label)
            if label is None or key in out:
                # First kind wins, and the order above is deliberate: a term
                # typed both owl:Class and something else is a class here.
                continue
            foreign = sorted(str(a) for a in graph.objects(subject, alternative)
                             if getattr(a, "language", None) == "de")
            if not foreign:
                # The closure labels most alternatives without a language tag.
                # Taking them all is worse than taking none: the English
                # synonym would be offered to the model as a German spelling.
                foreign = sorted(
                    str(a) for a in graph.objects(subject, alternative)
                    if getattr(a, "language", None) is None)
            meaning = graph.value(subject, definition)
            parent = (RDFS.subPropertyOf if kind.endswith("property")
                      else RDFS.subClassOf)
            out[key] = {
                "kind": kind,
                "label": str(label),
                "alt_labels": foreign,
                "definition": str(meaning) if meaning else None,
                "parents": sorted(short(p) for p in
                                  graph.objects(subject, parent)
                                  if isinstance(p, URIRef)),
                "deprecated": bool(graph.value(subject, OWL.deprecated)),
            }
    return out


def closures(graph, sets: dict) -> dict:
    """Each set of `sets` as a sorted list of identifiers.

    `sets` is the profile's: {name: ("class"|"individual", root IRI)}. Which
    roots a profile's lists draw from is the one thing about a vocabulary that
    is genuinely per profile, so it stays there.
    """
    from rdflib import OWL, RDF, RDFS, URIRef
    children = collections.defaultdict(set)
    for child, parent in graph.subject_objects(RDFS.subClassOf):
        if isinstance(child, URIRef) and isinstance(parent, URIRef):
            children[str(parent)].add(str(child))
    # An equivalentClass intersection is how OEO says "a biogenic solid fuel
    # is a solid fuel AND biogenic". Its conjuncts are parents in every sense
    # that matters here, and without them thirteen carriers the schema already
    # accepts fall outside their own root.
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
    for name, (kind, root) in sets.items():
        if kind == "class":
            members = under(root)
        else:
            members = {str(x) for x in graph.subjects(RDF.type, URIRef(root))}
        out[name] = sorted(short(m) for m in members)
    return out


def spec_terms(spec_raw: dict) -> dict:
    """Every ontology identifier the spec names, and where it names it.

    The whole spec, at any depth, in keys as well as values: a vocabulary
    writes its terms as KEYS, a `kg` block writes them as values, and one
    profile spells them bare while the other spells them as IRIs. The version
    this replaces walked three named places, matched bare identifiers only,
    and reported zero identifiers for the scenarios spec -- a checker that
    checks nothing reads exactly like a spec with nothing wrong.
    """
    found: dict = collections.defaultdict(list)

    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                name = identifier(key)
                if name:
                    found[name].append(where)
                walk(value, f"{where}.{key}" if not name else where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)
        else:
            name = identifier(node)
            if name:
                found[name].append(where)

    for parameter in spec_raw.get("parameters", []):
        walk(parameter, str(parameter.get("uri")))
    return {k: v for k, v in sorted(found.items())}


def build(closure: Path, sets: dict, spec_raw: dict, *,
          extra: Optional[list] = None, base: str = "") -> dict:
    """The vocabulary snapshot, from the ontology files as they stand.

    `extra` are further files parsed into the same graph (MHPO, say); `base`
    is the IRI prefix whose ontology header carries the version to pin.
    """
    from rdflib import OWL, RDF
    paths = [closure] + list(extra or [])
    graph = read(paths)
    reachable = closures(graph, sets)
    # Only the terms a list can draw from, plus everything the spec already
    # names and the parents of both. The closure holds thousands of labelled
    # terms and a profile reaches a few hundred; carrying the rest would be
    # half a megabyte of ontology nobody here reads, checked into a repository
    # that is not the ontology's.
    wanted = {uri for members in reachable.values() for uri in members}
    wanted |= set(spec_terms(spec_raw))
    full = index(graph)
    wanted |= {parent for uri in wanted
               for parent in (full.get(uri) or {}).get("parents", ())}
    terms = {uri: full[uri] for uri in sorted(wanted) if uri in full}
    version = None
    for ontology in graph.subjects(RDF.type, OWL.Ontology):
        if not base or str(ontology).startswith(base):
            version = graph.value(ontology, OWL.versionIRI) or version
    pin = {
        "oeo_version_iri": str(version) if version else None,
        "oeo_sha256": hashlib.sha256(closure.read_bytes()).hexdigest(),
        "oeo_file": closure.name,
        # Which identifier families this snapshot can speak for at all. A spec
        # may name a term of an ontology no file here covers -- kwp names
        # three MHPO classes and MHPO ships only as OWL functional syntax,
        # which rdflib does not read -- and reporting those as "not in the
        # pinned ontology" would be a false error that teaches everyone to
        # ignore the real ones.
        "families": sorted({name.split("_")[0] for name in full
                            if identifier(name)}),
    }
    for path in (extra or []):
        pin[f"{Path(path).stem}_sha256"] = hashlib.sha256(
            Path(path).read_bytes()).hexdigest()
    return {"pin": pin, "sets": reachable, "terms": terms}


def serialize(snapshot: dict) -> str:
    return json.dumps(snapshot, ensure_ascii=False, indent=1,
                      sort_keys=True) + "\n"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def uncovered(spec_raw: dict, snapshot: dict) -> dict:
    """{family: [where, ...]} for identifiers no file of this snapshot covers.

    Not a problem and not silence either. It is the honest third answer to
    "does the ontology have this": the snapshot cannot say.
    """
    families = set(snapshot.get("pin", {}).get("families") or ())
    out: dict = collections.defaultdict(list)
    for name, wheres in spec_terms(spec_raw).items():
        family = name.split("_")[0]
        if families and family not in families:
            out[family].extend(wheres)
    return dict(out)


def term_problems(spec_raw: dict, snapshot: dict) -> list:
    """The two complaints every profile shares: absent, and deprecated.

    Silent about a family the snapshot does not cover; `uncovered` reports
    those, so a term nobody can check is a named gap rather than an error.
    """
    terms = snapshot["terms"]
    families = set(snapshot.get("pin", {}).get("families") or ())
    problems: list = []
    for uri, wheres in spec_terms(spec_raw).items():
        if families and uri.split("_")[0] not in families:
            continue
        term = terms.get(uri)
        if term is None:
            problems.append(f"{wheres[0]}: {uri} is not in the pinned ontology")
        elif term["deprecated"]:
            problems.append(f"{wheres[0]}: {uri} is deprecated")
    return problems


def kind_problems(spec_raw: dict, snapshot: dict) -> list:
    """A `kg` block's predicate that the ontology does not call a property.

    The block says what a coordinate becomes in the graph, and a class written
    where a predicate belongs emits Turtle that parses and asserts nonsense.
    Only checkable since the index carries the kind.
    """
    terms = snapshot["terms"]
    problems: list = []

    def walk(node, where):
        if isinstance(node, dict):
            name = identifier(node.get("predicate"))
            if name:
                term = terms.get(name)
                if term and not term["kind"].endswith("property"):
                    problems.append(f"{where}: {name} ({term['label']}) is a "
                                    f"{term['kind']}, not a property")
            for key, value in node.items():
                walk(value, f"{where}.{key}")
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for parameter in spec_raw.get("parameters", []):
        walk(parameter.get("kg"), f"{parameter.get('uri')}.kg")
        for axis, block in (parameter.get("axes") or {}).items():
            walk(block.get("kg"), f"{parameter.get('uri')}.{axis}.kg")
    return problems


def set_problems(spec_raw: dict, snapshot: dict, rules: dict) -> list:
    """An axis option the ontology does not put under that axis' root.

    `rules` is {axis name: set name} and is the profile's: which of its axes
    draws from which root is a statement about that profile's spec.
    """
    terms, sets = snapshot["terms"], snapshot["sets"]
    problems: list = []
    for parameter in spec_raw.get("parameters", []):
        axes = parameter.get("axes") or {}
        for axis_name, set_name in rules.items():
            axis = axes.get(axis_name) or {}
            allowed = set(sets.get(set_name) or ())
            for uri in (axis.get("vocabulary") or {}):
                name = identifier(uri)
                if name is None or name in allowed:
                    continue
                if name in terms:
                    problems.append(
                        f"{parameter.get('uri')}.{axis_name}: {name} "
                        f"({terms[name]['label']}) is not a {set_name}")
    return problems


def foreign_labels(spec_raw: dict, snapshot: dict) -> list:
    """Options whose first label is not one the ontology gives the term.

    Not an error. The first label is what the model is offered and it is meant
    to be the word the corpus writes: a heat plan says "Private Haushalte",
    OEO says "household sector", and offering the ontology's word would ask
    the model to translate before it reads.

    It is worth listing all the same, because the same shape hides a real
    defect: an option labelled with a specific word whose class is a generic
    one. "Klaerschlamm" offered as OEO_00000439 waste fuel does not mean the
    model chose badly -- it means every sewage-sludge reading in the corpus
    becomes a generic waste fuel and nobody looking at the graph can tell.
    """
    terms = snapshot["terms"]
    out: list = []
    for parameter in spec_raw.get("parameters", []):
        lists = [(name, (axis.get("vocabulary") or {}))
                 for name, axis in (parameter.get("axes") or {}).items()]
        lists.append(("value", parameter.get("vocabulary") or {}))
        for name, vocabulary in lists:
            for uri, entry in vocabulary.items():
                key = identifier(uri)
                term = terms.get(key) if key else None
                # Either spec form: a list whose first item is the offered
                # label, or an object that names it.
                offered = (entry.get("label") if isinstance(entry, dict)
                           else (entry or [None])[0])
                if term is None or not offered:
                    continue
                known = {term["label"].casefold()}
                known |= {a.casefold() for a in term["alt_labels"]}
                if offered.casefold() not in known:
                    out.append((f"{parameter.get('uri')}.{name}", key,
                                offered, term["label"]))
    return out
