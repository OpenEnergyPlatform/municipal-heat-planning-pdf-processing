"""
ontology.py: Reads the ontology a spec is written against once and
pins it in a snapshot.

Every closed list a profile offers names terms of an ontology, and a
spec that is never checked against one can come to describe a graph
that does not exist. This module reads an ontology file and writes a
snapshot: per term its label, its foreign alternative labels, its
definition, its parents, whether it is deprecated, and which kind of
thing it is (a class, an individual or a property). It also writes
the sets a list may draw from, and a pin (the version IRI and the
file's own sha256), so the question of which ontology a spec is
written against has an answer.

The module is profile free by design. What a profile keeps is its
own: which roots its sets draw from, where its closure lives, and the
rules that concern its own axes. The builder, the index, the
identifier walk, and the two checks every profile shares (a term the
ontology does not have, a term the ontology has deprecated) are the
same question in every profile, so they live here.

The kind recorded for each term matters beyond bookkeeping. The arrows
of a drawing name predicates, and a predicate is an owl:ObjectProperty; an
index built over classes and individuals alone would report every
predicate as missing. That is why the scenarios profile had no
snapshot before this module existed: its seventeen identifiers are
mostly predicates.

rdflib is imported inside the functions that need it. The checks run
against the checked-in snapshot and need neither an ontology file nor
rdflib, so they run where rdflib is not installed.

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
XSD = "http://www.w3.org/2001/XMLSchema#"

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


def named(node) -> str:
    """`short`, except a datatype keeps the prefix that tells it apart.

    A property's range is a class or a datatype and the two are checked
    differently: `dateTime` alone would read like an ontology term.
    """
    text = str(node)
    if text.startswith(XSD):
        return "xsd:" + text[len(XSD):]
    return short(text)


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


def _class_names(graph, node) -> set:
    """The named classes a domain or range axiom allows.

    A union counts as its members: `has uuid` is domained on
    `report or factsheet`, and reading only named nodes would drop the axiom
    entirely and report nothing about a subject that is neither. Anything
    else anonymous -- an intersection, a restriction -- is dropped, because
    guessing at it would report triples that are fine.
    """
    from rdflib import OWL, URIRef
    from rdflib.collection import Collection
    if isinstance(node, URIRef):
        return {named(node)}
    out = set()
    for collection in graph.objects(node, OWL.unionOf):
        for member in Collection(graph, collection):
            if isinstance(member, URIRef):
                out.add(named(member))
    return out


def index(graph, language: str) -> dict:
    """identifier -> {kind, label, alt_labels, definition, parents, deprecated}.

    Properties as well as classes and individuals. Without them a drawing's
    arrows -- which name predicates and nothing else -- read as a list of
    terms the ontology does not have.

    `parents` is what a term is under: a class's superclasses, a property's
    superproperties, and for an individual the classes it is asserted into.

    `language` is the tag of the alternative labels a term carries: the
    language the corpus writes its words in, which the profile says
    (`extraction.ALT_LABEL_LANGUAGE`). The core names none.
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
                             if getattr(a, "language", None) == language)
            if not foreign:
                # The closure labels most alternatives without a language tag.
                # Taking them all is worse than taking none: a synonym of
                # another language would be offered to the model as a spelling
                # of this one.
                foreign = sorted(
                    str(a) for a in graph.objects(subject, alternative)
                    if getattr(a, "language", None) is None)
            meaning = graph.value(subject, definition)
            if kind == "individual":
                # An individual has no superclass. A predicate's range names
                # a class, and the only thing that holds an individual object
                # to it is the class the ontology asserts it into: read as
                # having no parents, every aggregation type was outside the
                # range `has aggregation type` declares since OEO 2.14.0.
                above = [p for p in graph.objects(subject, RDF.type)
                         if p != OWL.NamedIndividual]
            else:
                above = graph.objects(
                    subject, RDFS.subPropertyOf if kind.endswith("property")
                    else RDFS.subClassOf)
            out[key] = {
                "kind": kind,
                "label": str(label),
                "alt_labels": foreign,
                "definition": str(meaning) if meaning else None,
                "parents": sorted(short(p) for p in above
                                  if isinstance(p, URIRef)),
                "deprecated": bool(graph.value(subject, OWL.deprecated)),
            }
            if kind.endswith("property"):
                # What the ontology says a subject and an object of this
                # predicate ARE. Without them an arrow can name a real
                # property, pass every check here, and still emit a triple
                # that types its own subject into a class it is disjoint
                # from -- which is what three of kwp's edges did.
                # Anonymous unions are dropped rather than guessed at, so an
                # empty list means "nothing to hold this to", never "no
                # subject qualifies".
                for slot, predicate in (("domain", RDFS.domain),
                                        ("range", RDFS.range)):
                    names = set()
                    for node in graph.objects(subject, predicate):
                        names |= _class_names(graph, node)
                    out[key][slot] = sorted(names)
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
    writes its terms as KEYS, an arrow writes them as values, and one
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


def build(closure: Path, sets: dict, spec_raw: dict, *, language: str,
          extra: Optional[list] = None, base: str = "",
          also: tuple = (), drawing: Optional[dict] = None) -> dict:
    """The vocabulary snapshot, from the ontology files as they stand.

    `language` is the tag of the alternative labels the snapshot keeps, the
    profile's to say (see `index`); there is no default, so a caller cannot
    leave it to the core. `extra` are further files parsed into the same
    graph (MHPO, say); `base` is the IRI prefix whose ontology header carries
    the version to pin. `drawing` is the drawing of the profile's graph
    (`graph.json`, `map`): every term it names is carried, as every term the
    spec names is. `also` are identifiers the snapshot has to carry
    although neither names them: the classes a writer's own edges name.
    `edge_problems` asks whether a subject is under a predicate's domain,
    and a subject the snapshot does not carry has no parents to answer
    with.
    """
    from rdflib import OWL, RDF, URIRef
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
    wanted |= set(drawing_terms(drawing))
    wanted |= set(also)
    full = index(graph, language)
    # Grown to a fixpoint over parents, domains and ranges rather than one
    # generation up. `edge_problems` asks whether a subject class is UNDER a
    # predicate's domain, and a chain that stops early answers "no" for a
    # subject that is perfectly fine; the domain class itself is usually named
    # nowhere in the spec, so without this it is not in the file at all.
    frontier = set(wanted)
    while frontier:
        grown = set()
        for uri in frontier:
            term = full.get(uri) or {}
            grown |= set(term.get("parents") or ())
            for slot in ("domain", "range"):
                grown |= {name for name in (term.get(slot) or ())
                          if not name.startswith("xsd:")}
        frontier = grown - wanted
        wanted |= frontier
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
    # Which pairs of these classes cannot share an instance. A domain a
    # subject is merely not under is a wrong triple; a domain the subject is
    # DISJOINT from is an unsatisfiable graph, and the two deserve different
    # words in a report.
    disjoint = sorted({tuple(sorted((short(a), short(b))))
                       for a, b in graph.subject_objects(OWL.disjointWith)
                       if isinstance(a, URIRef) and isinstance(b, URIRef)
                       and short(a) in terms and short(b) in terms})
    return {"pin": pin, "sets": reachable, "terms": terms,
            "disjoint": [list(pair) for pair in disjoint]}


def with_context(graph, context) -> int:
    """Add to *graph* what *context* says about the nodes it only points at.

    *context* is [(subject, predicate, object)] the target graph already
    holds, classes and labels: an rdf:type object is an IRI, any other a
    literal. A node the graph describes itself gets nothing from it, so the
    graph's own statements are what is checked. Returns the triples added.
    """
    from rdflib import Literal, URIRef
    from rdflib.namespace import RDF
    described = set(graph.subjects())
    referenced = {o for o in graph.objects()
                  if isinstance(o, URIRef) and o not in described}
    added = 0
    for s, p, o in context:
        if URIRef(s) in referenced:
            graph.add((URIRef(s), URIRef(p),
                       URIRef(o) if p == str(RDF.type) else Literal(o)))
            added += 1
    return added


def shacl_report(data: Path, shapes: list, context=()) -> dict:
    """A written graph held against SHACL shapes: {conforms, violations, counts, text}.

    The shapes files are parsed into ONE graph first. pyshacl takes repeated
    `-s` flags and silently uses only the last, so a second shapes file would
    otherwise not be consulted at all (the schema repository's validate.py
    was bitten by exactly that). `counts` groups the violations by
    constraint, shape target and path, most frequent first, so a report of
    fifty thousand lines can still be read in the log.

    The graph is held together with *context* (`with_context`): a region or
    a term it references is checked as the target graph holds it, not as a
    bare IRI that has neither class nor label.
    """
    import re
    from pyshacl import validate
    from rdflib import Graph
    shapes_graph = Graph()
    for path in shapes:
        shapes_graph.parse(str(path), format="turtle")
    graph = Graph().parse(str(data), format="turtle")
    added = with_context(graph, context)
    conforms, _results, text = validate(
        graph, shacl_graph=shapes_graph, advanced=True)
    counts: collections.Counter = collections.Counter()
    blocks = text.split("Constraint Violation")[1:]
    for block in blocks:
        component = re.search(r"in (\w+)ConstraintComponent", block)
        path = re.search(r"Result Path: (\S+)", block)
        # The collection segment of an instance IRI (value, heatplan, ...).
        # A blank node or a nested result has none and counts as "?".
        focus = re.search(r"Focus Node: <[^>]*/([^/>]+)/[^/>]*>", block)
        counts[(component.group(1) if component else "?",
                path.group(1) if path else "-",
                focus.group(1) if focus else "?")] += 1
    return {"conforms": bool(conforms), "violations": len(blocks),
            "counts": counts.most_common(), "text": text, "context": added}


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


def drawing_identifier(value) -> Optional[str]:
    """`identifier`, also of a prefixed name as a drawing writes it
    (`oeo:OEO_00390096`, `mhpo:MHPO_00020003`)."""
    if isinstance(value, str) and "://" not in value and ":" in value:
        value = value.split(":", 1)[1]
    return identifier(value)


def _local(name) -> str:
    """A prefixed name's local part, as an edge names its predicate."""
    text = str(name)
    if "://" not in text and ":" in text:
        return text.split(":", 1)[1]
    return text


def drawing_term_problems(drawing: dict, snapshot: dict,
                          noted_elsewhere=()) -> list:
    """`term_problems` for the identifiers a drawing names
    (`drawing_terms`): absent, and deprecated. *noted_elsewhere* are the
    identifiers a profile holds to the pin in a report of their own (the
    terms a schema prescribes); they are not reported twice."""
    terms = snapshot["terms"]
    families = set(snapshot.get("pin", {}).get("families") or ())
    skipped = set(noted_elsewhere)
    problems: list = []
    for uri, wheres in drawing_terms(drawing).items():
        if families and uri.split("_")[0] not in families:
            continue
        if uri in skipped:
            continue
        term = terms.get(uri)
        if term is None:
            problems.append(f"{wheres[0]}: {uri} is not in the pinned "
                            f"ontology")
        elif term["deprecated"]:
            problems.append(f"{wheres[0]}: {uri} is deprecated")
    return problems


def kind_problems(drawing: dict, snapshot: dict) -> list:
    """A property of the drawing that the ontology does not call a property.

    An arrow says what a reading becomes in the graph, and a class written
    where a property belongs emits Turtle that parses and asserts nonsense.
    Only checkable since the index carries the kind.
    """
    terms = snapshot["terms"]
    problems: list = []
    for number, arrow in enumerate((drawing or {}).get("arrows") or (), 1):
        if not isinstance(arrow, dict):
            continue
        name = drawing_identifier(arrow.get("property"))
        term = terms.get(name) if name else None
        if term and not term["kind"].endswith("property"):
            problems.append(f"arrow {number} ({arrow.get('from')} -> "
                            f"{arrow.get('to')}): {name} ({term['label']}) "
                            f"is a {term['kind']}, not a property")
    return problems


def drawing_terms(drawing: dict) -> dict:
    """Every ontology identifier a drawing names, and where: the classes of
    its boxes and tables, its properties, and what its bricks are set to."""
    found: dict = collections.defaultdict(list)

    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                name = drawing_identifier(key)
                if name:
                    found[name].append(where)
                walk(value, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)
        else:
            name = drawing_identifier(node)
            if name:
                found[name].append(where)

    for box in (drawing or {}).get("boxes") or ():
        if isinstance(box, dict):
            walk({key: value for key, value in box.items()
                  if key not in ("note", "id")}, f"box {box.get('id')}")
    for number, arrow in enumerate((drawing or {}).get("arrows") or (), 1):
        if isinstance(arrow, dict):
            walk({key: value for key, value in arrow.items()
                  if key not in ("note", "label", "accepted", "from", "to")},
                 f"arrow {number}")
    return {k: v for k, v in sorted(found.items())}


def drawing_edges(drawing: dict, spec_raw: dict, bricks=None) -> list:
    """Every triple shape a drawing writes: {where, subject, predicate,
    object, datatype, accepted}, the subject's class, the predicate, and the
    object's class or the literal's datatype, each as far as the drawing
    says it.

    Derived, never listed: a box that takes its class from a coordinate
    (KWP's value) has every class that coordinate offers as a subject; an
    arrow whose brick writes an answer has every entry of the coordinate's
    list as an object (`Brick.writes`); an arrow from one box to another has
    the classes of both. An arrow may say why it is written against the
    ontology (`accepted`), and the reason travels with it to
    `edge_problems`.
    """
    drawing = drawing or {}
    bricks = bricks or {}
    parameters = {one["uri"]: one for one in spec_raw.get("parameters") or ()
                  if isinstance(one, dict) and one.get("uri")}
    boxes = {box["id"]: box for box in drawing.get("boxes") or ()
             if isinstance(box, dict) and box.get("id")}

    def fields_of(box: dict, seen=()) -> list:
        of = box.get("of")
        names = [of] if isinstance(of, str) else [
            one for one in of if isinstance(one, str)] \
            if isinstance(of, list) else []
        out = [one for one in names if one in parameters]
        among = box.get("among")
        if among in boxes and among not in seen:
            out += [one for one in fields_of(boxes[among], seen + (among,))
                    if one not in out]
        return out

    def listed(owner: dict) -> list:
        return [drawing_identifier(key) for key in (owner.get("vocabulary") or {})
                if not str(key).startswith("out:") and drawing_identifier(key)]

    def subjects(box: dict, field=None) -> list:
        if box.get("class"):
            return [drawing_identifier(box["class"])]
        out: list = []
        coordinate = ((box.get("class_brick") or {}).get("settings")
                      or {}).get("coordinate")
        if coordinate:
            for uri in ([field] if field else fields_of(box)):
                axis = (parameters[uri].get("axes") or {}).get(coordinate)
                out += [one for one in listed(axis or {}) if one not in out]
        for entry in (box.get("table") or {}).values():
            if isinstance(entry, dict) and drawing_identifier(entry.get("class")):
                out.append(drawing_identifier(entry["class"]))
        for klass in (box.get("class_by") or {}).values():
            if drawing_identifier(klass) and drawing_identifier(klass) not in out:
                out.append(drawing_identifier(klass))
        return out or [None]

    out: list = []

    def add(where, subject, arrow, object_=None, datatype=None):
        out.append({"where": where, "subject": subject,
                    "predicate": _local(arrow["property"]), "object": object_,
                    "datatype": datatype,
                    "accepted": arrow.get("accepted")})

    for arrow in drawing.get("arrows") or ():
        if not isinstance(arrow, dict) or arrow.get("to") not in boxes:
            continue
        source, target = arrow.get("from"), arrow["to"]
        subject_box = boxes[source] if source in boxes else boxes[target]
        where = f"{subject_box['id']}.{source} {arrow.get('property')}"
        if source in boxes and source != target:
            for subject in subjects(subject_box):
                for object_ in subjects(boxes[target]):
                    add(where, subject, arrow, object_)
            continue
        brick = bricks.get(arrow.get("brick") or "text")
        writes = getattr(brick, "writes", "") or ""
        settings = arrow.get("settings") or {}
        datatype = writes if writes.startswith("xsd:") else (
            settings.get("datatype") if writes == "setting:datatype"
            else None)
        if source in boxes:
            for subject in subjects(subject_box):
                add(where, subject, arrow, None, datatype)
            continue
        fields = [source] if source in parameters else [
            uri for uri in fields_of(subject_box)
            if source in (parameters[uri].get("axes") or {})
            or source in parameters[uri]
            or source in ("value", "value_target", "value_raw")]
        for uri in fields or [None]:
            parameter = parameters.get(uri) or {}
            objects: list = [None]
            if writes == "answers":
                objects = listed((parameter.get("axes") or {}).get(source)
                                 or {}) or [None]
                total = drawing_identifier(settings.get("total_class"))
                if total and total not in objects:
                    objects.append(total)
            elif writes == "entries":
                objects = listed(parameter) or [None]
            elif writes.startswith("key:"):
                objects = [drawing_identifier(parameter.get(writes[4:]))]
            for subject in subjects(subject_box, uri):
                for object_ in objects:
                    add(where, subject, arrow, object_, datatype)
    for box in boxes.values():
        if box.get("uuid"):
            for subject in subjects(box):
                out.append({"where": f"{box['id']}.uuid", "subject": subject,
                            "predicate": _local(box["uuid"]), "object": None,
                            "datatype": "xsd:string", "accepted": None})
    return out


def ancestors(name: str, snapshot: dict) -> set:
    """Every term above this one in the snapshot, transitively."""
    terms = snapshot["terms"]
    seen, stack = set(), [name]
    while stack:
        for parent in (terms.get(stack.pop()) or {}).get("parents") or ():
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def _is_under(name: str, root: str, snapshot: dict) -> bool:
    return name == root or root in ancestors(name, snapshot)


def _unsatisfiable(one: str, other: str, snapshot: dict) -> bool:
    """Can these two classes share an instance at all?"""
    here = {one} | ancestors(one, snapshot)
    there = {other} | ancestors(other, snapshot)
    for pair in snapshot.get("disjoint") or ():
        first, second = pair
        if (first in here and second in there) or (
                second in here and first in there):
            return True
    return False


def edge_problems(edges, snapshot: dict) -> list:
    """Emitted triples the pinned ontology contradicts.

    `edges` is what a serializer writes, as {where, subject, predicate,
    object, datatype} -- the subject's asserted class, the predicate, and
    either the object's class or the literal's datatype. Every field but the
    predicate may be absent, and an absent field is not checked.

    Why this is worth its own check. `term_problems` asks whether a predicate
    EXISTS and `kind_problems` asks whether it is a property; neither asks the
    only question a reader of the graph cares about, which is whether the
    triple is one the ontology allows. `rdfs:domain` is not a constraint a
    reasoner refuses -- it TYPES the subject -- so a wrong domain does not
    fail loudly anywhere, it silently asserts that our value nodes are
    something they are not. Three kwp edges named a domain (`study`) that is
    an occurrent while every value is a continuant, and the closure asserts
    those two disjoint: the whole graph was unsatisfiable and every check we
    had passed.

    Silent about a family the snapshot does not cover, like every check here.
    """
    families = set(snapshot.get("pin", {}).get("families") or ())
    terms = snapshot["terms"]

    def covered(name):
        return not families or name.split("_")[0] in families

    problems: list = []

    def report(text):
        # One shape, one line. A domain complaint does not depend on the
        # object, so an axis with forty options would otherwise print it
        # forty times and bury everything else.
        if text not in problems:
            problems.append(text)

    for edge in edges:
        # An edge may say why it is written anyway. The reason travels with
        # the declaration rather than in a list somewhere else, so it is read
        # by whoever reads the edge, and a SECOND divergence cannot hide
        # behind the first one: it is a new line here with no reason on it.
        if edge.get("accepted"):
            continue
        where = edge.get("where") or "?"
        name = identifier(edge.get("predicate"))
        term = terms.get(name) if name else None
        if term is None:
            continue
        label = term.get("label") or name
        subject = identifier(edge.get("subject"))
        domains = [d for d in (term.get("domain") or ()) if covered(d)]
        if subject and covered(subject) and domains:
            if not any(_is_under(subject, d, snapshot) for d in domains):
                spelled = ", ".join(
                    f"{d} ({(terms.get(d) or {}).get('label', d)})"
                    for d in domains)
                verdict = ("and the two are disjoint, so nothing can be both"
                           if any(_unsatisfiable(subject, d, snapshot)
                                  for d in domains)
                           else "so the triple types it into one")
                report(
                    f"{where}: {name} ({label}) has domain {spelled} and the "
                    f"subject is {subject} "
                    f"({(terms.get(subject) or {}).get('label', subject)}), "
                    f"{verdict}")
        ranges = term.get("range") or ()
        classes = [r for r in ranges if not r.startswith("xsd:")]
        literals = [r for r in ranges if r.startswith("xsd:")]
        obj = identifier(edge.get("object"))
        if obj and covered(obj) and classes:
            if not any(_is_under(obj, r, snapshot)
                       for r in classes if covered(r)):
                report(
                    f"{where}: {name} ({label}) has range "
                    f"{', '.join(classes)} and the object is {obj}")
        datatype = edge.get("datatype")
        if datatype and literals and datatype not in literals:
            report(
                f"{where}: {name} ({label}) has range {', '.join(literals)} "
                f"and the literal is written {datatype}")
        if datatype and classes and not literals:
            report(
                f"{where}: {name} ({label}) has range {', '.join(classes)}, "
                f"a class, and a {datatype} literal is written")
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


def _listed(spec_raw: dict):
    """(where, uri, entry) for every entry of every closed list of the spec.

    The lists of the axes and the list of a parameter's own value, where
    `where` is "<parameter>.<axis>" or "<parameter>.value".
    """
    for parameter in spec_raw.get("parameters", []):
        lists = [(name, (axis.get("vocabulary") or {}))
                 for name, axis in (parameter.get("axes") or {}).items()]
        lists.append(("value", parameter.get("vocabulary") or {}))
        for name, vocabulary in lists:
            for uri, entry in vocabulary.items():
                yield f"{parameter.get('uri')}.{name}", uri, entry


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

    This is also the note on a label that differs from the pin's: an entry is
    named when its first label is neither the pin's label nor one of the pin's
    alternative labels. A German word the pin records as an alternative label
    is not named, and that keeps kwp's corpus words, which the pin knows,
    from being noise. `definition_differences` leaves labels to this.
    """
    terms = snapshot["terms"]
    out: list = []
    for where, uri, entry in _listed(spec_raw):
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
            out.append((where, key, offered, term["label"]))
    return out


# The two ways a definition of the spec differs from the pin's.
REWRITTEN = "rewritten"       # both have one and the words are not the same
PIN_ONLY = "pin_only"         # the pin defines the class, the spec does not


def definition_differences(spec_raw: dict, snapshot: dict) -> list:
    """(where, class, kind, spec text, pin text), one per class and kind.

    What the model reads of a class stands in the spec, the pin is the
    yardstick the spec is held to, so a refresh that moves a definition moves
    nothing the model is asked until somebody edits the spec. This says where
    the two have drifted apart and decides nothing:

      REWRITTEN  the spec has a definition and the pin's words are others.
      PIN_ONLY   the pin defines the class and the spec says nothing of it.

    A definition only the spec has is the author's own words and is not a
    difference to anything. Words are compared with their white space
    folded, so a line break is no rewrite. A class that is no term of the pin
    (the profile's own "out:" entries, a region) has nothing to be held to.
    Labels are not compared here: `foreign_labels` already names every entry
    whose first label is neither the pin's nor one of its alternative labels.
    """
    terms = snapshot["terms"]
    out: list = []
    seen: set = set()
    for where, uri, entry in _listed(spec_raw):
        key = identifier(uri)
        term = terms.get(key) if key else None
        if term is None:
            continue
        theirs = " ".join(str(term.get("definition") or "").split())
        ours = " ".join(str((entry.get("definition")
                             if isinstance(entry, dict) else "") or "")
                        .split())
        if not theirs or ours == theirs:
            continue
        kind = REWRITTEN if ours else PIN_ONLY
        if (key, kind) in seen:
            continue
        seen.add((key, kind))
        out.append((where, key, kind, ours, theirs))
    return out


def definition_note(difference: tuple) -> str:
    """The line a refresh prints for one entry of `definition_differences`."""
    where, uri, kind, ours, theirs = difference

    def shown(text: str, limit: int = 110) -> str:
        return repr(text if len(text) <= limit else text[:limit - 3] + "...")

    if kind == PIN_ONLY:
        return (f"  note {where}: the pin defines {uri} as {shown(theirs)} "
                f"and the spec does not")
    return (f"  note {where}: the spec defines {uri} as {shown(ours)}, the "
            f"pin as {shown(theirs)}")
